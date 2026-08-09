# Power BI Report Spec — Enriched Daily Volume

Build target: `nyc311_investigation.pbix`. Theme: `powerbi/theme.json`
(View > Themes > Browse). Queries: `powerbi/queries.pq`. Measures: `powerbi/measures.dax`.

## Model

| Table | Source | Grain | Role |
| --- | --- | --- | --- |
| `Fact` | `marts.mart_daily_volume_enriched_by_type` | date × borough × complaint_type | fact |
| `Driver` | `marts.mart_daily_driver_events` | date × borough × driver_type | overlay fact |
| `Calendar` | `staging.stg_calendar` | date | date table |
| `DimBorough`, `DimComplaintType`, `DimDriverType` | derived distinct lists | — | dimensions |

Relationships (all single-direction, 1:*):
`Calendar[date_day] → Fact[date_day]`, `Calendar[date_day] → Driver[date_day]`,
`DimBorough[borough] → Fact[borough]` **and** `→ Driver[borough]`,
`DimComplaintType[complaint_type] → Fact[complaint_type]`,
`DimDriverType[driver_type] → Driver[driver_type]`.
Mark `Calendar` as the date table on `date_day`. Slice by dimension columns, never by
the fact copies, so borough filters hit volume and overlays together.

---

## Page 1 — Enriched Timeline (landing)

Canvas 1280×720, 12-column grid.

| # | Visual | Fields | Notes |
| --- | --- | --- | --- |
| 1 | Cards ×4 | `[Volume]`, `[YoY %]`, `[Anomaly Days]`, `[Driver Lift %]` | top strip |
| 2 | Line and stacked column chart | X `Calendar[date_day]`; Column `[Overlay Band]`; Lines `[Volume]`, `[Rolling Mean 28D]`, `[Band Upper 2s]`, `[Band Lower 2s]` | the overlay column renders as a shaded ribbon behind the series on driver days — set column fill to 25% transparency, gap width 0% |
| 3 | Scatter layer (same visual, extra line) | `[Anomaly Marker]` | line style none, markers on, color `#C0392B` |
| 4 | Secondary-axis line | `[Avg Max Temp]` or `[Total Precip]` (bookmark toggle) | right axis, dashed, `#E67E22` |
| 5 | Slicers | `Calendar[date_day]` (between), `DimBorough[borough]`, `DimComplaintType[complaint_type]`, `DimDriverType[driver_type]` | driver slicer filters the ribbon only |
| 6 | Tooltip page | `Driver Labels`, `holiday_name`, `temp_max_f`, `precip_in`, `snowfall_in`, `[Rolling Z]` | see "Tooltip page" below |

Dynamic title: `[Title | Timeline]` (Format > Title > fx > Field value).

Bookmarks: **Temperature overlay** / **Precipitation overlay** / **No overlay** —
each toggles visibility of the secondary-axis measure; wire to a 3-button group.

## Page 2 — Borough Drilldown

- Matrix: rows `DimBorough[borough]` → `DimComplaintType[complaint_type]`; values
  `[Volume]`, `[Volume LY]`, `[YoY %]`, `[Excess vs Baseline]`, `[Rolling Z]`.
  Enable the drill-down hierarchy (expand/collapse), conditional formatting on
  `[Rolling Z]` via `[Anomaly Color]` (Format > Cell elements > Background > Field value).
- Small-multiples line chart: `[Volume]` by `Calendar[date_day]`, small multiples =
  `DimBorough[borough]`, 3×2 layout, shared y-axis off.
- Decomposition tree: analyze `[Excess vs Baseline]`, explain by `borough`,
  `complaint_type`, `driver_type`, `Calendar[day_name]`.
- Right-click a borough → **Drill through** to Page 4.

## Page 3 — Weather & Holiday Effect

- Scatter: X `[Avg Max Temp]`, Y `[Volume]`, details `Calendar[date_day]`,
  play axis `Calendar[month]`, trend line on. Repeat with `[Total Precip]`.
