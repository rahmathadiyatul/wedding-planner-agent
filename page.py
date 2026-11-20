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


def render(token: str, title: str, entries: list, notes: str, tasks: list) -> str:
    payload = json.dumps({"entries": entries, "notes": notes, "tasks": tasks},
                         ensure_ascii=False)
    return (_PAGE
            .replace("__TITLE__", html.escape(title))
            .replace("__TOKEN__", html.escape(token))
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

  /* kanban */
  .board{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;align-items:start}
  .col{background:#12161d;border:1px solid var(--line);border-radius:12px;display:flex;
       flex-direction:column;min-height:160px}
  .col.over{border-color:var(--accent);background:#141c2b}
  .colhead{display:flex;align-items:center;gap:8px;padding:11px 12px;border-bottom:1px solid var(--line)}
  .colhead .dot{width:8px;height:8px;border-radius:50%}
  .colhead .n{font-weight:700;font-size:14px}
  .colhead .c{margin-left:auto;color:var(--muted);font-size:12px}
  .collist{padding:10px;display:flex;flex-direction:column;gap:10px}
  .tcard{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px;cursor:grab}
  .tcard.drag{opacity:.45}
  .tcard .th{display:flex;align-items:flex-start;gap:8px}
  .tcard .tt{flex:1;font-size:14px;font-weight:600;line-height:1.35;word-break:break-word}
  .tcard .meta{display:flex;gap:6px;flex-wrap:wrap;margin-top:7px;align-items:center}
  .chip{font-size:11px;color:var(--muted);background:#0b0d11;border:1px solid var(--line);
        border-radius:999px;padding:2px 8px}
  .chip.due{color:var(--warn);border-color:#3a3220}
  .chip.pr{color:var(--in);border-color:#20392c}
  .tbody{margin-top:9px;border-top:1px solid var(--line);padding-top:9px;display:none}
  .tcard.open .tbody{display:block}
  .ck{display:flex;align-items:center;gap:8px;padding:3px 0}
  .ck input[type=checkbox]{width:16px;height:16px;flex:0 0 16px;accent-color:var(--accent)}
  .ck .cx{flex:1;font-size:13px;background:transparent;border:0;padding:2px;color:var(--fg)}
  .ck.done .cx{text-decoration:line-through;color:var(--muted)}
  .ck .btn{padding:2px 6px}
  .trow{display:flex;gap:6px;margin-top:8px;flex-wrap:wrap}
  .trow .btn{flex:0 0 auto}
  .addcard{margin:0 10px 10px;border:1px dashed var(--line);color:var(--muted);background:transparent;
           border-radius:10px;padding:9px;cursor:pointer;font-size:13px}
  .addcard:hover{border-color:var(--accent);color:var(--fg)}

  /* save bar */
  .savebar{position:sticky;bottom:0;background:linear-gradient(180deg,rgba(15,17,21,0),var(--bg) 40%);
           padding:14px 18px;display:flex;gap:12px;align-items:center;flex-wrap:wrap}

  @media (max-width: 900px){ .board{grid-template-columns:1fr} }
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
    .tcard{cursor:default}
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
        <div class="bar">
          <input id="ksearch" placeholder="cari to-do..." oninput="KQ=this.value;renderBoard()" style="max-width:280px">
          <span class="muted">Seret kartu antar kolom (di HP pakai tombol &lsaquo; &rsaquo;) &middot; klik kartu untuk rincian</span>
        </div>
        <div class="board" id="board"></div>
      </section>

    </div>

    <div class="savebar">
      <button class="primary" onclick="save()">Simpan</button>
      <span id="status" class="ok"></span>
      <span class="muted">Simpan terakhir yang menang.</span>
    </div>
  </main>
</div>

<script>
const TOKEN = "__TOKEN__";
let DATA = __DATA__;
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

/* Sub-items start folded; OPEN holds the parents the viewer has expanded.
   Stored per browser, so a refresh keeps whatever you had open. */
let OPEN = new Set();
try{ OPEN = new Set(JSON.parse(localStorage.getItem('expanded')||'[]')); }catch(err){}
const saveOpen = () => { try{ localStorage.setItem('expanded',JSON.stringify([...OPEN])); }catch(err){} };
function togg(id){ OPEN.has(id)?OPEN.delete(id):OPEN.add(id); saveOpen(); render(); }
function toggAll(){ const tops=DATA.entries.filter(e=>e.kind===TAB&&!e.parent&&kids(e.id).length);
  const anyShut=tops.some(e=>!OPEN.has(e.id));
  tops.forEach(e=>{ anyShut?OPEN.add(e.id):OPEN.delete(e.id); }); saveOpen(); render(); }

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
  const open=computed&&OPEN.has(e.id);
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
    if(OPEN.has(e.id)) k.forEach(function(c,i){h+=rowHtml(c,true,i===k.length-1);}); });
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
  OPEN.add(pid); saveOpen(); render(); }
function del(id){ DATA.entries=DATA.entries.filter(e=>e.id!==id&&e.parent!==id); render(); }

/* ================= TO-DO (kanban) ================= */
const KCOLS=[['todo','Rencana','#6b7280'],['doing','Proses','#2f6df6'],['done','Selesai','#39d98a']];
let KQ='', OPEN={};
const tById = id => DATA.tasks.find(t=>t.id===id);
const tKids = id => DATA.tasks.filter(t=>t.parent===id);
const cards = st => DATA.tasks.filter(t=>!t.parent && t.status===st);

function updateKanCount(){
  const open=DATA.tasks.filter(t=>!t.parent&&t.status!=='done').length;
  document.getElementById('kan-ct').textContent=open;
}
function matches(c){
  const q=KQ.trim().toLowerCase(); if(!q) return true;
  const hit=o=>((o.title||'')+' '+(o.detail||'')+' '+(o.category||'')).toLowerCase().indexOf(q)!==-1;
  return hit(c)||tKids(c.id).some(hit);
}
function cardHtml(c){
  const ks=tKids(c.id), done=ks.filter(k=>k.status==='done').length;
  const idx=KCOLS.findIndex(x=>x[0]===c.status);
  const chips=[];
  if(ks.length) chips.push('<span class="chip pr">'+done+'/'+ks.length+'</span>');
  if(c.category) chips.push('<span class="chip">#'+esc(c.category)+'</span>');
  if(c.due) chips.push('<span class="chip due">'+esc(c.due)+'</span>');
  const ck=ks.map(function(k){
    return '<div class="ck'+(k.status==='done'?' done':'')+'">'+
      '<input type="checkbox" '+(k.status==='done'?'checked':'')+' onchange="tgl(\''+k.id+'\',this.checked)">'+
      '<input class="cx" value="'+esc(k.title)+'" oninput="tupd(\''+k.id+'\',\'title\',this.value)">'+
      '<button class="btn del" onclick="tdel(\''+k.id+'\')">&#10005;</button></div>'; }).join('');
  return '<div class="tcard'+(OPEN[c.id]?' open':'')+'" draggable="true" data-id="'+c.id+'"'+
    ' ondragstart="dstart(event,\''+c.id+'\')" ondragend="dend(event)">'+
    '<div class="th" onclick="toggleCard(event,\''+c.id+'\')">'+
      '<div class="tt">'+esc(c.title)+'</div></div>'+
    (chips.length?'<div class="meta">'+chips.join('')+'</div>':'')+
    '<div class="tbody">'+
      '<input value="'+esc(c.title)+'" oninput="tupd(\''+c.id+'\',\'title\',this.value)" placeholder="judul">'+
      '<textarea style="min-height:60px;margin-top:6px" placeholder="catatan..." '+
        'oninput="tupd(\''+c.id+'\',\'detail\',this.value)">'+esc(c.detail)+'</textarea>'+
      '<div class="trow">'+
        '<input style="flex:1;min-width:110px" value="'+esc(c.category)+'" placeholder="kategori" '+
          'oninput="tupd(\''+c.id+'\',\'category\',this.value)">'+
        '<input style="flex:1;min-width:140px" type="date" value="'+esc(c.due)+'" '+
          'oninput="tupd(\''+c.id+'\',\'due\',this.value)">'+
      '</div>'+
      (ck?'<div style="margin-top:8px">'+ck+'</div>':'')+
      '<div class="trow">'+
        '<button class="btn" onclick="addCk(\''+c.id+'\')">+ checklist</button>'+
        '<button class="btn" '+(idx<=0?'disabled':'')+' onclick="move(\''+c.id+'\',-1)">&lsaquo;</button>'+
        '<button class="btn" '+(idx>=KCOLS.length-1?'disabled':'')+' onclick="move(\''+c.id+'\',1)">&rsaquo;</button>'+
        '<button class="btn del" onclick="tdel(\''+c.id+'\')">Hapus</button>'+
      '</div>'+
    '</div></div>';
}
function renderBoard(){
  document.getElementById('board').innerHTML=KCOLS.map(function(col){
    const list=cards(col[0]).filter(matches);
    return '<div class="col" id="col-'+col[0]+'" ondragover="dover(event,\''+col[0]+'\')" '+
      'ondragleave="dleave(\''+col[0]+'\')" ondrop="drop(event,\''+col[0]+'\')">'+
      '<div class="colhead"><span class="dot" style="background:'+col[2]+'"></span>'+
        '<span class="n">'+col[1]+'</span><span class="c">'+list.length+'</span></div>'+
      '<div class="collist">'+(list.map(cardHtml).join('')||'<div class="empty" style="padding:14px">kosong</div>')+'</div>'+
      '<button class="addcard" onclick="addCard(\''+col[0]+'\')">+ tambah</button></div>';
  }).join('');
  updateKanCount();
}
function toggleCard(ev,id){
  if(ev.target.closest('input,textarea,button,select')) return;
  OPEN[id]=!OPEN[id]; renderBoard();
}
function tupd(id,k,v){ const t=tById(id); if(!t) return; t[k]=v;
  if(k==='title'||k==='category'||k==='due') { /* re-render on blur only to keep focus */ } }
function tgl(id,on){ const t=tById(id); if(!t) return; t.status=on?'done':'todo'; renderBoard(); }
function move(id,d){ const t=tById(id); if(!t) return;
  const i=KCOLS.findIndex(x=>x[0]===t.status), n=Math.min(KCOLS.length-1,Math.max(0,i+d));
  t.status=KCOLS[n][0]; renderBoard(); }
function addCard(st){ const id=tmp();
  DATA.tasks.push({id:id,title:'',detail:'',status:st,category:'',due:'',parent:''});
  OPEN[id]=true; renderBoard();
  const el=document.querySelector('[data-id="'+id+'"] .tbody input'); if(el) el.focus(); }
function addCk(pid){ const p=tById(pid); if(!p) return;
  DATA.tasks.push({id:tmp(),title:'',detail:'',status:'todo',category:'',due:'',parent:pid});
  OPEN[pid]=true; renderBoard(); }
function tdel(id){ DATA.tasks=DATA.tasks.filter(t=>t.id!==id&&t.parent!==id); renderBoard(); }

let DRAG=null;
function dstart(ev,id){ DRAG=id; ev.dataTransfer.effectAllowed='move';
  try{ev.dataTransfer.setData('text/plain',id);}catch(e){}
  ev.currentTarget.classList.add('drag'); }
function dend(ev){ ev.currentTarget.classList.remove('drag'); DRAG=null; }
function dover(ev,st){ ev.preventDefault(); const c=document.getElementById('col-'+st); if(c)c.classList.add('over'); }
function dleave(st){ const c=document.getElementById('col-'+st); if(c)c.classList.remove('over'); }
function drop(ev,st){ ev.preventDefault();
  const id=DRAG||(ev.dataTransfer?ev.dataTransfer.getData('text/plain'):'');
  const t=id?tById(id):null; if(t){ t.status=st; } DRAG=null; renderBoard(); }

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
