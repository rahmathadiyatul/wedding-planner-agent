"""The shared plan's web page.

Kept apart from plan.py so the storage logic stays readable. The page is a
small client-side app: it holds the whole plan in memory, renders one page of
one tab at a time, and POSTs everything back on save.

Sub-items live in the same flat list via `parent`; sorting/filtering/paging
apply to top-level rows only and children always travel with their parent, so
a breakdown never gets split across pages.
"""
from __future__ import annotations

import html
import json


def render(token: str, title: str, entries: list, notes: str) -> str:
    payload = json.dumps({"entries": entries, "notes": notes}, ensure_ascii=False)
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
         --muted:#949cab; --in:#39d98a; --out:#ff6b6b; --accent:#2f6df6; }
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--fg);
       font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
  header{padding:14px 16px;background:var(--card);border-bottom:1px solid var(--line);
         position:sticky;top:0;z-index:20;display:flex;justify-content:space-between;align-items:center;gap:10px}
  header h1{font-size:17px;margin:0}
  .wrap{max-width:1100px;margin:0 auto;padding:16px}
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
  tr.sub td:nth-child(2){padding-left:24px}
  tr.sub .tw{color:var(--muted)}
  .btn{background:transparent;border:1px solid var(--line);color:var(--fg);border-radius:8px;
       padding:5px 9px;font-size:12px;cursor:pointer;white-space:nowrap}
  .btn:hover{border-color:var(--accent)}
  .btn.del{color:var(--out);border-color:#3a2a2e}
  .btn:disabled{opacity:.4;cursor:default}
  .bar{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin:12px 0}
  button.primary{background:var(--accent);color:#fff;border:0;padding:11px 18px;border-radius:10px;
       font-size:15px;font-weight:600;cursor:pointer}
  .muted{color:var(--muted);font-size:13px}
  h2{font-size:15px;margin:22px 0 8px}
  textarea{min-height:130px;font:13px/1.5 ui-monospace,Menlo,Consolas,monospace}
  .ok{color:var(--in);font-size:14px}
  .pg{display:flex;gap:8px;align-items:center;justify-content:flex-end;padding:10px;flex-wrap:wrap}
  .empty{padding:26px;text-align:center;color:var(--muted)}
  .mctl{display:none;gap:8px;margin-bottom:10px}
  .mctl input{flex:1} .mctl select{width:auto}

  /* Phones: the table becomes stacked cards, with a search + sort bar standing
     in for the column headers and per-column filters. */
  @media (max-width: 760px){
    .wrap{padding:12px}
    .cards{grid-template-columns:repeat(2,1fr)}
    .card .v{font-size:16px}
    .big{grid-column:span 2}
    .mctl{display:flex}
    .tablewrap{overflow-x:visible}
    table{min-width:0}
    thead{display:none}
    tbody tr{display:block;padding:10px 10px 12px;border-bottom:1px solid var(--line)}
    tbody td{display:flex;align-items:center;gap:10px;border:0;padding:3px 0}
    tbody td::before{content:attr(data-l);color:var(--muted);font-size:12px;
                     min-width:76px;flex:0 0 76px}
    tbody td.act{justify-content:flex-end;gap:8px;padding-top:8px}
    tbody td.act::before{content:''}
    tr.sub{border-left:2px solid var(--accent);background:#12161d}
    tr.sub td:nth-child(2){padding-left:0}
    td.amt input{text-align:left}
  }
</style></head>
<body>
<header><h1>&#128141; __TITLE__</h1><span class="muted">bersama &middot; @bang</span></header>
<div class="wrap">
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
    <span class="muted">Nominal boleh 5000000 atau 5.000.000 &middot; pakai &ldquo;+ sub&rdquo; untuk rincian</span>
  </div>

  <div class="tablewrap">
    <table>
      <thead>
        <tr id="head"></tr>
        <tr class="filters" id="filters"></tr>
      </thead>
      <tbody id="rows"></tbody>
    </table>
    <div class="pg" id="pager"></div>
  </div>

  <h2>Catatan</h2>
  <textarea id="notes" spellcheck="false" oninput="DATA.notes=this.value"></textarea>

  <div class="bar">
    <button class="primary" onclick="save()">Simpan</button>
    <span id="status" class="ok"></span>
    <span class="muted">Simpan terakhir yang menang.</span>
  </div>
</div>

<script>
const TOKEN = "__TOKEN__";
let DATA = __DATA__;
(DATA.entries||[]).forEach(e=>{ if(!e.parent) e.parent=''; });

const COLS = [
  {k:'status',   t:'Status',   w:'120px'},
  {k:'item',     t:'Item',     w:''},
  {k:'amount',   t:'Nominal',  w:'150px'},
  {k:'category', t:'Kategori', w:'140px'},
  {k:'date',     t:'Tanggal',  w:'150px'},
];
const ST = {
  income:  {sort:{k:'item',d:1}, f:{}, q:'', page:1},
  expense: {sort:{k:'item',d:1}, f:{}, q:'', page:1},
};
let TAB = 'expense';
const PAGE_SIZE = 10;

const rp = n => { n=Math.round(Number(n)||0);
  return (n<0?'-':'')+'Rp '+Math.abs(n).toLocaleString('id-ID'); };
const digits = s => { const neg=String(s).trim().startsWith('-');
  const d=String(s||'').replace(/[^0-9]/g,''); const n=d?parseInt(d,10):0; return neg?-n:n; };
const esc = s => String(s==null?'':s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const byId = id => (DATA.entries||[]).find(e=>e.id===id);
const kids = id => (DATA.entries||[]).filter(e=>e.parent===id);
const amountOf = e => { const k=kids(e.id); return k.length ? k.reduce((a,c)=>a+amountOf(c),0) : (Number(e.amount)||0); };
const tmp = () => 'tmp-'+Math.random().toString(36).slice(2,9);
const countTop = k => (DATA.entries||[]).filter(e=>e.kind===k && !e.parent).length;

function updateSummary(){
  const all = DATA.entries||[];
  const parents = new Set(all.filter(e=>e.parent).map(e=>e.parent));
  const lv = all.filter(e=>!parents.has(e.id));
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
           '<div class="v '+c[3]+'">'+c[1]+'</div>'+
           (c[2]?'<div class="s">'+c[2]+'</div>':'')+'</div>'; }).join('');
  document.getElementById('tab-income').textContent  = 'Pemasukan ('+countTop('income')+')';
  document.getElementById('tab-expense').textContent = 'Pengeluaran ('+countTop('expense')+')';
}

const fieldText = (o,k) => k==='amount' ? String(amountOf(o))
  : k==='status' ? (o.status==='actual'?'sudah':'rencana')
  : String(o[k]||'');

function visibleTop(){
  const st = ST[TAB];
  let rows = (DATA.entries||[]).filter(e=>e.kind===TAB && !e.parent);
  const q = (st.q||'').trim().toLowerCase();
  if(q){  // mobile/global search: any column, parent or sub-item
    rows = rows.filter(function(e){
      const hit = o => COLS.some(c=>fieldText(o,c.k).toLowerCase().indexOf(q)!==-1);
      return hit(e) || kids(e.id).some(hit);
    });
  }
  COLS.forEach(function(c){
    const q = (st.f[c.k]||'').trim().toLowerCase();
    if(!q) return;
    rows = rows.filter(function(e){
      const hit = function(o){
        let v;
        if(c.k==='amount') v = String(amountOf(o));
        else if(c.k==='status') v = (o.status==='actual'?'sudah':'rencana');
        else v = String(o[c.k]||'');
        return v.toLowerCase().indexOf(q) !== -1;
      };
      return hit(e) || kids(e.id).some(hit);
    });
  });
  const k = st.sort.k, d = st.sort.d;
  rows.sort(function(a,b){
    let x,y;
    if(k==='amount'){ x=amountOf(a); y=amountOf(b); }
    else { x=String(a[k]||'').toLowerCase(); y=String(b[k]||'').toLowerCase();
           if(!x&&y) return 1; if(x&&!y) return -1; }
    return x<y?-d:x>y?d:0;
  });
  return rows;
}
const hasFilter = () => COLS.some(c=>(ST[TAB].f[c.k]||'').trim());

function renderHead(){
  const st = ST[TAB];
  document.getElementById('head').innerHTML = COLS.map(function(c){
    const on = st.sort.k===c.k;
    const ar = on ? (st.sort.d>0?'&#9650;':'&#9660;') : '&#8645;';
    return '<th class="s" style="'+(c.w?'width:'+c.w:'')+'" onclick="sortBy(\''+c.k+'\')">'+
           c.t+' <span class="ar">'+ar+'</span></th>';
  }).join('') + '<th style="width:150px"></th>';
  document.getElementById('filters').innerHTML = COLS.map(function(c){
    return '<th><input placeholder="filter..." value="'+esc(st.f[c.k]||'')+
           '" oninput="setFilter(\''+c.k+'\', this.value)"></th>';
  }).join('') + '<th></th>';
}

function rowHtml(e, isSub){
  const k = kids(e.id), computed = k.length>0;
  const amt = computed ? amountOf(e) : (Number(e.amount)||0);
  const sel = '<select onchange="upd(\''+e.id+'\',\'status\',this.value)">'+
    '<option value="actual"'+(e.status==='actual'?' selected':'')+'>Sudah</option>'+
    '<option value="expected"'+(e.status==='expected'?' selected':'')+'>Rencana</option></select>';
  return '<tr class="'+(isSub?'sub':'')+'" data-id="'+e.id+'">'+
    '<td data-l="Status">'+sel+'</td>'+
    '<td data-l="Item"><span class="tw">'+(isSub?'&#8627; ':'')+'</span><input value="'+esc(e.item)+'" '+
      'placeholder="'+(isSub?'rincian...':'mis. Administrasi KUA')+'" '+
      'oninput="upd(\''+e.id+'\',\'item\',this.value)"></td>'+
    '<td class="amt" data-l="Nominal"><input inputmode="numeric" '+
      (computed?'disabled title="total dari sub-item"':'')+' '+
      'value="'+(amt?amt.toLocaleString('id-ID'):'')+'" '+
      'oninput="upd(\''+e.id+'\',\'amount\',digits(this.value))" '+
      'onblur="this.value=this.value?digits(this.value).toLocaleString(\'id-ID\'):\'\'"></td>'+
    '<td data-l="Kategori"><input value="'+esc(e.category)+'" oninput="upd(\''+e.id+'\',\'category\',this.value)"></td>'+
    '<td data-l="Tanggal"><input type="date" value="'+esc(e.date)+'" oninput="upd(\''+e.id+'\',\'date\',this.value)"></td>'+
    '<td class="act">'+(isSub?'':'<button class="btn" onclick="addSub(\''+e.id+'\')">+ sub</button> ')+
      '<button class="btn del" onclick="del(\''+e.id+'\')">&#10005;</button></td></tr>';
}

function render(){
  renderHead();
  const st = ST[TAB];
  const rows = visibleTop();
  const pages = Math.max(1, Math.ceil(rows.length/PAGE_SIZE));
  if(st.page>pages) st.page=pages;
  const slice = rows.slice((st.page-1)*PAGE_SIZE, st.page*PAGE_SIZE);
  let html='';
  slice.forEach(function(e){ html += rowHtml(e,false);
    kids(e.id).forEach(function(c){ html += rowHtml(c,true); }); });
  document.getElementById('rows').innerHTML = html ||
    '<tr><td colspan="6" class="empty">Belum ada data'+(hasFilter()?' yang cocok dengan filter':'')+'.</td></tr>';
  document.getElementById('pager').innerHTML =
    '<span class="muted">'+rows.length+' baris utama &middot; halaman '+st.page+'/'+pages+'</span>'+
    '<button class="btn" '+(st.page<=1?'disabled':'')+' onclick="go(-1)">&lsaquo; Sebelumnya</button>'+
    '<button class="btn" '+(st.page>=pages?'disabled':'')+' onclick="go(1)">Berikutnya &rsaquo;</button>';
  document.getElementById('tab-income').className  = 'tab'+(TAB==='income'?' on':'');
  document.getElementById('tab-expense').className = 'tab'+(TAB==='expense'?' on':'');
  syncMobile();
  updateSummary();
}

function syncMobile(){
  const st = ST[TAB];
  const sel = document.getElementById('msort');
  sel.innerHTML = COLS.map(function(c){
    return '<option value="'+c.k+':1"'+(st.sort.k===c.k&&st.sort.d>0?' selected':'')+'>'+c.t+' ↑</option>'+
           '<option value="'+c.k+':-1"'+(st.sort.k===c.k&&st.sort.d<0?' selected':'')+'>'+c.t+' ↓</option>';
  }).join('');
  document.getElementById('msearch').value = st.q||'';
}
function setSearch(v){ ST[TAB].q=v; ST[TAB].page=1; render(); }
function setSortSel(v){ const p=v.split(':'); ST[TAB].sort={k:p[0],d:parseInt(p[1],10)}; render(); }
function setTab(t){ TAB=t; render(); }
function sortBy(k){ const s=ST[TAB].sort; s.d = (s.k===k) ? -s.d : 1; s.k=k; render(); }
function setFilter(k,v){ ST[TAB].f[k]=v; ST[TAB].page=1; render(); }
function clearFilters(){ ST[TAB].f={}; ST[TAB].q=''; ST[TAB].page=1; render(); }
function go(d){ ST[TAB].page+=d; render(); }
function upd(id,k,v){ const e=byId(id); if(!e) return; e[k]=v;
  if(k==='amount'||k==='status') updateSummary(); }
function addTop(){
  DATA.entries.push({id:tmp(),kind:TAB,status:'expected',item:'',amount:0,category:'',date:'',parent:''});
  ST[TAB].page = Math.max(1, Math.ceil(visibleTop().length/PAGE_SIZE));
  render();
}
function addSub(pid){
  const p=byId(pid); if(!p) return;
  DATA.entries.push({id:tmp(),kind:p.kind,status:p.status,item:'',amount:0,
                     category:p.category||'',date:'',parent:pid});
  render();
}
function del(id){ DATA.entries = DATA.entries.filter(e=>e.id!==id && e.parent!==id); render(); }

async function save(){
  const body={entries:(DATA.entries||[]).filter(e=>e.item||e.amount||kids(e.id).length),
              notes:document.getElementById('notes').value};
  const st=document.getElementById('status'); st.textContent='menyimpan...';
  try{
    const r=await fetch('/api/plan?token='+encodeURIComponent(TOKEN),
      {method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(body)});
    if(!r.ok) throw new Error(r.status);
    DATA=await r.json(); (DATA.entries||[]).forEach(e=>{ if(!e.parent) e.parent=''; });
    document.getElementById('notes').value = DATA.notes||'';
    render(); st.textContent='tersimpan ✓';
    setTimeout(function(){ st.textContent=''; },2500);
  }catch(e){ st.textContent='gagal menyimpan: '+e.message; }
}

document.getElementById('notes').value = DATA.notes || '';
render();
</script>
</body></html>"""
