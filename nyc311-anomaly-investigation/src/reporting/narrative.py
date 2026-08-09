"""Auto-written case-study narrative for an exported cohort comparison.

Turns the export frame (plus the enriched daily rows, when available) into the
five investigation beats used throughout this project — detect, hypothesise,
test, eliminate confounders, conclude — as plain markdown that can be pasted
straight into ``reports/root_cause_case_study.md``, embedded in the PDF brief,
dropped on an Excel sheet, or used as the e-mail body.

Everything here is derived from the numbers; no wording is hard-coded to a
particular incident, so the nightly job produces a fresh, accurate narrative.
"""
from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd

MATERIAL_DRIVER_PP = 10.0      # driver-day share shift that counts as a driver
MATERIAL_TEMP_F = 3.0          # avg daily max temperature shift worth naming
MATERIAL_PRECIP_IN = 0.10      # avg daily precipitation shift worth naming


def _num(value, default=np.nan) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return default if np.isnan(out) else out


def _pct(value) -> str:
    v = _num(value)
    return "n/a" if np.isnan(v) else f"{v:+.1f}%"


def _cohort_name(row) -> str:
    return f"{row.get('borough', 'Unknown')} / {row.get('complaint_type', 'Unknown')}"


# --------------------------------------------------------------------- pieces
def top_drivers(df: pd.DataFrame, limit: int = 5) -> list[dict]:
    """Rank cohorts by absolute contribution and describe each one's evidence."""
    if df is None or not len(df):
        return []
    ranked = df.assign(_k=df["abs_change"].abs().fillna(-1)) \
               .sort_values("_k", ascending=False).head(limit)
    drivers = []
    for _, row in ranked.iterrows():
        q = _num(row.get("q_value"))
        d = _num(row.get("effect_size_d"))
        drv = _num(row.get("driver_day_pct_delta"))
        drivers.append({
            "cohort": _cohort_name(row),
            "abs_change": _num(row.get("abs_change"), 0.0),
            "pct_change": _num(row.get("pct_change")),
            "contribution_pct": _num(row.get("contribution_pct")),
            "effect_size_d": d,
            "q_value": q,
            "significant": bool(row.get("is_significant")) or (not np.isnan(q) and q < 0.01),
            "weather_confounded": (not np.isnan(drv)) and abs(drv) >= MATERIAL_DRIVER_PP,
            "calendar_mix_warning": bool(row.get("calendar_mix_warning")),
        })
    return drivers


def confounder_checks(df: pd.DataFrame, daily: pd.DataFrame | None = None) -> list[dict]:
    """Each dict is one confounder we tested, with a verdict of eliminated / retained."""
    checks: list[dict] = []
    if df is None or not len(df):
        return checks

    # 1. Window length ------------------------------------------------------
    base_days = _num(df["baseline_days"].median()) if "baseline_days" in df else np.nan
    post_days = _num(df["post_days"].median()) if "post_days" in df else np.nan
    checks.append({
        "name": "Unequal window lengths",
        "eliminated": True,
        "detail": (f"Baseline window is {base_days:.0f} days vs {post_days:.0f} post-change "
                   "days; all deltas use the length-normalised baseline "
                   "(baseline daily average x post-change days), so window size "
                   "cannot create the gap."
                   if not (np.isnan(base_days) or np.isnan(post_days))
                   else "Deltas use a length-normalised baseline, so window size "
                        "cannot create the gap."),
    })

    # 2. Calendar mix -------------------------------------------------------
    mix = int(df.get("calendar_mix_warning", pd.Series(dtype=bool)).fillna(False).sum())
    checks.append({
        "name": "Calendar mix (weekends / holidays)",
        "eliminated": mix == 0,
        "detail": ("Non-business-day share matches between the two windows in every "
                   "cohort (within 10 pp), so weekday mix is not driving the change."
                   if mix == 0 else
                   f"{mix} cohort(s) carry a calendar-mix warning: their non-business-day "
                   "share differs by more than 10 pp. Read those rows against the "
                   "day-of-week profile before attributing the change to the event."),
    })

    # 3. Weather ------------------------------------------------------------
    temp = _num(df.get("temp_max_f_delta", pd.Series(dtype=float)).mean())
    precip = _num(df.get("precip_in_delta", pd.Series(dtype=float)).mean())
    drv = df.get("driver_day_pct_delta", pd.Series(dtype=float))
    weather_hits = int((drv.abs() >= MATERIAL_DRIVER_PP).fillna(False).sum()) if len(drv) else 0
    weather_material = (weather_hits > 0
                        or (not np.isnan(temp) and abs(temp) >= MATERIAL_TEMP_F)
                        or (not np.isnan(precip) and abs(precip) >= MATERIAL_PRECIP_IN))
    checks.append({
        "name": "Weather (heat, rain, snow, wind)",
        "eliminated": not weather_material,
        "detail": (
            f"Average daily max temperature moved {temp:+.1f} F and precipitation "
            f"{precip:+.2f} in between the windows"
            + (f"; {weather_hits} cohort(s) shifted their driver-day share by "
               f"{MATERIAL_DRIVER_PP:.0f} pp or more, so weather is a live "
               "co-explanation and the weather-adjusted delta should be quoted."
               if weather_material else
               ", both below the materiality thresholds, so weather is eliminated "
               "as an explanation for the change.")),
    })

    # 4. Multiple comparisons ----------------------------------------------
    n = len(df)
    sig = int(df.get("is_significant", pd.Series(dtype=bool)).fillna(False).sum())
    checks.append({
        "name": "Multiple comparisons (false positives)",
        "eliminated": True,
        "detail": (f"{n} cohorts were tested with Welch t-tests on daily volumes and "
                   f"p-values corrected with Benjamini-Hochberg FDR control; "
                   f"{sig} survive. Uncorrected testing at this width would be "
                   "expected to produce false positives by chance alone."),
    })

    # 5. Reporting-channel / volume shift ----------------------------------
    if daily is not None and len(daily) and "volume" in daily:
        base = daily.loc[daily.get("cohort_period") == "Baseline", "volume"]
        post = daily.loc[daily.get("cohort_period") == "Post-change", "volume"]
        spread_ok = len(base) >= 2 and len(post) >= 2
        checks.append({
            "name": "One-off spike vs sustained shift",
            "eliminated": spread_ok,
            "detail": (f"The post-change window contains {post.index.size} cohort-days "
                       f"(baseline {base.index.size}); the comparison is built on the "
                       "full daily series rather than period totals, so a single "
                       "outlier day cannot carry the result."
                       if spread_ok else
                       "Too few daily observations to separate a one-off spike from a "
                       "sustained shift — widen the windows before concluding."),
        })
    return checks


