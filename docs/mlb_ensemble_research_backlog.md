# MLB pregame ensemble — research backlog (R1)

> **Status:** R1 complete — orchestrator assigns implementation windows (W10+) only from rows marked `recommend: implement`.
>
> **Branch:** `docs/mlb-ensemble/r1-research-backlog` · **Base:** `main` @ `3ba1793` · **Eval:** val 2024 / test 2025

Generated: 2026-05-31 · Error anatomy: `reports/mlb/eval/research/error_anatomy.json`

---

## Executive summary

The 13-member linear ensemble is **production-ready on winner%** (55.7% test) but **under-fit on run totals**, especially tails. Ensemble `pred_total` spans only **7.83–10.05** on 2025 test (σ ≈ 0.31) while actuals range ~4–20+. **33%** of test games have actual &lt; 7 (MAE 4.56, bias **+4.56**); **25%** have actual &gt; 11 (MAE 6.22, bias **−6.22**). W9 isotonic calibration improved val MAE marginally and **did not fix tail bias** — the binding constraint is **missing pregame signal and sidecar coverage**, not blend weights.

**Highest-ROI path:** (1) backfill historical SP/lineup sidecars so train rows are not 100% league-average fallback, (2) add **orthogonal** context members (bullpen fatigue, Statcast talent) that widen the pred range, (3) spike market lines when an odds source is approved. **Do not** add XGB or duplicate form heuristics — 75 test pairs already have total-error r ≥ 0.94.

**Top 3 for orchestrator:** **P1** (SP/lineup coverage) → **P2** (bullpen member) → **P3** (Statcast offense features). Suggested first implementation window: **W10-sp-lineup-coverage**.

---

## Baseline (May 2026)

### Ensemble & splits

| Metric | Val 2024 | Test 2025 |
|--------|----------|-----------|
| Linear `ensemble` total MAE | 3.407 | **3.609** |
| Linear `ensemble` margin MAE | 3.443 | 3.505 |
| Linear `ensemble` winner% | 58.1% | **55.7%** |
| `ensemble_stacked` total MAE | 3.380 | 3.582 |
| `ensemble_stacked` winner% | 57.2% | 53.9% |
| Train / val / test N | 6919 / 2358 / 2359 | |

Production blend: **`use_stacking: false`** (linear weights). Stacking wins ~0.03 runs total MAE on test but loses ~1.8 pp winner%.

### 13 shipped members — solo test metrics

| Member | Test total MAE | Test margin MAE | Test winner% |
|--------|----------------|-----------------|--------------|
| `runs_strength` | **3.612** | 3.506 | **54.9%** |
| `lineup` | 3.616 | 3.565 | 53.0% |
| `pitcher` | 3.617 | 3.561 | 52.6% |
| `elo` | 3.620 | **3.500** | 54.5% |
| `pythagorean` | 3.624 | 3.608 | 53.6% |
| `lgbm` | 3.630 | 3.547 | 53.4% |
| `series_context` | 3.631 | 3.560 | 52.8% |
| `poisson` | 3.632 | 3.514 | 54.7% |
| `travel_rest` | 3.633 | 3.576 | 53.5% |
| `park_factor` | 3.634 | 3.572 | 54.1% |
| `h2h` | 3.666 | 3.587 | 50.1% |
| `weather` | 3.690 | 3.573 | 50.4% |
| `heuristic` | 3.776 | 3.686 | 52.8% |
| **Linear ensemble** | **3.609** | **3.505** | **55.7%** |

No solo member beats linear ensemble on **overall** test total MAE or winner%. Grid puts ~21% total weight on `pitcher`, ~25% margin weight on `elo`.

### Sidecar coverage (`pregame_summary.json`)

| Flag | Overall | Train | Val | Test |
|------|---------|-------|-----|------|
| `has_starting_pitcher_frac` | **0.426** | — | — | — |
| `has_lineup_frac` | **0.426** | **0.0** | 1.0 | 0.932 |
| `has_weather_frac` | 0.988 | 1.0 | 1.0 | 0.966 |
| `has_park_factor_frac` | 1.0 | — | — | — |
| `has_series_context_frac` | 0.999 | 0.998 | 1.0 | 1.0 |

**Critical gap:** train rows have **zero** lineup sidecar hits — LGBM and `lineup` member learned mostly on league-average wOBA placeholders for 2021–2023.

### W9 total calibration outcome

