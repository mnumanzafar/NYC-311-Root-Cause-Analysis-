// Power Query (M) — paste each block into Home > Transform data > New Source > Blank Query > Advanced Editor.
// Rename the queries exactly as noted; the DAX in measures.dax assumes these names.
// Parameters: create text params PgServer, PgDatabase (Home > Manage Parameters).

// ---- Query name: Fact -----------------------------------------------------
let
    Source = PostgreSQL.Database(PgServer, PgDatabase),
    Data   = Source{[Schema="marts", Item="mart_daily_volume_enriched_by_type"]}[Data],
    Typed  = Table.TransformColumnTypes(Data, {
        {"date_day", type date},
        {"borough", type text},
        {"complaint_type", type text},
        {"volume", Int64.Type},
        {"temp_max_f", type number},
        {"precip_in", type number},
        {"snowfall_in", type number},
        {"primary_driver", type text}
    })
in
    Typed

// ---- Query name: Driver ---------------------------------------------------
let
    Source = PostgreSQL.Database(PgServer, PgDatabase),
    Data   = Source{[Schema="marts", Item="mart_daily_driver_events"]}[Data],
    Typed  = Table.TransformColumnTypes(Data, {
        {"date_day", type date}, {"borough", type text},
        {"driver_type", type text}, {"driver_group", type text}, {"driver_detail", type text}
    })
in
    Typed

// ---- Query name: Calendar (mark as date table on date_day) ----------------
let
    Source = PostgreSQL.Database(PgServer, PgDatabase),
    Data   = Source{[Schema="staging", Item="stg_calendar"]}[Data],
    Typed  = Table.TransformColumnTypes(Data, {{"date_day", type date}}),
    Sorted = Table.Sort(Typed, {{"date_day", Order.Ascending}})
in
    Sorted

// ---- Query name: DimBorough ----------------------------------------------
let
    Source   = Table.Distinct(Table.SelectColumns(Fact, {"borough"})),
    Filtered = Table.SelectRows(Source, each [borough] <> null and [borough] <> "")
in
    Filtered

// ---- Query name: DimComplaintType ----------------------------------------
let
    Source   = Table.Distinct(Table.SelectColumns(Fact, {"complaint_type"})),
    Filtered = Table.SelectRows(Source, each [complaint_type] <> null)
in
    Filtered

// ---- Query name: DimDriverType -------------------------------------------
let
    Source = Table.Distinct(Table.SelectColumns(Driver, {"driver_type", "driver_group"}))
in
    Source

// ---- Query name: CohortCompare (period-level cohort summary) --------------
let
    Source = PostgreSQL.Database(PgServer, PgDatabase),
    Data   = Source{[Schema="marts", Item="mart_cohort_comparison"]}[Data],
    Typed  = Table.TransformColumnTypes(Data, {
        {"borough", type text},
        {"complaint_type", type text},
        {"baseline_days", Int64.Type},
        {"post_days", Int64.Type},
        {"baseline_volume", Int64.Type},
        {"post_volume", Int64.Type},
        {"baseline_daily_avg", type number},
        {"post_daily_avg", type number},
        {"baseline_volume_scaled", type number},
        {"abs_change", type number},
        {"pct_change", type number},
        {"contribution_pct", type number},
        {"effect_size_d", type number},
        {"temp_max_f_delta", type number},
        {"precip_in_delta", type number},
        {"baseline_driver_day_pct", type number},
        {"post_driver_day_pct", type number},
        {"calendar_mix_warning", type logical}
    })
in
    Typed

// ---- Query name: CohortDaily (day-level, both cohort periods) -------------
let
    Source = PostgreSQL.Database(PgServer, PgDatabase),
    Data   = Source{[Schema="marts", Item="mart_cohort_daily"]}[Data],
    Typed  = Table.TransformColumnTypes(Data, {
        {"date_day", type date},
        {"borough", type text},
        {"complaint_type", type text},
        {"cohort_period", type text},
        {"day_in_period", Int64.Type},
        {"day_name", type text},
        {"volume", Int64.Type},
        {"temp_max_f", type number},
        {"precip_in", type number},
        {"primary_driver", type text}
    })
in
    Typed

// ---- Query name: DimPeriod (sortable cohort period dimension) -------------
let
    Source = Table.FromRecords({
        [cohort_period = "Baseline",    period_order = 1],
        [cohort_period = "Post-change", period_order = 2]
    }),
    Typed = Table.TransformColumnTypes(Source, {
        {"cohort_period", type text}, {"period_order", Int64.Type}
    })
in
    Typed

// ---------------------------------------------------------------------------
// DriverExamples — drillthrough target feed (marts.mart_driver_flag_examples)
// ---------------------------------------------------------------------------
let
    Source = PostgreSQL.Database(PgServer, PgDatabase),
    Data = Source{[Schema="marts", Item="mart_driver_flag_examples"]}[Data],
    Typed = Table.TransformColumnTypes(
        Data,
        {
            {"date_day", type date},
            {"driver_flag", type text},
            {"driver_group", type text},
            {"driver_label", type text},
            {"borough", type text},
            {"complaint_type", type text},
            {"volume", Int64.Type},
            {"rolling_mean_28d", type number},
            {"rolling_z", type number},
            {"excess_vs_baseline", type number},
            {"excess_pct", type number},
            {"is_anomaly_day", type logical},
            {"cohort_driver_days", Int64.Type},
            {"cohort_anomaly_days", Int64.Type},
            {"cohort_excess_total", type number},
            {"cohort_avg_z", type number},
            {"example_rank", Int64.Type},
            {"example_rank_citywide", Int64.Type}
        })
in
    Typed

// DimDriver — the driver dimension both the matrix and the drillthrough filter on.
// Relationship: DimDriver[driver_flag] 1..* DriverExamples[driver_flag]
//               DimDriver[driver_type] 1..* DriverEvents[driver_type]
let
    Source = Table.Distinct(
        Table.SelectColumns(DriverExamples, {"driver_flag", "driver_group", "driver_label"})),
    Sorted = Table.Sort(Source, {{"driver_group", Order.Ascending}, {"driver_label", Order.Ascending}})
in
    Sorted
