"""Train pre-game LightGBM regressors, blowout classifier, quantile margins, calibration."""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import lightgbm as lgb
import numpy as np
import pandas as pd

from gametime.pregame.augment import augment_team_games
from gametime.pregame.calibration import (
    _band_metrics,
    fit_margin_band_calibration,
    fit_margin_calibration,
    save_band_calibration,
    save_calibration,
)
from gametime.pregame.constants import (
    DEFAULT_BLOWOUT_MARGIN_PTS,
    TARGET_BLOWOUT,
    TARGET_MARGIN,
    TARGET_MARGIN_P10,
    TARGET_MARGIN_P90,
    TARGET_TOTAL,
)
from gametime.pregame.elo import EloParams, fit_elo, fit_off_def_elo, save_offdef_state, save_state
from gametime.pregame.features import FEATURE_COLUMNS, build_training_table
from gametime.pregame.team_games import build_team_games


def _lgb_regression_params() -> dict[str, Any]:
    return {
        "objective": "regression",
        "metric": "mae",
        "verbosity": -1,
        "learning_rate": 0.05,
        "num_leaves": 31,
        "min_data_in_leaf": 30,
        "feature_fraction": 0.9,
        "bagging_fraction": 0.8,
        "bagging_freq": 1,
    }


def _lgb_binary_params() -> dict[str, Any]:
    return {
        "objective": "binary",
        "metric": "binary_logloss",
        "verbosity": -1,
        "learning_rate": 0.05,
        "num_leaves": 31,
        "min_data_in_leaf": 20,
        "feature_fraction": 0.9,
        "bagging_fraction": 0.8,
        "bagging_freq": 1,
    }


def _lgb_quantile_params(alpha: float) -> dict[str, Any]:
    return {
        "objective": "quantile",
        "alpha": alpha,
        "metric": "quantile",
        "verbosity": -1,
        "learning_rate": 0.05,
        "num_leaves": 31,
        "min_data_in_leaf": 30,
        "feature_fraction": 0.9,
        "bagging_fraction": 0.8,
        "bagging_freq": 1,
    }


