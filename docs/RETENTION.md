# Customer lapse extension — v2

This optional track addresses **which previously active repeat shoppers are at risk of not purchasing again within a chosen horizon**. It is a separate business question from the established `v1` next-seven-day repurchase benchmark. The `v1` model, its holdout results, and the existing four explorer views remain intact.

## Full-data run: measured results

The committed aggregate reports describe the original **2,500-household** dataset, not a smoke cohort. The latest day-711 scoring roster contains **1,543 active + 386 at-risk + 280 inactive + 174 dormant + 117 limited-history = 2,500 households**. The 1,929 active/at-risk households are eligible for lapse probabilities; the other 571 remain visible with null model risk.

The **untouched chronological holdout** contains **5,808 household-date observations** from **2,163 distinct households** on days 600, 630, and 660 (observed lapse rate **19.15%**). The 20% capacity is applied separately to each scoring date, giving **1,163 selected observations** in total.

| Frozen holdout model | ROC-AUC | Average precision | Brier score | Precision@20% | Lift@20% |
|---|---:|---:|---:|---:|---:|
| Recency rule | 0.6761 | 0.3222 | — | 37.06% | 1.94× |
| **Logistic Regression (selected)** | **0.8022** | **0.4315** | **0.1281** | **45.49%** | **2.38×** |
| LightGBM | 0.8042 | 0.4310 | 0.1273 | 45.31% | 2.37× |

The selected model identifies **529 eventual lapse instances** at this capacity versus **431 for recency**. The **+8.43-pp** Precision@20% improvement has a paired, whole-household **500-replicate bootstrap 95% CI of +5.96 to +11.80 pp**. This interval reflects held-fixed predictions with household resampling, not model-training or deployment uncertainty. LightGBM–LR Precision@20% differed by about −0.17 pp on holdout (paired CI spanning zero), supporting the validation-defined choice of the simpler LR.

**Selection was performed without consulting this holdout.** Validation lapse prevalences were 35.43% (7d), 19.13% (14d), and 8.55% (28d). The 28-day option had the largest measured lift (3.13×) but did not satisfy the predeclared ≥10% prevalence requirement. Hence **14 days** was chosen within the eligible horizon set; that rule is not proof of an economically optimal window. Validation Precision@20% was **50.78% for LR** versus **51.04% for LightGBM**, below the preset 1.5-pp hurdle for choosing the more complex model.

The validation-only LightGBM ablation was **49.09% Precision@20% with 13 behavioral encoded inputs** versus **51.04% with the full 51 encoded inputs**. Adding cadence alone lowered precision; other omissions had unequal effects. These results do not establish that every feature family improves the selected LR. See `reports/tables/retention_ablation.csv` for each combination.

Across the three fixed holdout dates, prediction PSI values were approximately **0.0048–0.0113**, while day-660 mean predicted lapse risk (**16.95%**) was below observed lapse (**19.96%**). Low distribution PSI therefore does **not** establish good calibration. The economics sheet uses assumed margin and incremental response, not observed treatment effects; the **13.33%** break-even is `CAD 2 / CAD 15`.

## One-time migration and run

Use the **same populated PostgreSQL database** already serving Behind the Basket. The original 2,500-household source data is required; no synthetic or shortened demonstration cohort is substituted.

If you run the project's existing Docker Compose stack, the updated `compose.yaml`
exposes the **same persisted PostgreSQL container** only to your machine at
`127.0.0.1:55432`. Keep the existing Docker volumes: **never run `docker compose down -v`**.
From your repository root, start the existing database, then run the SQL inside
its container (no host `psql` installation needed):

```bash
docker compose up -d db
docker compose exec -T db psql -U retail -d retail_analytics -v ON_ERROR_STOP=1 < sql/marts/retention_features.sql
docker compose exec -T db psql -U retail -d retail_analytics -v ON_ERROR_STOP=1 < sql/schema/retention.sql

# The Python model runner on your Mac uses that exact same database.
# Load the existing local .env password without printing it.
set -a
source .env
set +a
export PGPASSWORD="$POSTGRES_PASSWORD"
export RETAIL_DATABASE_URL="postgresql+psycopg://retail@127.0.0.1:55432/retail_analytics"

python -m pip install -e ".[modeling,serving,dev,reporting]"
python -m retail_analytics.retention run --horizon auto --day 711

# Rebuild and restart the existing web app; no separate app or database.
docker compose up -d --build api
```

