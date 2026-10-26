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
import html
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
            data["entries"] = [_clean(e) for e in entries if _clean(e)["item"] or _clean(e)["amount"]]
            if notes is not None:
                data["notes"] = notes
            self._write_locked(data)

    def add(self, kind: str, item: str, amount, status: str = "actual",
            category: str = "", date: str = "", note: str = "") -> dict:
        entry = _clean({
            "id": uuid.uuid4().hex[:8], "kind": kind, "item": item, "amount": amount,
            "status": status, "category": category, "date": date, "note": note,
        })
        with self._lock:
            data = self._read_locked()
            data["entries"].append(entry)
            self._write_locked(data)
        return entry

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
        with self._lock:
            data = self._read_locked()
            before = len(data["entries"])
            data["entries"] = [e for e in data["entries"] if e.get("id") != entry_id]
            if len(data["entries"]) != before:
                self._write_locked(data)
                return True
        return False

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
        entries = self.read()["entries"]

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
            "count": len(entries),
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
        entries = self.read()["entries"]
        if kind in KINDS:
            entries = [e for e in entries if e.get("kind") == kind]
        if status in STATUSES:
            entries = [e for e in entries if e.get("status") == status]
        if not entries:
            return "(belum ada entri)"
        lines = []
        for e in entries:
            bits = [e.get("date") or "-", e.get("item", ""), rupiah(e.get("amount", 0))]
            meta = [e.get("kind", ""), e.get("status", "")]
            if e.get("category"):
                meta.append(e["category"])
            lines.append(f"[{e.get('id')}] " + " | ".join(bits) + f"  ({', '.join(meta)})")
        return "\n".join(lines)


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
    }


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------- web page

def render_page(token: str, store: PlanStore) -> str:
    data = store.read()
    payload = json.dumps({"entries": data["entries"], "notes": data.get("notes", "")},
                         ensure_ascii=False)
    return (_PAGE
            .replace("__TITLE__", html.escape(store.title))
            .replace("__TOKEN__", html.escape(token))
            .replace("__DATA__", payload.replace("</", "<\\/")))


