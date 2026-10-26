r"""Optional Langfuse tracing.

Everything here is best-effort: if Langfuse isn't configured, the SDK is
missing, or the network is down, every call degrades to a no-op. Observability
must never take the bot down.

Shape of a traced message:
    whatsapp-message (span)
      |- llm (generation)   -- one per tool-call round, with usage
      |- tool:web_search    -- one per tool invocation
      \- errors recorded with level=ERROR + status_message
"""
from __future__ import annotations

import os

_client = None
ENABLED = False

_PK = os.environ.get("LANGFUSE_PUBLIC_KEY", "")
_SK = os.environ.get("LANGFUSE_SECRET_KEY", "")
_HOST = os.environ.get("LANGFUSE_BASE_URL") or os.environ.get("LANGFUSE_HOST") or "https://cloud.langfuse.com"

if _PK and _SK:
    try:
        from langfuse import Langfuse  # type: ignore
        _client = Langfuse(public_key=_PK, secret_key=_SK, host=_HOST)
        ENABLED = True
    except Exception as e:  # noqa: BLE001
        print(f"[obs] langfuse disabled: {e!r}", flush=True)


def _usage(u) -> dict | None:
    """OpenAI-style usage -> Langfuse usage_details."""
    if not isinstance(u, dict):
        return None
    out = {}
    for src, dst in (("prompt_tokens", "input"), ("completion_tokens", "output"),
                     ("total_tokens", "total")):
        v = u.get(src)
        if isinstance(v, int):
            out[dst] = v
    return out or None


class _Null:
    """Stand-in used whenever tracing is off or a call failed."""

    def generation(self, *a, **k):
        return self

    def span(self, *a, **k):
        return self

    def end(self, *a, **k):
        return None


NULL = _Null()


class _Obs:
    def __init__(self, o) -> None:
        self._o = o

    def _child(self, name: str, as_type: str, **kw):
        try:
            return _Obs(self._o.start_observation(name=name, as_type=as_type, **kw))
        except Exception:  # noqa: BLE001
            return NULL

    def generation(self, name: str, model: str | None = None, input=None):
        child = self._child(name, "generation", input=input)
        if model and isinstance(child, _Obs):
            try:
                child._o.update(model=model)
            except Exception:  # noqa: BLE001
                pass
        return child

    def span(self, name: str, input=None):
        return self._child(name, "tool", input=input)

    def end(self, output=None, error=None, usage=None) -> None:
        try:
            kw = {}
            if error is not None:
                kw["level"] = "ERROR"
                kw["status_message"] = f"{type(error).__name__}: {error}"[:900]
                kw["output"] = str(error)[:2000]
            elif output is not None:
                kw["output"] = output
            u = _usage(usage)
            if u:
                kw["usage_details"] = u
            if kw:
                self._o.update(**kw)
            self._o.end()
        except Exception:  # noqa: BLE001
            pass


def trace(name: str, input=None, metadata=None):
    """Start a root observation for one handled message."""
    if not ENABLED or _client is None:
        return NULL
    try:
        return _Obs(_client.start_observation(
            name=name, as_type="span", input=input, metadata=metadata))
    except Exception:  # noqa: BLE001
        return NULL


def error(name: str, exc: BaseException, metadata=None) -> None:
    """Record a standalone failure that happened outside a traced LLM call."""
    if not ENABLED or _client is None:
        return
    try:
        o = _client.start_observation(name=name, as_type="span", metadata=metadata)
        o.update(level="ERROR", status_message=f"{type(exc).__name__}: {exc}"[:900])
        o.end()
    except Exception:  # noqa: BLE001
        pass


def flush() -> None:
    if _client is not None:
        try:
            _client.flush()
        except Exception:  # noqa: BLE001
            pass
