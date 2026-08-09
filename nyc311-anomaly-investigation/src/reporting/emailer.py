"""E-mail delivery of the generated cohort exports.

Credentials and the recipient list come from the environment / ``config.yaml``
so nothing sensitive is committed:

    SMTP_HOST, SMTP_PORT (587), SMTP_USER, SMTP_PASSWORD, SMTP_STARTTLS (true)
    EXPORT_EMAIL_FROM, EXPORT_EMAIL_TO  (comma-separated), EXPORT_EMAIL_CC

``send_exports(..., dry_run=True)`` builds and returns the message without
touching the network — used by the tests and by ``--email-dry-run``.
"""
from __future__ import annotations

import logging
import mimetypes
import os
import re
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path

log = logging.getLogger(__name__)

MAX_ATTACHMENT_MB = 20.0


def parse_recipients(value) -> list[str]:
    """Accept a list, or a comma/semicolon/whitespace separated string."""
    if not value:
        return []
    items = value if isinstance(value, (list, tuple)) else re.split(r"[,;\s]+", str(value))
    seen: list[str] = []
    for item in items:
        addr = str(item).strip().strip("<>")
        if addr and "@" in addr and addr not in seen:
            seen.append(addr)
    return seen


@dataclass
class SMTPSettings:
    host: str
    port: int = 587
    user: str | None = None
    password: str | None = None
    starttls: bool = True
    sender: str | None = None

    @classmethod
    def from_env(cls, defaults: dict | None = None) -> "SMTPSettings":
        d = defaults or {}
        host = os.getenv("SMTP_HOST") or d.get("host")
        if not host:
            raise RuntimeError(
                "SMTP_HOST is not set — configure SMTP_HOST/SMTP_USER/SMTP_PASSWORD "
                "in .env (see .env.example) or pass --no-email.")
        return cls(
            host=host,
            port=int(os.getenv("SMTP_PORT") or d.get("port") or 587),
            user=os.getenv("SMTP_USER") or d.get("user"),
            password=os.getenv("SMTP_PASSWORD"),
            starttls=str(os.getenv("SMTP_STARTTLS", d.get("starttls", "true"))).lower()
            not in ("0", "false", "no"),
            sender=(os.getenv("EXPORT_EMAIL_FROM") or d.get("sender")
                    or os.getenv("SMTP_USER") or d.get("user")),
        )


def build_message(paths, recipients: list[str], *, sender: str, subject: str,
                  body_text: str, body_markdown: str | None = None,
                  cc: list[str] | None = None) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    if cc:
        msg["Cc"] = ", ".join(cc)
    msg["Subject"] = subject
    msg.set_content(body_text)
    if body_markdown:
        html = ("<html><body style=\"font-family:Segoe UI,Arial,sans-serif;font-size:13px\">"
                + _markdown_to_html(body_markdown) + "</body></html>")
        msg.add_alternative(html, subtype="html")

    total_mb = 0.0
    for path in paths:
        path = Path(path)
        if not path.exists():
            log.warning("attachment missing, skipped: %s", path)
            continue
        size_mb = path.stat().st_size / 1_048_576
        if total_mb + size_mb > MAX_ATTACHMENT_MB:
            log.warning("attachment %s skipped: would exceed %.0f MB limit",
                        path.name, MAX_ATTACHMENT_MB)
            continue
        total_mb += size_mb
        ctype, _ = mimetypes.guess_type(path.name)
        maintype, _, subtype = (ctype or "application/octet-stream").partition("/")
        msg.add_attachment(path.read_bytes(), maintype=maintype, subtype=subtype,
                           filename=path.name)
    return msg


def _markdown_to_html(text: str) -> str:
    out = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("###"):
            out.append(f"<h4>{line.lstrip('# ')}</h4>")
        elif line.startswith("##"):
            out.append(f"<h3>{line.lstrip('# ')}</h3>")
        elif line.startswith("#"):
            out.append(f"<h2>{line.lstrip('# ')}</h2>")
        elif line.startswith(("- ", "* ")):
            out.append(f"<li>{_inline(line[2:])}</li>")
        else:
            out.append(f"<p>{_inline(line)}</p>")
    return "".join(out)


def _inline(text: str) -> str:
    return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)


def send_exports(paths, recipients=None, *, subject: str,
                 body_text: str, body_markdown: str | None = None,
                 cc=None, settings: SMTPSettings | None = None,
                 dry_run: bool = False) -> dict:
    """Attach the export files and mail them to the recipient list."""
    to = parse_recipients(recipients if recipients is not None
                          else os.getenv("EXPORT_EMAIL_TO"))
    cc_list = parse_recipients(cc if cc is not None else os.getenv("EXPORT_EMAIL_CC"))
    if not to:
        raise ValueError("no recipients — pass --email-to or set EXPORT_EMAIL_TO")

    if dry_run:
        sender = (settings.sender if settings else None) or \
            os.getenv("EXPORT_EMAIL_FROM") or "nyc311-bot@localhost"
        msg = build_message(paths, to, sender=sender, subject=subject,
                            body_text=body_text, body_markdown=body_markdown, cc=cc_list)
        return {"sent": False, "dry_run": True, "to": to, "cc": cc_list,
                "attachments": [Path(p).name for p in paths], "message": msg}

    settings = settings or SMTPSettings.from_env()
    sender = settings.sender or settings.user or "nyc311-bot@localhost"
    msg = build_message(paths, to, sender=sender, subject=subject,
                        body_text=body_text, body_markdown=body_markdown, cc=cc_list)
    with smtplib.SMTP(settings.host, settings.port, timeout=60) as smtp:
        if settings.starttls:
            smtp.starttls()
        if settings.user and settings.password:
            smtp.login(settings.user, settings.password)
        smtp.send_message(msg, to_addrs=to + cc_list)
    log.info("emailed %d attachment(s) to %s", len(list(paths)), ", ".join(to))
    return {"sent": True, "dry_run": False, "to": to, "cc": cc_list,
            "attachments": [Path(p).name for p in paths]}
