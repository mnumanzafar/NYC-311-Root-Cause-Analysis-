# Scheduling the nightly refresh and export

One command does the whole job:

```bash
python -m src.orchestration.nightly_export        # or: make nightly
```

Steps it performs:

1. **refresh** — re-runs the SQL pipeline (staging → intermediate → marts) so the
   enriched daily mart contains yesterday's 311 rows, weather and holidays.
2. **window** — picks the latest *complete* week as the post-change cohort and the
   preceding 4 weeks as the baseline (`--week-days`, `--baseline-weeks`).
   `--lag-days 1` drops the newest day, because 311 rows arrive late.
3. **compare** — re-tags and re-aggregates cohorts on that rolling window
   (`src/reporting/recent_week.py`), so the fixed windows in the SQL marts are untouched.
4. **export** — CSV + PDF + XLSX + the auto-written narrative markdown.
5. **deliver** — e-mails the files to the recipient list, when SMTP is configured.

Every run appends a line to `reports/exports/nightly/nightly_runs.jsonl` with the
window, cohort count, file paths and e-mail outcome — that file is the audit trail.

## Useful flags

| Flag | Effect |
| --- | --- |
| `--skip-refresh` | reuse the marts as they are (no DB writes) |
| `--from-parquet DIR` | read marts from parquet instead of Postgres |
| `--format csv\|pdf\|xlsx\|both\|all` | which artefacts to write |
| `--borough BROOKLYN --complaint-type "Noise - Residential"` | narrow the run (repeatable) |
| `--email-to a@x.com,b@x.com` | override the recipient list |
| `--email-dry-run` | build and log the message without sending |
| `--no-email` | files only |
| `--alpha 0.05` | significance threshold for the BH q-values |

Dry run that touches nothing: `make nightly-dry`.

## cron

```bash
make install-cron                      # 05:30 local, idempotent
CRON_SCHEDULE="0 6 * * *" bash deploy/install_cron.sh
```

`deploy/nightly_export.sh` is the cron entry point: it cds into the project,
sources `.env`, prefers `.venv/bin/python`, writes
`reports/exports/nightly/logs/nightly_<date>.log` and exits non-zero on failure so
cron mail (or your monitoring) picks the failure up.

## systemd

```bash
sudo cp deploy/nyc311-nightly.{service,timer} /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now nyc311-nightly.timer
systemctl list-timers nyc311-nightly.timer
journalctl -u nyc311-nightly.service -n 50
```

Adjust `User=` and `WorkingDirectory=` in the unit to match your deployment path.
`Persistent=true` means a missed run (machine asleep) fires on the next boot.

## Windows Task Scheduler

```powershell
schtasks /Create /TN "NYC311 nightly export" /SC DAILY /ST 05:30 ^
  /TR "C:\nyc311\.venv\Scripts\python.exe -m src.orchestration.nightly_export" ^
  /RU SYSTEM
```

Set the *Start in* directory to the project root so relative paths resolve.

## E-mail delivery

Configure in `.env` (never in `config.yaml` — it is committed):

```
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USER=nyc311-bot@example.com
SMTP_PASSWORD=...
SMTP_STARTTLS=true
EXPORT_EMAIL_FROM=nyc311-bot@example.com
EXPORT_EMAIL_TO=analytics@example.com,ops@example.com
EXPORT_EMAIL_CC=
```

The message body is the auto-written narrative (HTML + plain-text alternative) and
the CSV / PDF / XLSX are attached. Set `reporting.email.enabled: true` in
`config/config.yaml` once the credentials are in place. Without `SMTP_HOST` the job
still writes every file and logs that delivery was skipped — a mail outage never
loses an export.

## Failure behaviour

* Any exception exits with status `1` after logging a full traceback.
* The refresh step is transactional per SQL file; a failed mart leaves the previous
  night's data in place rather than a half-built table.
* Re-running the job for the same date overwrites that date's files — it is safe to
  retry after fixing the cause.