- Clustered bar: `[Avg Volume | Driver Days]` vs `[Avg Volume | Non-Driver Days]`
  by `DimDriverType[driver_type]`, with `[Driver Lift %]` as a data label.
- Holiday table: `Driver[driver_detail]` (holiday name), `[Volume]`, `[YoY %]`,
  `[Rolling Z]`, filtered to `driver_group = "Calendar"`.
- Text box: reminder that lift is descriptive; the Poisson confounder model in
  `src/analysis/confounders.py` is the inferential answer.

## Page 4 — Segment Detail (drill-through)

Drill-through fields: `DimBorough[borough]`, `DimComplaintType[complaint_type]`.
- Header card with `[Volume]`, `[YoY %]`, `[Anomaly Days]`.
- Line: `[Volume]` vs `[Volume PY Same Weekday]`.
- Waterfall: `[Delta vs Baseline]` broken down by `Calendar[day_name]`.
- Table of anomalous days: `Calendar[date_day]`, `[Volume]`, `[Rolling Z]`,
  `Driver Labels`, filtered to `[Anomaly Flag] = 1`.

## Page 5 — Evidence Summary

Static-ish page mirroring `reports/root_cause_case_study.md`: hypothesis, test,
statistic, verdict. Use a table over a small `Evidence` query (Enter data) plus
`[Contribution to Change %]` bar chart by `complaint_type`.

## Tooltip page (`tt_day_detail`)

Page size Tooltip (320×240), `Allow use as tooltip` on. Cards for `[Volume]`,
`[Rolling Z]`, `[Driver Labels]`, `[Avg Max Temp]`, `[Total Precip]`.
Set it as the tooltip on every timeline visual.

---

## Refresh & performance

- Import mode against `marts.*` only; the by-type mart is ~5k rows/year/borough.
- Set incremental refresh on `Fact` (`date_day`, archive 3 years, refresh 10 days)
  if you extend the pull beyond a couple of years.
- Rebuild the marts before refreshing: `make sql` (or `make external` after a
  weather/holiday reload).

## Page 6 — Cohort Comparison (Baseline vs Post-change)

Purpose: contrast the two investigation windows side by side and let the analyst
drill from citywide → borough → complaint category without losing the
length-normalised and weather-adjusted framing.

Tables: `CohortCompare` (period-level), `CohortDaily` (day-level),
`DimPeriod` (sort `cohort_period` by `period_order`), plus the shared
`DimBorough` / `DimComplaintType` dimensions.

Dynamic title: `[Title | Cohort]`. Card under it: `[Cohort Mix Warning]`
(hidden when blank because the measure returns "").

**Interaction bar (top)**
- Slicers: `DimBorough[borough]` (dropdown, multi-select), `DimComplaintType[complaint_type]`
  (searchable list), `CohortDaily[primary_driver]` (tile), `DimPeriod[cohort_period]`
  (used only on the distribution visuals — set cross-filter interactions to
  *None* on the KPI row so both periods stay visible there).
- Field parameter `Cohort Split` = { `DimBorough[borough]`, `DimComplaintType[complaint_type]`,
  `CohortDaily[day_name]`, `CohortDaily[primary_driver]` }. Bind it to the axis of the
  butterfly, waterfall and scatter so one control re-pivots the whole page.
- Numeric range slicer on `[Cohort Delta]` via a calculated column is not possible —
  use the `Top N` visual filter on `[Cohort Delta]` instead (default Top 15).

**Visuals**
1. KPI row (5 cards): `[Baseline Daily Avg]`, `[Post Daily Avg]`, `[Cohort Delta]`,
   `[Cohort Delta %]`, `[Cohort Verdict]` — conditional font colour on the last via
   `[Cohort Verdict Color]`.
2. Butterfly / tornado (clustered bar, two measures mirrored): `[Baseline Volume | Scaled]`
   and `[Post Volume]` by `Cohort Split`, sorted by `[Cohort Delta]` desc.
   Data label `[Cohort Delta %]`.
3. Waterfall: category `Cohort Split`, Y `[Cohort Delta]`, breakdown = top 10 with
   "Other" — reads directly as *which cohorts produced the change*.
