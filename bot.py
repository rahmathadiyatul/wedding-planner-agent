#!/usr/bin/env python3
"""
WAHA group-chat LLM bot (throwaway test).

Polls one WhatsApp group via the WAHA HTTP API, and when a message starts with
the trigger prefix (default "@bot") it feeds the recent group history to an
OpenAI-compatible LLM, runs a small tool loop, and posts the reply back into
the group. No inbound webhook needed -- pure polling, so it works from any host
that can reach the WAHA API (e.g. procure-staging).

Config is all via env (see env.example). Single file, only dep is httpx.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import html
import threading
import datetime as dt
from typing import Any
from urllib.parse import urlparse, parse_qs

import httpx


def _load_dotenv(path: str = ".env") -> None:
    """Minimal .env loader (no dependency). Does not override real env vars."""
    here = os.path.join(os.path.dirname(os.path.abspath(__file__)), path)
    try:
        with open(here, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k, v = k.strip(), v.strip()
                if k and k not in os.environ:
                    os.environ[k] = v
    except FileNotFoundError:
        pass


_load_dotenv()

# ---------------------------------------------------------------- config

WAHA_BASE_URL = os.environ.get("WAHA_BASE_URL", "https://whatsapp-auto.ximplify.id").rstrip("/")
WAHA_API_KEY = os.environ.get("WAHA_API_KEY", "")
WAHA_SESSION = os.environ.get("WAHA_SESSION", "default")
GROUP_CHAT_ID = os.environ.get("GROUP_CHAT_ID", "")  # "<id>@g.us"; empty -> list groups and exit
TRIGGER_PREFIX = os.environ.get("TRIGGER_PREFIX", "@bot").strip()
POLL_INTERVAL = float(os.environ.get("POLL_INTERVAL", "4"))
HISTORY_LIMIT = int(os.environ.get("HISTORY_LIMIT", "20"))
REPLY_PREFIX = os.environ.get("REPLY_PREFIX", "🤖 ")

# LLM (OpenAI-compatible: litellm-prod, OpenAI, etc.)
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
LLM_MODEL = os.environ.get("LLM_MODEL", "gpt-4o-mini")
SYSTEM_PROMPT = os.environ.get(
    "SYSTEM_PROMPT",
    "You are a helpful assistant replying inside a WhatsApp group chat. "
    "Keep answers short and plain-text (no markdown). You can call tools when useful.",
)

HTTP_TIMEOUT = float(os.environ.get("HTTP_TIMEOUT", "30"))

# Mode: "poll" (default; works anywhere that can reach WAHA) or "webhook"
# (WAHA pushes to us -- real-time, but needs a public URL WAHA can POST to, set
# via PUBLIC_WEBHOOK_URL). Note: webhooks ride the same WhatsApp receive stream
# as polling, so neither survives a WAHA/GOWS backend hang.
BOT_MODE = os.environ.get("BOT_MODE", "poll").strip().lower()
WEBHOOK_HOST = os.environ.get("WEBHOOK_HOST", "0.0.0.0")
WEBHOOK_PORT = int(os.environ.get("WEBHOOK_PORT", "8080"))
WEBHOOK_PATH = os.environ.get("WEBHOOK_PATH", "/webhook")
# message.any includes OUR OWN messages (fromMe) -- needed because triggers come
# from the linked number itself. Set to "message" to only react to others.
WEBHOOK_EVENTS = [e.strip() for e in os.environ.get("WEBHOOK_EVENTS", "message.any").split(",") if e.strip()]

# Shared wedding doc (self-hosted). Lives on a volume; served as a mobile web
# page + edited by the bot's tools. DOC_TOKEN gates every public route.
DOC_PATH = os.environ.get("DOC_PATH", "/data/wedding.md")
DOC_TOKEN = os.environ.get("DOC_TOKEN", "")
DOC_PUBLIC_BASE = os.environ.get("DOC_PUBLIC_BASE", "").rstrip("/")  # e.g. http://1.2.3.4:8080
DOC_TITLE = os.environ.get("DOC_TITLE", "Wedding Plan")


def log(*a: Any) -> None:
    print(dt.datetime.now().strftime("%H:%M:%S"), *a, flush=True)


# ---------------------------------------------------------------- WAHA client

class Waha:
    def __init__(self, base_url: str, api_key: str, session: str) -> None:
        self.base_url = base_url
        self.session = session
        self._c = httpx.Client(
            base_url=base_url,
            headers={"x-api-key": api_key, "accept": "application/json"},
            timeout=HTTP_TIMEOUT,
        )

    def _request(self, method: str, path: str, json: dict | None = None):
        r = self._c.request(method, path, json=json)
        r.raise_for_status()
        return r.json() if r.content else None

    def version(self) -> dict:
        return self._c.get("/api/version").raise_for_status().json()

    def session_status(self) -> str | None:
        r = self._c.get(f"/api/sessions/{self.session}")
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return (r.json() or {}).get("status")

    def ensure_session_started(self) -> None:
        """Create the session if missing, then start it (idempotent)."""
        st = self.session_status()
        if st is None:
            self._c.post("/api/sessions", json={"name": self.session, "start": True})
            return
        if st in ("STOPPED", "FAILED"):
            self._c.post(f"/api/sessions/{self.session}/start", json={})

    def get_qr_png(self) -> bytes:
        r = self._c.get(f"/api/{self.session}/auth/qr", headers={"accept": "image/png"})
        r.raise_for_status()
        return r.content

    def list_groups(self) -> list[dict]:
        r = self._c.get(f"/api/{self.session}/groups")
        r.raise_for_status()
        return r.json()

    def get_messages(self, chat_id: str, limit: int) -> list[dict]:
        r = self._c.get(
            f"/api/{self.session}/chats/{chat_id}/messages",
            params={"limit": limit, "downloadMedia": "false"},
        )
        r.raise_for_status()
        return r.json()

    def send_text(self, chat_id: str, text: str) -> dict:
        r = self._c.post(
            "/api/sendText",
            json={"session": self.session, "chatId": chat_id, "text": text},
        )
        r.raise_for_status()
        return r.json()


# ---------------------------------------------------------------- shared doc

class DocStore:
    """A single shared Markdown doc, edited by both the web page and the bot.
    One in-process lock serializes every read/modify/write, so human saves and
    tool edits can't clobber each other."""

    def __init__(self, path: str) -> None:
        self.path = path
        self._lock = threading.Lock()
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        if not os.path.exists(path):
            self._write_locked(f"# {DOC_TITLE}\n\n## To-dos\n\n## Budget\n\n## Guests\n\n## Vendors\n\n## Notes\n")

    def _write_locked(self, text: str) -> None:
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, self.path)

    def read(self) -> str:
        with self._lock:
            try:
                with open(self.path, encoding="utf-8") as fh:
                    return fh.read()
            except FileNotFoundError:
                return ""

    def overwrite(self, text: str) -> None:
        with self._lock:
            self._write_locked(text if text.endswith("\n") else text + "\n")

    def append(self, text: str, section: str | None = None) -> None:
        with self._lock:
            try:
                with open(self.path, encoding="utf-8") as fh:
                    doc = fh.read()
            except FileNotFoundError:
                doc = ""
            line = text.strip()
            if not line.startswith(("-", "*", "#")):
                line = "- " + line
            if section:
                doc = _upsert_section(doc, section, _section_body(doc, section) + line + "\n", append=True, new_line=line)
            else:
                doc = doc.rstrip("\n") + "\n" + line + "\n"
            self._write_locked(doc)

    def set_section(self, section: str, body: str) -> None:
        with self._lock:
            try:
                with open(self.path, encoding="utf-8") as fh:
                    doc = fh.read()
            except FileNotFoundError:
                doc = ""
            self._write_locked(_upsert_section(doc, section, body.rstrip("\n") + "\n"))


