from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from gametime.live.fetch import fetch_todays_scoreboard, find_game

_DATE_IN_NAME = re.compile(r"20\d{2}[-_]?\d{2}[-_]?\d{2}")


def _scoreboard_date(scoreboard: dict) -> str:
    raw = scoreboard.get("scoreboard", {}).get("gameDate", "")
    if raw:
        return raw.replace("-", "")
    return datetime.now(timezone.utc).strftime("%Y%m%d")


def resolve_live_json_path(
    root: Path,
    *,
    json_out: Optional[str] = None,
    home: Optional[str] = None,
    away: Optional[str] = None,
    report_dir: str = "reports/live",
) -> Optional[Path]:
    """
    Build a dated JSON report path.

    Default: reports/live/live_20260525_NYK_CLE.json
    If json_out is given without a date, inserts date: live_nyk_cle.json -> live_20260525_nyk_cle.json
    """
    away_t = (away or "away").upper()
    home_t = (home or "home").upper()

    try:
        board = fetch_todays_scoreboard()
        date_str = _scoreboard_date(board)
        if home and away:
            snap = find_game(home=home, away=away, scoreboard=board)
            away_t, home_t = snap.away_tricode, snap.home_tricode
    except Exception:
        date_str = datetime.now(timezone.utc).strftime("%Y%m%d")

    if not json_out:
        out_dir = root / report_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        return out_dir / f"live_{date_str}_{away_t}_{home_t}.json"

    path = Path(json_out)
    if not path.is_absolute():
        path = root / path
    if _DATE_IN_NAME.search(path.name):
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    dated_name = f"{path.stem}_{date_str}{path.suffix}"
    path = path.parent / dated_name
    path.parent.mkdir(parents=True, exist_ok=True)
    return path
