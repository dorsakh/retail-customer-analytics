# Retail Customer Analytics

A retail analytics project examining household purchasing behavior, customer retention, promotional campaigns, and repeat-purchase patterns using PostgreSQL and the dunnhumby *The Complete Journey* dataset.

The current implementation covers data ingestion, relational modeling, data quality checks, SQL-based customer analytics, and historical feature generation for repeat-purchase prediction.

## Dataset

This project uses [dunnhumby's The Complete Journey](https://www.dunnhumby.com/source-files/), a dataset representing approximately two years of transactions from 2,500 frequent-shopping households.

The current analysis includes:

| Dataset component | Records |
|---|---:|
| Transaction line items | 2,595,732 |
| Unique shopping baskets | 276,484 |
| Households | 2,500 |
| Products | 92,353 |
| Marketing campaigns | 30 |
| Coupon redemption events | 2,318 |

Transaction dates are represented as sequential day numbers (1–711).

Seven source tables are used: transactions, products, household demographics, campaign definitions, campaign assignments, coupon definitions, and coupon redemptions.

The original CSV files are not included in this repository. They can be obtained from [dunnhumby](https://www.dunnhumby.com/source-files/) or the [Kaggle dataset](https://www.kaggle.com/datasets/frtgnn/dunnhumby-the-complete-journey).

## Data Architecture

Data preparation follows an ELT approach in PostgreSQL.

**Raw layer**

Source CSVs are loaded into PostgreSQL without altering their original records. Initial checks examine row counts, identifiers, candidate keys, basket consistency, and relationships between tables.

**Core layer**

Raw records are transformed into typed relational tables covering transactions, households, products, campaigns, and coupons.

Repeated coupon-to-product mappings are deduplicated in the core layer to prevent duplicated records in downstream joins, while the raw records remain unchanged.

Reconciliation queries verify that transaction counts, basket counts, quantities, sales, and discount totals are preserved between layers.

**Analytics layer**

Basket-level aggregations and household snapshots support customer behavior analysis and repeat-purchase modeling.

Household snapshots use historical purchasing activity to calculate recency, frequency, spending trends, basket characteristics, product diversity, discount usage, and visit regularity.

## Analysis

### Repeat-Purchase Patterns

Household purchasing behavior is examined across recency segments and spending trends.

A seven-day repeat-purchase outcome is evaluated at multiple historical observation points. SQL-based ranking strategies provide reference benchmarks for subsequent predictive models.

### Cohort Retention

Households are grouped by their first observed purchase period, and subsequent purchasing activity is measured in 30-day intervals.

Retention calculations account for incomplete observation windows. Small cohorts are excluded from the main reporting view to avoid overinterpreting unstable percentages.

Because the dataset represents frequent shoppers, first-observed purchases should not be interpreted as confirmed new-customer acquisitions.

### Campaign Performance

Campaign analysis examines targeted households, coupon redemption participation, purchasing activity, and spending during promotional periods.

Campaign spending is compared with an equally long preceding period where both windows are fully observed.

These comparisons describe purchasing associations, not the causal or incremental effects of marketing campaigns.

## Repository Structure

```text
.
├── scripts/
│   ├── assess_repurchase_target.py
│   └── download_data.py
│
├── sql/
│   ├── schema/
│   │   ├── raw.sql
│   │   └── core.sql
│   │
│   ├── load/
│   │   ├── load_raw.sql
│   │   └── load_core.sql
│   │
│   ├── checks/
│   │   ├── raw_row_counts.sql
│   │   ├── raw_integrity.sql
│   │   └── core_reconciliation.sql
│   │
│   ├── marts/
│   │   ├── customer_behavior.sql
│   │   └── household_snapshots.sql
│   │
│   └── analysis/
│       ├── repurchase_signals.sql
│       ├── cohort_retention.sql
│       └── campaign_performance.sql
│
└── README.md
```

## Getting Started

### Requirements

- PostgreSQL and the `psql` command-line client
- The Complete Journey CSV files
- Python for the supporting scripts

The SQL implementation has been tested with PostgreSQL 18.

### 1. Prepare the data

Download the dataset and place the following CSV files in:

`data/raw/complete_journey/`

```text
campaign_desc.csv
campaign_table.csv
coupon.csv
coupon_redempt.csv
hh_demographic.csv
product.csv
transaction_data.csv
```

The `data/raw/` directory is excluded from Git.

### 2. Create the database

From the repository root:

```bash
createdb retail_analytics
```

This step is required only when setting up a new database.

### 3. Load and validate the raw data

```bash
psql -d retail_analytics -v ON_ERROR_STOP=1 -f sql/schema/raw.sql

psql -d retail_analytics -v ON_ERROR_STOP=1 -1 -f sql/load/load_raw.sql

psql -d retail_analytics -v ON_ERROR_STOP=1 -f sql/checks/raw_row_counts.sql

psql -d retail_analytics -v ON_ERROR_STOP=1 -f sql/checks/raw_integrity.sql
```

### 4. Build the core tables

```bash
psql -d retail_analytics -v ON_ERROR_STOP=1 -f sql/schema/core.sql

psql -d retail_analytics -v ON_ERROR_STOP=1 -1 -f sql/load/load_core.sql

psql -d retail_analytics -v ON_ERROR_STOP=1 -f sql/checks/core_reconciliation.sql
```

### 5. Build the analytical datasets

```bash
psql -d retail_analytics -v ON_ERROR_STOP=1 -f sql/marts/customer_behavior.sql

psql -d retail_analytics -v ON_ERROR_STOP=1 -f sql/marts/household_snapshots.sql
```

### 6. Run the analyses

```bash
psql -d retail_analytics -f sql/analysis/repurchase_signals.sql

psql -d retail_analytics -f sql/analysis/cohort_retention.sql

psql -d retail_analytics -f sql/analysis/campaign_performance.sql
```

These setup commands are intended for a fresh database. The load scripts are not designed to append the same source records repeatedly.

## Current Development

The PostgreSQL data model and SQL analyses are implemented.

The next development stages cover time-aware repeat-purchase modeling, model evaluation and calibration, business intelligence dashboards, and model-serving components.

Implementation details and measured results will be documented as these components are completed.