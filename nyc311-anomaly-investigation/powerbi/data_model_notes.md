# Power BI Data Model Notes

Files in this folder:

| File | Purpose |
| --- | --- |
| `report_spec.md` | Page-by-page build spec (visuals, fields, bookmarks, drill-through) |
| `measures.dax` | Full DAX measure library to paste into the `Measures` table |
| `queries.pq` | Power Query (M) source definitions for every model table |
| `theme.json` | Report theme (View > Themes > Browse for themes) |

## Star schema
- **Fact:** `marts.mart_daily_volume_enriched_by_type` (grain: date × borough ×
  complaint_type, with weather/holiday columns, 28-day baseline and ±2σ band).
- **Overlay fact:** `marts.mart_daily_driver_events` (grain: date × borough ×
  driver_type) — the unpivoted weather/holiday flags that drive the overlay ribbon
  and the "Driver type" slicer.
- **Dimensions:** `staging.stg_calendar` (date table, also carries
  `in_event_window` / `in_baseline_window`), `DimBorough`, `DimComplaintType`,
  `DimDriverType`.
- Single-direction 1:* relationships from dimensions to both facts; borough and
  date join to `Driver` as well so overlays follow the same filters as volume.

## Pages
1. **Enriched Timeline** — volume vs 28-day mean and ±2σ band, anomaly markers,
   shaded weather/holiday ribbon, temperature/precip overlay toggle.
2. **Borough Drilldown** — matrix hierarchy borough → complaint type, small
   multiples, decomposition tree on excess vs baseline.
3. **Weather & Holiday Effect** — driver-day vs non-driver-day lift, temp/precip
   scatter with trend line, holiday table.
4. **Segment Detail (drill-through)** — YoY, weekday waterfall, anomalous-day list.
5. **Evidence Summary** — hypothesis/verdict table mirroring the case study.
Plus a `tt_day_detail` tooltip page used by every timeline visual.

## Notes
- Import mode for the marts (small, aggregated); avoid DirectQuery on the
  request-grain table.
- Keep the .pbix pointed at `marts.*` and `staging.stg_calendar` only — never `raw.*`.
- Edit the event/baseline window dates at the top of `sql/staging/stg_calendar.sql`
  to match the anomaly you are investigating, then re-run `make sql`.
- Driver lift on page 3 is descriptive; the inferential answer comes from the
  Poisson confounder model in `src/analysis/confounders.py`.

## Cohort comparison tables (Page 6)

| Table | Source | Grain | Relationships |
|---|---|---|---|
| `CohortDaily` | `marts.mart_cohort_daily` | date × borough × complaint_type (cohort windows only) | many-to-one → `DimBorough`, `DimComplaintType`, `DimPeriod[cohort_period]`; **no** relationship to `Calendar` (it is a filtered subset — relating it would let the date slicer empty the cohort visuals) |
| `CohortCompare` | `marts.mart_cohort_comparison` | borough × complaint_type | many-to-one → `DimBorough`, `DimComplaintType`. Import it for the pre-computed SQL columns (`effect_size_d`, `calendar_mix_warning`) used as a cross-check against the DAX measures |
| `DimPeriod` | Enter data / M literal | 2 rows | sort `cohort_period` by `period_order` so Baseline always renders left of Post-change |

Notes:
- Compare periods on `[Baseline Volume | Scaled]`, never raw `baseline_volume`, unless
  the windows are the same length.
- `[Cohort p-value approx]` is a normal-tail approximation for the report surface;
  the authoritative test is `src/analysis/hypothesis_tests.py` with FDR control.
