# Ops: custom ranges, alert gating, Slack, and the status dashboard

Four operational features sit on top of the nightly export. All of them respect
the Power BI borough / complaint-category filters, because they all route
through `src.reporting.cohort_export.run()`.

---

## 1. Export any date range (not just the last week)

The nightly job defaults to *the latest complete week vs the prior 4 weeks*.
Pass an explicit post-change window to override that — useful for re-running an
investigation window, a heat wave, or a policy change after the fact.

```bash
# Custom post window; baseline defaults to the equally long block before it
python -m src.reporting.cohort_export \
  --post-start 2024-06-01 --post-end 2024-06-30 --baseline-weeks 2

# Fully explicit windows
python -m src.reporting.cohort_export \
  --post-start 2024-06-01 --post-end 2024-06-30 \
  --baseline-start 2024-04-01 --baseline-end 2024-05-31

# Same thing through the orchestrator (refresh + export + notify)
python -m src.orchestration.nightly_export \
  --post-start 2024-06-01 --post-end 2024-06-30

# Makefile shortcut
make range POST_START=2024-06-01 POST_END=2024-06-30
```

Rules enforced by `recent_week.explicit_windows()`:

- reversed dates are swapped, so `--post-start` after `--post-end` still works;
- an explicit baseline that overlaps the post window raises immediately;
- `--baseline-start` requires `--baseline-end`;
- with no explicit baseline, the baseline is `baseline_weeks x (post length)`
  days ending the day before the post window.

Deltas stay comparable across unequal windows because the comparison mart
length-normalises the baseline (`baseline_volume_scaled`).

**Filters still apply.** `--borough` / `--complaint-type`, or the
`--filters-json powerbi/filter_state.json` file written by the Power BI export
button, are applied to the daily rows *before* the windows are tagged, and the
output stem is suffixed with the filter slug.

---

## 2. Anomaly-driven notifications

`--notify-on-anomaly` (on by default in the nightly job; disable with
`--always-email`) scores each run and e-mails only when it is worth reading.
The policy lives in `config/config.yaml` under `reporting.alerts` and in
`src/reporting/alerting.py`.

| Trigger | Fires when |
| --- | --- |
| `significant` | >= `min_significant` cohorts with BH `q < alpha` **and** `abs_change >= min_abs_change` |
| `net_shift` | citywide net change exceeds `net_pct_threshold`% of the normalised baseline |
| `driver_change` | a new cohort entered the top `top_n`, or the leader changed vs last run |
| `driver_share` | a top cohort's weather/holiday driver-day share moved >= `driver_pp_threshold` pp |
| `first_run` | no previous fingerprint on disk yet |

Each run writes a fingerprint (top cohorts, significance list, net change) to
`reports/exports/nightly/alert_state.json`; the next run diffs against it. A
corrupt or missing state file is treated as a first run, never as a crash.
When the policy stays quiet the export files are still written — only the
e-mail is suppressed, and the run log records `email.skipped = "no anomaly"`.

The triggers and their plain-English reasons are prepended to the e-mail body
and posted to Slack, so recipients see *why* the alert fired.

Tune it:

```bash
python -m src.orchestration.nightly_export \
  --alert-alpha 0.05 --alert-min-abs-change 50 --alert-net-pct 5
```

---

## 3. Slack alerts per run

Every nightly run posts a Block Kit summary: status, scope, windows, duration,
the alert headline and reasons, plus one line per generated artifact.
Failures post a red message with the exception text, before the job exits
non-zero.

Configure **one** transport in `.env`:

```bash
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...   # simplest
# or
SLACK_BOT_TOKEN=xoxb-...                                 # needs chat:write
SLACK_CHANNEL=#ops-311
```

Set `EXPORT_BASE_URL` (share, S3, or intranet prefix) to turn the CSV/PDF/Excel
file names into clickable links; without it Slack shows the absolute path,
which still works for anyone on the same file share.

Slack never fails the job: network errors and Slack-side rejections are logged
and recorded in the run log. Preview a payload without sending:

```bash
python -m src.orchestration.nightly_export --skip-refresh --slack-dry-run --no-email
make nightly-dry
```

---

## 4. Status dashboard

```bash
make status                                  # text summary in the terminal
python -m src.reporting.status --html reports/status.html
python -m src.reporting.status --json        # machine-readable state
```

It reports:

- **Last nightly run** — finish time, age, duration, window, cohort count, and
  whether e-mail / Slack actually went out (read from `nightly_runs.jsonl`).
  A successful run older than 36h is downgraded to `stale`.
- **Record counts + mart freshness** — rows and newest `date_day` per table with
  an OK / STALE / EMPTY / MISSING verdict against the per-table lag budgets in
  `status.py` (`FRESHNESS_BUDGET`). Reads Postgres when reachable and falls back
  to the parquet mirror (`--from-parquet data/processed/marts`).
- **Latest artifacts** — most recent CSV, PDF, Excel and narrative with size and
  timestamp, linked via `EXPORT_BASE_URL` or a `file://` path.

The nightly job refreshes `reports/status.html` at the end of every run
(disable with `--no-status-html`), so the page is always current without a
server. Overall verdict: `healthy`, `degraded` (stale marts or a stale run), or
`attention` (failed run or unreachable table) — the CLI exits 1 on `attention`,
which makes it usable as a monitoring check.
