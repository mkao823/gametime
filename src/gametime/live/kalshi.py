"""Kalshi public market data for live NBA total and spread lines.

Kalshi lists strike ladders (e.g. \"Over 215.5 points\", \"OKC wins by over 7.5\")
as separate binary markets. We infer a consensus line by finding where the
yes-side mid price crosses 50%.

No API key required for market data (api.elections.kalshi.com).
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

DEFAULT_API_BASE = "https://api.elections.kalshi.com/trade-api/v2"
SERIES_TOTAL = "KXNBATOTAL"
SERIES_SPREAD = "KXNBASPREAD"

_CACHE: dict[str, tuple[float, Any]] = {}


class KalshiLineUnavailable(RuntimeError):
    pass


@dataclass
class KalshiLines:
    home_tricode: str
    away_tricode: str
    total: float
    spread_home: float
    event_ticker_total: str
    event_ticker_spread: str
    fetched_at_utc: str

    def as_dict(self) -> dict:
        return {
            "home_tricode": self.home_tricode,
            "away_tricode": self.away_tricode,
            "total": self.total,
            "spread_home": self.spread_home,
            "event_ticker_total": self.event_ticker_total,
            "event_ticker_spread": self.event_ticker_spread,
            "fetched_at_utc": self.fetched_at_utc,
        }


def _get_json(url: str, params: Optional[dict] = None, timeout: float = 20.0) -> dict:
    qs = f"?{urlencode(params)}" if params else ""
    req = Request(f"{url}{qs}", headers={"User-Agent": "gametime/0.1", "Accept": "application/json"})
    with urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _cached_get(cache_key: str, fetcher, cache_seconds: float) -> Any:
    now = time.time()
    if cache_key in _CACHE:
        ts, payload = _CACHE[cache_key]
        if now - ts < cache_seconds:
            return payload
    payload = fetcher()
    _CACHE[cache_key] = (now, payload)
    return payload


def _yes_mid(market: dict) -> Optional[float]:
    yb = market.get("yes_bid_dollars")
    ya = market.get("yes_ask_dollars")
    if yb is None and ya is None:
        lp = market.get("last_price_dollars")
        return float(lp) if lp is not None else None
    yb_f = float(yb or 0)
    ya_f = float(ya if ya is not None else 1)
    if ya_f <= yb_f:
        lp = market.get("last_price_dollars")
        return float(lp) if lp is not None else None
    return (yb_f + ya_f) / 2.0


def _implied_strike_at_fifty(strikes: list[tuple[float, float]]) -> Optional[float]:
    """Linear interpolation: strike where probability crosses 0.5."""
    if not strikes:
        return None
    ordered = sorted(strikes, key=lambda x: x[0])
    for i in range(len(ordered) - 1):
        s1, p1 = ordered[i]
        s2, p2 = ordered[i + 1]
        if p1 == p2:
            continue
        if (p1 - 0.5) * (p2 - 0.5) <= 0:
            return s1 + (0.5 - p1) * (s2 - s1) / (p2 - p1)
    best = min(ordered, key=lambda x: abs(x[1] - 0.5))
    return best[0]


def _fetch_series_events(api_base: str, series_ticker: str, cache_seconds: float) -> list[dict]:
    def _fetch():
        data = _get_json(
            f"{api_base}/events",
            {
                "series_ticker": series_ticker,
                "status": "open",
                "with_nested_markets": "true",
                "limit": 50,
            },
        )
        return data.get("events") or []

    return _cached_get(f"events:{series_ticker}", _fetch, cache_seconds)


def _match_event(events: list[dict], home: str, away: str) -> Optional[dict]:
    home_u, away_u = home.upper(), away.upper()
    needle = f"{away_u}{home_u}"
    for ev in events:
        ticker = str(ev.get("event_ticker", "")).upper()
        if needle in ticker:
            return ev
    for ev in events:
        ticker = str(ev.get("event_ticker", "")).upper()
        if home_u in ticker and away_u in ticker:
            return ev
    return None


def _home_team_names(home_tricode: str) -> tuple[str, ...]:
    names = {
        "OKC": ("oklahoma city", "okc", "thunder"),
        "SAS": ("san antonio", "spurs", "sas"),
        "NYK": ("new york", "knicks", "nyk"),
        "CLE": ("cleveland", "cavaliers", "cle"),
        "BOS": ("boston", "celtics", "bos"),
        "IND": ("indiana", "pacers", "ind"),
        "MIN": ("minnesota", "timberwolves", "min"),
        "DAL": ("dallas", "mavericks", "dal"),
        "LAL": ("los angeles l", "lakers", "lal"),
        "GSW": ("golden state", "warriors", "gsw"),
        "MIA": ("miami", "heat", "mia"),
        "PHI": ("philadelphia", "76ers", "phi"),
        "DEN": ("denver", "nuggets", "den"),
    }
    return names.get(home_tricode.upper(), (home_tricode.lower(),))


def _implied_total(event: dict) -> Optional[float]:
    strikes: list[tuple[float, float]] = []
    for m in event.get("markets") or []:
        strike = m.get("floor_strike")
        if strike is None:
            continue
        mid = _yes_mid(m)
        if mid is None:
            continue
        strikes.append((float(strike), mid))
    return _implied_strike_at_fifty(strikes)


def _implied_home_margin(event: dict, home_tricode: str) -> Optional[float]:
    home_names = _home_team_names(home_tricode)
    strikes: list[tuple[float, float]] = []
    for m in event.get("markets") or []:
        text = " ".join(
            filter(
                None,
                [
                    str(m.get("yes_sub_title") or ""),
                    str(m.get("title") or ""),
                    str(m.get("rules_primary") or ""),
                ],
            )
        ).lower()
        if not any(n in text for n in home_names):
            continue
        if "wins by over" not in text and "win by over" not in text:
            continue
        strike = m.get("floor_strike")
        if strike is None:
            continue
        mid = _yes_mid(m)
        if mid is None:
            continue
        strikes.append((float(strike), mid))
    margin = _implied_strike_at_fifty(strikes)
    return margin


def fetch_kalshi_lines(
    home: str,
    away: str,
    *,
    api_base: str = DEFAULT_API_BASE,
    cache_seconds: float = 25.0,
) -> KalshiLines:
    home_u, away_u = home.upper(), away.upper()
    total_events = _fetch_series_events(api_base, SERIES_TOTAL, cache_seconds)
    spread_events = _fetch_series_events(api_base, SERIES_SPREAD, cache_seconds)

    total_ev = _match_event(total_events, home_u, away_u)
    spread_ev = _match_event(spread_events, home_u, away_u)
    if total_ev is None and spread_ev is None:
        raise KalshiLineUnavailable(
            f"No open Kalshi total/spread events for {away_u} @ {home_u}. "
            f"Checked {SERIES_TOTAL} and {SERIES_SPREAD}."
        )

    total = _implied_total(total_ev) if total_ev else None
    margin = _implied_home_margin(spread_ev, home_u) if spread_ev else None
    if total is None and margin is None:
        raise KalshiLineUnavailable(
            f"Matched Kalshi events but could not infer lines for {away_u} @ {home_u}."
        )

    # spread_home: negative when home favored (sportsbook convention)
    spread_home = -float(margin) if margin is not None else float("nan")

    return KalshiLines(
        home_tricode=home_u,
        away_tricode=away_u,
        total=float(total) if total is not None else float("nan"),
        spread_home=spread_home,
        event_ticker_total=str(total_ev.get("event_ticker", "")) if total_ev else "",
        event_ticker_spread=str(spread_ev.get("event_ticker", "")) if spread_ev else "",
        fetched_at_utc=datetime.now(timezone.utc).isoformat(),
    )
