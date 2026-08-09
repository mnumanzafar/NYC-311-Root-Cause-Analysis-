"""One-click CSV + PDF export of the cohort comparison results.

Bundles, for every borough x complaint_type cohort:
  deltas        - abs/pct change, length-normalised baseline, contribution %
  effect sizes  - Cohen's d (pooled sd)
  significance  - Welch t-test statistic, p-value, BH q-value, significant flag
  driver flags  - weather deltas, driver-day share, calendar mix warning

Usage:
    python -m src.reporting.cohort_export --out reports/exports
    python -m src.reporting.cohort_export --out reports/exports --format csv
    python -m src.reporting.cohort_export --from-parquet data/processed  # offline
"""
from __future__ import annotations

import argparse
import logging
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

COMPARISON_TABLE = "marts.mart_cohort_comparison"
DAILY_TABLE = "marts.mart_cohort_daily"

# Column order of the shareable extract: identity -> deltas -> effect -> stats -> drivers.
EXPORT_COLUMNS: list[str] = [
    "borough",
    "complaint_type",
    "baseline_days",
    "post_days",
    "baseline_volume",
    "post_volume",
    "baseline_daily_avg",
    "post_daily_avg",
    "baseline_volume_scaled",
    "abs_change",
    "pct_change",
    "contribution_pct",
    "effect_size_d",
    "t_statistic",
    "p_value",
    "q_value",
    "is_significant",
    "temp_max_f_delta",
    "precip_in_delta",
    "baseline_driver_day_pct",
    "post_driver_day_pct",
    "driver_day_pct_delta",
    "calendar_mix_warning",
]

# Compact subset that actually fits on a landscape PDF page.
PDF_COLUMNS: list[str] = [
    "borough",
    "complaint_type",
    "baseline_daily_avg",
    "post_daily_avg",
    "abs_change",
    "pct_change",
    "contribution_pct",
    "effect_size_d",
    "p_value",
    "q_value",
    "driver_day_pct_delta",
    "flags",
]

PDF_HEADERS = {
    "borough": "Borough",
    "complaint_type": "Complaint type",
    "baseline_daily_avg": "Base/day",
    "post_daily_avg": "Post/day",
    "abs_change": "Chg vol",
    "pct_change": "Chg %",
    "contribution_pct": "Contrib %",
    "effect_size_d": "Cohen's d",
    "p_value": "p",
    "q_value": "q (BH)",
    "driver_day_pct_delta": "Chg drv-day pp",
    "flags": "Flags",
}


# --------------------------------------------------------------------------- stats
def benjamini_hochberg_q(p_values) -> np.ndarray:
    """BH-adjusted p-values (q-values), monotone and clipped to 1.0."""
    p = np.asarray(p_values, dtype=float)
    out = np.full(p.shape, np.nan)
    valid = ~np.isnan(p)
    m = int(valid.sum())
    if m == 0:
        return out
    idx = np.where(valid)[0]
    order = idx[np.argsort(p[idx])]
    ranked = p[order] * m / np.arange(1, m + 1)
    out[order] = np.minimum.accumulate(ranked[::-1])[::-1].clip(0, 1)
    return out


def cohort_significance(daily: pd.DataFrame, value_col: str = "volume",
                        period_col: str = "cohort_period") -> pd.DataFrame:
    """Per-cohort Welch t-test of baseline vs post-change daily volumes."""
    rows = []
    for (borough, complaint_type), grp in daily.groupby(["borough", "complaint_type"],
                                                        dropna=False):
        base = grp.loc[grp[period_col] == "Baseline", value_col].astype(float).to_numpy()
        post = grp.loc[grp[period_col] == "Post-change", value_col].astype(float).to_numpy()
        if len(base) < 2 or len(post) < 2 or (np.std(base) == 0 and np.std(post) == 0):
            t_stat, p_val = np.nan, np.nan
        else:
            t_stat, p_val = stats.ttest_ind(post, base, equal_var=False)
        rows.append({"borough": borough, "complaint_type": complaint_type,
                     "t_statistic": float(t_stat) if t_stat == t_stat else np.nan,
                     "p_value": float(p_val) if p_val == p_val else np.nan})
    out = pd.DataFrame(rows, columns=["borough", "complaint_type", "t_statistic", "p_value"])
    out["q_value"] = benjamini_hochberg_q(out["p_value"]) if len(out) else []
    return out


