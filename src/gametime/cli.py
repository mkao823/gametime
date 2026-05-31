from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from gametime.config import load_config, project_root


def download(argv=None):
    from gametime.pipeline import run_download

    p = argparse.ArgumentParser(description="Download historical PBP archives")
    p.add_argument("--config", default="configs/default.yaml")
    args = p.parse_args(argv)
    root = project_root()
    cfg = load_config(root / args.config)
    from gametime.sports import get_sport

    sport = get_sport(cfg)
    print(f"Downloading {sport.name} data…")
    print(f"Downloaded to {run_download(cfg, root)}")


def build_snapshots(argv=None):
    from gametime.pipeline import run_build

    p = argparse.ArgumentParser(description="Build snapshot parquet from raw PBP")
    p.add_argument("--config", default="configs/default.yaml")
    args = p.parse_args(argv)
    root = project_root()
    cfg = load_config(root / args.config)
    print(f"Built {run_build(cfg, root)}")


def train(argv=None):
    from gametime.pipeline import run_train

    p = argparse.ArgumentParser(description="Train in-game LightGBM models")
    p.add_argument("--config", default="configs/default.yaml")
    args = p.parse_args(argv)
    root = project_root()
    cfg = load_config(root / args.config)
    print(f"Models {run_train(cfg, root)}")


def eval_cmd(argv=None):
    from gametime.pipeline import run_eval

    p = argparse.ArgumentParser(description="Held-out eval for in-game models")
    p.add_argument("--config", default="configs/default.yaml")
    args = p.parse_args(argv)
    root = project_root()
    cfg = load_config(root / args.config)
    print(json.dumps(run_eval(cfg, root), indent=2, default=str))


def iteration_report(argv=None):
    from gametime.evaluate.iteration_report import build_iteration_report, write_iteration_report

    p = argparse.ArgumentParser(description="Compare holdout evals across iteration steps")
    p.add_argument("--config", default="configs/default.yaml")
    p.add_argument("--no-live", action="store_true", help="Skip live log analysis")
    args = p.parse_args(argv)

    root = project_root()
    cfg = load_config(root / args.config)
    eval_dir = root / cfg.get("evaluate", {}).get("report_dir", "reports/eval")
    lc = cfg.get("live", {})
    pg = cfg.get("pregame", {})

    report = build_iteration_report(
        eval_dir,
        live_log_dir=None if args.no_live else root / lc.get("log_dir", "data/live_predictions"),
        live_report_dir=eval_dir / "live_iteration",
        pregame_summary_path=root / pg.get("report_path", "reports/eval/pregame_summary.json"),
    )
    out = write_iteration_report(eval_dir, report)
    print(json.dumps(report, indent=2, default=str))
    print(f"\nWrote {out}")


def backtest_signals(argv=None):
    from gametime.pipeline import run_signals

    p = argparse.ArgumentParser(description="Peak/trough signal backtest on held-out test set")
    p.add_argument("--config", default="configs/default.yaml")
    args = p.parse_args(argv)
    root = project_root()
    cfg = load_config(root / args.config)
    print(json.dumps(run_signals(cfg, root), indent=2, default=str))


def analyze_live(argv=None):
    from gametime.evaluate.live_analysis import analyze_live_logs

    p = argparse.ArgumentParser(description="Aggregate phase MAE across logged live games")
    p.add_argument("--config", default="configs/default.yaml")
    args = p.parse_args(argv)
    root = project_root()
    cfg = load_config(root / args.config)
    lc = cfg["live"]
    s = analyze_live_logs(root / lc["log_dir"], root / lc["analysis_dir"])
    print(json.dumps(s, indent=2, default=str))


def analyze_game_cmd(argv=None):
    from gametime.evaluate.game_timeline import analyze_game

    p = argparse.ArgumentParser(description="Per-game live prediction timeline vs actual final")
    p.add_argument("--config", default="configs/default.yaml")
    p.add_argument("--game-id", default=None)
    p.add_argument("--home", default=None, help="Home tricode, e.g. SAS")
    p.add_argument("--away", default=None, help="Away tricode, e.g. OKC")
    p.add_argument("--log-dir", default=None)
    p.add_argument("--report-dir", default=None)
    p.add_argument(
        "--model-type",
        default=None,
        help="Filter polls: naive (pace-only) or lightgbm (default model tag)",
    )
    args = p.parse_args(argv)

    root = project_root()
    cfg = load_config(root / args.config)
    lc = cfg.get("live", {})
    log_dir = Path(args.log_dir) if args.log_dir else root / lc.get("log_dir", "data/live_predictions")
    report_dir = Path(args.report_dir) if args.report_dir else root / lc.get("analysis_dir", "reports/live_analysis")

    summary = analyze_game(
        log_dir,
        report_dir,
        game_id=args.game_id,
        matchup_home=args.home,
        matchup_away=args.away,
        model_type=args.model_type,
    )
    print(json.dumps(summary, indent=2, default=str))
    if summary.get("status") == "ok":
        gid = summary["game_id"]
        stem = f"{gid}_{args.model_type}" if args.model_type else gid
        print(f"\nWrote {report_dir / f'{stem}_timeline.csv'}")
        print(f"Wrote {report_dir / f'{stem}_summary.json'}")


