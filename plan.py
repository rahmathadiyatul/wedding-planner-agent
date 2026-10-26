"""Shared wedding plan: income/expense ledger + freeform notes.

Stored as one JSON file on a volume. Both the web page and the bot's tools go
through PlanStore, whose lock serializes every read/modify/write so a human
save and a bot edit can't clobber each other.

Entry shape:
    {"id", "kind": income|expense, "item", "amount": int (IDR),
     "category", "date": "YYYY-MM-DD"|"", "status": actual|expected, "note"}

`status` is what makes "money I already have" vs "money I expect" work:
    income  + actual   -> already received
    income  + expected -> still coming
    expense + actual   -> already paid
    expense + expected -> planned, not paid yet
"""
from __future__ import annotations

import json
import os
import threading
import datetime as dt
import uuid

KINDS = ("income", "expense")
STATUSES = ("actual", "expected")


# ---------------------------------------------------------------- formatting

def rupiah(n: int | float) -> str:
    """5000000 -> 'Rp 5.000.000' (Indonesian thousands separator)."""
    try:
        n = int(round(float(n)))
    except (TypeError, ValueError):
        return "Rp 0"
    sign = "-" if n < 0 else ""
    return f"{sign}Rp {abs(n):,}".replace(",", ".")


def parse_amount(v) -> int:
    """Accept 5000000, '5.000.000', 'Rp 5juta'-ish -> int. Non-digits dropped."""
    if isinstance(v, (int, float)):
        return int(round(v))
    s = str(v or "")
    neg = s.strip().startswith("-")
    digits = "".join(ch for ch in s if ch.isdigit())
    n = int(digits) if digits else 0
    return -n if neg else n


# ---------------------------------------------------------------- store

