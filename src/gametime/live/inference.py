from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd

from gametime.live.features import ScoreHistory, snapshot_to_feature_row
from gametime.live.fetch import LiveGameSnapshot, fetch_todays_scoreboard, find_game
from gametime.live.confidence import CrunchTotalRange
from gametime.live.kalshi import KalshiLines
from gametime.live.prior import LivePrior
from gametime.models.constants import TARGET_REMAINING_MARGIN, TARGET_REMAINING_TOTAL


@dataclass
class LivePrediction:
    game_id: str
    matchup: str
    period: int
    clock: str
    home_score: float
    away_score: float
    status_text: str
    pred_total_final: float
    pred_home_final: float
    pred_away_final: float
    naive_total_final: float
    pct_complete: float
    pace_total: float = 0.0
    pace_recent: float = 0.0
    raw_pred_total_final: Optional[float] = None
    raw_pred_home_final: Optional[float] = None
    raw_pred_away_final: Optional[float] = None
    prior_total: Optional[float] = None
    prior_margin: Optional[float] = None
    prior_weight: Optional[float] = None
    prior_source: Optional[str] = None
    crunch_range: Optional[CrunchTotalRange] = None

    def as_dict(self) -> dict:
        d = {
            "game_id": self.game_id,
            "matchup": self.matchup,
            "pred_total_final": round(self.pred_total_final, 1),
            "pred_home_final": round(self.pred_home_final, 1),
            "pred_away_final": round(self.pred_away_final, 1),
            "naive_total_final": round(self.naive_total_final, 1),
            "pct_complete": round(self.pct_complete, 3),
            "pace_total": round(self.pace_total, 1),
            "pace_recent": round(self.pace_recent, 1),
        }
        if self.prior_source is not None:
            d["prior_source"] = self.prior_source
            d["prior_weight"] = round(self.prior_weight or 0.0, 3)
            d["prior_total"] = round(self.prior_total or 0.0, 1)
            d["prior_margin"] = round(self.prior_margin or 0.0, 1)
            d["raw_pred_total_final"] = round(self.raw_pred_total_final or 0.0, 1)
            d["raw_pred_home_final"] = round(self.raw_pred_home_final or 0.0, 1)
            d["raw_pred_away_final"] = round(self.raw_pred_away_final or 0.0, 1)
        if self.crunch_range is not None:
            d["total_low"] = round(self.crunch_range.low, 1)
            d["total_high"] = round(self.crunch_range.high, 1)
        return d


