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
import datetime as dt
from typing import Any

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

    def version(self) -> dict:
        return self._c.get("/api/version").raise_for_status().json()

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


TOOLS = {
    "get_current_time": tool_get_current_time,
    "calculate": tool_calculate,
    "web_search": tool_web_search,
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
]


# ---------------------------------------------------------------- LLM

def llm_chat(messages: list[dict]) -> str:
    client = httpx.Client(
        base_url=LLM_BASE_URL,
        headers={"Authorization": f"Bearer {LLM_API_KEY}", "content-type": "application/json"},
        timeout=HTTP_TIMEOUT,
    )
    convo = [{"role": "system", "content": SYSTEM_PROMPT}] + messages
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

    Sender names, when known, go in a `name` field (OpenAI-style) rather than
    inlined into the content, so the model doesn't learn to echo a `[who]` tag.
    """
    out = []
    for m in messages:
        t = msg_text(m)
        if not t:
            continue
        role = "assistant" if m.get("fromMe") else "user"
        out.append({"role": role, "content": t})
    return out[-HISTORY_LIMIT:]


# ---------------------------------------------------------------- main loop

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
            gid = g.get("id", {})
            gid = gid.get("_serialized") if isinstance(gid, dict) else gid
            log("  ", gid, "|", (g.get("name") or g.get("subject") or "?"))
        return 0

    if not LLM_API_KEY:
        log("FATAL: LLM_API_KEY not set")
        return 2

    log(f"Watching {GROUP_CHAT_ID}, trigger='{TRIGGER_PREFIX}', every {POLL_INTERVAL}s")
    seen: set[str] = set()
    # Baseline: mark everything already in the group as seen, so we only react to NEW triggers.
    try:
        for m in waha.get_messages(GROUP_CHAT_ID, HISTORY_LIMIT):
            if m.get("id"):
                seen.add(m["id"])
    except Exception as e:  # noqa: BLE001
        log("warn: baseline fetch failed:", e)

    while True:
        try:
            messages = waha.get_messages(GROUP_CHAT_ID, HISTORY_LIMIT)
        except Exception as e:  # noqa: BLE001
            log("poll error:", e)
            time.sleep(POLL_INTERVAL)
            continue

        # WAHA can return a non-list (e.g. an error dict) during transient states.
        if not isinstance(messages, list):
            log("poll: unexpected response:", str(messages)[:160])
            time.sleep(POLL_INTERVAL)
            continue

        for m in messages:
            # Never let one bad message kill the loop.
            try:
                if not isinstance(m, dict):
                    continue
                mid = m.get("id")
                if not mid or mid in seen:
                    continue
                seen.add(mid)
                text = msg_text(m)
                if not text or not text.startswith(TRIGGER_PREFIX):
                    continue
                prompt = text[len(TRIGGER_PREFIX):].strip()
                log("trigger:", prompt)
                history = build_history(messages)
                history.append({"role": "user", "content": prompt})
                try:
                    answer = llm_chat(history)
                except Exception as e:  # noqa: BLE001
                    answer = f"(LLM error: {e})"
                log("reply:", answer[:120])
                try:
                    waha.send_text(GROUP_CHAT_ID, REPLY_PREFIX + answer)
                except Exception as e:  # noqa: BLE001
                    log("send error:", e)
            except Exception as e:  # noqa: BLE001
                log("message handling error:", e)

        # Cap memory of seen ids.
        if len(seen) > 2000:
            seen = set(list(seen)[-1000:])
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        log("bye")