# --------------------------------------------------------------------------- frame
def build_export_frame(comparison: pd.DataFrame, daily: pd.DataFrame | None = None,
                       alpha: float = 0.01) -> pd.DataFrame:
    """Join comparison mart + significance tests into the shareable extract."""
    df = comparison.copy()
    if daily is not None and len(daily):
        df = df.merge(cohort_significance(daily), on=["borough", "complaint_type"],
                      how="left")
    for col in ("t_statistic", "p_value", "q_value"):
        if col not in df:
            df[col] = np.nan
    df["is_significant"] = df["q_value"] < alpha
    df["driver_day_pct_delta"] = (df.get("post_driver_day_pct", np.nan)
                                  - df.get("baseline_driver_day_pct", np.nan))
    if "calendar_mix_warning" not in df:
        df["calendar_mix_warning"] = False
    df["calendar_mix_warning"] = df["calendar_mix_warning"].fillna(False).astype(bool)
    for col in EXPORT_COLUMNS:
        if col not in df:
            df[col] = np.nan
    df = df[EXPORT_COLUMNS]
    sort_key = df["contribution_pct"].abs().fillna(-1)
    return df.assign(_k=sort_key).sort_values("_k", ascending=False).drop(columns="_k") \
             .reset_index(drop=True)


def _flags(row: pd.Series) -> str:
    marks = []
    if bool(row.get("is_significant")):
        marks.append("SIG")
    if bool(row.get("calendar_mix_warning")):
        marks.append("MIX")
    d = row.get("driver_day_pct_delta")
    if pd.notna(d) and abs(float(d)) >= 10:
        marks.append("DRV")
    return " ".join(marks) or "-"


def summarise(df: pd.DataFrame, alpha: float = 0.01) -> dict:
    total = float(df["abs_change"].sum(skipna=True))
    sig = df[df["is_significant"].fillna(False)]
    top = df.head(3)
    return {
        "cohorts": int(len(df)),
        "total_abs_change": total,
        "significant_cohorts": int(len(sig)),
        "alpha": alpha,
        "mix_warnings": int(df["calendar_mix_warning"].sum()),
        "top_contributors": [
            f"{r.borough} / {r.complaint_type}: {r.abs_change:+,.0f} "
            f"({r.contribution_pct:+.1f}% of change)"
            for r in top.itertuples() if pd.notna(r.abs_change)
        ],
    }


# --------------------------------------------------------------------------- output
def _fmt(value, col: str) -> str:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return "-"
    if col in ("p_value", "q_value"):
        return "<0.001" if float(value) < 0.001 else f"{float(value):.3f}"
    if col in ("effect_size_d",):
        return f"{float(value):+.2f}"
    if col in ("driver_day_pct_delta",):
        return f"{float(value):+.1f} pp"
    if col in ("pct_change", "contribution_pct"):
        return f"{float(value):+.1f}%"
    if col in ("abs_change",):
        return f"{float(value):+,.0f}"
    if isinstance(value, (int, float, np.floating, np.integer)):
        return f"{float(value):,.1f}"
    return str(value)


def export_csv(df: pd.DataFrame, path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, float_format="%.6g")
    return path