def live(argv=None):
    from gametime.live.inference import poll_until_final
    from gametime.live.prior import LivePrior, resolve_live_prior
    from gametime.live.report_path import resolve_live_json_path

    p = argparse.ArgumentParser()
    p.add_argument("--config", default="configs/default.yaml")
    p.add_argument("--away")
    p.add_argument("--home")
    p.add_argument("--game-id", default=None,
                   help="Optional NBA game_id (used by --auto-prior lookup)")
    p.add_argument("--interval", type=float, default=None)
    p.add_argument("--once", action="store_true")
    p.add_argument("--naive-only", action="store_true")
    p.add_argument(
        "--json-out",
        default=None,
        help="Report path; date inserted if missing (e.g. reports/live_nyk_cle.json -> live_20260525_nyk_cle.json)",
    )
    p.add_argument("--no-json", action="store_true", help="Do not write a JSON snapshot file")
    p.add_argument("--no-log", action="store_true")
    p.add_argument("--auto-prior", action="store_true",
                   help="Force pregame prior (default when live.prior.enabled=true)")
    p.add_argument("--no-prior", action="store_true",
                   help="Disable pregame→live convergence blend")
    p.add_argument("--prior-total", type=float, default=None,
                   help="Manual prior for final total (overrides --auto-prior)")
    p.add_argument("--prior-margin", type=float, default=None,
                   help="Manual prior for final margin (home minus away)")
    p.add_argument("--prior-source", default="manual",
                   help="Tag for the manual prior (only used with --prior-total/--prior-margin)")
    p.add_argument("--prior-decay-pct", type=float, default=None,
                   help="Pct-complete at which prior weight reaches zero (default 0.5 = halftime)")
    p.add_argument("--prior-prefer", default=None,
                   help="Pregame variant for --auto-prior (default from config: pure)")
    p.add_argument("--kalshi", action="store_true",
                   help="Fetch live O/U and spread from Kalshi (public API, no key)")
    p.add_argument("--no-crunch-range", action="store_true",
                   help="Do not show low/high total band in crunch time")
    p.add_argument("--no-pregame", action="store_true",
                   help="Skip pregame feature columns (only if model was trained without them)")
    args = p.parse_args(argv)
    root = project_root()
    cfg = load_config(root / args.config)
    lc = cfg["live"]
    prior_cfg = lc.get("prior", {})

    json_path = None
    if not args.no_json:
        json_path = resolve_live_json_path(
            root,
            json_out=args.json_out,
            home=args.home,
            away=args.away,
            report_dir=lc["json_report_dir"],
        )
        print(f"JSON report: {json_path}")

    prior: Optional["LivePrior"] = None  # noqa: F821
    pg_cfg = cfg.get("pregame", {})
    pregame_predictor = None
    is_playoff = bool(pg_cfg.get("is_playoff_live", True))
    if not args.naive_only and pg_cfg.get("join_in_game", True) and not getattr(args, "no_pregame", False):
        from gametime.pregame.predict import PregamePredictor

        pregame_predictor = PregamePredictor(
            root / pg_cfg.get("model_dir", "models/pregame"),
            root / pg_cfg.get("team_games_path", "data/processed/team_games.parquet"),
            form_window=int(pg_cfg.get("form_window", 10)),
        )

    use_prior = prior_cfg.get("enabled", True) and not args.no_prior
    if args.auto_prior:
        use_prior = True
    if args.naive_only and use_prior:
        print("Warning: --naive-only ignores prior.", file=sys.stderr)
        use_prior = False
    elif use_prior:
        if args.prior_total is not None or args.prior_margin is not None:
            if args.prior_total is None or args.prior_margin is None:
                print("Error: provide both --prior-total and --prior-margin together.",
                      file=sys.stderr)
                sys.exit(2)
            prior = LivePrior(
                total=float(args.prior_total),
                margin=float(args.prior_margin),
                source=args.prior_source,
                decay_pct=float(args.prior_decay_pct or prior_cfg.get("decay_pct", 0.5)),
            )
        else:
            prior = resolve_live_prior(
                log_dir=root / lc["log_dir"],
                game_id=args.game_id,
                home=args.home,
                away=args.away,
                prefer_variant=args.prior_prefer or prior_cfg.get("prefer_variant", "pure"),
                decay_pct=float(args.prior_decay_pct or prior_cfg.get("decay_pct", 0.5)),
                pregame_predictor=pregame_predictor,
                is_playoff=is_playoff,
            )
            if prior is None:
                print(
                    "Warning: pregame prior enabled but no log row or pregame model; "
                    "running without prior blend.",
                    file=sys.stderr,
                )

    if prior is not None:
        eff = prior.effective_decay_pct()
        print(
            f"Using prior {prior.source}: total={prior.total:.1f} "
            f"margin={prior.margin:+.1f} "
            f"(weight=1 at tip → 0 at {eff * 100:.0f}% complete; "
            f"band={prior.margin_band_width:.0f}, blowout={prior.blowout_prob:.0%})"
        )

    kc = lc.get("kalshi", {})
    cc = lc.get("confidence", {})
    poll_until_final(
        None if args.naive_only else root / cfg["train"]["model_dir"],
        game_id=args.game_id,
        home=args.home,
        away=args.away,
        interval_seconds=args.interval or lc.get("poll_interval_seconds", 30),
        once=args.once,
        json_out=json_path,
        naive_only=args.naive_only,
        log_dir=None if args.no_log else root / lc["log_dir"],
        prior=prior,
        kalshi_enabled=args.kalshi,
        kalshi_api_base=kc.get("api_base", "https://api.elections.kalshi.com/trade-api/v2"),
        kalshi_cache_seconds=float(kc.get("cache_seconds", 25)),
        crunch_range_enabled=not args.no_crunch_range and cc.get("enabled", True),
        crunch_pct=float(cc.get("crunch_pct", 0.9375)),
        crunch_mae=float(cc.get("crunch_mae", 3.7)),
        pregame_predictor=pregame_predictor,
        is_playoff=is_playoff,
    )


