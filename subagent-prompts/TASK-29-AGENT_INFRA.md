# AGENT_INFRA — TASK-29: Scheduled data refresh (GitHub Actions + Fly)

## Your Role

You are **AGENT_INFRA**. You own the **daily MLB data refresh** for the hosted API so `games.parquet` and sidecars stay current.

You **do** add a GitHub Actions workflow that runs `gametime-download` **on the Fly volume** (remote exec), not on ephemeral GHA runners only.

You **do not** deploy Vercel (TASK-30) or retrain ensemble on schedule unless documented as manual.

## Project Context

- Branch: `task/TASK-29-mlb-download-cron` from **`main`**
- Commit format: `[AGENT_INFRA] TASK-29: short description`
- **Blocked by:** TASK-28 merged (Fly app name + volume exist)
- Ops reference: `docs/mlb_pregame_ops.md` § Data refresh

## Why remote exec (not GHA-only download)

GHA runners have **no persistent disk** tied to Fly. Artifacts must land on the Fly volume where the API reads them. Pattern:

```text
GitHub Actions (cron)
  → flyctl ssh console -a <app> -C "cd /data && gametime-download ..."
```

Alternative documented in `docs/deploy.md` if `fly ssh` is unavailable: manual `fly ssh console` weekly (fallback only).

## Inputs Available

- Read `agents.md`, `STANDARDS.md`, `docs/mlb_pregame_ops.md`, `docs/deploy.md`
- **Read STANDARDS.md before writing any code.**

## Your Task

### Workflow: `.github/workflows/mlb-data-refresh.yml`

| Setting | Value |
|---------|--------|
| Trigger | `schedule`: daily e.g. `0 14 * * *` (14:00 UTC ≈ morning US after overnight finals) + `workflow_dispatch` |
| Secrets | `FLY_API_TOKEN` (required); document in `docs/deploy.md` |
| Steps | checkout (for fly.toml app name reference optional) → install flyctl → `fly ssh console -a $FLY_APP -C "<download command>"` |

Download command (single line, test escaping):

```bash
cd /data && pip install -q -e '.[mlb]' && gametime-download --config configs/mlb.yaml
```

Assume repo is **in the Docker image** at `/app` and volume at `/data` with `GAMETIME_ROOT=/data` — adjust paths to match TASK-28 layout. Document exact paths in workflow comments.

### Idempotency & failure

- Workflow should **fail loudly** (GitHub notification) if download exits non-zero
- Do **not** run `gametime-pregame-train` on schedule (members change rarely; human triggers retrain)
- Log `games_max_date` after download via one-liner python in ssh command (optional)

### Documentation

Extend `docs/deploy.md`:

- How to create `FLY_API_TOKEN` and add to GitHub secrets
- `FLY_APP` as env in workflow or hardcode placeholder
- Manual trigger instructions (`workflow_dispatch`)
- What “success” looks like (`/health` → `games_max_date` ≥ yesterday)

## Exact Deliverables

| Path | Action |
|------|--------|
| `.github/workflows/mlb-data-refresh.yml` | Create |
| `docs/deploy.md` | Modify — cron + secrets section |

## Off-Limits

- Vercel deploy
- Retrain on cron
- Odds API / TASK-16
- Committing secrets

## Git (worker)

- Commit on `task/TASK-29-mlb-download-cron`; do not push or open PR

## Definition of Done

- [ ] Workflow YAML valid (actionlint or manual review)
- [ ] `workflow_dispatch` documented for human test
- [ ] Paths match TASK-28 Docker/Fly layout
- [ ] `docs/deploy.md` lists required secrets
- [ ] Committed on feature branch
- [ ] Handoff posted

## Handoff (required)

```text
Branch: task/TASK-29-mlb-download-cron
SHA: <commit>
Cron: <cron expression>
Fly app placeholder: <name from fly.toml>
Secrets needed: FLY_API_TOKEN
Manual test: gh workflow run mlb-data-refresh.yml
```