def _split_table(
    table: pd.DataFrame,
    *,
    train_seasons: list[int],
    train_seasontypes: list[str],
    val_season: int,
    val_seasontype: str,
    test_seasons: list[int],
    test_seasontype: str,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    train = table[
        table["season_start_year"].isin(train_seasons) & table["seasontype"].isin(train_seasontypes)
    ]
    val = table[
        (table["season_start_year"] == val_season) & (table["seasontype"] == val_seasontype)
    ]
    test = table[
        table["season_start_year"].isin(test_seasons) & (table["seasontype"] == test_seasontype)
    ]
    return train, val, test


def _metrics(pred_total: np.ndarray, pred_margin: np.ndarray, df: pd.DataFrame) -> dict[str, float]:
    if len(df) == 0:
        return {"n": 0}
    total_mae = float(np.mean(np.abs(pred_total - df[TARGET_TOTAL].to_numpy())))
    margin_mae = float(np.mean(np.abs(pred_margin - df[TARGET_MARGIN].to_numpy())))
    pred_home_wins = pred_margin > 0
    actual_home_wins = df[TARGET_MARGIN].to_numpy() > 0
    winner_acc = float(np.mean(pred_home_wins == actual_home_wins))
    return {
        "n": int(len(df)),
        "total_mae": total_mae,
        "margin_mae": margin_mae,
        "winner_accuracy": winner_acc,
    }


def _blowout_label(margin: pd.Series, threshold: float) -> pd.Series:
    return (margin.abs() >= threshold).astype(int)


def _train_booster(
    train_df: pd.DataFrame,
    val_df: pd.DataFrame,
    *,
    label: str,
    params: dict[str, Any],
    model_path: Path,
    init_model: lgb.Booster | None = None,
    num_boost_round: int = 1000,
) -> lgb.Booster:
    train_set = lgb.Dataset(train_df[FEATURE_COLUMNS], label=train_df[label])
    val_set = lgb.Dataset(val_df[FEATURE_COLUMNS], label=val_df[label], reference=train_set)
    booster = lgb.train(
        params,
        train_set,
        num_boost_round=num_boost_round,
        valid_sets=[val_set],
        init_model=init_model,
        callbacks=[lgb.early_stopping(50, verbose=False)],
    )
    booster.save_model(str(model_path))
    return booster


def train_pregame(
    *,
    root: Path,
    raw_dir: Path,
    snapshots_path: Path,
    model_dir: Path,
    seasons: list[int],
    train_seasons: list[int],
    train_seasontypes: list[str],
    val_season: int,
    val_seasontype: str,
    test_seasons: list[int],
    test_seasontype: str,
    form_window: int = 10,
    elo_params: EloParams | None = None,
    report_path: Path | None = None,
    team_games_out: Path | None = None,
    v3_archive_seasons: list[int] | None = None,
    pbp_source: str = "nbastats",
    league=None,
    blowout_margin_pts: float = DEFAULT_BLOWOUT_MARGIN_PTS,
    po_finetune_rounds: int = 75,
    include_po_in_train: bool = True,
    calibration_blowout_gate: float = 0.35,
    band_target_coverage: float = 0.80,
) -> dict[str, Any]:
    model_dir = Path(model_dir)
    model_dir.mkdir(parents=True, exist_ok=True)

    print(f"[pregame] Building team_games from {raw_dir} (seasons={seasons})…")
    team_games = build_team_games(
        raw_dir=raw_dir,
        snapshots_path=snapshots_path,
        seasons=seasons,
        seasontype="both",
        pbp_source=pbp_source,
        v3_archive_seasons=v3_archive_seasons,
        league=league,
    )
    processed_dir = snapshots_path.parent
    print("[pregame] Attaching game dates and Q4 pace…")
    team_games = augment_team_games(
        team_games,
        raw_dir=raw_dir,
        processed_dir=processed_dir,
        seasons=seasons,
        v3_archive_seasons=v3_archive_seasons,
    )
    if team_games_out:
        team_games_out.parent.mkdir(parents=True, exist_ok=True)
        team_games.to_parquet(team_games_out, index=False)
        print(f"[pregame] Wrote {team_games_out} ({len(team_games):,} rows)")

    print("[pregame] Fitting Elo across all games…")
    games_elo, elo_state = fit_elo(team_games, params=elo_params)
    print("[pregame] Fitting offensive/defensive Elo…")
    games_offdef, offdef_state = fit_off_def_elo(team_games, params=elo_params)
    off_cols = [
        "game_id",
        "home_off_elo_pre",
        "away_off_elo_pre",
        "home_def_elo_pre",
        "away_def_elo_pre",
    ]
    games = games_elo.merge(games_offdef[off_cols], on="game_id", how="left")

    print(f"[pregame] Building training table (form_window={form_window})…")
    table = build_training_table(games, team_games, window=form_window)
    table[TARGET_BLOWOUT] = _blowout_label(table[TARGET_MARGIN], blowout_margin_pts)

    train_df, val_df, test_df = _split_table(
        table,
        train_seasons=train_seasons,
        train_seasontypes=train_seasontypes,
        val_season=val_season,
        val_seasontype=val_seasontype,
        test_seasons=test_seasons,
        test_seasontype=test_seasontype,
    )
    if len(train_df) == 0:
        raise ValueError("Pre-game training set is empty; check raw_dir and config seasons.")
    if len(val_df) == 0:
        print(f"[pregame] Validation set empty for {val_season}/{val_seasontype}; "
              "using last 15% of train as fallback.")
        cut = int(len(train_df) * 0.85)
        train_df, val_df = train_df.iloc[:cut], train_df.iloc[cut:]

    if include_po_in_train:
        po_extra = table[
            (table["seasontype"] == "po")
            & table["season_start_year"].isin(train_seasons)
        ]
        if len(po_extra):
            train_df = pd.concat([train_df, po_extra], ignore_index=True).drop_duplicates(
                "game_id", keep="first"
            )
            print(f"[pregame] Added {len(po_extra)} historical PO games to train → {len(train_df)} rows")

    print(f"[pregame] sizes: train={len(train_df)} val={len(val_df)} test={len(test_df)}")

    boosters: dict[str, lgb.Booster] = {}
    for target in (TARGET_TOTAL, TARGET_MARGIN):
        print(f"[pregame] Training {target}…")
        boosters[target] = _train_booster(
            train_df,
            val_df,
            label=target,
            params=_lgb_regression_params(),
            model_path=model_dir / f"{target}.txt",
        )

    po_history = table[
        (table["seasontype"] == "po")
        & table["season_start_year"].isin(list(train_seasons) + [val_season])
    ]
    po_finetune_train_n = 0
    po_finetune_val_n = 0
    po_train = pd.DataFrame()
    po_val = pd.DataFrame()

    print(f"[pregame] Training blowout classifier (|margin|>={blowout_margin_pts})…")
    boosters[TARGET_BLOWOUT] = _train_booster(
        train_df,
        val_df,
        label=TARGET_BLOWOUT,
        params=_lgb_binary_params(),
        model_path=model_dir / f"{TARGET_BLOWOUT}.txt",
    )

    for alpha, name in ((0.1, TARGET_MARGIN_P10), (0.9, TARGET_MARGIN_P90)):
        print(f"[pregame] Training margin quantile alpha={alpha}…")
        boosters[name] = _train_booster(
            train_df,
            val_df,
            label=TARGET_MARGIN,
            params=_lgb_quantile_params(alpha),
            model_path=model_dir / f"{name}.txt",
        )

    if po_finetune_rounds > 0 and len(po_history) >= 40:
        print(
            f"[pregame] PO fine-tune on {len(po_history)} historical playoff games "
            f"(seasons {sorted(po_history['season_start_year'].unique().tolist())})…"
        )
        po_val = po_history.iloc[int(len(po_history) * 0.85) :]
        po_train = po_history.iloc[: int(len(po_history) * 0.85)]
        if len(po_val) == 0:
            po_train, po_val = po_history, po_history.iloc[: max(1, len(po_history) // 5)]
        po_finetune_train_n = int(len(po_train))
        po_finetune_val_n = int(len(po_val))
        po_quantiles = (TARGET_MARGIN_P10, TARGET_MARGIN_P90)
        po_regression = (TARGET_MARGIN,)
        for target in po_regression + po_quantiles:
            label = TARGET_MARGIN
            params = (
                _lgb_regression_params()
                if target == TARGET_MARGIN
                else _lgb_quantile_params(0.1 if target == TARGET_MARGIN_P10 else 0.9)
            )
            print(f"[pregame]   PO fine-tune {target}…")
            boosters[target] = _train_booster(
                po_train,
                po_val,
                label=label,
                params=params,
                model_path=model_dir / f"{target}.txt",
                init_model=boosters[target],
                num_boost_round=po_finetune_rounds,
            )

    save_state(elo_state, model_dir / "elo_state.json")
    save_offdef_state(offdef_state, model_dir / "elo_offdef.json")

    pred_total_val = boosters[TARGET_TOTAL].predict(val_df[FEATURE_COLUMNS])
    pred_margin_val = boosters[TARGET_MARGIN].predict(val_df[FEATURE_COLUMNS])
    blowout_prob_val = boosters[TARGET_BLOWOUT].predict(val_df[FEATURE_COLUMNS])

    cal = fit_margin_calibration(
        pred_margin_val,
        val_df[TARGET_MARGIN].to_numpy(),
        blowout_margin_pts=blowout_margin_pts,
        blowout_prob_gate=calibration_blowout_gate,
    )
    save_calibration(cal, model_dir / "calibration.json")

    band_cal = fit_margin_band_calibration(
        boosters[TARGET_MARGIN_P10].predict(po_val[FEATURE_COLUMNS])
        if len(po_val)
        else boosters[TARGET_MARGIN_P10].predict(val_df[FEATURE_COLUMNS]),
        boosters[TARGET_MARGIN_P90].predict(po_val[FEATURE_COLUMNS])
        if len(po_val)
        else boosters[TARGET_MARGIN_P90].predict(val_df[FEATURE_COLUMNS]),
        po_val[TARGET_MARGIN].to_numpy()
        if len(po_val)
        else val_df[TARGET_MARGIN].to_numpy(),
        target_coverage=band_target_coverage,
    )
    save_band_calibration(band_cal, model_dir / "margin_band.json")
    print(
        f"[pregame] Margin band conformal (fit n={band_cal.n_fit_games} PO val): "
        f"scale={band_cal.scale:.3f} coverage {band_cal.coverage_before:.1%}→{band_cal.coverage_after:.1%} "
        f"width {band_cal.mean_width_before:.1f}→{band_cal.mean_width_after:.1f}"
    )

    pred_margin_val_cal = np.array([cal.apply(m, p) for m, p in zip(pred_margin_val, blowout_prob_val)])

    pred_total_train = boosters[TARGET_TOTAL].predict(train_df[FEATURE_COLUMNS])
    pred_margin_train = boosters[TARGET_MARGIN].predict(train_df[FEATURE_COLUMNS])
    pred_total_test = boosters[TARGET_TOTAL].predict(test_df[FEATURE_COLUMNS])
    pred_margin_test = boosters[TARGET_MARGIN].predict(test_df[FEATURE_COLUMNS])
    pred_margin_test_cal = np.array(
        [
            cal.apply(m, p)
            for m, p in zip(
                pred_margin_test,
                boosters[TARGET_BLOWOUT].predict(test_df[FEATURE_COLUMNS]),
            )
        ]
    )

    league_total_mean = float(train_df[TARGET_TOTAL].mean())
    baseline_total_mae_test = (
        float(np.mean(np.abs(test_df[TARGET_TOTAL] - league_total_mean))) if len(test_df) else None
    )
    baseline_home_acc_test = (
        float(np.mean(test_df[TARGET_MARGIN] > 0)) if len(test_df) else None
    )

    blowout_test_actual = _blowout_label(test_df[TARGET_MARGIN], blowout_margin_pts)
    blowout_test_pred = boosters[TARGET_BLOWOUT].predict(test_df[FEATURE_COLUMNS]) >= 0.5
    blowout_acc_test = (
        float(np.mean(blowout_test_pred == blowout_test_actual.astype(bool)))
        if len(test_df)
        else None
    )

    margin_p10_test = boosters[TARGET_MARGIN_P10].predict(test_df[FEATURE_COLUMNS])
    margin_p90_test = boosters[TARGET_MARGIN_P90].predict(test_df[FEATURE_COLUMNS])
    actual_margin_test = test_df[TARGET_MARGIN].to_numpy()
    band_coverage_test, band_width_test = _band_metrics(
        actual_margin_test, margin_p10_test, margin_p90_test
    )
    band_coverage_test = band_coverage_test if len(test_df) else None
    band_width_test = band_width_test if len(test_df) else None

    if len(test_df):
        scaled_low, scaled_high = [], []
        for lo, hi in zip(margin_p10_test, margin_p90_test):
            slo, shi = band_cal.apply(lo, hi)
            scaled_low.append(slo)
            scaled_high.append(shi)
        band_coverage_test_scaled, band_width_test_scaled = _band_metrics(
            actual_margin_test, np.array(scaled_low), np.array(scaled_high)
        )
    else:
        band_coverage_test_scaled = None
        band_width_test_scaled = None

    meta: dict[str, Any] = {
        "features": FEATURE_COLUMNS,
        "targets": [TARGET_TOTAL, TARGET_MARGIN, TARGET_BLOWOUT, TARGET_MARGIN_P10, TARGET_MARGIN_P90],
        "form_window": form_window,
        "elo_params": asdict(elo_params) if elo_params else asdict(EloParams()),
        "blowout_margin_pts": blowout_margin_pts,
        "po_finetune_rounds": po_finetune_rounds,
        "include_po_in_train": include_po_in_train,
        "calibration": cal.to_dict(),
        "margin_band_calibration": band_cal.to_dict(),
        "po_finetune_pool_n": int(len(po_history)),
        "po_finetune_train_n": po_finetune_train_n,
        "po_finetune_val_n": po_finetune_val_n,
        "band_target_coverage": band_target_coverage,
        "n_train_rows": int(len(train_df)),
        "n_val_rows": int(len(val_df)),
        "n_test_rows": int(len(test_df)),
        "train_seasons": train_seasons,
        "train_seasontypes": train_seasontypes,
        "val_season": val_season,
        "val_seasontype": val_seasontype,
        "test_seasons": test_seasons,
        "test_seasontype": test_seasontype,
        "best_iter_total": int(boosters[TARGET_TOTAL].best_iteration or 0),
        "best_iter_margin": int(boosters[TARGET_MARGIN].best_iteration or 0),
        "train_metrics": _metrics(pred_total_train, pred_margin_train, train_df),
        "val_metrics": _metrics(pred_total_val, pred_margin_val, val_df),
        "val_metrics_calibrated_margin": _metrics(
            pred_total_val, pred_margin_val_cal, val_df
        ),
        "test_metrics": _metrics(pred_total_test, pred_margin_test, test_df),
        "test_metrics_calibrated_margin": _metrics(
            pred_total_test, pred_margin_test_cal, test_df
        ),
        "test_blowout_classifier_accuracy": blowout_acc_test,
        "test_margin_band_coverage_p10_p90": band_coverage_test,
        "test_margin_band_mean_width": band_width_test,
        "test_margin_band_coverage_scaled": band_coverage_test_scaled,
        "test_margin_band_mean_width_scaled": band_width_test_scaled,
        "baseline_total_mae_test": baseline_total_mae_test,
        "baseline_home_pick_accuracy_test": baseline_home_acc_test,
        "league_total_mean_train": league_total_mean,
    }
    (model_dir / "meta.json").write_text(json.dumps(meta, indent=2))
    if report_path:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(meta, indent=2))

    print(f"[pregame] Done. Models in {model_dir}.")
    print(f"  val   {meta['val_metrics']}")
    print(f"  val cal margin {meta['val_metrics_calibrated_margin']}")
    print(f"  test  {meta['test_metrics']}")
    print(f"  test cal margin {meta['test_metrics_calibrated_margin']}")
    print(f"  blowout classifier acc (test)={blowout_acc_test}")
    print(f"  margin band coverage p10-p90 (test)={band_coverage_test} width={band_width_test}")
    print(
        f"  margin band scaled (test) coverage={band_coverage_test_scaled} "
        f"width={band_width_test_scaled}"
    )
    return meta
