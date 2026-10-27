# Setup and runbook

The [README](../README.md) summarizes the system. This page covers reproducibility and operational commands. The original dunnhumby data is intentionally excluded from Git.

## Requirements

- Python 3.11+, Node.js 24 and npm for the React build; PostgreSQL and `psql` (project tested with PostgreSQL 18).
- Seven CSVs from [dunnhumby, *The Complete Journey*](https://www.dunnhumby.com/source-files/) (also available via Kaggle under its own terms).
- Docker Desktop / Docker Compose only if you want the containerized API and optional scheduler.

Start at the repository root:

```bash
python -m pip install -e ".[modeling,serving,dev,reporting]"
```

The local default connection is `postgresql+psycopg:///retail_analytics`; override it with `RETAIL_DATABASE_URL` when using a different PostgreSQL connection.

## 1. Prepare the data and SQL layers

Place the following files in `data/raw/complete_journey/`:

```text
campaign_desc.csv      campaign_table.csv
coupon.csv             coupon_redempt.csv
hh_demographic.csv     product.csv
transaction_data.csv
```

On a fresh local PostgreSQL database:

```bash
createdb retail_analytics

psql -d retail_analytics -v ON_ERROR_STOP=1 -f sql/schema/raw.sql
psql -d retail_analytics -v ON_ERROR_STOP=1 -1 -f sql/load/load_raw.sql
psql -d retail_analytics -v ON_ERROR_STOP=1 -f sql/checks/raw_row_counts.sql
psql -d retail_analytics -v ON_ERROR_STOP=1 -f sql/checks/raw_integrity.sql

psql -d retail_analytics -v ON_ERROR_STOP=1 -f sql/schema/core.sql
psql -d retail_analytics -v ON_ERROR_STOP=1 -1 -f sql/load/load_core.sql
psql -d retail_analytics -v ON_ERROR_STOP=1 -f sql/checks/core_reconciliation.sql

psql -d retail_analytics -v ON_ERROR_STOP=1 -f sql/marts/customer_behavior.sql
psql -d retail_analytics -v ON_ERROR_STOP=1 -f sql/marts/household_snapshots.sql
psql -d retail_analytics -v ON_ERROR_STOP=1 -f sql/marts/household_features_at.sql
psql -d retail_analytics -v ON_ERROR_STOP=1 -f sql/checks/household_features_parity.sql
psql -d retail_analytics -v ON_ERROR_STOP=1 -f sql/schema/predictions.sql
```

These are **fresh-load** instructions, not a repeatable append process. Source-data corrections may require appropriate core/mart rebuilds before re-scoring. The parity check covers days 300, 540, 600, 690.

The project also includes descriptive SQL analyses in `sql/analysis/`: purchasing behavior, retention cohorts, and campaign activity. Campaign-period comparisons are descriptive, not experimental treatment effects.

## 2. Reproduce holdout results

```bash
python -m retail_analytics.data
python -m retail_analytics.benchmark
python -m retail_analytics.evaluate
python -m retail_analytics.visualize
python -m retail_analytics.business
```

Evaluation retrains the **fixed development-period** model on days no later than 600. It does **not** evaluate the saved production model on its own training dates. Reports are written to `reports/tables/` and figures to `reports/figures/`; business capacity output includes the 5–100% shortlist comparison and paired household-bootstrap intervals.

## 3. Save and score with model v1

If the versioned `artifacts/models/v1/` files are already present, **do not** re-run `train_final`: the script intentionally refuses to overwrite an existing version. If starting from an environment with no saved model, generate the final artifact once:

```bash
python -m retail_analytics.train_final
```

The all-history v1 model trains on every labeled snapshot through day 690. The reproducible model filename and SHA-256 hash are recorded in its metadata JSON.

Run a non-mutating validation followed by an idempotent scoring batch:

```bash
python -m retail_analytics.pipeline --dry-run
python -m retail_analytics.pipeline
python -m retail_analytics.monitor --as-of-day 711
```

By default the batch chooses the maximum day in the existing `analytics.baskets` mart. With the provided dataset, that is day 711 and **2,326** households. A successful identical run is skipped; `--force` explicitly requests a new score when the source was corrected. Run metadata is stored in `analytics.pipeline_runs`; monitoring reports in `analytics.monitoring_reports`.

Day-711 outcomes are marked `pending`: the source data ends at day 711, earlier than the end of its seven-day prediction horizon. Do not present training-window labels as monitoring accuracy.

## 4. Launch Behind the Basket locally

The browser explorer uses two additional PostgreSQL tables with derived profile data:

```bash
psql -d retail_analytics -v ON_ERROR_STOP=1 -f sql/schema/explorer.sql
python -m retail_analytics.build_explorer --as-of-day 711
cd frontend
npm ci
npm run build
cd ..
python -m uvicorn retail_analytics.api:app --host 127.0.0.1 --port 8001
```

- Explorer: `http://127.0.0.1:8001/`
- API documentation: `http://127.0.0.1:8001/docs`

For frontend development, run `npm run dev` from `frontend/` while FastAPI runs at `127.0.0.1:8001`; Vite serves `http://127.0.0.1:5173` and proxies API requests. Check the UI with `npm test` and `npm run build`. For normal local serving, the compiled frontend is served directly at `/` by FastAPI; no separate Node server is needed. The Python API retains the legacy HTML fallback if the frontend has not been built.

Beat the Model uses strictly historical holdout predictions produced by a model fitted only on development observations; the directory and profile drawer use the saved `v1` model and day-711 derived profiles. Behavioral Paradox opens profiles in place without navigation.

## 5. Optional Docker deployment and scheduling

Create an untracked environment file for Compose (replace the example password):

```bash
cp .env.example .env
docker compose --profile automation up -d --build
```

Services:

| Service | Role |
|---|---|
| `db` | PostgreSQL 18 with a persistent named volume and health check |
| `api` | Multi-stage built React frontend + non-root Python 3.13 FastAPI on `127.0.0.1:8000` |
| `scheduler` (opt-in profile) | One batch at startup and repeats every 24 hours while Docker is running |

**Important:** Docker Compose starts its own PostgreSQL database. It does **not** copy the host's existing `retail_analytics` database, ingest the dataset, refresh marts, or automatically build Explorer tables. A fresh Docker database must be populated separately before scoring and explorer endpoints can serve data. The container image includes the model artifact, not the original transaction CSVs.

```bash
docker compose logs --tail=30 scheduler
docker compose ps
```

This is local container deployment, not a hosted public service. The GitHub Actions workflow runs tests on pushes and pull requests; it does not deploy infrastructure or images.

## 6. Tests and repository hygiene

```bash
python -m pytest -q
```

The repository ignores raw data, environment files, local database backups, Python caches, and build artifacts. Do not commit source CSVs or credential-bearing `.env` files. Commit only selected aggregate figures/reports needed to demonstrate the work; household-level scoring exports and database dumps should remain private unless redistribution rights are confirmed.

The Node dependency lockfile `frontend/package-lock.json` **is** committed; generated `frontend/node_modules/` and `frontend/dist/` are ignored. CI separately verifies the React frontend with `npm ci`, `npm test`, and `npm run build`.
