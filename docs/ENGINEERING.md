# Engineering notes

Concise implementation details behind the metrics in the [README](../README.md).

## Dataset and modeling contract

| Quantity | Value |
|---|---:|
| Transaction line items / baskets / households | 2,595,732 / 276,484 / 2,500 |
| Product catalog | 92,353 products |
| Campaigns / coupon redemptions | 30 / 2,318 |
| Historical labeled snapshots | 41,507 |
| Unique modeled households | 2,493 |
| Development / holdout rows | 34,530 / 6,977 |
| Feature lookback / target horizon | 90 days / 7 days |
| Point-in-time model inputs | 15 |

The seven source CSVs populate `raw`, normalized `core`, and derived `analytics` PostgreSQL schemas. Data integrity checks cover candidate keys, nulls, duplicate associations, basket consistency, transaction/quantity/sales totals, and analytical feature parity. Coupon-product mappings are deduplicated in the core layer to avoid downstream join multiplication while retaining source records.

Each observation is `(household_key, as_of_day)` with binary `repurchased_7d` indicating any purchase in the following seven days. Historical observation dates are 30 days apart, so prediction windows do not overlap.

### Feature contract (15)

| Family | Features |
|---|---|
| Recency | `recency_days` |
| Frequency | `baskets_90d`, `baskets_30d`, `baskets_previous_30d` |
| Monetary | `sales_90d`, `sales_30d`, `sales_previous_30d`, `sales_growth_30d` |
| Basket composition | `avg_basket_value_90d`, `basket_value_volatility_90d`, `avg_product_diversity_90d` |
| Store/promotion | `distinct_stores_90d`, `discount_share_90d` |
| Visit timing | `avg_days_between_visits_90d`, `visit_interval_volatility_90d` |

All features are generated using purchases available **no later than the observation day**. The SQL function `analytics.household_features_at(as_of_day)` applies the same feature contract to arbitrary scoring dates; a four-date parity check verifies its output against the historical materialized-view snapshots. Genuinely unavailable derived history values are not fabricated.

## Experimental design

- **Chronological split:** train 180–540 (29,902 rows), validation 570/600 (4,628), holdout 630/660/690 (6,977).
- **Benchmark:** recency/frequency ranking, logistic regression, LightGBM, XGBoost, HistGradientBoosting; four additional rolling-origin checks.
- **Selection:** LightGBM chosen on development-period validation and stability, not holdout tuning. The selected configuration uses 300 estimators, 0.03 learning rate, 15 leaves, minimum leaf size 100, and L2 regularization.
- **Unseen-period evaluation:** train the fixed model on 34,530 development rows; evaluate once on 6,977 later observations. Across holdout dates, households may recur, so this tests **future behavior of known households**, not new-customer cold starts.
- **Metrics:** ROC-AUC `0.809`, average precision `0.858`, Brier `0.176`, Precision@20% `0.941`, lift `1.643×` (overall holdout repurchase rate `57.23%`).
- **Baseline:** recency ascending, then 90-day frequency descending, separately ranked each observation day; Precision@20% `0.802`.
- **Uncertainty:** paired household-cluster bootstrap, resampling all snapshots of a household together. Original holdout Precision@20% gap = `+13.9 pp`, 95% CI `[+11.8, +15.9] pp`; the fitted model is held fixed, and the interval does not include training uncertainty or future drift.
- **Calibration and interpretation:** quantile-based calibration, LightGBM gain importance, probability deciles. Importance and feature contribution are model-specific associations, not causal explanations.

### Fixed-capacity ranking (offline decision evaluation)

At each holdout observation date, select `ceil(fraction × number_of_households)` highest-ranked snapshots, then aggregate over days. The business analysis compares the *same capacity* across two ranking strategies.

| Daily capacity | Baseline precision | LightGBM precision | Difference | Extra future-purchase instances found |
|---:|---:|---:|---:|---:|
| 5% | 96.0% | 98.9% | +2.85 pp | 10 |
| 10% | 89.1% | 97.7% | +8.58 pp | 60 |
| 20% | 80.2% | 94.1% | +13.89 pp | 194 |
| 30% | 78.2% | 89.6% | +11.41 pp | 239 |
| 40% | 75.1% | 85.1% | +9.99 pp | 279 |
| 50% | 73.6% | 80.0% | +6.45 pp | 225 |
| 100% | 57.2% | 57.2% | 0 pp | 0 |

