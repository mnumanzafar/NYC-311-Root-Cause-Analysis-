"""Slack notification for each nightly export run.

Two transports, picked automatically:

1. **Incoming webhook** — set ``SLACK_WEBHOOK_URL``. Simplest option, no scopes.
2. **Web API** — set ``SLACK_BOT_TOKEN`` (``xoxb-…``) and ``SLACK_CHANNEL``
   (``#ops-311`` or a channel ID). Uses ``chat.postMessage``.

Both send the same Block Kit payload: status, window, headline numbers and a
link/path per generated artifact. ``dry_run=True`` builds and returns the exact
payload without opening a connection, which is what the tests assert against and
what ``--slack-dry-run`` prints.

Artifact links: when ``EXPORT_BASE_URL`` is set (a share, S3 or intranet prefix)
the file names are turned into clickable links; otherwise the absolute path is
posted as text, which is still what an analyst on the same file share needs.
"""
from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from pathlib import Path

log = logging.getLogger(__name__)

SLACK_POST_MESSAGE = "https://slack.com/api/chat.postMessage"
STATUS_EMOJI = {"success": ":white_check_mark:", "warning": ":warning:",
                "failure": ":rotating_light:", "skipped": ":zzz:"}


def is_configured() -> bool:
    return bool(os.getenv("SLACK_WEBHOOK_URL")
                or (os.getenv("SLACK_BOT_TOKEN") and os.getenv("SLACK_CHANNEL")))


def artifact_link(path, base_url: str | None = None) -> str:
    """Slack mrkdwn for one artifact — a link when a base URL exists, else the path."""
    p = Path(path)
    base = base_url if base_url is not None else os.getenv("EXPORT_BASE_URL")
    if base:
        return f"<{base.rstrip('/')}/{p.name}|{p.name}>"
    return f"`{p}`"


def build_message(*, status: str, headline: str, window_label: str = "",
                  scope: str = "", files: dict | None = None,
                  reasons: str = "", error: str = "",
                  duration_s: float | None = None,
                  base_url: str | None = None,
                  title: str = "NYC 311 nightly cohort export") -> dict:
    """Block Kit payload shared by both transports."""
    emoji = STATUS_EMOJI.get(status, ":information_source:")
    fields = []
    if scope:
        fields.append({"type": "mrkdwn", "text": f"*Scope*\n{scope}"})
    if window_label:
        fields.append({"type": "mrkdwn", "text": f"*Windows*\n{window_label}"})
    if duration_s is not None:
        fields.append({"type": "mrkdwn", "text": f"*Duration*\n{duration_s:,.1f}s"})
    fields.append({"type": "mrkdwn", "text": f"*Status*\n{status}"})

    blocks: list[dict] = [
        {"type": "header",
         "text": {"type": "plain_text", "text": f"{emoji} {title}", "emoji": True}},
    ]
    if headline:
        blocks.append({"type": "section",
                       "text": {"type": "mrkdwn", "text": headline}})
    blocks.append({"type": "section", "fields": fields[:10]})

    if error:
        blocks.append({"type": "section",
                       "text": {"type": "mrkdwn",
                                "text": f"*Error*\n```{error[:2500]}```"}})
    if reasons:
        blocks.append({"type": "section",
                       "text": {"type": "mrkdwn", "text": f"*Why this fired*\n{reasons}"}})

    order = ["csv", "pdf", "xlsx", "narrative"]
    items = sorted((files or {}).items(), key=lambda kv: (order + [kv[0]]).index(kv[0])
                   if kv[0] in order else len(order))
    if items:
        listing = "\n".join(f"• *{kind.upper()}* — {artifact_link(path, base_url)}"
                            for kind, path in items)
        blocks.append({"type": "section",
                       "text": {"type": "mrkdwn", "text": f"*Files*\n{listing}"}})

    text = f"{emoji} {title}: {status}" + (f" — {headline}" if headline else "")
    return {"text": text, "blocks": blocks}


def _post(url: str, payload: dict, headers: dict, timeout: int = 30) -> dict:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as response:   # noqa: S310 - fixed hosts
        body = response.read().decode() or ""
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        parsed = {"ok": body.strip().lower() == "ok", "raw": body[:500]}
    return parsed


def notify(*, status: str, headline: str = "", window_label: str = "",
           scope: str = "", files: dict | None = None, reasons: str = "",
           error: str = "", duration_s: float | None = None,
           channel: str | None = None, dry_run: bool = False,
           base_url: str | None = None) -> dict:
    """Send the run summary to Slack. Never raises — a Slack outage is not a job failure."""
    payload = build_message(status=status, headline=headline, window_label=window_label,
                            scope=scope, files=files, reasons=reasons, error=error,
                            duration_s=duration_s, base_url=base_url)
    webhook = os.getenv("SLACK_WEBHOOK_URL")
    token = os.getenv("SLACK_BOT_TOKEN")
    target = channel or os.getenv("SLACK_CHANNEL")
    transport = "webhook" if webhook else ("web_api" if token and target else None)
    result: dict = {"sent": False, "dry_run": dry_run, "transport": transport,
                    "channel": target, "payload": payload}

    if transport is None:
        result["skipped"] = ("Slack is not configured — set SLACK_WEBHOOK_URL, or "
                             "SLACK_BOT_TOKEN together with SLACK_CHANNEL")
        log.info("slack notification skipped: %s", result["skipped"])
        return result
    if dry_run:
        log.info("slack dry-run via %s: %s", transport, payload["text"])
        return result

    try:
        if transport == "webhook":
            response = _post(webhook, payload, {"Content-Type": "application/json"})
        else:
            response = _post(SLACK_POST_MESSAGE, {**payload, "channel": target},
                             {"Content-Type": "application/json; charset=utf-8",
                              "Authorization": f"Bearer {token}"})
        result["response"] = {k: response.get(k) for k in ("ok", "error", "ts", "channel")
                              if k in response}
        result["sent"] = bool(response.get("ok", True))
        if not result["sent"]:
            result["error"] = response.get("error", "unknown Slack error")
            log.error("slack rejected the message: %s", result["error"])
    except (urllib.error.URLError, OSError, TimeoutError) as exc:   # network problems
        result["error"] = f"{type(exc).__name__}: {exc}"
        log.error("slack notification failed: %s", result["error"])
    return result
