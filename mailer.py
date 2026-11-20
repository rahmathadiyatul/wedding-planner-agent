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


def env_people() -> dict[str, str]:
    """name -> email, parsed from MAIL_PEOPLE. Only a seed for first run."""
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


# --------------------------------------------------------------------------
# Config
#
# Secrets (the Brevo key, the SMTP password) come from the environment and
# never leave the server. Everything a human adjusts -- who is reminded, how
# far ahead, the sender -- is saved in plan.json and edited on the Settings
# screen, with the environment only supplying first-run defaults.
# --------------------------------------------------------------------------

def conf(saved: dict | None = None) -> dict:
    """Merge the saved settings over the environment defaults."""
    s = saved if isinstance(saved, dict) else {}

    people = {}
    for p in (s.get("people") or []):
        if isinstance(p, dict) and p.get("name") and p.get("email"):
            people[str(p["name"]).strip().lower()] = str(p["email"]).strip()
    if not people:
        people = env_people()

    return {
        "from_email": (s.get("from_email") or MAIL_FROM_EMAIL).strip(),
        "from_name": (s.get("from_name") or MAIL_FROM_NAME).strip(),
        "people": people,
        "default_to": (s.get("default_to") or MAIL_TO_DEFAULT).strip(),
        "lead": (s.get("default_lead") or REMIND_DEFAULT_LEAD).strip(),
        "time": (s.get("default_time") or REMIND_DEFAULT_TIME).strip(),
        "on": bool(s.get("enabled", True)) and REMIND_ENABLED,
    }


def has_api() -> bool:
    return bool(BREVO_API_KEY)


def has_smtp() -> bool:
    return bool(SMTP_HOST and SMTP_LOGIN and SMTP_PASSWORD)


def enabled(c: dict | None = None) -> bool:
    c = c or conf()
    return bool(c["on"] and c["from_email"] and (has_api() or has_smtp()))


def why_disabled(c: dict | None = None) -> str:
    c = c or conf()
    if not REMIND_ENABLED:
        return "REMIND_ENABLED is off in .env"
    if not c["on"]:
        return "dimatikan di Settings"
    if not (has_api() or has_smtp()):
        return "belum ada kredensial: isi BREVO_API_KEY atau SMTP_PASSWORD di .env"
    if not c["from_email"]:
        return "alamat pengirim belum diisi di Settings"
    return ""


def transport() -> str:
    if has_api():
        return "api" + ("+smtp" if has_smtp() else "")
    return "smtp" if has_smtp() else "none"


def web_config(saved: dict | None = None) -> dict:
    """What the Settings screen needs: the saved values plus computed status."""
    c = conf(saved)
    s = saved if isinstance(saved, dict) else {}
    return {
        "from_email": s.get("from_email", ""),
        "from_name": s.get("from_name", ""),
        # Saved people come back exactly as typed (capitals, order). The
        # lowercased map in conf() is only for matching names to addresses.
        "people": ([{"name": str(p.get("name") or ""), "email": str(p.get("email") or "")}
                    for p in (s.get("people") or []) if isinstance(p, dict) and p.get("name")]
                   or [{"name": n, "email": e} for n, e in sorted(c["people"].items())]),
        "default_to": s.get("default_to", ""),
        "default_lead": s.get("default_lead", ""),
        "default_time": s.get("default_time", ""),
        "enabled": bool(s.get("enabled", True)),
        # resolved values, for the hints in the UI
        "eff_lead": c["lead"], "eff_time": c["time"], "eff_to": c["default_to"],
        "eff_from": c["from_email"], "eff_from_name": c["from_name"],
        "leads": [l[0] for l in LEAD_CHOICES], "lead_labels": [l[1] for l in LEAD_CHOICES],
        "ready": enabled(c), "why": why_disabled(c),
        "transport": transport(), "has_secret": has_api() or has_smtp(),
        "tz": TIMEZONE,
    }


# --------------------------------------------------------------- lead times

_UNITS = {
    "m": "m", "min": "m", "mins": "m", "menit": "m", "minute": "m", "minutes": "m",
    "h": "h", "hr": "h", "hrs": "h", "jam": "h", "hour": "h", "hours": "h",
    "d": "d", "day": "d", "days": "d", "hari": "d",
    "w": "w", "week": "w", "weeks": "w", "minggu": "w",
}
_SECONDS = {"m": 60, "h": 3600, "d": 86400, "w": 604800}

# Offered in the Settings screen and in each to-do's reminder dropdown.
LEAD_CHOICES = [("15m", "15 menit"), ("30m", "30 menit"), ("1h", "1 jam"),
                ("3h", "3 jam"), ("6h", "6 jam"), ("12h", "12 jam"),
                ("1d", "1 hari"), ("2d", "2 hari"), ("3d", "3 hari"), ("1w", "1 minggu")]


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

def resolve_recipients(spec: str, c: dict | None = None) -> list[tuple[str, str]]:
    """'dian, rahmat' or raw addresses -> [(name, email)]. Unknown names dropped."""
    c = c or conf()
    book = c["people"]
    raw = str(spec or "").strip() or c["default_to"]
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

