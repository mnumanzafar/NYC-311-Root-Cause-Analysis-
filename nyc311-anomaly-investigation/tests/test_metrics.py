"""Prometheus exposition: shape, labels, counter accumulation."""
from __future__ import annotations

from src.observability import metrics


RUN = {
    "status": "ok",
    "started_at": "2026-08-09T03:00:00+00:00",
    "finished_at": "2026-08-09T03:06:52+00:00",
    "cohorts": 34,
    "alert": {"should_notify": True, "triggers": ["significant", "driver_change"]},
    "email": {"sent": True, "recipients": 3},
    "slack": {"status": "sent"},
}
TABLES = [
    {"table": "marts.mart_cohort_daily", "rows": 12000, "lag_days": 1,
     "verdict": "OK", "source": "postgres"},
    {"table": "staging.stg_weather_daily", "rows": 900, "lag_days": 5,
     "verdict": "STALE", "source": "postgres"},
]


def _lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if line and not line.startswith("#")]


def test_from_run_covers_duration_freshness_and_alerts():
    text = metrics.render(metrics.from_run(RUN, tables=TABLES))
    assert 'nyc311_nightly_duration_seconds{status="ok"} 412' in text
    assert "nyc311_nightly_last_success_timestamp_seconds " in text
    assert "nyc311_nightly_cohorts 34" in text
    assert 'nyc311_table_rows{source="postgres",table="marts.mart_cohort_daily"} 12000' in text
    assert 'nyc311_table_lag_days{table="staging.stg_weather_daily"} 5' in text
    assert 'nyc311_table_freshness_ok{table="staging.stg_weather_daily",verdict="STALE"} 0' in text
    assert "nyc311_freshness_checks_failed 1" in text
    assert 'nyc311_alert_triggered_total{trigger="significant"} 1' in text
    assert 'nyc311_notification_total{channel="email",result="sent"} 1' in text


def test_help_and_type_headers_precede_every_series():
    text = metrics.render(metrics.from_run(RUN, tables=TABLES))
    for name in {line.split("{")[0].split(" ")[0] for line in _lines(text)}:
        assert f"# TYPE {name} " in text
        assert f"# HELP {name} " in text


def test_counters_accumulate_across_runs_and_gauges_replace(tmp_path):
    path = tmp_path / "nyc311.prom"
    metrics.write(metrics.from_run(RUN, tables=TABLES), path)
    second = dict(RUN, cohorts=30)
    metrics.write(metrics.from_run(second, tables=TABLES), path)
    text = path.read_text()
    assert 'nyc311_nightly_run_total{status="ok"} 2' in text        # counter grew
    assert 'nyc311_alert_triggered_total{trigger="significant"} 2' in text
    assert "nyc311_nightly_cohorts 30" in text                       # gauge replaced
    assert "nyc311_nightly_cohorts 34" not in text


def test_failed_run_still_emits_and_keeps_previous_success_counter(tmp_path):
    path = tmp_path / "nyc311.prom"
    metrics.write(metrics.from_run(RUN, tables=TABLES), path)
    failed = {"status": "failed", "started_at": RUN["started_at"],
              "finished_at": "2026-08-09T03:01:00+00:00",
              "error": "OperationalError"}
    metrics.write(metrics.from_run(failed, tables=TABLES), path)
    text = path.read_text()
    assert 'nyc311_nightly_run_total{status="failed"} 1' in text
    assert 'nyc311_nightly_run_total{status="ok"} 1' in text          # carried over


def test_artifact_sizes_are_reported(tmp_path):
    csv = tmp_path / "cohort.csv"
    csv.write_text("a,b\n1,2\n")
    text = metrics.render(metrics.from_run(RUN, artifacts={"csv": str(csv)}))
    assert f'nyc311_export_artifact_bytes{{kind="csv"}} {csv.stat().st_size}' in text


def test_emit_never_raises_on_bad_input(tmp_path):
    out = metrics.emit({"status": "ok", "cohorts": None}, tables=None,
                       path=tmp_path / "m.prom")
    assert "error" not in out and out["samples"] > 0
