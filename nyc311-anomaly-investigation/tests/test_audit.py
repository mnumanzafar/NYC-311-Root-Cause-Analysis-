"""Audit records: fingerprints, parameters, replay command, log."""
from __future__ import annotations

import json

import pandas as pd

from src.reporting import audit


def frame() -> pd.DataFrame:
    return pd.DataFrame({
        "date_day": pd.to_datetime(["2024-06-01", "2024-06-02", "2024-06-03"]),
        "borough": ["BROOKLYN", "QUEENS", "BROOKLYN"],
        "complaint_type": ["Noise", "Heat", "Noise"],
        "volume": [10, 20, 30],
    })


def test_fingerprint_is_order_independent_but_value_sensitive():
    a = frame()
    shuffled = a.iloc[::-1][["volume", "complaint_type", "borough", "date_day"]]
    assert audit.fingerprint_frame(a) == audit.fingerprint_frame(shuffled)

    changed = a.copy()
    changed.loc[0, "volume"] = 11
    assert audit.fingerprint_frame(changed) != audit.fingerprint_frame(a)


def test_describe_dataset_reports_span_and_cardinality():
    info = audit.describe_dataset("export_frame", frame())
    assert info["rows"] == 3 and info["columns"] == 4
    assert info["date_min"] == "2024-06-01" and info["date_max"] == "2024-06-03"
    assert info["distinct_borough"] == 2 and info["distinct_complaint_type"] == 2
    assert info["fingerprint"].startswith("sha256:")


def test_replay_command_round_trips_windows_and_filters():
    command = audit.replay_command({
        "alpha": 0.05,
        "window": {"post_start": "2024-06-01", "post_end": "2024-06-07",
                   "baseline_start": "2024-05-04", "baseline_end": "2024-05-31"},
        "filters": {"boroughs": ["BROOKLYN"], "complaint_types": ["Noise"]},
    })
    assert "--post-start 2024-06-01" in command and "--post-end 2024-06-07" in command
    assert "--baseline-start 2024-05-04" in command
    assert "--alpha 0.05" in command
    assert '--borough "BROOKLYN"' in command and '--complaint-type "Noise"' in command


def test_build_record_and_write_emit_json_markdown_and_log(tmp_path):
    csv = tmp_path / "cohort.csv"
    csv.write_text("a,b\n1,2\n")
    record = audit.build_record(
        parameters={"alpha": 0.01, "recent_week": True, "week_days": 7,
                    "filters": {"boroughs": [], "complaint_types": []}},
        datasets=[audit.describe_dataset("export_frame", frame())],
        outputs={"csv": csv})
    paths = audit.write(record, tmp_path, "cohort", log_path=tmp_path / "audit_log.jsonl")

    saved = json.loads(paths["json"].read_text())
    assert saved["run_id"] == record["run_id"]
    assert saved["inputs_fingerprint"].startswith("sha256:")
    assert saved["outputs"][0]["fingerprint"].startswith("sha256:")
    assert saved["environment"]["python"]

    md = paths["markdown"].read_text()
    assert "# Export audit" in md and "## Reproduce" in md
    assert "`alpha`" in md and "export_frame" in md

    log = audit.load_log(paths["log"])
    assert len(log) == 1 and log[0]["run_id"] == record["run_id"]
    assert audit.find(record["run_id"], paths["log"])["audit_json"] == str(paths["json"])


def test_identical_inputs_produce_identical_inputs_fingerprint():
    one = audit.build_record(parameters={}, datasets=[audit.describe_dataset("f", frame())])
    two = audit.build_record(parameters={}, datasets=[audit.describe_dataset("f", frame())])
    assert one["inputs_fingerprint"] == two["inputs_fingerprint"]
    assert one["run_id"] != two["run_id"]
