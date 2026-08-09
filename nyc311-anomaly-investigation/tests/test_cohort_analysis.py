import pandas as pd

from src.analysis.cohort_analysis import cohort_change, concentration_index, period_flag


def _frame():
    return pd.DataFrame({
        "date_day": ["2022-08-01", "2022-08-02", "2023-08-01", "2023-08-02"] * 2,
        "complaint_type": ["Noise"] * 4 + ["Sanitation"] * 4,
        "volume": [100, 100, 40, 40, 80, 80, 79, 81],
    })


def test_period_flag_labels_window():
    out = period_flag(_frame(), "date_day", "2023-07-01", "2023-09-30")
    assert set(out["period"]) == {"baseline", "anomaly"}
    assert (out.loc[out["date_day"].str.startswith("2023"), "period"] == "anomaly").all()


def test_cohort_change_isolates_the_dropping_segment():
    df = period_flag(_frame(), "date_day", "2023-07-01", "2023-09-30")
    cohort = cohort_change(df, "complaint_type")
    noise = cohort.set_index("complaint_type").loc["Noise"]
    sanitation = cohort.set_index("complaint_type").loc["Sanitation"]
    assert noise["pct_change"] == -60.0
    assert abs(sanitation["pct_change"]) < 1
    assert cohort.iloc[0]["complaint_type"] == "Noise"


def test_concentration_index_flags_concentrated_drop():
    df = period_flag(_frame(), "date_day", "2023-07-01", "2023-09-30")
    assert concentration_index(cohort_change(df, "complaint_type"), top_n=1) > 90