def export_pdf(df: pd.DataFrame, path: str | Path, title: str = "Cohort Comparison Results",
               subtitle: str = "", alpha: float = 0.01, max_rows: int = 40,
               narrative: str = "") -> Path:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (Paragraph, SimpleDocTemplate, Spacer, Table,
                                    TableStyle)

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    styles = getSampleStyleSheet()
    small = styles["BodyText"].clone("small")
    small.fontSize = 7.5
    small.leading = 9

    view = df.head(max_rows).copy()
    view["flags"] = view.apply(_flags, axis=1)
    header = [PDF_HEADERS[c] for c in PDF_COLUMNS]
    body = [[Paragraph(_fmt(row[c], c), small) for c in PDF_COLUMNS]
            for _, row in view.iterrows()]

    stats_ = summarise(df, alpha)
    doc = SimpleDocTemplate(str(path), pagesize=landscape(A4),
                            leftMargin=12 * mm, rightMargin=12 * mm,
                            topMargin=12 * mm, bottomMargin=12 * mm,
                            title=title)
    flow = [Paragraph(title, styles["Title"])]
    if subtitle:
        flow.append(Paragraph(subtitle, styles["Normal"]))
    flow.append(Paragraph(
        f"Generated {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC} &middot; "
        f"{stats_['cohorts']} cohorts &middot; net change {stats_['total_abs_change']:+,.0f} "
        f"requests &middot; {stats_['significant_cohorts']} significant at "
        f"BH q &lt; {alpha} &middot; {stats_['mix_warnings']} calendar-mix warnings",
        styles["Normal"]))
    flow.append(Spacer(1, 6))
    if stats_["top_contributors"]:
        flow.append(Paragraph("<b>Top contributors to the change</b>", styles["Normal"]))
        for line in stats_["top_contributors"]:
            flow.append(Paragraph("&bull; " + line, small))
        flow.append(Spacer(1, 6))

    widths = [26 * mm, 52 * mm, 18 * mm, 18 * mm, 20 * mm, 18 * mm, 20 * mm,
              20 * mm, 16 * mm, 16 * mm, 26 * mm, 18 * mm]
    table = Table([header] + body, colWidths=widths, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F3864")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, 0), 7.5),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#B4C6E7")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
         [colors.white, colors.HexColor("#F2F5FB")]),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
    ]))
    flow.append(table)
    if len(df) > max_rows:
        flow.append(Spacer(1, 4))
        flow.append(Paragraph(
            f"Showing top {max_rows} of {len(df)} cohorts by absolute contribution; "
            "the CSV export contains every row and column.", small))
    flow.append(Spacer(1, 6))
    flow.append(Paragraph(
        "Flags: SIG = significant after Benjamini-Hochberg FDR control; "
        "MIX = baseline/post calendar mix differs by more than 10 pp; "
        "DRV = weather/holiday driver-day share shifted by 10 pp or more. "
        "Deltas use a length-normalised baseline, so windows of different "
        "lengths remain comparable.", small))
    if narrative:
        from reportlab.platypus import PageBreak

        from .narrative import narrative_paragraphs
        flow.append(PageBreak())
        flow.append(Paragraph("Auto-written case study", styles["Title"]))
        flow.append(Spacer(1, 4))
        for line in narrative_paragraphs(narrative):
            if line.startswith("<b>"):
                flow.append(Spacer(1, 5))
            flow.append(Paragraph(line, small))
    doc.build(flow)
    return path


# --------------------------------------------------------------------------- runner
def _load_from_db() -> tuple[pd.DataFrame, pd.DataFrame]:
    from ..utils.db import read_sql
    return (read_sql(f"SELECT * FROM {COMPARISON_TABLE}"),
            read_sql(f"SELECT * FROM {DAILY_TABLE}"))


