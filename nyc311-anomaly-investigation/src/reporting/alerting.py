"""Anomaly-driven notification gating.

The nightly job runs every night, but most nights are boring: volumes wobble
inside the noise band and an e-mail would train everybody to ignore the alert.
This module decides whether the *latest* export is worth a notification, by
comparing it against the previous run's fingerprint stored on disk.

A run is notable when any of these fire:

  significant   - at least ``min_significant`` cohorts clear BH ``q < alpha``
                  with an absolute change of at least ``min_abs_change``
  net_shift     - the citywide net change exceeds ``net_pct_threshold`` percent
                  of the length-normalised baseline
  driver_change - the ranked top-driver cohorts differ from the previous run
                  (a new cohort entered the top ``top_n``, or the leader changed)
  driver_share  - the weather/holiday driver-day share of a top cohort moved by
                  ``driver_pp_threshold`` percentage points or more
  first_run     - no previous fingerprint exists yet

Nothing here sends anything: it returns a decision the caller acts on, which
keeps the logic testable and lets the same decision drive e-mail and Slack.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

DEFAULT_STATE_FILE = "reports/exports/nightly/alert_state.json"


@dataclass
class AlertPolicy:
    """Thresholds that decide whether a run is worth a notification."""

    alpha: float = 0.01
    min_significant: int = 1
    min_abs_change: float = 25.0
    net_pct_threshold: float = 10.0
    driver_pp_threshold: float = 15.0
    top_n: int = 5
    always_notify_on_failure: bool = True

    @classmethod
    def from_config(cls, config: dict | None) -> "AlertPolicy":
        data = dict((config or {}))
        known = {f for f in cls.__dataclass_fields__}          # noqa: SLF001 - dataclass API
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class AlertDecision:
    should_notify: bool
    reasons: list[str] = field(default_factory=list)
    triggers: list[str] = field(default_factory=list)
    headline: str = ""
    fingerprint: dict = field(default_factory=dict)
    previous: dict | None = None

    def to_dict(self) -> dict:
        return asdict(self)


# --------------------------------------------------------------------- helpers
def _num(value, default=0.0) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return default if np.isnan(out) else out


def fingerprint(df: pd.DataFrame, *, alpha: float = 0.01, top_n: int = 5,
                window: dict | None = None, scope: str | None = None) -> dict:
    """Compact, JSON-serialisable summary of an export used for run-to-run diffs."""
    if df is None or not len(df):
        return {"cohorts": 0, "net_abs_change": 0.0, "significant": [], "top": [],
                "window": window, "scope": scope,
                "generated_at": datetime.now(timezone.utc).isoformat()}

    frame = df.copy()
    frame["_key"] = frame["borough"].astype(str) + " / " + frame["complaint_type"].astype(str)
    ranked = frame.reindex(frame["abs_change"].abs().sort_values(ascending=False).index)
    significant = ranked.loc[ranked.get("q_value", pd.Series(index=ranked.index,
                                                             dtype=float)) < alpha]
    baseline_scaled = _num(frame.get("baseline_volume_scaled", pd.Series(dtype=float)).sum())
    net = _num(frame["abs_change"].sum())
    return {
        "cohorts": int(len(frame)),
        "net_abs_change": net,
        "net_pct_change": (100.0 * net / baseline_scaled) if baseline_scaled else 0.0,
        "significant": significant["_key"].head(50).tolist(),
        "top": [
            {"cohort": row["_key"],
             "abs_change": _num(row["abs_change"]),
             "q_value": _num(row.get("q_value"), 1.0),
             "driver_day_pct_delta": _num(row.get("driver_day_pct_delta"))}
            for _, row in ranked.head(top_n).iterrows()
        ],
        "window": window,
        "scope": scope,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def load_state(path: str | Path = DEFAULT_STATE_FILE) -> dict | None:
    file = Path(path)
    if not file.exists():
        return None
    try:
        return json.loads(file.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def save_state(state: dict, path: str | Path = DEFAULT_STATE_FILE) -> Path:
    file = Path(path)
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(json.dumps(state, indent=2, default=str))
    return file


# -------------------------------------------------------------------- decision
def evaluate(df: pd.DataFrame, *, policy: AlertPolicy | None = None,
             previous: dict | None = None, window: dict | None = None,
             scope: str | None = None) -> AlertDecision:
    """Decide whether this export deserves a notification."""
    policy = policy or AlertPolicy()
    current = fingerprint(df, alpha=policy.alpha, top_n=policy.top_n,
                          window=window, scope=scope)
    reasons: list[str] = []
    triggers: list[str] = []

    frame = df.copy() if df is not None and len(df) else pd.DataFrame()
    if len(frame):
        q = frame.get("q_value", pd.Series(index=frame.index, dtype=float))
        strong = frame.loc[(q < policy.alpha)
                           & (frame["abs_change"].abs() >= policy.min_abs_change)]
        if len(strong) >= policy.min_significant:
            triggers.append("significant")
            top = strong.reindex(strong["abs_change"].abs()
                                 .sort_values(ascending=False).index).iloc[0]
            reasons.append(
                f"{len(strong)} cohort(s) significant at BH q < {policy.alpha} with "
                f"|change| >= {policy.min_abs_change:,.0f}; largest is "
                f"{top['borough']} / {top['complaint_type']} "
                f"({_num(top['abs_change']):+,.0f} requests)")

    net_pct = _num(current.get("net_pct_change"))
    if abs(net_pct) >= policy.net_pct_threshold:
        triggers.append("net_shift")
        reasons.append(f"citywide net change {net_pct:+.1f}% vs the length-normalised "
                       f"baseline (threshold {policy.net_pct_threshold:.1f}%)")

    for entry in current["top"]:
        if abs(_num(entry.get("driver_day_pct_delta"))) >= policy.driver_pp_threshold:
            triggers.append("driver_share")
            reasons.append(
                f"{entry['cohort']} weather/holiday driver-day share moved "
                f"{_num(entry['driver_day_pct_delta']):+.1f} pp between the windows")
            break

    if previous is None:
        triggers.append("first_run")
        reasons.append("no previous run on record — sending the first baseline report")
    else:
        prev_top = [e.get("cohort") for e in (previous.get("top") or [])]
        curr_top = [e.get("cohort") for e in current["top"]]
        entered = [c for c in curr_top if c not in prev_top]
        if entered:
            triggers.append("driver_change")
            reasons.append("new cohort(s) in the top drivers: " + ", ".join(entered))
        elif curr_top and prev_top and curr_top[0] != prev_top[0]:
            triggers.append("driver_change")
            reasons.append(f"top driver changed from {prev_top[0]} to {curr_top[0]}")

    decision = AlertDecision(
        should_notify=bool(triggers),
        reasons=reasons,
        triggers=sorted(set(triggers)),
        fingerprint=current,
        previous=previous,
    )
    decision.headline = headline(decision, policy)
    return decision


def headline(decision: AlertDecision, policy: AlertPolicy | None = None) -> str:
    policy = policy or AlertPolicy()
    fp = decision.fingerprint
    net = _num(fp.get("net_abs_change"))
    sig = len(fp.get("significant") or [])
    if not decision.should_notify:
        return (f"No notable change: net {net:+,.0f} requests, "
                f"0 cohorts past the alert thresholds")
    lead = fp["top"][0]["cohort"] if fp.get("top") else "n/a"
    return (f"{net:+,.0f} requests net, {sig} significant cohort(s) at q < {policy.alpha}, "
            f"led by {lead}")


def render_reasons(decision: AlertDecision) -> str:
    if not decision.reasons:
        return "Nothing crossed the alert thresholds."
    return "\n".join(f"- {r}" for r in decision.reasons)
