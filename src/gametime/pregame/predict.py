"""Pre-game prediction: load saved models + Elo state, score one matchup."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

import lightgbm as lgb
import pandas as pd

from gametime.pregame.calibration import (
    MarginBandCalibration,
    MarginCalibration,
    load_band_calibration,
    load_calibration,
)
from gametime.pregame.constants import (
    TARGET_BLOWOUT,
    TARGET_MARGIN,
    TARGET_MARGIN_P10,
    TARGET_MARGIN_P90,
    TARGET_TOTAL,
)
from gametime.pregame.elo import EloState, OffDefState, load_offdef_state, load_state
from gametime.pregame.features import FEATURE_COLUMNS, build_inference_row, feature_row_to_frame
from gametime.pregame.vegas import VegasLine, VegasLineUnavailable, fetch_pregame_line


@dataclass
class PregamePrediction:
    home_tricode: str
    away_tricode: str
    variant: str
    is_playoff: bool
    elo_home: float
    elo_away: float
    pred_total: float
    pred_margin: float
    pred_home_final: float
    pred_away_final: float
    winner_tricode: str
    win_prob_home: float
    home_form_n: int
    away_form_n: int
    pred_margin_raw: Optional[float] = None
    pred_margin_calibrated: Optional[float] = None
    margin_low: Optional[float] = None
    margin_high: Optional[float] = None
    blowout_prob: Optional[float] = None
    vegas: Optional[dict] = None
    vegas_weight: Optional[float] = None
    model_only: Optional[dict] = None

    def as_dict(self) -> dict:
        return asdict(self)


def _logistic_home_win(margin: float, scale: float = 14.0) -> float:
    import math
    return 1.0 / (1.0 + math.exp(-margin / scale))


def _winner(home_tri: str, away_tri: str, margin: float) -> str:
    return home_tri if margin >= 0 else away_tri


class PregamePredictor:
    def __init__(self, model_dir: str | Path, team_games_path: str | Path, form_window: int = 10):
        model_dir = Path(model_dir)
        self.boosters: dict[str, lgb.Booster] = {
            TARGET_TOTAL: lgb.Booster(model_file=str(model_dir / f"{TARGET_TOTAL}.txt")),
            TARGET_MARGIN: lgb.Booster(model_file=str(model_dir / f"{TARGET_MARGIN}.txt")),
        }
        for name in (TARGET_BLOWOUT, TARGET_MARGIN_P10, TARGET_MARGIN_P90):
            path = model_dir / f"{name}.txt"
            if path.exists():
                self.boosters[name] = lgb.Booster(model_file=str(path))
        cal_path = model_dir / "calibration.json"
        self.calibration: Optional[MarginCalibration] = (
            load_calibration(cal_path) if cal_path.exists() else None
        )
        band_path = model_dir / "margin_band.json"
        self.band_calibration: Optional[MarginBandCalibration] = (
            load_band_calibration(band_path) if band_path.exists() else None
        )
        self.elo_state: EloState = load_state(model_dir / "elo_state.json")
        offdef_path = model_dir / "elo_offdef.json"
        self.offdef_state: OffDefState = (
            load_offdef_state(offdef_path) if offdef_path.exists() else OffDefState()
        )
        self.team_games = pd.read_parquet(team_games_path)
        if "game_date" not in self.team_games.columns or "q4_pace48" not in self.team_games.columns:
            from gametime.pregame.augment import augment_team_games

            raw_guess = team_games_path.parent.parent / "raw"
            proc = team_games_path.parent
            if raw_guess.exists():
                self.team_games = augment_team_games(
                    self.team_games,
                    raw_dir=raw_guess,
                    processed_dir=proc,
                    seasons=sorted(self.team_games["season_start_year"].unique().tolist()),
                    v3_archive_seasons=[2025],
                )
        self.form_window = form_window

    def _score(self, *, home: str, away: str, is_playoff: bool) -> dict:
        row = build_inference_row(
            home=home,
            away=away,
            elo_state=self.elo_state,
            offdef_state=self.offdef_state,
            team_games=self.team_games,
            is_playoff=is_playoff,
            window=self.form_window,
        )
        X = feature_row_to_frame(row)
        total = float(self.boosters[TARGET_TOTAL].predict(X)[0])
        margin_raw = float(self.boosters[TARGET_MARGIN].predict(X)[0])
        blowout_prob = (
            float(self.boosters[TARGET_BLOWOUT].predict(X)[0])
            if TARGET_BLOWOUT in self.boosters
            else 0.0
        )
        margin_low = (
            float(self.boosters[TARGET_MARGIN_P10].predict(X)[0])
            if TARGET_MARGIN_P10 in self.boosters
            else margin_raw - 8.0
        )
        margin_high = (
            float(self.boosters[TARGET_MARGIN_P90].predict(X)[0])
            if TARGET_MARGIN_P90 in self.boosters
            else margin_raw + 8.0
        )
        if self.band_calibration is not None:
            margin_low, margin_high = self.band_calibration.apply(margin_low, margin_high)
        margin_cal = (
            self.calibration.apply(margin_raw, blowout_prob)
            if self.calibration is not None
            else margin_raw
        )
        return {
            "row": row,
            "total": total,
            "margin_raw": margin_raw,
            "margin_calibrated": margin_cal,
            "margin_low": margin_low,
            "margin_high": margin_high,
            "blowout_prob": blowout_prob,
        }

    def predict(
        self,
        *,
        home: str,
        away: str,
        is_playoff: bool = True,
        with_vegas: bool = False,
        spread_override: Optional[float] = None,
        total_override: Optional[float] = None,
        vegas_weight: float = 0.5,
        api_key: Optional[str] = None,
        use_calibrated_margin: bool = True,
    ) -> PregamePrediction:
        home, away = home.upper(), away.upper()
        scored = self._score(home=home, away=away, is_playoff=is_playoff)
        row = scored["row"]
        total = scored["total"]
        margin_raw = scored["margin_raw"]
        margin = scored["margin_calibrated"] if use_calibrated_margin else margin_raw

        vegas_payload: Optional[dict] = None
        model_only_payload: Optional[dict] = None
        variant = "pure"

        if with_vegas or spread_override is not None or total_override is not None:
            if spread_override is not None or total_override is not None:
                if spread_override is None or total_override is None:
                    raise ValueError("Provide both --spread and --total when overriding.")
                vegas_payload = {
                    "spread_home": float(spread_override),
                    "total": float(total_override),
                    "source": "manual_override",
                }
            else:
                line: VegasLine = fetch_pregame_line(home=home, away=away, api_key=api_key)
                vegas_payload = line.as_dict()
                vegas_payload["source"] = "the_odds_api"

            vegas_margin = -float(vegas_payload["spread_home"])
            vegas_total = float(vegas_payload["total"])
            blended_total = vegas_weight * vegas_total + (1.0 - vegas_weight) * total
            blended_margin = vegas_weight * vegas_margin + (1.0 - vegas_weight) * margin
            model_only_payload = {
                "pred_total": total,
                "pred_margin": margin,
                "pred_margin_raw": margin_raw,
                "pred_home_final": (total + margin) / 2.0,
                "pred_away_final": (total - margin) / 2.0,
                "winner": _winner(home, away, margin),
                "blowout_prob": scored["blowout_prob"],
            }
            total, margin = blended_total, blended_margin
            variant = "vegas_blend"

        home_final = (total + margin) / 2.0
        away_final = (total - margin) / 2.0
        return PregamePrediction(
            home_tricode=home,
            away_tricode=away,
            variant=variant,
            is_playoff=is_playoff,
            elo_home=float(row["elo_home"]),
            elo_away=float(row["elo_away"]),
            pred_total=total,
            pred_margin=margin,
            pred_home_final=home_final,
            pred_away_final=away_final,
            winner_tricode=_winner(home, away, margin),
            win_prob_home=_logistic_home_win(margin),
            home_form_n=int(row["_home_form_n"]),
            away_form_n=int(row["_away_form_n"]),
            pred_margin_raw=margin_raw,
            pred_margin_calibrated=scored["margin_calibrated"],
            margin_low=scored["margin_low"],
            margin_high=scored["margin_high"],
            blowout_prob=scored["blowout_prob"],
            vegas=vegas_payload,
            vegas_weight=vegas_weight if variant == "vegas_blend" else None,
            model_only=model_only_payload,
        )


def format_prediction(p: PregamePrediction) -> str:
    lines = [
        f"Matchup: {p.away_tricode} @ {p.home_tricode}  "
        f"({'playoff' if p.is_playoff else 'regular season'}, variant={p.variant})",
        f"Elo:     {p.home_tricode} {p.elo_home:.0f}  vs  {p.away_tricode} {p.elo_away:.0f}  "
        f"(diff {p.elo_home - p.elo_away:+.0f})",
        f"Form n:  {p.home_tricode} last {p.home_form_n}  /  {p.away_tricode} last {p.away_form_n}",
        f"Predicted final: {p.away_tricode} {p.pred_away_final:.1f} @ "
        f"{p.home_tricode} {p.pred_home_final:.1f}  "
        f"(total {p.pred_total:.1f}, margin {p.pred_margin:+.1f})",
        f"Predicted winner: {p.winner_tricode}  "
        f"(home win prob {p.win_prob_home * 100:.1f}%)",
    ]
    if p.blowout_prob is not None:
        lines.append(f"Blowout prob (|margin|>10): {p.blowout_prob * 100:.1f}%")
    if p.margin_low is not None and p.margin_high is not None:
        lines.append(f"Margin band (p10–p90): {p.margin_low:+.1f} to {p.margin_high:+.1f}")
    if p.pred_margin_raw is not None and p.pred_margin_calibrated is not None:
        if abs(p.pred_margin_raw - p.pred_margin_calibrated) > 0.05:
            lines.append(
                f"  Raw margin {p.pred_margin_raw:+.1f} → calibrated {p.pred_margin_calibrated:+.1f}"
            )
    if p.vegas:
        src = p.vegas.get("source", "vegas")
        lines.append(
            f"Vegas ({src}, weight {p.vegas_weight:.2f}): "
            f"spread_home {p.vegas['spread_home']:+.1f}, total {p.vegas['total']:.1f}"
        )
        if p.model_only:
            mo = p.model_only
            lines.append(
                f"  Model-only would say: {p.away_tricode} {mo['pred_away_final']:.1f} @ "
                f"{p.home_tricode} {mo['pred_home_final']:.1f} "
                f"(total {mo['pred_total']:.1f}, margin {mo['pred_margin']:+.1f}, "
                f"winner {mo['winner']})"
            )
    return "\n".join(lines)