4. Overlaid period lines: line chart, X `CohortDaily[day_in_period]`, legend
   `DimPeriod[cohort_period]`, Y `[Cohort Volume]`. Because the x-axis is the day
   index, unequal calendar windows still overlay cleanly.
5. Distribution: box-and-whisker (or a `Cohort Daily Avg` + error-bar column chart if
   you avoid custom visuals) of `CohortDaily[volume]` by `DimPeriod[cohort_period]`,
   small multiples = `DimBorough[borough]`. Shows whether the shift is a level change
   or a few outlier days.
6. Comparison matrix: rows `DimBorough[borough]` → `DimComplaintType[complaint_type]`;
   values `[Baseline Daily Avg]`, `[Post Daily Avg]`, `[Cohort Delta]`, `[Cohort Delta %]`,
   `[Cohort Contribution %]`, `[Cohort Effect Size d]`, `[Cohort p-value approx]`,
   `[Cohort Verdict]`. Conditional background on `[Cohort Delta %]` (diverging red/blue),
   icon set on `[Cohort Significant]`. Drill-down enabled; right-click → drill through
   to Page 4 (Segment Detail).
7. Confounder panel (bottom strip): `[Cohort Temp Delta]`, `[Cohort Driver Day % Delta]`,
   and a clustered bar of `[Cohort Delta]` vs `[Cohort Delta | Weather Adjusted]`
   by `Cohort Split`, with `[Cohort Unexplained Share]` as the label. This is the visual
   that separates "the weather changed" from "something else changed".
8. Scatter (quadrant view): X `[Cohort Delta %]`, Y `[Cohort Contribution %]`,
   size `[Post Volume]`, details `complaint_type`, legend `borough`. Add constant lines
   at x = 0 and y = 0. Top-right quadrant = big movers that also matter in absolute terms.

**Bookmarks**
- `Raw delta` / `Weather-adjusted delta` — swaps the measure in visuals 2, 3 and 6.
- `By borough` / `By category` — presets of the `Cohort Split` field parameter.
- `Significant only` — applies the visual filter `[Cohort Significant] = 1`.

**Changing the windows**: edit the `windows` CTE in `sql/staging/stg_calendar.sql`
(mirrors `config/config.yaml` → `analysis.anomaly_window`), then `make sql` and refresh.
Everything on this page derives from `in_event_window` / `in_baseline_window`, so no
DAX edits are needed.

### Page 6 — One-click export

Add a small "Export" group in the bottom-right of Page 6 so the analyst can ship exactly
what is on screen.

1. Drop a **Python script visual** onto the page with the fields `borough`,
   `complaint_type` and `cohort_period` added (Power BI passes the *filtered* values in
   the `dataset` frame). Script:

   ```python
   import json, pathlib
   state = {
       "boroughs": sorted(dataset["borough"].dropna().unique().tolist()),
       "complaint_types": sorted(dataset["complaint_type"].dropna().unique().tolist()),
       "source": "Power BI Page 6",
   }
   pathlib.Path(r"C:\nyc311\powerbi\filter_state.json").write_text(json.dumps(state))
   ```

   Set the visual's height to ~1 px behind the button — it only needs to run, not render.

2. Add a **Button** ("Export CSV / PDF / Excel") with a *Page navigation → none* action and
   a bookmark that shows an instruction card, or wire it to a Power Automate flow /
   local scheduled task that runs:

   ```bash
   python -m src.reporting.cohort_export --format all --filters-json powerbi/filter_state.json
   ```

3. Add a second button, "E-mail to the team", running the same command with
   `--email --email-to <list>`.

The exported files carry the same scope suffix as the slicer selection
(`cohort_comparison_brooklyn-bronx.xlsx`) and contribution percentages are re-based to
the selection, so the PDF matches the numbers on the page rather than the citywide totals.

Cards worth placing next to the buttons: `[Cohort Delta]`, `[Cohort Contribution %]` and a
text box reading *"Exports respect the borough and category slicers on this page."*


