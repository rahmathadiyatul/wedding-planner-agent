"""Email reminders for to-dos, sent through Brevo's transactional API.

Everything here is best-effort: with no BREVO_API_KEY the module reports
itself as disabled and the scheduler simply never sends anything, so the
bot runs fine without mail configured.

Two transports, both Brevo. The HTTPS API is preferred because it rides port
443, which no host blocks; SMTP needs outbound 587, which Hetzner (and most
cloud providers) blocks by default on new accounts. Set either one -- if both
are configured the API wins, and SMTP is tried as a fallback when it fails.

Config (all from the environment -- see env.example):

  BREVO_API_KEY        Brevo v3 API key ("xkeysib-...").
  SMTP_HOST/PORT       Brevo relay, e.g. smtp-relay.brevo.com : 587.
  SMTP_LOGIN           The relay login ("86dee1001@smtp-brevo.com").
  SMTP_PASSWORD        The SMTP key from Brevo -- NOT your account password.
  MAIL_FROM_EMAIL      Sender address. Must be a verified sender in Brevo.
  MAIL_FROM_NAME       Sender display name.
  MAIL_PEOPLE          Address book: "rahmat:a@x.com,dian:b@y.com". The keys
                       are what you (or the bot) type as a recipient.
  MAIL_TO_DEFAULT      Who gets a reminder when a to-do names nobody.
  REMIND_DEFAULT_LEAD  How far ahead to warn by default: 15m / 2h / 1d / 1w.
  REMIND_DEFAULT_TIME  Time of day a dateless-but-dated to-do is due (HH:MM).
  REMIND_POLL_SECONDS  How often the scheduler wakes up.
  TIMEZONE             IANA zone the due dates are written in.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

BREVO_URL = "https://api.brevo.com/v3/smtp/email"

BREVO_API_KEY = os.environ.get("BREVO_API_KEY", "").strip()
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp-relay.brevo.com").strip()
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_LOGIN = os.environ.get("SMTP_LOGIN", "").strip()
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "").strip()
MAIL_FROM_EMAIL = os.environ.get("MAIL_FROM_EMAIL", "").strip()
MAIL_FROM_NAME = os.environ.get("MAIL_FROM_NAME", "Wedding Planner").strip()
MAIL_TO_DEFAULT = os.environ.get("MAIL_TO_DEFAULT", "").strip()
REMIND_DEFAULT_LEAD = os.environ.get("REMIND_DEFAULT_LEAD", "1d").strip()
REMIND_DEFAULT_TIME = os.environ.get("REMIND_DEFAULT_TIME", "09:00").strip()
REMIND_POLL_SECONDS = int(os.environ.get("REMIND_POLL_SECONDS", "60"))
REMIND_ENABLED = os.environ.get("REMIND_ENABLED", "true").strip().lower() not in ("0", "false", "no")
TIMEZONE = os.environ.get("TIMEZONE", "Asia/Jakarta").strip()
MAIL_TIMEOUT = float(os.environ.get("MAIL_TIMEOUT", "20"))


def tz():
    """The configured zone, falling back to UTC if tzdata is missing."""
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(TIMEZONE)
    except Exception:  # noqa: BLE001
        return timezone.utc


def people() -> dict[str, str]:
    """name -> email, parsed from MAIL_PEOPLE."""
    out: dict[str, str] = {}
    for part in os.environ.get("MAIL_PEOPLE", "").split(","):
        part = part.strip()
        if not part:
            continue
        key, _, addr = part.partition(":")
        key, addr = key.strip(), addr.strip()
        if key and addr:
            out[key.lower()] = addr
    return out


def has_api() -> bool:
    return bool(BREVO_API_KEY)


def has_smtp() -> bool:
    return bool(SMTP_HOST and SMTP_LOGIN and SMTP_PASSWORD)


def enabled() -> bool:
    return bool(REMIND_ENABLED and MAIL_FROM_EMAIL and (has_api() or has_smtp()))


def why_disabled() -> str:
    if not REMIND_ENABLED:
        return "REMIND_ENABLED is off"
    if not (has_api() or has_smtp()):
        return "no transport: set BREVO_API_KEY, or SMTP_LOGIN + SMTP_PASSWORD"
    if not MAIL_FROM_EMAIL:
        return "MAIL_FROM_EMAIL not set"
    return ""


def transport() -> str:
    if has_api():
        return "api" + ("+smtp" if has_smtp() else "")
    return "smtp" if has_smtp() else "none"


# --------------------------------------------------------------- lead times

_UNITS = {
    "m": "m", "min": "m", "mins": "m", "menit": "m", "minute": "m", "minutes": "m",
    "h": "h", "hr": "h", "hrs": "h", "jam": "h", "hour": "h", "hours": "h",
    "d": "d", "day": "d", "days": "d", "hari": "d",
    "w": "w", "week": "w", "weeks": "w", "minggu": "w",
}
_SECONDS = {"m": 60, "h": 3600, "d": 86400, "w": 604800}


def parse_lead(spec: str) -> timedelta | None:
    """'15m' / '2 jam' / '1d' / '1 minggu' -> timedelta. 'off' or junk -> None."""
    s = str(spec or "").strip().lower()
    if not s or s in ("off", "none", "no", "-", "0"):
        return None
    m = re.fullmatch(r"(\d+)\s*([a-z]*)", s)
    if not m:
        return None
    n = int(m.group(1))
    unit = _UNITS.get(m.group(2) or "m")
    if not unit or n <= 0:
        return None
    return timedelta(seconds=n * _SECONDS[unit])


def fmt_lead(spec: str) -> str:
    """Human label for a lead, in Indonesian."""
    td = parse_lead(spec)
    if td is None:
        return "tidak diingatkan"
    secs = int(td.total_seconds())
    for unit, label, size in (("w", "minggu", 604800), ("d", "hari", 86400),
                              ("h", "jam", 3600), ("m", "menit", 60)):
        if secs % size == 0 and secs >= size:
            return f"{secs // size} {label} sebelumnya"
    return f"{secs // 60} menit sebelumnya"


# -------------------------------------------------------------- recipients

def resolve_recipients(spec: str) -> list[tuple[str, str]]:
    """'dian, rahmat' or raw addresses -> [(name, email)]. Unknown names are dropped."""
    book = people()
    raw = str(spec or "").strip() or MAIL_TO_DEFAULT
    out: list[tuple[str, str]] = []
    seen = set()
    for part in raw.replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        name, addr = part, book.get(part.lower(), "")
        if not addr and "@" in part:
            addr = part
            name = part.split("@")[0]
        if addr and addr.lower() not in seen:
            seen.add(addr.lower())
            out.append((name, addr))
    return out


# ------------------------------------------------------------------ sending

def send(to: list[tuple[str, str]], subject: str, html: str, text: str = "") -> tuple[bool, str]:
    """Send one mail over whichever transport is configured. Never raises.

    The HTTPS API is tried first (port 443 is never blocked); SMTP is the
    fallback, and the only path when no API key is set.
    """
    if not enabled():
        return False, f"email disabled: {why_disabled()}"
    if not to:
        return False, "no recipients"
    if has_api():
        ok, detail = _send_api(to, subject, html, text)
        if ok or not has_smtp():
            return ok, detail
        ok2, detail2 = _send_smtp(to, subject, html, text)
        return ok2, (f"smtp fallback ok (api said: {detail})" if ok2
                     else f"api: {detail} | smtp: {detail2}")
    return _send_smtp(to, subject, html, text)


def _send_smtp(to: list[tuple[str, str]], subject: str, html: str,
               text: str = "") -> tuple[bool, str]:
    import smtplib
    from email.message import EmailMessage
    from email.utils import formataddr

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr((MAIL_FROM_NAME, MAIL_FROM_EMAIL))
    msg["To"] = ", ".join(formataddr((n, e)) for n, e in to)
    msg.set_content(text or "Lihat versi HTML.")
    msg.add_alternative(html, subtype="html")
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=MAIL_TIMEOUT) as s:
            s.starttls()
            s.login(SMTP_LOGIN, SMTP_PASSWORD)
            s.send_message(msg)
        return True, f"smtp {SMTP_HOST}:{SMTP_PORT}"
    except Exception as e:  # noqa: BLE001
        return False, repr(e)


def _send_api(to: list[tuple[str, str]], subject: str, html: str,
              text: str = "") -> tuple[bool, str]:
    body = {
        "sender": {"email": MAIL_FROM_EMAIL, "name": MAIL_FROM_NAME},
        "to": [{"email": e, "name": n} for n, e in to],
        "subject": subject,
        "htmlContent": html,
    }
    if text:
        body["textContent"] = text
    req = urllib.request.Request(
        BREVO_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={"api-key": BREVO_API_KEY, "content-type": "application/json",
                 "accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=MAIL_TIMEOUT) as r:
            raw = r.read().decode("utf-8", "replace")
        return True, raw[:200]
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        return False, f"HTTP {e.code}: {detail}"
    except Exception as e:  # noqa: BLE001
        return False, repr(e)


# -------------------------------------------------------------- due + email

def due_at(task: dict) -> datetime | None:
    """When a to-do is due, as an aware datetime, or None if it has no date."""
    d = str(task.get("due") or "").strip()
    if not d:
        return None
    t = str(task.get("time") or "").strip() or REMIND_DEFAULT_TIME
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H.%M"):
        try:
            return datetime.strptime(f"{d} {t}", fmt).replace(tzinfo=tz())
        except ValueError:
            continue
    try:
        return datetime.strptime(d, "%Y-%m-%d").replace(tzinfo=tz())
    except ValueError:
        return None


def esc(s) -> str:
    return (str(s if s is not None else "")
            .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


_STATUS = {"todo": ("Rencana", "#6b7280"), "doing": ("Proses", "#2f6df6"),
           "done": ("Selesai", "#39d98a")}


def reminder_body(task: dict, kids: list[dict], when: datetime, lead: str,
                  doc_link: str = "") -> tuple[str, str, str]:
    """(subject, html, text) for one to-do's reminder."""
    title = task.get("title") or "(tanpa judul)"
    label, colour = _STATUS.get(task.get("status") or "todo", _STATUS["todo"])
    stamp = when.strftime("%A, %d %B %Y, %H:%M")
    subject = f"Pengingat: {title} ({fmt_lead(lead)})"

    rows = ""
    for k in kids:
        mark = "&#9745;" if k.get("status") == "done" else "&#9744;"
        rows += (f'<li style="margin:3px 0;color:#444">{mark} {esc(k.get("title"))}</li>')
    checklist = f'<ul style="padding-left:18px;margin:8px 0">{rows}</ul>' if rows else ""
    note = (f'<p style="margin:8px 0;color:#555;white-space:pre-wrap">{esc(task.get("detail"))}</p>'
            if task.get("detail") else "")
    cat = (f'<span style="background:#eef1f6;border-radius:999px;padding:2px 9px;'
           f'font-size:12px;color:#555">#{esc(task.get("category"))}</span>'
           if task.get("category") else "")
    link = (f'<p style="margin:16px 0 0"><a href="{esc(doc_link)}" '
            f'style="background:#2f6df6;color:#fff;text-decoration:none;padding:9px 16px;'
            f'border-radius:8px;display:inline-block;font-size:14px">Buka rencana</a></p>'
            if doc_link else "")

    html = f"""<div style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;max-width:520px">
  <p style="color:#777;font-size:13px;margin:0 0 4px">Pengingat {esc(fmt_lead(lead))}</p>
  <h2 style="margin:0 0 6px;font-size:19px;color:#111">{esc(title)}</h2>
  <p style="margin:4px 0 10px">
    <span style="background:{colour};color:#fff;border-radius:999px;padding:2px 9px;font-size:12px">{label}</span>
    {cat}
  </p>
  <p style="margin:6px 0;color:#111;font-size:15px"><b>{esc(stamp)}</b></p>
  {note}{checklist}{link}
</div>"""

    lines = [f"Pengingat {fmt_lead(lead)}", "", title, f"{label} - {stamp}"]
    if task.get("detail"):
        lines += ["", str(task["detail"])]
    for k in kids:
        lines.append(("[x] " if k.get("status") == "done" else "[ ] ") + str(k.get("title")))
    if doc_link:
        lines += ["", doc_link]
    return subject, html, "\n".join(lines)
