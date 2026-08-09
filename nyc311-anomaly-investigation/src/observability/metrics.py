"""Prometheus metrics for the nightly pipeline.

Emits a plain OpenMetrics/Prometheus **text exposition** file that either the
node_exporter *textfile collector* scrapes from disk, or that we push to a
Pushgateway (nightly batch jobs have no long-lived HTTP endpoint, so those are
the two supported delivery modes).

    from src.observability import metrics
    metrics.write(metrics.from_run(run_result, tables=status_tables))

Series exported
---------------
``nyc311_nightly_last_success_timestamp_seconds``   gauge
``nyc311_nightly_duration_seconds``                 gauge   {status}
``nyc311_nightly_run_total``                        counter {status}
``nyc311_nightly_cohorts``                          gauge
``nyc311_table_rows``                               gauge   {table,source}
``nyc311_table_lag_days``                           gauge   {table}
``nyc311_table_freshness_ok``                       gauge   {table,verdict}
``nyc311_freshness_checks_failed``                  gauge
``nyc311_alert_triggered_total``                    counter {trigger}
``nyc311_notification_total``                       counter {channel,result}
``nyc311_export_artifact_bytes``                    gauge   {kind}

Counters are cumulative across runs: the previous values are read back from the
textfile before writing, so restarting the job never resets a ``_total`` series
(Prometheus would otherwise see a spurious counter reset).

CLI:
    python -m src.observability.metrics                    # rebuild from run log
    python -m src.observability.metrics --push http://pushgw:9091
"""
from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_TEXTFILE = "reports/metrics/nyc311.prom"
JOB_NAME = "nyc311_nightly"

HELP = {
    "nyc311_nightly_last_success_timestamp_seconds":
        ("gauge", "Unix time of the last successful nightly export"),
    "nyc311_nightly_duration_seconds": ("gauge", "Duration of the last nightly run"),
    "nyc311_nightly_run_total": ("counter", "Nightly runs by terminal status"),
    "nyc311_nightly_cohorts": ("gauge", "Cohorts in the last exported comparison"),
    "nyc311_table_rows": ("gauge", "Row count per staging/mart table"),
    "nyc311_table_lag_days": ("gauge", "Days between today and the table's newest date_day"),
    "nyc311_table_freshness_ok": ("gauge", "1 when the freshness verdict is OK, else 0"),
    "nyc311_freshness_checks_failed": ("gauge", "Number of tables failing their freshness budget"),
    "nyc311_alert_triggered_total": ("counter", "Alert-policy triggers fired, by trigger name"),
    "nyc311_notification_total": ("counter", "Notifications by channel and result"),
    "nyc311_export_artifact_bytes": ("gauge", "Size of the latest export artifact by kind"),
}

_LABEL_UNSAFE = re.compile(r'([\\"\n])')


@dataclass
class Sample:
    name: str
    value: float
    labels: dict[str, str] = field(default_factory=dict)

    @property
    def key(self) -> str:
        return f"{self.name}{_render_labels(self.labels)}"

    def render(self) -> str:
        value = self.value
        text = f"{value:.6f}".rstrip("0").rstrip(".") if isinstance(value, float) else str(value)
        return f"{self.key} {text or '0'}"


def _render_labels(labels: dict[str, str]) -> str:
    if not labels:
        return ""
    inner = ",".join(
        f'{k}="{_LABEL_UNSAFE.sub(lambda m: chr(92) + (m.group(1) if m.group(1) != chr(10) else "n"), str(v))}"'
        for k, v in sorted(labels.items()))
    return "{" + inner + "}"


# --------------------------------------------------------------- build samples
def from_run(run: dict | None, *, tables: list[dict] | None = None,
             artifacts: dict | None = None) -> list[Sample]:
    """Translate one nightly ``run`` result (+ status tables) into samples."""
    samples: list[Sample] = []
    run = run or {}
    status = str(run.get("status") or "unknown")

    duration = _duration_s(run)
    if duration is not None:
        samples.append(Sample("nyc311_nightly_duration_seconds", duration,
                              {"status": status}))
    samples.append(Sample("nyc311_nightly_run_total", 1, {"status": status}))

    if status == "ok":
        finished = _parse_ts(run.get("finished_at"))
        if finished:
            samples.append(Sample("nyc311_nightly_last_success_timestamp_seconds",
                                  finished.timestamp()))
    if run.get("cohorts") is not None:
        samples.append(Sample("nyc311_nightly_cohorts", float(run["cohorts"])))

    failed = 0
    for table in tables or []:
        name = table.get("table", "unknown")
        verdict = str(table.get("verdict", "MISSING"))
        ok = 1 if verdict == "OK" else 0
        failed += 1 - ok
        if table.get("rows") is not None:
            samples.append(Sample("nyc311_table_rows", float(table["rows"]),
                                  {"table": name, "source": str(table.get("source", "unknown"))}))
        if table.get("lag_days") is not None:
            samples.append(Sample("nyc311_table_lag_days", float(table["lag_days"]),
                                  {"table": name}))
        samples.append(Sample("nyc311_table_freshness_ok", ok,
                              {"table": name, "verdict": verdict}))
    if tables is not None:
        samples.append(Sample("nyc311_freshness_checks_failed", float(failed)))

    alert = run.get("alert") or {}
    for trigger in alert.get("triggers", []) or []:
        samples.append(Sample("nyc311_alert_triggered_total", 1, {"trigger": str(trigger)}))
    if alert and not alert.get("triggers"):
        samples.append(Sample("nyc311_alert_triggered_total", 0, {"trigger": "none"}))

    email = run.get("email") or {}
    if email:
        samples.append(Sample("nyc311_notification_total", 1,
                              {"channel": "email",
                               "result": "sent" if email.get("sent") else "skipped"}))
    slack = run.get("slack")
    if slack:
        result = slack.get("status", "sent") if isinstance(slack, dict) else "sent"
        samples.append(Sample("nyc311_notification_total", 1,
                              {"channel": "slack", "result": str(result)}))

    for kind, path in (artifacts or {}).items():
        try:
            size = Path(str(path)).stat().st_size
        except OSError:
            continue
        samples.append(Sample("nyc311_export_artifact_bytes", float(size), {"kind": kind}))
    return samples