_PAGE = r"""<!doctype html>
<html lang="id"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
  :root{ color-scheme: dark; --bg:#0f1115; --card:#161a21; --line:#262c36; --fg:#e8eaed;
         --muted:#949cab; --in:#39d98a; --out:#ff6b6b; --accent:#2f6df6; }
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--fg);
       font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
  header{padding:14px 16px;background:var(--card);border-bottom:1px solid var(--line);
         position:sticky;top:0;z-index:5;display:flex;justify-content:space-between;align-items:center;gap:10px}
  header h1{font-size:17px;margin:0}
  .wrap{max-width:980px;margin:0 auto;padding:16px}
  .cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-bottom:18px}
  .card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px}
  .card .l{font-size:12px;color:var(--muted);margin-bottom:6px}
  .card .v{font-size:18px;font-weight:700;letter-spacing:.2px}
  .card .s{font-size:11px;color:var(--muted);margin-top:4px}
  .in{color:var(--in)} .out{color:var(--out)}
  .big{grid-column:span 2}
  @media(max-width:520px){ .big{grid-column:span 2} }
  .tablewrap{overflow-x:auto;border:1px solid var(--line);border-radius:12px;background:var(--card)}
  table{border-collapse:collapse;width:100%;min-width:700px}
  th,td{padding:8px;border-bottom:1px solid var(--line);text-align:left;font-size:14px}
  th{font-size:12px;color:var(--muted);font-weight:600;white-space:nowrap}
  input,select,textarea{background:#0b0d11;color:var(--fg);border:1px solid #2a313c;
       border-radius:8px;padding:8px;font:14px inherit;width:100%}
  input:focus,select:focus,textarea:focus{outline:2px solid var(--accent);outline-offset:-1px}
  td.amt input{text-align:right}
  .del{background:transparent;border:1px solid #3a2a2e;color:var(--out);border-radius:8px;
       padding:6px 10px;font-size:13px;cursor:pointer}
  .bar{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin:14px 0}
  button.primary{background:var(--accent);color:#fff;border:0;padding:11px 18px;border-radius:10px;
       font-size:15px;font-weight:600;cursor:pointer}
  button.ghost{background:transparent;color:var(--fg);border:1px solid var(--line);
       padding:10px 14px;border-radius:10px;font-size:14px;cursor:pointer}
  .muted{color:var(--muted);font-size:13px}
  h2{font-size:15px;margin:22px 0 8px}
  textarea{min-height:140px;font:13px/1.5 ui-monospace,Menlo,Consolas,monospace}
  .ok{color:var(--in);font-size:14px}
</style></head>
<body>
<header>
  <h1>💍 __TITLE__</h1>
  <span class="muted">bersama · @bang</span>
</header>
<div class="wrap">
  <div class="cards" id="cards"></div>

  <div class="bar">
    <button class="ghost" onclick="addRow('income')">+ Pemasukan</button>
    <button class="ghost" onclick="addRow('expense')">+ Pengeluaran</button>
    <span class="muted">Nominal boleh ditulis 5000000 atau 5.000.000</span>
  </div>

  <div class="tablewrap">
    <table>
      <thead><tr>
        <th style="width:110px">Jenis</th><th style="width:120px">Status</th>
        <th>Item</th><th style="width:140px">Nominal</th>
        <th style="width:130px">Kategori</th><th style="width:140px">Tanggal</th><th style="width:60px"></th>
      </tr></thead>
      <tbody id="rows"></tbody>
    </table>
  </div>

  <h2>Catatan</h2>
  <textarea id="notes" spellcheck="false"></textarea>

  <div class="bar">
    <button class="primary" onclick="save()">Simpan</button>
    <span id="status" class="ok"></span>
    <span class="muted">Simpan terakhir yang menang.</span>
  </div>
</div>

<script>
const TOKEN = "__TOKEN__";
let DATA = __DATA__;

const rp = n => { n = Math.round(Number(n)||0);
  const s = Math.abs(n).toLocaleString('id-ID'); return (n<0?'-':'') + 'Rp ' + s; };
const digits = s => { const neg=String(s).trim().startsWith('-');
  const d=String(s||'').replace(/[^0-9]/g,''); const n=d?parseInt(d,10):0; return neg?-n:n; };

function rowHtml(e){
  const sel=(v,o)=>o.map(([k,l])=>`<option value="${k}"${v===k?' selected':''}>${l}</option>`).join('');
  return `<tr data-id="${e.id||''}">
    <td><select class="k" onchange="recalc()">${sel(e.kind,[['income','Pemasukan'],['expense','Pengeluaran']])}</select></td>
    <td><select class="s" onchange="recalc()">${sel(e.status,[['actual','Sudah'],['expected','Rencana']])}</select></td>
    <td><input class="i" value="${(e.item||'').replace(/"/g,'&quot;')}" placeholder="mis. DP catering"></td>
    <td class="amt"><input class="a" inputmode="numeric" value="${e.amount? Number(e.amount).toLocaleString('id-ID'):''}"
        oninput="recalc()" onblur="this.value=this.value?Number(digits(this.value)).toLocaleString('id-ID'):''"></td>
    <td><input class="c" value="${(e.category||'').replace(/"/g,'&quot;')}" placeholder="venue, catering…"></td>
    <td><input class="d" type="date" value="${e.date||''}"></td>
    <td><button class="del" onclick="this.closest('tr').remove();recalc()">✕</button></td>
  </tr>`;
}
function render(){
  document.getElementById('rows').innerHTML = (DATA.entries||[]).map(rowHtml).join('');
  document.getElementById('notes').value = DATA.notes || '';
  recalc();
}
function addRow(kind){
  document.getElementById('rows').insertAdjacentHTML('beforeend',
    rowHtml({kind:kind,status:kind==='income'?'expected':'expected',item:'',amount:0,category:'',date:''}));
  recalc();
}
function collect(){
  return [...document.querySelectorAll('#rows tr')].map(tr=>({
    id: tr.dataset.id || '',
    kind: tr.querySelector('.k').value, status: tr.querySelector('.s').value,
    item: tr.querySelector('.i').value, amount: digits(tr.querySelector('.a').value),
    category: tr.querySelector('.c').value, date: tr.querySelector('.d').value,
  })).filter(e=>e.item || e.amount);
}
function recalc(){
  const es = collect();
  const t=(k,s)=>es.filter(e=>e.kind===k&&(!s||e.status===s)).reduce((a,e)=>a+(e.amount||0),0);
  const ia=t('income','actual'), ie=t('income','expected'), ea=t('expense','actual'), ee=t('expense','expected');
  const cards=[
    ['Uang di tangan', rp(ia-ea), 'diterima − dibayar', (ia-ea)>=0?'in':'out', true],
    ['Saldo proyeksi', rp((ia+ie)-(ea+ee)), 'semua pemasukan − pengeluaran', ((ia+ie)-(ea+ee))>=0?'in':'out', true],
    ['Pemasukan diterima', rp(ia), '', 'in', false],
    ['Pemasukan diharapkan', rp(ie), '', 'in', false],
    ['Pengeluaran dibayar', rp(ea), '', 'out', false],
    ['Pengeluaran rencana', rp(ee), '', 'out', false],
  ];
  document.getElementById('cards').innerHTML = cards.map(([l,v,s,cls,big])=>
    `<div class="card${big?' big':''}"><div class="l">${l}</div>
     <div class="v ${cls}">${v}</div>${s?`<div class="s">${s}</div>`:''}</div>`).join('');
}
async function save(){
  const body={entries:collect(), notes:document.getElementById('notes').value};
  const st=document.getElementById('status'); st.textContent='menyimpan…';
  try{
    const r=await fetch('/api/plan?token='+encodeURIComponent(TOKEN),
      {method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(body)});
    if(!r.ok) throw new Error(r.status);
    DATA=await r.json(); render(); st.textContent='tersimpan ✓';
    setTimeout(()=>st.textContent='',2500);
  }catch(e){ st.textContent='gagal menyimpan: '+e.message; }
}
render();
</script>
</body></html>"""
