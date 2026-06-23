# AGENT_BACKEND — TASK-33: Slate games sorted by start time

## Your Role

You are **AGENT_BACKEND** (with small **AGENT_FRONTEND** deliverables in `web/`). You make the daily slate return games in **scheduled first-pitch order** and expose `start_time` on each game.

You **do** use the MLB Stats API schedule (`gameDate`) for ordering and optional display time.

You **do not** change ensemble members, retrain models, or add new npm dependencies.

## Project Context

- Branch: `task/TASK-33-slate-start-time` from **`main`**
- Commit format: `[AGENT_BACKEND] TASK-33: short description` (frontend files may use `[AGENT_FRONTEND]` in same branch if split commits preferred)
- Design: `docs/design/mlb-slate-mvp-spec.md` — game cards on slate grid
- **Read STANDARDS.md before writing any code.**

## Problem

Slate matchups are currently sorted alphabetically by `(away, home)` in `slate_from_games_parquet` and `fetch_slate_from_pybaseball`. The UI renders API order as-is (`SlateView.tsx`). Users expect **chronological** order (East → West).

`games.parquet` has `game_date` only — **no start time**. MLB Stats API schedule returns `gameDate` (ISO UTC), e.g. `2024-06-15T18:20:00Z`.

## Orchestrator decisions (locked)

| Decision | Value |
|----------|-------|
| Sort authority | **API** (`GET /v1/slate` games array order) — frontend must not re-sort |
| Time field | `start_time: string \| null` — ISO-8601 UTC from Stats API `gameDate` |
| Missing time | Games without a schedule match sort **after** timed games; tie-break `(away, home)` |
| Schedule source | **MLB Stats API** one request per slate date (reuse pattern from `ingest/mlb_pitchers.py`) |
| Display | Frontend shows local time on `GameCard` when `start_time` present (optional label) |
| CLI | `gametime-pregame-slate` should print same order (wire through shared helper) |

## Your Task

### 1. Schedule helper (`src/gametime/ingest/`)

Add a function (module of your choice, e.g. extend `mlb_pitchers.py` or new `mlb_schedule.py`):

```python
def fetch_slate_times_for_date(game_date: date) -> dict[tuple[str, str], str]:
    """Map (away_tricode, home_tricode) -> gameDate ISO string (UTC)."""
```

- One `GET https://statsapi.mlb.com/api/v1/schedule?sportId=1&date=YYYY-MM-DD&gameType=R&hydrate=team`
- Include **all** games on the date (not only `Final`) so upcoming slates work
- Canon tricodes with existing `_canon_from_mlb_api` helper
- `@lru_cache(maxsize=16)` on date arg (same pattern as `fetch_probables_for_date`)

### 2. Sort matchups after discovery

In `slate_matchups_for_date` (or a thin wrapper used by API + CLI):

1. Get matchups list (parquet → pybaseball fallback — unchanged discovery)
2. Load `fetch_slate_times_for_date(target_date)`
3. Attach `start_time` to each matchup dict when key matches
4. Sort: `(start_time is None, start_time or "", away, home)`

Remove alphabetical-only sort as the final order (may keep as tie-break only).

### 3. API schema + handlers

| File | Change |
|------|--------|
| `src/gametime/api/schemas.py` | Add `start_time: Optional[str]` on `GamePrediction` |
| `src/gametime/api/deps.py` | Pass `start_time` through `to_game_prediction` or slate loop |
| `src/gametime/api/app.py` | Ensure `/v1/slate` games list is sorted before return |

Update `tests/test_api_predictions.py` — slate order assertion if present; add test that mocked schedule times define order.

### 4. CLI slate table (optional column)

`gametime-pregame-slate` output: games already in sort order; optionally add **Start** column with `HH:MM` local or UTC (document UTC in help if no local tz conversion).

### 5. Frontend (small)

| File | Change |
|------|--------|
| `web/lib/api-types.ts` | `start_time?: string \| null` on `GamePrediction` |
| `web/lib/format.ts` | `formatStartTime(isoUtc: string): string` — e.g. `7:20 PM ET` or locale short time |
| `web/components/GameCard.tsx` | Show formatted start time when present (secondary text, `--font-size-sm`) |
| `web/components/SlateView.tsx` | **No client-side sort** — trust API order |

## Exact Deliverables

| Path | Action |
|------|--------|
| `src/gametime/ingest/mlb_schedule.py` (or equivalent) | Create — `fetch_slate_times_for_date` |
| `src/gametime/ingest/mlb.py` | Modify — sort matchups by start time |
| `src/gametime/api/schemas.py` | Modify — `start_time` field |
| `src/gametime/api/deps.py` / `app.py` | Modify — wire field + order |
| `src/gametime/cli.py` | Modify — slate respects sort (if not automatic) |
| `tests/test_api_predictions.py` | Modify — cover `start_time` + order |
| `web/lib/api-types.ts` | Modify |
| `web/lib/format.ts` | Modify |
| `web/components/GameCard.tsx` | Modify |

## Off-Limits

- Fly/Vercel deploy (TASK-32)
- New ensemble members (TASK-14)
- Replacing pybaseball slate discovery entirely (future task; this task only adds schedule times + sort)

## Git (worker)

- Commit on `task/TASK-33-slate-start-time`; do not push or open PR

## Definition of Done

- [ ] `GET /v1/slate?date=2024-06-15` games ordered by `start_time` ascending
- [ ] Each game includes `start_time` when Stats API has a match
- [ ] `pytest tests/test_api_predictions.py` passes
- [ ] `cd web && npm run build` passes
- [ ] `gametime-pregame-slate --date 2024-06-15` lists same order as API
- [ ] Committed on feature branch
- [ ] Handoff posted

## Handoff (required)

```text
Branch: task/TASK-33-slate-start-time
SHA: <commit>
Sample date: 2024-06-15 — first game away@home + start_time
API: curl /v1/slate?date=2024-06-15 — first/last game matchups
Web: localhost:3000/?date=2024-06-15 — cards in time order with times shown
Notes: timezone display choice
```

## Unblocks

- Better slate UX on Vercel/local without alphabetical jumpiness
- Foundation for future TASK: Stats API slate discovery (fast upcoming dates)
