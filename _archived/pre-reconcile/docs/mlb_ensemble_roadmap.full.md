# MLB pregame ensemble — roadmap & multi-agent playbook

This document is the **single source of truth** for implementing the MLB pregame ensemble in gametime. Worker agents should read it (or the section they are assigned). An **orchestration agent** triages progress, assigns windows, and pastes handoff prompts.

**Config:** `configs/mlb.yaml`  
**Train entry:** `gametime-pregame-train --config configs/mlb.yaml`  
**Artifacts:** `models/mlb/pregame/`, `reports/mlb/eval/pregame_summary.json`

---

## Goal

Combine several **member models** (different approaches) into one pregame prediction via a **weighted average** (and optional later: Vegas blend, stacking). Ship training, eval, inference, and CLI for `sport: mlb`.

**How to improve after v1:** follow [Iteration SOP (members + ensemble)](#iteration-sop-members--ensemble) — iterate members and LGBM first, refit blend on val only, judge on test; add new members only when signal is orthogonal and decorrelated.

---

## Current state (May 2026)

Production track is **`main`** (direct merge; `feature/mlb-ensemble-integration` exists but ops uses `main`).

| Area | Status |
|------|--------|
| Phases P0–P4, W6b–W6g, W6d–W6e, W6-eval, W6-max-weight, W6-stack-prod | ✅ Merged |
| D-tier members W6h–W6k, W6m–W6o | ✅ Merged — **13 members** in `ensemble.json` |
| W6-statsapi-games, W7 slate, W8 slate backtest | ✅ Merged |
| W6-sp-live-fip + slate precision | ✅ Merged — live Prob SP + distinct FIP on slate |
| W6-eval 13-member refresh | ✅ Merged — holdout go/no-go in `docs/mlb_pregame_ops.md` |
| Production blend | **`use_stacking: false`** (linear weights) — 2025 test winner 55.7% vs stacked 53.9% |
| **W9 total calibration** | ✅ Merged — `total_enabled: false` (marginal test MAE gain; tail bias remains) |
| **R1 ensemble research** | ✅ Complete — [research backlog](mlb_ensemble_research_backlog.md) |
| **W6l XGBoost** | ❌ **Do not assign** — decorrelation audit (r ≥ 0.94) |
| **W6a Vegas** | ⏸ Deferred — no `ODDS_API_KEY` |

**Daily ops:** `gametime-download` → `gametime-pregame-slate --regular-season --decimals 2` (no `pregame-train` unless members/splits change). See `docs/mlb_pregame_ops.md`.

**Research backlog:** [docs/mlb_ensemble_research_backlog.md](mlb_ensemble_research_backlog.md) — ranked proposals from R1; orchestrator assigns implementation windows from this doc only after research Handoff.

---

## v1 status (shipped on `feature/mlb-ensemble-integration`)

| Piece | Path / signal |
|-------|----------------|
| Members | `heuristic`, `lgbm`, `runs_strength` under `models/` |
| Ensemble | `ensemble.py` — `combine`, `fit_weights`, `ensemble.json` |
| Train / eval | `train.py` → `reports/mlb/eval/pregame_summary.json` |
| Inference | `predict.py` — `BaseballPregamePredictor` |
| CLI | `cli.py` — `pregame_train` + `pregame` for `sport.family == "baseball"` |

**Known v1 quirk:** val grid search can collapse to a single member (e.g. 100% `runs_strength`). Treat optional **W6e** (weight constraints) as follow-up before production.

Reference patterns: basketball `src/gametime/pregame/predict.py` (Vegas blend); `features.py` FEATURE_ROADMAP for data gaps.

---

## Target layout

```text
src/gametime/pregame/baseball/
  prediction.py              # MemberPrediction, EnsemblePrediction
  models/
    base.py                  # member protocol
    heuristic.py             # v1
    lgbm.py                  # v1
    runs_strength.py         # v1
    poisson.py               # optional W6b
    pythagorean.py           # optional W6f
    elo.py                   # optional W6g
    pitcher.py               # optional W6h (after ingest)
    …                        # see Member catalog
  ensemble.py                # combine(), fit_weights(), optional stack
  train.py                   # train members + ensemble eval + ensemble.json
  predict.py                 # BaseballPregamePredictor (+ optional Vegas)

models/mlb/pregame/
  total_final.txt
  margin_final.txt
  home_win.txt
  ensemble.json              # members[] grows with optional windows
  meta.json
```

---

## Phases

| Phase | ID | Worker branch | Deliverable | Done when |
|-------|-----|---------------|-------------|-----------|
| Foundation | **P0** | `…/w1-p0-foundation` | `prediction.py`, `models/base.py`, `heuristic.py`, `ensemble.py` (equal weights) | Merged; train reports heuristic + ensemble_equal on val/test |
| LGBM member | **P1** | `…/w2-p1-lgbm` | `models/lgbm.py`, train loops both members | Merged; `members.lgbm` in summary JSON |
| Runs strength | **P3** | `…/w3-p3-runs-strength` | `models/runs_strength.py`, config | Merged; three members in eval |
| Val weights | **P2** | `…/w4-p2-weights` | `fit_weights`, `ensemble.json` | Merged; weights fit on val only |
| Inference | **P4** | `…/w5-p4-predict` | `predict.py`, CLI | Merged; `gametime-pregame` works for mlb |
| Optional | **P5+** | `…/w6a-…` … `w6n-…` | See [Optional windows](#optional-windows-w6) and [Member backlog](#ensemble-member-backlog) | Per window; refit weights after each new member |

(Branch prefix: `feature/mlb-ensemble/` for workers; integration: `feature/mlb-ensemble-integration`.)

**v1 phases P0–P4 are complete.** New work branches from `feature/mlb-ensemble-integration` (or `main` after merge).

**Note:** P2 (weights) is implemented after P1+P3 so all members exist. Phase IDs in prompts match this table.

---

## Splits & discipline

From `configs/mlb.yaml`:

- **Train:** 2021–2023 regular season  
- **Val:** 2024 RS (tune weights, early stopping, stacker fit)  
- **Test:** 2025 RS (report only; never fit weights or stacker on test)

Use `gametime.train.common.split_table_by_season` and `build_training_table` for all members.

**Holdout (W6-eval):** `configs/mlb.yaml` uses val **2024** / test **2025**. Expect val→test MAE gaps (~0.20 runs on total) — normal year shift, not a split bug. Re-run [W6-eval](#w6-eval--holdout-splits-recommended) if splits or seasons change.

---

## Post-v1 improvement strategy (recommended order)

This section captures the **post-ship** plan after W6b–W6g (six members + stacking in train). Goal: improve **real pregame signal** and **honest measurement**, not add correlated members on the same form stats.

### What the current eval shows (`reports/mlb/eval/pregame_summary.json`)

Metrics below are **val 2024 / test 2025** (re-run train after config or member changes). Top-level `val` / `test` in the JSON are **LGBM solo** only — use `ensemble*` and `members.*` blocks for blend comparisons.

| Layer | Val total MAE | Test total MAE | Test winner% | Notes |
|-------|---------------|----------------|--------------|-------|
| `runs_strength` (solo) | ~3.41 | ~3.61 | ~55% | Best solo total on val; grid puts **~75%** weight on it |
| `ensemble` (val-tuned) | ~3.41 | ~3.61 | ~55% | Beats `ensemble_equal` by ~0.007 test total MAE |
| `ensemble_equal` (6 members) | ~3.42 | ~3.62 | ~55% | Tuned weights add little → members highly correlated |
| `ensemble_stacked` (Ridge, val fit) | ~3.39 | **~3.60** | ~54% | Best test total MAE; **worse** test winner% vs linear; `use_stacking: false` |
| `elo` (solo) | ~3.43 | ~3.62 | ~54% | Strong margin / winner on val |
| `lgbm` (solo) | ~3.42 | ~3.63 | ~52% | Only tree on `FEATURE_COLUMNS`; `has_*` placeholders often 0 until W6h+ |

**Calibration note (test):** ensemble totals cluster ~8.9 runs while actuals span ~5–14; high/low scoring games are under-fit. Address via new signal (park, SP) or explicit calibration work, not weight grid alone.

**Takeaways for orchestrator:**

1. **More same-flavor members** (another rolling-runs heuristic, XGB on form columns) has **low ROI** — errors are highly correlated.
2. **Blend/meta fixes** are cheap (stacking toggle, max weight cap, proper holdout).
3. **Features + ingest** (starting pitcher, park, …) are the **highest long-term ROI** — unlock both a new member **and** a stronger `lgbm`.
4. Prefer **one orthogonal member per window** + val refit; extend `FEATURE_COLUMNS` when ingest adds columns.

### Recommended windows (orchestrator assignment order)

| Order | Window | Branch / doc | Focus | When |
|-------|--------|--------------|-------|------|
| **▶ NEXT** | **W10 SP/lineup coverage** | `w10-sp-lineup-coverage` | Backfill train sidecars; fix 0% lineup train coverage | [R1 backlog #1](mlb_ensemble_research_backlog.md) |
| — | **Maintenance** | — | `gametime-download` + slate | Ongoing |
| — | **W9 total calibration** | `w9-total-calibration` | Post-blend total mapping | ✅ Merged; `total_enabled: false` |
| — | **W6-eval refresh** | `w6-eval-13member-refresh` | 13-member holdout + decorrelation audit | ✅ May 2026 |
| — | **Linear prod blend** | `w6-stack-linear-prod` | `use_stacking: false` | ✅ Shipped |
| 2 | **W6a** | `w6a-vegas` | Market blend / member | ⏸ deferred — needs odds |
| — | **W6l XGBoost** | `w6l-xgb` | XGB on same `FEATURE_COLUMNS` | ❌ gated |
| — | **W9b win-prob cal** | `w9b-win-prob-calibration` | Platt/isotonic on `win_prob_home` | Low priority — winner% OK on test |

**Do not prioritize:** W6l (XGB on same columns as LGBM), extra form heuristics, or finer grid alone without new signal.

### Per-window checklist (any new member, including W6h)

1. Ingest / features (no leakage; `has_*` flags real when populated).
2. `models/<member>.py` → `MemberPrediction`.
3. Extend `FEATURE_COLUMNS` + **retrain `lgbm`** if new columns are game-level pregame signal.
4. Wire `train.py` + `BaseballPregamePredictor` + `configs/mlb.yaml` `members`.
5. **Val-only** refit `ensemble.json` (weights + stacker).
6. `pytest tests/test_baseball_ensemble.py` + `gametime-pregame-train`.
7. Handoff with val + **holdout test** metrics (2025 test season).

### Iteration SOP (members + ensemble)

Use this loop for **every** improvement — whether you change one member, add ingest, or tune the blend. Do **not** skip member retrain when using an ensemble; the blend only combines what members already know.

#### What moves the needle (ROI order)

| Lever | Why | Roadmap |
|-------|-----|---------|
| **Ingest + features** | New signal for `lgbm` *and* orthogonal members; fixes placeholder `has_*` | **W6h** → W6i–k |
| **Honest measurement** | Val/test must be different RS years; judge go/no-go on **test** | **W6-eval** (shipped) |
| **Blend discipline** | Caps, optional stacking; small gains if members stay correlated | **W6-max-weight**, **W6-stack-prod** |
| **Total calibration** | Preds regress to ~8.9 runs; weak on very low/high actual totals | **W9** ✅ shipped (`total_enabled: false`); tails need **new signal** — see R1 |
| **More form-style members** | Errors r≈0.94–1.0 across LGBM / Poisson / runs_strength | Defer **W6l** and duplicate heuristics |

#### Standard iteration loop

```text
1. Signal     — ingest / FEATURE_COLUMNS (no leakage; has_* real when populated)
2. Members    — implement or fix ONE member (or retrain lgbm only)
3. Train      — gametime-pregame-train on train 2021–2023
4. Blend      — fit weights + stacker on val 2024 ONLY → ensemble.json
5. Measure    — compare on test 2025:
                 • each member solo
                 • ensemble_equal
                 • ensemble (tuned)
                 • ensemble_stacked (if considering prod stack)
6. Ship       — update config / ops only after test go/no-go
```

**Rules**

- Change **one** of: ingest/features, member logic, or blend rule per experiment.
- **Never** tune weights, stacker, or member hyperparameters on the test split.
- After any new game-level column: extend `FEATURE_COLUMNS` and **retrain `lgbm`** in the same PR.
- After any member add/remove: **val-only** refit of `ensemble.json` (weights + stacker).

#### When to iterate an existing member (no new model)

Do this when:

- You are improving **signal** the member already uses (e.g. better form window, fixed leakage).
- You extended `FEATURE_COLUMNS` and need a stronger **`lgbm`** (only learner on those columns).
- One target matters most (e.g. margin / winner) and a solo member leads on **test** for that target.

Skip “another pass on the same heuristic” if a **correlation audit** on `val_predictions.parquet` / `test_predictions.parquet` shows total-error r ≥ ~0.94 vs the rest — you will not get blend diversity.

#### When to add a new ensemble member

Add a member when **all** of the following hold:

| Gate | Criterion |
|------|-----------|
| **Orthogonal signal** | Uses information existing members do not (SP, park, weather, market — not another rolling-runs clone). |
| **Coverage** | Ingest populates real `has_*` flags; member weight is not stuck at `min_member_weight` only after val refit. |
| **Solo or equal-weight lift** | Competitive solo **test** MAE/winner%, **or** `ensemble_equal` improves on **test** (proves diversity, not val grid luck). |
| **Decorrelation** | Pearson r of total errors vs existing members on **val** ideally **&lt; ~0.85** (avg \|r\| across incumbents). |

**Do not add** when:

- The idea duplicates form / rolling-runs / same `FEATURE_COLUMNS` tree (**W6l** low priority).
- Val weights assign ~floor only → fix ingest first.
- Tuned **ensemble** on **test** is worse than best solo on the metric you care about → fix members or weights before adding more.

**Heuristic**

```text
New member worth it  ≈  (test Δ ensemble_equal total_mae) > noise (~0.01 runs)
                    AND  (avg |r| vs incumbent total errors on val) < ~0.85
```

If correlation stays ~0.95+, invest in **features + one orthogonal member** (W6h, W6i, …), not a seventh similar model.

#### Iterate members vs iterate ensemble meta

| Phase | What you change | What you measure |
|-------|-----------------|------------------|
| **Signal** | Download, park, SP, weather | `has_*` fractions, sidecar row counts |
| **Members** | One new or improved `models/<member>.py` | Solo test MAE / winner% |
| **LGBM** | Retrain when `FEATURE_COLUMNS` change | Solo test vs prior |
| **Blend** | Val-only `fit_weights`, optional max-weight cap / stack | `ensemble` vs `ensemble_equal` on **test** |
| **Prod** | `use_stacking`, `ensemble.json`, CLI | Live deduped preds vs `game_outcomes.parquet` |

You **always** update members (and LGBM when features change) **before** refitting the blend. Meta-layer changes alone cannot fix missing pregame signal.

#### Stacking go/no-go (after W6-eval)

**13-member holdout (May 2026, 2025 test):** `ensemble_stacked` beats linear on total MAE (**3.582 vs 3.609**) and margin MAE (**3.500 vs 3.505**) but **loses on winner%** (**53.9% vs 55.7%**). Production ships **`use_stacking: false`** unless product accepts ~1.8 pp winner hit for ~0.03 runs total MAE. See [W6-stack-prod](#w6-stack-prod--enable-stacking-at-inference) and `docs/mlb_pregame_ops.md`.

#### Pre-W6h gate (orchestrator)

Before assigning W6i+:

- `data/mlb/processed/pitcher_games.parquet` exists and `has_starting_pitcher_frac` in summary is **&gt; 0**
- `pitcher` appears in `ensemble.json` `members` and config `pregame.ensemble.members` matches artifacts
- Re-run train after ingest; handoff includes val + test tables from [Iteration SOP](#iteration-sop-members--ensemble)

---

## Git branching (one branch per agent window)

Each **worker** agent works on its **own branch**. An **integration branch** collects finished phases before optional merge to `main`.

### Branch names

| Branch | Who | Purpose |
|--------|-----|---------|
| `feature/mlb-ensemble-integration` | Integration | Merge target after each worker phase; orchestrator tracks this |
| `feature/mlb-ensemble/w1-p0-foundation` | W1 | P0 |
| `feature/mlb-ensemble/w2-p1-lgbm` | W2 | P1 |
| `feature/mlb-ensemble/w3-p3-runs-strength` | W3 | P3 |
| `feature/mlb-ensemble/w4-p2-weights` | W4 | P2 |
| `feature/mlb-ensemble/w5-p4-predict` | W5 | P4 |
| `feature/mlb-ensemble/w6*` | W6+ | Optional — see [Optional windows](#optional-windows-w6) (`w6a-vegas` … `w6n-travel-rest`) |

### Workflow

1. **Once (before W1):** From default branch (`main`), create integration branch:
   ```bash
   git fetch origin
   git checkout main
   git pull origin main
   git checkout -b feature/mlb-ensemble-integration
   ```
   Orchestrator chat stays on `main` or `feature/mlb-ensemble-integration` — **read-only** audit; no feature commits in orchestrator chat unless unblocking.

2. **Each worker window:**
   ```bash
   git fetch origin
   git checkout feature/mlb-ensemble-integration
   git pull origin feature/mlb-ensemble-integration   # if pushed; else merge locally
   git checkout -b feature/mlb-ensemble/wN-...
   ```
   Implement phase → run verify commands → **commit on worker branch** (see below) → Handoff with branch name + commit SHA.

3. **After worker Handoff (you or orchestrator):** Merge worker branch into integration:
   ```bash
   git checkout feature/mlb-ensemble-integration
   git merge --no-ff feature/mlb-ensemble/w2-p1-lgbm -m "mlb ensemble: P1 lgbm member"
   ```
   Optional: `git push -u origin feature/mlb-ensemble-integration` when ready.

4. **Parallel W2 + W3:** Both branch from the **same** `feature/mlb-ensemble-integration` commit (after W1 merged). Merge W2, then merge W3 (resolve conflicts in `train.py` / `ensemble` eval if needed). **Do not start W4** until both are on `feature/mlb-ensemble-integration`.

5. **After P4:** Open one PR: `feature/mlb-ensemble-integration` → `main`, or squash-merge locally when satisfied.

### Commit rules (workers)

- Work **only** on the assigned `feature/mlb-ensemble/wN-...` branch.
- **Commit** when the phase is complete and `gametime-pregame-train` (or scoped checks) pass. Use one commit per phase unless the user asks to split.
- **Do not** commit on `main` directly.
- **Do not** `push`, `force-push`, or open a PR unless the user explicitly asks.
- **Do not** run destructive git (`reset --hard`, `clean -fdx`, force-push to `main`).

### Commit message format

```text
mlb ensemble: <phase-id> <short description>

e.g. mlb ensemble: P0 foundation, heuristic, equal ensemble eval
```

### Orchestrator git duties

- Report `git branch --show-current` and whether `feature/mlb-ensemble-integration` exists.
- Include **exact branch name** in every worker prompt.
- After Handoff: confirm worker branch merged into `feature/mlb-ensemble-integration` before assigning dependent phases (gate W4 on W2+W3 merged).
- Never assign two workers the **same** branch name.

---

## Orchestration agent

### Role

The orchestration agent **does not implement large features** unless unblocking. It:

1. Reads this file and inspects `src/gametime/pregame/baseball/` + `models/mlb/pregame/`.
2. Checks **git state**: integration branch `feature/mlb-ensemble-integration`, which worker branches exist, what is merged (see [Git branching](#git-branching-one-branch-per-agent-window)).
3. Determines which phases are **done / in progress / blocked**.
4. Assigns **exactly one phase** to the next worker window (or parallel W2+W3 after P0) with the **exact branch name** to create.
5. Pastes the matching **worker prompt** from [Worker prompts](#worker-prompts) below.
6. After a worker finishes, verifies claims (files, train, **branch merged to `feature/mlb-ensemble-integration`**) and updates status in the handoff reply.
7. For **quality audits** (abnormalities, stack vs linear, member ROI, decorrelation / W6l gate), re-run train and inspect `reports/mlb/eval/` — see [W6-eval](#w6-eval--holdout-splits-recommended) and `docs/mlb_pregame_ops.md`. Use a separate eval chat; do not assign W6l unless audit passes.

### How to specify the orchestration agent

Use **one** of these (best: combine 1 + 2):

| Method | How |
|--------|-----|
| **@ file** | In a new Cursor chat: `@docs/mlb_ensemble_roadmap.md` plus the [Orchestrator prompt](#orchestrator-prompt-copy-paste) below. |
| **Rule (optional)** | Add `.cursor/rules/mlb-ensemble.mdc` with `globs: src/gametime/pregame/baseball/**` pointing agents to this doc (see repo `.cursor/rules/` if present). |
| **Pin in chat** | Paste the Orchestrator prompt as the **first message** of a dedicated "MLB ensemble orchestrator" chat; keep that chat open only for triage/handoffs. |
| **Resume** | Worker ends with **Handoff**; you paste Handoff into orchestrator chat → orchestrator outputs the next worker prompt. |
| **Git** | One branch per worker; merge into `feature/mlb-ensemble-integration` before the next gated phase — see [Git branching](#git-branching-one-branch-per-agent-window). |

### Orchestrator prompt (copy-paste)

```markdown
You are the **orchestration agent** for the MLB pregame ensemble in the gametime repo.

## Authority
Follow `docs/mlb_ensemble_roadmap.md` (attached / @docs/mlb_ensemble_roadmap.md). Do not invent a different architecture.

**Default next window:** **W10 SP/lineup coverage** — [P1](mlb_ensemble_research_backlog.md#p1--historical-sp--lineup-sidecar-backfill). Implementation workers start only from ranked `recommend: implement` rows in `docs/mlb_ensemble_research_backlog.md`. **Do not assign W6l (XGB)**. **W6a** deferred unless research unblocks odds ingest.

## Your job (this chat only)
1. **Audit** — Phases P0–P4 + W6b–W6g: files, `reports/mlb/eval/pregame_summary.json`, `models/mlb/pregame/ensemble.json`.
2. **Audit git** — `git branch -a | grep mlb-ensemble`; which worker branches are merged into `feature/mlb-ensemble-integration` (`git log feature/mlb-ensemble-integration --oneline -10`).
3. **Do not** implement a full phase yourself unless a 5-line unblock is needed (e.g. broken import). Do not commit on worker branches.
4. **Assign** — Output ONE ready-to-paste **worker prompt** (from Worker prompts) including **Git** subsection with exact branch name. W2 and W3 may run in parallel only after W1 is merged to `feature/mlb-ensemble-integration`.
5. **Gate** — Do not assign P2 (W4) until W2 and W3 are both merged to `feature/mlb-ensemble-integration` and all three members run in train.
6. **Handoff** — When I paste a worker Handoff, confirm merge status; if not merged, tell me the merge commands before assigning the next window.
7. **Optional track** — Do **not** assign W6a unless un-deferred. W6b–W6g are done; after PR to `main`, assign **W7** (today's slate) per [W7](#w7--todays-slate-production-predict).

## Output format (every reply)
### Status
| Phase | State | Evidence |
| P0 | done / not started | … |
| … | | |

### Git
| Branch | Exists | Merged to feature/mlb-ensemble-integration |
| feature/mlb-ensemble-integration | yes/no | — |
| feature/mlb-ensemble/w… | … | yes/no |

### Next action
- **Window:** W# / Phase P#
- **Branch:** `feature/mlb-ensemble/wN-...`
- **Base:** `feature/mlb-ensemble-integration` @ `<short-sha or main if not created yet>`
- **Parallel:** yes/no
- **Worker prompt:** (full markdown fenced block to copy into a new agent chat)

### Merge reminder (if previous worker done but not merged)
\`\`\`bash
git checkout feature/mlb-ensemble-integration
git merge --no-ff feature/mlb-ensemble/wN-... -m "mlb ensemble: ..."
\`\`\`

### Risks / blockers
- …

## Commands you may run to audit
git branch -a | grep mlb-ensemble || true
git log feature/mlb-ensemble-integration --oneline -5 2>/dev/null || echo "integration branch not created yet"
gametime-pregame-train --config configs/mlb.yaml
ls models/mlb/pregame/
```

### Orchestrator checklist (quick audit)

| Check | Path / signal |
|-------|----------------|
| P0 | `ensemble.py`, `models/heuristic.py`, `prediction.py` exist |
| P1 | `models/lgbm.py`; summary has `members.lgbm` |
| P3 | `models/runs_strength.py`; summary has `members.runs_strength` |
| P2 | `models/mlb/pregame/ensemble.json` with `weights.total` / `weights.margin` |
| P4 | `predict.py`; `cli.py` `pregame()` uses baseball predictor for `mlb` |
| P5+ | Optional: per [W6 quick index](#w6--quick-index-orchestrator) |

---

## Worker prompts

Copy **one** block into a **new** agent chat. Add: `@docs/mlb_ensemble_roadmap.md`

---

### W1 — P0 Foundation

```markdown
Implement Phase **P0** per @docs/mlb_ensemble_roadmap.md.

## Git (required)
1. If missing, create integration branch from main: `git checkout main && git pull && git checkout -b feature/mlb-ensemble-integration`
2. Create worker branch: `git checkout feature/mlb-ensemble-integration && git checkout -b feature/mlb-ensemble/w1-p0-foundation`
3. Work only on this branch. Commit when P0 passes verify (do not push unless user asks).

## Scope
prediction.py, models/base.py, models/heuristic.py, ensemble.py (equal weights); extend train to report heuristic + ensemble_equal on val/test. No CLI predict. No runs_strength. No val weight tuning.

## Verify
gametime-pregame-train --config configs/mlb.yaml

At end, output **Handoff** (include branch + commit SHA) and W2 prompt for the next window.
```

---

### W2 — P1 LGBM member

```markdown
Implement Phase **P1** per @docs/mlb_ensemble_roadmap.md.

## Git (required)
Prerequisite: W1 merged into `feature/mlb-ensemble-integration`.
`git checkout feature/mlb-ensemble-integration && git pull 2>/dev/null; git checkout -b feature/mlb-ensemble/w2-p1-lgbm`
Commit on this branch when done (no push unless user asks).

## Scope
models/lgbm.py; train collects lgbm + heuristic on val/test; equal-weight ensemble metrics in pregame_summary.json. No val weight tuning. No runs_strength.

Read existing P0 files first. End with Handoff + W3 prompt.
```

---

### W3 — P3 runs_strength member

```markdown
Implement Phase **P3** per @docs/mlb_ensemble_roadmap.md.

## Git (required)
Prerequisite: W1 merged into `feature/mlb-ensemble-integration`. May run parallel with W2 (branch from same integration commit).
`git checkout feature/mlb-ensemble-integration && git checkout -b feature/mlb-ensemble/w3-p3-runs-strength`
Commit when done (no push unless user asks).

## Scope
models/runs_strength.py (no leakage); config in configs/mlb.yaml; train eval for three members + equal ensemble. No val weight tuning.

Read existing baseball ensemble files first. End with Handoff + W4 prompt.
```

---

### W4 — P2 Val-tuned weights

```markdown
Implement Phase **P2** per @docs/mlb_ensemble_roadmap.md.

## Git (required)
Prerequisite: W2 and W3 both merged into `feature/mlb-ensemble-integration`.
`git checkout feature/mlb-ensemble-integration && git checkout -b feature/mlb-ensemble/w4-p2-weights`

## Scope
ensemble.fit_weights (grid on val); write models/mlb/pregame/ensemble.json; separate weights for total/margin; test eval with frozen weights. No CLI yet.

End with Handoff + W5 prompt.
```

---

### W5 — P4 Predictor + CLI

```markdown
Implement Phase **P4** per @docs/mlb_ensemble_roadmap.md.

## Git (required)
Prerequisite: W4 merged into `feature/mlb-ensemble-integration`.
`git checkout feature/mlb-ensemble-integration && git checkout -b feature/mlb-ensemble/w5-p4-predict`

## Scope
predict.py BaseballPregamePredictor; cli.py pregame for baseball; document commands. Optional: log to pregame parquet.

Verify: gametime-pregame-train && gametime-pregame --config configs/mlb.yaml --home NYY --away BOS --regular-season

End with Handoff; suggest PR `feature/mlb-ensemble-integration` → `main` if v1 complete.
```

---

## Optional windows (W6+)

One **optional window = one worker chat = one branch**. Branch from latest `feature/mlb-ensemble-integration` (or `main` if v1 is merged). Merge to integration; **refit `ensemble.json` on val** whenever a new **member** is added.

### Priority tiers

| Tier | ID | Branch | Focus | Why first |
|------|-----|--------|-------|-----------|
| **A — quality / ops** | W6d | `w6d-tests` | Tests, parquet export, leakage checks | Protect refactors; reproducible eval |
| | W6e | `w6e-weight-floor` | Min member weight, finer grid, tie-break | Fix single-member collapse; diversify blend |
| **B — blend / meta** | W6a | `w6a-vegas` | ⏸ **Deferred** — needs `ODDS_API_KEY` or manual lines only | Skip for now; see [W6a deferred](#w6a--vegas-deferred) |
| | W6c | `w6c-stacking` | Ridge/meta on val | After W6b; may beat linear weights if members decorrelate |
| **C — new members (low data)** | W6b | `w6b-poisson` | Poisson / run-rate generative | ✅ done |
| | W6f | `w6f-pythagorean` | Pythagorean win% → implied runs | ✅ done |
| | W6g | `w6g-elo` | Baseball Elo → margin/total | ✅ done |
| **A′ — eval / blend** | W6-eval | `w6-eval-holdout` | Test season 2025; honest stack vs linear | Optional but recommended before prod stack |
| | W6-stack-prod | `w6-stack-prod` | `use_stacking: true` at inference if holdout wins | After W6-eval or explicit user OK |
| | W6-max-weight | `w6-max-weight` | Max member weight cap in `fit_weights` | If weights still collapse (e.g. 75% one member) |
| **D — new members (needs ingest)** | W6h | `w6h-pitcher` | ▶ **Next** — M1 ingest + SP/bullpen + `pitcher` member | [W6h prompt](#w6h--pitcher-copy-paste-worker-prompt) |
| | W6i | `w6i-park` | Park factor on total | Stable run environment signal |
| | W6j | `w6j-weather` | Wind/temp/humidity on total | Game-total lever when weather ingest exists |
| | W6k | `w6k-lineup` | Lineup wOBA / platoon | Needs lineup ingest |
| | W6o | `w6o-series-context` | Series game context + prior-game style | Games-only context for totals |
| **E — experimental** | W6l | `w6l-xgb` | XGBoost member | Tree diversity vs LGBM |
| | W6m | `w6m-h2h` | Head-to-head shrinkage | Sparse; regular-season only |
| | W6n | `w6n-travel-rest` | Travel miles, getaway, DH | Schedule stress beyond `rest_days` |
| | W6o | `w6o-series-context` | Series game index + prior-game context | Keep as one member (avoid splitting correlated sub-members) |

Run **A** before adding many members. **D** items depend on `features.py` ingest (see FEATURE_ROADMAP).

### Optional track status

| Window | Status | Notes |
|--------|--------|-------|
| W6d–W6g, W6-max-weight, W6-stack-prod | ✅ done | tests, weights, Poisson, stacking, Pythagorean, Elo, weight cap |
| W6h–W6k, W6m–W6o | ✅ done | pitcher, park, weather, lineup, h2h, travel_rest, series_context |
| W6-statsapi-games, W6-sp-live-fip, W7, W8 | ✅ done | hybrid games, live FIP, slate CLI, slate backtest |
| W6-eval 13-member refresh | ✅ done | decorrelation audit gates W6l |
| Linear prod blend | ✅ done | `use_stacking: false` |
| W9 total calibration | ✅ done | `total_enabled: false`; isotonic val-fit |
| **R1 research** | ✅ done | Feature/member proposals — [backlog](mlb_ensemble_research_backlog.md) |
| **W10 SP/lineup coverage** | ▶ **next** | [P1](mlb_ensemble_research_backlog.md#p1--historical-sp--lineup-sidecar-backfill) |
| **W6a** | **⏸ deferred** | No `ODDS_API_KEY`; skip unless user un-defers |
| **W6l XGBoost** | ❌ **gated out** | [W6l](#w6l--xgboost-gated) — r ≥ 0.94 vs incumbents on test |

**Orchestrator:** Default assign **W9** after linear prod ship. Do **not** assign W6l unless decorrelation audit passes. Do not assign W6a unless un-deferred.

### Original W6 windows (expanded)

| Window | Branch | Deliverable | Done when |
|--------|--------|-------------|-----------|
| **W6a Vegas** | `w6a-vegas` | ⏸ **Deferred** — see [W6a deferred](#w6a--vegas-deferred) | — |
| **W6b Poisson** | `w6b-poisson` | `models/poisson.py`; team attack/def rates on train; member preds | `members.poisson` in summary; weights refit |
| **W6c Stacking** | `w6c-stacking` | `ensemble.stack_fit` / `stack_predict`; compare to `fit_weights` | Summary reports stack vs linear on val/test |
| **W6d Tests** | `w6d-tests` | pytest + parquet export | CI-green unit tests |
| **W6e Weight floor** | `w6e-weight-floor` | `min_member_weight`, finer grid | Non-degenerate `ensemble.json` weights |

### W6 worker prompt template

Every optional worker prompt must be **self-contained** (include `@docs/mlb_ensemble_roadmap.md` at top). Minimum blocks: **Git**, **Scope**, **Verify**, **Handoff**.

```markdown
@docs/mlb_ensemble_roadmap.md

Implement optional window **W6x — <title>** per the roadmap optional section.

## Git (required)
git fetch origin
git checkout feature/mlb-ensemble-integration
git pull origin feature/mlb-ensemble-integration 2>/dev/null || true
git checkout -b feature/mlb-ensemble/w6x-<slug>

Work only on this branch. Commit when verify passes (no push unless user asks).
Commit message: mlb ensemble: W6x <short description>

## Scope
(specific to window — see optional table)

## Verify
gametime-pregame-train --config configs/mlb.yaml
# plus window-specific CLI/tests

## Handoff
(branch, commit, merged to feature/mlb-ensemble-integration yes/no, metrics, blockers)
```

### W6a — Vegas (deferred)

**Status: ⏸ not scheduled** for the current MLB track.

**Why deferred:** This project does not use `ODDS_API_KEY`. `--with-vegas` would fail in normal workflows and adds `vegas.py` MLB team mapping + CLI surface with little benefit.

**When to revisit:**
- You obtain an Odds API key and want live `baseball_mlb` lines, or
- You only need **manual** `--spread` / `--total` blending (no API) — implement a thin blend in `baseball/predict.py` only; skip full `vegas.py` + `--with-vegas` until then.

**Do not block** merging `feature/mlb-ensemble-integration` → `main` on W6a.

<details>
<summary>Archived W6a worker prompt (use only if un-deferring)</summary>

```markdown
@docs/mlb_ensemble_roadmap.md
Implement optional **W6a — Vegas blend** for MLB pregame.
… (mirror NBA predict.py; extend vegas.py for baseball_mlb)
```
</details>

### W6b — Poisson (next optional window)

Copy **everything** in the fenced block below into a new worker chat:

````markdown
@docs/mlb_ensemble_roadmap.md

You are **Window W6b — optional Poisson member** for the MLB pregame ensemble in gametime.

## Authority
Follow `docs/mlb_ensemble_roadmap.md` (Optional windows → W6b). W6a (Vegas) is **deferred** — do not implement Vegas in this window.

## Git (required)
**Prerequisite:** W6e merged into `feature/mlb-ensemble-integration` (pull latest).

    git fetch origin
    git checkout feature/mlb-ensemble-integration
    git pull origin feature/mlb-ensemble-integration 2>/dev/null || true
    git checkout -b feature/mlb-ensemble/w6b-poisson

- Work **only** on `feature/mlb-ensemble/w6b-poisson`.
- **Commit** when verify passes (do not push or open PR unless the user asks).

**Commit message:** `mlb ensemble: W6b poisson member`

## Scope
1. Add `src/gametime/pregame/baseball/models/poisson.py`:
   - Estimate team attack/def (or λ) rates on **train only** using shifted cumulative stats (no leakage).
   - `predict()` → `MemberPrediction` with `total` and `margin` per row.
2. Wire into `train.py` and `BaseballPregamePredictor` (same member loop as other models).
3. Add `poisson` to `configs/mlb.yaml` → `pregame.ensemble.members`.
4. **Refit** `ensemble.json` on val (`min_member_weight` / `grid_step` from config).
5. Report `members.poisson` in `pregame_summary.json`.

## Out of scope
- Vegas / odds API (W6a deferred)
- Stacking (W6c)
- New ingest (pitcher, weather, etc.)

## Constraints
- Reuse `BaseballMemberModel` protocol.
- Val-only weight fitting; frozen weights on test.
- Extend `tests/test_baseball_ensemble.py` if grid/member count assumptions change.

## Verify

    pytest tests/test_baseball_ensemble.py -q
    gametime-pregame-train --config configs/mlb.yaml
    gametime-pregame --config configs/mlb.yaml --home NYY --away BOS --regular-season

If CLI not on PATH:

    PYTHONPATH=src python3 -m pytest tests/test_baseball_ensemble.py -q
    PYTHONPATH=src python3 -m gametime.cli pregame-train --config configs/mlb.yaml
    PYTHONPATH=src python3 -m gametime.cli pregame --config configs/mlb.yaml --home NYY --away BOS --regular-season

## Handoff (required at end)
Include: branch, commit SHA, merged to `feature/mlb-ensemble-integration` yes/no, `members.poisson` metrics, refit `ensemble.json` weights, files changed, blockers.

## Merge reminder (for user after W6b)

    git checkout feature/mlb-ensemble-integration
    git merge --no-ff feature/mlb-ensemble/w6b-poisson -m "mlb ensemble: W6b poisson member"
````

### W6c — Stacking (queued after W6b)

Copy **everything** in the fenced block below when W6b is merged:

````markdown
@docs/mlb_ensemble_roadmap.md

You are **Window W6c — optional Ridge stacking** for the MLB pregame ensemble.

## Git (required)

    git fetch origin
    git checkout feature/mlb-ensemble-integration
    git pull origin feature/mlb-ensemble-integration 2>/dev/null || true
    git checkout -b feature/mlb-ensemble/w6c-stacking

- Work **only** on `feature/mlb-ensemble/w6c-stacking`.
- **Commit** when verify passes (do not push unless user asks).

**Commit message:** `mlb ensemble: W6c ridge stacking on val`

## Scope
- Add `stack_fit` / `stack_predict` in `ensemble.py` (Ridge on member preds, **val only**).
- Compare stacked vs linear `fit_weights` in `pregame_summary.json` (`ensemble` vs `ensemble_stacked` or similar).
- Persist stacker coefficients in `ensemble.json` or `stacker.json` under `models/mlb/pregame/`.
- Wire predict path when config enables stacking.
- Do **not** add Vegas (W6a deferred).

## Verify

    pytest tests/test_baseball_ensemble.py -q
    gametime-pregame-train --config configs/mlb.yaml

## Handoff
Branch, commit, merged yes/no, val/test metrics (linear vs stacked), files changed, blockers.

## Merge reminder

    git checkout feature/mlb-ensemble-integration
    git merge --no-ff feature/mlb-ensemble/w6c-stacking -m "mlb ensemble: W6c ridge stacking"
````

### W6-eval — Holdout splits (recommended)

**Status: shipped** — `test_seasons: [2025]`, val 2024. **13-member refresh (May 2026):** branch `w6-eval-13member-refresh`; ops go/no-go in `docs/mlb_pregame_ops.md`. Re-open only if splits, parquet seasons, or `pregame.ensemble.members` change.

**13-member decorrelation audit (May 2026):** 73 pairs on val / 75 on test with total-error Pearson **r ≥ 0.94** (e.g. lgbm × travel_rest **0.9997**, lgbm × pitcher **0.9985**). No solo member beats linear `ensemble` on 2025 test total MAE or winner%. **Gates out W6l (XGB)** and duplicate form-style members.

Small window to fix **measurement** before production blend changes. See [Post-v1 improvement strategy](#post-v1-improvement-strategy-recommended-order) and [Iteration SOP](#iteration-sop-members--ensemble).

**Scope:**

1. `configs/mlb.yaml`: `test_seasons: [2025]` (or latest full RS year available in parquet); keep val 2024.
2. `train.py` / summary: clearly label `val` vs `test`; never fit weights or stacker on test.
3. Report `ensemble`, `ensemble_equal`, `ensemble_stacked`, and per-member on **both** splits.
4. Document in `pregame_summary.json` or comment which season is test.

**Done when:** test metrics differ from val; orchestrator can compare stack vs linear on 2025.

**Branch:** `feature/mlb-ensemble/w6-eval-holdout`  
**Commit message:** `mlb ensemble: W6-eval 2025 holdout test split`

---

### W6-stack-prod — Enable stacking at inference

**Status:** Stacking was enabled at inference (`use_stacking: true`) after W6c; **May 2026 W6-eval 13-member refresh** flipped production to **linear** (`use_stacking: false`) because stacked inference loses ~1.8 pp winner% on 2025 test. Stacker artifact is still fit at train time; toggle only changes inference blend.

**Prerequisite:** W6c merged; W6-eval showing tradeoff on **test**.

**Scope (historical — enable stack):**

1. Set `pregame.ensemble.use_stacking: true` in `configs/mlb.yaml` if holdout (or user) accepts winner hit.
2. `BaseballPregamePredictor` / CLI already wire `stack_predict` when flag set.
3. Update `docs/mlb_pregame_ops.md` one line on blend mode.

**Scope (May 2026 — linear prod):** Set `use_stacking: false`; document holdout numbers in ops. Branch `feature/mlb-ensemble/w6-stack-linear-prod`.

**Out of scope:** New members, re-tuning member models.

**Branch:** `feature/mlb-ensemble/w6-stack-prod` (enable) or `w6-stack-linear-prod` (disable at inference)

---

### W6l — XGBoost (gated)

**Window ID:** W6l · **Branch:** `feature/mlb-ensemble/w6l-xgb` · **Tier:** E (experimental)

**Planned approach (never shipped):**

Add a fourteenth ensemble member `xgb` that mirrors the existing **`lgbm`** member but uses **XGBoost** instead of LightGBM on the **same** pregame feature matrix (`FEATURE_COLUMNS` in `features.py`):

| Piece | Plan |
|-------|------|
| Model file | `src/gametime/pregame/baseball/models/xgb.py` — `XgbMember(BaseballMemberModel)` |
| Learners | Three boosters: `total_final`, `margin_final`, optional `home_win` (same targets as `lgbm.py`) |
| Features | Identical columns to LGBM — form, RS/RA windows, SP/park/weather/lineup sidecars when populated |
| Hyperparams | Deliberately **different** from LGBM (e.g. `max_depth`, `eta`, `subsample`) in hope of **decorrelated** errors vs `lgbm` |
| Train | `fit(train 2021–2023, early stop on val 2024)`; wire in `train.py` + `predict.py` + `configs/mlb.yaml` `members` |
| Blend | Val-only refit of `ensemble.json` weights + stacker after adding member |

**Hypothesis:** A second tree algorithm on the same columns might capture slightly different splits and improve the blend.

**Why not assign (May 2026 W6-eval audit):**

- Member errors are **highly correlated** — 75 test pairs with total-error **r ≥ 0.94**; top pairs include lgbm × pitcher (0.9985), lgbm × poisson (0.9984).
- XGB on **`FEATURE_COLUMNS` only** would correlate with **`lgbm`** almost as strongly as other form-style members; val weight refit would assign ~floor weight (same failure mode as duplicate heuristics).
- No solo incumbent beats linear **`ensemble`** on 2025 test total or winner%; adding a correlated tree does not fix the binding constraint (missing **orthogonal** signal, e.g. market lines or better SP/lineup coverage).

**Orchestrator gate — assign W6l only if ALL hold:**

1. Fresh decorrelation audit on `test_predictions.parquet` shows **`xgb` total errors** with **r &lt; 0.94** vs every incumbent on test, **or**
2. User explicitly requests an experimental branch with no merge expectation, **or**
3. **`FEATURE_COLUMNS` gains new orthogonal columns** and the experiment is “retrain lgbm + add xgb” in one window — still require audit before merge.

**Dependency:** `xgboost` package (not in repo today); add to `[project.optional-dependencies] mlb` if un-gated.

**Do not block** daily ops or linear prod on W6l.

---

### W6-max-weight — Cap member weights (optional)

**Scope:** In `ensemble._grid_search_target`, add `max_member_weight` (e.g. 0.45) so no single member exceeds cap after normalization. Config key `pregame.ensemble.max_member_weight`. Refit `ensemble.json` on val only.

**Branch:** `feature/mlb-ensemble/w6-max-weight`

---

### W6h — Pitcher (copy-paste worker prompt)

**Orchestrator:** Assign this window when the user wants **starting pitcher / bullpen** signal (highest ROI ingest track). Branch from `main` or `feature/mlb-ensemble-integration` after pull.

Copy **everything** in the fenced block below into a new worker chat:

````markdown
@docs/mlb_ensemble_roadmap.md

You are **Window W6h — starting pitcher + bullpen** for the MLB pregame ensemble in gametime.

## Authority
Follow `docs/mlb_ensemble_roadmap.md`:
- [Post-v1 improvement strategy](#post-v1-improvement-strategy-recommended-order)
- [Ingest milestones](#ingest-milestones-unblocks-d-tier-members) — **M1 — Starting pitcher**
- [Member catalog](#member-catalog) — `pitcher` row

W6a (Vegas) is **deferred**. Do not implement W6i+ in this window.

## Git (required)
**Prerequisite:** Latest `main` or `feature/mlb-ensemble-integration` with six members (lgbm, heuristic, runs_strength, poisson, pythagorean, elo) and W6c stacking in train.

    git fetch origin
    git checkout main
    git pull origin main 2>/dev/null || true
    git checkout -b feature/mlb-ensemble/w6h-pitcher

- Work **only** on `feature/mlb-ensemble/w6h-pitcher`.
- **Commit** when verify passes (do not push or open PR unless the user asks).

**Commit message:** `mlb ensemble: W6h pitcher ingest, features, and member`

## Scope (in order)

### 1. M1 — Ingest (starting pitcher per game)
- Extend MLB ingest or add a small join path so `games.parquet` (or a sidecar joined at feature build) has **pre-game** starting pitcher IDs and a quality metric per side (pick one and document):
  - **Preferred:** `home_sp_id`, `away_sp_id`, `home_sp_era` or `home_sp_fip`, `away_sp_*` (season-to-date or rolling prior to game date — **no leakage**).
  - **Bullpen (minimal v1):** optional `home_pen_era_7d`, `away_pen_era_7d` or days rest since last SP start if data is easy from pybaseball.
- Source ideas: pybaseball `pitching_stats` / game logs / statcast; document rate limits and caching like `ingest/mlb.py`.
- If full history is too heavy for one window, ship **2024+** with a clear TODO and tests on a fixture slice.

### 2. Features (`features.py`)
- Add pitcher columns to `FEATURE_COLUMNS` (e.g. `home_sp_fip`, `away_sp_fip`, `sp_fip_diff`, `home_sp_rest_days`, `away_sp_rest_days`).
- Set `has_starting_pitcher = 1` when SP columns are populated; `0` + sensible league-average fallback when missing (inference-safe).
- `build_training_table` and `build_inference_row` must attach the same columns with **shifted / prior-only** stats.

### 3. Member (`models/pitcher.py`)
- Implement `PitcherMember` (`BaseballMemberModel`):
  - Map SP quality diff (+ optional pen) → `total` and `margin` per row (linear or calibrated heuristic is fine for v1).
  - `name = "pitcher"`.
- Wire into `train.py` member loop and `BaseballPregamePredictor`.

### 4. LGBM refresh
- Retrain `LgbmMember` on expanded `FEATURE_COLUMNS` (same train/val split as config).
- Goal: `lgbm` uses pitcher signal, not only the new member.

### 5. Ensemble refit (val only)
- Add `pitcher` to `configs/mlb.yaml` → `pregame.ensemble.members`.
- Refit `ensemble.json` weights + stacker on **val**; frozen on test.
- `reports/mlb/eval/pregame_summary.json` includes `members.pitcher`.

### 6. Tests
- Extend `tests/test_baseball_ensemble.py`: member count, no leakage smoke (pitcher cols NaN on first game of season if applicable), combine with 7 members.

## Out of scope
- Park (W6i), weather (W6j), lineup (W6k), Vegas (W6a), XGB (W6l)
- Changing val/test seasons unless needed for ingest fixture (prefer separate W6-eval PR)

## Constraints
- **No leakage:** only information knowable before first pitch for that game.
- Reuse `BaseballMemberModel`, `attach_*` patterns from `runs_strength` / `poisson`.
- Val-only weight + stacker fitting.

## Verify

    pytest tests/test_baseball_ensemble.py -q
    gametime-pregame-train --config configs/mlb.yaml
    gametime-pregame --config configs/mlb.yaml --home NYY --away BOS --regular-season

If CLI not on PATH:

    PYTHONPATH=src python3 -m pytest tests/test_baseball_ensemble.py -q
    PYTHONPATH=src python3 -m gametime.cli pregame-train --config configs/mlb.yaml
    PYTHONPATH=src python3 -m gametime.cli pregame --config configs/mlb.yaml --home NYY --away BOS --regular-season

## Handoff (required)
- Branch, commit SHA, merged to `main` / integration yes/no
- Ingest source + date range covered
- `members.pitcher` val/test metrics; before/after `ensemble` and `ensemble_stacked`
- New `FEATURE_COLUMNS` list; fraction of rows with `has_starting_pitcher=1`
- Refit `ensemble.json` weights (note if `pitcher` or `lgbm` gained weight)
- Files changed, blockers (missing SP for historical games, API limits)

## Merge reminder

    git checkout main
    git merge --no-ff feature/mlb-ensemble/w6h-pitcher -m "mlb ensemble: W6h pitcher member"
````

---

## Ensemble member backlog

Brainstormed **additional approaches** beyond v1’s heuristic + LGBM + runs_strength. Each should implement `BaseballMemberModel`, plug into `train.py` / `predict.py`, and trigger a **val-only weight refit** (or stacker refit for W6c).

### Design principles

1. **Diversity over duplication** — prefer members whose errors are weakly correlated (generative vs tree vs market vs context).
2. **No leakage** — only information available before first pitch; shifted rolls / prior-season priors where needed.
3. **One member per window** — keeps review small; orchestrator assigns branch per row below.
4. **Config-driven** — `pregame.ensemble.members` lists active members; inactive members skipped in train/predict.

### Member catalog

| Member ID | Approach | Inputs (main) | Predicts | Data / ingest | Priority | Notes |
|-----------|----------|---------------|----------|---------------|----------|-------|
| `heuristic` | Form sum + bias | 10-game form | total, margin | ✅ shipped | — | v1 baseline |
| `lgbm` | Gradient boosting | `FEATURE_COLUMNS` | total, margin | ✅ shipped | — | v1; consider monotonic constraints later |
| `runs_strength` | Long-window RS/RA | 30-game off/def | total, margin | ✅ shipped | — | v1; dominated val weights today |
| `poisson` | Poisson / Skellam | Team λ_home, λ_away from RS/RA | total, margin | games only | **C** | W6b; generative total |
| `pythagorean` | Pythag (RS^α/(RS^α+RA^α)) | Season-to-date RS/RA | margin, implied total | games only | **C** | Exponent α≈1.83 MLB; fit α on train |
| `elo` | Elo-style ratings | Game results → team rating | margin (+ optional total) | games only | **C** | Reuse `pregame/elo.py` ideas; baseball K, home field |
| `park_factor` | Multiplicative park | home_team, park_id | total (margin small) | park table | **D** | Static or rolling park runs factor |
| `pitcher` | SP quality + pen fatigue | SP FIP/xRA, days rest, pen IP | total, margin | SP/bullpen ingest | **D** | Highest impact when `has_starting_pitcher`=1 |
| `lineup` | Lineup strength | projected wOBA, platoon | total, margin | lineup ingest | **D** | Day-of; may be null pre-lineup |
| `weather` | Weather adjustment | wind, temp, humidity | total | weather API | **D** | Wind-out totals; dome flag |
| `market` | Closing line as member | spread, total (not just blend) | total, margin | odds API | **B (deferred)** | Needs `ODDS_API_KEY` / historical lines; same blocker as W6a |
| `xgb` | XGBoost | same as LGBM (`FEATURE_COLUMNS`) | total, margin | games only | **E — gated** | W6l; **do not assign** until decorrelation audit passes — see [W6l](#w6l--xgboost-gated) |
| `ridge` | Ridge on features | linear in form cols | total, margin | games only | **E** | Interpretable foil to LGBM |
| `h2h` | Head-to-head shrink | last N meetings | margin | games only | **E** | High variance; strong shrinkage |
| `travel_rest` | Schedule stress | miles, games in 3d, DH | margin, total | schedule | **E** | Extends `rest_days` |
| `series_context` | Series situation | game-in-series, prior game style, prior series outcome | total (+small margin) | games only | **E** | Keep one consolidated member; avoid multiple highly-correlated series members |
| `benter` | Benter-style | model + market logit | winner prob | model + odds | **B (deferred)** | After W6a / market data exists |

### Combining layers (not always new members)

| Layer | Type | Window | Description |
|-------|------|--------|-------------|
| **Linear weights** | Meta | v1 / W6e | `fit_weights` grid on val — add floors, finer step |
| **Stacking** | Meta | W6c | Ridge on member OOF preds (val only) |
| **Vegas blend** | Post | W6a ⏸ | `pred = (1-α)*model + α*market` — **deferred** (no API key) |
| **Total calibration** | Post | **W9** ✅ | Val-fit isotonic on `pred_total`; prod off by default |
| **Win-prob calibration** | Post | W9b (future) | Platt / isotonic on `win_prob_home` vs outcomes — separate from total |
| **Quantiles** | Post | future | Member quantile LGBM → interval for total |

### Suggested execution order (post-v1)

```text
main
  ├── W6b–W6g, W6d, W6e, W6-max-weight, W6-stack-prod     ✅
  ├── W6h–W6k, W6m–W6o (13 members)                        ✅
  ├── W6-statsapi-games, W6-sp-live-fip, W7, W8             ✅
  ├── W6-eval 13-member refresh + linear prod blend         ✅
  ├── W9-total-calibration                                    ✅ (default off)
  ├── R1-research ▶                                          proposals → research_backlog.md
  ├── W6l-xgb                                               ❌ gated
  └── W6a-vegas                                             ⏸ deferred
```

**Orchestrator rule:** After any new member window, **refit on val** in the same PR (`ensemble.json` weights + stacker). Run [Iteration SOP](#iteration-sop-members--ensemble) and [Per-window checklist](#per-window-checklist-any-new-member-including-w6h).

### Ingest milestones (unblocks D-tier members)

| Milestone | Unlocks | Source ideas |
|-----------|---------|--------------|
| M1 — Starting pitcher | `pitcher` | pybaseball statcast, retrosheet, or manual CSV |
| M2 — Park factors | `park_factor` | FanGraphs park factors or rolling home/away split |
| M3 — Weather | `weather` | Open-Meteo at game time + stadium coords |
| M4 — Lineups | `lineup` | daily lineup + platoon wOBA |
| M5 — Historical odds | `market` member | The Odds API history or stored closing lines |

Track in `features.py` FEATURE_ROADMAP; flip `has_*` flags when columns are populated.

---

### W6 — quick index (orchestrator)

| Window | Status | Branch slug | One-line scope |
|--------|--------|-------------|----------------|
| W6d | ✅ | `w6d-tests` | Unit tests + pred export |
| W6e | ✅ | `w6e-weight-floor` | Min weight + grid tuning |
| W6a | ⏸ | `w6a-vegas` | Vegas blend — **deferred** |
| W6b | ✅ | `w6b-poisson` | Poisson member + refit weights |
| W6c | ✅ | `w6c-stacking` | Ridge stacker vs linear weights |
| W6f | ✅ | `w6f-pythagorean` | Pythagorean member |
| W6g | ✅ | `w6g-elo` | Elo member |
| W6-eval | ✅ | `w6-eval-holdout` / `w6-eval-13member-refresh` | Test 2025 holdout; 13-member audit May 2026 |
| W6-stack-prod | ✅ | `w6-stack-prod` / `w6-stack-linear-prod` | Stacking at train; **linear at inference** (May 2026) |
| W6-max-weight | ✅ | `w6-max-weight` | Max weight cap in grid search |
| W6h–W6k, W6m–W6o | ✅ | `w6h-pitcher` … `w6o-series-context` | 13-member production set |
| W6-statsapi-games | ✅ | `w6-statsapi-games` | Hybrid games.parquet backfill |
| W6-sp-live-fip | ✅ | `w6-sp-live-fip` | Live Prob SP + distinct FIP on slate |
| W6l | ❌ gated | `w6l-xgb` | XGBoost member — [W6l](#w6l--xgboost-gated) |
| W9 | ✅ | `w9-total-calibration` | Total calibration (default off) |
| R1 | ✅ | `docs/mlb-ensemble/r1-research-backlog` | Research backlog — [backlog doc](mlb_ensemble_research_backlog.md) |
| W10 | ▶ **next** | `w10-sp-lineup-coverage` | SP/lineup sidecar backfill for train — [P1](#proposed-next-features-research-backlog) |
| W11 | recommend | `w11-bullpen-fatigue` | Bullpen fatigue member + features — [P2](#proposed-next-features-research-backlog) |
| W12 | recommend | `w12-statcast-offense` | Statcast team offense features — [P3](#proposed-next-features-research-backlog) |
| W13 | recommend | `w13-lineup-platoon-v2` | Platoon-aware lineup member — [P7](#proposed-next-features-research-backlog) |
| W14 | recommend | `w14-quantile-total` | Quantile total intervals (meta) — [P8](#proposed-next-features-research-backlog) |

Each row → full copy-paste prompt via [W6 worker prompt template](#w6-worker-prompt-template) + scope from [Member catalog](#member-catalog). **W9** uses its [dedicated prompt](#w9--total-calibration-copy-paste-worker-prompt). **W10+** scopes from [research backlog](mlb_ensemble_research_backlog.md).

---

## W7 — Today's slate / production predict

**Purpose:** Run the **existing** 13-member ensemble on real upcoming games (not a new model window). No new ensemble members unless blocking bugs are found.

**When all members run together:** Every `gametime-pregame` call runs all members listed in `pregame.ensemble.members`, then blends via linear `weights` in `ensemble.json` (production default: `use_stacking: false`). You do **not** run separate commands per member.

### Prerequisites

| Step | Why |
|------|-----|
| PR merged to `main` | Stable code + artifacts path |
| `pip install -e '.[mlb]'` | pybaseball for ingest |
| Fresh `games.parquet` through **yesterday** | Form / Elo / Poisson need 2025–current season rows |
| `models/mlb/pregame/` artifacts | From `pregame-train` on `main` |
| Matchup tricodes | e.g. NYY, BOS (same as ingest) |

**Data gap:** `configs/mlb.yaml` may only list seasons through 2024. For 2026 games, extend `data.seasons` (e.g. `[2021, 2022, 2023, 2024, 2025, 2026]`) before `gametime-download`.

### Operator workflow (no new code)

```bash
# From repo root on main
pip install -e '.[mlb]'

gametime-download --config configs/mlb.yaml    # refresh games.parquet
gametime-pregame-train --config configs/mlb.yaml   # optional if artifacts stale

# One game (all members + ensemble in one command)
gametime-pregame --config configs/mlb.yaml --home NYY --away BOS --regular-season

# Repeat per matchup, or use W7 deliverable: pregame-slate CLI
```

Logs append to `data/live_predictions/pregame_predictions.parquet` unless `--no-log`.

### W7 worker window (optional code)

| Branch | `feature/mlb-ensemble/w7-today-slate` (or `feature/mlb-today-slate` from `main` after PR) |
| Deliverable | (1) Extend `data.seasons` for current year; (2) `gametime-download` verified; (3) optional `pregame-slate` CLI: `--date YYYY-MM-DD` runs predict for that day's matchups; (4) short `docs/mlb_pregame_ops.md` with commands |

**Not in scope:** New members, Vegas, re-tuning train splits (unless user asks to add 2025 to `train_seasons`).

Copy-paste prompt: [W7 — Today's slate](#w7--todays-slate-copy-paste-worker-prompt).

### W7 — Today's slate (copy-paste worker prompt)

````markdown
@docs/mlb_ensemble_roadmap.md

You are **Window W7 — today's slate / production MLB pregame predict** in gametime.

## Authority
Follow `docs/mlb_ensemble_roadmap.md` (W7 — Today's slate). Use the **existing** ensemble on `main`; do not add W6h+ members or Vegas unless fixing a blocker.

## Git (required)
Branch from `main` (after MLB ensemble PR is merged):

```bash
git fetch origin
git checkout main
git pull origin main
git checkout -b feature/mlb-ensemble/w7-today-slate
```

Work only on this branch. Commit when verify passes (user may push if they ask).

**Commit message:** `mlb ops: fresh seasons, slate CLI, and pregame runbook`

## Scope
1. **Config** — Update `configs/mlb.yaml` `data.seasons` to include the current season (and prior year if needed) so `games.parquet` has recent results for form/Elo/Poisson.
2. **Verify ingest** — Document/run `gametime-download --config configs/mlb.yaml`; confirm `data/mlb/processed/games.parquet` has games through yesterday.
3. **Verify train artifacts** — Run `gametime-pregame-train --config configs/mlb.yaml` if `models/mlb/pregame/ensemble.json` is missing or stale; confirm six members in config match predict path.
4. **Optional CLI** — Add `gametime-pregame-slate` (or `pregame --slate --date`) that:
   - Accepts `--config`, `--date` (default today local), `--regular-season`
   - Builds today's matchup list (pybaseball or parquet filter on `game_date`)
   - Calls `BaseballPregamePredictor` per game; logs to `pregame_predictions.parquet`
   - Prints a compact table: away @ home, pred total, margin, winner
5. **Docs** — Add `docs/mlb_pregame_ops.md` with operator commands (download, train, single game, slate, log path). No ODDS_API_KEY required.

## Out of scope
- New ensemble members (W6h+)
- Vegas (W6a deferred)
- Changing val/test splits unless user explicitly requests retraining on 2025

## Verify
```bash
gametime-download --config configs/mlb.yaml
gametime-pregame-train --config configs/mlb.yaml
gametime-pregame --config configs/mlb.yaml --home NYY --away BOS --regular-season
# If slate CLI added:
gametime-pregame-slate --config configs/mlb.yaml --date $(date +%Y-%m-%d) --regular-season
```

If CLI not on PATH: `PYTHONPATH=src python3 -m gametime.cli ...`

## Handoff
Branch, commit, merged to main yes/no, sample slate output for today's date, any data gaps (teams with no history), files changed.
````

---

## W9 — Total calibration

**Status: shipped (May 2026)** — branch `w9-total-calibration` merged; `pregame.calibration.total_enabled: false` by default. Isotonic val-fit; test total MAE 3.609→3.595; tail bias largely unchanged. See Handoff in git history.

**Purpose:** Fix **regression-to-the-mean** on ensemble game totals. W6-eval 13-member holdout shows linear `ensemble` test total MAE **3.609** and winner **55.7%**, but predicted totals cluster near league average (~8.9 runs) while actuals span roughly **5–14**. Weight grid and new correlated members cannot fix this; a **post-blend calibration layer** on `pred_total` is the next roadmap feature (aside from deferred Vegas).

**Not in scope for W9:** new ensemble members, re-tuning member weights, win-prob Platt/isotonic (**W9b**), quantile intervals.

### Problem (what we observe)

| Symptom | Meaning |
|---------|---------|
| Low-scoring games (actual total &lt; ~7) | Model overshoots — positive `bias_total` |
| High-scoring games (actual total &gt; ~11) | Model undershoots — negative `bias_total` |
| Overall MAE ~3.6 | Acceptable on average; **band errors** are structured |
| `bias_total` ≈ 0 globally | Affine shift alone may not help; need **shape** mapping |

Calibration adjusts the **final ensemble total** after members combine. **`pred_margin` and winner** stay on the unc calibrated margin path in v1 unless eval shows coupling is needed (**W9b**).

### Process (worker must follow)

```text
1. Diagnose (analysis, val + test report-only)
      • From val/test preds: pred_total vs actual_total scatter
      • bias_total overall; MAE and bias by pred_total terciles AND actual_total terciles
      • Optional: export reports/mlb/eval/total_calibration_diagnostic.json

2. Choose calibrator (fit on VAL ONLY — 2024 RS)
      • v1 default: affine  total_cal = slope * total_raw + intercept
        (mirror src/gametime/pregame/calibration.py fit_margin_calibration)
      • If affine fails go/no-go: isotonic regression (sklearn, monotonic, clip to [3, 20])
      • Optional v2: piecewise / tercile knots — only if isotonic insufficient

3. Fit
      • Input: ensemble linear pred_total on val rows (same blend as prod: use_stacking false)
      • Target: actual total runs (home + away)
      • Never fit on test 2025

4. Persist artifact
      • models/mlb/pregame/total_calibration.json
      • Fields: type ("affine" | "isotonic"), params, fit_split="val", val_season, n_fit

5. Wire train + predict
      • train_baseball_pregame: after ensemble combine on val, fit calibrator, save artifact
      • BaseballPregamePredictor.predict: after combine(), apply calibrator to total only
      • Config: pregame.calibration.total_enabled: true (default false until merged)

6. Evaluate (TEST 2025 — report only)
      • total_mae, margin_mae, winner_accuracy: before vs after calibration
      • bias_total overall and by actual_total bands (<7, 7–11, >11)
      • Go/no-go: ship if test total MAE improves OR band |bias| drops materially
        without winner_accuracy falling > 0.5 pp vs uncalibrated ensemble

7. Handoff
      • Val/test before/after tables, artifact path, config flag, pytest coverage
```

**Reference implementation:** Basketball/WNBA uses post-LGBM margin calibration in `src/gametime/pregame/calibration.py` (`MarginCalibration`, `fit_margin_calibration`). W9 should add **`TotalCalibration`** — either in that module (shared) or `src/gametime/pregame/baseball/calibration.py` (MLB-specific). Prefer shared module if API is sport-agnostic.

### Implementation sketch

| Component | Path / action |
|-----------|----------------|
| Calibrator dataclass | `TotalCalibration` with `apply(total_raw) -> total_cal` |
| Fit helper | `fit_total_calibration(pred_total, actual_total) -> TotalCalibration` |
| Train hook | `src/gametime/pregame/baseball/train.py` — after val ensemble preds |
| Predict hook | `src/gametime/pregame/baseball/predict.py` — after `combine()` / `stack_predict()` |
| Artifact | `models/mlb/pregame/total_calibration.json` |
| Config | `configs/mlb.yaml` → `pregame.calibration.total_enabled: true` |
| Tests | `tests/test_baseball_total_calibration.py` — affine round-trip, isotonic monotonic, no test leakage |
| Summary | `pregame_summary.json` → `total_calibration` block with val/test metrics before/after |

**Inference fields:** expose both `pred_total` (calibrated when enabled) and `pred_total_raw` on `BaseballPregamePrediction` for debugging; log both in `pregame_predictions.parquet` when calibration active.

### Go / no-go (orchestrator)

| Result | Action |
|--------|--------|
| Test total MAE ↓ and winner% within 0.5 pp | Merge; set `total_enabled: true` |
| Band bias improves, MAE flat, winner% OK | Merge if product cares about O/U-style bias |
| MAE worse or winner% drops &gt; 0.5 pp | Do not enable in config; document in Handoff |
| Affine fails, isotonic helps | Ship isotonic; document in ops |

### W9 — Total calibration (copy-paste worker prompt)

````markdown
@docs/mlb_ensemble_roadmap.md

You are **Window W9 — total calibration** for the MLB pregame ensemble in gametime.

## Authority
Follow `docs/mlb_ensemble_roadmap.md` → [W9 — Total calibration](#w9--total-calibration).
Reference: `src/gametime/pregame/calibration.py` (margin calibration pattern for basketball).

Do **not** add ensemble members, change weights/stacker, or fit on test 2025.

## Git (required)
```bash
git fetch origin
git checkout main
git pull origin main
git checkout -b feature/mlb-ensemble/w9-total-calibration
```

Work only on this branch. Commit when verify passes (no push unless user asks).

**Commit message:** `mlb pregame: W9 post-ensemble total calibration (val fit)`

## Scope
1. **Diagnose** — val/test ensemble `pred_total` vs actual; bias and MAE by total bands (see W9 process).
2. **Implement** `TotalCalibration` + `fit_total_calibration()` (affine v1; isotonic fallback if needed).
3. **Train** — fit on **val 2024 only** from ensemble linear preds (`use_stacking: false`); save `models/mlb/pregame/total_calibration.json`.
4. **Predict** — apply after ensemble combine in `BaseballPregamePredictor`; add `pred_total_raw` when calibration enabled.
5. **Config** — `pregame.calibration.total_enabled` (default `false` until verified).
6. **Summary** — extend `pregame_summary.json` with before/after total metrics on val and test.
7. **Tests** — `tests/test_baseball_total_calibration.py`; existing ensemble tests still pass.

## Out of scope
- New members (W6l gated), Vegas (W6a deferred)
- Win-prob Platt/isotonic (W9b)
- Margin calibration (separate window if needed)
- Re-tuning `ensemble.json` weights

## Verify
```bash
PYTHONPATH=src pytest tests/test_baseball_total_calibration.py tests/test_baseball_ensemble.py -q
gametime-pregame-train --config configs/mlb.yaml
# Inspect reports/mlb/eval/pregame_summary.json total_calibration block
gametime-pregame --config configs/mlb.yaml --home NYY --away BOS --regular-season
gametime-pregame-slate --config configs/mlb.yaml --regular-season --decimals 2
```

## Handoff (required)
- Branch, commit SHA, merged yes/no
- Calibrator type (affine / isotonic) and val fit params
- Val vs test: total_mae, bias_total, band bias table **before/after**
- Winner% before/after on test (must be within 0.5 pp or justify)
- Recommend `total_enabled: true/false` for prod config
- Files changed
````

---

## R1 — Ensemble research (feature & member discovery)

**Purpose:** After 13 members + W9 calibration, **marginal gains require orthogonal signal** — not duplicate trees or weight tuning. R1 is a **read-only research agent** that inventories data gaps, evaluates candidate features/members, and produces a **ranked backlog** for the orchestrator. **No production code** in R1 except updating docs.

**Deliverables:**

| Output | Path |
|--------|------|
| Research report + ranked proposals | `docs/mlb_ensemble_research_backlog.md` |
| Roadmap sync | [Proposed next features](#proposed-next-features-research-backlog) section below (summary table) |
| Optional analysis artifacts | `reports/mlb/eval/research/` (parquet/json; gitignored OK) |

**Known constraints (do not re-propose without new evidence):**

- W6l XGB on `FEATURE_COLUMNS` — **gated** (r ≥ 0.94 vs incumbents)
- W6a / `market` member — **deferred** without odds ingest
- W9 total calibration — **shipped**, prod off; tails need wider pred **range** from features
- `has_starting_pitcher_frac` / `has_lineup_frac` ~**0.43** overall; train **0.0** for lineup — ingest gap
- 13-member linear ensemble test: total MAE **3.609**, winner **55.7%**

### Proposed next features (research backlog)

Full ranked proposals live in **[docs/mlb_ensemble_research_backlog.md](mlb_ensemble_research_backlog.md)** (maintained by R1). Orchestrator assigns implementation windows **only** from rows marked `recommend: implement`.

| ID | Proposal | Type | Hypothesis | Window | Recommend |
|----|----------|------|------------|--------|-----------|
| **P1** | Historical SP + lineup sidecar backfill | Ingest + LGBM | Train lineup 0% → 85%+; tail bias −0.5+ on &lt;7 band | **W10-sp-lineup-coverage** | **implement** |
| **P2** | Bullpen fatigue / pen usage member | Member + features | Orthogonal to SP; targets &gt;11 band (ens MAE 6.22) | **W11-bullpen-fatigue** | **implement** |
| **P3** | Statcast team x offense (xwOBA, barrel%) | Feature + member | True talent beyond form; widen pred σ | **W12-statcast-offense** | **implement** |
| **P7** | Lineup platoon v2 vs SP hand | Member + features | `lineup` beats ens on &lt;7/7–9 bands when sidecars exist | **W13-lineup-platoon-v2** | **implement** |
| **P8** | Quantile total LGBM (P10/P90) | Meta | O/U intervals; tail uncertainty product | **W14-quantile-total** | **implement** |
| P4 | Closing total market member | Member (market) | Best orthogonal signal; blocked on odds ingest | W15-market-closing | spike |
| P5 | Umpire K/BB tendency | Feature | Run environment by crew | W16-umpire | spike |

Full ranked list (12 proposals), error anatomy, and decorrelation plans: **[mlb_ensemble_research_backlog.md](mlb_ensemble_research_backlog.md)**.

### R1 — Ensemble research (copy-paste agent prompt)

````markdown
@docs/mlb_ensemble_roadmap.md
@docs/mlb_pregame_ops.md

You are the **R1 research agent** for the MLB pregame ensemble in gametime.

## Role
**Read-only research** — propose additional **features** and **ensemble members** that could improve holdout performance. You do **not** implement train/predict code, open PRs, or assign yourself implementation windows.

## Authority
- `docs/mlb_ensemble_roadmap.md` — member catalog, Iteration SOP, W6-eval decorrelation rules, W9 outcomes
- `docs/mlb_pregame_ops.md` — production ops and coverage notes
- `src/gametime/pregame/baseball/features.py` — `FEATURE_COLUMNS`, `FEATURE_ROADMAP`
- `reports/mlb/eval/pregame_summary.json` — coverage fractions, member metrics (run train locally if missing)
- `reports/mlb/eval/val_predictions.parquet`, `test_predictions.parquet` — decorrelation analysis

## Git (required)
Research updates **docs only** on a short-lived branch:

```bash
git fetch origin
git checkout main
git pull origin main
git checkout -b docs/mlb-ensemble/r1-research-backlog
```

Commit when deliverables are complete (user may push).

**Commit message:** `docs: R1 MLB ensemble research backlog and proposed features`

## Research process (follow in order)

### 1. Baseline audit
- List **13 shipped members** and their solo test metrics from `pregame_summary.json`
- Note **coverage**: `has_starting_pitcher_frac`, `has_lineup_frac`, `has_weather_frac`, train vs val vs test splits
- Summarize **W9 outcome**: isotonic could not fix tail bias; pred_total range ~7.86–10.06 on val
- Re-state **decorrelation gate**: new members need plausible r < 0.94 vs incumbents on test total errors

### 2. Error anatomy
Using `test_predictions.parquet` (and val):
- MAE and **bias_total** by **actual_total** bands (<7, 7–9, 9–11, >11)
- MAE by **pred_total** terciles — where does ensemble fail?
- Which **solo members** beat ensemble on any band (if any)?
- Export summary to `reports/mlb/eval/research/error_anatomy.json` (optional)

### 3. Feature & data inventory
For each candidate, document:
| Field | Content |
|-------|---------|
| Signal | What pregame information it captures |
| Source | pybaseball, Statcast, MLB Stats API, Open-Meteo, odds, manual CSV, etc. |
| Availability | Historical depth, lag, cost, API key |
| Leakage risk | Available before first pitch? |
| Join key | `game_id`, `(date, home, away)`, pitcher_id, … |
| Affects | `FEATURE_COLUMNS` / new member / both |

Review `FEATURE_ROADMAP` in `features.py` and [Member catalog](#member-catalog). Include **ingest fixes** (P1) as first-class proposals.

### 4. Candidate generation (minimum 8, maximum 15)
Categories to consider (not all will rank high):
- **Ingest / coverage** — SP, lineup, bullpen, Statcast team aggregates
- **Orthogonal members** — market lines, generative run models, simulation
- **Context** — umpire, travel v2, altitude, day/night, doubleheader fatigue
- **LGBM-only features** — no new member if signal only helps tree
- **Meta** — quantiles, stratified calibration by park/weather (not duplicate of W9)

**Explicitly reject or deprioritize** with evidence:
- XGB / duplicate trees on `FEATURE_COLUMNS` (W6l gated)
- Same-flavor rolling form heuristics
- Weight-grid / stacking-only ideas

### 5. Rank proposals
Score each candidate 1–5 on:
| Criterion | Question |
|-----------|----------|
| **Orthogonality** | Likely decorrelated vs lgbm/pitcher/poisson errors? |
| **Tail impact** | Could it widen pred_total range or fix low/high bias? |
| **Coverage** | What fraction of games get non-null signal? |
| **Effort** | S / M / L ingest + train wiring |
| **Risk** | Leakage, latency, maintenance |

Sort by expected **test holdout ROI**. Top 3 should be defensible to a skeptical orchestrator.

### 6. Write deliverables

**A. `docs/mlb_ensemble_research_backlog.md`** (create or replace) with:

```markdown
# MLB pregame ensemble — research backlog (R1)

Generated: <date> · Base commit: <main sha> · Eval: val 2024 / test 2025

## Executive summary
(3–5 bullets: what's broken, what kind of signal we need, top 3 recommendations)

## Baseline (May 2026)
(table: ensemble + coverage + decorrelation reminder)

## Ranked proposals
| Rank | ID | Title | Type | Orthogonality | Tail | Coverage | Effort | Recommend | Suggested window |
|------|-----|-------|------|---------------|------|----------|--------|-----------|------------------|
| 1 | P? | … | ingest/member/feature/meta | H/M/L | H/M/L | … | S/M/L | implement / spike / defer | W10-… |

(One subsection per top-5 proposal: signal, source, join, eval plan, decorrelation test, out of scope)

## Deprioritized / rejected
(bullet list with reason — include W6l, duplicate heuristics)

## Suggested implementation order
(numbered list for orchestrator — one window per row)

## Open questions
(data the maintainer must decide)
```

**B. Update `docs/mlb_ensemble_roadmap.md`:**
- Refresh [Current state](#current-state-may-2026): R1 complete, link backlog
- Replace seed table in [Proposed next features](#proposed-next-features-research-backlog) with top-5 summary rows from your ranked list
- Add any new window stubs (W10, W11, …) one line each in W6 quick index if you recommend implement

**C. Optional:** `src/gametime/pregame/baseball/features.py` — append to `FEATURE_ROADMAP` comment block **only** approved high-priority signals (no code wiring).

## Out of scope
- Implementing `BaseballMemberModel`, train.py, or predict.py changes
- Fitting models on test 2025
- Enabling W9 `total_enabled` or changing ensemble weights
- Vegas implementation without odds source plan

## Verify
- [ ] `docs/mlb_ensemble_research_backlog.md` exists and has ≥8 ranked proposals
- [ ] Roadmap Proposed next features table updated
- [ ] Every `recommend: implement` row has suggested window ID, data source, and decorrelation test plan
- [ ] W6l / duplicate tree ideas explicitly rejected

## Handoff (required)
```markdown
## Handoff — R1 Research

| Field | Value |
|-------|-------|
| Branch | docs/mlb-ensemble/r1-research-backlog |
| Commit | <sha> |
| Merged | yes/no |

### Top 3 recommendations
1. …
2. …
3. …

### Files changed
- docs/mlb_ensemble_research_backlog.md
- docs/mlb_ensemble_roadmap.md
- (optional) reports/mlb/eval/research/*

### Orchestrator: next implementation window
Suggest: **W10 — <title>** from backlog rank #1
Do **not** self-assign implementation.
```
````

---

## Handoff template (workers must output)

```markdown
## Handoff

### Git
- **Branch:** `feature/mlb-ensemble/wN-...`
- **Commit:** `<sha>` — `mlb ensemble: ...`
- **Merged to `feature/mlb-ensemble-integration`:** yes / no (if no, run merge before next window)

### Completed
- [ ] …

### Files
- …

### How to run
\`\`\`bash
gametime-pregame-train --config configs/mlb.yaml
\`\`\`

### Metrics (if train ran)
- val: …
- test: …

### Gaps / blockers
- …

### Next window
Paste into **orchestrator** chat, or open new worker with:

> [full next worker prompt]
```

---

## Execution order

```text
main
 └── feature/mlb-ensemble-integration   ← integration
       ├── w1 … w5 (P0–P4)  ✅ v1
       └── w6* optional     → merge each → PR to main when ready
             (see Suggested execution order in Optional windows)

Orchestrator (read-only git audit, assigns branch names)
```

---

## `ensemble.json` schema (target)

```json
{
  "version": 2,
  "members": ["lgbm", "heuristic", "runs_strength", "poisson", "pythagorean", "elo"],
  "weights": {
    "total": { "lgbm": 0.05, "runs_strength": 0.75, "…": "…" },
    "margin": { "elo": 0.65, "poisson": 0.15, "…": "…" }
  },
  "stacker": { "total": { "members": [], "intercept": 0, "coef": {}, "alpha": 1.0 }, "margin": {} },
  "winner_mode": "sign_margin",
  "val_metrics": {},
  "stack_val_metrics": {}
}
```

After **W6h**, append `"pitcher"` to `members` and refit weights + stacker on val.

---

## Config snippet (target)

```yaml
# configs/mlb.yaml
pregame:
  # vegas_weight: 0.35        # W6a deferred — no ODDS_API_KEY
  ensemble:
    enabled: true
    tune_weights: true
    min_member_weight: 0.05   # W6e
    grid_step: 0.05
    export_predictions: true  # W6d
    members: [lgbm, heuristic, runs_strength, poisson, pythagorean, elo]  # + pitcher after W6h
    use_stacking: false   # W6-stack-prod may set true after holdout
    runs_strength_window: 30
```
