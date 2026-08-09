"""Reusable chart functions so notebooks stay thin and figures stay consistent."""
from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

FIGURES = Path(__file__).resolve().parents[2] / "reports" / "figures"


def _save(fig, name: str | None):
    if name:
        FIGURES.mkdir(parents=True, exist_ok=True)
        fig.savefig(FIGURES / f"{name}.png", dpi=150, bbox_inches="tight")
    return fig


def plot_metric_with_bands(bands: pd.DataFrame, title: str, save_as: str | None = None):
    fig, ax = plt.subplots(figsize=(12, 5))
    ax.plot(bands.index, bands["value"], lw=1, label="daily volume")
    ax.plot(bands.index, bands["mean"], lw=2, label="rolling mean")
    ax.fill_between(bands.index, bands["lower"], bands["upper"], alpha=0.2,
                    label="±2σ band")
    ax.set_title(title)
    ax.legend()
    return _save(fig, save_as)


def plot_change_points(series: pd.Series, breakpoints, title: str,
                       save_as: str | None = None):
    fig, ax = plt.subplots(figsize=(12, 5))
    ax.plot(series.index, series.values, lw=1)
    for bp in breakpoints:
        ax.axvline(bp, color="crimson", ls="--", lw=1.5)
    ax.set_title(title)
    return _save(fig, save_as)


def plot_stl(decomp: pd.DataFrame, save_as: str | None = None):
    fig, axes = plt.subplots(4, 1, figsize=(12, 9), sharex=True)
    for ax, col in zip(axes, ["observed", "trend", "seasonal", "resid"]):
        ax.plot(decomp.index, decomp[col], lw=1)
        ax.set_ylabel(col)
    return _save(fig, save_as)


def plot_cohort_waterfall(cohort: pd.DataFrame, segment: str, top_n: int = 12,
                          save_as: str | None = None):
    data = cohort.reindex(cohort["abs_change"].abs().sort_values(ascending=False).index).head(top_n)
    fig, ax = plt.subplots(figsize=(10, 6))
    ax.barh(data[segment].astype(str), data["abs_change"])
    ax.axvline(0, color="black", lw=1)
    ax.set_xlabel("absolute change vs. baseline")
    ax.invert_yaxis()
    return _save(fig, save_as)
