"""Nightly refresh + automatic export of the most recent week's cohort comparison.

One command, meant for cron / systemd / Task Scheduler:

    python -m src.orchestration.nightly_export

Steps:
    1. refresh   - re-run the SQL pipeline (staging -> intermediate -> marts)
    2. window    - compute the latest complete week vs the prior 4 weeks
    3. compare   - re-tag and aggregate cohorts on that rolling window
    4. export    - CSV + PDF + Excel (+ auto-written narrative markdown)
    5. alert     - score the run against the alert policy (anomaly gating)
    6. deliver   - e-mail (only when the policy fires, if gated) + Slack summary
    7. status    - refresh reports/status.html for the ops dashboard

Every step is skippable so the job can be re-run cheaply while debugging:
    --skip-refresh --no-email --email-dry-run --format csv --slack-dry-run

Custom range instead of the rolling week:
    python -m src.orchestration.nightly_export \
        --post-start 2024-06-01 --post-end 2024-06-30 --baseline-weeks 2
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

from ..notifications import slack as slack_notify
from ..reporting import cohort_export, status as status_dashboard
from ..reporting.alerting import AlertPolicy
from ..reporting.filters import CohortFilter
from ..utils.config_loader import setup_logging

log = logging.getLogger("nightly")

ENRICHED_DAILY_TABLE = "marts.mart_daily_volume_enriched_by_type"


def refresh_marts() -> list[str]:
    from ..etl.run_sql_pipeline import run as run_sql
    log.info("refreshing SQL layers")
    return run_sql()


def run(out_dir: str | Path = "reports/exports/nightly", *, fmt: str = "all",
        week_days: int = 7, baseline_weeks: int = 4, lag_days: int = 1,
        alpha: float = 0.01, skip_refresh: bool = False,
        from_parquet: str | Path | None = None,
        filters: CohortFilter | None = None,
        email: bool = True, email_to=None, email_dry_run: bool = False,
        post_start=None, post_end=None, baseline_start=None, baseline_end=None,
        notify_on_anomaly: bool = True, alert_policy: AlertPolicy | None = None,
        slack: bool = True, slack_dry_run: bool = False, slack_channel=None,
        status_html: str | Path | None = "reports/status.html",
        metrics: bool = True,
        metrics_path: str | Path = "reports/metrics/nyc311.prom",
        pushgateway: str | None = None,
        audit: bool = True) -> dict:
    started = datetime.now(timezone.utc)
    result: dict = {"started_at": started.isoformat(), "refreshed": [],
                    "status": "ok"}
    custom = bool(post_start or post_end)
    stem = (f"cohort_{pd_date(post_start)}_{pd_date(post_end)}" if custom
            else f"cohort_recent_week_{started:%Y%m%d}")

    try:
        if not skip_refresh and not from_parquet:
            result["refreshed"] = refresh_marts()

        export = cohort_export.run(
            out_dir=out_dir, fmt=fmt, alpha=alpha, from_parquet=from_parquet,
            filters=filters, recent_week=not custom, week_days=week_days,
            baseline_weeks=baseline_weeks, lag_days=lag_days,
            post_start=post_start, post_end=post_end,
            baseline_start=baseline_start, baseline_end=baseline_end,
            stem=stem,
            email=email, email_to=email_to, email_dry_run=email_dry_run,
            email_subject_prefix="[NYC 311 nightly]",
            notify_on_anomaly=notify_on_anomaly,
            alert_policy=alert_policy,
            alert_state_path=Path(out_dir) / "alert_state.json",
            audit=audit)
    except Exception as exc:                             # noqa: BLE001 - report, then re-raise
        result.update({"status": "failed", "error": f"{type(exc).__name__}: {exc}",
                       "finished_at": datetime.now(timezone.utc).isoformat()})
        _append_run_log(out_dir, result)
        if metrics:
            result["metrics"] = _emit_metrics(result, metrics_path, pushgateway,
                                              from_parquet, out_dir)
        if slack:
            slack_notify.notify(status="failure", headline="Nightly export failed",
                                error=result["error"], scope=(filters or CohortFilter()).label(),
                                dry_run=slack_dry_run, channel=slack_channel,
                                duration_s=_elapsed(started))
        raise

    result.update({k: str(v) for k, v in export["files"].items()})
    result["window"] = export.get("window")
    result["cohorts"] = export.get("cohorts")
    result["scope"] = export.get("scope")
    result["email"] = export.get("email")
    result["alert"] = export.get("alert")
    result["finished_at"] = datetime.now(timezone.utc).isoformat()
    result["duration_s"] = _elapsed(started)
    result["audit"] = export.get("audit")

    alert = export.get("alert") or {}
    if slack:
        result["slack"] = slack_notify.notify(
            status="success" if not alert or alert.get("should_notify") else "skipped",
            headline=alert.get("headline") or f"{export.get('cohorts', 0)} cohorts exported",
            window_label=(export.get("window") or {}).get("label", ""),
            scope=export.get("scope", ""),
            files={k: str(v) for k, v in export["files"].items()},
            reasons="\n".join(f"• {r}" for r in alert.get("reasons", [])),
            duration_s=_elapsed(started), dry_run=slack_dry_run, channel=slack_channel)
        result["slack"].pop("payload", None)

    _append_run_log(out_dir, result)

    if metrics:
        result["metrics"] = _emit_metrics(result, metrics_path, pushgateway,
                                          from_parquet, out_dir,
                                          artifacts=export["files"])

    if status_html:
        try:
            state = status_dashboard.collect(
                Path(out_dir) / "nightly_runs.jsonl", from_parquet=from_parquet,
                export_dirs=(str(out_dir), *status_dashboard.EXPORT_DIRS))
            path = Path(status_html)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(status_dashboard.render_html(state))
            result["status_dashboard"] = str(path)
        except Exception:                                # noqa: BLE001 - never fail the job
            log.warning("could not refresh the status dashboard", exc_info=True)

    log.info("nightly export complete: %s", ", ".join(
        f"{k}={v}" for k, v in export["files"].items()))
    return result


def _emit_metrics(result: dict, path, gateway, from_parquet, out_dir,
                  artifacts: dict | None = None) -> dict:
    """Prometheus textfile (+ optional push). Never fails the nightly job."""
    try:
        from ..observability import metrics as prom
        tables = status_dashboard.table_health(from_parquet)
        return prom.emit(result, tables=tables,
                         artifacts={k: str(v) for k, v in (artifacts or {}).items()
                                    if k in ("csv", "pdf", "xlsx")},
                         path=path, gateway=gateway)
    except Exception as exc:                             # noqa: BLE001
        log.warning("could not emit Prometheus metrics: %s", exc)
        return {"error": str(exc)}


def pd_date(value) -> str:
    import pandas as pd
    return f"{pd.Timestamp(value):%Y%m%d}" if value else "na"


def _elapsed(started: datetime) -> float:
    return (datetime.now(timezone.utc) - started).total_seconds()


def _append_run_log(out_dir: str | Path, result: dict) -> Path:
    run_log = Path(out_dir) / "nightly_runs.jsonl"
    run_log.parent.mkdir(parents=True, exist_ok=True)
    with run_log.open("a") as handle:
        handle.write(json.dumps({k: v for k, v in result.items()
                                 if k != "refreshed"}, default=str) + "\n")
    return run_log


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="reports/exports/nightly")
    parser.add_argument("--format", dest="fmt",
                        choices=["csv", "pdf", "xlsx", "both", "all"], default="all")
    parser.add_argument("--week-days", type=int, default=7)
    parser.add_argument("--baseline-weeks", type=int, default=4)
    parser.add_argument("--lag-days", type=int, default=1,
                        help="ignore the newest N days (late-arriving 311 rows)")
    parser.add_argument("--alpha", type=float, default=0.01)
    parser.add_argument("--skip-refresh", action="store_true")
    parser.add_argument("--from-parquet", default=None)
    parser.add_argument("--borough", action="append", default=None)
    parser.add_argument("--complaint-type", action="append", default=None)
    parser.add_argument("--no-email", action="store_true")
    parser.add_argument("--email-to", default=None)
    parser.add_argument("--email-dry-run", action="store_true")
    parser.add_argument("--post-start", default=None,
                        help="custom range: first day of the post-change window "
                             "(disables the rolling most-recent-week logic)")
    parser.add_argument("--post-end", default=None)
    parser.add_argument("--baseline-start", default=None)
    parser.add_argument("--baseline-end", default=None)
    parser.add_argument("--always-email", action="store_true",
                        help="skip anomaly gating and e-mail every run")
    parser.add_argument("--alert-alpha", type=float, default=0.01)
    parser.add_argument("--alert-min-abs-change", type=float, default=25.0)
    parser.add_argument("--alert-net-pct", type=float, default=10.0)
    parser.add_argument("--no-slack", action="store_true")
    parser.add_argument("--slack-dry-run", action="store_true")
    parser.add_argument("--slack-channel", default=None)
    parser.add_argument("--no-status-html", action="store_true")
    parser.add_argument("--no-metrics", action="store_true",
                        help="skip the Prometheus textfile / push")
    parser.add_argument("--metrics-out", default="reports/metrics/nyc311.prom")
    parser.add_argument("--pushgateway", default=None,
                        help="Prometheus Pushgateway base URL "
                             "(defaults to $PROMETHEUS_PUSHGATEWAY_URL)")
    parser.add_argument("--no-audit", action="store_true",
                        help="skip the reproducibility audit record")
    args = parser.parse_args()

    setup_logging()
    filters = CohortFilter(boroughs=args.borough or [],
                           complaint_types=args.complaint_type or [],
                           source="nightly CLI")
    try:
        outcome = run(args.out, fmt=args.fmt, week_days=args.week_days,
                      baseline_weeks=args.baseline_weeks, lag_days=args.lag_days,
                      alpha=args.alpha, skip_refresh=args.skip_refresh,
                      from_parquet=args.from_parquet, filters=filters,
                      email=not args.no_email, email_to=args.email_to,
                      email_dry_run=args.email_dry_run,
                      post_start=args.post_start, post_end=args.post_end,
                      baseline_start=args.baseline_start,
                      baseline_end=args.baseline_end,
                      notify_on_anomaly=not args.always_email,
                      alert_policy=AlertPolicy(alpha=args.alert_alpha,
                                               min_abs_change=args.alert_min_abs_change,
                                               net_pct_threshold=args.alert_net_pct),
                      slack=not args.no_slack, slack_dry_run=args.slack_dry_run,
                      slack_channel=args.slack_channel,
                      status_html=None if args.no_status_html else "reports/status.html",
                      metrics=not args.no_metrics, metrics_path=args.metrics_out,
                      pushgateway=args.pushgateway, audit=not args.no_audit)
    except Exception:                                    # noqa: BLE001 - cron needs a code
        log.exception("nightly export failed")
        return 1
    print(json.dumps({k: v for k, v in outcome.items() if k != "refreshed"},
                     indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
