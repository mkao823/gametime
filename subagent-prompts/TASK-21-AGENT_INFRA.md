# AGENT_INFRA — TASK-21: Predictions API v1

## Your Role

You are **AGENT_INFRA**. You own CLI entry points, service wiring, config threading, and the read-only HTTP API layer.

You **do** add an isolated FastAPI package, pytest API tests, `pyproject.toml` optional deps, and an OpenAPI schema that frontend can codegen against.

You **do not** change ensemble members, `FEATURE_COLUMNS`, ingest sidecars, train logic, or enable `use_stacking: true`. Do not refactor `cli.py` beyond a thin shared helper if needed to avoid duplicating predictor construction.

## Project Context

- Project: gametime — MLB pregame ensemble
- **Parallel track B** — runs alongside TASK-13; branch from **`main`**, not from `task/TASK-13-*`
- Branch: `task/TASK-21-predictions-api` from `main`
- Commit format: `[AGENT_INFRA] TASK-21: short description`
- Inference: `BaseballPregamePredictor` in `src/gametime/pregame/baseball/predict.py`
- Slate discovery: `slate_matchups_for_date` in `src/gametime/ingest/mlb.py` (mirror `pregame_slate` in `cli.py`)

## Inputs Available

- Read `agents.md`, `STANDARDS.md`, `docs/mlb_ensemble_roadmap.md`, `docs/mlb_pregame_ops.md`
- **Read STANDARDS.md before writing any code.**
- Reference: `src/gametime/cli.py` → `pregame_slate`, `pregame` (predictor init kwargs)
- Dataclass: `BaseballPregamePrediction` + `.as_dict()` in `predict.py`

## Your Task

Ship **Predictions API v1**: read-only HTTP service with health, single-game prediction, and daily slate using `configs/mlb.yaml`. No training or download in the request path.

### Endpoints (v1 — stable contract)

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/health` | Liveness + data freshness metadata |
| `GET` | `/v1/game` | Single matchup prediction |
| `GET` | `/v1/slate` | All matchups for a calendar date |
| `GET` | `/openapi.json` | Auto-generated (FastAPI default) |

#### `GET /health`

Response JSON:

```json
{
  "status": "ok",
  "games_max_date": "2026-06-08",
  "model_dir": "models/mlb/pregame",
  "ensemble_members": ["lgbm", "heuristic", "..."]
}
```

#### `GET /v1/game`

Query params: `home`, `away`, `date` (optional `YYYY-MM-DD`), `regular_season` (default `true`), `include_members` (default `false`).

Returns **404** when matchup is not on the slate for that date (v1 — document in app docstring).

#### `GET /v1/slate`

Query params: `date`, `regular_season`, `include_members`.

Empty slate → `200` with `"games": []`.

#### `GamePrediction` (v1 stable fields)

`home`, `away`, `date`, `pred_total`, `pred_margin`, `pred_home_final`, `pred_away_final`, `winner`, `win_prob_home`, `is_playoff`, `home_form_n`, `away_form_n`, optional `member_totals` / `member_margins`.

### Implementation guidance

1. New package under `src/gametime/api/`
2. Predictor factory in `api/deps.py` mirroring `cli.py` kwargs
3. Load predictor once at app startup (FastAPI `lifespan`)
4. Env: `GAMETIME_CONFIG` (default `configs/mlb.yaml`), `GAMETIME_ROOT`
5. `[api]` extra: `fastapi`, `uvicorn[standard]`; optional `gametime-api` console script

### Tests

`tests/test_api_predictions.py` — TestClient, mocked predictor, no network.

## Exact Deliverables

| Path | Action |
|------|--------|
| `src/gametime/api/__init__.py` | Create |
| `src/gametime/api/app.py` | Create |
| `src/gametime/api/schemas.py` | Create — Pydantic models |
| `src/gametime/api/deps.py` | Create — config + predictor factory |
| `src/gametime/api/__main__.py` | Create — uvicorn entry |
| `pyproject.toml` | Modify — `[api]` extra + script |
| `tests/test_api_predictions.py` | Create |
| `docs/mlb_pregame_ops.md` | Modify — Local API section |

## Off-Limits

- Ensemble / ingest / `features.py` changes
- CORS, stale-date blocking, cache → **TASK-22**
- Docker → **TASK-28**
- Do not push or open PR

## Git (worker)

- Commit on `task/TASK-21-predictions-api` when verify passes
- **Do not** push or open PR — orchestrator handles after Handoff

## Definition of Done

- [ ] `pytest tests/test_api_predictions.py tests/test_baseball_ensemble.py -q` passes
- [ ] OpenAPI matches documented `GamePrediction` fields
- [ ] Code **committed** on feature branch (not pushed)
- [ ] Handoff block posted

## Handoff (required)

```text
Branch: task/TASK-21-predictions-api
SHA: <commit>
Run command: uvicorn gametime.api.app:app --reload  # or gametime-api
Example curls: /health, /v1/slate, /v1/game
OpenAPI: http://127.0.0.1:8000/openapi.json
Notes: deps added, any shared helper from cli.py
```
