# Observability — Prometheus + Grafana

The nightly job is a batch process, so it exposes metrics the two ways batch jobs
can: a **textfile** for the node_exporter textfile collector, and an optional
**Pushgateway** push.

```bash
make metrics                                   # rebuild reports/metrics/nyc311.prom
python -m src.observability.metrics --push http://pushgw:9091
```

`src/orchestration/nightly_export.py` emits metrics automatically at the end of every
run (success *and* failure), so a job that dies still moves
`nyc311_nightly_run_total{status="failed"}`.

## Series

| Metric | Type | Labels | Meaning |
| --- | --- | --- | --- |
| `nyc311_nightly_duration_seconds` | gauge | `status` | wall-clock duration of the last run |
| `nyc311_nightly_last_success_timestamp_seconds` | gauge | — | when the last successful run finished |
| `nyc311_nightly_run_total` | counter | `status` | runs by terminal status (`ok`/`failed`) |
| `nyc311_nightly_cohorts` | gauge | — | cohorts in the last exported comparison |
| `nyc311_table_rows` | gauge | `table`,`source` | row counts per staging/mart table |
| `nyc311_table_lag_days` | gauge | `table` | today − newest `date_day` |
| `nyc311_table_freshness_ok` | gauge | `table`,`verdict` | 1 = within its freshness budget |
| `nyc311_freshness_checks_failed` | gauge | — | how many tables failed their budget |
| `nyc311_alert_triggered_total` | counter | `trigger` | alert-policy triggers fired |
| `nyc311_notification_total` | counter | `channel`,`result` | email/Slack sends and skips |
| `nyc311_export_artifact_bytes` | gauge | `kind` | size of the newest CSV/PDF/XLSX |

Counters are read back from the textfile before each write, so restarting the job
never produces a spurious counter reset.

## Scrape config

```yaml
# node_exporter
--collector.textfile.directory=/var/lib/node_exporter/textfile
```
Point the job at that directory:
```bash
python -m src.observability.metrics --out /var/lib/node_exporter/textfile/nyc311.prom
```
or set `PROMETHEUS_TEXTFILE_PATH` / `PROMETHEUS_PUSHGATEWAY_URL` in `.env`.

## Grafana starters

```promql
# nightly freshness SLO
time() - nyc311_nightly_last_success_timestamp_seconds > 36 * 3600

# runtime trend
nyc311_nightly_duration_seconds

# failing freshness checks
nyc311_freshness_checks_failed > 0

# alert noise (per day)
increase(nyc311_alert_triggered_total[1d])

# mart growth
increase(nyc311_table_rows{table="marts.mart_daily_volume_enriched_by_type"}[7d])
```

Suggested alert rules: *no successful run in 36 h*, *`nyc311_freshness_checks_failed > 0`
for 2 h*, *`increase(nyc311_nightly_run_total{status="failed"}[1d]) > 0`*.
