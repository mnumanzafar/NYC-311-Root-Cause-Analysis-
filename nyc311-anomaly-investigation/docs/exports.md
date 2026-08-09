# Cohort comparison exports (CSV + PDF)

One command turns `marts.mart_cohort_comparison` (+ `marts.mart_cohort_daily`) into a
shareable pair of files: a full CSV extract and a one-page-per-40-cohorts PDF brief.

```bash
make export                                  # both formats -> reports/exports/
python -m src.reporting.cohort_export --out reports/exports --format csv
python -m src.reporting.cohort_export --from-parquet data/processed/marts   # offline
```

## What gets exported

| Group | Columns |
|---|---|
| Identity | `borough`, `complaint_type`, `baseline_days`, `post_days` |
| Volumes | `baseline_volume`, `post_volume`, `baseline_daily_avg`, `post_daily_avg`, `baseline_volume_scaled` |
| Deltas | `abs_change`, `pct_change`, `contribution_pct` |
| Effect size | `effect_size_d` (Cohen's d, pooled sd) |
| Significance | `t_statistic`, `p_value` (Welch, daily volumes), `q_value` (Benjamini-Hochberg), `is_significant` |
| Driver flags | `temp_max_f_delta`, `precip_in_delta`, `baseline_driver_day_pct`, `post_driver_day_pct`, `driver_day_pct_delta`, `calendar_mix_warning` |

Rows are ranked by absolute contribution to the citywide change, so the first rows are
the cohorts worth defending in the case study.

## Statistics notes

- **Welch t-test** on the daily volume series of each cohort (unequal variance, unequal
  window lengths are fine). Cohorts with fewer than two days per period return `NaN`.
- **BH q-values** correct for running one test per cohort; `is_significant` uses
  `q < alpha` (default `0.01`, override with `--alpha`).
- `abs_change` compares against a **length-normalised** baseline
  (`baseline_daily_avg x post_days`), so a 90-day window never looks bigger than a
  30-day one for structural reasons.

## PDF flags

- `SIG` — significant after FDR control.
- `MIX` — baseline/post calendar mix differs by more than 10 pp (weekend/holiday share);
  treat the delta as confounded.
- `DRV` — weather/holiday driver-day share moved by 10 pp or more between windows.

The PDF shows the top 40 cohorts and the summary statistics; the CSV always contains
every cohort and every column, so it is the artifact to attach for downstream analysis.

## Excel workbook (`--format xlsx` / `all`)

`src/reporting/excel_export.py` writes one workbook with five sheets, so each audience
gets its own view instead of one 25-column sheet:

| Sheet | Contents |
|---|---|
| `Summary` | run metadata, scope, windows, net change, significant-cohort count, sheet guide |
| `Deltas` | volumes, length-normalised baseline, abs/% change, contribution share |
| `Effect sizes` | Cohen's d, Welch t, p, BH q, significance flag |
| `Driver flags` | temperature/precipitation deltas, driver-day share shift, calendar-mix warning |
| `Narrative` | the auto-written case study as text |

Every data sheet has a frozen header row, an auto-filter, sized columns, and diverging
conditional formatting on `abs_change`, `effect_size_d` and `q_value`.

## Auto-written case-study narrative

Every export also emits `<stem>_narrative.md` (and page 2+ of the PDF, and the e-mail
body). `src/reporting/narrative.py` writes five sections from the numbers themselves:

1. **What changed** — net delta, direction, how many cohorts clear BH significance.
2. **Where the change comes from** — the top contributing cohorts with delta, share of
   the total change, effect size, q-value and driver caveats.
3. **Confounders tested and eliminated** — window length, calendar mix, weather,
   multiple comparisons, one-off-spike-vs-level-shift; each marked ELIMINATED or
   RETAINED with the evidence that decided it.
4. **Conclusion** — where the change is concentrated and what remains unresolved.
5. **Recommended next steps.**

It is a first draft with the arithmetic already right, not a replacement for
`reports/root_cause_case_study.md`.

## Respecting the Power BI slicers

The export can mirror exactly what the analyst is looking at on Page 6:

```bash
python -m src.reporting.cohort_export --borough BROOKLYN --borough BRONX \
    --complaint-type "Noise - Residential"
python -m src.reporting.cohort_export --filters-json powerbi/filter_state.json
```

`src/reporting/filters.py` reads either the CLI flags or a JSON slicer-state file that a
Power BI Python-script visual writes to disk (see `powerbi/report_spec.md` → Page 6,
"One-click export"). Contribution percentages are re-based to the filtered selection, so
the shares in a borough-filtered export sum to that borough's change, and the filename
gets a scope suffix (`cohort_comparison_brooklyn-bronx.csv`).

## Rolling "most recent week" exports

`--recent-week` ignores the fixed windows in the marts and compares the latest complete
week against the prior four weeks, which is what the nightly job runs. See
`docs/scheduling.md`.

## E-mailing the files

```bash
python -m src.reporting.cohort_export --format all --email --email-to team@example.com
python -m src.reporting.cohort_export --email --email-dry-run   # build, log, don't send
```

Credentials come from `.env` (`SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`,
`SMTP_STARTTLS`, `EXPORT_EMAIL_FROM`, `EXPORT_EMAIL_TO`, `EXPORT_EMAIL_CC`). The body is
the narrative rendered as HTML with a plain-text alternative; the CSV/PDF/XLSX are
attached. Dry-run mode returns the exact recipients, subject and attachment list without
opening a connection, which is what the tests assert against.

