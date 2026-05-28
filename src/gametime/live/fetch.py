from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Optional
from urllib.request import Request, urlopen

from gametime.live.clock import parse_iso_clock

CDN_SCOREBOARD = "https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json"
NBA_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept": "application/json",
    "Referer": "https://www.nba.com/",
}
STATUS_LIVE = 2
STATUS_FINAL = 3


@dataclass
class LiveGameSnapshot:
    game_id: str
    game_code: str
    status: int
    status_text: str
    period: int
    clock_raw: str
    sec_remaining_period: float
    home_tricode: str
    away_tricode: str
    home_score: float
    away_score: float

    @property
    def is_live(self) -> bool:
        return self.status == STATUS_LIVE

    @property
    def is_final(self) -> bool:
        return self.status == STATUS_FINAL


def fetch_todays_scoreboard() -> dict[str, Any]:
    req = Request(CDN_SCOREBOARD, headers=NBA_HEADERS)
    with urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _parse_game(raw: dict) -> LiveGameSnapshot:
    sec = parse_iso_clock(str(raw.get("gameClock") or "")) or 0.0
    home, away = raw["homeTeam"], raw["awayTeam"]
    return LiveGameSnapshot(
        game_id=str(raw["gameId"]),
        game_code=str(raw.get("gameCode", "")),
        status=int(raw.get("gameStatus", 0)),
        status_text=str(raw.get("gameStatusText", "")),
        period=int(raw.get("period") or 1),
        clock_raw=str(raw.get("gameClock", "")),
        sec_remaining_period=sec,
        home_tricode=str(home["teamTricode"]),
        away_tricode=str(away["teamTricode"]),
        home_score=float(home.get("score") or 0),
        away_score=float(away.get("score") or 0),
    )


def fetch_all_games(scoreboard: Optional[dict] = None) -> list[LiveGameSnapshot]:
    board = scoreboard or fetch_todays_scoreboard()
    return [_parse_game(g) for g in board.get("scoreboard", {}).get("games", [])]


def find_game(
    *,
    game_id: Optional[str] = None,
    home: Optional[str] = None,
    away: Optional[str] = None,
    scoreboard: Optional[dict] = None,
) -> LiveGameSnapshot:
    games = fetch_all_games(scoreboard)
    if not games:
        raise RuntimeError("No games on scoreboard")
    if game_id:
        for g in games:
            if g.game_id == game_id:
                return g
        raise ValueError(f"Game {game_id} not found")
    home, away = (home or "").upper(), (away or "").upper()
    if home and away:
        for g in games:
            if {g.home_tricode, g.away_tricode} == {home, away}:
                return g
        raise ValueError(f"No game for {away} @ {home}")
    live = [g for g in games if g.is_live]
    if len(live) == 1:
        return live[0]
    raise ValueError("Specify --game-id or --home/--away")