Open `http://127.0.0.1:8000/` and select **Retention Lab**. The new
analytical reports are included in the rebuilt image, while the scored roster
resides in the existing Docker PostgreSQL volume.

If you instead run an independently installed local PostgreSQL server (rather
than Docker Compose), use the host-database alternative below.

### Alternative: existing host PostgreSQL

```bash
python -m pip install -e ".[modeling,serving,dev,reporting]"

psql -d retail_analytics -v ON_ERROR_STOP=1 -f sql/marts/retention_features.sql
psql -d retail_analytics -v ON_ERROR_STOP=1 -f sql/schema/retention.sql

python -m retail_analytics.retention run --horizon auto --day 711

# Rebuild the React UI and launch the local API as usual:
npm --prefix frontend ci
npm --prefix frontend test
npm --prefix frontend run build
python -m uvicorn retail_analytics.api:app --host 127.0.0.1 --port 8001
```

Open `http://127.0.0.1:8001/`, select **Retention Lab**. The v2 research and scored roster only appear after `retention run` finishes; the original v1 views work independently. If the project uses a custom `RETAIL_DATABASE_URL`, export it before running the SQL/model commands and adapt `psql` accordingly. **Do not create or replace your existing database.**

`run` performs these operations as a single repeatable update *once*: create historical feature snapshots and matured future labels, compare 7/14/28-day outcomes on validation, perform validation feature-family ablations, choose between logistic regression and LightGBM, fit a separate development-only holdout estimator, compare multiple baselines on the same holdout, bootstrap entire households, generate assumption-only economics and a per-date holdout report, refit a final versioned model on available labeled history, then score the day-711 cohort. The script refuses to overwrite an existing `lapse_v2` model artifact.

If rerunning research without replacing the production artifact:

```bash
python -m retail_analytics.retention prepare
python -m retail_analytics.retention evaluate --horizon auto
python -m retail_analytics.retention score --day 711
```

For a predeclared 14-day horizon, replace `--horizon auto` with `--horizon 14` *before* inspecting holdout results. An automatic candidate is chosen **using validation only**: among horizons with 10–75% validation lapse prevalence, maximize the observed lift at 20% capacity. This is a transparent heuristic, not evidence of an economically optimal horizon.

Marketing assumptions are configurable (default: hypothetical CAD 15 contribution margin per additional purchase, CAD 2 fixed contact/offer cost): append `--margin 20 --contact-cost 3` to either `run` or `evaluate`. Regenerating scenarios does not update the versioned model artifact, but changing the model/horizon requires a **new** artifact version instead of overwriting `lapse_v2`.

## Model contract

| Aspect | Definition |
|---|---|
| Observation unit | `(household_key, as_of_day)` |
| History | Prior 90 days for behavioral features; lifetime history for coverage |
| Target | **No basket in the next H days** (H ∈ {7,14,28}) |
| Eligible cohort | At least 3 baskets in the past 90 days **and** latest visit ≤30 days ago |
| Current-day retention roster | **Every household with any purchase on or before that day**, including those with no purchases in the last 90 days |
| Noneligible segments | `inactive` (31–89 day gap), `dormant` (90+ days), `limited_history` (under 3 baskets) |
| At-risk flag | Highest predicted-risk 20% among eligible households; **not** a coupon-response prediction |
| Split | Train through day 510; validation 540/570; holdout 600/630/660 |
| Leakage protection | 30-day separation between observation cutoffs allows all 28-day outcomes to mature before the next period; no post-cutoff campaign or transaction covariates |
| Final v2 candidate | Separate versioned model trained after fixed holdout evaluation; never used to report in-sample holdout metrics |

**Important:** The target *does not claim* that every lapse is abnormal or that a high-risk customer would respond to a coupon. Historical purchase cadence (typical interval, overdue ratio) helps distinguish unusual gaps. The 7/14/28-day evaluation and per-segment coverage report indicate how restrictive the actual outcome definition is. In noncontractual retail, temporary inactivity is not proof of permanent churn.

## Feature families and ablation