def _load_from_parquet(folder: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    return (pd.read_parquet(folder / "mart_cohort_comparison.parquet"),
            pd.read_parquet(folder / "mart_cohort_daily.parquet"))


def _load_enriched_daily(from_parquet: Path | None) -> pd.DataFrame:
    """Full enriched daily series, used to build rolling recent-week cohorts."""
    if from_parquet:
        for name in ("mart_daily_volume_enriched_by_type.parquet",
                     "mart_cohort_daily.parquet"):
            candidate = Path(from_parquet) / name
            if candidate.exists():
                return pd.read_parquet(candidate)
        raise FileNotFoundError(
            f"no enriched daily parquet found in {from_parquet}")
    from ..utils.db import read_sql
    return read_sql("SELECT * FROM marts.mart_daily_volume_enriched_by_type")


def run(out_dir: str | Path = "reports/exports", fmt: str = "both",
        alpha: float = 0.01, from_parquet: str | Path | None = None,
        stem: str | None = None, *,
        filters: "CohortFilter | None" = None,
        recent_week: bool = False, week_days: int = 7, baseline_weeks: int = 4,
        lag_days: int = 1, as_of=None,
        post_start=None, post_end=None, baseline_start=None, baseline_end=None,
        narrative: bool = True,
        email: bool = False, email_to=None, email_cc=None,
        email_dry_run: bool = False, email_subject_prefix: str = "[NYC 311]",
        window_label: str | None = None,
        notify_on_anomaly: bool = False, alert_policy=None,
        alert_state_path=None,
        audit: bool = True, audit_log: str | Path | None = None) -> dict:
    """Build the export frame and write every requested artefact.

    ``fmt`` accepts csv | pdf | xlsx | both (csv+pdf) | all (csv+pdf+xlsx).
    ``filters`` narrows the run to the selected boroughs / complaint categories
    (the Power BI page writes those into a JSON file, see filters.py).
    ``recent_week`` re-tags cohorts to the latest complete week instead of the
    fixed windows baked into the SQL marts; ``post_start``/``post_end`` (with an
    optional explicit ``baseline_start``/``baseline_end``) do the same for a
    user-specified date range. Both paths apply ``filters`` first, so a run
    always respects the Power BI borough / category slicers.
    ``notify_on_anomaly`` runs the alert policy and only e-mails when the run
    clears the thresholds (see reporting/alerting.py).
    """
    from .filters import CohortFilter, recompute_contribution

    filters = filters or CohortFilter()
    source = Path(from_parquet) if from_parquet else None
    window = None
    started_at = datetime.now(timezone.utc).isoformat()

    if post_start or post_end:
        from .recent_week import build_window_cohorts, explicit_windows
        if not (post_start and post_end):
            raise ValueError("a custom range needs both --post-start and --post-end")
        enriched = _load_enriched_daily(source)
        enriched = filters.apply(enriched)
        windows = explicit_windows(post_start, post_end, baseline_start, baseline_end,
                                   baseline_weeks=None if baseline_start else baseline_weeks)
        comparison, daily, window = build_window_cohorts(enriched, windows)
        window_label = window_label or window.label()
    elif recent_week:
        from .recent_week import build_recent_week_cohorts
        enriched = _load_enriched_daily(source)
        enriched = filters.apply(enriched)
        comparison, daily, window = build_recent_week_cohorts(
            enriched, week_days=week_days, baseline_weeks=baseline_weeks,
            lag_days=lag_days, as_of=as_of)
        window_label = window_label or window.label()
    else:
        comparison, daily = (_load_from_parquet(source) if source else _load_from_db())
        comparison = filters.apply(comparison)
        daily = filters.apply(daily)

    df = build_export_frame(comparison, daily, alpha=alpha)
    if not filters.is_empty:
        df = recompute_contribution(df)

    scope = filters.label()
    window_label = window_label or "baseline vs post-change (config/config.yaml)"
    text = ""
    if narrative:
        from .narrative import build_narrative
        text = build_narrative(df, daily, scope=scope, window_label=window_label,
                               alpha=alpha)

    out_dir = Path(out_dir)
    stem = stem or f"cohort_comparison_{datetime.now(timezone.utc):%Y%m%d}"
    if not filters.is_empty:
        stem = f"{stem}_{filters.slug()}"
    want = {"csv": fmt in ("csv", "both", "all"),
            "pdf": fmt in ("pdf", "both", "all"),
            "xlsx": fmt in ("xlsx", "all")}

    written: dict[str, Path] = {}
    if want["csv"]:
        written["csv"] = export_csv(df, out_dir / f"{stem}.csv")
    if want["pdf"]:
        written["pdf"] = export_pdf(
            df, out_dir / f"{stem}.pdf",
            subtitle=f"NYC 311 root-cause investigation &middot; {scope} &middot; {window_label}",
            alpha=alpha, narrative=text)
    if want["xlsx"]:
        from .excel_export import export_excel
        written["xlsx"] = export_excel(
            df, out_dir / f"{stem}.xlsx", narrative=text,
            meta={"scope": scope, "window_label": window_label, "alpha": alpha})
    if narrative:
        md_path = out_dir / f"{stem}_narrative.md"
        md_path.parent.mkdir(parents=True, exist_ok=True)
        md_path.write_text(text)
        written["narrative"] = md_path

    outcome: dict = {"files": written, "cohorts": int(len(df)),
                     "scope": scope, "window": window.to_dict() if window else None,
                     "narrative": text, "email": None, "alert": None,
                     "audit": None}

    if audit:
        from . import audit as audit_report
        try:
            parameters = {
                "alpha": alpha, "format": fmt, "recent_week": recent_week,
                "week_days": week_days, "baseline_weeks": baseline_weeks,
                "lag_days": lag_days, "as_of": as_of,
                "window": outcome["window"] or {"label": window_label},
                "window_label": window_label,
                "filters": {"boroughs": list(filters.boroughs),
                            "complaint_types": list(filters.complaint_types),
                            "source": getattr(filters, "source", None)},
                "source": str(source) if source else "postgres",
                "narrative": narrative,
                "alert_policy": alert_policy,
                "stem": stem,
            }
            datasets = [
                audit_report.describe_dataset("cohort_comparison", comparison),
                audit_report.describe_dataset("cohort_daily", daily),
                audit_report.describe_dataset("export_frame", df),
            ]
            record = audit_report.build_record(
                parameters=parameters, datasets=datasets,
                outputs={k: v for k, v in written.items()},
                started_at=started_at)
            paths = audit_report.write(
                record, out_dir, stem,
                log_path=audit_log or audit_report.AUDIT_LOG)
            written["audit"] = paths["json"]
            written["audit_markdown"] = paths["markdown"]
            outcome["audit"] = {"run_id": record["run_id"],
                                "inputs_fingerprint": record["inputs_fingerprint"],
                                "replay_command": record["replay_command"],
                                "json": str(paths["json"]),
                                "markdown": str(paths["markdown"])}
        except Exception:                                # noqa: BLE001 - never fail an export
            logging.getLogger(__name__).warning("audit record failed", exc_info=True)

    if notify_on_anomaly:
        from . import alerting
        policy = (alert_policy if isinstance(alert_policy, alerting.AlertPolicy)
                  else alerting.AlertPolicy.from_config(alert_policy))
        state_path = alert_state_path or alerting.DEFAULT_STATE_FILE
        decision = alerting.evaluate(df, policy=policy,
                                     previous=alerting.load_state(state_path),
                                     window=outcome["window"], scope=scope)
        alerting.save_state(decision.fingerprint, state_path)
        outcome["alert"] = decision.to_dict()
        if email and not decision.should_notify:
            email = False
            outcome["email"] = {"sent": False, "skipped": "no anomaly",
                                "headline": decision.headline}

    if email:
        from .emailer import send_exports
        attachments = [p for k, p in written.items()
                       if k not in ("narrative", "audit", "audit_markdown")]
        subject = (f"{email_subject_prefix} Cohort comparison — {scope} — "
                   f"{datetime.now(timezone.utc):%Y-%m-%d}")
        body = summary_text(df, scope, window_label, alpha)
        if outcome.get("alert"):
            body = ("Alert triggers: "
                    + ", ".join(outcome["alert"]["triggers"]) + "\n"
                    + outcome["alert"]["headline"] + "\n\n"
                    + "\n".join(f"- {r}" for r in outcome["alert"]["reasons"])
                    + "\n\n" + body)
        outcome["email"] = send_exports(
            attachments, email_to, subject=subject,
            body_text=body + "\n\n" + text, body_markdown=text,
            cc=email_cc, dry_run=email_dry_run)
        if isinstance(outcome["email"], dict):
            outcome["email"].pop("message", None)
    return outcome


def summary_text(df: pd.DataFrame, scope: str, window_label: str,
                 alpha: float = 0.01) -> str:
    stats_ = summarise(df, alpha)
    lines = [f"Scope: {scope}", f"Windows: {window_label}",
             f"Cohorts: {stats_['cohorts']:,}",
             f"Net change: {stats_['total_abs_change']:+,.0f} requests",
             f"Significant (BH q < {alpha}): {stats_['significant_cohorts']}",
             f"Calendar-mix warnings: {stats_['mix_warnings']}"]
    if stats_["top_contributors"]:
        lines.append("Top contributors:")
        lines += [f"  - {t}" for t in stats_["top_contributors"]]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="reports/exports")
    parser.add_argument("--format", dest="fmt",
                        choices=["csv", "pdf", "xlsx", "both", "all"], default="both")
    parser.add_argument("--alpha", type=float, default=0.01)
    parser.add_argument("--from-parquet", default=None,
                        help="read the marts from parquet instead of Postgres")
    parser.add_argument("--stem", default=None, help="output filename stem")
    parser.add_argument("--borough", action="append", default=None,
                        help="repeatable; matches the Power BI borough slicer")
    parser.add_argument("--complaint-type", action="append", default=None,
                        help="repeatable; matches the Power BI category slicer")
    parser.add_argument("--filters-json", default=None,
                        help="filter file written by the Power BI export button")
    parser.add_argument("--recent-week", action="store_true",
                        help="compare the latest complete week to prior weeks")
    parser.add_argument("--post-start", default=None,
                        help="custom range: first day of the post-change window")
    parser.add_argument("--post-end", default=None,
                        help="custom range: last day of the post-change window")
    parser.add_argument("--baseline-start", default=None,
                        help="optional explicit baseline start (default: the block "
                             "immediately before the post window)")
    parser.add_argument("--baseline-end", default=None)
    parser.add_argument("--week-days", type=int, default=7)
    parser.add_argument("--baseline-weeks", type=int, default=4)
    parser.add_argument("--lag-days", type=int, default=1)
    parser.add_argument("--no-narrative", action="store_true")
    parser.add_argument("--email", action="store_true")
    parser.add_argument("--email-to", default=None)
    parser.add_argument("--email-cc", default=None)
    parser.add_argument("--email-dry-run", action="store_true")
    parser.add_argument("--notify-on-anomaly", action="store_true",
                        help="only e-mail when the alert policy fires")
    parser.add_argument("--alert-alpha", type=float, default=None)
    parser.add_argument("--alert-state", default=None)
    args = parser.parse_args()

    from .filters import CohortFilter
    filters = (CohortFilter.from_json(args.filters_json) if args.filters_json
               else CohortFilter(boroughs=args.borough or [],
                                 complaint_types=args.complaint_type or [],
                                 source="CLI"))
    outcome = run(args.out, args.fmt, args.alpha, args.from_parquet, args.stem,
                  filters=filters, recent_week=args.recent_week,
                  week_days=args.week_days, baseline_weeks=args.baseline_weeks,
                  lag_days=args.lag_days, narrative=not args.no_narrative,
                  post_start=args.post_start, post_end=args.post_end,
                  baseline_start=args.baseline_start, baseline_end=args.baseline_end,
                  email=args.email or args.email_dry_run, email_to=args.email_to,
                  email_cc=args.email_cc, email_dry_run=args.email_dry_run,
                  notify_on_anomaly=args.notify_on_anomaly,
                  alert_policy=({"alpha": args.alert_alpha}
                                if args.alert_alpha is not None else None),
                  alert_state_path=args.alert_state)
    print(f"scope: {outcome['scope']} ({outcome['cohorts']} cohorts)")
    if outcome.get("window"):
        print(f"window: {outcome['window'].get('label', outcome['window'])}")
    if outcome.get("alert"):
        print(f"alert: {'FIRED' if outcome['alert']['should_notify'] else 'quiet'}"
              f" [{', '.join(outcome['alert']['triggers']) or 'none'}] "
              f"{outcome['alert']['headline']}")
    for kind, path in outcome["files"].items():
        print(f"{kind}: {path}")
    mail = outcome.get("email")
    if mail and mail.get("skipped"):
        print(f"email: skipped ({mail['skipped']})")
    elif mail:
        state = "dry-run" if mail.get("dry_run") else "sent"
        print(f"email ({state}): {', '.join(mail.get('to', []))}")


if __name__ == "__main__":
    main()