def _duration_s(run: dict) -> float | None:
    if run.get("duration_s") is not None:
        try:
            return float(run["duration_s"])
        except (TypeError, ValueError):
            return None
    start, end = _parse_ts(run.get("started_at")), _parse_ts(run.get("finished_at"))
    return (end - start).total_seconds() if start and end else None


def _parse_ts(value) -> datetime | None:
    if not value:
        return None
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)


# ------------------------------------------------------------------- rendering
def is_counter(name: str) -> bool:
    return HELP.get(name, ("gauge", ""))[0] == "counter"


def parse_existing(text: str) -> dict[str, float]:
    """Read back previous ``_total`` values so counters keep accumulating."""
    out: dict[str, float] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, _, value = line.rpartition(" ")
        try:
            out[key.strip()] = float(value)
        except ValueError:
            continue
    return out


def render(samples: list[Sample], previous: dict[str, float] | None = None) -> str:
    previous = previous or {}
    merged: dict[str, Sample] = {}
    for sample in samples:
        key = sample.key
        if is_counter(sample.name):
            base = merged[key].value if key in merged else previous.get(key, 0.0)
            merged[key] = Sample(sample.name, base + sample.value, sample.labels)
        else:
            merged[key] = sample
    # keep counter series that this run did not touch
    for key, value in previous.items():
        if is_counter(key.split("{", 1)[0]) and key not in merged:
            merged[key] = _RawSample(key, value)

    lines: list[str] = [f"# generated {datetime.now(timezone.utc).isoformat()} by "
                        "src/observability/metrics.py"]
    for name in sorted({_name_of(s) for s in merged.values()}):
        kind, help_text = HELP.get(name, ("gauge", name))
        lines.append(f"# HELP {name} {help_text}")
        lines.append(f"# TYPE {name} {kind}")
        for sample in sorted((s for s in merged.values() if _name_of(s) == name),
                             key=lambda s: _key_of(s)):
            lines.append(sample.render())
    return "\n".join(lines) + "\n"


class _RawSample(Sample):
    """A carried-over series whose labels we only have in rendered form."""

    def __init__(self, key: str, value: float) -> None:
        super().__init__(key.split("{", 1)[0], value, {})
        self._key = key

    @property
    def key(self) -> str:                                       # type: ignore[override]
        return self._key

    def render(self) -> str:
        text = f"{self.value:.6f}".rstrip("0").rstrip(".")
        return f"{self._key} {text or '0'}"


def _name_of(sample: Sample) -> str:
    return sample.name


def _key_of(sample: Sample) -> str:
    return sample.key


def write(samples: list[Sample], path: str | Path = DEFAULT_TEXTFILE) -> Path:
    """Atomically write the textfile-collector file (keeps counters monotonic)."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    previous = parse_existing(target.read_text()) if target.exists() else {}
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(render(samples, previous))
    tmp.replace(target)
    return target


def push(samples: list[Sample], gateway: str, *, job: str = JOB_NAME,
         instance: str | None = None, timeout: float = 10.0) -> dict:
    """POST the same exposition to a Prometheus Pushgateway."""
    import urllib.error
    import urllib.request

    url = f"{gateway.rstrip('/')}/metrics/job/{job}"
    if instance:
        url += f"/instance/{instance}"
    body = render(samples).encode()
    request = urllib.request.Request(url, data=body, method="POST",
                                     headers={"Content-Type": "text/plain"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return {"pushed": True, "url": url, "status": response.status}
    except urllib.error.URLError as exc:                        # noqa: BLE001
        return {"pushed": False, "url": url, "error": str(exc)}


def emit(run: dict | None, *, tables: list[dict] | None = None,
         artifacts: dict | None = None,
         path: str | Path = DEFAULT_TEXTFILE,
         gateway: str | None = None) -> dict:
    """Build + write (+ optionally push) in one call. Never raises."""
    try:
        samples = from_run(run, tables=tables, artifacts=artifacts)
        written = write(samples, path)
        out = {"samples": len(samples), "path": str(written)}
        gateway = gateway or os.getenv("PROMETHEUS_PUSHGATEWAY_URL")
        if gateway:
            out["push"] = push(samples, gateway)
        return out
    except Exception as exc:                                    # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-log", default="reports/exports/nightly/nightly_runs.jsonl")
    parser.add_argument("--out", default=DEFAULT_TEXTFILE)
    parser.add_argument("--push", default=None, help="Pushgateway base URL")
    args = parser.parse_args()

    from ..reporting import status as status_dashboard

    run = None
    log_path = Path(args.run_log)
    if log_path.exists():
        for line in reversed(log_path.read_text().splitlines()):
            if line.strip():
                run = json.loads(line)
                break
    tables = status_dashboard.table_health()
    result = emit(run, tables=tables, path=args.out, gateway=args.push)
    print(json.dumps(result, indent=2))
    return 0 if "error" not in result else 1


if __name__ == "__main__":
    raise SystemExit(main())