| | Val before | Val after (isotonic) | Test before | Test after |
|--|------------|----------------------|-------------|------------|
| Total MAE | 3.407 | 3.383 | 3.609 | 3.595 |
| `bias_total` | +0.088 | ~0 | −0.010 | −0.101 |
| Band bias `lt_7` | +4.53 | +4.40 | +4.56 | +4.43 |
| Band bias `gt_11` | −5.89 | −5.90 | −6.22 | −6.28 |

W9 merged; **`total_enabled: false`**. Isotonic could stretch val `pred_total` to ~7.86–10.06 but **tail band bias persists** — mapping alone cannot invent low/high run environments.

### Decorrelation gate (W6-eval)

On **2025 test** total errors: **75 member pairs** with Pearson **r ≥ 0.94** (e.g. `lgbm` × `travel_rest` **0.9997**, `lgbm` × `pitcher` **0.9985**). **New members must target r &lt; 0.94** vs all incumbents on test total errors before merge. Solo heuristic has lowest max-r (~0.95 vs `lgbm`) — still near gate.

---

## Error anatomy (test 2025)

Source: `reports/mlb/eval/test_predictions.parquet` · Full JSON: `reports/mlb/eval/research/error_anatomy.json`

### By actual_total band

| Band | N | % games | Ens MAE | Ens bias | Actual μ | Pred μ |
|------|---|---------|---------|----------|----------|--------|
| **&lt; 7** | 784 | 33.2% | **4.56** | **+4.56** | 4.26 | 8.82 |
| 7–9 | 431 | 18.3% | 1.52 | +1.52 | 7.35 | 8.87 |
| 9–11 | 553 | 23.4% | 1.10 | −1.04 | 9.92 | 8.88 |
| **&gt; 11** | 591 | 25.1% | **6.22** | **−6.22** | 15.14 | 8.91 |

Tails drive ~**58%** of games and dominate MAE. Ensemble predicts ~8.87 runs regardless of actual band.

### By ensemble pred_total tercile

| Tercile | Pred range | MAE | Bias | Actual μ |
|---------|------------|-----|------|----------|
| Low | 7.83 – 8.74 | 3.49 | +0.43 | 8.10 |
| Mid | 8.74 – 8.99 | 3.59 | −0.14 | 9.01 |
| High | 8.99 – 10.05 | **3.75** | −0.32 | 9.53 |

High-tercile preds still under-shoot high-scoring games (actual μ 9.53 in top third; many actuals &gt; 11 land here).

### Solo members beating ensemble by band (test)

| Band | Best solo beaters (Δ MAE vs ensemble) |
|------|---------------------------------------|
| &lt; 7 | `lineup` (−0.27), `pythagorean` (−0.14), `pitcher` (−0.13) |
| 7–9 | `lineup` (−0.29), `pitcher` (−0.17) |
| 9–11 | `lgbm` (−0.16), `weather` (−0.14), `travel_rest` (−0.14) |
| &gt; 11 | `weather` (−0.35), `park_factor` (−0.23), `series_context` (−0.12) |

**Implication:** `lineup` / `pitcher` carry low-run signal when sidecars exist; `weather` / `park_factor` carry high-run context — but sidecar sparsity and narrow blend range limit ensemble benefit.

---

## Ranked proposals

Scoring: Orthogonality / Tail impact / Coverage / Effort (S/M/L) / Risk (L/M/H). Sorted by expected **2025 test ROI** (total MAE + tail bias reduction).

| Rank | ID | Title | Type | Orth | Tail | Cov | Effort | Risk | Recommend | Window |
|------|-----|-------|------|------|------|-----|--------|------|-----------|--------|
| 1 | **P1** | Historical SP + lineup sidecar backfill | ingest + LGBM | M | **H** | **H** | M | L | **implement** | W10-sp-lineup-coverage |
| 2 | **P2** | Bullpen fatigue / pen usage member | member + features | **H** | **H** | M | M | M | **implement** | W11-bullpen-fatigue |
| 3 | **P3** | Statcast team expected offense (xwOBA, barrel%, hard-hit) | feature + optional member | **H** | **H** | M | M | M | **implement** | W12-statcast-offense |
| 4 | **P7** | Lineup platoon v2 (confirmed-order wOBA vs SP hand) | member + features | M | **H** | M | M | M | **implement** | W13-lineup-platoon-v2 |
| 5 | **P8** | Quantile total LGBM (P10/P90 intervals) | meta | — | M | H | M | L | **implement** | W14-quantile-total |
| 6 | **P4** | Closing total / run line as market member | member (market) | **H** | M | H | M | H | **spike** | W15-market-closing (blocked) |
| 7 | **P5** | Umpire K/BB zone tendency | feature | M | L | H | M | L | spike | W16-umpire |
| 8 | **P9** | SP Stuff+ / pitch-mix features (LGBM-only) | feature | M | M | L | M | M | spike | W17-sp-stuff |
| 9 | **P10** | Park × weather interaction (wind×HR factor) | feature | M | M | H | S | L | spike | defer |
| 10 | **P6** | Team defense / OAA rolling | feature | M | L | M | S | L | defer | — |
| 11 | **P11** | Monte Carlo run simulation member | member (generative) | L | M | H | L | M | defer | — |
| 12 | **P12** | Travel distance + timezone fatigue v2 | feature | L | L | H | S | L | defer | — |

