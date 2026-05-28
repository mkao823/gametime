"""Pre-game prior for in-game prediction: start at pregame, converge to live model.

At tip-off (pct_complete=0) the displayed total/margin equals the pregame prior.
Weight decays linearly to zero by ``decay_pct`` (default 0.5 = halftime), after
which the in-game LightGBM prediction is used alone.

    blended = w(t) * prior + (1 - w(t)) * lgb
    w(t)    = clip(1 - pct_complete / effective_decay, 0, 1)

When pregame uncertainty is high (wide margin band, elevated blowout prob),
``effective_decay`` is stretched so the prior persists longer into the game.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pandas as pd


@dataclass
class LivePrior:
    total: float
    margin: float
    source: str
    decay_pct: float = 0.5
    margin_band_width: float = 16.0
    blowout_prob: float = 0.0

    def effective_decay_pct(self) -> float:
        """Hold prior longer when pregame margin uncertainty is high."""
        width_factor = min(1.0, max(0.0, self.margin_band_width / 30.0))
        blowout_factor = min(1.0, max(0.0, self.blowout_prob))
        stretch = 1.0 + 0.5 * width_factor * blowout_factor
        return min(0.85, self.decay_pct * stretch)

    def weight(self, pct_complete: float) -> float:
        decay = self.effective_decay_pct()
        if decay <= 0:
            return 0.0
        w = 1.0 - float(pct_complete) / decay
        return max(0.0, min(1.0, w))

    def blend(
        self, lgb_total: float, lgb_margin: float, pct_complete: float
    ) -> tuple[float, float, float]:
        w = self.weight(pct_complete)
        blended_total = w * self.total + (1.0 - w) * lgb_total
        blended_margin = w * self.margin + (1.0 - w) * lgb_margin
        return blended_total, blended_margin, w


def load_prior_from_log(
    log_dir: str | Path,
    *,
    game_id: Optional[str] = None,
    home: Optional[str] = None,
    away: Optional[str] = None,
    prefer_variant: str = "pure",
    decay_pct: float = 0.5,
) -> Optional[LivePrior]:
    path = Path(log_dir) / "pregame_predictions.parquet"
    if not path.exists():
        return None
    df = pd.read_parquet(path)
    if df.empty:
        return None

    candidates = df
    if game_id:
        match_gid = candidates[candidates["game_id"].astype(str) == str(game_id)]
        if not match_gid.empty:
            candidates = match_gid
    if (game_id is None or candidates is df) and home and away:
        candidates = candidates[
            (candidates["home_tricode"].str.upper() == home.upper())
            & (candidates["away_tricode"].str.upper() == away.upper())
        ]
    if candidates.empty:
        return None

    preferred = candidates[candidates["variant"] == prefer_variant]
    if not preferred.empty:
        candidates = preferred

    row = candidates.sort_values("recorded_at_utc").iloc[-1]
    margin_low = row.get("margin_low")
    margin_high = row.get("margin_high")
    if margin_low is not None and margin_high is not None and pd.notna(margin_low) and pd.notna(margin_high):
        band_width = float(margin_high) - float(margin_low)
    else:
        band_width = 16.0
    blowout_prob = float(row["blowout_prob"]) if "blowout_prob" in row and pd.notna(row.get("blowout_prob")) else 0.0

    return LivePrior(
        total=float(row["pred_total"]),
        margin=float(row["pred_margin"]),
        source=f"pregame_{row['variant']}",
        decay_pct=decay_pct,
        margin_band_width=band_width,
        blowout_prob=blowout_prob,
    )


def prior_from_pregame_scored(
    scored: dict,
    *,
    source: str = "pregame_live",
    decay_pct: float = 0.5,
) -> LivePrior:
    """Build a prior from PregamePredictor._score() output."""
    return LivePrior(
        total=float(scored["total"]),
        margin=float(scored["margin_calibrated"]),
        source=source,
        decay_pct=decay_pct,
        margin_band_width=float(scored["margin_high"]) - float(scored["margin_low"]),
        blowout_prob=float(scored["blowout_prob"]),
    )


def resolve_live_prior(
    *,
    log_dir: str | Path,
    game_id: Optional[str] = None,
    home: Optional[str] = None,
    away: Optional[str] = None,
    prefer_variant: str = "pure",
    decay_pct: float = 0.5,
    pregame_predictor=None,
    is_playoff: bool = True,
) -> Optional[LivePrior]:
    """Log row first, then live pregame model if home/away are known."""
    prior = load_prior_from_log(
        log_dir,
        game_id=game_id,
        home=home,
        away=away,
        prefer_variant=prefer_variant,
        decay_pct=decay_pct,
    )
    if prior is not None:
        return prior
    if pregame_predictor is None or not home or not away:
        return None
    scored = pregame_predictor._score(
        home=home.upper(),
        away=away.upper(),
        is_playoff=is_playoff,
    )
    return prior_from_pregame_scored(scored, source="pregame_live", decay_pct=decay_pct)