### Page 7 — Driver drillthrough (drillthrough target)

**Purpose**: click any significant driver flag anywhere in the report and land on the
exact borough / complaint-category / day breakdown behind it, with example complaint
types ranked by the excess volume they carry.

**Setup**
- Page name `Driver drillthrough`, *Page information → Allow use as drillthrough*, and
  *Drill through → Add drill-through fields*:
  `DimDriver[driver_flag]`, `DriverExamples[borough]`, `DriverExamples[complaint_type]`.
  All three are **optional** (`Drill through → keep all filters = On`), so a click that
  carries only a driver flag still works, and a click from a borough × category cell
  carries all three.
- Hide the page from the tab strip (right-click → *Hide page*).
- Because `keep all filters` is on, the source page's date slicer travels with the click,
  so the drillthrough always reflects the window the analyst was looking at.

**Where the clicks come from**
| Source page | Visual | Right-click → Drill through |
| --- | --- | --- |
| Page 1 Timeline | Driver ribbon / overlay markers | driver flag (+ borough if sliced) |
| Page 3 Weather effect | Driver-flag matrix (rows = driver, values = `[Cohort Delta]`) | driver flag + borough |
| Page 4 Segment detail | Borough × category matrix | driver flag + borough + category |
| Page 6 Cohort comparison | Butterfly bars / quadrant scatter | driver flag + borough + category |

Make the entry points obvious: on the driver matrix apply conditional formatting driven by
`[Driver Flag Significant]` (background `#7A2E2E` when 1) and add the
`[Driver Flag Marker]` measure as a second column so significant rows read `▲ significant`.

**Layout**
1. **Header band** — card `[Drillthrough Title]` (driver • boroughs • categories) with
   `[Drillthrough Window Label]` underneath, plus the standard back button
   (*Insert → Buttons → Back*, top-left).
2. **KPI row** — `[Driver Days]`, `[Driver Anomaly Days]`, `[Driver Excess Volume]`,
   `[Driver Excess %]`, `[Driver Avg Z]`, `[Driver Share of Excess %]`.
3. **Daily breakdown** (line + column combo) — X `DriverExamples[date_day]`,
   columns `Sum(volume)`, line `Sum(rolling_mean_28d)`, markers where
   `is_anomaly_day = TRUE`. This is the "exact time breakdown" for the clicked flag.
4. **Borough split** (bar) — `borough` × `[Driver Excess Volume]`, sorted descending;
   cross-filters visuals 3 and 5.
5. **Example complaint types** (table) — `complaint_type`, `[Driver Days]`,
   `[Driver Excess Volume]`, `[Driver Excess %]`, `[Driver Share of Excess %]`,
   `[Driver Example Rank]`; visual-level filter `example_rank <= 10`, sorted by rank.
6. **Example days** (table) — `date_day`, `borough`, `complaint_type`, `volume`,
   `rolling_mean_28d`, `rolling_z`, `temp_max_f` / `precip_in` / `snowfall_in`,
   `holiday_name`; top 25 by `excess_vs_baseline`. Set *Show data point as table* so the
   analyst can copy rows straight into the case study.
7. **Card** `[Driver Top Examples]` — the five headline categories as text, formatted for
   pasting into the narrative.

**Page 8 — Cohort drillthrough** (same pattern, drill-through fields
`CohortCompare[borough]` + `CohortCompare[complaint_type]`) shows the cohort's baseline vs
post-change daily lines, `[Cohort Delta]`, `[Cohort Effect Size d]`, `[Cohort q-value]`,
its driver-day mix, and the same *example days* table filtered to that cohort — so a click
on any cohort in Page 6 explains itself without leaving the report.

**Model wiring**: `DimDriver[driver_flag] → DriverExamples[driver_flag]` (1:*, single),
`DimDate[date_day] → DriverExamples[date_day]` (1:*, single),
`DimBorough[borough] → DriverExamples[borough]`,
`DimComplaint[complaint_type] → DriverExamples[complaint_type]`. Keep all four single
direction so drillthrough context flows one way and the matrix stays fast.
