"""Cohort slicing — is the drop concentrated (real signal) or uniform (macro noise)?"""
from __future__ import annotations

import pandas as pd


def period_flag(df: pd.DataFrame, date_col: str, start: str, end: str,
                label: str = "period") -> pd.DataFrame:
    dates = pd.to_datetime(df[date_col])
    out = df.copy()
    out[label] = "baseline"
    out.loc[(dates >= pd.Timestamp(start)) & (dates <= pd.Timestamp(end)), label] = "anomaly"
    return out


def cohort_change(df: pd.DataFrame, segment: str, value_col: str = "volume",
                  period_col: str = "period") -> pd.DataFrame:
    """Per-segment before/after volumes, pct change, and share of the total change."""
    pivot = (df.pivot_table(index=segment, columns=period_col, values=value_col,
                            aggfunc="sum", fill_value=0)
               .rename_axis(columns=None).reset_index())
    for col in ("baseline", "anomaly"):
        if col not in pivot:
            pivot[col] = 0.0
    pivot["abs_change"] = pivot["anomaly"] - pivot["baseline"]
    pivot["pct_change"] = pivot.apply(
        lambda r: (r["abs_change"] / r["baseline"] * 100) if r["baseline"] else float("nan"),
        axis=1)
    total = pivot["abs_change"].sum()
    pivot["contribution_pct"] = pivot["abs_change"] / total * 100 if total else float("nan")
    return pivot.sort_values("abs_change").reset_index(drop=True)


def concentration_index(cohort: pd.DataFrame, contribution_col: str = "contribution_pct",
                        top_n: int = 3) -> float:
    """Share of total change explained by the top N segments (0-100)."""
    return float(cohort[contribution_col].abs().nlargest(top_n).sum())