- **Behavioral:** recency, basket and sales counts for 30/90-day periods, changes in sales, basket value variability, store variety, basket diversity, discount share.
- **Cadence:** median days between purchase dates, interval variability, current gap relative to typical gap.
- **Products:** past-90-day department diversity, grocery sales share, private-label sales share.
- **Promotions:** historical campaign assignments known by the cutoff; recorded coupon redemptions through the cutoff (redemption is **not** coupon receipt or treatment assignment).
- **Seasonality:** seven-day cycle and day-index annual Fourier terms (relative day-index, not verified Gregorian weekdays).
- **Demographics:** categorical age, income, and household-size attributes when available; explicit unknown category for uncovered households.

The ablation output starts from existing behavior, adds cadence, and separately removes the remaining families from the full model. Results reflect **validation-only observational predictive contributions**, not causal feature effects.

## Evaluation and economics

The evaluation includes **recency-only**, **overdue-ratio**, **logistic regression**, and **LightGBM** on identical holdout examples. Model selection uses validation Precision@20% and prefers logistic regression unless LightGBM's gain reaches 1.5 percentage points. The fit used for holdout is frozen after day 570; a later final refit is clearly distinguished.

Reports are stored in `reports/tables/retention_*.csv` and `retention_decision.json`:

| File | Contents |
|---|---|
| `retention_horizons.csv` | Validation prevalence, PR-AUC, AUC, calibration and shortlist lift per horizon |
| `retention_model_selection.csv` | LR versus LightGBM on validation |
| `retention_ablation.csv` | Family-wise model comparisons on validation |
| `retention_holdout.csv` | Fixed chronological holdout performance for all four baselines |
| `retention_paired_bootstrap.csv` | Paired whole-household Precision@20% intervals, models held fixed |
| `retention_coverage.csv` | Count of all known households by date and lifecycle segment |
| `retention_holdout_by_date.csv` | Three fixed holdout dates (600, 630, 660): predicted versus observed lapse and PSI; **not a daily replay** |
| `retention_profit_scenarios.csv` | **Explicitly hypothetical** offer-cost/margin/incremental-response sensitivity |

Profit scenarios assume a constant incremental response probability for all contacted customers, a hypothetical gross contribution per incremental purchase, and an assumed per-contact marketing cost. The break-even threshold is:

`required_incremental_purchase_probability = contact_and_offer_cost / margin_per_incremental_purchase`

**Neither uplift nor measured marketing profit is inferable from repurchase/lapse predictions alone.** A proper customer-targeting ROI estimate would require a randomized no-offer holdout or defensible treatment-effect identification. Under uniform assumed uplift, profit is monotonic in number contacted; **the code does not manufacture an "optimal" capacity**.

## Holdout by observation date

The committed report contains **three holdout dates**, not 84 daily batches. The same development-only estimator, fitted through day 570, was scored on point-in-time features from days 600, 630, and 660. The report shows observed lapse after each fully matured interval, mean predicted risk, and prediction-distribution PSI relative to validation. The three dates are useful for comparison but are **not evidence of continuous daily monitoring**, production shadow serving, or a randomized campaign. A separate daily-replay command exists in the code, but its output has **not** been run or committed here.

## Artifact/version and deployment boundaries

- `artifacts/models/v1/` remains unchanged; its 7-day outcome is *purchase*, not lapse.
- `artifacts/models/lapse_v2/` is generated locally on first `run`, including hash-checked metadata and a serialized scikit-learn-compatible estimator. Treat this model as a trusted local artifact; never load untrusted joblib files.
- Individual training snapshots are placed in ignored `data/processed/retention_snapshots.csv.gz`, **not** committed.
- `analytics.retention_scores` stores the entire known-household roster, with null probability for noneligible segments. This SQL table drives `/retention/overview` and `/retention/directory`.
- The new React tab displays genuine saved reports through `/retention/research`. The README now links a **55-second combined v1/v2 application walkthrough** and labels the Retention screenshots separately from the original v1 explorer images.
- Docker Compose's database is independent of any separately installed host PostgreSQL server. Compose now exposes its own PostgreSQL container at host loopback port 55432 for research commands; the API connects to the same container over its Docker service name. If you use the host-database alternative instead, its retention table will not automatically appear in the Docker database.

No online hosting, real-time ingestion, automated retraining, causal uplift, or realized ROI is claimed.