def pregame_train(argv=None):
    from gametime.pipeline import v3_archive_seasons
    from gametime.pregame.elo import EloParams
    from gametime.pregame.train import train_pregame
    from gametime.sports import get_sport

    p = argparse.ArgumentParser(description="Train pre-game models (total + margin/winner)")
    p.add_argument("--config", default="configs/default.yaml")
    args = p.parse_args(argv)

    root = project_root()
    cfg = load_config(root / args.config)
    sport = get_sport(cfg)
    pg = cfg.get("pregame", {})
    data_cfg = cfg["data"]
    train_cfg = cfg["train"]

    if sport.family == "baseball":
        from gametime.pregame.baseball.models.elo import BaseballEloParams
        from gametime.pregame.baseball.train import train_baseball_pregame

        elo_cfg = pg.get("elo", {})
        h2h_cfg = pg.get("h2h", {})
        baseball_elo_params = BaseballEloParams(
            k=float(elo_cfg.get("k", 4.0)),
            home_adv_runs=float(elo_cfg.get("home_adv_runs", 0.15)),
            season_regression=float(elo_cfg.get("season_regression", 0.25)),
            margin_elo_scale=float(elo_cfg.get("margin_elo_scale", 50.0)),
        )

        meta = train_baseball_pregame(
            games_path=root / pg.get("games_path", data_cfg.get("games_path")),
            model_dir=root / pg.get("model_dir", train_cfg["model_dir"]),
            report_path=root / pg.get("report_path", "reports/mlb/eval/pregame_summary.json"),
            train_seasons=train_cfg["train_seasons"],
            train_seasontypes=train_cfg.get("train_seasontypes", ["rg"]),
            val_season=train_cfg["val_season"],
            val_seasontype=train_cfg.get("val_seasontype", "rg"),
            test_seasons=train_cfg.get("test_seasons", []),
            test_seasontype=train_cfg.get("test_seasontype", "rg"),
            form_window=int(pg.get("form_window", 10)),
            runs_strength_window=int(
                pg.get("ensemble", {}).get("runs_strength_window", 30)
            ),
            tune_ensemble_weights=bool(
                pg.get("ensemble", {}).get("tune_weights", True)
            ),
            weight_grid_step=float(
                pg.get("ensemble", {}).get("grid_step", 0.1)
            ),
            min_member_weight=float(
                pg.get("ensemble", {}).get("min_member_weight", 0.05)
            ),
            max_member_weight=(
                float(mw)
                if (mw := pg.get("ensemble", {}).get("max_member_weight")) is not None
                else None
            ),
            stack_alpha=float(pg.get("ensemble", {}).get("stack_alpha", 1.0)),
            export_predictions=bool(
                pg.get("ensemble", {}).get("export_predictions", True)
            ),
            eval_dir=root / Path(pg.get("report_path", "reports/mlb/eval/pregame_summary.json")).parent,
            elo_params=baseball_elo_params,
            pitcher_games_path=root
            / data_cfg.get(
                "pitcher_games_path", "data/mlb/processed/pitcher_games.parquet"
            ),
            park_factors_path=root
            / data_cfg.get(
                "park_factors_path", "data/mlb/processed/park_factors.parquet"
            ),
            weather_games_path=root
            / data_cfg.get(
                "weather_games_path", "data/mlb/processed/weather_games.parquet"
            ),
            lineup_games_path=root
            / data_cfg.get(
                "lineup_games_path", "data/mlb/processed/lineup_games.parquet"
            ),
            league_total_fallback=float(pg.get("league_total_fallback", 8.5)),
            h2h_window=int(h2h_cfg.get("meeting_window", 10)),
            h2h_shrink_k=float(h2h_cfg.get("shrink_k", 8.0)),
        )
        print(json.dumps(meta, indent=2, default=str))
        return

    model_dir = root / pg.get("model_dir", "models/pregame")
    elo_cfg = pg.get("elo", {})
    elo_params = EloParams(
        base_rating=float(elo_cfg.get("base_rating", 1500.0)),
        k=float(elo_cfg.get("k", 20.0)),
        home_court_adv=float(elo_cfg.get("home_court_adv", 65.0)),
        season_regression=float(elo_cfg.get("season_regression", 0.25)),
    )

    meta = train_pregame(
        root=root,
        raw_dir=root / data_cfg["raw_dir"],
        snapshots_path=root / data_cfg["processed_dir"] / "snapshots.parquet",
        model_dir=model_dir,
        seasons=data_cfg["seasons"],
        train_seasons=train_cfg["train_seasons"],
        train_seasontypes=train_cfg.get("train_seasontypes", ["rg"]),
        val_season=train_cfg["val_season"],
        val_seasontype=train_cfg.get("val_seasontype", "rg"),
        test_seasons=train_cfg.get("test_seasons", []),
        test_seasontype=train_cfg.get("test_seasontype", "po"),
        form_window=int(pg.get("form_window", 10)),
        elo_params=elo_params,
        report_path=root / pg.get("report_path", "reports/eval/pregame_summary.json"),
        team_games_out=root / pg.get("team_games_path", "data/processed/team_games.parquet"),
        v3_archive_seasons=v3_archive_seasons(data_cfg),
        pbp_source=data_cfg.get("source", "nbastats"),
        league=sport,
        blowout_margin_pts=float(pg.get("blowout_margin_pts", 10.0)),
        po_finetune_rounds=int(pg.get("po_finetune_rounds", 75)),
        include_po_in_train=bool(pg.get("include_po_in_train", True)),
        calibration_blowout_gate=float(pg.get("calibration_blowout_gate", 0.35)),
        band_target_coverage=float(pg.get("band_target_coverage", 0.80)),
    )
    print(json.dumps(meta, indent=2, default=str))