def _section_body(doc: str, section: str) -> str:
    lines = doc.splitlines(keepends=True)
    out, grab = [], False
    for ln in lines:
        if ln.startswith("## "):
            if grab:
                break
            grab = ln[3:].strip().lower() == section.strip().lower()
            continue
        if grab:
            out.append(ln)
    return "".join(out)


def _upsert_section(doc: str, section: str, body: str, append: bool = False, new_line: str = "") -> str:
    """Replace the `## section` block with body, or add the section if missing."""
    lines = doc.splitlines(keepends=True)
    out, i, found = [], 0, False
    while i < len(lines):
        ln = lines[i]
        if ln.startswith("## ") and ln[3:].strip().lower() == section.strip().lower():
            found = True
            out.append(ln)
            i += 1
            # skip old body until next section
            while i < len(lines) and not lines[i].startswith("## "):
                i += 1
            if not body.startswith("\n"):
                out.append("\n")
            out.append(body if body.endswith("\n") else body + "\n")
            out.append("\n")
            continue
        out.append(ln)
        i += 1
    if not found:
        doc2 = "".join(out).rstrip("\n") + f"\n\n## {section}\n\n{body.rstrip(chr(10))}\n"
        return doc2
    return "".join(out)


_doc: "DocStore | None" = None


def get_doc() -> DocStore:
    global _doc
    if _doc is None:
        _doc = DocStore(DOC_PATH)
    return _doc