The capacity analysis runs a separate **500-replicate paired household bootstrap** by default. It also outputs per-day counts, shortlist precision, lift, and fraction of all eventual purchasers captured. The outcome is an observed purchase in the subsequent seven days; **extra identified observations are not additional purchases caused by an intervention**, nor necessarily distinct customers.

## Model artifact and inference

The final `v1` booster is refitted on **all 41,507 labeled historical observations through day 690**, independently of holdout evaluation. Its ~0.5 MB native LightGBM file and JSON metadata include feature ordering, configuration, data scope, software versions, and SHA-256 integrity hash. The loader checks the hash and exact 15-feature schema; a reload parity check compares saved-model predictions with the original estimator.

Scoring uses a day-specific SQL feature snapshot, checks unique IDs and finite probabilities, ranks households, assigns deciles, and upserts `(household_key, as_of_day, model_version)` predictions into PostgreSQL. The verified day-711 batch scored **2,326 distinct households** and stored the full set.

## Batch orchestration and monitoring

| Concern | Implementation |
|---|---|
| Batch validation | Required columns, 90-day recency/frequency invariants, numeric/finite inputs, row-count parity |
| Idempotence | Previous successful batch matched on observation day, model version, SHA-256, and stored row count; otherwise re-score; `--force` supported |
| Concurrency | PostgreSQL **advisory lock per observation day** to prevent concurrent scoring |
| Audit | UUID run ID, timestamps, result status (`running`, `succeeded`, `failed`, `skipped`), input/output counts and error classification in `analytics.pipeline_runs` |
| Scheduler | Optional Docker Compose service; on startup, then every 24 hours while its host is running |
| Drift | PSI of 15 features and prediction scores against historical train-period reference (days 180–540); missingness handled explicitly |
| Alert thresholds | PSI ≥ `0.20` or increase in feature missingness ≥ `5 percentage points`; configurable review alerts, not proof of degraded accuracy |
| Delayed outcomes | Only evaluates saved predictions after `as_of_day + 7` has arrived **and** after the model's maximum training day; pending windows revisited |
| API visibility | `/pipeline/runs`, `/monitoring/latest`, `/monitoring/history` plus prediction endpoints |

In the verified day-711 run: **prediction PSI = 0.0062**, **0 feature alerts**, `drift_status=ok`, and `label_status=pending`. The source dataset ends on day 711, so these predictions lack their full future outcome window. Historical in-sample reference scores are **never** reported as generalization performance.

The scheduler does not ingest live transactions, refresh upstream materialized views, or retrain the model; those are distinct lifecycle concerns.

## API, interface, testing, and delivery

- **Backend:** FastAPI, Pydantic request/response models, SQLAlchemy + psycopg, `/docs` OpenAPI interface, parameterized database queries.
- **Frontend:** React 19 + TypeScript + Vite, Lucide and Recharts; four views (Customer Explorer, Behavioral Paradox, Beat the Model, Model Pulse). Complete cohort browsing via parameterized `/explorer/directory` (search, sort allowlist, limit/offset). Selecting a household loads full server-derived history, percentiles, and live model prediction in a contextual drawer shared across routes; comparisons remain visible.
- **Historical game isolation:** its probabilities are computed by a model trained through day 600, while the latest-customer explorer uses saved `v1` predictions. Future outcomes never become real-time inputs.
- **Explainability:** cohort-relative percentiles and native LightGBM raw-score feature contributions; no causal interpretation.
- **Testing:** Python pytest tests cover feature/split contracts, ranking calculations, bootstrap edge cases, API routes, the explorer, batch idempotence, and monitoring. Vitest + React Testing Library cover directory search, in-context profiles, paradox inspection, historical game outcomes, and operations UI.
- **CI:** Separate GitHub Actions workflows on pushes/PRs: Python 3.11/3.13 pytest matrix; Node 24 with `npm ci`, Vitest, TypeScript type-check and production Vite build.
- **Packaging/containers:** setuptools `src/` Python package with bundled SQL and legacy fallback; Docker multi-stage Node 24 frontend build + Python 3.13 runtime, LightGBM OpenMP dependency and non-root user; Compose for PostgreSQL, FastAPI, and opt-in scheduler.

The environment supports **local Docker deployment**. There is **no MLflow tracking service, automatic CD release, hosted cloud instance, measured throughput benchmark, or marketing-uplift experiment** in this repository. Consequently, those capabilities are not claimed.
