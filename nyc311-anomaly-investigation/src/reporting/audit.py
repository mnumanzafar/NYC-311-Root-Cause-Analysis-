"""Reproducibility audit report for every export.

Answers "what exactly produced this file, and can I rebuild it?" — the audit
record captures the analysis parameters *and* content fingerprints of the data
that went in, so a run can be replayed for any date range and byte-compared.

Written next to the artefacts as ``<stem>_audit.json`` plus a human-readable
``<stem>_audit.md``, and appended to ``reports/exports/audit_log.jsonl``.

Captured per export
-------------------
run          : id, timestamps, host, user, CLI argv, git commit (if available)
parameters   : windows, alpha, lag/week/baseline settings, filters, alert policy
environment  : python version, key package versions, config.yaml fingerprint
datasets     : per input frame — rows, columns, date span, sha256 fingerprint
outputs      : each artefact with size and sha256
replay       : the exact command that reproduces this export

The dataset fingerprint is a sha256 over the canonical CSV of the sorted frame
(sorted columns, sorted rows), so it is stable across row/column ordering and
across pandas versions, and it changes whenever a single value changes.
"""
from __future__ import annotations

import getpass
import hashlib
import json
import os
import platform
import socket
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

AUDIT_LOG = "reports/exports/audit_log.jsonl"
_PACKAGES = ("pandas", "numpy", "scipy", "scikit-learn", "reportlab", "xlsxwriter")


# ----------------------------------------------------------------- fingerprints
def fingerprint_frame(frame: pd.DataFrame) -> str:
    """Order-independent sha256 of a dataframe's contents."""
    if frame is None or len(frame) == 0:
        return "sha256:empty"
    ordered = frame.reindex(sorted(frame.columns), axis=1)
    ordered = ordered.sort_values(list(ordered.columns), kind="mergesort")
    payload = ordered.to_csv(index=False, date_format="%Y-%m-%d").encode()
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def fingerprint_file(path: str | Path) -> str | None:
    file = Path(path)
    if not file.exists():
        return None
    digest = hashlib.sha256()
    with file.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def describe_dataset(name: str, frame: pd.DataFrame, *,
                     date_column: str = "date_day") -> dict:
    """Rows, columns, date span and fingerprint for one input frame."""
    info: dict = {"name": name, "rows": int(len(frame)),
                  "columns": int(frame.shape[1]) if len(frame.shape) > 1 else 0,
                  "column_names": [str(c) for c in frame.columns],
                  "fingerprint": fingerprint_frame(frame)}
    if date_column in frame.columns and len(frame):
        dates = pd.to_datetime(frame[date_column], errors="coerce").dropna()
        if len(dates):
            info["date_min"] = f"{dates.min():%Y-%m-%d}"
            info["date_max"] = f"{dates.max():%Y-%m-%d}"
            info["distinct_days"] = int(dates.dt.normalize().nunique())
    for key in ("borough", "complaint_type"):
        if key in frame.columns:
            info[f"distinct_{key}"] = int(frame[key].nunique(dropna=True))
    return info


# ------------------------------------------------------------------ environment
def _git_commit() -> str | None:
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                             text=True, timeout=5, check=False)
        return out.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def _package_versions() -> dict[str, str]:
    from importlib import metadata
    versions = {}
    for package in _PACKAGES:
        try:
            versions[package] = metadata.version(package)
        except Exception:                                       # noqa: BLE001
            continue
    return versions


def environment(config_path: str | Path = "config/config.yaml") -> dict:
    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "host": socket.gethostname(),
        "user": _safe_user(),
        "packages": _package_versions(),
        "config_file": str(config_path),
        "config_fingerprint": fingerprint_file(config_path),
        "git_commit": _git_commit(),
        "timezone": os.getenv("TZ") or "system",
    }


def _safe_user() -> str:
    try:
        return getpass.getuser()
    except Exception:                                           # noqa: BLE001
        return "unknown"


# ---------------------------------------------------------------------- record
def build_record(*, parameters: dict, datasets: list[dict],
                 outputs: dict | None = None, run_id: str | None = None,
                 started_at: str | None = None,
                 config_path: str | Path = "config/config.yaml") -> dict:
    outputs = outputs or {}
    now = datetime.now(timezone.utc)
    record = {
        "audit_version": 1,
        "run_id": run_id or uuid.uuid4().hex[:12],
        "created_at": now.isoformat(),
        "started_at": started_at or now.isoformat(),
        "argv": sys.argv[:],
        "parameters": _clean(parameters),
        "environment": environment(config_path),
        "datasets": datasets,
        "outputs": [
            {"kind": kind, "path": str(path), "bytes": _size(path),
             "fingerprint": fingerprint_file(path)}
            for kind, path in outputs.items()
        ],
    }
    record["replay_command"] = replay_command(record["parameters"])
    record["inputs_fingerprint"] = combined_fingerprint(datasets)
    return record


def combined_fingerprint(datasets: list[dict]) -> str:
    digest = hashlib.sha256()
    for item in sorted(datasets, key=lambda d: d.get("name", "")):
        digest.update(f"{item.get('name')}={item.get('fingerprint')}".encode())
    return "sha256:" + digest.hexdigest()


def replay_command(parameters: dict) -> str:
    window = parameters.get("window") or {}
    parts = ["python -m src.reporting.cohort_export", "--format all"]
    if window.get("post_start") and window.get("post_end"):
        parts += [f"--post-start {window['post_start']}", f"--post-end {window['post_end']}"]
        if window.get("baseline_start"):
            parts += [f"--baseline-start {window['baseline_start']}",
                      f"--baseline-end {window['baseline_end']}"]
    elif parameters.get("recent_week"):
        parts += [f"--week-days {parameters.get('week_days', 7)}",
                  f"--baseline-weeks {parameters.get('baseline_weeks', 4)}",
                  f"--lag-days {parameters.get('lag_days', 1)}"]
    parts.append(f"--alpha {parameters.get('alpha', 0.01)}")
    for borough in (parameters.get("filters") or {}).get("boroughs", []) or []:
        parts.append(f'--borough "{borough}"')
    for kind in (parameters.get("filters") or {}).get("complaint_types", []) or []:
        parts.append(f'--complaint-type "{kind}"')
    return " ".join(parts)


