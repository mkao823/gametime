"""MLB Stats API schedule helpers for slate discovery and start times."""
from __future__ import annotations

from datetime import date
from functools import lru_cache
from typing import Any, Optional

from gametime.ingest.mlb_pitchers import (
    MLB_STATS_BASE,
    _canon_from_mlb_api,
    _http_json,
    _team_lookup_variants,
)

_ALLOWED_GAME_STATES = frozenset({"Preview", "Live", "Final"})


@lru_cache(maxsize=16)
def fetch_slate_schedule_for_date(game_date: date) -> list[dict[str, Any]]:
    """Each row: game_id, away, home, start_time (ISO UTC)."""
    url = (
        f"{MLB_STATS_BASE}/schedule?sportId=1&date={game_date.isoformat()}"
        "&gameType=R&hydrate=team"
    )
    payload = _http_json(url)
    out: list[dict[str, Any]] = []
    seen_pks: set[int] = set()
    for day in payload.get("dates", []):
        for g in day.get("games", []):
            state = g.get("status", {}).get("abstractGameState")
            if state not in _ALLOWED_GAME_STATES:
                continue
            game_pk = int(g["gamePk"])
            if game_pk in seen_pks:
                continue
            seen_pks.add(game_pk)
            game_date_iso = g.get("gameDate")
            if not game_date_iso:
                continue
            home = _canon_from_mlb_api(
                g["teams"]["home"]["team"].get("abbreviation", "")
            )
            away = _canon_from_mlb_api(
                g["teams"]["away"]["team"].get("abbreviation", "")
            )
            out.append(
                {
                    "game_id": str(game_pk),
                    "away": away,
                    "home": home,
                    "start_time": str(game_date_iso),
                }
            )
    return out


@lru_cache(maxsize=16)
def fetch_slate_times_for_date(game_date: date) -> dict[tuple[str, str], str]:
    """Map (away_tricode, home_tricode) -> gameDate ISO string (UTC)."""
    return {
        (row["away"], row["home"]): row["start_time"]
        for row in fetch_slate_schedule_for_date(game_date)
    }


def lookup_slate_time_for_matchup(
    times: dict[tuple[str, str], str],
    away: str,
    home: str,
) -> Optional[str]:
    """Resolve start time when home/away tricode differs by Athletics alias (ATH vs OAK)."""
    away_u, home_u = away.upper(), home.upper()
    for h in _team_lookup_variants(home_u):
        for a in _team_lookup_variants(away_u):
            key = (a, h)
            if key in times:
                return times[key]
    return None