class LivePredictor:
    def __init__(
        self,
        model_dir: str | Path,
        *,
        prior: Optional[LivePrior] = None,
        pregame_predictor=None,
        is_playoff: bool = True,
    ):
        import lightgbm as lgb
        from gametime.models.train import predict_from_snapshot

        self._predict = predict_from_snapshot
        model_dir = Path(model_dir)
        self.boosters = {
            TARGET_REMAINING_TOTAL: lgb.Booster(model_file=str(model_dir / f"{TARGET_REMAINING_TOTAL}.txt")),
            TARGET_REMAINING_MARGIN: lgb.Booster(model_file=str(model_dir / f"{TARGET_REMAINING_MARGIN}.txt")),
        }
        self.history = ScoreHistory()
        self.prior = prior
        self.pregame = pregame_predictor
        self.is_playoff = is_playoff
        self._pregame_cache: dict[str, dict] = {}

    def _pregame_scored(self, snap: LiveGameSnapshot) -> Optional[dict]:
        if self.pregame is None:
            return None
        if snap.game_id not in self._pregame_cache:
            self._pregame_cache[snap.game_id] = self.pregame._score(
                home=snap.home_tricode,
                away=snap.away_tricode,
                is_playoff=self.is_playoff,
            )
        return self._pregame_cache[snap.game_id]

    def predict_snapshot(self, snap: LiveGameSnapshot) -> tuple[LivePrediction, pd.Series]:
        from gametime.features.pregame_join import attach_pregame_to_row

        row = snapshot_to_feature_row(snap, self.history)
        scored = self._pregame_scored(snap)
        if scored is not None:
            row = attach_pregame_to_row(
                row,
                pregame_pred_total=scored["total"],
                pregame_pred_margin=scored["margin_calibrated"],
                elo_diff=float(scored["row"]["elo_diff"]),
                pregame_margin_band_width=float(scored["margin_high"]) - float(scored["margin_low"]),
                pregame_blowout_prob=float(scored["blowout_prob"]),
            )
        out = self._predict(row, self.boosters)
        pct = float(row["pct_complete"])
        raw_total = float(out["pred_total_final"])
        raw_home = float(out["pred_home_final"])
        raw_away = float(out["pred_away_final"])

        total = raw_total
        home = raw_home
        away = raw_away
        prior_w = None
        prior_total_v = None
        prior_margin_v = None
        prior_src = None
        raw_total_field: Optional[float] = None
        raw_home_field: Optional[float] = None
        raw_away_field: Optional[float] = None

        if self.prior is not None:
            raw_margin = raw_home - raw_away
            blended_total, blended_margin, w = self.prior.blend(raw_total, raw_margin, pct)
            total = blended_total
            home = (blended_total + blended_margin) / 2.0
            away = (blended_total - blended_margin) / 2.0
            prior_w = w
            prior_total_v = self.prior.total
            prior_margin_v = self.prior.margin
            prior_src = self.prior.source
            raw_total_field = raw_total
            raw_home_field = raw_home
            raw_away_field = raw_away

        return LivePrediction(
            game_id=snap.game_id,
            matchup=f"{snap.away_tricode} @ {snap.home_tricode}",
            period=snap.period,
            clock=snap.clock_raw,
            home_score=snap.home_score,
            away_score=snap.away_score,
            status_text=snap.status_text,
            pred_total_final=total,
            pred_home_final=home,
            pred_away_final=away,
            naive_total_final=float(row["naive_recent_total_final"]),
            pct_complete=pct,
            pace_total=float(row["pace_total"]),
            pace_recent=float(row["pace_recent"]),
            raw_pred_total_final=raw_total_field,
            raw_pred_home_final=raw_home_field,
            raw_pred_away_final=raw_away_field,
            prior_total=prior_total_v,
            prior_margin=prior_margin_v,
            prior_weight=prior_w,
            prior_source=prior_src,
        ), row


def format_prediction_line(
    pred: LivePrediction,
    kalshi: Optional[KalshiLines] = None,
) -> str:
    base = (
        f"[{pred.matchup}] {pred.status_text} | Q{pred.period} {pred.clock} | "
        f"Score {pred.away_score:.0f}-{pred.home_score:.0f} (away-home) | "
        f"Pred final: {pred.pred_away_final:.0f}-{pred.pred_home_final:.0f} "
        f"(total {pred.pred_total_final:.0f}) | "
        f"Naive total {pred.naive_total_final:.0f} | "
        f"Pace {pred.pace_total:.0f} (recent {pred.pace_recent:.0f}) | "
        f"{pred.pct_complete * 100:.0f}% reg. complete"
    )
    if pred.prior_source is not None and pred.raw_pred_total_final is not None:
        base += (
            f" | prior {pred.prior_source} w={pred.prior_weight:.2f} "
            f"(pregame total {pred.prior_total:.0f} margin {pred.prior_margin:+.1f} → "
            f"lgb total {pred.raw_pred_total_final:.0f})"
        )
    if kalshi is not None:
        parts = ["Kalshi"]
        if kalshi.total == kalshi.total:
            parts.append(f"O/U {kalshi.total:.1f}")
        if kalshi.spread_home == kalshi.spread_home:
            parts.append(f"spread {kalshi.spread_home:+.1f}")
        if len(parts) > 1:
            base += " | " + " ".join(parts)
    if pred.crunch_range is not None:
        base += f" | crunch range {pred.crunch_range.format()}"
    return base