def _size(path) -> int | None:
    try:
        return Path(str(path)).stat().st_size
    except OSError:
        return None


def _clean(value):
    """Make parameters JSON-safe without losing information."""
    if isinstance(value, dict):
        return {str(k): _clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_clean(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (datetime, pd.Timestamp)):
        return value.isoformat()
    if hasattr(value, "to_dict"):
        try:
            return _clean(value.to_dict())
        except Exception:                                       # noqa: BLE001
            pass
    return str(value)


# --------------------------------------------------------------------- writing
def render_markdown(record: dict) -> str:
    params, env = record["parameters"], record["environment"]
    lines = [
        f"# Export audit — run `{record['run_id']}`", "",
        f"*Created {record['created_at']} · inputs `{record['inputs_fingerprint'][:23]}…`*", "",
        "## Reproduce", "", "```bash", record["replay_command"], "```", "",
        "## Analysis parameters", "", "| Parameter | Value |", "| --- | --- |",
    ]
    for key, value in _flatten(params).items():
        lines.append(f"| `{key}` | {_fmt(value)} |")

    lines += ["", "## Datasets", "",
              "| Dataset | Rows | Cols | Date span | Fingerprint |",
              "| --- | ---: | ---: | --- | --- |"]
    for item in record["datasets"]:
        span = (f"{item.get('date_min', '—')} → {item.get('date_max', '—')}"
                if item.get("date_min") else "—")
        lines.append(f"| `{item['name']}` | {item['rows']:,} | {item['columns']} | "
                     f"{span} | `{item['fingerprint'][7:19]}…` |")

    lines += ["", "## Outputs", "", "| Kind | File | Size | Fingerprint |",
              "| --- | --- | ---: | --- |"]
    for out in record["outputs"]:
        size = "—" if out["bytes"] is None else f"{out['bytes'] / 1024:,.1f} KB"
        digest = (out["fingerprint"] or "sha256:—")[7:19]
        lines.append(f"| {out['kind']} | `{Path(out['path']).name}` | {size} | `{digest}…` |")

    lines += ["", "## Environment", "",
              f"- python {env['python']} on {env['platform']}",
              f"- host `{env['host']}` · user `{env['user']}`",
              f"- git commit `{env.get('git_commit') or 'n/a'}`",
              f"- config `{env['config_file']}` `{(env.get('config_fingerprint') or '—')[7:19]}…`",
              "- packages: " + ", ".join(f"{k} {v}" for k, v in env["packages"].items()),
              "", f"- argv: `{' '.join(record['argv'])}`", ""]
    return "\n".join(lines)


def _flatten(data: dict, prefix: str = "") -> dict:
    out: dict = {}
    for key, value in (data or {}).items():
        name = f"{prefix}{key}"
        if isinstance(value, dict):
            out.update(_flatten(value, f"{name}."))
        else:
            out[name] = value
    return out


def _fmt(value) -> str:
    if isinstance(value, list):
        return ", ".join(str(v) for v in value) if value else "*(all)*"
    if value is None:
        return "—"
    return f"`{value}`" if not isinstance(value, str) else value


def write(record: dict, out_dir: str | Path, stem: str, *,
          log_path: str | Path = AUDIT_LOG) -> dict[str, Path]:
    directory = Path(out_dir)
    directory.mkdir(parents=True, exist_ok=True)
    json_path = directory / f"{stem}_audit.json"
    md_path = directory / f"{stem}_audit.md"
    json_path.write_text(json.dumps(record, indent=2, default=str))
    md_path.write_text(render_markdown(record))

    log = Path(log_path)
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a") as handle:
        handle.write(json.dumps({
            "run_id": record["run_id"], "created_at": record["created_at"],
            "inputs_fingerprint": record["inputs_fingerprint"],
            "replay_command": record["replay_command"],
            "parameters": record["parameters"],
            "outputs": [o["path"] for o in record["outputs"]],
            "audit_json": str(json_path),
        }, default=str) + "\n")
    return {"json": json_path, "markdown": md_path, "log": log}


def load_log(log_path: str | Path = AUDIT_LOG, limit: int = 50) -> list[dict]:
    path = Path(log_path)
    if not path.exists():
        return []
    rows = []
    for line in path.read_text().splitlines():
        if line.strip():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows[-limit:][::-1]


def find(run_id: str, log_path: str | Path = AUDIT_LOG) -> dict | None:
    for row in load_log(log_path, limit=10_000):
        if row.get("run_id") == run_id:
            return row
    return None


def main() -> int:
    """`python -m src.reporting.audit --list` / `--show <run_id>`."""
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", default=AUDIT_LOG)
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--show", default=None, help="run_id to print in full")
    args = parser.parse_args()

    if args.show:
        row = find(args.show, args.log)
        if not row:
            print(f"no audit record for {args.show}")
            return 1
        record = json.loads(Path(row["audit_json"]).read_text())
        print(render_markdown(record))
        return 0

    rows = load_log(args.log)
    if not rows:
        print("no audit records yet — run `make export` or `make nightly`")
        return 1
    for row in rows:
        print(f"{row['created_at']}  {row['run_id']}  "
              f"{row['inputs_fingerprint'][7:19]}…  {row['replay_command']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