class PlanStore:
    def __init__(self, path: str, legacy_md: str = "", title: str = "Wedding Plan") -> None:
        self.path = path
        self.title = title
        self._lock = threading.Lock()
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        if not os.path.exists(path):
            notes = ""
            if legacy_md and os.path.exists(legacy_md):  # carry over the old markdown doc
                try:
                    with open(legacy_md, encoding="utf-8") as fh:
                        notes = fh.read()
                except OSError:
                    notes = ""
            self._write_locked({"entries": [], "notes": notes, "updated_at": _now()})

    # -- raw io (callers hold the lock) --
    def _read_locked(self) -> dict:
        try:
            with open(self.path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            data = {}
        data.setdefault("entries", [])
        data.setdefault("notes", "")
        return data

    def _write_locked(self, data: dict) -> None:
        data["updated_at"] = _now()
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)

    # -- public --
    def read(self) -> dict:
        with self._lock:
            return self._read_locked()

    def replace_all(self, entries: list, notes: str | None = None) -> None:
        """Full save from the web page."""
        with self._lock:
            data = self._read_locked()
            cleaned, idmap = [], {}
            for e in entries:
                c = _clean(e)
                if not c["item"] and not c["amount"]:
                    continue
                old = str(e.get("id") or "")
                if not old or old.startswith("tmp-"):
                    c["id"] = uuid.uuid4().hex[:8]
                    if old:
                        idmap[old] = c["id"]
                cleaned.append(c)
            _relink(cleaned, idmap)
            data["entries"] = cleaned
            if notes is not None:
                data["notes"] = notes
            self._write_locked(data)

    def add(self, kind: str, item: str, amount, status: str = "actual",
            category: str = "", date: str = "", note: str = "", parent: str = "") -> dict:
        with self._lock:
            data = self._read_locked()
            pid = _resolve_parent(data["entries"], parent)
            if pid:  # a sub-item always belongs to its parent's side of the ledger
                par = next((x for x in data["entries"] if x["id"] == pid), None)
                if par:
                    kind = par.get("kind", kind)
            entry = _clean({
                "id": uuid.uuid4().hex[:8], "kind": kind, "item": item, "amount": amount,
                "status": status, "category": category, "date": date, "note": note,
                "parent": pid,
            })
            data["entries"].append(entry)
            self._write_locked(data)
        return entry

    def add_many(self, items: list[dict], parent: str = "") -> list[dict]:
        """Add several entries at once, optionally all under one parent."""
        out = []
        with self._lock:
            data = self._read_locked()
            pid = _resolve_parent(data["entries"], parent)
            par = next((x for x in data["entries"] if x["id"] == pid), None) if pid else None
            for it in items or []:
                e = dict(it)
                if par:
                    e["kind"] = par.get("kind", e.get("kind"))
                    e["parent"] = pid
                e["id"] = uuid.uuid4().hex[:8]
                c = _clean(e)
                data["entries"].append(c)
                out.append(c)
            self._write_locked(data)
        return out

    def update(self, entry_id: str, **fields) -> dict | None:
        with self._lock:
            data = self._read_locked()
            for e in data["entries"]:
                if e.get("id") == entry_id:
                    e.update({k: v for k, v in fields.items() if v is not None and v != ""})
                    e.update(_clean(e))
                    self._write_locked(data)
                    return e
        return None

    def delete(self, entry_id: str) -> bool:
        """Delete an entry and, with it, any sub-items it owns."""
        with self._lock:
            data = self._read_locked()
            before = len(data["entries"])
            data["entries"] = [e for e in data["entries"]
                               if e.get("id") != entry_id and e.get("parent") != entry_id]
            if len(data["entries"]) != before:
                self._write_locked(data)
                return True
        return False

    def _resolved(self, parent: str) -> str:
        """The id an item name/id resolves to, or '' if there's no such entry."""
        return _resolve_parent(self.read()["entries"], parent)

    def find(self, text: str) -> list[dict]:
        t = (text or "").strip().lower()
        return [e for e in self.read()["entries"]
                if t and (t in e.get("item", "").lower() or t == e.get("id"))]

    def set_notes(self, notes: str) -> None:
        with self._lock:
            data = self._read_locked()
            data["notes"] = notes
            self._write_locked(data)

    def summary(self) -> dict:
        all_entries = self.read()["entries"]
        # A parent's amount is the sum of its children, so counting both would
        # double-count: total over leaves only.
        entries = leaves(all_entries)

        def tot(kind, status=None):
            return sum(int(e.get("amount") or 0) for e in entries
                       if e.get("kind") == kind and (status is None or e.get("status") == status))

        inc_a, inc_e = tot("income", "actual"), tot("income", "expected")
        exp_a, exp_e = tot("expense", "actual"), tot("expense", "expected")
        return {
            "income_actual": inc_a, "income_expected": inc_e, "income_total": inc_a + inc_e,
            "expense_actual": exp_a, "expense_expected": exp_e, "expense_total": exp_a + exp_e,
            "cash_on_hand": inc_a - exp_a,
            "projected_balance": (inc_a + inc_e) - (exp_a + exp_e),
            "count": len(all_entries),
        }

    def summary_text(self) -> str:
        s = self.summary()
        return (
            f"Pemasukan diterima: {rupiah(s['income_actual'])}\n"
            f"Pemasukan diharapkan: {rupiah(s['income_expected'])}\n"
            f"Total pemasukan (proyeksi): {rupiah(s['income_total'])}\n"
            f"Pengeluaran dibayar: {rupiah(s['expense_actual'])}\n"
            f"Pengeluaran direncanakan: {rupiah(s['expense_expected'])}\n"
            f"Total pengeluaran (proyeksi): {rupiah(s['expense_total'])}\n"
            f"Uang di tangan (diterima - dibayar): {rupiah(s['cash_on_hand'])}\n"
            f"Saldo proyeksi: {rupiah(s['projected_balance'])}"
        )

    def entries_text(self, kind: str = "", status: str = "") -> str:
        """Tree listing: sub-items indented under their parent, parents showing
        the summed total so the bot can read the breakdown back accurately."""
        all_entries = self.read()["entries"]
        lines: list[str] = []

        def want(e: dict) -> bool:
            return ((kind not in KINDS or e.get("kind") == kind)
                    and (status not in STATUSES or e.get("status") == status))

        def emit(e: dict, depth: int) -> None:
            kids = children_of(all_entries, e.get("id", ""))
            amt = amount_of(all_entries, e)
            meta = [e.get("status", "")]
            if e.get("category"):
                meta.append(e["category"])
            if kids:
                meta.append(f"{len(kids)} sub-item")
            head = "  " * depth + ("- " if depth else "")
            date = f"{e.get('date')} | " if e.get("date") else ""
            lines.append(f"{head}[{e.get('id')}] {date}{e.get('item','')} | "
                         f"{rupiah(amt)}  ({', '.join(m for m in meta if m)})")
            for k in kids:
                emit(k, depth + 1)

        for e in all_entries:
            if e.get("parent"):
                continue  # reached through its parent
            kids = children_of(all_entries, e.get("id", ""))
            if want(e) or any(want(k) for k in kids):
                emit(e, 0)
        return "\n".join(lines) if lines else "(belum ada entri)"


