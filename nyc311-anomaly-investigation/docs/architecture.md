# Architecture

```text
Socrata API (erm2-nwe9)
        |  src/etl/extract.py
        v
data/raw/nyc311_raw.parquet
        |  src/etl/load_to_db.py
        v
Postgres  raw.nyc311_requests
        |  src/etl/run_sql_pipeline.py
        v
   staging.stg_311_requests + staging.stg_calendar     (rename / type / clean)
        v
   intermediate.int_daily_complaint_volume             (dedup, dense daily grain)
        v
   marts.mart_daily_volume_by_borough
   marts.mart_cohort_breakdown                         (analysis-ready)
        |                          \
        |  src/analysis/*           \  Power BI (DirectQuery / import)
        v                            v
   notebooks/ (exploration)      powerbi/nyc311_investigation.pbix
        v
   reports/root_cause_case_study.md  <- the deliverable
```

Design rules:
- Notebooks import from `src/`; they never define statistical logic.
- Every function in `src/analysis/` has a pytest in `tests/`.
- SQL is layered staging -> intermediate -> marts; each layer is idempotent (`DROP`/`CREATE`).
- Config lives in `config/config.yaml`; credentials only in `.env`.