def pregame_slate(argv=None):
    from datetime import date

    from gametime.ingest.mlb import infer_season_start_year, slate_matchups_for_date
    from gametime.ingest.mlb_pitchers import (
        fetch_probables_for_date,
        format_probable_sp_line,
        lookup_probables_for_matchup,
    )
    from gametime.pregame.baseball.models.elo import BaseballEloParams
    from gametime.pregame.baseball.predict import BaseballPregamePredictor
    from gametime.pregame.log import log_pregame_prediction
    from gametime.sports import get_sport

    p = argparse.ArgumentParser(
        description="Run MLB pregame ensemble for all games on a calendar date"
    )
    p.add_argument("--config", default="configs/mlb.yaml")
    p.add_argument(
        "--date",
        default=None,
        help="Slate date YYYY-MM-DD (default: today in local timezone)",
    )
    p.add_argument("--season", type=int, default=None, help="MLB season_start_year override")
    p.add_argument("--regular-season", action="store_true", help="Regular-season games only")
    p.add_argument("--no-log", action="store_true")
    p.add_argument(
        "--decimals",
        type=int,
        default=2,
        help="Decimal places for total/margin in slate table output",
    )
    args = p.parse_args(argv)

    if args.date:
        slate_date = date.fromisoformat(args.date)
    else:
        slate_date = date.today()

    root = project_root()
    cfg = load_config(root / args.config)
    sport = get_sport(cfg)
    if sport.family != "baseball":
        print("pregame-slate is only supported for MLB (sport: mlb).", file=sys.stderr)
        sys.exit(2)

    pg = cfg.get("pregame", {})
    data_cfg = cfg.get("data", {})
    train_cfg = cfg.get("train", {})
    games_path = root / pg.get("games_path", data_cfg.get("games_path"))
    model_dir = root / pg.get("model_dir", train_cfg["model_dir"])
    season = args.season or infer_season_start_year(slate_date)

    matchups = slate_matchups_for_date(
        slate_date,
        season_start_year=season,
        games_path=games_path,
        teams=sport.mlb_teams or None,
        regular_season_only=args.regular_season,
    )
    if not matchups:
        print(f"No matchups found for {slate_date.isoformat()} (season {season}).")
        sys.exit(1)

    ensemble_cfg = pg.get("ensemble", {})
    elo_cfg = pg.get("elo", {})
    baseball_elo_params = BaseballEloParams(
        k=float(elo_cfg.get("k", 4.0)),
        home_adv_runs=float(elo_cfg.get("home_adv_runs", 0.15)),
        season_regression=float(elo_cfg.get("season_regression", 0.25)),
        margin_elo_scale=float(elo_cfg.get("margin_elo_scale", 50.0)),
    )
    pitcher_games_path = root / data_cfg.get(
        "pitcher_games_path", "data/mlb/processed/pitcher_games.parquet"
    )
    park_factors_path = root / data_cfg.get(
        "park_factors_path", "data/mlb/processed/park_factors.parquet"
    )
    weather_games_path = root / data_cfg.get(
        "weather_games_path", "data/mlb/processed/weather_games.parquet"
    )
    lineup_games_path = root / data_cfg.get(
        "lineup_games_path", "data/mlb/processed/lineup_games.parquet"
    )
    total_cal_enabled = bool(pg.get("calibration", {}).get("total_enabled", False))
    predictor = BaseballPregamePredictor(
        model_dir,
        games_path,
        form_window=int(pg.get("form_window", 10)),
        runs_strength_window=int(ensemble_cfg.get("runs_strength_window", 30)),
        train_seasons=train_cfg["train_seasons"],
        train_seasontypes=train_cfg.get("train_seasontypes", ["rg"]),
        use_stacking=bool(ensemble_cfg.get("use_stacking", False)),
        elo_params=baseball_elo_params,
        pitcher_games_path=pitcher_games_path,
        park_factors_path=park_factors_path,
        weather_games_path=weather_games_path,
        lineup_games_path=lineup_games_path,
        total_calibration_enabled=total_cal_enabled,
    )

    is_playoff = not args.regular_season
    log_dir = root / cfg.get("live", {}).get("log_dir", "data/live_predictions")
    probables = fetch_probables_for_date(slate_date)
    rows: list[dict] = []
    errors: list[str] = []

    for m in matchups:
        away, home = m["away"], m["home"]
        home_pp, away_pp = lookup_probables_for_matchup(probables, home, away)
        try:
            pred = predictor.predict(
                home=home, away=away, is_playoff=is_playoff, game_date=slate_date
            )
        except Exception as exc:
            errors.append(f"{away} @ {home}: {exc}")
            continue
        if not args.no_log:
            log_pregame_prediction(
                log_dir,
                predictor.to_pregame_prediction(pred),
                game_id=m.get("game_id"),
            )
        rows.append(
            {
                "matchup": f"{away} @ {home}",
                "prob_sp": format_probable_sp_line(away_pp, home_pp),
                "total": pred.pred_total,
                "margin": pred.pred_margin,
                "winner": pred.winner_tricode,
            }
        )

    print(f"MLB slate {slate_date.isoformat()}  ({len(rows)} games, season {season})")
    if rows:
        dec = max(0, int(args.decimals))
        num_w = max(6, dec + 4)
        w_matchup = max(len(r["matchup"]) for r in rows)
        w_prob = max(len("Prob SP"), max(len(r["prob_sp"]) for r in rows))
        header = (
            f"{'Matchup':<{w_matchup}}  {'Prob SP':<{w_prob}}  "
            f"{'Total':>{num_w}}  {'Margin':>{num_w + 1}}  Winner"
        )
        print(header)
        print("-" * len(header))
        for r in rows:
            print(
                f"{r['matchup']:<{w_matchup}}  {r['prob_sp']:<{w_prob}}  "
                f"{r['total']:{num_w}.{dec}f}  "
                f"{r['margin']:+{num_w + 1}.{dec}f}  {r['winner']}"
            )
    if errors:
        print("\nSkipped:", file=sys.stderr)
        for msg in errors:
            print(f"  {msg}", file=sys.stderr)
        if not rows:
            sys.exit(1)
    if not args.no_log and rows:
        print(f"\nLogged → {log_dir / 'pregame_predictions.parquet'}")


