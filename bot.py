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
DOC_PATH = os.environ.get("DOC_PATH", "/data/wedding.md")  # legacy markdown, migrated into notes
PLAN_PATH = os.environ.get("PLAN_PATH", "/data/plan.json")
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


# ---------------------------------------------------------------- shared plan

from plan import PlanStore, rupiah, render_page  # noqa: E402

_plan: "PlanStore | None" = None


def get_plan() -> PlanStore:
    """The shared income/expense ledger + notes, lazily opened."""
    global _plan
    if _plan is None:
        _plan = PlanStore(PLAN_PATH, legacy_md=DOC_PATH, title=DOC_TITLE)
    return _plan


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


def doc_url() -> str:
    if not DOC_PUBLIC_BASE:
        return "(doc link not configured)"
    tok = f"?token={DOC_TOKEN}" if DOC_TOKEN else ""
    return f"{DOC_PUBLIC_BASE}/doc{tok}"


def tool_doc_link() -> str:
    """Return the shareable link to the editable wedding plan."""
    return doc_url()


def tool_budget_summary() -> str:
    """Totals: income received/expected, expenses paid/planned, cash on hand, balance."""
    return get_plan().summary_text() + "\n\nlink: " + doc_url()


def tool_budget_list(kind: str = "", status: str = "") -> str:
    """List ledger entries, optionally filtered by kind (income|expense)/status."""
    return get_plan().entries_text(kind=kind.strip().lower(), status=status.strip().lower())


def tool_budget_add(kind: str, item: str, amount, status: str = "actual",
                    category: str = "", date: str = "") -> str:
    """Add one income or expense entry."""
    if kind not in ("income", "expense"):
        return "error: kind must be 'income' or 'expense'"
    if not item:
        return "error: item is required"
    e = get_plan().add(kind=kind, item=item, amount=amount, status=status,
                       category=category, date=date)
    return (f"ok, added [{e['id']}] {e['item']} {rupiah(e['amount'])} "
            f"({e['kind']}, {e['status']})" + "\n" + get_plan().summary_text())


def tool_budget_update(id: str, item: str = "", amount=None, kind: str = "",
                       status: str = "", category: str = "", date: str = "") -> str:
    """Update an entry by its id (get ids from budget_list)."""
    e = get_plan().update(id, item=item or None, amount=amount, kind=kind or None,
                          status=status or None, category=category or None, date=date or None)
    if not e:
        return f"error: no entry with id '{id}' (use budget_list to see ids)"
    return f"ok, updated [{e['id']}] {e['item']} {rupiah(e['amount'])} ({e['kind']}, {e['status']})"


def tool_budget_delete(id: str) -> str:
    """Delete an entry by id."""
    return f"ok, deleted {id}" if get_plan().delete(id) else f"error: no entry with id '{id}'"


def tool_notes_read() -> str:
    """Read the freeform notes attached to the plan."""
    return get_plan().read().get("notes", "").strip() or "(no notes yet)"


def tool_notes_append(text: str) -> str:
    """Append a line to the freeform notes."""
    p = get_plan()
    cur = p.read().get("notes", "")
    line = text.strip()
    if not line.startswith(("-", "#", "*")):
        line = "- " + line
    p.set_notes((cur.rstrip("\n") + "\n" + line).strip() + "\n")
    return "ok, note added"


TOOLS = {
    "get_current_time": tool_get_current_time,
    "calculate": tool_calculate,
    "web_search": tool_web_search,
    "doc_link": tool_doc_link,
    "budget_summary": tool_budget_summary,
    "budget_list": tool_budget_list,
    "budget_add": tool_budget_add,
    "budget_update": tool_budget_update,
    "budget_delete": tool_budget_delete,
    "notes_read": tool_notes_read,
    "notes_append": tool_notes_append,
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
            "name": "budget_summary",
            "description": "Totals of the wedding money plan: income already received, income still "
                           "expected, expenses paid, expenses planned, cash on hand, projected balance. "
                           "Use for 'berapa sisa budget', 'total pemasukan', 'how much do we have'.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "budget_list",
            "description": "List the ledger entries (with their ids). Filter by kind "
                           "(income|expense) and/or status (actual|expected).",
            "parameters": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": ["income", "expense"]},
                    "status": {"type": "string", "enum": ["actual", "expected"]},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "budget_add",
            "description": "Add one income or expense. status='actual' means already "
                           "received/paid; status='expected' means still coming / only planned. "
                           "Amount is in IDR; accept plain numbers like 5000000.",
            "parameters": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": ["income", "expense"]},
                    "item": {"type": "string", "description": "e.g. 'DP catering', 'amplop om Budi'"},
                    "amount": {"type": "integer"},
                    "status": {"type": "string", "enum": ["actual", "expected"]},
                    "category": {"type": "string"},
                    "date": {"type": "string", "description": "YYYY-MM-DD"},
                },
                "required": ["kind", "item", "amount"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "budget_update",
            "description": "Change an existing entry by id (call budget_list first to find the id). "
                           "Only pass the fields you want to change.",
            "parameters": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "item": {"type": "string"},
                    "amount": {"type": "integer"},
                    "kind": {"type": "string", "enum": ["income", "expense"]},
                    "status": {"type": "string", "enum": ["actual", "expected"]},
                    "category": {"type": "string"},
                    "date": {"type": "string"},
                },
                "required": ["id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "budget_delete",
            "description": "Delete a ledger entry by id.",
            "parameters": {
                "type": "object",
                "properties": {"id": {"type": "string"}},
                "required": ["id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "notes_read",
            "description": "Read the freeform wedding notes (non-money stuff: ideas, vendors, to-dos).",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "notes_append",
            "description": "Add a line to the freeform wedding notes.",
            "parameters": {
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "doc_link",
            "description": "Return the shareable web link to the editable wedding doc. "
                           "Use when asked for the doc link / where to edit it.",
            "parameters": {"type": "object", "properties": {}},
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
    get_plan()  # create/migrate the plan file up front

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
                page = render_page((q.get("token") or [""])[0], get_plan())
                return self._send(200, page, "text/html; charset=utf-8")
            if path == "/api/plan":
                if not self._token_ok(q):
                    return self._send(403, "forbidden")
                return self._send(200, json.dumps(get_plan().read(), ensure_ascii=False),
                                  "application/json; charset=utf-8")
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
            if path == "/api/plan":
                if not self._token_ok(q):
                    return self._send(403, "forbidden")
                try:
                    payload = json.loads(body or b"{}")
                except Exception:  # noqa: BLE001
                    return self._send(400, "bad json")
                get_plan().replace_all(payload.get("entries") or [], payload.get("notes"))
                return self._send(200, json.dumps(get_plan().read(), ensure_ascii=False),
                                  "application/json; charset=utf-8")
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
