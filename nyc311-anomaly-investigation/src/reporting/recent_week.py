"""Rolling "most recent week" cohort windows, computed from the data itself.

The SQL cohort marts use the fixed event/baseline windows in ``config.yaml``,
which is right for the original investigation but wrong for a nightly job: each
night we want *the latest complete week* compared against the weeks before it.

This module re-tags the enriched daily rows in pandas and re-aggregates them
into exactly the schema ``marts.mart_cohort_comparison`` produces, so every
downstream consumer (export frame, PDF, Excel, narrative) is unchanged.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

import numpy as np
import pandas as pd

DRIVER_COLUMNS = ("is_hot_day", "is_freezing_day", "is_heavy_rain_day",
                  "is_snow_day", "is_high_wind_day", "is_holiday")


@dataclass
class CohortWindows:
    post_start: pd.Timestamp
    post_end: pd.Timestamp
    baseline_start: pd.Timestamp
    baseline_end: pd.Timestamp

    def label(self) -> str:
        return (f"post {self.post_start:%Y-%m-%d}–{self.post_end:%Y-%m-%d} vs "
                f"baseline {self.baseline_start:%Y-%m-%d}–{self.baseline_end:%Y-%m-%d}")

    @property
    def post_days(self) -> int:
        return (self.post_end - self.post_start).days + 1

    @property
    def baseline_days(self) -> int:
        return (self.baseline_end - self.baseline_start).days + 1

    def to_dict(self) -> dict:
        out = {k: f"{v:%Y-%m-%d}" for k, v in {
            "post_start": self.post_start, "post_end": self.post_end,
            "baseline_start": self.baseline_start, "baseline_end": self.baseline_end}.items()}
        out.update({"post_days": self.post_days, "baseline_days": self.baseline_days,
                    "label": self.label()})
        return out


def recent_week_windows(daily: pd.DataFrame, *, week_days: int = 7,
                        baseline_weeks: int = 4, lag_days: int = 1,
                        as_of=None) -> CohortWindows:
    """Latest ``week_days`` complete days, versus the ``baseline_weeks`` before them.

    ``lag_days`` drops the most recent day(s), because 311 rows for the current
    day keep arriving and would understate the newest week.
    """
    last = (pd.Timestamp(as_of) if as_of is not None
            else pd.to_datetime(daily["date_day"]).max())
    post_end = pd.Timestamp(last).normalize() - timedelta(days=lag_days)
    post_start = post_end - timedelta(days=week_days - 1)
    baseline_end = post_start - timedelta(days=1)
    baseline_start = baseline_end - timedelta(days=week_days * baseline_weeks - 1)
    return CohortWindows(post_start, post_end, baseline_start, baseline_end)


def explicit_windows(post_start, post_end, baseline_start=None, baseline_end=None,
                     *, baseline_weeks: int | None = None) -> CohortWindows:
    """User-specified post-change window, with an optional explicit baseline.

    When the baseline is omitted it is the block of days immediately before the
    post-change window: ``baseline_weeks`` x (length of the post window), or the
    same length as the post window when ``baseline_weeks`` is None.
    """
    p_start = pd.Timestamp(post_start).normalize()
    p_end = pd.Timestamp(post_end).normalize()
    if p_end < p_start:
        p_start, p_end = p_end, p_start
    if baseline_start is None and baseline_end is None:
        length = (p_end - p_start).days + 1
        b_end = p_start - timedelta(days=1)
        b_start = b_end - timedelta(days=length * (baseline_weeks or 1) - 1)
    else:
        if baseline_end is None:
            raise ValueError("baseline-start given without baseline-end")
        b_end = pd.Timestamp(baseline_end).normalize()
        b_start = (pd.Timestamp(baseline_start).normalize()
                   if baseline_start is not None else b_end)
        if b_end < b_start:
            b_start, b_end = b_end, b_start
        if b_end >= p_start:
            raise ValueError("baseline window overlaps the post-change window: "
                             f"baseline ends {b_end:%Y-%m-%d}, post starts {p_start:%Y-%m-%d}")
    return CohortWindows(p_start, p_end, b_start, b_end)


def tag_cohorts(daily: pd.DataFrame, windows: CohortWindows) -> pd.DataFrame:
    """Return only the in-window rows, with ``cohort_period`` / ``day_in_period``."""
    df = daily.copy()
    days = pd.to_datetime(df["date_day"])
    period = np.where((days >= windows.post_start) & (days <= windows.post_end),
                      "Post-change",
                      np.where((days >= windows.baseline_start)
                               & (days <= windows.baseline_end), "Baseline", None))
    df["cohort_period"] = period
    df = df.loc[df["cohort_period"].notna()].copy()
    if "primary_driver" not in df:
        df["primary_driver"] = _primary_driver(df)
    df["day_in_period"] = (df.sort_values("date_day")
                             .groupby(["borough", "complaint_type", "cohort_period"])
                             .cumcount() + 1)
    return df.reset_index(drop=True)


def _primary_driver(df: pd.DataFrame) -> pd.Series:
    labels = [("is_snow_day", "Snow"), ("is_heavy_rain_day", "Heavy rain"),
              ("is_high_wind_day", "High wind"), ("is_hot_day", "Heat"),
              ("is_freezing_day", "Freeze"), ("is_holiday", "Holiday")]
    out = pd.Series("Normal", index=df.index)
    for col, name in reversed(labels):
        if col in df:
            out = out.mask(df[col].fillna(False).astype(bool), name)
    return out


def aggregate_comparison(tagged: pd.DataFrame) -> pd.DataFrame:
    """Re-create marts.mart_cohort_comparison from tagged daily rows."""
    df = tagged.copy()
    if "is_non_business_day" not in df:
        df["is_non_business_day"] = df.get("is_weekend", False)
    df["_driver_day"] = df.get("primary_driver", "Normal").ne("Normal")
    rows = []
    for (borough, complaint_type), grp in df.groupby(["borough", "complaint_type"],
                                                     dropna=False):
        base = grp[grp["cohort_period"] == "Baseline"]
        post = grp[grp["cohort_period"] == "Post-change"]
        b_avg = base["volume"].mean() if len(base) else np.nan
        p_avg = post["volume"].mean() if len(post) else np.nan
        b_sig = base["volume"].std(ddof=1) if len(base) > 1 else np.nan
        p_sig = post["volume"].std(ddof=1) if len(post) > 1 else np.nan
        scaled = (0 if pd.isna(b_avg) else b_avg) * len(post)
        pooled = np.sqrt(((0 if pd.isna(b_sig) else b_sig) ** 2
                          + (0 if pd.isna(p_sig) else p_sig) ** 2) / 2.0)
        b_nb, p_nb = int(base["is_non_business_day"].sum()), int(post["is_non_business_day"].sum())
        rows.append({
            "borough": borough, "complaint_type": complaint_type,
            "baseline_days": len(base), "post_days": len(post),
            "baseline_volume": float(base["volume"].sum()),
            "post_volume": float(post["volume"].sum()),
            "baseline_daily_avg": b_avg, "post_daily_avg": p_avg,
            "baseline_sigma": b_sig, "post_sigma": p_sig,
            "baseline_volume_scaled": scaled,
            "abs_change": float(post["volume"].sum()) - scaled,
            "pct_change": (100.0 * (p_avg - b_avg) / b_avg
                           if b_avg not in (0, np.nan) and not pd.isna(b_avg)
                           and not pd.isna(p_avg) else np.nan),
            "effect_size_d": ((p_avg - b_avg) / pooled
                              if pooled and not pd.isna(p_avg) and not pd.isna(b_avg)
                              else np.nan),
            "baseline_temp_max_f": base.get("temp_max_f", pd.Series(dtype=float)).mean(),
            "post_temp_max_f": post.get("temp_max_f", pd.Series(dtype=float)).mean(),
            "baseline_precip_in": base.get("precip_in", pd.Series(dtype=float)).mean(),
            "post_precip_in": post.get("precip_in", pd.Series(dtype=float)).mean(),
            "baseline_driver_days": int(base["_driver_day"].sum()),
            "post_driver_days": int(post["_driver_day"].sum()),
            "baseline_driver_day_pct": 100.0 * base["_driver_day"].mean() if len(base) else np.nan,
            "post_driver_day_pct": 100.0 * post["_driver_day"].mean() if len(post) else np.nan,
            "baseline_non_business_days": b_nb, "post_non_business_days": p_nb,
        })
    out = pd.DataFrame(rows)
    if not len(out):
        return out
    out["temp_max_f_delta"] = out["post_temp_max_f"] - out["baseline_temp_max_f"]
    out["precip_in_delta"] = out["post_precip_in"] - out["baseline_precip_in"]
    total = out["abs_change"].sum()
    out["contribution_pct"] = 100.0 * out["abs_change"] / total if total else np.nan
    b_share = 100.0 * out["baseline_non_business_days"] / out["baseline_days"].replace(0, np.nan)
    p_share = 100.0 * out["post_non_business_days"] / out["post_days"].replace(0, np.nan)
    out["calendar_mix_warning"] = (b_share - p_share).abs().gt(10).fillna(False)
    return out


def build_window_cohorts(enriched_daily: pd.DataFrame, windows: CohortWindows
                         ) -> tuple[pd.DataFrame, pd.DataFrame, CohortWindows]:
    """Tag + aggregate an already-decided pair of windows."""
    tagged = tag_cohorts(enriched_daily, windows)
    if not len(tagged):
        raise ValueError(f"no rows fall inside {windows.label()} — check the dates "
                         "against the data range in the enriched daily mart")
    return aggregate_comparison(tagged), tagged, windows


def build_recent_week_cohorts(enriched_daily: pd.DataFrame, **kwargs
                              ) -> tuple[pd.DataFrame, pd.DataFrame, CohortWindows]:
    """Convenience wrapper: windows -> tagged daily -> comparison frame."""
    windows = recent_week_windows(enriched_daily, **kwargs)
    return build_window_cohorts(enriched_daily, windows)