def pregame_slate_backtest(argv=None):
    from datetime import date

    import pandas as pd

    from gametime.pregame.baseball.models.elo import BaseballEloParams
    from gametime.pregame.baseball.slate_backtest import (
        default_end_date,
        discover_slate_dates,
        run_slate_backtest,
        write_backtest_outputs,
    )
    from gametime.sports import get_sport

    p = argparse.ArgumentParser(
        description="Retro MLB pregame slate backtest (no same-day leakage)"
    )
    p.add_argument("--config", default="configs/mlb.yaml")
    p.add_argument(
        "--end-date",
        default=None,
        help="Last slate date YYYY-MM-DD (default: yesterday or latest in games)",
    )
    p.add_argument("--days", type=int, default=14, help="Lookback window in days")
    p.add_argument("--regular-season", action="store_true", help="Regular-season games only")
    p.add_argument(
        "--append",
        action="store_true",
        help="Append only new slate dates to existing report files",
    )
    args = p.parse_args(argv)

    root = project_root()
    cfg = load_config(root / args.config)
    sport = get_sport(cfg)
    if sport.family != "baseball":
        print("pregame-slate-backtest is only supported for MLB.", file=sys.stderr)
        sys.exit(2)

    pg = cfg.get("pregame", {})
    data_cfg = cfg.get("data", {})
    train_cfg = cfg.get("train", {})
    sb_cfg = pg.get("slate_backtest", {})
    games_path = root / pg.get("games_path", data_cfg.get("games_path"))
    if not games_path.exists():
        print(f"Missing games parquet: {games_path}", file=sys.stderr)
        sys.exit(1)

    games = pd.read_parquet(games_path)
    end_date = (
        date.fromisoformat(args.end_date) if args.end_date else default_end_date(games)
    )
    slate_dates = discover_slate_dates(
        games,
        end_date=end_date,
        days=args.days,
        regular_season_only=args.regular_season,
    )
    if not slate_dates:
        print(
            f"No slate dates with games in ({end_date.isoformat()} - {args.days} days, "
            f"{end_date.isoformat()}]."
        )
        sys.exit(1)

    report_path = root / pg.get("report_path", "reports/mlb/eval/pregame_summary.json")
    out_dir = root / sb_cfg.get("report_dir", report_path.parent)

    ensemble_cfg = pg.get("ensemble", {})
    elo_cfg = pg.get("elo", {})
    h2h_cfg = pg.get("h2h", {})
    baseball_elo_params = BaseballEloParams(
        k=float(elo_cfg.get("k", 4.0)),
        home_adv_runs=float(elo_cfg.get("home_adv_runs", 0.15)),
        season_regression=float(elo_cfg.get("season_regression", 0.25)),
        margin_elo_scale=float(elo_cfg.get("margin_elo_scale", 50.0)),
    )
    model_dir = root / pg.get("model_dir", train_cfg["model_dir"])
    processed_dir = root / data_cfg.get("processed_dir", "data/mlb/processed")
    pitcher_games_path = root / data_cfg.get(
        "pitcher_games_path", "data/mlb/processed/pitcher_games.parquet"
    )
    park_factors_path = root / data_cfg.get(
        "park_factors_path", "data/mlb/processed/park_factors.parquet"
    )
    weather_games_path = root / data_cfg.get(
        "weather_games_path", "data/mlb/processed/weather_games.parquet"
    )
    lineup_games_path = root / data_cfg.get(
        "lineup_games_path", "data/mlb/processed/lineup_games.parquet"
    )
    use_stacking = bool(ensemble_cfg.get("use_stacking", False))

    daily_df, games_df = run_slate_backtest(
        games,
        slate_dates,
        model_dir=model_dir,
        games_through_dir=processed_dir,
        form_window=int(pg.get("form_window", 10)),
        runs_strength_window=int(ensemble_cfg.get("runs_strength_window", 30)),
        train_seasons=train_cfg["train_seasons"],
        train_seasontypes=train_cfg.get("train_seasontypes", ["rg"]),
        use_stacking=use_stacking,
        elo_params=baseball_elo_params,
        pitcher_games_path=pitcher_games_path,
        park_factors_path=park_factors_path,
        weather_games_path=weather_games_path,
        lineup_games_path=lineup_games_path,
        league_total_fallback=float(pg.get("league_total_fallback", 8.5)),
        h2h_window=int(h2h_cfg.get("meeting_window", 10)),
        h2h_shrink_k=float(h2h_cfg.get("shrink_k", 8.0)),
        regular_season_only=args.regular_season,
        is_playoff=not args.regular_season,
    )

    paths = write_backtest_outputs(
        daily_df, games_df, out_dir, append=args.append
    )
    blend = "stacking" if use_stacking else "linear"
    n_games = int(daily_df["n_games"].sum()) if len(daily_df) else 0
    print(
        f"MLB slate backtest: {len(slate_dates)} days, {n_games} games "
        f"({slate_dates[0].isoformat()} … {slate_dates[-1].isoformat()}), blend={blend}"
    )
    if len(daily_df):
        cols = ["slate_date", "n_games", "total_mae", "margin_mae", "winner_accuracy"]
        print(daily_df[cols].to_string(index=False))
    print(f"\nWrote → {paths.get('daily_parquet', out_dir / 'slate_backtest_daily.parquet')}")