# ---------------------------------------------------------------- tools

def tool_get_current_time(timezone: str = "Asia/Jakarta") -> str:
    try:
        from zoneinfo import ZoneInfo
        now = dt.datetime.now(ZoneInfo(timezone))
    except Exception:
        now = dt.datetime.utcnow()
        timezone = "UTC"
    return f"{now:%Y-%m-%d %H:%M:%S} {timezone}"


def tool_calculate(expression: str) -> str:
    # Safe arithmetic only: digits, operators, parens, spaces, dot.
    if not re.fullmatch(r"[0-9+\-*/().%\s]+", expression or ""):
        return "error: only basic arithmetic is allowed"
    try:
        return str(eval(expression, {"__builtins__": {}}, {}))  # noqa: S307 - gated above
    except Exception as e:  # noqa: BLE001
        return f"error: {e}"


def tool_web_search(query: str, max_results: int = 5) -> str:
    """Search the web via Tavily and return an answer + top sources."""
    key = os.environ.get("TAVILY_API_KEY", "")
    if not key:
        return "error: web search not configured (TAVILY_API_KEY missing)"
    try:
        resp = httpx.post(
            "https://api.tavily.com/search",
            json={
                "api_key": key,
                "query": query,
                "max_results": max(1, min(int(max_results), 10)),
                "search_depth": "basic",
                "include_answer": True,
            },
            timeout=HTTP_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:  # noqa: BLE001
        return f"error: web search failed ({e})"
    lines = []
    if data.get("answer"):
        lines.append(f"Answer: {data['answer']}")
    for r in (data.get("results") or [])[:max_results]:
        title = (r.get("title") or "").strip()
        url = r.get("url") or ""
        snippet = (r.get("content") or "").strip().replace("\n", " ")[:200]
        lines.append(f"- {title} ({url}): {snippet}")
    return "\n".join(lines) or "no results"


def tool_doc_read(section: str = "") -> str:
    """Read the shared wedding doc (whole thing, or one section)."""
    doc = get_doc().read()
    if section:
        body = _section_body(doc, section).strip()
        return f"## {section}\n{body}" if body else f"(section '{section}' is empty)"
    return doc.strip() or "(the doc is empty)"


def tool_doc_edit(mode: str, content: str, section: str = "") -> str:
    """Edit the shared wedding doc. mode: append | set_section | overwrite."""
    d = get_doc()
    mode = (mode or "").strip().lower()
    try:
        if mode == "append":
            d.append(content, section or None)
        elif mode == "set_section":
            if not section:
                return "error: set_section needs a section name"
            d.set_section(section, content)
        elif mode == "overwrite":
            d.overwrite(content)
        else:
            return "error: mode must be append, set_section, or overwrite"
    except Exception as e:  # noqa: BLE001
        return f"error: {e}"
    link = f" ({DOC_PUBLIC_BASE}/doc?token=...)" if DOC_PUBLIC_BASE else ""
    return f"ok, doc updated{link}"


TOOLS = {
    "get_current_time": tool_get_current_time,
    "calculate": tool_calculate,
    "web_search": tool_web_search,
    "doc_read": tool_doc_read,
    "doc_edit": tool_doc_edit,
}

TOOL_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "get_current_time",
            "description": "Get the current date and time in a timezone.",
            "parameters": {
                "type": "object",
                "properties": {"timezone": {"type": "string", "description": "IANA tz, e.g. Asia/Jakarta"}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calculate",
            "description": "Evaluate a basic arithmetic expression.",
            "parameters": {
                "type": "object",
                "properties": {"expression": {"type": "string"}},
                "required": ["expression"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web for current or factual info. Use for news, "
                           "recent events, prices, or anything you are unsure about.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "max_results": {"type": "integer", "description": "1-10, default 5"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "doc_read",
            "description": "Read the couple's shared wedding-planning doc (Markdown). "
                           "Use when asked what's planned, the budget, guest list, to-dos, etc. "
                           "Optionally pass a section name to read just that part.",
            "parameters": {
                "type": "object",
                "properties": {
                    "section": {"type": "string", "description": "e.g. Budget, Guests, Vendors, To-dos, Notes"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "doc_edit",
            "description": "Update the shared wedding doc. Use when asked to add/change/record "
                           "anything about the wedding (a task, a cost, a guest, a vendor, a note). "
                           "mode='append' adds a line (optionally under a section); "
                           "mode='set_section' replaces a whole section; "
                           "mode='overwrite' replaces the entire doc (rare).",
            "parameters": {
                "type": "object",
                "properties": {
                    "mode": {"type": "string", "enum": ["append", "set_section", "overwrite"]},
                    "content": {"type": "string"},
                    "section": {"type": "string", "description": "section name for append/set_section"},
                },
                "required": ["mode", "content"],
            },
        },
    },
]


# ---------------------------------------------------------------- LLM

def llm_chat(messages: list[dict]) -> str:
    client = httpx.Client(
        base_url=LLM_BASE_URL,
        headers={"Authorization": f"Bearer {LLM_API_KEY}", "content-type": "application/json"},
        timeout=HTTP_TIMEOUT,
    )
    # Give the model today's date (so "this year"/"latest" resolve correctly) and
    # push it to verify time-sensitive facts with web_search instead of guessing.
    try:
        from zoneinfo import ZoneInfo
        now = dt.datetime.now(ZoneInfo(os.environ.get("TZ_NAME", "Asia/Jakarta")))
    except Exception:  # noqa: BLE001
        now = dt.datetime.utcnow()
    grounding = (
        f"Today's date is {now:%A, %d %B %Y}. "
        "When the user asks about 'this year', 'latest', recent news, scores, prices, "
        "or current events, call web_search first and answer from the results; "
        "do not rely on memory for anything time-sensitive."
    )
    convo = [{"role": "system", "content": SYSTEM_PROMPT + "\n\n" + grounding}] + messages
    for _ in range(5):  # cap tool-call rounds
        resp = client.post(
            "/chat/completions",
            json={"model": LLM_MODEL, "messages": convo, "tools": TOOL_SCHEMA},
        )
        resp.raise_for_status()
        msg = resp.json()["choices"][0]["message"]
        calls = msg.get("tool_calls") or []
        if not calls:
            text = (msg.get("content") or "").strip()
            # Defensive: strip a leading "[me]"/"[name]" tag if the model ever adds one.
            text = re.sub(r"^\[[^\]]{1,20}\]\s*", "", text)
            return text or "(no response)"
        convo.append(msg)
        for call in calls:
            fn = call["function"]["name"]
            try:
                args = json.loads(call["function"].get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            result = TOOLS[fn](**args) if fn in TOOLS else f"error: unknown tool {fn}"
            log(f"  tool {fn}({args}) -> {result}")
            convo.append({"role": "tool", "tool_call_id": call["id"], "content": str(result)})
    return "(stopped: too many tool calls)"


# ---------------------------------------------------------------- message helpers

def msg_text(m: dict) -> str:
    return (m.get("body") or m.get("text") or "").strip()


def build_history(messages: list[dict]) -> list[dict]:
    """Turn WAHA messages (oldest->newest) into LLM context.

    The bot sends as the SAME WhatsApp number the human types from, so `fromMe`
    cannot tell them apart -- everything would look like the assistant. Instead
    we identify the bot's own turns by the reply prefix; everything else is a
    user turn. Trigger/reply prefixes are stripped from the content.
    """
    rp = REPLY_PREFIX.strip()
    out = []
    for m in messages:
        t = msg_text(m)
        if not t:
            continue
        if rp and t.startswith(rp):
            role, content = "assistant", t[len(rp):].strip()
        else:
            role = "user"
            content = t[len(TRIGGER_PREFIX):].strip() if t.startswith(TRIGGER_PREFIX) else t
        if content:
            out.append({"role": role, "content": content})
    return out[-HISTORY_LIMIT:]


# ---------------------------------------------------------------- shared handling

_seen_ids: set[str] = set()


def _already_handled(mid: str | None) -> bool:
    """Idempotency guard so a message is answered at most once."""
    if not mid:
        return False
    if mid in _seen_ids:
        return True
    _seen_ids.add(mid)
    if len(_seen_ids) > 4000:
        _seen_ids.intersection_update(list(_seen_ids)[-2000:])
    return False


def handle_trigger(waha: "Waha", chat_id: str, prompt: str) -> None:
    """Fetch context, ask the LLM, and reply into the chat."""
    log("trigger:", prompt)
    history = []
    try:
        msgs = waha.get_messages(chat_id, HISTORY_LIMIT)
        if isinstance(msgs, list):
            history = build_history(msgs)
    except Exception as e:  # noqa: BLE001
        log("warn: history fetch failed:", e)
    # The triggering message is usually already the last history item; only add
    # it if it isn't, so we don't duplicate the current question.
    if not (history and history[-1]["role"] == "user" and history[-1]["content"] == prompt):
        history.append({"role": "user", "content": prompt})
    try:
        answer = llm_chat(history)
    except Exception as e:  # noqa: BLE001
        answer = f"(LLM error: {e})"
    log("reply:", answer[:120])
    try:
        waha.send_text(chat_id, REPLY_PREFIX + answer)
    except Exception as e:  # noqa: BLE001
        log("send error:", e)


def process_event(waha: "Waha", payload: dict) -> None:
    """Handle one WAHA message payload (webhook) or REST message (poll)."""
    if not isinstance(payload, dict):
        return
    mid = payload.get("id")
    if isinstance(mid, dict):
        mid = mid.get("_serialized") or mid.get("id")
    chat_id = payload.get("from") or payload.get("chatId") or GROUP_CHAT_ID
    text = msg_text(payload)
    if not text or not text.startswith(TRIGGER_PREFIX):
        return
    # Don't answer our own bot replies (they carry REPLY_PREFIX, not the trigger),
    # but guard anyway in case REPLY_PREFIX ever overlaps the trigger.
    if payload.get("fromMe") and text.startswith(REPLY_PREFIX.strip()):
        return
    if GROUP_CHAT_ID and chat_id != GROUP_CHAT_ID:
        return  # only our watched group
    if _already_handled(mid):
        return
    prompt = text[len(TRIGGER_PREFIX):].strip()
    handle_trigger(waha, chat_id, prompt)


# ---------------------------------------------------------------- webhook mode

def run_webhook(waha: "Waha") -> int:
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    base = os.environ.get("PUBLIC_WEBHOOK_URL", "").rstrip("/")
    if not base:
        log("FATAL: PUBLIC_WEBHOOK_URL not set (the URL WAHA should POST to, e.g. http://bot:8080)")
        return 2
    # Token guards every public route (incl. /webhook, since the port is exposed).
    qs = f"?token={DOC_TOKEN}" if DOC_TOKEN else ""
    hook_url = base + WEBHOOK_PATH + qs
    get_doc()  # create the doc file up front

    # Bring the session up and wait for it to link, so webhook registration sticks
    # even across reboots (QR scan happens out of band via /auth/qr).
    try:
        waha.ensure_session_started()
    except Exception as e:  # noqa: BLE001
        log("warn: ensure_session_started:", e)
    waited = 0
    while True:
        try:
            st = waha.session_status()
        except Exception as e:  # noqa: BLE001
            st = f"err:{e}"
        if st == "WORKING":
            break
        if waited % 15 == 0:
            log(f"waiting for session '{WAHA_SESSION}' to be WORKING (status={st}); scan the QR if prompted")
        time.sleep(3)
        waited += 3

    try:
        cfg = {"config": {"webhooks": [{"url": hook_url, "events": WEBHOOK_EVENTS}]}}
        waha._request("PUT", f"/api/sessions/{WAHA_SESSION}", json=cfg)
        log(f"registered webhook -> {hook_url} events={WEBHOOK_EVENTS}")
    except Exception as e:  # noqa: BLE001
        log("warn: could not register webhook:", e)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):  # silence default stderr logging
            pass

        # -- helpers --
        def _parsed(self):
            u = urlparse(self.path)
            return u.path, parse_qs(u.query)

        def _token_ok(self, q) -> bool:
            if not DOC_TOKEN:
                return True
            return (q.get("token") or [""])[0] == DOC_TOKEN

        def _send(self, code, body=b"", ctype="text/plain; charset=utf-8"):
            if isinstance(body, str):
                body = body.encode("utf-8")
            self.send_response(code)
            self.send_header("content-type", ctype)
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            try:
                self.wfile.write(body)
            except Exception:  # noqa: BLE001
                pass

        # -- routes --
        def do_GET(self):
            path, q = self._parsed()
            if path in ("/", "/healthz"):
                return self._send(200, "ok")
            if path == "/doc":
                if not self._token_ok(q):
                    return self._send(403, "forbidden")
                return self._send(200, _doc_page_html((q.get("token") or [""])[0]), "text/html; charset=utf-8")
            if path == "/doc/raw":
                if not self._token_ok(q):
                    return self._send(403, "forbidden")
                return self._send(200, get_doc().read(), "text/markdown; charset=utf-8")
            return self._send(404, "not found")

        def do_POST(self):
            path, q = self._parsed()
            n = int(self.headers.get("content-length", 0) or 0)
            body = self.rfile.read(n) if n else b""
            if path == WEBHOOK_PATH:
                self._send(200, "ok")  # ack fast
                if not self._token_ok(q):
                    return
                try:
                    data = json.loads(body or b"{}")
                except Exception:  # noqa: BLE001
                    return
                if data.get("event") in ("message", "message.any"):
                    threading.Thread(
                        target=lambda: _safe(process_event, waha, data.get("payload") or {}),
                        daemon=True,
                    ).start()
                return
            if path == "/doc":
                if not self._token_ok(q):
                    return self._send(403, "forbidden")
                from urllib.parse import parse_qs as _pq
                content = (_pq(body.decode("utf-8", "replace")).get("content") or [""])[0]
                get_doc().overwrite(content)
                tok = (q.get("token") or [""])[0]
                # redirect back to the viewer
                self.send_response(303)
                self.send_header("location", f"/doc?token={tok}&saved=1")
                self.end_headers()
                return
            return self._send(404, "not found")

    srv = ThreadingHTTPServer((WEBHOOK_HOST, WEBHOOK_PORT), Handler)
    doc_link = f"{DOC_PUBLIC_BASE}/doc?token={DOC_TOKEN}" if DOC_PUBLIC_BASE else f"(set DOC_PUBLIC_BASE) /doc?token={DOC_TOKEN}"
    log(f"webhook server on {WEBHOOK_HOST}:{WEBHOOK_PORT}{WEBHOOK_PATH}  (trigger='{TRIGGER_PREFIX}')")
    log(f"shared doc: {doc_link}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        log("bye")
    return 0


def _doc_page_html(token: str) -> str:
    content = get_doc().read()
    esc = html.escape(content)
    tok = html.escape(token)
    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(DOC_TITLE)}</title>
<style>
  :root {{ color-scheme: light dark; }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
         background:#0f1115; color:#e6e6e6; }}
  header {{ padding:14px 16px; background:#161a21; border-bottom:1px solid #262c36;
            display:flex; align-items:center; justify-content:space-between; gap:12px; }}
  header h1 {{ font-size:17px; margin:0; }}
  .wrap {{ max-width:820px; margin:0 auto; padding:16px; }}
  textarea {{ width:100%; min-height:62vh; padding:12px; font:14px/1.5 ui-monospace,Menlo,Consolas,monospace;
              background:#0b0d11; color:#e6e6e6; border:1px solid #2a313c; border-radius:10px; resize:vertical; }}
  .row {{ display:flex; gap:10px; align-items:center; margin-top:12px; }}
  button {{ background:#2f6df6; color:#fff; border:0; padding:11px 18px; border-radius:10px;
            font-size:15px; font-weight:600; }}
  .hint {{ color:#8b94a3; font-size:13px; }}
  .saved {{ color:#39d98a; font-size:14px; }}
</style></head>
<body>
  <header><h1>💍 {html.escape(DOC_TITLE)}</h1>
    <span class="hint">shared · edited by you, Princess &amp; @bang</span></header>
  <div class="wrap">
    <form method="POST" action="/doc?token={tok}">
      <textarea name="content" spellcheck="false">{esc}</textarea>
      <div class="row">
        <button type="submit">Save</button>
        <span class="hint">Markdown. Use <code>## Section</code> headings. Last save wins.</span>
        <span id="s" class="saved"></span>
      </div>
    </form>
  </div>
  <script>
    if (new URLSearchParams(location.search).get('saved')) {{
      document.getElementById('s').textContent = 'saved ✓';
    }}
  </script>
</body></html>"""


def _safe(fn, *a) -> None:
    try:
        fn(*a)
    except Exception as e:  # noqa: BLE001
        log("handler error:", e)


# ---------------------------------------------------------------- poll mode

def run_poll(waha: "Waha") -> int:
    log(f"polling {GROUP_CHAT_ID}, trigger='{TRIGGER_PREFIX}', every {POLL_INTERVAL}s")
    try:  # baseline so we only react to NEW messages
        for m in waha.get_messages(GROUP_CHAT_ID, HISTORY_LIMIT):
            if isinstance(m, dict):
                _already_handled(m.get("id"))
    except Exception as e:  # noqa: BLE001
        log("warn: baseline fetch failed:", e)

    while True:
        try:
            messages = waha.get_messages(GROUP_CHAT_ID, HISTORY_LIMIT)
        except Exception as e:  # noqa: BLE001
            log("poll error:", e)
            time.sleep(POLL_INTERVAL)
            continue
        if isinstance(messages, list):
            for m in messages:
                _safe(process_event, waha, m)
        else:
            log("poll: unexpected response:", str(messages)[:160])
        time.sleep(POLL_INTERVAL)


# ---------------------------------------------------------------- entrypoint

def main() -> int:
    if not WAHA_API_KEY:
        log("FATAL: WAHA_API_KEY not set")
        return 2
    waha = Waha(WAHA_BASE_URL, WAHA_API_KEY, WAHA_SESSION)
    try:
        log("WAHA version:", waha.version())
    except Exception as e:  # noqa: BLE001
        log("FATAL: cannot reach/auth WAHA:", e)
        return 2

    if not GROUP_CHAT_ID:
        log("GROUP_CHAT_ID not set -- listing groups so you can pick one:")
        for g in waha.list_groups():
            jid = g.get("JID") or g.get("id")
            if isinstance(jid, dict):
                jid = jid.get("_serialized")
            log("  ", jid, "|", (g.get("Name") or g.get("name") or g.get("subject") or "?"))
        return 0

    if not LLM_API_KEY:
        log("FATAL: LLM_API_KEY not set")
        return 2

    if BOT_MODE == "poll":
        return run_poll(waha)
    return run_webhook(waha)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        log("bye")
