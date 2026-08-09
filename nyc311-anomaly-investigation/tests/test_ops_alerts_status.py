"""Custom date ranges, anomaly gating, Slack payloads and the status dashboard."""
from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.notifications import slack
from src.reporting import alerting, status
from src.reporting.recent_week import (build_window_cohorts, explicit_windows)


# ------------------------------------------------------------------- fixtures
def make_daily(start="2024-05-01", days=90, seed=0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.date_range(start, periods=days, freq="D")
    rows = []
    for borough in ("BROOKLYN", "QUEENS"):
        for complaint in ("Noise - Residential", "Heat/Hot Water"):
            base = 100 if borough == "BROOKLYN" else 60
            for i, day in enumerate(dates):
                bump = 40 if (i >= days - 10 and complaint == "Heat/Hot Water") else 0
                rows.append({
                    "date_day": day, "borough": borough, "complaint_type": complaint,
                    "volume": base + bump + int(rng.normal(0, 4)),
                    "temp_max_f": 70 + rng.normal(0, 5), "precip_in": abs(rng.normal(0.1, 0.1)),
                    "is_hot_day": False, "is_freezing_day": False,
                    "is_heavy_rain_day": False, "is_snow_day": False,
                    "is_high_wind_day": False, "is_holiday": day.dayofweek == 0,
                })
    return pd.DataFrame(rows)


def comparison_frame(**over) -> pd.DataFrame:
    frame = pd.DataFrame({
        "borough": ["BROOKLYN", "QUEENS", "BRONX"],
        "complaint_type": ["Heat/Hot Water", "Noise - Residential", "Street Condition"],
        "abs_change": [420.0, -30.0, 5.0],
        "baseline_volume_scaled": [1000.0, 900.0, 800.0],
        "q_value": [0.0001, 0.4, 0.9],
        "driver_day_pct_delta": [22.0, 1.0, 0.0],
    })
    for key, value in over.items():
        frame[key] = value
    return frame


# -------------------------------------------------------------- custom windows
def test_explicit_windows_defaults_baseline_to_preceding_block():
    w = explicit_windows("2024-06-10", "2024-06-16", baseline_weeks=3)
    assert (w.post_start.date(), w.post_end.date()) == (date(2024, 6, 10), date(2024, 6, 16))
    assert w.post_days == 7 and w.baseline_days == 21
    assert w.baseline_end.date() == date(2024, 6, 9)


def test_explicit_windows_accepts_explicit_baseline_and_normalises_order():
    w = explicit_windows("2024-06-16", "2024-06-10", "2024-05-31", "2024-05-01")
    assert w.post_start < w.post_end and w.baseline_start < w.baseline_end
    assert w.to_dict()["label"].startswith("post 2024-06-10")


def test_explicit_windows_rejects_overlapping_baseline():
    with pytest.raises(ValueError, match="overlaps"):
        explicit_windows("2024-06-01", "2024-06-30", "2024-05-15", "2024-06-05")


def test_custom_window_cohorts_match_the_requested_range():
    daily = make_daily()
    windows = explicit_windows("2024-07-20", "2024-07-26", baseline_weeks=2)
    comparison, tagged, used = build_window_cohorts(daily, windows)
    assert used is windows
    assert comparison["post_days"].max() == 7
    assert comparison["baseline_days"].max() == 14
    assert tagged["date_day"].min() >= windows.baseline_start
    assert tagged["date_day"].max() <= windows.post_end


def test_custom_window_outside_the_data_is_a_clear_error():
    with pytest.raises(ValueError, match="no rows"):
        build_window_cohorts(make_daily(), explicit_windows("2030-01-01", "2030-01-07"))


# --------------------------------------------------------------- alert gating
def test_alert_fires_on_significant_cohort_and_names_it():
    decision = alerting.evaluate(comparison_frame(), previous={"top": [
        {"cohort": "BROOKLYN / Heat/Hot Water"}]})
    assert decision.should_notify
    assert "significant" in decision.triggers
    assert "BROOKLYN / Heat/Hot Water" in " ".join(decision.reasons)


def test_alert_stays_quiet_on_a_boring_night():
    quiet = comparison_frame(abs_change=[4.0, -3.0, 1.0],
                             q_value=[0.6, 0.7, 0.9],
                             driver_day_pct_delta=[1.0, 0.5, 0.0])
    previous = alerting.fingerprint(quiet)
    decision = alerting.evaluate(quiet, previous=previous)
    assert not decision.should_notify
    assert decision.triggers == []
    assert "No notable change" in decision.headline


def test_first_run_always_notifies():
    quiet = comparison_frame(abs_change=[1.0, 0.0, 0.0], q_value=[0.8, 0.9, 0.9],
                             driver_day_pct_delta=[0.0, 0.0, 0.0])
    assert alerting.evaluate(quiet, previous=None).triggers == ["first_run"]


def test_top_driver_change_triggers_even_without_new_significance():
    quiet = comparison_frame(abs_change=[10.0, -8.0, 2.0], q_value=[0.5, 0.6, 0.9],
                             driver_day_pct_delta=[1.0, 0.0, 0.0])
    previous = {"top": [{"cohort": "QUEENS / Noise - Residential"}]}
    decision = alerting.evaluate(quiet, previous=previous)
    assert "driver_change" in decision.triggers


def test_net_shift_and_driver_share_thresholds_are_configurable():
    frame = comparison_frame(q_value=[0.9, 0.9, 0.9])
    previous = alerting.fingerprint(frame)
    strict = alerting.evaluate(frame, policy=alerting.AlertPolicy(
        net_pct_threshold=99.0, driver_pp_threshold=99.0), previous=previous)
    assert not strict.should_notify
    loose = alerting.evaluate(frame, policy=alerting.AlertPolicy(
        net_pct_threshold=5.0, driver_pp_threshold=10.0), previous=previous)
    assert {"net_shift", "driver_share"} <= set(loose.triggers)


def test_alert_state_round_trips(tmp_path):
    path = tmp_path / "state.json"
    assert alerting.load_state(path) is None
    fp = alerting.fingerprint(comparison_frame())
    alerting.save_state(fp, path)
    assert alerting.load_state(path)["top"][0]["cohort"] == "BROOKLYN / Heat/Hot Water"


def test_corrupt_alert_state_is_treated_as_missing(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("{not json")
    assert alerting.load_state(path) is None


# ----------------------------------------------------------------- slack layer
def test_slack_payload_lists_every_artifact_and_status(monkeypatch):
    monkeypatch.delenv("EXPORT_BASE_URL", raising=False)
    payload = slack.build_message(
        status="success", headline="+420 requests net",
        window_label="post 2024-06-10–2024-06-16", scope="All boroughs",
        files={"pdf": "/x/a.pdf", "csv": "/x/a.csv", "xlsx": "/x/a.xlsx"},
        duration_s=12.5)
    text = json.dumps(payload)
    assert payload["text"].startswith(":white_check_mark:")
    for name in ("a.csv", "a.pdf", "a.xlsx"):
        assert name in text
    assert "+420 requests net" in text


def test_slack_links_artifacts_when_a_base_url_is_set(monkeypatch):
    monkeypatch.setenv("EXPORT_BASE_URL", "https://share.example.com/311/")
    assert slack.artifact_link("/tmp/report.pdf") == \
        "<https://share.example.com/311/report.pdf|report.pdf>"


def test_slack_failure_message_carries_the_error(monkeypatch):
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
    payload = slack.build_message(status="failure", headline="Nightly export failed",
                                  error="RuntimeError: mart missing")
    assert ":rotating_light:" in payload["text"]
    assert "mart missing" in json.dumps(payload)


def test_slack_notify_skips_cleanly_when_unconfigured(monkeypatch):
    for var in ("SLACK_WEBHOOK_URL", "SLACK_BOT_TOKEN", "SLACK_CHANNEL"):
        monkeypatch.delenv(var, raising=False)
    out = slack.notify(status="success", headline="hi")
    assert out["sent"] is False and out["transport"] is None and "skipped" in out


def test_slack_dry_run_builds_but_does_not_send(monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.test/abc")
    calls = []
    monkeypatch.setattr(slack, "_post", lambda *a, **k: calls.append(a))
    out = slack.notify(status="success", headline="hi", dry_run=True)
    assert out["transport"] == "webhook" and out["sent"] is False and not calls


def test_slack_web_api_transport_posts_to_chat_postmessage(monkeypatch):
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setenv("SLACK_CHANNEL", "#ops-311")
    seen = {}

    def fake_post(url, payload, headers, timeout=30):
        seen.update(url=url, payload=payload, headers=headers)
        return {"ok": True, "ts": "1.0"}

    monkeypatch.setattr(slack, "_post", fake_post)
    out = slack.notify(status="success", headline="hi")
    assert out["sent"] and seen["url"] == slack.SLACK_POST_MESSAGE
    assert seen["payload"]["channel"] == "#ops-311"
    assert seen["headers"]["Authorization"] == "Bearer xoxb-test"


def test_slack_network_failure_is_reported_not_raised(monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.test/abc")

    def boom(*a, **k):
        raise OSError("connection refused")

    monkeypatch.setattr(slack, "_post", boom)
    out = slack.notify(status="success", headline="hi")
    assert out["sent"] is False and "connection refused" in out["error"]


# ------------------------------------------------------------------ dashboard
def write_run_log(tmp_path: Path, **over) -> Path:
    finished = datetime.now(timezone.utc)
    entry = {"started_at": (finished - timedelta(seconds=42)).isoformat(),
             "finished_at": finished.isoformat(), "status": "ok",
             "cohorts": 12, "scope": "All boroughs",
             "window": {"post_start": "2024-06-10", "post_end": "2024-06-16",
                        "baseline_start": "2024-05-13", "baseline_end": "2024-06-09",
                        "label": "post 2024-06-10–2024-06-16"},
             "alert": {"should_notify": True}, "email": {"sent": True},
             "slack": {"sent": True}}
    entry.update(over)
    path = tmp_path / "nightly_runs.jsonl"
    path.write_text(json.dumps(entry, default=str) + "\n")
    return path


def test_run_summary_reads_duration_and_notification_state(tmp_path):
    summary = status.run_summary(write_run_log(tmp_path))
    assert summary["status"] == "ok"
    assert 41 <= summary["duration_s"] <= 43
    assert summary["cohorts"] == 12 and summary["notified"] is True


def test_run_summary_handles_a_missing_log():
    assert status.run_summary(Path("does/not/exist.jsonl"))["status"] == "never run"


def test_old_successful_run_is_flagged_stale(tmp_path):
    old = datetime.now(timezone.utc) - timedelta(days=3)
    path = write_run_log(tmp_path, finished_at=old.isoformat(),
                         started_at=old.isoformat())
    assert status.run_summary(path)["status"] == "stale"


def test_freshness_verdicts_use_the_per_table_budget():
    fresh = status._verdict("marts.mart_cohort_daily", 1000,
                            f"{date.today():%Y-%m-%d}", source="parquet")
    stale = status._verdict("marts.mart_cohort_daily", 1000,
                            f"{date.today() - timedelta(days=30):%Y-%m-%d}",
                            source="parquet")
    empty = status._verdict("marts.mart_cohort_daily", 0, None, source="parquet")
    assert (fresh["verdict"], stale["verdict"], empty["verdict"]) == ("OK", "STALE", "EMPTY")


def test_parquet_table_health_counts_rows(tmp_path):
    frame = make_daily(days=10)
    frame.to_parquet(tmp_path / "mart_cohort_daily.parquet")
    rows = status._table_health_parquet(tmp_path)
    assert rows and rows[0]["rows"] == len(frame) and rows[0]["source"] == "parquet"


def test_latest_artifacts_sorts_newest_first_and_labels_kinds(tmp_path, monkeypatch):
    monkeypatch.delenv("EXPORT_BASE_URL", raising=False)
    (tmp_path / "a.csv").write_text("x")
    (tmp_path / "a.pdf").write_bytes(b"%PDF-1.4")
    old = tmp_path / "old.xlsx"
    old.write_bytes(b"x")
    os.utime(old, (0, 0))
    found = status.latest_artifacts([tmp_path])
    assert [f["kind"] for f in found][-1] == "Excel"
    assert {f["kind"] for f in found} == {"CSV", "PDF", "Excel"}
    assert found[0]["url"].startswith("file://")


def test_dashboard_html_renders_run_tables_and_artifacts(tmp_path):
    (tmp_path / "cohort.csv").write_text("a,b\n1,2\n")
    state = status.collect(write_run_log(tmp_path), from_parquet=tmp_path,
                           export_dirs=[tmp_path])
    html = status.render_html(state)
    assert "<title>NYC 311 pipeline status</title>" in html
    assert "cohort.csv" in html and "Marts &amp; freshness" in html
    text = status.render_text(state)
    assert "Last nightly run" in text and "Latest artifacts" in text


def test_dashboard_flags_a_failed_run_as_attention(tmp_path):
    state = status.collect(write_run_log(tmp_path, status="failed"),
                           from_parquet=tmp_path, export_dirs=[tmp_path])
    assert state["overall"] == "attention"
