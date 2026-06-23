# AGENT_BACKEND — TASK-34: Fast slate discovery (MLB Stats API)

## Your Role

You are **AGENT_BACKEND**. You replace the **slow pybaseball slate fallback** with a **single MLB Stats API schedule request** so `/v1/slate` and the web UI load in a few seconds (including today / upcoming dates).

You **do** refactor `mlb_schedule.py` and `slate_matchups_for_date` discovery order.

You **do not** change ensemble members, frontend components, or deploy docs.

## Project Context

- Branch: `task/TASK-34-fast-slate-statsapi` from **`main`** (includes merged TASK-33 @ `9d6de50`)
- Commit format: `[AGENT_BACKEND] TASK-34: short description`
- **Blocked by:** TASK-33 merge ✅
- **Read STANDARDS.md before writing any code.**

## Problem (measured June 2026)

| Path | When | Latency |
|------|------|---------|
| `slate_from_games_parquet` | Date has **completed** games in `games.parquet` | ~4–7s (predict loop) |
| `fetch_slate_from_pybaseball` | Today / upcoming (parquet empty) | **30s–3min** (30× `schedule_and_record`) |
| Vercel BFF | Same API, Hobby **10s** function limit | 502/500 on slow dates |

TASK-33 added `fetch_slate_times_for_date` (one fast Stats API call) but **matchup discovery** still falls through to pybaseball when parquet has no rows for that calendar day.

## Orchestrator decisions (locked)

| Decision | Value |
|----------|-------|
| Primary fallback | **MLB Stats API** `GET /schedule?sportId=1&date=YYYY-MM-DD&gameType=R&hydrate=team` |
| Game states | Include `Preview`, `Live`, and `Final`; **exclude** `Postponed` / `Cancelled` |
| Playoffs | `regular_season_only=True` → `gameType=R` only (unchanged); playoff slates out of scope |
| pybaseball | **Last resort** only if Stats API request fails (network/parse); log warning |
| Cache | One `@lru_cache` schedule fetch per date returning **matchups + times** together |
| `game_id` | Use `str(gamePk)` from Stats API when parquet id unavailable |
| Sort | Reuse TASK-33 `_attach_and_sort_slate_matchups` / `start_time` (do not duplicate sort logic) |
| Performance target | Stats API discovery path **< 2s**; full `/v1/slate` for today **< 10s** on dev hardware |

## Your Task

### 1. Unified schedule fetch — `src/gametime/ingest/mlb_schedule.py`

Refactor TASK-33 `fetch_slate_times_for_date` into a richer helper, e.g.:

```python
@lru_cache(maxsize=16)
def fetch_slate_schedule_for_date(game_date: date) -> list[dict[str, Any]]:
    """Each row: game_id, away, home, start_time (ISO UTC)."""
```

- Reuse `MLB_STATS_BASE`, `_http_json`, `_canon_from_mlb_api` from `mlb_pitchers.py`
- Filter `abstractGameState` — allow `Preview`, `Live`, `Final`; skip postponed/cancelled
- Deduplicate by `gamePk`
- Keep `lookup_slate_time_for_matchup` / Athletics alias handling

Expose thin backward-compatible wrapper if tests import `fetch_slate_times_for_date`.

### 2. New discovery helper — `fetch_slate_from_statsapi`

In `mlb.py` or `mlb_schedule.py`:

```python
def fetch_slate_from_statsapi(target_date: date, *, regular_season_only: bool = True) -> list[dict[str, str]]:
```

Map schedule rows to `{game_id, away, home}` (and pass `start_time` through to avoid double fetch).

### 3. Update `slate_matchups_for_date` order

```text
1. slate_from_games_parquet  (completed games — unchanged)
2. fetch_slate_from_statsapi (NEW — upcoming/today)
3. fetch_slate_from_pybaseball (fallback only on Stats API failure)
4. _attach_and_sort_slate_matchups (attach times if missing; sort)
```

Optimize: when step 2 succeeds, schedule already has `start_time` — avoid a **second** HTTP call in `_attach_and_sort_slate_matchups` (pass pre-fetched schedule or enriched rows).

### 4. Tests

| File | Coverage |
|------|----------|
| `tests/test_mlb_slate_schedule.py` | Extend — Stats API path returns ordered matchups; postponed game excluded |
| New or existing | Mock `_http_json` — assert pybaseball **not** called when Stats API succeeds |
| `tests/test_api_predictions.py` | Optional timing smoke with mocked schedule (no live network in CI) |

### 5. Docs (one line)

`docs/mlb_pregame_ops.md` — slate discovery: parquet → Stats API → pybaseball fallback.

## Exact Deliverables

| Path | Action |
|------|--------|
| `src/gametime/ingest/mlb_schedule.py` | Refactor — unified schedule fetch |
| `src/gametime/ingest/mlb.py` | Modify — Stats API discovery + fallback order |
| `tests/test_mlb_slate_schedule.py` | Modify — Stats API cases |
| `docs/mlb_pregame_ops.md` | Modify — one paragraph |

## Off-Limits

- Frontend / BFF changes (TASK-31)
- `maxDuration` on Vercel routes (optional follow-up)
- Ensemble / TASK-14
- Removing pybaseball from **download** pipeline

## Git (worker)

- Commit on `task/TASK-34-fast-slate-statsapi`; do not push or open PR

## Definition of Done

- [ ] `curl -w '%{time_total}' http://127.0.0.1:8000/v1/slate?date=TODAY` completes **< 10s** with non-empty or empty games (not 30s+)
- [ ] `curl ...?date=2024-06-15` still works; order unchanged vs TASK-33
- [ ] pybaseball not invoked when Stats API mock succeeds (unit test)
- [ ] `pytest tests/test_mlb_slate_schedule.py tests/test_api_predictions.py` passes
- [ ] Committed on feature branch
- [ ] Handoff posted with before/after timing for today + historical date

## Handoff (required)

```text
Branch: task/TASK-34-fast-slate-statsapi
SHA: <commit>
Timing: /v1/slate?date=<today> <Xs>; /v1/slate?date=2024-06-15 <Xs>
Sample today: n_games=… first away@home
Fallback: pybaseball only when <condition>
Notes: any edge cases (doubleheader, ATH/OAK)
```

## Unblocks

- Vercel slate loads for current date within Hobby timeout
- TASK-31 E2E against production/tunnel URLs
