# NYC 311 Anomaly Investigation — "Why did complaint volume drop?"

**Key finding (fill in after analysis):** _Brooklyn 311 complaint volume fell X% in Q3 20XX vs. the 3-year seasonal baseline (-Nσ). Root cause: <cause>, evidenced by category isolation, p<0.01 significance, and exact timing alignment with <event>._

The main deliverable is [`reports/root_cause_case_study.md`](reports/root_cause_case_study.md).

## Structure
| Path | Purpose |
|---|---|
| `sql/` | staging -> intermediate -> marts (dbt-style layering) |
| enrichment | daily weather + holiday joins, see `docs/external_enrichment.md` (`make external`) |
| `src/analysis/` | tested, importable statistical logic (change-point, STL, cohorts, tests) |
| `notebooks/` | exploration only — no business logic lives here |
| `tests/` | pytest coverage of analysis functions |
| `powerbi/` | executive dashboard |
| `reports/` | case study + figures + 1-page exec summary |
| `docs/` | methodology, data dictionary, architecture, `ops_monitoring.md` |

## Quickstart
```bash
cp .env.example .env      # fill in Postgres credentials
make setup                # venv + requirements
make etl                  # extract -> load -> sql pipeline
make test                 # pytest
```

## Data
NYC Open Data 311 Service Requests (Socrata dataset `erm2-nwe9`). Reference data
(weather, holidays, policy dates) lives in `data/external/`.

## Method
Detect (change-point) -> Hypothesize (log all) -> Test (STL, cohort, z/chi-square,
confounder elimination, Isolation Forest) -> Conclude (with falsification criteria) -> Recommend.
See `docs/methodology.md`.

## Power BI cohort comparison

`marts.mart_cohort_daily` (day level) and `marts.mart_cohort_comparison`
(borough × complaint_type level) power the **Cohort Comparison** page, which
contrasts the baseline and post-change windows with length-normalised totals,
effect sizes, and weather/calendar-adjusted deltas. The windows are defined once
in `sql/staging/stg_calendar.sql`; rebuild with `make sql` after editing.
See `powerbi/report_spec.md` (Page 6) and `powerbi/measures.dax`.

## Sharing results

`make export` writes CSV + PDF + Excel + an auto-written case-study narrative to
`reports/exports/` — deltas, effect sizes, Welch p-values with BH q-values, and
weather/holiday driver flags for every borough x complaint-type cohort. Add
`--borough` / `--complaint-type` (or `--filters-json powerbi/filter_state.json`) to export
exactly the selection showing on the Power BI cohort page. See `docs/exports.md`.

Any window, not just the latest one:

```bash
make range POST_START=2024-06-01 POST_END=2024-06-30
```

## Nightly automation

```bash
make nightly       # refresh marts -> latest complete week vs prior 4 weeks -> export -> e-mail
make nightly-dry   # same, without touching the DB or sending mail
make install-cron  # 05:30 daily; systemd units live in deploy/
```

`src/orchestration/nightly_export.py` is the single entry point and appends an audit
line to `reports/exports/nightly/nightly_runs.jsonl` per run. SMTP settings go in `.env`
(see `.env.example`). Full runbook: `docs/scheduling.md`.

Each run also: scores itself against the alert policy and **only e-mails when the
latest week is genuinely anomalous** (significant cohorts, a net shift, or a change
in the top drivers), posts a Slack summary with links to the CSV/PDF/Excel, and
refreshes the status page.

```bash
make status        # last run, record counts, mart freshness, latest artifacts
```

`reports/status.html` is regenerated after every nightly run. Details and tuning:
`docs/ops_monitoring.md`.

