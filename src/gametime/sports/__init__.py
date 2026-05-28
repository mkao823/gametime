"""Sport profiles: capabilities, data family, and league constants.

Each sport is configured via YAML (`league:` key kept for backward compatibility).
Use `get_sport(cfg)` everywhere instead of hard-coding NBA.

Capabilities:
  ingame   — PBP → snapshots → in-game LightGBM (basketball)
  pregame  — pre-match winner + total (all supported sports)

Families share ingest/feature code:
  basketball — NBA, WNBA (nbastats PBP archives)
  baseball   — MLB pregame only (game logs; no live in-game model)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, FrozenSet


@dataclass(frozen=True)
class SportProfile:
    id: str
    name: str
    family: str
    capabilities: FrozenSet[str] = frozenset({"ingame", "pregame"})
    # --- basketball ingest (ignored for baseball) ---
    data_source: str = ""
    regular_game_id_prefix: str = ""
    playoff_game_id_prefix: str = ""
    period_length_sec: int = 720
    regulation_periods: int = 4
    regulation_minutes: float = 48.0
    stats_league_id: str = "00"
    odds_api_sport: str | None = None
    league_ppg: float = 113.0
    league_total_fallback: float = 225.8
    # --- baseball defaults ---
    league_rpg: float = 4.5
    mlb_teams: tuple[str, ...] = ()

    def has(self, capability: str) -> bool:
        return capability in self.capabilities

    @property
    def regulation_seconds(self) -> int:
        return self.regulation_periods * self.period_length_sec


NBA = SportProfile(
    id="nba",
    name="NBA",
    family="basketball",
    capabilities=frozenset({"ingame", "pregame"}),
    data_source="nbastats",
    regular_game_id_prefix="002",
    playoff_game_id_prefix="004",
    period_length_sec=720,
    regulation_minutes=48.0,
    stats_league_id="00",
    odds_api_sport="basketball_nba",
    league_ppg=113.0,
    league_total_fallback=225.8,
)

WNBA = SportProfile(
    id="wnba",
    name="WNBA",
    family="basketball",
    capabilities=frozenset({"ingame", "pregame"}),
    data_source="wnba_nbastats",
    regular_game_id_prefix="102",
    playoff_game_id_prefix="104",
    period_length_sec=600,
    regulation_minutes=40.0,
    stats_league_id="10",
    odds_api_sport="basketball_wnba",
    league_ppg=82.0,
    league_total_fallback=165.0,
)

_MLB_TEAMS = (
    "ARI", "ATL", "BAL", "BOS", "CHC", "CHW", "CIN", "CLE", "COL", "DET",
    "HOU", "KCR", "LAA", "LAD", "MIA", "MIL", "MIN", "NYM", "NYY", "OAK",
    "PHI", "PIT", "SDP", "SEA", "SFG", "STL", "TBR", "TEX", "TOR", "WSN",
)

MLB = SportProfile(
    id="mlb",
    name="MLB",
    family="baseball",
    capabilities=frozenset({"pregame"}),
    odds_api_sport="baseball_mlb",
    league_rpg=4.5,
    league_total_fallback=8.5,
    mlb_teams=_MLB_TEAMS,
)

_REGISTRY: dict[str, SportProfile] = {
    NBA.id: NBA,
    WNBA.id: WNBA,
    MLB.id: MLB,
}


def get_sport(cfg: dict[str, Any]) -> SportProfile:
    sport_id = cfg.get("sport") or cfg.get("league", NBA.id)
    if sport_id not in _REGISTRY:
        raise ValueError(f"Unknown sport {sport_id!r}; known: {sorted(_REGISTRY)}")
    return _REGISTRY[sport_id]


# Backward compatibility for basketball-only call sites
def get_league(cfg: dict[str, Any]) -> SportProfile:
    sport = get_sport(cfg)
    if sport.family != "basketball":
        raise ValueError(f"get_league() is for basketball; use get_sport() for {sport.id}")
    return sport
