"""The shared plan's web page.

Kept apart from plan.py so the storage logic stays readable. The page is a
small client-side app holding the whole plan in memory; one Save posts
everything back.

Two views behind a sidebar:
  Keuangan - income/expense ledger, tabbed by kind, sortable/filterable/paged.
             Sub-items nest under a parent whose amount is their sum.
  To-do    - a kanban board. A task with a parent is a checklist item inside
             its parent's card rather than a card of its own.

On phones the sidebar becomes a top nav and tables become stacked cards.
"""
from __future__ import annotations

import html
import json


def render(token: str, title: str, entries: list, notes: str, tasks: list,
           mail: dict | None = None) -> str:
    payload = json.dumps({"entries": entries, "notes": notes, "tasks": tasks},
                         ensure_ascii=False)
    cfg = json.dumps(mail or {"people": [], "default_lead": "1d", "default_to": "",
                              "default_time": "09:00", "enabled": False, "why": ""},
                     ensure_ascii=False)
    return (_PAGE
            .replace("__TITLE__", html.escape(title))
            .replace("__TOKEN__", html.escape(token))
            .replace("__MAIL__", cfg.replace("</", "<\\/"))
            .replace("__DATA__", payload.replace("</", "<\\/")))


_PAGE = r"""<!doctype html>
<html lang="id"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
  :root{ color-scheme: dark; --bg:#0f1115; --card:#161a21; --line:#262c36; --fg:#e8eaed;
         --muted:#949cab; --in:#39d98a; --out:#ff6b6b; --accent:#2f6df6; --warn:#f5a524; }
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--fg);
       font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
  .app{display:flex;min-height:100vh}

  /* sidebar */
  .side{width:212px;flex:0 0 212px;background:var(--card);border-right:1px solid var(--line);
        display:flex;flex-direction:column;gap:4px;padding:16px 12px;position:sticky;top:0;height:100vh}
  .brand{font-size:16px;font-weight:700;padding:4px 8px 14px}
  .nav{display:flex;align-items:center;gap:10px;background:transparent;border:0;color:var(--muted);
       padding:10px 12px;border-radius:10px;cursor:pointer;font-size:14px;font-weight:600;text-align:left;width:100%}
  .nav:hover{background:#1b212b;color:var(--fg)}
  .nav.on{background:#17233d;color:#fff}
  .nav .ic{font-size:15px}
  .nav .ct{margin-left:auto;font-size:11px;color:var(--muted);background:#0b0d11;
           border:1px solid var(--line);border-radius:999px;padding:1px 7px}
  .sidefoot{margin-top:auto;color:var(--muted);font-size:12px;padding:8px}

  .main{flex:1;min-width:0;display:flex;flex-direction:column}
  .wrap{padding:18px;max-width:1240px;width:100%;margin:0 auto;flex:1}
  .view{display:none} .view.on{display:block}
  h2{font-size:15px;margin:22px 0 8px}
  .muted{color:var(--muted);font-size:13px}

  /* finance */
  .cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-bottom:16px}
  .card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px}
  .card .l{font-size:12px;color:var(--muted);margin-bottom:6px}
  .card .v{font-size:18px;font-weight:700}
  .card .s{font-size:11px;color:var(--muted);margin-top:4px}
  .in{color:var(--in)} .out{color:var(--out)}
  .big{grid-column:span 2}
  .tabs{display:flex;gap:6px;margin-bottom:12px;flex-wrap:wrap}
  .tab{background:var(--card);border:1px solid var(--line);color:var(--muted);
       padding:9px 16px;border-radius:10px;cursor:pointer;font-size:14px;font-weight:600}
  .tab.on{color:#fff;border-color:var(--accent);background:#17233d}
  .tablewrap{overflow-x:auto;border:1px solid var(--line);border-radius:12px;background:var(--card)}
  table{border-collapse:collapse;width:100%;min-width:820px}
  th,td{padding:7px 8px;border-bottom:1px solid var(--line);text-align:left;font-size:14px;vertical-align:middle}
  th{font-size:12px;color:var(--muted);font-weight:600;white-space:nowrap}
  th.s{cursor:pointer;user-select:none} th.s:hover{color:var(--fg)}
  th .ar{opacity:.45;font-size:10px}
  tr.filters input{padding:5px 7px;font-size:12px}
  input,select,textarea{background:#0b0d11;color:var(--fg);border:1px solid #2a313c;
       border-radius:8px;padding:7px;font:14px inherit;width:100%}
  input:focus,select:focus,textarea:focus{outline:2px solid var(--accent);outline-offset:-1px}
  td.amt input{text-align:right}
  td.amt input:disabled{background:#11151b;color:var(--muted);font-weight:700}
  td.ic{display:flex;align-items:center;gap:6px}
  td.ic .tw{flex:0 0 auto;line-height:1}
  .cr{flex:0 0 auto;width:34px;display:inline-flex;align-items:center;justify-content:center;gap:3px;
      background:transparent;border:1px solid var(--line);border-radius:6px;color:var(--muted);
      font-size:10px;padding:3px 0;cursor:pointer;line-height:1}
  .cr:hover{border-color:var(--accent);color:var(--fg)}
  .cr b{font-size:10px;font-weight:700}
  .cr.ph{border-color:transparent;cursor:default}
  /* sub-items hug their parent: tighter rows, no divider until the last child */
  tr.sub{background:#0f1319}
  tr.sub td{padding-top:2px;padding-bottom:2px}
  tr.sub td.ic{padding-left:22px}
  tr.sub input,tr.sub select{padding:4px 7px;font-size:13px}
  tr.hask td,tr.sub td{border-bottom:0}
  tr.sub.lastsub td{border-bottom:1px solid var(--line)}
  tr.sub .tw{color:var(--accent);opacity:.55}
  .pg{display:flex;gap:8px;align-items:center;justify-content:flex-end;padding:10px;flex-wrap:wrap}
  .empty{padding:26px;text-align:center;color:var(--muted)}
  .mctl{display:none;gap:8px;margin-bottom:10px}
  .mctl input{flex:1} .mctl select{width:auto}

  .btn{background:transparent;border:1px solid var(--line);color:var(--fg);border-radius:8px;
       padding:5px 9px;font-size:12px;cursor:pointer;white-space:nowrap}
  .btn:hover{border-color:var(--accent)}
  .btn.del{color:var(--out);border-color:#3a2a2e}
  .btn:disabled{opacity:.4;cursor:default}
  .bar{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin:12px 0}
  button.primary{background:var(--accent);color:#fff;border:0;padding:11px 18px;border-radius:10px;
       font-size:15px;font-weight:600;cursor:pointer}
  textarea{min-height:120px;font:13px/1.5 ui-monospace,Menlo,Consolas,monospace}
  .ok{color:var(--in);font-size:14px}

  /* ---- calendar to-do ---- */
  .calbar{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin:12px 0}
  .calbar .ttl{font-weight:700;font-size:16px;min-width:170px}
  .seg{display:flex;border:1px solid var(--line);border-radius:8px;overflow:hidden}
  .seg button{background:transparent;border:0;color:var(--muted);padding:6px 13px;font-size:12px;cursor:pointer}
  .seg button.on{background:var(--accent);color:#fff}
  .cal{border:1px solid var(--line);border-radius:12px;overflow:hidden;background:#12161d}
  .calhead{display:grid;grid-template-columns:repeat(7,1fr);background:#0f1319}
  .calhead div{padding:8px 6px;font-size:12px;color:var(--muted);font-weight:600;text-align:center}
  .calgrid{display:grid;grid-template-columns:repeat(7,1fr)}
  .day{border-top:1px solid var(--line);border-left:1px solid var(--line);min-height:108px;
       padding:6px;display:flex;flex-direction:column;gap:4px;position:relative}
  .day:nth-child(7n+1){border-left:0}
  .day.out{background:#0e1116}
  .day.out .dn{opacity:.4}
  .day.over{background:#141c2b;box-shadow:inset 0 0 0 1px var(--accent)}
  .dn{font-size:12px;color:var(--muted);width:22px;height:22px;display:flex;
      align-items:center;justify-content:center;flex:0 0 auto}
  .day.today .dn{background:var(--accent);color:#fff;border-radius:50%;font-weight:700}
  .day .plus{position:absolute;top:4px;right:4px;opacity:0;background:transparent;border:0;
       color:var(--muted);font-size:14px;cursor:pointer;line-height:1;padding:2px 4px}
  .day:hover .plus{opacity:1}
  .day .plus:hover{color:var(--fg)}
  .pill{display:flex;align-items:center;gap:6px;background:var(--card);border:1px solid var(--line);
        border-left:3px solid var(--muted);border-radius:6px;padding:4px 6px;font-size:12px;
        cursor:pointer;text-align:left;width:100%;color:var(--fg)}
  .pill:hover{border-color:var(--accent)}
  .pill .pt{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .pill .pc{font-size:10px;color:var(--muted);flex:0 0 auto}
  .pill.done .pt{text-decoration:line-through;color:var(--muted)}
  .cal.week .day{min-height:300px}
  .more{font-size:11px;color:var(--muted);background:transparent;border:0;cursor:pointer;text-align:left;padding:1px 2px}
  .nodate{margin-top:16px}
  .nodate .list{display:flex;flex-wrap:wrap;gap:8px}
  .nodate .pill{width:auto;max-width:280px}

  /* detail drawer */
  .ov{position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:50;display:none}
  .ov.on{display:block}
  .drw{position:fixed;top:0;right:0;bottom:0;width:min(430px,100%);background:#12161d;
       border-left:1px solid var(--line);z-index:51;transform:translateX(102%);
       transition:transform .18s ease;overflow:auto;padding:16px;display:flex;flex-direction:column;gap:10px}
  .drw.on{transform:none}
  .drw h3{margin:0;font-size:15px;display:flex;align-items:center;gap:8px}
  .drw h3 .x{margin-left:auto}
  .drw label{font-size:12px;color:var(--muted)}
  .stsel{display:flex;gap:6px;flex-wrap:wrap}
  .stsel button{flex:1;min-width:92px;background:transparent;border:1px solid var(--line);
        color:var(--muted);border-radius:8px;padding:8px;font-size:12px;cursor:pointer;
        display:flex;align-items:center;justify-content:center;gap:6px}
  .stsel button .dot{width:8px;height:8px;border-radius:50%;background:currentColor}
  .stsel button.on{color:#fff;border-width:2px}
  .ck{display:flex;align-items:center;gap:8px;padding:3px 0}
  .ck input[type=checkbox]{width:16px;height:16px;flex:0 0 16px;accent-color:var(--accent)}
  .ck .cx{flex:1;font-size:13px;background:transparent;border:0;padding:2px;color:var(--fg)}
  .ck.done .cx{text-decoration:line-through;color:var(--muted)}
  .ck .btn{padding:2px 6px}
  .trow{display:flex;gap:6px;margin-top:4px;flex-wrap:wrap}
  .whos{display:flex;gap:10px;flex-wrap:wrap;margin-top:2px}
  .who{display:flex;align-items:center;gap:5px;font-size:13px;color:var(--fg);
       border:1px solid var(--line);border-radius:8px;padding:5px 9px;cursor:pointer}
  .who input{width:15px;height:15px;accent-color:var(--accent)}
  .chip{font-size:11px;color:var(--muted);background:#0b0d11;border:1px solid var(--line);
        border-radius:999px;padding:2px 8px}
  .chip.pr{color:var(--in);border-color:#20392c}

  /* save bar */
  .savebar{position:sticky;bottom:0;background:linear-gradient(180deg,rgba(15,17,21,0),var(--bg) 40%);
           padding:14px 18px;display:flex;gap:12px;align-items:center;flex-wrap:wrap}

  @media (max-width: 760px){
    .app{flex-direction:column}
    .side{width:auto;flex:none;height:auto;position:sticky;top:0;z-index:20;
          flex-direction:row;align-items:center;gap:6px;padding:10px;overflow-x:auto}
    .brand{padding:0 8px 0 4px;font-size:15px;white-space:nowrap}
    .nav{width:auto;padding:8px 12px;white-space:nowrap}
    .sidefoot{display:none}
    .wrap{padding:12px}
    .cards{grid-template-columns:repeat(2,1fr)} .card .v{font-size:16px} .big{grid-column:span 2}
    .mctl{display:flex}
    .tablewrap{overflow-x:visible} table{min-width:0} thead{display:none}
    tbody tr{display:block;padding:10px 10px 12px;border-bottom:1px solid var(--line)}
    tbody td{display:flex;align-items:center;gap:10px;border:0;padding:3px 0}
    tbody td::before{content:attr(data-l);color:var(--muted);font-size:12px;min-width:76px;flex:0 0 76px}
    tbody td.act{justify-content:flex-end;gap:8px;padding-top:8px}
    tbody td.act::before{content:''}
    tr.sub{border-left:2px solid var(--accent);background:#12161d;margin-left:14px;padding-top:6px}
    tr.sub td.ic{padding-left:0}
    tbody tr.sub td,tbody tr.hask td{border-bottom:0}
    td.amt input{text-align:left}
    .cal{border-radius:10px}
    .calhead div{font-size:10px;padding:6px 2px}
    .day{min-height:62px;padding:3px;gap:2px}
    .day .plus{display:none}
    .pill{padding:2px 4px;font-size:10px;border-left-width:4px}
    .pill .pt,.pill .pc{display:none}
    .pill{height:7px;border-radius:3px;border-top:0;border-bottom:0;border-right:0}
    .cal.week .day{min-height:120px}
    .cal.week .pill{height:auto;border:1px solid var(--line);border-left:3px solid var(--muted);
         border-radius:6px;padding:4px 6px;font-size:12px}
    .cal.week .pill .pt{display:block}
    .calbar .ttl{min-width:0;flex:1}
  }
</style></head>
<body>
<div class="app">
  <aside class="side">
    <div class="brand">&#128141; __TITLE__</div>
    <button class="nav on" id="nav-fin" onclick="setView('fin')"><span class="ic">&#128176;</span> Keuangan</button>
    <button class="nav" id="nav-kan" onclick="setView('kan')"><span class="ic">&#9745;</span> To-do <span class="ct" id="kan-ct">0</span></button>
    <div class="sidefoot">bersama &middot; @bang</div>
  </aside>

  <main class="main">
    <div class="wrap">

      <!-- ============== KEUANGAN ============== -->
      <section id="v-fin" class="view on">
        <div class="cards" id="cards"></div>
        <div class="tabs">
          <button class="tab" id="tab-income"  onclick="setTab('income')">Pemasukan</button>
          <button class="tab" id="tab-expense" onclick="setTab('expense')">Pengeluaran</button>
        </div>
        <div class="mctl">
          <input id="msearch" placeholder="cari item, kategori, nominal..." oninput="setSearch(this.value)">
          <select id="msort" onchange="setSortSel(this.value)"></select>
        </div>
        <div class="bar">
          <button class="btn" onclick="addTop()">+ Tambah baris</button>
          <button class="btn" onclick="clearFilters()">Bersihkan filter</button>
          <button class="btn" onclick="toggAll()">Buka/tutup rincian</button>
          <span class="muted">Nominal boleh 5000000 atau 5.000.000 &middot; pakai &ldquo;+ sub&rdquo; untuk rincian</span>
        </div>
        <div class="tablewrap">
          <table>
            <thead><tr id="head"></tr><tr class="filters" id="filters"></tr></thead>
            <tbody id="rows"></tbody>
          </table>
          <div class="pg" id="pager"></div>
        </div>
        <h2>Catatan</h2>
        <textarea id="notes" spellcheck="false" oninput="DATA.notes=this.value"></textarea>
      </section>

      <!-- ============== TO-DO ============== -->
      <section id="v-kan" class="view">
        <div class="calbar">
          <button class="btn" onclick="shift(-1)">&lsaquo;</button>
          <button class="btn" onclick="today()">Hari ini</button>
          <button class="btn" onclick="shift(1)">&rsaquo;</button>
          <span class="ttl" id="caltitle"></span>
          <div class="seg">
            <button id="seg-week" onclick="setMode('week')">Minggu</button>
            <button id="seg-month" onclick="setMode('month')">Bulan</button>
          </div>
          <input id="ksearch" placeholder="cari to-do..." oninput="KQ=this.value;renderBoard()" style="max-width:220px">
        </div>
        <div class="cal" id="cal">
          <div class="calhead" id="calhead"></div>
          <div class="calgrid" id="calgrid"></div>
        </div>
        <div class="nodate">
          <h2 style="margin-bottom:8px">Tanpa tanggal <span class="chip" id="nd-ct"></span></h2>
          <div class="list" id="nodate"></div>
          <button class="btn" style="margin-top:8px" onclick="addTask('')">+ to-do tanpa tanggal</button>
        </div>
      </section>

    </div>

    <div class="savebar">
      <button class="primary" onclick="save()">Simpan</button>
      <span id="status" class="ok"></span>
      <span class="muted">Simpan terakhir yang menang.</span>
    </div>
  </main>
</div>
<div class="ov" id="ov" onclick="closeDrw()"></div>
<div class="drw" id="drw"></div>

<script>
const TOKEN = "__TOKEN__";
let DATA = __DATA__;
const MAIL = __MAIL__;
DATA.entries = DATA.entries || []; DATA.tasks = DATA.tasks || [];
DATA.entries.forEach(e=>{ if(!e.parent) e.parent=''; });
DATA.tasks.forEach(t=>{ if(!t.parent) t.parent=''; });

const esc = s => String(s==null?'':s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const tmp = () => 'tmp-'+Math.random().toString(36).slice(2,9);

/* ================= view switching ================= */
let VIEW='fin';
function setView(v){
  VIEW=v;
  document.getElementById('v-fin').className='view'+(v==='fin'?' on':'');
  document.getElementById('v-kan').className='view'+(v==='kan'?' on':'');
  document.getElementById('nav-fin').className='nav'+(v==='fin'?' on':'');
  document.getElementById('nav-kan').className='nav'+(v==='kan'?' on':'');
  if(v==='kan') renderBoard();
}

/* ================= KEUANGAN ================= */
const COLS = [
  {k:'status',   t:'Status',   w:'120px'},
  {k:'item',     t:'Item',     w:''},
  {k:'amount',   t:'Nominal',  w:'150px'},
  {k:'category', t:'Kategori', w:'140px'},
  {k:'date',     t:'Tanggal',  w:'150px'},
];
const ST = { income:{sort:{k:'item',d:1},f:{},q:'',page:1}, expense:{sort:{k:'item',d:1},f:{},q:'',page:1} };
let TAB='expense'; const PAGE_SIZE=10;

/* Sub-items start folded; SUBOPEN holds the parents the viewer has expanded.
   Stored per browser, so a refresh keeps whatever you had open. */
let SUBOPEN = new Set();
try{ SUBOPEN = new Set(JSON.parse(localStorage.getItem('expanded')||'[]')); }catch(err){}
const saveOpen = () => { try{ localStorage.setItem('expanded',JSON.stringify([...SUBOPEN])); }catch(err){} };
function togg(id){ SUBOPEN.has(id)?SUBOPEN.delete(id):SUBOPEN.add(id); saveOpen(); render(); }
function toggAll(){ const tops=DATA.entries.filter(e=>e.kind===TAB&&!e.parent&&kids(e.id).length);
  const anyShut=tops.some(e=>!SUBOPEN.has(e.id));
  tops.forEach(e=>{ anyShut?SUBOPEN.add(e.id):SUBOPEN.delete(e.id); }); saveOpen(); render(); }

const rp = n => { n=Math.round(Number(n)||0); return (n<0?'-':'')+'Rp '+Math.abs(n).toLocaleString('id-ID'); };
const digits = s => { const neg=String(s).trim().startsWith('-');
  const d=String(s||'').replace(/[^0-9]/g,''); const n=d?parseInt(d,10):0; return neg?-n:n; };
const byId = id => DATA.entries.find(e=>e.id===id);
const kids = id => DATA.entries.filter(e=>e.parent===id);
const amountOf = e => { const k=kids(e.id); return k.length ? k.reduce((a,c)=>a+amountOf(c),0) : (Number(e.amount)||0); };
const countTop = k => DATA.entries.filter(e=>e.kind===k && !e.parent).length;

function updateSummary(){
  const all=DATA.entries, parents=new Set(all.filter(e=>e.parent).map(e=>e.parent));
  const lv=all.filter(e=>!parents.has(e.id));
  const t=(k,s)=>lv.filter(e=>e.kind===k&&e.status===s).reduce((a,e)=>a+(Number(e.amount)||0),0);
  const ia=t('income','actual'), ie=t('income','expected'), ea=t('expense','actual'), ee=t('expense','expected');
  const cards=[
    ['Uang di tangan', rp(ia-ea), 'diterima - dibayar', (ia-ea)>=0?'in':'out', true],
    ['Saldo proyeksi', rp((ia+ie)-(ea+ee)), 'semua pemasukan - pengeluaran', ((ia+ie)-(ea+ee))>=0?'in':'out', true],
    ['Pemasukan diterima', rp(ia), '', 'in', false],
    ['Pemasukan diharapkan', rp(ie), '', 'in', false],
    ['Pengeluaran dibayar', rp(ea), '', 'out', false],
    ['Pengeluaran rencana', rp(ee), '', 'out', false],
  ];
  document.getElementById('cards').innerHTML = cards.map(function(c){
    return '<div class="card'+(c[4]?' big':'')+'"><div class="l">'+c[0]+'</div>'+
           '<div class="v '+c[3]+'">'+c[1]+'</div>'+(c[2]?'<div class="s">'+c[2]+'</div>':'')+'</div>'; }).join('');
  document.getElementById('tab-income').textContent='Pemasukan ('+countTop('income')+')';
  document.getElementById('tab-expense').textContent='Pengeluaran ('+countTop('expense')+')';
}

const fieldText = (o,k) => k==='amount' ? String(amountOf(o))
  : k==='status' ? (o.status==='actual'?'sudah':'rencana') : String(o[k]||'');

function visibleTop(){
  const st=ST[TAB]; let rows=DATA.entries.filter(e=>e.kind===TAB && !e.parent);
  const q=(st.q||'').trim().toLowerCase();
  if(q) rows=rows.filter(function(e){
    const hit=o=>COLS.some(c=>fieldText(o,c.k).toLowerCase().indexOf(q)!==-1);
    return hit(e)||kids(e.id).some(hit); });
  COLS.forEach(function(c){
    const f=(st.f[c.k]||'').trim().toLowerCase(); if(!f) return;
    rows=rows.filter(function(e){
      const hit=o=>fieldText(o,c.k).toLowerCase().indexOf(f)!==-1;
      return hit(e)||kids(e.id).some(hit); }); });
  const k=st.sort.k,d=st.sort.d;
  rows.sort(function(a,b){ let x,y;
    if(k==='amount'){x=amountOf(a);y=amountOf(b);}
    else{x=String(a[k]||'').toLowerCase();y=String(b[k]||'').toLowerCase();
         if(!x&&y)return 1; if(x&&!y)return -1;}
    return x<y?-d:x>y?d:0; });
  return rows;
}
const hasFilter=()=>COLS.some(c=>(ST[TAB].f[c.k]||'').trim());

function renderHead(){
  const st=ST[TAB];
  document.getElementById('head').innerHTML=COLS.map(function(c){
    const on=st.sort.k===c.k, ar=on?(st.sort.d>0?'&#9650;':'&#9660;'):'&#8645;';
    return '<th class="s" style="'+(c.w?'width:'+c.w:'')+'" onclick="sortBy(\''+c.k+'\')">'+c.t+' <span class="ar">'+ar+'</span></th>';
  }).join('')+'<th style="width:150px"></th>';
  document.getElementById('filters').innerHTML=COLS.map(function(c){
    return '<th><input placeholder="filter..." value="'+esc(st.f[c.k]||'')+'" oninput="setFilter(\''+c.k+'\', this.value)"></th>';
  }).join('')+'<th></th>';
}
function rowHtml(e,isSub,isLast){
  const k=kids(e.id), computed=k.length>0, amt=computed?amountOf(e):(Number(e.amount)||0);
  const open=computed&&SUBOPEN.has(e.id);
  const cls=(isSub?'sub':'')+(computed&&open?' hask':'')+(isSub&&isLast?' lastsub':'');
  const caret=isSub?'<span class="tw">&#8627;</span>'
    : computed ? '<button class="cr" title="buka/tutup rincian" onclick="togg(\''+e.id+'\')">'+
        (open?'&#9662;':'&#9656;')+'<b>'+k.length+'</b></button>'
    : '<span class="cr ph"></span>';
  const sel='<select onchange="upd(\''+e.id+'\',\'status\',this.value)">'+
    '<option value="actual"'+(e.status==='actual'?' selected':'')+'>Sudah</option>'+
    '<option value="expected"'+(e.status==='expected'?' selected':'')+'>Rencana</option></select>';
  return '<tr class="'+cls+'" data-id="'+e.id+'">'+
    '<td data-l="Status">'+sel+'</td>'+
    '<td class="ic" data-l="Item">'+caret+'<input value="'+esc(e.item)+'" '+
      'placeholder="'+(isSub?'rincian...':'mis. Administrasi KUA')+'" oninput="upd(\''+e.id+'\',\'item\',this.value)"></td>'+
    '<td class="amt" data-l="Nominal"><input inputmode="numeric" '+(computed?'disabled title="total dari sub-item"':'')+' '+
      'value="'+(amt?amt.toLocaleString('id-ID'):'')+'" oninput="upd(\''+e.id+'\',\'amount\',digits(this.value))" '+
      'onblur="this.value=this.value?digits(this.value).toLocaleString(\'id-ID\'):\'\'"></td>'+
    '<td data-l="Kategori"><input value="'+esc(e.category)+'" oninput="upd(\''+e.id+'\',\'category\',this.value)"></td>'+
    '<td data-l="Tanggal"><input type="date" value="'+esc(e.date)+'" oninput="upd(\''+e.id+'\',\'date\',this.value)"></td>'+
    '<td class="act">'+(isSub?'':'<button class="btn" onclick="addSub(\''+e.id+'\')">+ sub</button> ')+
      '<button class="btn del" onclick="del(\''+e.id+'\')">&#10005;</button></td></tr>';
}
function render(){
  renderHead();
  const st=ST[TAB], rows=visibleTop(), pages=Math.max(1,Math.ceil(rows.length/PAGE_SIZE));
  if(st.page>pages) st.page=pages;
  const slice=rows.slice((st.page-1)*PAGE_SIZE, st.page*PAGE_SIZE);
  let h=''; slice.forEach(function(e){ const k=kids(e.id); h+=rowHtml(e,false,false);
    if(SUBOPEN.has(e.id)) k.forEach(function(c,i){h+=rowHtml(c,true,i===k.length-1);}); });
  document.getElementById('rows').innerHTML = h ||
    '<tr><td colspan="6" class="empty">Belum ada data'+(hasFilter()?' yang cocok dengan filter':'')+'.</td></tr>';
  document.getElementById('pager').innerHTML=
    '<span class="muted">'+rows.length+' baris utama &middot; halaman '+st.page+'/'+pages+'</span>'+
    '<button class="btn" '+(st.page<=1?'disabled':'')+' onclick="go(-1)">&lsaquo; Sebelumnya</button>'+
    '<button class="btn" '+(st.page>=pages?'disabled':'')+' onclick="go(1)">Berikutnya &rsaquo;</button>';
  document.getElementById('tab-income').className='tab'+(TAB==='income'?' on':'');
  document.getElementById('tab-expense').className='tab'+(TAB==='expense'?' on':'');
  syncMobile(); updateSummary(); updateKanCount();
}
function syncMobile(){
  const st=ST[TAB], sel=document.getElementById('msort');
  sel.innerHTML=COLS.map(function(c){
    return '<option value="'+c.k+':1"'+(st.sort.k===c.k&&st.sort.d>0?' selected':'')+'>'+c.t+' ↑</option>'+
           '<option value="'+c.k+':-1"'+(st.sort.k===c.k&&st.sort.d<0?' selected':'')+'>'+c.t+' ↓</option>';
  }).join('');
  document.getElementById('msearch').value=st.q||'';
}
function setSearch(v){ ST[TAB].q=v; ST[TAB].page=1; render(); }
function setSortSel(v){ const p=v.split(':'); ST[TAB].sort={k:p[0],d:parseInt(p[1],10)}; render(); }
function setTab(t){ TAB=t; render(); }
function sortBy(k){ const s=ST[TAB].sort; s.d=(s.k===k)?-s.d:1; s.k=k; render(); }
function setFilter(k,v){ ST[TAB].f[k]=v; ST[TAB].page=1; render(); }
function clearFilters(){ ST[TAB].f={}; ST[TAB].q=''; ST[TAB].page=1; render(); }
function go(d){ ST[TAB].page+=d; render(); }
function upd(id,k,v){ const e=byId(id); if(!e) return; e[k]=v; if(k==='amount'||k==='status') updateSummary(); }
function addTop(){ DATA.entries.push({id:tmp(),kind:TAB,status:'expected',item:'',amount:0,category:'',date:'',parent:''});
  ST[TAB].page=Math.max(1,Math.ceil(visibleTop().length/PAGE_SIZE)); render(); }
function addSub(pid){ const p=byId(pid); if(!p) return;
  DATA.entries.push({id:tmp(),kind:p.kind,status:p.status,item:'',amount:0,category:p.category||'',date:'',parent:pid});
  SUBOPEN.add(pid); saveOpen(); render(); }
function del(id){ DATA.entries=DATA.entries.filter(e=>e.id!==id&&e.parent!==id); render(); }

/* ================= TO-DO (calendar) =================
   Tasks live on a calendar keyed by `due`. Status is no longer a column --
   it is a coloured state shown on the pill and edited in the detail drawer.
   A task with a parent is a checklist item inside that parent, never a pill. */
const KST={todo:['Rencana','#6b7280'],doing:['Proses','#2f6df6'],done:['Selesai','#39d98a']};
const KORDER=['todo','doing','done'];
const DAYS=['Sen','Sel','Rab','Kam','Jum','Sab','Min'];
const MONTHS=['Januari','Februari','Maret','April','Mei','Juni','Juli','Agustus',
              'September','Oktober','November','Desember'];
let KQ='', CALMODE='month', CUR=new Date(), SEL=null, EXPDAY={};

const tById = id => DATA.tasks.find(t=>t.id===id);
const tKids = id => DATA.tasks.filter(t=>t.parent===id);
const pad2 = n => (n<10?'0':'')+n;
const iso = d => d.getFullYear()+'-'+pad2(d.getMonth()+1)+'-'+pad2(d.getDate());
const dayAdd = (d,n) => { const x=new Date(d); x.setDate(x.getDate()+n); return x; };
function weekStart(d){ const x=new Date(d); x.setHours(0,0,0,0);
  x.setDate(x.getDate()-((x.getDay()+6)%7)); return x; }   /* weeks start Monday */

function matches(c){
  const q=KQ.trim().toLowerCase(); if(!q) return true;
  const hit=o=>((o.title||'')+' '+(o.detail||'')+' '+(o.category||'')).toLowerCase().indexOf(q)!==-1;
  return hit(c)||tKids(c.id).some(hit);
}
const topTasks = () => DATA.tasks.filter(t=>!t.parent && matches(t));
const tasksOn  = ds => topTasks().filter(t=>(t.due||'')===ds);

function updateKanCount(){
  const open=DATA.tasks.filter(t=>!t.parent&&t.status!=='done').length;
  document.getElementById('kan-ct').textContent=open;
}
function setMode(m){ CALMODE=m; renderBoard(); }
function shift(n){ CUR = CALMODE==='month'
    ? new Date(CUR.getFullYear(), CUR.getMonth()+n, 1)
    : dayAdd(CUR, 7*n);
  renderBoard(); }
function today(){ CUR=new Date(); renderBoard(); }

/* true when the scheduler would mail about this to-do */
function armed(t){
  if(!MAIL.enabled || !t.due || t.status==='done') return false;
  const lead=(t.remind||MAIL.default_lead||'');
  if(lead==='off') return false;
  return !!((t.remind_to||'').trim() || (MAIL.default_to||'').trim());
}
function pillHtml(t){
  const st=KST[t.status]||KST.todo, ks=tKids(t.id), done=ks.filter(k=>k.status==='done').length;
  return '<button class="pill'+(t.status==='done'?' done':'')+'" draggable="true"'+
    ' style="border-left-color:'+st[1]+'" title="'+esc(t.title)+' - '+st[0]+'"'+
    ' ondragstart="dstart(event,\'' + t.id + '\')" ondragend="dend(event)"'+
    ' onclick="openTask(\'' + t.id + '\')">'+
    '<span class="pt">'+esc(t.title||'(tanpa judul)')+'</span>'+
    (armed(t)?'<span class="pc" title="ada pengingat email">&#9993;</span>':'')+
    (ks.length?'<span class="pc">'+done+'/'+ks.length+'</span>':'')+'</button>';
}
function dayCell(d, outside){
  const ds=iso(d), list=tasksOn(ds), isToday=ds===iso(new Date());
  const cap = CALMODE==='week' ? 99 : (EXPDAY[ds]?99:3);
  const shown=list.slice(0,cap), rest=list.length-shown.length;
  return '<div class="day'+(outside?' out':'')+(isToday?' today':'')+'" id="d-'+ds+'"'+
    ' ondragover="dover(event,\'' + ds + '\')" ondragleave="dleave(\'' + ds + '\')"'+
    ' ondrop="drop(event,\'' + ds + '\')">'+
    '<div class="dn">'+d.getDate()+'</div>'+
    '<button class="plus" title="tambah to-do" onclick="addTask(\'' + ds + '\')">+</button>'+
    shown.map(pillHtml).join('')+
    (rest>0?'<button class="more" onclick="EXPDAY[\'' + ds + '\']=1;renderBoard()">+'+rest+' lagi</button>':'')+
    '</div>';
}
function renderBoard(){
  const cal=document.getElementById('cal');
  cal.className='cal'+(CALMODE==='week'?' week':'');
  document.getElementById('calhead').innerHTML=DAYS.map(d=>'<div>'+d+'</div>').join('');
  document.getElementById('seg-week').className  = CALMODE==='week'?'on':'';
  document.getElementById('seg-month').className = CALMODE==='month'?'on':'';

  let cells='', title='';
  if(CALMODE==='month'){
    const first=new Date(CUR.getFullYear(),CUR.getMonth(),1);
    const start=weekStart(first);
    const lead=(first.getDay()+6)%7, days=new Date(CUR.getFullYear(),CUR.getMonth()+1,0).getDate();
    const weeks=Math.ceil((lead+days)/7);
    for(let n=0;n<weeks*7;n++){ const d=dayAdd(start,n);
      cells+=dayCell(d, d.getMonth()!==CUR.getMonth()); }
    title=MONTHS[CUR.getMonth()]+' '+CUR.getFullYear();
  }else{
    const start=weekStart(CUR), endd=dayAdd(start,6);
    for(let n=0;n<7;n++) cells+=dayCell(dayAdd(start,n), false);
    title=start.getDate()+' '+MONTHS[start.getMonth()].slice(0,3)+' &ndash; '+
          endd.getDate()+' '+MONTHS[endd.getMonth()].slice(0,3)+' '+endd.getFullYear();
  }
  document.getElementById('calgrid').innerHTML=cells;
  document.getElementById('caltitle').innerHTML=title;

  const nd=topTasks().filter(t=>!t.due);
  document.getElementById('nodate').innerHTML = nd.map(pillHtml).join('') ||
    '<span class="muted">semua to-do sudah punya tanggal.</span>';
  document.getElementById('nd-ct').textContent=nd.length;
  updateKanCount();
}

/* ---- detail drawer ---- */
function openTask(id){ SEL=id; renderDrw();
  document.getElementById('ov').classList.add('on');
  document.getElementById('drw').classList.add('on'); }
function closeDrw(){ SEL=null;
  document.getElementById('ov').classList.remove('on');
  document.getElementById('drw').classList.remove('on');
  renderBoard(); }
function renderDrw(){
  const c=SEL?tById(SEL):null; const el=document.getElementById('drw');
  if(!c){ el.innerHTML=''; return; }
  const ks=tKids(c.id), done=ks.filter(k=>k.status==='done').length;
  const sts=KORDER.map(function(k){ const st=KST[k];
    return '<button class="'+(c.status===k?'on':'')+'" style="color:'+st[1]+
      (c.status===k?';border-color:'+st[1]+';background:'+st[1]+'22':'')+'"'+
      ' onclick="setStatus(\'' + c.id + '\',\'' + k + '\')">'+
      '<span class="dot"></span>'+st[0]+'</button>'; }).join('');
  const ck=ks.map(function(k){
    return '<div class="ck'+(k.status==='done'?' done':'')+'">'+
      '<input type="checkbox" '+(k.status==='done'?'checked':'')+
        ' onchange="tgl(\'' + k.id + '\',this.checked)">'+
      '<input class="cx" value="'+esc(k.title)+'" oninput="tupd(\'' + k.id + '\',\'title\',this.value)">'+
      '<button class="btn del" onclick="tdel(\'' + k.id + '\')">&#10005;</button></div>'; }).join('');
  el.innerHTML=
    '<h3>Rincian to-do <button class="btn x" onclick="closeDrw()">&#10005;</button></h3>'+
    '<label>Judul</label>'+
    '<input value="'+esc(c.title)+'" placeholder="mis. Cari venue" oninput="tupd(\'' + c.id + '\',\'title\',this.value)">'+
    '<label>Status</label><div class="stsel">'+sts+'</div>'+
    '<label>Tanggal &amp; jam</label>'+
    '<div class="trow" style="margin:0">'+
      '<input style="flex:2;min-width:140px" type="date" value="'+esc(c.due)+'" '+
        'onchange="setDue(\'' + c.id + '\',this.value)">'+
      '<input style="flex:1;min-width:96px" type="time" value="'+esc(c.time)+'" '+
        'onchange="setTime(\'' + c.id + '\',this.value)" title="kosong = jam '+esc(MAIL.default_time)+'">'+
    '</div>'+
    remindHtml(c)+
    '<label>Kategori</label>'+
    '<input value="'+esc(c.category)+'" placeholder="mis. akad" oninput="tupd(\'' + c.id + '\',\'category\',this.value)">'+
    '<label>Catatan</label>'+
    '<textarea style="min-height:90px" placeholder="catatan..." oninput="tupd(\'' + c.id + '\',\'detail\',this.value)">'+esc(c.detail)+'</textarea>'+
    '<label>Checklist '+(ks.length?'<span class="chip pr">'+done+'/'+ks.length+'</span>':'')+'</label>'+
    '<div>'+(ck||'<span class="muted" style="font-size:12px">belum ada.</span>')+'</div>'+
    '<div class="trow">'+
      '<button class="btn" onclick="addCk(\'' + c.id + '\')">+ checklist</button>'+
      '<button class="btn del" onclick="tdel(\'' + c.id + '\');closeDrw()">Hapus to-do</button>'+
    '</div>';
}
/* edits that change where/how a pill is drawn redraw the calendar too; typing
   in a text field only updates DATA, so the input never loses focus. */
function tupd(id,k,v){ const t=tById(id); if(!t) return; t[k]=v; }
function setTime(id,v){ tupd(id,'time',v); renderDrw(); }

/* ---- reminder controls (email, via Brevo) ---- */
const LEADS=[['','default ('+(MAIL.default_lead||'1d')+')'],['off','jangan ingatkan'],
             ['15m','15 menit'],['30m','30 menit'],['1h','1 jam'],['3h','3 jam'],
             ['1d','1 hari'],['2d','2 hari'],['1w','1 minggu']];
function remindHtml(c){
  if(!MAIL.enabled)
    return '<label>Pengingat</label><div class="muted" style="font-size:12px">'+
           'email mati: '+esc(MAIL.why||'belum dikonfigurasi')+'</div>';
  const to=(c.remind_to||'').split(',').map(s=>s.trim().toLowerCase()).filter(Boolean);
  const opts=LEADS.map(function(l){
    return '<option value="'+l[0]+'"'+((c.remind||'')===l[0]?' selected':'')+'>'+l[1]+'</option>';
  }).join('');
  const who=(MAIL.people||[]).map(function(n){
    const on=to.length?to.indexOf(n)!==-1:false;
    return '<label class="who"><input type="checkbox" '+(on?'checked':'')+
      ' onchange="setWho(\''+c.id+'\',\''+n+'\',this.checked)"> '+esc(n)+'</label>';
  }).join('') || '<span class="muted" style="font-size:12px">MAIL_PEOPLE belum diisi</span>';
  const note = !c.due ? 'kasih tanggal dulu biar bisa diingatkan'
    : (c.remind==='off' ? 'pengingat dimatikan untuk to-do ini'
    : (to.length?'':'belum dipilih &rarr; pakai default ('+esc(MAIL.default_to||'tidak ada')+')'));
  return '<label>Pengingat email</label>'+
    '<select onchange="setRemind(\''+c.id+'\',this.value)">'+opts+'</select>'+
    '<div class="whos">'+who+'</div>'+
    (note?'<div class="muted" style="font-size:12px">'+note+'</div>':'');
}
function setRemind(id,v){ tupd(id,'remind',v); renderDrw(); }
function setWho(id,name,on){
  const t=tById(id); if(!t) return;
  const cur=(t.remind_to||'').split(',').map(s=>s.trim()).filter(Boolean);
  const i=cur.map(s=>s.toLowerCase()).indexOf(name);
  if(on && i===-1) cur.push(name);
  if(!on && i!==-1) cur.splice(i,1);
  t.remind_to=cur.join(','); renderDrw();
}
function setStatus(id,v){ tupd(id,'status',v); renderDrw(); renderBoard(); }
function setDue(id,v){ tupd(id,'due',v); renderBoard(); }
function tgl(id,on){ const t=tById(id); if(!t) return; t.status=on?'done':'todo'; renderDrw(); renderBoard(); }
function addTask(due){ const id=tmp();
  DATA.tasks.push({id:id,title:'',detail:'',status:'todo',category:'',due:due||'',parent:''});
  renderBoard(); openTask(id);
  const el=document.querySelector('#drw input'); if(el) el.focus(); }
function addCk(pid){ const p=tById(pid); if(!p) return;
  DATA.tasks.push({id:tmp(),title:'',detail:'',status:'todo',category:'',due:'',parent:pid});
  renderDrw(); renderBoard(); }
function tdel(id){ DATA.tasks=DATA.tasks.filter(t=>t.id!==id&&t.parent!==id); renderDrw(); renderBoard(); }

/* ---- drag a pill onto another day to reschedule ---- */
let DRAG=null;
function dstart(ev,id){ DRAG=id; ev.dataTransfer.effectAllowed='move';
  try{ev.dataTransfer.setData('text/plain',id);}catch(e){} }
function dend(ev){ DRAG=null; }
function dover(ev,ds){ ev.preventDefault(); const c=document.getElementById('d-'+ds); if(c)c.classList.add('over'); }
function dleave(ds){ const c=document.getElementById('d-'+ds); if(c)c.classList.remove('over'); }
function drop(ev,ds){ ev.preventDefault();
  const id=DRAG||(ev.dataTransfer?ev.dataTransfer.getData('text/plain'):'');
  const t=id?tById(id):null; if(t) t.due=ds; DRAG=null; renderBoard(); }

/* ================= save ================= */
async function save(){
  const body={
    entries:DATA.entries.filter(e=>e.item||e.amount||kids(e.id).length),
    tasks:DATA.tasks.filter(t=>(t.title||'').trim()),
    notes:document.getElementById('notes').value };
  const st=document.getElementById('status'); st.textContent='menyimpan...';
  try{
    const r=await fetch('/api/plan?token='+encodeURIComponent(TOKEN),
      {method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(body)});
    if(!r.ok) throw new Error(r.status);
    DATA=await r.json();
    DATA.entries=DATA.entries||[]; DATA.tasks=DATA.tasks||[];
    DATA.entries.forEach(e=>{ if(!e.parent) e.parent=''; });
    DATA.tasks.forEach(t=>{ if(!t.parent) t.parent=''; });
    document.getElementById('notes').value=DATA.notes||'';
    render(); if(VIEW==='kan') renderBoard();
    st.textContent='tersimpan ✓'; setTimeout(function(){st.textContent='';},2500);
  }catch(e){ st.textContent='gagal menyimpan: '+e.message; }
}

document.getElementById('notes').value = DATA.notes || '';
render();
</script>
</body></html>"""
