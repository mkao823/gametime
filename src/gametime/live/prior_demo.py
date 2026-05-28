"""Demo: pregame prior weight and blended totals across game progress."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pandas as pd

from gametime.data.pbp import PERIOD_LENGTH_SEC
from gametime.live.clock import REGULATION_SECONDS
from gametime.live.fetch import LiveGameSnapshot
from gametime.live.inference import LivePredictor
from gametime.live.prior import LivePrior, resolve_live_prior

STATUS_LIVE = 2


@dataclass
class PriorDemoRow:
    pct_complete: float
    prior_weight: float
    prior_total: float
    prior_margin: float
    lgb_total: float
    lgb_margin: float
    blended_total: float
    blended_margin: float
    blended_home: float
    blended_away: float
    home_score: float
    away_score: float


def snapshot_at_pct(
    *,
    game_id: str,
    home: str,
    away: str,
    pct_complete: float,
    prior: LivePrior,
) -> LiveGameSnapshot:
    """Synthetic live snapshot with scores tracking the prior-implied line."""
    pct = max(0.0, min(1.0, float(pct_complete)))
    sec_elapsed = pct * REGULATION_SECONDS
    period = min(4, int(sec_elapsed // PERIOD_LENGTH_SEC) + 1)
    elapsed_in_period = sec_elapsed - (period - 1) * PERIOD_LENGTH_SEC
    sec_remaining = max(0.0, PERIOD_LENGTH_SEC - elapsed_in_period)
    total = prior.total * pct
    margin = prior.margin * pct
    home_score = (total + margin) / 2.0
    away_score = (total - margin) / 2.0
    mins = int(sec_remaining // 60)
    secs = int(sec_remaining % 60)
    clock = f"PT{mins}M{secs}.00S"
    return LiveGameSnapshot(
        game_id=game_id or "demo",
        game_code="prior_demo",
        status=STATUS_LIVE,
        status_text="Demo",
        period=period,
        clock_raw=clock,
        sec_remaining_period=sec_remaining,
        home_tricode=home.upper(),
        away_tricode=away.upper(),
        home_score=home_score,
        away_score=away_score,
    )


def run_prior_convergence_demo(
    *,
    model_dir: Path,
    home: str,
    away: str,
    game_id: Optional[str] = None,
    prior: LivePrior,
    pregame_predictor=None,
    is_playoff: bool = True,
    checkpoints: Optional[list[float]] = None,
    outcome: Optional[pd.Series] = None,
) -> list[PriorDemoRow]:
    """Score the live model at fixed pct_complete checkpoints with prior blend."""
    checkpoints = checkpoints or [0.0, 0.25, 0.5, 0.75, 1.0]
    predictor = LivePredictor(
        model_dir,
        prior=prior,
        pregame_predictor=pregame_predictor,
        is_playoff=is_playoff,
    )
    rows: list[PriorDemoRow] = []
    for pct in checkpoints:
        snap = snapshot_at_pct(
            game_id=game_id or "demo",
            home=home,
            away=away,
            pct_complete=pct,
            prior=prior,
        )
        pred, _ = predictor.predict_snapshot(snap)
        lgb_margin = float(pred.raw_pred_home_final or pred.pred_home_final) - float(
            pred.raw_pred_away_final or pred.pred_away_final
        )
        rows.append(
            PriorDemoRow(
                pct_complete=pct,
                prior_weight=float(pred.prior_weight or 0.0),
                prior_total=float(pred.prior_total or prior.total),
                prior_margin=float(pred.prior_margin or prior.margin),
                lgb_total=float(pred.raw_pred_total_final or pred.pred_total_final),
                lgb_margin=lgb_margin,
                blended_total=float(pred.pred_total_final),
                blended_margin=float(pred.pred_home_final - pred.pred_away_final),
                blended_home=float(pred.pred_home_final),
                blended_away=float(pred.pred_away_final),
                home_score=float(snap.home_score),
                away_score=float(snap.away_score),
            )
        )
    return rows


def format_demo_table(
    rows: list[PriorDemoRow],
    *,
    prior: LivePrior,
    matchup: str,
    actual_total: Optional[float] = None,
    actual_margin: Optional[float] = None,
) -> str:
    lines = [
        f"Prior convergence demo: {matchup}",
        f"  source={prior.source}  pregame total={prior.total:.1f}  margin={prior.margin:+.1f}",
        f"  decay_pct={prior.decay_pct:.2f}  effective_decay={prior.effective_decay_pct():.2f}  "
        f"band_width={prior.margin_band_width:.0f}  blowout_prob={prior.blowout_prob:.0%}",
        "",
        f"{'pct':>6} {'w':>5} {'blend_tot':>9} {'lgb_tot':>9} {'blend_mgn':>9} {'lgb_mgn':>9} {'score':>12}",
        "-" * 72,
    ]
    for r in rows:
        score = f"{r.away_score:.0f}-{r.home_score:.0f}"
        lines.append(
            f"{r.pct_complete * 100:5.0f}% {r.prior_weight:5.2f} "
            f"{r.blended_total:9.1f} {r.lgb_total:9.1f} "
            f"{r.blended_margin:+9.1f} {r.lgb_margin:+9.1f} {score:>12}"
        )
    if actual_total is not None:
        lines.append("")
        lines.append(f"Actual final: total {actual_total:.0f}" + (
            f"  margin {actual_margin:+.0f}" if actual_margin is not None else ""
        ))
    lines.append("")
    lines.append("At tip (0%), blended ≈ pregame. By effective_decay%, w→0 and output ≈ LGB only.")
    return "\n".join(lines)


def load_outcome(
    log_dir: Path,
    game_id: Optional[str],
    home: str,
    away: str,
) -> Optional[pd.Series]:
    path = log_dir / "game_outcomes.parquet"
    if not path.exists():
        return None
    df = pd.read_parquet(path)
    if game_id:
        hit = df[df["game_id"].astype(str) == str(game_id)]
        if not hit.empty:
            return hit.iloc[-1]
    if home and away:
        hit = df[
            (df["home_tricode"].str.upper() == home.upper())
            & (df["away_tricode"].str.upper() == away.upper())
        ]
        if not hit.empty:
            return hit.iloc[-1]
    return None