def pregame(argv=None):
    from gametime.pregame.log import log_pregame_prediction, write_pregame_json
    from gametime.pregame.predict import PregamePredictor, format_prediction
    from gametime.pregame.vegas import VegasLineUnavailable
    from gametime.sports import get_sport

    p = argparse.ArgumentParser(description="Pre-game winner/total/margin prediction")
    p.add_argument("--config", default="configs/default.yaml")
    p.add_argument("--home", required=True, help="Home tricode, e.g. OKC")
    p.add_argument("--away", required=True, help="Away tricode, e.g. SAS")
    p.add_argument("--regular-season", action="store_true",
                   help="Treat as regular-season game (default: playoff)")
    p.add_argument("--with-vegas", action="store_true",
                   help="Fetch live spread/total from the-odds-api and blend")
    p.add_argument("--spread", type=float, default=None,
                   help="Manual home-spread override (negative = home favored)")
    p.add_argument("--total", type=float, default=None, help="Manual total override")
    p.add_argument("--vegas-weight", type=float, default=None,
                   help="Blend weight on Vegas (0..1). Default from config.")
    p.add_argument("--game-id", default=None, help="Optional NBA game_id for logging")
    p.add_argument("--no-log", action="store_true")
    p.add_argument("--json-out", default=None, help="Write JSON snapshot to this path")
    args = p.parse_args(argv)

    root = project_root()
    cfg = load_config(root / args.config)
    sport = get_sport(cfg)
    pg = cfg.get("pregame", {})
    data_cfg = cfg.get("data", {})
    train_cfg = cfg.get("train", {})
    model_dir = root / pg.get("model_dir", "models/pregame")
    form_window = int(pg.get("form_window", 10))
    is_playoff = not args.regular_season

    if sport.family == "baseball":
        if args.with_vegas or args.spread is not None or args.total is not None:
            print(
                "Vegas blend is not implemented for MLB pregame yet (see roadmap W6a).",
                file=sys.stderr,
            )
            sys.exit(2)
        from gametime.pregame.baseball.models.elo import BaseballEloParams
        from gametime.pregame.baseball.predict import (
            BaseballPregamePredictor,
            format_baseball_prediction,
        )

        games_path = root / pg.get("games_path", data_cfg.get("games_path"))
        ensemble_cfg = pg.get("ensemble", {})
        elo_cfg = pg.get("elo", {})
        h2h_cfg = pg.get("h2h", {})
        baseball_elo_params = BaseballEloParams(
            k=float(elo_cfg.get("k", 4.0)),
            home_adv_runs=float(elo_cfg.get("home_adv_runs", 0.15)),
            season_regression=float(elo_cfg.get("season_regression", 0.25)),
            margin_elo_scale=float(elo_cfg.get("margin_elo_scale", 50.0)),
        )
        pitcher_games_path = root / data_cfg.get(
            "pitcher_games_path", "data/mlb/processed/pitcher_games.parquet"
        )
        park_factors_path = root / data_cfg.get(
            "park_factors_path", "data/mlb/processed/park_factors.parquet"
        )
        weather_games_path = root / data_cfg.get(
            "weather_games_path", "data/mlb/processed/weather_games.parquet"
        )
        lineup_games_path = root / data_cfg.get(
            "lineup_games_path", "data/mlb/processed/lineup_games.parquet"
        )
        total_cal_enabled = bool(pg.get("calibration", {}).get("total_enabled", False))
        predictor = BaseballPregamePredictor(
            model_dir,
            games_path,
            form_window=form_window,
            runs_strength_window=int(ensemble_cfg.get("runs_strength_window", 30)),
            train_seasons=train_cfg["train_seasons"],
            train_seasontypes=train_cfg.get("train_seasontypes", ["rg"]),
            use_stacking=bool(ensemble_cfg.get("use_stacking", False)),
            elo_params=baseball_elo_params,
            pitcher_games_path=pitcher_games_path,
            park_factors_path=park_factors_path,
            weather_games_path=weather_games_path,
            lineup_games_path=lineup_games_path,
            league_total_fallback=float(pg.get("league_total_fallback", 8.5)),
            h2h_window=int(h2h_cfg.get("meeting_window", 10)),
            h2h_shrink_k=float(h2h_cfg.get("shrink_k", 8.0)),
            total_calibration_enabled=total_cal_enabled,
        )
        pred = predictor.predict(
            home=args.home,
            away=args.away,
            is_playoff=is_playoff,
        )
        print(format_baseball_prediction(pred))

        if not args.no_log:
            log_dir = root / cfg.get("live", {}).get("log_dir", "data/live_predictions")
            path = log_pregame_prediction(
                log_dir,
                predictor.to_pregame_prediction(pred),
                game_id=args.game_id,
            )
            print(f"\nLogged → {path}")
        if args.json_out:
            out = Path(args.json_out)
            if not out.is_absolute():
                out = root / out
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(pred.as_dict(), indent=2, default=float))
            print(f"JSON   → {out}")
        return

    team_games_path = root / pg.get("team_games_path", "data/processed/team_games.parquet")
    vegas_weight = (
        args.vegas_weight if args.vegas_weight is not None
        else float(pg.get("vegas_weight", 0.5))
    )

    predictor = PregamePredictor(model_dir, team_games_path, form_window=form_window)
    try:
        pred = predictor.predict(
            home=args.home,
            away=args.away,
            is_playoff=is_playoff,
            with_vegas=args.with_vegas,
            spread_override=args.spread,
            total_override=args.total,
            vegas_weight=vegas_weight,
        )
    except VegasLineUnavailable as exc:
        print(f"Vegas line unavailable: {exc}", file=sys.stderr)
        sys.exit(2)

    print(format_prediction(pred))

    if not args.no_log:
        log_dir = root / cfg.get("live", {}).get("log_dir", "data/live_predictions")
        path = log_pregame_prediction(log_dir, pred, game_id=args.game_id)
        print(f"\nLogged → {path}")
    if args.json_out:
        out = Path(args.json_out)
        if not out.is_absolute():
            out = root / out
        write_pregame_json(out, pred)
        print(f"JSON   → {out}")


