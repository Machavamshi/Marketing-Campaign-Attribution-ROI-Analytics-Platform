# Marketing Campaign Attribution & ROI Analytics Platform

A modular Flask and SQLite application for comparing marketing attribution methods and campaign ROI. It includes a reproducible synthetic-data generator, validation, exception traceability, CSV workflows, and an interactive dashboard. No public or personal data is used.

## Quick start

Requires Python 3.10+.

```powershell
python -m pip install -r requirements.txt
python -m data_generator.generate_all --scale starter --seed 20261022
python .\app.py
```

Open `http://127.0.0.1:5000` and create an account to sign in. The first run imports the starter CSVs from `data/` into `instance/marketing.db`. The starter preset emits 50 campaigns, 5,000 contacts, 20,000 touchpoints, and 1,000 opportunities. Generate the requested full scale with:

```powershell
python -m data_generator.generate_all --scale full --seed 20261022 --output .\data-full
```

The full preset emits exactly 500 campaigns, 50,000 contacts, 200,000 touchpoints, and 10,000 opportunities. Use `--seed` to select a seed (default `20261022`) and `--campaigns`, `--contacts`, `--touchpoints`, or `--opportunities` to override individual scale dimensions. Both presets use the same generator and rules. The generator uses Python's seeded `random`, Faker, and NumPy generators.

## Application features

* Dashboard KPIs, attribution chart, and reconciliation status.
* Campaign search, creation, and details; campaign name/budget revisions are retained in an append-only event history. Optional recorded spend is distinct from campaign budget.
* Contact, touchpoint, lead, opportunity, and order views; contact-level journey timelines.
* First-touch, last-touch, and linear multi-touch comparison across chronological evaluation periods.
* Campaign/channel ROI and visible missing-cost or currency-mismatch status.
* Separate labelled exception view, validation report, CSV import/export, and dataset generation.
* JSON endpoints: `/analytics/api/comparison` and `/analytics/api/roi`.
* Account registration and sign-in; the analytics workspace requires an authenticated account. Passwords require at least 6 characters, including an uppercase letter, a number, and a special character. Password recovery uses expiring, one-time email links.

CSV imports append within a transaction and enforce schema, primary-key uniqueness, allowed values, and foreign keys. Export is available for operational tables; ground-truth labels are not included in operational exports.

## Configuration

Set `DATABASE_PATH`, `DATASET_DIR`, `BASE_CURRENCY`, and `SECRET_KEY` as environment variables to override local defaults. Configure `MAIL_SERVER`, `MAIL_PORT`, `MAIL_USERNAME`, `MAIL_PASSWORD`, `MAIL_USE_TLS`, `MAIL_DEFAULT_SENDER`, and `PUBLIC_BASE_URL` to enable password reset email delivery. Password reset is unavailable until SMTP and the public application URL are configured. The default base currency is INR. A database created by the earlier USD version is not silently converted; point `DATABASE_PATH` at a new SQLite file to initialize the INR dataset. Use a unique secret key in any deployed environment. The default development key is not suitable for deployment.

## Outputs

CSV files are generated for all entities, bridge tables, state-event history, attribution results, and campaign metrics. `ground_truth.csv` and `ground_truth.json` separately label the five deliberate exceptions; the labels are not included in operational feature tables. `schema.sql` defines the SQLite schema and keys. `seed.sql` contains schema plus insert statements for the generated operational CSVs (not ground truth). `validation_summary.json` records integrity and revenue reconciliation checks. `source_manifest.json` records the seed, requested scale, row counts, date range, provenance, rule version, and SHA-256 checksums of the dataset files.

Empty CSV fields represent NULL. SQL imports preserve those values as SQL NULL.

## Rules and evaluation

* Campaigns have one channel, one audience, and one creative; contacts can belong to multiple audiences through `contact_audiences`. A touchpoint belongs to exactly one contact, campaign, channel, and creative.
* Sessions may be anonymous and may optionally reference a contact, touchpoint, lead, and opportunity. Leads reference a source session and a contact. Opportunities reference a lead and contact; orders represent closed-won revenue.
* Lead score is derived from pre-conversion eligible touch count, unique campaigns, and session page views: `min(100, 15 + min(40, 7 × touches) + min(20, 5 × campaigns) + min(20, 2 × pages))`. A conversion window of up to 180 days follows the anchor touch. Score >=70 yields closed-won, >=40 qualified, otherwise closed-lost. A won opportunity produces one canonical order equal to its estimated amount.
* First-touch and last-touch assign all credit to the earliest and latest eligible touch respectively. Linear attribution splits credit evenly across eligible touch events, then aggregates event-level credit by campaign. Only touchpoints at or before conversion are eligible. Revenue allocation rounds to cents and assigns any residual to the last campaign allocation, so each model reconciles exactly.
* Evaluation is chronological: train covers 2026-01-01 through 2026-06-30, validation 2026-07-01 through 2026-09-30, and test 2026-10-01 through 2026-12-31. Dates are UTC.
* Campaign ROI is `(period-attributed revenue - period base-currency spend) / period base-currency spend`. Available campaign spend is allocated to train/validation/test in proportion to campaign days active in each period; paise are balanced so period spend reconciles exactly to the source cost. Missing or non-INR spend yields NULL ROI rather than treating spend as zero. Period-level ROI is a comparison metric, not incremental profit.

## Tests

```powershell
python -m pytest -q
```

## Reproducibility

Runs with identical scale arguments and seed produce identical CSV, JSON, schema, and SQL bytes. The manifest itself is excluded from its own checksum list. The test suite regenerates two small datasets and verifies checksums, anomaly coverage, reconciliation, and SQL foreign keys.

## Data model

See [data_dictionary.md](./data_dictionary.md) for per-field requirements and validation, and [schema.sql](./schema.sql) for database constraints and indexes. Campaign revisions and lead/opportunity state transitions are appended to event-history tables with immutable IDs. Campaign-to-touchpoint, campaign-to-cost, channel-to-campaign, contact-to-touchpoint, contact-to-session, contact-to-lead, and lead-to-opportunity are 1:N; opportunity-to-order is normally 1:1, with duplicates retained and labelled. Campaign/contact and contact/audience journeys are represented by touchpoint and audience bridge records.

The five known exceptions are intentionally localized: duplicate order for one opportunity, a post-conversion touch, a EUR campaign cost, an omitted campaign cost, and an anonymous session linked to a lead without contact/touch evidence. Their expected analyst decisions are in the separate ground-truth files.