def poll_until_final(
    model_dir: Optional[str | Path] = None,
    *,
    game_id=None,
    home=None,
    away=None,
    interval_seconds: float = 30.0,
    once: bool = False,
    json_out: Optional[Path] = None,
    naive_only: bool = False,
    log_dir: Optional[str | Path] = None,
    prior: Optional[LivePrior] = None,
    kalshi_enabled: bool = False,
    kalshi_api_base: str = "https://api.elections.kalshi.com/trade-api/v2",
    kalshi_cache_seconds: float = 25.0,
    crunch_range_enabled: bool = True,
    crunch_pct: float = 0.9375,
    crunch_mae: float = 3.7,
    pregame_predictor=None,
    is_playoff: bool = True,
) -> Optional[LivePrediction]:
    from gametime.live.confidence import crunch_total_range
    from gametime.live.log import LivePredictionLogger
    from gametime.live.naive import naive_prediction

    predictor = None if naive_only else LivePredictor(
        model_dir,
        prior=prior,
        pregame_predictor=pregame_predictor,
        is_playoff=is_playoff,
    )
    logger = LivePredictionLogger(log_dir) if log_dir else None
    last_total: Optional[float] = None
    kalshi_warned = False

    while True:
        snap = find_game(game_id=game_id, home=home, away=away, scoreboard=fetch_todays_scoreboard())
        if snap.is_live:
            if naive_only:
                row = snapshot_to_feature_row(snap)
                pred = naive_prediction(snap, row)
            else:
                pred, row = predictor.predict_snapshot(snap)
            if crunch_range_enabled:
                pred.crunch_range = crunch_total_range(
                    pred.pred_total_final,
                    snap.home_score + snap.away_score,
                    pred.pct_complete,
                    crunch_pct=crunch_pct,
                    half_width=crunch_mae,
                )
            kalshi_lines: Optional[KalshiLines] = None
            if kalshi_enabled:
                from gametime.live.kalshi import KalshiLineUnavailable, fetch_kalshi_lines

                try:
                    kalshi_lines = fetch_kalshi_lines(
                        snap.home_tricode,
                        snap.away_tricode,
                        api_base=kalshi_api_base,
                        cache_seconds=kalshi_cache_seconds,
                    )
                except (KalshiLineUnavailable, OSError) as exc:
                    if not kalshi_warned:
                        print(f"Kalshi lines unavailable: {exc}")
                        kalshi_warned = True
            if logger:
                logger.log_prediction(
                    snap, pred, row, naive_only=naive_only, kalshi=kalshi_lines
                )
            line = format_prediction_line(pred, kalshi=kalshi_lines)
            if last_total is None or abs(pred.pred_total_final - last_total) >= 0.5:
                print(f"{datetime.now():%H:%M:%S} {line}")
                last_total = pred.pred_total_final
            else:
                print(f"{datetime.now():%H:%M:%S} (unchanged) {line}")
            if json_out:
                json_out.parent.mkdir(parents=True, exist_ok=True)
                json_out.write_text(json.dumps(pred.as_dict(), indent=2))
            if once:
                return pred
        elif snap.is_final:
            if logger:
                logger.log_game_outcome(snap)
            actual = snap.home_score + snap.away_score
            print(f"Game final: {snap.away_tricode} {snap.away_score:.0f} @ {snap.home_tricode} {snap.home_score:.0f}")
            if last_total is not None:
                print(f"Last live prediction was total {last_total:.0f} (actual {actual:.0f})")
            if logger:
                print(f"Logged outcome → {logger.outcomes_path}")
            return None
        else:
            print(
                f"{datetime.now():%H:%M:%S} Waiting for tip… {snap.away_tricode}@{snap.home_tricode} "
                f"status={snap.status} ({snap.status_text}) — polling every {interval_seconds:.0f}s"
            )
        time.sleep(interval_seconds)