def live_prior_demo(argv=None):
    from gametime.live.prior import resolve_live_prior
    from gametime.live.prior_demo import (
        format_demo_table,
        load_outcome,
        run_prior_convergence_demo,
    )

    p = argparse.ArgumentParser(
        description="Show pregame→live prior blend at 0%, 25%, 50%, … (synthetic checkpoints)"
    )
    p.add_argument("--config", default="configs/default.yaml")
    p.add_argument("--home", required=True)
    p.add_argument("--away", required=True)
    p.add_argument("--game-id", default=None)
    p.add_argument(
        "--checkpoints",
        default="0,0.25,0.5,0.75,1",
        help="Comma-separated pct_complete values (0–1)",
    )
    p.add_argument("--prior-decay-pct", type=float, default=None)
    p.add_argument("--no-prior", action="store_true", help="Show LGB-only (no blend)")
    args = p.parse_args(argv)

    root = project_root()
    cfg = load_config(root / args.config)
    lc = cfg.get("live", {})
    pg = cfg.get("pregame", {})
    prior_cfg = lc.get("prior", {})
    log_dir = root / lc.get("log_dir", "data/live_predictions")

    from gametime.pregame.predict import PregamePredictor

    pregame_predictor = PregamePredictor(
        root / pg.get("model_dir", "models/pregame"),
        root / pg.get("team_games_path", "data/processed/team_games.parquet"),
        form_window=int(pg.get("form_window", 10)),
    )
    is_playoff = bool(pg.get("is_playoff_live", True))

    prior = None
    if not args.no_prior:
        prior = resolve_live_prior(
            log_dir=log_dir,
            game_id=args.game_id,
            home=args.home,
            away=args.away,
            prefer_variant=prior_cfg.get("prefer_variant", "pure"),
            decay_pct=float(args.prior_decay_pct or prior_cfg.get("decay_pct", 0.5)),
            pregame_predictor=pregame_predictor,
            is_playoff=is_playoff,
        )
    if prior is None and not args.no_prior:
        print("No pregame prior found; use --no-prior or log/run gametime-pregame first.", file=sys.stderr)
        sys.exit(1)

    checkpoints = [float(x.strip()) for x in args.checkpoints.split(",") if x.strip()]
    matchup = f"{args.away.upper()} @ {args.home.upper()}"

    if args.no_prior:
        from gametime.live.prior import LivePrior

        prior = LivePrior(total=0.0, margin=0.0, source="disabled", decay_pct=0.0)

    rows = run_prior_convergence_demo(
        model_dir=root / cfg["train"]["model_dir"],
        home=args.home,
        away=args.away,
        game_id=args.game_id,
        prior=prior,
        pregame_predictor=pregame_predictor,
        is_playoff=is_playoff,
        checkpoints=checkpoints,
    )

    import pandas as pd

    outcome = load_outcome(log_dir, args.game_id, args.home, args.away)
    actual_total = float(outcome["total_final"]) if outcome is not None else None
    actual_margin = None
    if outcome is not None and pd.notna(outcome.get("home_final")) and pd.notna(outcome.get("away_final")):
        actual_margin = float(outcome["home_final"]) - float(outcome["away_final"])

    print(
        format_demo_table(
            rows,
            prior=prior,
            matchup=matchup,
            actual_total=actual_total,
            actual_margin=actual_margin,
        )
    )


def main():
    cmds = {
        "download": download,
        "build": build_snapshots,
        "train": train,
        "eval": eval_cmd,
        "backtest-signals": backtest_signals,
        "analyze-live": analyze_live,
        "analyze-game": analyze_game_cmd,
        "live": live,
        "pregame": pregame,
        "pregame-train": pregame_train,
        "pregame-slate": pregame_slate,
        "pregame-slate-backtest": pregame_slate_backtest,
    }
    if len(sys.argv) < 2 or sys.argv[1] not in cmds:
        print(
            "Usage: gametime <download|build|train|eval|backtest-signals|"
            "analyze-live|analyze-game|live|pregame|pregame-train|pregame-slate|"
            "pregame-slate-backtest>"
        )
        sys.exit(1)
    cmds[sys.argv[1]](sys.argv[2:])


if __name__ == "__main__":
    main()