---

## Top-5 detail

### P1 — Historical SP + lineup sidecar backfill

| Field | Detail |
|-------|--------|
| **Signal** | Actual game SP and batting-order wOBA/platoon splits for 2021–2023 train rows |
| **Source** | MLB Stats API box scores (`/game/{pk}/boxscore`); Retrosheet / pybaseball game logs as fallback |
| **Availability** | Full RS history; Stats API free; ~1 req/game for backfill (~7k train games) |
| **Leakage** | Use official starter + lineup **as played** only for completed games; pre-game for live slate unchanged |
| **Join key** | `game_id` → `pitcher_games.parquet`, `lineup_games.parquet` |
| **Affects** | `FEATURE_COLUMNS` (`has_starting_pitcher`, `has_lineup`, SP FIP, lineup wOBA); strengthens `pitcher`, `lineup`, `lgbm` |
| **Hypothesis** | Train with 0% lineup coverage forces league-average wOBA — root cause of tail underprediction and `lineup` beating ensemble only when sidecars exist |
| **Decorrelation test** | Re-run train; expect lower error correlation among `pitcher`/`lineup`/`lgbm` once features vary on train; no new member required for W10 |
| **Success criteria** | `has_lineup_frac_train` ≥ 0.85; test total MAE −0.05+; `lt_7` band bias −0.5+ runs |

### P2 — Bullpen fatigue / pen usage member

| Field | Detail |
|-------|--------|
| **Signal** | Rolling bullpen IP, rest, leverage innings last 3 days; pen ERA/FIP vs starter |
| **Source** | pybaseball pitching game logs; MLB Stats API box score relief lines |
| **Availability** | 2021+ game-level; daily refresh with download |
| **Leakage** | Shift(1) rolling pen stats before game date |
| **Join key** | `(team, game_date)` |
| **Affects** | New `FEATURE_COLUMNS` (`home_pen_ip_3d`, `away_pen_ip_3d`, …); new `bullpen` member |
| **Hypothesis** | High-scoring games (&gt;11) correlate with tired pens; orthogonal to SP FIP (within-pair r expected &lt; 0.90 vs `pitcher`) |
| **Decorrelation test** | Pearson r on test total errors vs all 13 incumbents &lt; 0.94; solo MAE on `gt_11` band &lt; ensemble 6.22 |
| **Success criteria** | Test total MAE −0.03+; `gt_11` bias magnitude −0.5+ |

### P3 — Statcast team expected offense

| Field | Detail |
|-------|--------|
| **Signal** | Team rolling xwOBA, barrel%, avg exit velo, hard-hit% (offense + contact quality) |
| **Source** | Baseball Savant / pybaseball Statcast batting aggregates |
| **Availability** | 2015+; pitch-level lag ~24h; aggregate to team-date |
| **Leakage** | Rolling windows with shift(1); no same-day Statcast |
| **Join key** | `(team, game_date)` |
| **Affects** | `FEATURE_COLUMNS` + optional `statcast_offense` heuristic member |
| **Hypothesis** | True-talent offense decouples from recent form (10-game window); widens pred range for elite/bottom offenses |
| **Decorrelation test** | Member errors vs `runs_strength` / `poisson` target r &lt; 0.92; feature importance in LGBM without duplicate SHAP cluster |
| **Success criteria** | Test total MAE −0.04+; ensemble pred σ &gt; 0.35 |

### P7 — Lineup platoon v2

| Field | Detail |
|-------|--------|
| **Signal** | wOBA of confirmed lineup vs opposing SP hand (L/R splits); bench depth proxy |
| **Source** | MLB Stats API lineups + Statcast platoon splits |
| **Availability** | 2024+ reliable; historical via box score batting order |
| **Leakage** | Confirmed lineup only after publish (~2–3h pregame live; historical as-played OK) |
| **Join key** | `game_id`, `pitcher_id`, batter IDs |
| **Affects** | Upgrades `lineup` member + `lineup_platoon_diff` feature |
| **Hypothesis** | Error anatomy: `lineup` beats ensemble on &lt;7 (−0.27 MAE) and 7–9 (−0.29) — platoon-aware wOBA amplifies low-run edge |
| **Decorrelation test** | Enhanced `lineup` errors vs incumbent `lineup` baseline; vs `pitcher` r should stay &lt; 0.96 |
| **Success criteria** | `lt_7` band MAE −0.2+; depends on P1 train coverage |

