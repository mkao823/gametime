"""the-odds-api client for pre-game spread/total lookup.

Requires the ODDS_API_KEY env var. Free tier allows ~500 requests/month.
Returns median spread (from the *home* team's perspective; negative = home favored)
and median total across US books that quote both markets for the requested game.

Docs: https://the-odds-api.com/liveapi/guides/v4/
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from statistics import median
from typing import Optional
from urllib.parse import urlencode
from urllib.request import Request, urlopen

API_BASE = "https://api.the-odds-api.com/v4/sports"
SPORT_KEYS = ("basketball_nba",)
# the-odds-api currently lists NBA playoff games under the same `basketball_nba`
# key. We retain a small tuple here so additional fallback keys (e.g. preseason)
# can be added without touching call sites.


class VegasLineUnavailable(RuntimeError):
    pass


@dataclass
class VegasLine:
    home_tricode: str
    away_tricode: str
    spread_home: float
    total: float
    n_books: int
    sport_key: str
    commence_time: str

    def as_dict(self) -> dict:
        return {
            "home_tricode": self.home_tricode,
            "away_tricode": self.away_tricode,
            "spread_home": self.spread_home,
            "total": self.total,
            "n_books": self.n_books,
            "sport_key": self.sport_key,
            "commence_time": self.commence_time,
        }


TEAM_TO_TRICODE = {
    "Atlanta Hawks": "ATL", "Boston Celtics": "BOS", "Brooklyn Nets": "BKN",
    "Charlotte Hornets": "CHA", "Chicago Bulls": "CHI", "Cleveland Cavaliers": "CLE",
    "Dallas Mavericks": "DAL", "Denver Nuggets": "DEN", "Detroit Pistons": "DET",
    "Golden State Warriors": "GSW", "Houston Rockets": "HOU", "Indiana Pacers": "IND",
    "LA Clippers": "LAC", "Los Angeles Clippers": "LAC", "Los Angeles Lakers": "LAL",
    "Memphis Grizzlies": "MEM", "Miami Heat": "MIA", "Milwaukee Bucks": "MIL",
    "Minnesota Timberwolves": "MIN", "New Orleans Pelicans": "NOP",
    "New York Knicks": "NYK", "Oklahoma City Thunder": "OKC", "Orlando Magic": "ORL",
    "Philadelphia 76ers": "PHI", "Phoenix Suns": "PHX", "Portland Trail Blazers": "POR",
    "Sacramento Kings": "SAC", "San Antonio Spurs": "SAS", "Toronto Raptors": "TOR",
    "Utah Jazz": "UTA", "Washington Wizards": "WAS",
}


def _name_to_tri(name: str) -> Optional[str]:
    return TEAM_TO_TRICODE.get(name)


def _fetch(sport_key: str, api_key: str) -> list[dict]:
    qs = urlencode(
        {
            "apiKey": api_key,
            "regions": "us",
            "markets": "spreads,totals",
            "oddsFormat": "american",
        }
    )
    url = f"{API_BASE}/{sport_key}/odds?{qs}"
    req = Request(url, headers={"User-Agent": "gametime/0.1"})
    with urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _extract_lines_for_game(event: dict) -> tuple[Optional[float], Optional[float], int]:
    spreads: list[float] = []
    totals: list[float] = []
    home_name = event.get("home_team")
    for bk in event.get("bookmakers", []):
        spread_for_home: Optional[float] = None
        total_for_book: Optional[float] = None
        for market in bk.get("markets", []):
            key = market.get("key")
            outcomes = market.get("outcomes", [])
            if key == "spreads":
                for o in outcomes:
                    if o.get("name") == home_name and o.get("point") is not None:
                        spread_for_home = float(o["point"])
                        break
            elif key == "totals":
                for o in outcomes:
                    if o.get("point") is not None:
                        total_for_book = float(o["point"])
                        break
        if spread_for_home is not None:
            spreads.append(spread_for_home)
        if total_for_book is not None:
            totals.append(total_for_book)
    n_books = max(len(spreads), len(totals))
    return (
        median(spreads) if spreads else None,
        median(totals) if totals else None,
        n_books,
    )


def fetch_pregame_line(home: str, away: str, *, api_key: Optional[str] = None) -> VegasLine:
    api_key = api_key or os.environ.get("ODDS_API_KEY")
    if not api_key:
        raise VegasLineUnavailable(
            "ODDS_API_KEY not set. Either export it, or pass --spread and --total manually."
        )
    home_upper, away_upper = home.upper(), away.upper()
    last_err: Optional[str] = None
    for key in SPORT_KEYS:
        try:
            events = _fetch(key, api_key)
        except Exception as exc:
            last_err = f"{key}: {exc}"
            continue
        for ev in events:
            home_tri = _name_to_tri(ev.get("home_team") or "")
            away_tri = _name_to_tri(ev.get("away_team") or "")
            if home_tri == home_upper and away_tri == away_upper:
                spread, total, n_books = _extract_lines_for_game(ev)
                if spread is None or total is None:
                    last_err = f"{key}: matched event but no spread/total quotes"
                    continue
                return VegasLine(
                    home_tricode=home_tri,
                    away_tricode=away_tri,
                    spread_home=spread,
                    total=total,
                    n_books=n_books,
                    sport_key=key,
                    commence_time=str(ev.get("commence_time", "")),
                )
    raise VegasLineUnavailable(
        f"No live spread+total for {away_upper} @ {home_upper} in {SPORT_KEYS}. "
        f"Last error: {last_err}. Try --spread/--total override."
    )