def _clean(e: dict) -> dict:
    kind = str(e.get("kind") or "expense").lower()
    status = str(e.get("status") or "actual").lower()
    return {
        "id": e.get("id") or uuid.uuid4().hex[:8],
        "kind": kind if kind in KINDS else "expense",
        "item": str(e.get("item") or "").strip(),
        "amount": parse_amount(e.get("amount")),
        "status": status if status in STATUSES else "actual",
        "category": str(e.get("category") or "").strip(),
        "date": str(e.get("date") or "").strip(),
        "note": str(e.get("note") or "").strip(),
        "parent": str(e.get("parent") or "").strip(),
    }


def children_of(entries: list[dict], pid: str) -> list[dict]:
    return [e for e in entries if e.get("parent") == pid]


def leaves(entries: list[dict]) -> list[dict]:
    """Entries with no sub-items -- the ones that actually carry money."""
    parents = {e.get("parent") for e in entries if e.get("parent")}
    return [e for e in entries if e.get("id") not in parents]


def amount_of(entries: list[dict], e: dict) -> int:
    """An entry's effective amount: the sum of its sub-items, or its own value."""
    kids = children_of(entries, e.get("id", ""))
    if kids:
        return sum(amount_of(entries, k) for k in kids)
    return int(e.get("amount") or 0)


def _resolve_parent(entries: list[dict], parent: str) -> str:
    """Accept either an id or an item name (what the bot will usually have)."""
    p = (parent or "").strip()
    if not p:
        return ""
    for e in entries:
        if e.get("id") == p:
            return p
    low = p.lower()
    for e in entries:
        if e.get("item", "").strip().lower() == low:
            return e.get("id", "")
    for e in entries:
        if low in e.get("item", "").strip().lower():
            return e.get("id", "")
    return ""


def _relink(cleaned: list[dict], idmap: dict) -> None:
    """Point children at their parents' final ids and drop dangling links."""
    ids = {c["id"] for c in cleaned}
    for c in cleaned:
        p = c.get("parent") or ""
        if p in idmap:
            c["parent"] = idmap[p]
        if c.get("parent") and c["parent"] not in ids:
            c["parent"] = ""
        if c.get("parent") == c["id"]:
            c["parent"] = ""
    # children follow their parent's side of the ledger
    by_id = {c["id"]: c for c in cleaned}
    for c in cleaned:
        par = by_id.get(c.get("parent") or "")
        if par:
            c["kind"] = par.get("kind", c["kind"])


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------- web page

def render_page(token: str, store: PlanStore) -> str:
    import page
    data = store.read()
    return page.render(token, store.title, data["entries"], data.get("notes", ""))