### P8 — Quantile total LGBM (P10/P90)

| Field | Detail |
|-------|--------|
| **Signal** | Prediction intervals for total runs (10th/50th/90th percentile) |
| **Source** | Same `FEATURE_COLUMNS` + quantile LightGBM objective |
| **Availability** | No new ingest |
| **Leakage** | Same train/val/test discipline |
| **Join key** | N/A (meta on existing features) |
| **Affects** | New artifact `total_quantile.json`; slate output `pred_total_lo/hi`; does not change point ensemble by default |
| **Hypothesis** | Point MAE plateaued; intervals capture tail uncertainty for O/U product; P90 should correlate with `gt_11` outcomes |
| **Decorrelation test** | N/A (meta layer); validate P90 − P10 width correlates with actual total variance (ρ &gt; 0.3) |
| **Success criteria** | 80% of actuals fall in [P10, P90]; interval width higher in Coors/wind games |

---

## Deprioritized / rejected

| Item | Reason |
|------|--------|
| **W6l XGBoost** | Decorrelation audit: 75 test pairs r ≥ 0.94; XGB on same `FEATURE_COLUMNS` duplicates LGBM error structure |
| **Duplicate form heuristics** | Another rolling-runs / win-% member correlates r &gt; 0.97 with `runs_strength`, `poisson`, `travel_rest` |
| **Weight grid / stacking-only** | W6-eval: tuned weights ≈ equal weights (+0.007 test MAE); W6-stack-prod: stacking loses 1.8 pp winner% |
| **W9b win-prob calibration** | Test winner% 55.7% without calibration; not binding |
| **W9 enable in prod** | Tail bias unchanged after isotonic; point MAE gain ~0.014 test — insufficient |
| **P11 Monte Carlo simulation** | Likely r &gt; 0.97 vs `poisson` / `runs_strength` (same rate parameters) |
| **P12 Travel distance v2** | `travel_rest` already r ≈ 0.9997 with LGBM; marginal new signal |
| **P4 market (implement now)** | No `ODDS_API_KEY` or historical closing-line store — spike only until ingest plan approved |

---

## Suggested implementation order

1. **W10 — P1 SP/lineup coverage** — unblocks train signal for existing members; lowest risk, highest tail ROI
2. **W11 — P2 bullpen fatigue** — orthogonal member; targets `gt_11` band where weather/park solo beaters hint at context gap
3. **W12 — P3 Statcast offense** — true-talent features + optional member; widens pred range
4. **W13 — P7 lineup platoon v2** — builds on W10 sidecars; evidence from low-run band solo beats
5. **W14 — P8 quantile total** — meta layer for O/U product once point model stabilizes
6. **Spike queue:** P4 market (when odds budget approved), P5 umpire, P9 SP Stuff+

Re-run `gametime-pregame-train` + decorrelation audit after **each** new member.

---

## Open questions

1. **Odds API:** Budget and retention policy for historical closing totals (P4)? Manual CSV acceptable for 2024–2025 spike?
2. **Statcast rate limits:** Cache strategy in `ingest/mlb.py` — daily team aggregates vs per-game pull?
3. **Lineup backfill scope:** Full 2021–2023 box-score crawl vs accept 2024+ only for platoon v2 train?
4. **Quantile product:** Ship intervals on slate before point MAE improves, or gate W14 on W10–W12 success?
5. **Bullpen definition:** Include opener roles / bulk relievers separately post-2023 rules?

---

## Handoff — R1 Research

| Field | Value |
|-------|-------|
| **Branch** | `docs/mlb-ensemble/r1-research-backlog` |
| **Commit** | *(pending commit)* |
| **Merged** | No |
| **Top 3** | **P1** SP/lineup backfill · **P2** bullpen fatigue · **P3** Statcast offense |
| **Files changed** | `docs/mlb_ensemble_research_backlog.md`, `docs/mlb_ensemble_roadmap.md`, `src/gametime/pregame/baseball/features.py` (comment only) |
| **Suggested W10** | **W10-sp-lineup-coverage** — backfill `pitcher_games.parquet` + `lineup_games.parquet` for 2021–2023 train; target `has_lineup_frac_train` ≥ 0.85; re-train and verify tail bias reduction |
