"""Status dashboard: is the pipeline healthy, and where are the latest files?

Answers four questions in one place, from the CLI or a static HTML page:

  1. **Last nightly run** — when it ran, how long it took, whether it succeeded,
     whether it notified anyone (read from ``nightly_runs.jsonl``).
  2. **Record counts** — rows per mart/staging table (Postgres, or the parquet
     mirror when the database is not reachable).
  3. **Mart freshness** — newest ``date_day`` per table versus today, with an
     OK / STALE / MISSING verdict per configurable lag budget.
  4. **Artifacts** — the most recent CSV / PDF / XLSX / narrative, with size and
     age, so the latest export is one click away.

    python -m src.reporting.status                 # text summary
    python -m src.reporting.status --html reports/status.html
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timedelta, timezone
from html import escape
from pathlib import Path

import pandas as pd

RUN_LOG = "reports/exports/nightly/nightly_runs.jsonl"
EXPORT_DIRS = ("reports/exports/nightly", "reports/exports")
ARTIFACT_KINDS = {".csv": "CSV", ".pdf": "PDF", ".xlsx": "Excel", ".md": "Narrative"}

# table -> maximum acceptable lag in days between today and its newest date_day
FRESHNESS_BUDGET = {
    "marts.mart_daily_volume_enriched_by_type": 3,
    "marts.mart_daily_volume_enriched": 3,
    "marts.mart_cohort_daily": 3,
    "staging.stg_311_requests": 3,
    "staging.stg_weather_daily": 2,
    "staging.stg_holidays_daily": -365,      # forward-looking calendar
}
COUNT_TABLES = tuple(FRESHNESS_BUDGET) + ("marts.mart_cohort_comparison",)


# ------------------------------------------------------------------ nightly run
def last_runs(run_log: str | Path = RUN_LOG, limit: int = 10) -> list[dict]:
    path = Path(run_log)
    if not path.exists():
        return []
    rows: list[dict] = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows[-limit:][::-1]


def run_summary(run_log: str | Path = RUN_LOG) -> dict:
    runs = last_runs(run_log, limit=30)
    if not runs:
        return {"status": "never run", "runs_recorded": 0,
                "detail": "no nightly_runs.jsonl yet — run `make nightly`"}
    latest = runs[0]
    started, finished = latest.get("started_at"), latest.get("finished_at")
    duration = None
    if started and finished:
        try:
            duration = (datetime.fromisoformat(finished)
                        - datetime.fromisoformat(started)).total_seconds()
        except ValueError:
            duration = None
    age_h = None
    if finished:
        try:
            age_h = (datetime.now(timezone.utc)
                     - datetime.fromisoformat(finished)).total_seconds() / 3600
        except ValueError:
            age_h = None
    finished_pretty = _pretty_ts(finished)
    status = latest.get("status") or ("ok" if latest.get("csv") or latest.get("pdf")
                                      else "unknown")
    if age_h is not None and age_h > 36 and status == "ok":
        status = "stale"
    return {
        "status": status,
        "finished_at": finished_pretty,
        "age_hours": age_h,
        "duration_s": duration,
        "window": latest.get("window"),
        "cohorts": latest.get("cohorts"),
        "scope": latest.get("scope"),
        "notified": (latest.get("alert") or {}).get("should_notify"),
        "email": latest.get("email"),
        "slack": (latest.get("slack") or {}).get("sent"),
        "runs_recorded": len(runs),
        "history": runs[:5],
    }


def _pretty_ts(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).astimezone(timezone.utc)\
            .strftime("%Y-%m-%d %H:%M UTC")
    except ValueError:
        return value


# ------------------------------------------------------------- counts/freshness
def _parquet_dir(from_parquet: str | Path | None) -> Path | None:
    if from_parquet:
        return Path(from_parquet)
    guess = Path("data/processed/marts")
    return guess if guess.exists() else None


def table_health(from_parquet: str | Path | None = None) -> list[dict]:
    """Row counts + newest date per table, from Postgres when available."""
    rows = _table_health_db() if not from_parquet else []
    if rows:
        return rows
    return _table_health_parquet(_parquet_dir(from_parquet))


def _table_health_db() -> list[dict]:
    try:
        from ..utils.db import read_sql
    except Exception:                                            # noqa: BLE001
        return []
    out: list[dict] = []
    for table in COUNT_TABLES:
        try:
            has_date = table in FRESHNESS_BUDGET
            column = "max(date_day)::text" if has_date else "null"
            frame = read_sql(f"select count(*) as n, {column} as max_date from {table}")
            out.append(_verdict(table, int(frame["n"].iloc[0]),
                                frame["max_date"].iloc[0], source="postgres"))
        except Exception as exc:                                 # noqa: BLE001
            out.append({"table": table, "rows": None, "max_date": None,
                        "verdict": "MISSING", "source": "postgres",
                        "detail": str(exc).splitlines()[0][:160]})
    return out


def _table_health_parquet(directory: Path | None) -> list[dict]:
    if directory is None or not directory.exists():
        return []
    out = []
    for file in sorted(directory.glob("*.parquet")):
        table = f"marts.{file.stem}"
        try:
            frame = pd.read_parquet(file)
            max_date = (pd.to_datetime(frame["date_day"]).max()
                        if "date_day" in frame else None)
            out.append(_verdict(table, len(frame),
                                None if max_date is None else f"{max_date:%Y-%m-%d}",
                                source="parquet"))
        except Exception as exc:                                 # noqa: BLE001
            out.append({"table": table, "rows": None, "max_date": None,
                        "verdict": "MISSING", "source": "parquet",
                        "detail": str(exc)[:160]})
    return out


def _verdict(table: str, rows: int, max_date, *, source: str) -> dict:
    budget = FRESHNESS_BUDGET.get(table)
    lag = None
    verdict = "OK"
    if max_date:
        lag = (datetime.now(timezone.utc).date() - pd.Timestamp(max_date).date()).days
        if budget is not None and lag > budget:
            verdict = "STALE"
    elif budget is not None:
        verdict = "NO DATE"
    if not rows:
        verdict = "EMPTY"
    return {"table": table, "rows": rows, "max_date": max_date, "lag_days": lag,
            "budget_days": budget, "verdict": verdict, "source": source}


# ------------------------------------------------------------------- artifacts
def latest_artifacts(dirs=EXPORT_DIRS, limit: int = 8) -> list[dict]:
    seen: list[dict] = []
    for directory in dirs:
        base = Path(directory)
        if not base.exists():
            continue
        for file in base.iterdir():
            if not file.is_file() or file.suffix.lower() not in ARTIFACT_KINDS:
                continue
            stat = file.stat()
            seen.append({
                "kind": ARTIFACT_KINDS[file.suffix.lower()],
                "name": file.name,
                "path": str(file.resolve()),
                "size_kb": round(stat.st_size / 1024, 1),
                "modified": datetime.fromtimestamp(stat.st_mtime, timezone.utc)
                            .strftime("%Y-%m-%d %H:%M UTC"),
                "age_hours": round((datetime.now(timezone.utc).timestamp()
                                    - stat.st_mtime) / 3600, 1),
                "url": _artifact_url(file),
            })
    seen.sort(key=lambda item: item["age_hours"])
    return seen[:limit]


def _artifact_url(file: Path) -> str:
    base = os.getenv("EXPORT_BASE_URL")
    return f"{base.rstrip('/')}/{file.name}" if base else file.resolve().as_uri()


# --------------------------------------------------------------------- assemble
def collect(run_log: str | Path = RUN_LOG, *, from_parquet=None,
            export_dirs=EXPORT_DIRS) -> dict:
    tables = table_health(from_parquet)
    problems = [t for t in tables if t["verdict"] not in ("OK",)]
    run = run_summary(run_log)
    overall = "healthy"
    if run["status"] in ("failed", "never run") or any(t["verdict"] == "MISSING"
                                                       for t in tables):
        overall = "attention"
    elif problems or run["status"] == "stale":
        overall = "degraded"
    return {"generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "overall": overall, "run": run, "tables": tables,
            "artifacts": latest_artifacts(export_dirs)}


def render_text(state: dict) -> str:
    run = state["run"]
    lines = [f"NYC 311 pipeline status — {state['overall'].upper()}"
             f"   (generated {state['generated_at']})", ""]
    lines.append("Last nightly run")
    lines.append(f"  status      : {run['status']}")
    if run.get("finished_at"):
        age = run.get("age_hours")
        lines.append(f"  finished    : {run['finished_at']}"
                     + (f"  ({age:.1f} h ago)" if age is not None else ""))
    if run.get("duration_s") is not None:
        lines.append(f"  duration    : {run['duration_s']:.1f}s")
    if run.get("window"):
        window = run["window"]
        lines.append("  window      : " + (window.get("label") if isinstance(window, dict)
                                           else str(window)))
    if run.get("cohorts") is not None:
        lines.append(f"  cohorts     : {run['cohorts']}")
    lines.append(f"  notified    : email={bool((run.get('email') or {}).get('sent'))} "
                 f"slack={bool(run.get('slack'))} anomaly={run.get('notified')}")
    if run.get("detail"):
        lines.append(f"  detail      : {run['detail']}")

    lines += ["", "Tables"]
    if not state["tables"]:
        lines.append("  (no database or parquet marts reachable)")
    for t in state["tables"]:
        rows = "—" if t["rows"] is None else f"{t['rows']:,}"
        lag = "" if t.get("lag_days") is None else f"  lag {t['lag_days']}d"
        lines.append(f"  [{t['verdict']:<7}] {t['table']:<45} {rows:>12}"
                     f"  max {t.get('max_date') or '—'}{lag}")

    lines += ["", "Latest artifacts"]
    if not state["artifacts"]:
        lines.append("  (none yet — run `make export` or `make nightly`)")
    for a in state["artifacts"]:
        lines.append(f"  {a['kind']:<9} {a['name']:<48} {a['size_kb']:>8} KB"
                     f"  {a['modified']}")
    return "\n".join(lines)


def render_html(state: dict) -> str:
    badge = {"healthy": "#1a7f4b", "degraded": "#b8860b", "attention": "#b3261e"}
    run = state["run"]
    verdict_color = {"OK": "#1a7f4b", "STALE": "#b8860b", "EMPTY": "#b8860b",
                     "NO DATE": "#b8860b", "MISSING": "#b3261e"}

    def rows_tables() -> str:
        if not state["tables"]:
            return "<tr><td colspan='5'>No database or parquet marts reachable.</td></tr>"
        out = []
        for t in state["tables"]:
            out.append(
                "<tr>"
                f"<td>{escape(t['table'])}</td>"
                f"<td class='num'>{'—' if t['rows'] is None else format(t['rows'], ',')}</td>"
                f"<td>{escape(str(t.get('max_date') or '—'))}</td>"
                f"<td class='num'>{'—' if t.get('lag_days') is None else t['lag_days']}</td>"
                f"<td><span class='pill' style=\"background:"
                f"{verdict_color.get(t['verdict'], '#555')}\">{escape(t['verdict'])}</span></td>"
                "</tr>")
        return "".join(out)

    def rows_artifacts() -> str:
        if not state["artifacts"]:
            return "<tr><td colspan='4'>No exports yet.</td></tr>"
        return "".join(
            "<tr>"
            f"<td>{escape(a['kind'])}</td>"
            f"<td><a href=\"{escape(a['url'])}\">{escape(a['name'])}</a></td>"
            f"<td class='num'>{a['size_kb']:,} KB</td>"
            f"<td>{escape(a['modified'])}</td>"
            "</tr>" for a in state["artifacts"])

    window = run.get("window") or {}
    window_text = (window.get("label")
                   or f"{window.get('baseline_start')}–{window.get('baseline_end')} → "
                      f"{window.get('post_start')}–{window.get('post_end')}") if window else "—"
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>NYC 311 pipeline status</title>
<style>
 :root {{ color-scheme: light; }}
 body {{ font: 15px/1.5 -apple-system, Segoe UI, Roboto, Helvetica, sans-serif;
        margin: 0; padding: 32px; background: #f6f7f9; color: #14181f; }}
 .wrap {{ max-width: 1040px; margin: 0 auto; }}
 h1 {{ font-size: 22px; margin: 0 0 4px; }}
 .sub {{ color: #5a6472; margin-bottom: 24px; }}
 .pill {{ color: #fff; border-radius: 999px; padding: 2px 10px; font-size: 12px;
         font-weight: 600; letter-spacing: .02em; }}
 .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
          gap: 12px; margin-bottom: 24px; }}
 .card {{ background: #fff; border: 1px solid #e3e6ea; border-radius: 10px; padding: 14px 16px; }}
 .card .k {{ color: #5a6472; font-size: 12px; text-transform: uppercase;
            letter-spacing: .05em; }}
 .card .v {{ font-size: 20px; font-weight: 600; margin-top: 4px; }}
 section {{ background: #fff; border: 1px solid #e3e6ea; border-radius: 10px;
           padding: 4px 16px 12px; margin-bottom: 20px; }}
 h2 {{ font-size: 15px; text-transform: uppercase; letter-spacing: .05em;
      color: #5a6472; }}
 table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
 th, td {{ text-align: left; padding: 7px 8px; border-bottom: 1px solid #eef0f3; }}
 th {{ color: #5a6472; font-weight: 600; font-size: 12px; text-transform: uppercase; }}
 td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
 a {{ color: #1b5fbe; }}
 footer {{ color: #8b95a3; font-size: 12px; margin-top: 8px; }}
</style></head><body><div class="wrap">
<h1>NYC 311 pipeline status
  <span class="pill" style="background:{badge.get(state['overall'], '#555')}">
  {escape(state['overall'].upper())}</span></h1>
<div class="sub">Generated {escape(state['generated_at'])}</div>

<div class="cards">
  <div class="card"><div class="k">Last run</div><div class="v">{escape(str(run['status']))}</div>
    <div class="sub">{escape(str(run.get('finished_at') or '—'))}</div></div>
  <div class="card"><div class="k">Duration</div><div class="v">
    {'—' if run.get('duration_s') is None else f"{run['duration_s']:.0f}s"}</div></div>
  <div class="card"><div class="k">Cohorts</div><div class="v">
    {escape(str(run.get('cohorts') if run.get('cohorts') is not None else '—'))}</div></div>
  <div class="card"><div class="k">Notified</div><div class="v">
    {'yes' if run.get('notified') else 'no'}</div>
    <div class="sub">email {str(bool((run.get('email') or {}).get('sent'))).lower()} ·
      slack {str(bool(run.get('slack'))).lower()}</div></div>
  <div class="card"><div class="k">Window</div><div class="v" style="font-size:14px">
    {escape(window_text)}</div></div>
</div>

<section><h2>Marts &amp; freshness</h2>
<table><thead><tr><th>Table</th><th class="num">Rows</th><th>Newest date</th>
<th class="num">Lag (days)</th><th>Check</th></tr></thead>
<tbody>{rows_tables()}</tbody></table></section>

<section><h2>Latest export artifacts</h2>
<table><thead><tr><th>Kind</th><th>File</th><th class="num">Size</th><th>Modified</th></tr>
</thead><tbody>{rows_artifacts()}</tbody></table></section>

<footer>Refresh with <code>make status</code>. Freshness budgets live in
src/reporting/status.py.</footer>
</div></body></html>
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-log", default=RUN_LOG)
    parser.add_argument("--from-parquet", default=None,
                        help="read marts from parquet instead of Postgres")
    parser.add_argument("--html", nargs="?", const="reports/status.html", default=None,
                        help="also write a static HTML dashboard")
    parser.add_argument("--json", action="store_true", help="print the raw state")
    parser.add_argument("--exports", action="append", default=None,
                        help="repeatable; folders to scan for export artifacts "
                             f"(default: {', '.join(EXPORT_DIRS)})")
    args = parser.parse_args()

    state = collect(args.run_log, from_parquet=args.from_parquet,
                    export_dirs=args.exports or EXPORT_DIRS)
    if args.json:
        print(json.dumps(state, indent=2, default=str))
    else:
        print(render_text(state))
    if args.html:
        path = Path(args.html)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render_html(state))
        print(f"\nhtml: {path.resolve()}")
    return 0 if state["overall"] != "attention" else 1


if __name__ == "__main__":
    raise SystemExit(main())