def send(to: list[tuple[str, str]], subject: str, html: str, text: str = "",
         c: dict | None = None) -> tuple[bool, str]:
    """Send one mail over whichever transport is configured. Never raises.

    The HTTPS API is tried first (port 443 is never blocked); SMTP is the
    fallback, and the only path when no API key is set.
    """
    c = c or conf()
    if not enabled(c):
        return False, f"email disabled: {why_disabled(c)}"
    if not to:
        return False, "no recipients"
    if has_api():
        ok, detail = _send_api(to, subject, html, text, c)
        if ok or not has_smtp():
            return ok, detail
        ok2, detail2 = _send_smtp(to, subject, html, text, c)
        return ok2, (f"smtp fallback ok (api said: {detail})" if ok2
                     else f"api: {detail} | smtp: {detail2}")
    return _send_smtp(to, subject, html, text)


def _send_smtp(to: list[tuple[str, str]], subject: str, html: str,
               text: str = "", c: dict | None = None) -> tuple[bool, str]:
    import smtplib
    from email.message import EmailMessage
    from email.utils import formataddr

    msg = EmailMessage()
    msg["Subject"] = subject
    c = c or conf()
    msg["From"] = formataddr((c["from_name"], c["from_email"]))
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
              text: str = "", c: dict | None = None) -> tuple[bool, str]:
    c = c or conf()
    body = {
        "sender": {"email": c["from_email"], "name": c["from_name"]},
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

def _at(day: str, hhmm: str, c: dict) -> datetime | None:
    day = str(day or "").strip()
    if not day:
        return None
    t = str(hhmm or "").strip() or c["time"]
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H.%M"):
        try:
            return datetime.strptime(f"{day} {t}", fmt).replace(tzinfo=tz())
        except ValueError:
            continue
    try:
        return datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=tz())
    except ValueError:
        return None


def due_at(task: dict, c: dict | None = None) -> datetime | None:
    """When a to-do starts, as an aware datetime, or None if it has no date."""
    return _at(task.get("due"), task.get("time"), c or conf())


def end_at(task: dict, c: dict | None = None) -> datetime | None:
    """The last day of a multi-day to-do, or None when it sits on one day."""
    c = c or conf()
    start = due_at(task, c)
    end = _at(task.get("due_end"), task.get("time"), c)
    if not start or not end or end <= start:
        return None
    return end


MAX_OCCURRENCES = 400          # a sanity cap on a mistyped range


def occurrences(task: dict, c: dict | None = None) -> list[tuple[datetime, str, int, int]]:
    """Every moment this to-do should be mailed about: (when, key, index, total).

    One date  -> a single reminder, `lead` ahead of it.
    A range   -> one reminder per day at the chosen hour, start to end. The
                 lead does not apply: "remind me daily at 9" is the point of
                 giving a range, and an extra offset would only blur it.

    `key` is what gets recorded in the task's `notified` field, so each day
    fires exactly once and a restart never repeats one.
    """
    c = c or conf()
    start = due_at(task, c)
    if not start:
        return []
    end = end_at(task, c)
    if end:
        out, cur, i = [], start, 0
        while cur <= end and i < MAX_OCCURRENCES:
            i += 1
            out.append((cur, f"{cur:%Y-%m-%d}|daily", i, 0))
            cur += timedelta(days=1)
        return [(w, k, n, len(out)) for w, k, n, _ in out]
    lead = task.get("remind") or c["lead"]
    td = parse_lead(lead)
    if td is None:
        return []
    send_at = start - td
    return [(send_at, f"{send_at:%Y-%m-%dT%H:%M}|{lead}", 1, 1)]


def esc(s) -> str:
    return (str(s if s is not None else "")
            .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


_STATUS = {"todo": ("Rencana", "#6b7280"), "doing": ("Proses", "#2f6df6"),
           "done": ("Selesai", "#39d98a")}


def reminder_body(task: dict, kids: list[dict], when: datetime, lead: str,
                  doc_link: str = "", index: int = 1, total: int = 1) -> tuple[str, str, str]:
    """(subject, html, text) for one to-do's reminder."""
    title = task.get("title") or "(tanpa judul)"
    label, colour = _STATUS.get(task.get("status") or "todo", _STATUS["todo"])
    stamp = when.strftime("%A, %d %B %Y, %H:%M")
    if total > 1:
        when_label = f"Hari ke-{index} dari {total}"
        subject = f"Pengingat harian: {title} (hari {index}/{total})"
    else:
        when_label = f"Pengingat {fmt_lead(lead)}"
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
  <p style="color:#777;font-size:13px;margin:0 0 4px">{esc(when_label)}</p>
  <h2 style="margin:0 0 6px;font-size:19px;color:#111">{esc(title)}</h2>
  <p style="margin:4px 0 10px">
    <span style="background:{colour};color:#fff;border-radius:999px;padding:2px 9px;font-size:12px">{label}</span>
    {cat}
  </p>
  <p style="margin:6px 0;color:#111;font-size:15px"><b>{esc(stamp)}</b></p>
  {note}{checklist}{link}
</div>"""

    lines = [when_label, "", title, f"{label} - {stamp}"]
    if task.get("detail"):
        lines += ["", str(task["detail"])]
    for k in kids:
        lines.append(("[x] " if k.get("status") == "done" else "[ ] ") + str(k.get("title")))
    if doc_link:
        lines += ["", doc_link]
    return subject, html, "\n".join(lines)