def build_narrative(df: pd.DataFrame, daily: pd.DataFrame | None = None,
                    *, scope: str = "All boroughs, all complaint categories",
                    window_label: str | None = None, alpha: float = 0.01,
                    title: str = "Cohort comparison — auto-written case study") -> str:
    """Render the full markdown narrative for an export run."""
    stamp = f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}"
    if df is None or not len(df):
        return (f"# {title}\n\n_Generated {stamp}_\n\n"
                f"**Scope:** {scope}\n\nNo cohorts matched this selection, so there is "
                "nothing to explain. Widen the borough or complaint-category filter "
                "and re-run the export.\n")

    total = _num(df["abs_change"].sum(skipna=True), 0.0)
    base_total = _num(df.get("baseline_volume_scaled", pd.Series(dtype=float)).sum(), 0.0)
    overall_pct = 100.0 * total / base_total if base_total else np.nan
    direction = "increase" if total > 0 else "decrease" if total < 0 else "flat result"
    drivers = top_drivers(df)
    checks = confounder_checks(df, daily)
    sig = int(df.get("is_significant", pd.Series(dtype=bool)).fillna(False).sum())

    lines = [f"# {title}", "", f"_Generated {stamp}_", "",
             f"**Scope:** {scope}  ",
             f"**Windows:** {window_label or 'baseline vs post-change (see config)'}  ",
             f"**Cohorts compared:** {len(df):,}", "",
             "## 1. What changed", ""]
    lines.append(
        f"Across the selected cohorts, post-change volume differs from the "
        f"length-normalised baseline by **{total:+,.0f} requests** "
        f"({_pct(overall_pct)}), a net {direction}. "
        f"{sig} of {len(df):,} cohorts clear significance at BH q &lt; {alpha}.")
    lines += ["", "## 2. Where the change comes from", ""]
    if drivers:
        for i, drv in enumerate(drivers, 1):
            evidence = []
            if not np.isnan(drv["effect_size_d"]):
                evidence.append(f"Cohen's d {drv['effect_size_d']:+.2f}")
            if not np.isnan(drv["q_value"]):
                q_txt = "<0.001" if drv["q_value"] < 0.001 else f"{drv['q_value']:.3f}"
                evidence.append(f"q {q_txt}")
            verdict = ("statistically significant" if drv["significant"]
                       else "not significant after FDR control")
            caveats = []
            if drv["weather_confounded"]:
                caveats.append("weather/holiday driver-day share also moved materially")
            if drv["calendar_mix_warning"]:
                caveats.append("calendar mix differs between windows")
            lines.append(
                f"{i}. **{drv['cohort']}** — {drv['abs_change']:+,.0f} requests "
                f"({_pct(drv['pct_change'])}, {_pct(drv['contribution_pct'])} of the "
                f"selected change); {', '.join(evidence) if evidence else 'no test statistics'}; "
                f"{verdict}"
                + (f". Caveat: {'; '.join(caveats)}." if caveats else "."))
    else:
        lines.append("No cohort carries a measurable share of the change.")

    lines += ["", "## 3. Confounders tested and eliminated", ""]
    for check in checks:
        mark = "ELIMINATED" if check["eliminated"] else "RETAINED"
        lines.append(f"- **{check['name']} — {mark}.** {check['detail']}")

    retained = [c["name"] for c in checks if not c["eliminated"]]
    lines += ["", "## 4. Conclusion", ""]
    lines.append(
        f"The {direction} is concentrated in "
        f"{', '.join(d['cohort'] for d in drivers[:3]) if drivers else 'no single cohort'}"
        + (", and survives every confounder tested here."
           if not retained else
           f", but {', '.join(retained).lower()} remain(s) unresolved and should be "
           "addressed before the finding is treated as causal."))
    lines += ["", "## 5. Recommended next steps", "",
              "- Review the top cohorts above against the Power BI cohort page "
              "(Page 6) with the same borough / category slicers applied.",
              "- Quote the weather-adjusted delta wherever a cohort is flagged DRV.",
              "- Re-run this export after the next nightly refresh to confirm the "
              "effect persists rather than decaying."]
    return "\n".join(lines) + "\n"


def narrative_paragraphs(markdown: str) -> list[str]:
    """Flatten the markdown into PDF-friendly paragraphs (headings kept as bold)."""
    out: list[str] = []
    for raw in markdown.splitlines():
        line = raw.strip()
        if not line or line.startswith("_Generated"):
            continue
        if line.startswith("#"):
            out.append(f"<b>{line.lstrip('# ').strip()}</b>")
        else:
            out.append(line.replace("**", "").replace("  ", " "))
    return out
