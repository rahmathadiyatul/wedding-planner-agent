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

# Status of a to-do. The web view shows these as colours on a calendar (the
# card's `due` date is what places it). A task with a parent is a checklist item
# inside its parent's card rather than a card of its own.
TASK_STATES = ("todo", "doing", "done")
TASK_LABELS = {"todo": "Rencana", "doing": "Proses", "done": "Selesai"}


# ---------------------------------------------------------------- formatting

def rupiah(n: int | float) -> str:
    """5000000 -> 'Rp 5.000.000' (Indonesian thousands separator)."""
    try:
        n = int(round(float(n)))
    except (TypeError, ValueError):
        return "Rp 0"
    sign = "-" if n < 0 else ""
    return f"{sign}Rp {abs(n):,}".replace(",", ".")


_MULT = (("miliar", 10**9), ("milyar", 10**9), ("juta", 10**6), ("jt", 10**6), ("j", 10**6),
         ("ribu", 10**3), ("rb", 10**3), ("k", 10**3))


def parse_amount(v) -> int:
    """'5jt', '1,5 juta', '500rb', '2.5k', 'Rp 1.500.000,00' -> rupiah.

    Mirrors parseAmount() in the web page, so the bot and the page read a
    number the same way. A lone separator NOT followed by exactly three
    digits is a decimal point ('1,5jt'); otherwise separators are thousands.
    """
    if isinstance(v, (int, float)):
        return int(round(v))
    s = str(v or "").lower().replace("rp.", "").replace("rp", "")
    s = "".join(s.split())
    if not s:
        return 0
    neg = s.startswith("-")
    if neg:
        s = s[1:]
    mult = 1
    for suffix, m in _MULT:
        if s.endswith(suffix):
            mult, s = m, s[: -len(suffix)]
            break
    s = "".join(ch for ch in s if ch.isdigit() or ch in ".,")
    try:
        if "." in s and "," in s:
            n = float(s.replace(".", "").replace(",", "."))
        elif "," in s or "." in s:
            sep = "," if "," in s else "."
            parts = s.split(sep)
            if len(parts) == 2 and len(parts[1]) != 3:
                n = float(parts[0] + "." + parts[1])
            else:
                n = float("".join(parts))
        else:
            n = float(s) if s else 0.0
    except ValueError:
        n = 0.0
    n = int(round(n * mult))
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
        data.setdefault("tasks", [])
        data["mail"] = _clean_mail(data.get("mail"))
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

    def replace_mail(self, cfg: dict) -> dict:
        """Save the reminder settings edited on the Settings screen."""
        with self._lock:
            data = self._read_locked()
            data["mail"] = _clean_mail(cfg)
            self._write_locked(data)
            return data["mail"]

    def mail(self) -> dict:
        with self._lock:
            return self._read_locked()["mail"]

    def apply_patch(self, patch: dict) -> dict:
        """Merge an edit from the web page, row by row.

        The page sends only what it changed: rows to upsert and ids to
        delete, per collection, plus notes/mail when those changed. Every
        other row is left exactly as it is on disk -- which is the point:
        the WhatsApp bot writes this same file, and a whole-file overwrite
        from a page that loaded ten minutes ago would erase the bot's work.

        Rules:
          * deleting a parent also deletes its children, unless the same
            patch re-sends a child (it was moved, not removed);
          * an upsert replaces the row with that id in place, or appends;
          * a row whose name is blank is kept when it still has children,
            so a breakdown is never orphaned by an unnamed parent;
          * `notified` on a task belongs to the reminder scheduler -- the
            page can never set it, so a save can't make a reminder re-fire.
        """
        patch = patch if isinstance(patch, dict) else {}
        with self._lock:
            data = self._read_locked()
            for key, clean in (("entries", _clean), ("tasks", _clean_task)):
                part = patch.get(key)
                if not isinstance(part, dict):
                    continue
                rows = list(data.get(key) or [])
                ups = [r for r in (part.get("upsert") or []) if isinstance(r, dict)]
                up_ids = {str(r.get("id") or "") for r in ups}
                dels = {str(x) for x in (part.get("delete") or []) if x}
                grew = True
                while grew:                      # cascade to children, grandchildren...
                    grew = False
                    for r in rows:
                        rid = r.get("id")
                        if (r.get("parent") in dels and rid not in dels
                                and rid not in up_ids):
                            dels.add(rid)
                            grew = True
                rows = [r for r in rows if r.get("id") not in dels]
                index = {r.get("id"): i for i, r in enumerate(rows)}
                for raw in ups:
                    c = clean(raw)
                    if not c.get("id") or str(c["id"]).startswith("tmp-"):
                        c["id"] = uuid.uuid4().hex[:8]
                    if key == "tasks":
                        prev = rows[index[c["id"]]] if c["id"] in index else {}
                        c["notified"] = str(prev.get("notified") or "")
                    if c["id"] in index:
                        rows[index[c["id"]]] = c
                    else:
                        index[c["id"]] = len(rows)
                        rows.append(c)
                ids = {r.get("id") for r in rows}
                for r in rows:
                    p = r.get("parent") or ""
                    if p and (p not in ids or p == r.get("id")):
                        r["parent"] = ""
                data[key] = rows
            if isinstance(patch.get("notes"), str):
                data["notes"] = patch["notes"]
            if isinstance(patch.get("mail"), dict):
                data["mail"] = _clean_mail(patch["mail"])
            self._write_locked(data)
            return data

    def replace_all(self, entries: list, notes: str | None = None) -> None:
        """Full save from the web page."""
        with self._lock:
            data = self._read_locked()
            cleaned, idmap = [], {}
            parents = {str(e.get("parent") or "") for e in entries if e.get("parent")}
            for e in entries:
                c = _clean(e)
                if not c["item"] and not c["amount"] and str(e.get("id") or "") not in parents:
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

    # -------------------------------------------------------- tasks (calendar)

    def replace_tasks(self, tasks: list) -> None:
        """Full save from the to-do view."""
        with self._lock:
            data = self._read_locked()
            cleaned, idmap = [], {}
            for t in tasks:
                c = _clean_task(t)
                if not c["title"]:
                    continue
                old = str(t.get("id") or "")
                if not old or old.startswith("tmp-"):
                    c["id"] = uuid.uuid4().hex[:8]
                    if old:
                        idmap[old] = c["id"]
                cleaned.append(c)
            ids = {c["id"] for c in cleaned}
            for c in cleaned:
                p = c.get("parent") or ""
                if p in idmap:
                    c["parent"] = idmap[p]
                if c.get("parent") and (c["parent"] not in ids or c["parent"] == c["id"]):
                    c["parent"] = ""
            data["tasks"] = cleaned
            self._write_locked(data)

    def task_add(self, title: str, detail: str = "", status: str = "todo",
                 category: str = "", due: str = "", parent: str = "",
                 time: str = "", remind: str = "", remind_to: str = "",
                 due_end: str = "") -> dict:
        with self._lock:
            data = self._read_locked()
            pid = _resolve_task(data["tasks"], parent)
            t = _clean_task({"id": uuid.uuid4().hex[:8], "title": title, "detail": detail,
                             "status": status, "category": category, "due": due,
                             "time": time, "remind": remind, "remind_to": remind_to,
                             "due_end": due_end, "parent": pid})
            data["tasks"].append(t)
            self._write_locked(data)
        return t

    def task_add_many(self, items: list, status: str = "todo", category: str = "",
                      parent: str = "") -> list[dict]:
        """Add a batch of tasks (optionally all as checklist items of one card)."""
        out = []
        with self._lock:
            data = self._read_locked()
            pid = _resolve_task(data["tasks"], parent)
            if parent.strip() and not pid:
                # No such card yet -- make it, so the batch lands as its
                # checklist instead of silently becoming loose to-dos.
                card = _clean_task({"id": uuid.uuid4().hex[:8], "title": parent.strip(),
                                    "status": status, "category": category, "parent": ""})
                data["tasks"].append(card)
                pid = card["id"]
            for it in items or []:
                raw = {"title": it, "status": status} if isinstance(it, str) else dict(it)
                raw.setdefault("status", status)
                raw.setdefault("category", category)
                raw["parent"] = pid
                raw["id"] = uuid.uuid4().hex[:8]
                t = _clean_task(raw)
                if not t["title"]:
                    continue
                data["tasks"].append(t)
                out.append(t)
            self._write_locked(data)
        return out

    def task_update(self, task_id: str, **fields) -> dict | None:
        with self._lock:
            data = self._read_locked()
            tid = _resolve_task(data["tasks"], task_id)
            for t in data["tasks"]:
                if t.get("id") == tid:
                    t.update({k: v for k, v in fields.items() if v is not None and v != ""})
                    t.update(_clean_task(t))
                    self._write_locked(data)
                    return t
        return None

    def task_delete(self, task_id: str) -> bool:
        """Delete a task and any checklist items under it."""
        with self._lock:
            data = self._read_locked()
            tid = _resolve_task(data["tasks"], task_id)
            before = len(data["tasks"])
            data["tasks"] = [t for t in data["tasks"]
                             if t.get("id") != tid and t.get("parent") != tid]
            if len(data["tasks"]) != before:
                self._write_locked(data)
                return True
        return False

    def tasks_text(self, status: str = "") -> str:
        """Board as text, grouped by column, with checklist progress per card."""
        tasks = self.read()["tasks"]
        if not tasks:
            return "(belum ada to-do)"
        want = [status] if status in TASK_STATES else list(TASK_STATES)
        cards = [t for t in tasks if not t.get("parent") and t.get("status") in want]
        if not cards:
            return "(belum ada to-do)"

        # Grouped by due date, because the web view is a calendar. Undated
        # cards come first -- they are the ones nobody has scheduled yet.
        def key(c: dict) -> tuple:
            d = str(c.get("due") or "").strip()
            return (1, d) if d else (0, "")

        out: list[str] = []
        cur = object()
        for c in sorted(cards, key=key):
            due = str(c.get("due") or "").strip()
            if due != cur:
                cur = due
                out.append(f"== {due or 'Tanpa tanggal'} ==")
            kids = [k for k in tasks if k.get("parent") == c["id"]]
            done = sum(1 for k in kids if k.get("status") == "done")
            bits = [f"[{c['id']}] {c['title']}", f"<{TASK_LABELS.get(c.get('status'), '?')}>"]
            if c.get("due_end") and c.get("due_end") != due:
                bits.append(f"s/d {c['due_end']} (tiap hari)")
            if kids:
                bits.append(f"({done}/{len(kids)})")
            if c.get("category"):
                bits.append(f"#{c['category']}")
            out.append("  " + " ".join(bits))
            if c.get("detail"):
                out.append(f"    {c['detail'][:120]}")
            for k in kids:
                mark = "x" if k.get("status") == "done" else " "
                out.append(f"    [{mark}] [{k['id']}] {k['title']}")
        return "\n".join(out)

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
        # Walk only the top level and let amount_of fold each sub-tree in, so
        # nothing is counted twice and no branch is lost.
        tops = [e for e in all_entries if not e.get("parent")]

        def parts(e: dict) -> list:
            # Once a breakdown carries numbers, each sub-item counts under
            # its OWN status (DP paid, the rest still planned).
            kids = children_of(all_entries, e.get("id", ""))
            if kids and sum(amount_of(all_entries, k) for k in kids):
                out: list = []
                for k in kids:
                    out.extend(parts(k))
                return out
            return [(e.get("status"), int(e.get("amount") or 0))]

        def tot(kind, status=None):
            return sum(a for e in tops if e.get("kind") == kind
                       for st, a in parts(e) if status is None or st == status)

        inc_a, inc_e = tot("income", "actual"), tot("income", "expected")
        exp_a, exp_e = tot("expense", "actual"), tot("expense", "expected")
        return {
            "income_actual": inc_a, "income_expected": inc_e, "income_total": inc_a + inc_e,
            "expense_actual": exp_a, "expense_expected": exp_e, "expense_total": exp_a + exp_e,
            "cash_on_hand": inc_a - exp_a,
            "projected_balance": (inc_a + inc_e) - (exp_a + exp_e),
            "count": len(all_entries),
            "blank": sum(1 for e in leaves(all_entries) if not int(e.get("amount") or 0)),
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
            + (f"\n({s['blank']} item belum diisi nominalnya, jadi belum ikut hitungan)"
               if s.get("blank") else "")
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


MAIL_DEFAULTS = {
    "from_email": "", "from_name": "Wedding Planner",
    "people": [], "default_to": "", "default_lead": "1d",
    "default_time": "09:00", "enabled": True,
}


def _clean_mail(m) -> dict:
    """Reminder settings, as edited on the Settings screen.

    Only non-secret settings live here -- the Brevo API key and SMTP password
    stay in the environment, since this file is served to anyone holding the
    doc token.
    """
    m = m if isinstance(m, dict) else {}
    people = []
    seen = set()
    for p in (m.get("people") or []):
        if not isinstance(p, dict):
            continue
        name = str(p.get("name") or "").strip()
        email = str(p.get("email") or "").strip()
        if not name or "@" not in email or name.lower() in seen:
            continue
        seen.add(name.lower())
        people.append({"name": name, "email": email})
    to = m.get("default_to")
    if isinstance(to, list):
        to = ",".join(str(x) for x in to)
    return {
        "from_email": str(m.get("from_email") or "").strip(),
        "from_name": str(m.get("from_name") or MAIL_DEFAULTS["from_name"]).strip(),
        "people": people,
        "default_to": str(to or "").strip(),
        "default_lead": str(m.get("default_lead") or "").strip(),
        "default_time": str(m.get("default_time") or "").strip(),
        "enabled": bool(m.get("enabled", True)),
    }


def _clean_task(t: dict) -> dict:
    status = str(t.get("status") or "todo").lower()
    return {
        "id": t.get("id") or uuid.uuid4().hex[:8],
        "title": str(t.get("title") or "").strip(),
        "detail": str(t.get("detail") or "").strip(),
        "status": status if status in TASK_STATES else "todo",
        "category": str(t.get("category") or "").strip(),
        "due": str(t.get("due") or "").strip(),
        # A to-do can span days. With due_end set, `due` is the first day and
        # the reminder repeats daily at `time` until due_end.
        "due_end": str(t.get("due_end") or "").strip(),
        "time": str(t.get("time") or "").strip(),
        # reminder: "" = use the configured default lead, "off" = never.
        "remind": str(t.get("remind") or "").strip(),
        "remind_to": str(t.get("remind_to") or "").strip(),
        # bookkeeping for the scheduler: the send-time it last mailed for.
        "notified": str(t.get("notified") or "").strip(),
        "parent": str(t.get("parent") or "").strip(),
    }


def _resolve_task(tasks: list[dict], ref: str) -> str:
    """Accept a task id or (part of) its title -- the bot usually has the title."""
    r = (ref or "").strip()
    if not r:
        return ""
    for t in tasks:
        if t.get("id") == r:
            return r
    low = r.lower()
    for t in tasks:
        if t.get("title", "").strip().lower() == low:
            return t.get("id", "")
    for t in tasks:
        if low in t.get("title", "").strip().lower():
            return t.get("id", "")
    return ""


def children_of(entries: list[dict], pid: str) -> list[dict]:
    return [e for e in entries if e.get("parent") == pid]


def leaves(entries: list[dict]) -> list[dict]:
    """Entries with no sub-items -- the ones that actually carry money."""
    parents = {e.get("parent") for e in entries if e.get("parent")}
    return [e for e in entries if e.get("id") not in parents]


def amount_of(entries: list[dict], e: dict) -> int:
    """An entry's effective amount.

    Sub-items win when at least one of them carries a number -- that is the
    breakdown replacing the estimate. But a parent whose sub-items are all
    still blank keeps its own figure, otherwise the moment you jot down the
    first placeholder line the parent silently drops to zero and every total
    on the page is understated.
    """
    kids = children_of(entries, e.get("id", ""))
    if kids:
        total = sum(amount_of(entries, k) for k in kids)
        if total:
            return total
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
    try:
        import mailer
        cfg = mailer.web_config(data["mail"])
    except Exception as e:  # noqa: BLE001
        cfg = dict(data["mail"], enabled=False, why=f"mailer unavailable: {e!r}",
                   transport="none", has_secret=False)
    return page.render(token, store.title, data["entries"],
                       data.get("notes", ""), data.get("tasks", []), cfg,
                       data.get("updated_at", ""))
