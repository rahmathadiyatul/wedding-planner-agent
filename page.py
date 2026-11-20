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
           mail: dict | None = None, updated_at: str = "") -> str:
    payload = json.dumps({"entries": entries, "notes": notes, "tasks": tasks,
                          "updated_at": updated_at}, ensure_ascii=False)
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
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,600&family=Plus+Jakarta+Sans:wght@400;500;600;700&display=swap">
<meta name="theme-color" content="#f6f1e9" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#14120f" media="(prefers-color-scheme: dark)">
<script>try{var t=localStorage.getItem("theme");if(t)document.documentElement.setAttribute("data-theme",t);}catch(e){}</script>
<style>
  /* ======================================================================
     Ivory & sage -- a wedding-stationery palette. Light by default, a warm
     dark variant follows the OS, and the sidebar toggle can force either.
     Every colour below is a token; nothing further down hard-codes one.
     ====================================================================== */
  :root{
    color-scheme:light;
    --bg:#f6f1e9; --surface:#fffcf7; --surface-2:#f3ece1; --sunken:#ece4d6;
    --line:#e6dccb; --line-2:#d5c7b0;
    --fg:#2b2521; --muted:#867b6d; --faint:#b2a690;
    --accent:#56704f; --accent-fg:#ffffff; --accent-soft:#e4ebdc;
    --gold:#a8834a; --gold-soft:#f4e9d6;
    --in:#3c7a55; --out:#b14f59; --warn:#a46a14;
    --in-soft:#e2efe5; --out-soft:#f7e3e3; --warn-soft:#f6ebd6;
    --shadow-sm:0 1px 2px rgba(70,50,25,.06);
    --shadow:0 1px 2px rgba(70,50,25,.05),0 10px 30px -8px rgba(70,50,25,.12);
    --shadow-lg:0 24px 60px -12px rgba(50,35,15,.28);
    --r:14px; --r-sm:10px;
    --serif:"Fraunces",Georgia,"Times New Roman",serif;
    --sans:"Plus Jakarta Sans",system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
  }
  @media (prefers-color-scheme: dark){
    :root:not([data-theme="light"]){
      color-scheme:dark;
      --bg:#14120f; --surface:#1c1915; --surface-2:#24201b; --sunken:#100e0c;
      --line:#2f2a23; --line-2:#40382e;
      --fg:#efe7da; --muted:#a69b8a; --faint:#6e655a;
      --accent:#a9c19a; --accent-fg:#16140f; --accent-soft:#263022;
      --gold:#d8b47c; --gold-soft:#2d251a;
      --in:#8dc8a1; --out:#e7939a; --warn:#e4ad5a;
      --in-soft:#1d2a21; --out-soft:#2e1d1f; --warn-soft:#2d2416;
      --shadow-sm:0 1px 2px rgba(0,0,0,.4);
      --shadow:0 1px 2px rgba(0,0,0,.35),0 12px 32px -10px rgba(0,0,0,.5);
      --shadow-lg:0 24px 60px -12px rgba(0,0,0,.7);
    }
  }
  :root[data-theme="dark"]{
    color-scheme:dark;
    --bg:#14120f; --surface:#1c1915; --surface-2:#24201b; --sunken:#100e0c;
    --line:#2f2a23; --line-2:#40382e;
    --fg:#efe7da; --muted:#a69b8a; --faint:#6e655a;
    --accent:#a9c19a; --accent-fg:#16140f; --accent-soft:#263022;
    --gold:#d8b47c; --gold-soft:#2d251a;
    --in:#8dc8a1; --out:#e7939a; --warn:#e4ad5a;
    --in-soft:#1d2a21; --out-soft:#2e1d1f; --warn-soft:#2d2416;
    --shadow-sm:0 1px 2px rgba(0,0,0,.4);
    --shadow:0 1px 2px rgba(0,0,0,.35),0 12px 32px -10px rgba(0,0,0,.5);
    --shadow-lg:0 24px 60px -12px rgba(0,0,0,.7);
  }

  *{box-sizing:border-box}
  html{-webkit-text-size-adjust:100%}
  body{margin:0;background:var(--bg);color:var(--fg);font-family:var(--sans);
       font-size:14px;line-height:1.45;-webkit-font-smoothing:antialiased}
  ::selection{background:var(--accent-soft)}
  .app{display:flex;min-height:100vh}

  /* ------------------------------------------------------------ sidebar */
  .side{width:228px;flex:0 0 228px;background:var(--surface);border-right:1px solid var(--line);
        display:flex;flex-direction:column;gap:2px;padding:20px 14px;position:sticky;top:0;
        height:100vh;transition:width .2s ease,flex-basis .2s ease}
  .brand{display:flex;align-items:center;gap:11px;padding:2px 8px 22px;white-space:nowrap;overflow:hidden}
  .brand .nic{color:var(--gold);width:24px;height:24px;flex-basis:24px}
  .brand .bt{flex:1;overflow:hidden;text-overflow:ellipsis;font-family:var(--serif);
             font-size:17px;font-weight:600;letter-spacing:-.015em}
  /* every row: a fixed 20px icon slot, so the labels line up no matter the glyph */
  .nav{display:flex;align-items:center;gap:12px;background:transparent;border:0;color:var(--muted);
       width:100%;text-align:left;padding:10px 12px;border-radius:var(--r-sm);cursor:pointer;
       font:600 14px var(--sans);white-space:nowrap;overflow:hidden;
       transition:background .15s,color .15s}
  .nav:hover{background:var(--surface-2);color:var(--fg)}
  .nav.on{background:var(--accent-soft);color:var(--accent)}
  /* sidebar icon only -- NOT td.ic, which is the ledger's Item cell */
  .nic{width:20px;height:20px;flex:0 0 20px;fill:none;stroke:currentColor;stroke-width:1.7;
       stroke-linecap:round;stroke-linejoin:round}
  .nav .lb{flex:1;overflow:hidden;text-overflow:ellipsis}
  .nav .ct{font-size:11px;font-weight:700;color:var(--muted);background:var(--surface-2);
           border-radius:999px;padding:1px 8px;flex:0 0 auto}
  .nav.on .ct{background:var(--accent);color:var(--accent-fg)}
  .nav.theme{margin-top:auto}
  .collapse{background:transparent;border:0;color:var(--faint);cursor:pointer;padding:4px;
            flex:0 0 auto;display:flex;border-radius:8px}
  .collapse svg{width:18px;height:18px;fill:none;stroke:currentColor;stroke-width:2;
                stroke-linecap:round;stroke-linejoin:round;transition:transform .2s}
  .collapse:hover{color:var(--fg);background:var(--surface-2)}
  /* collapsed: an icon rail. Labels and counts fold away, icons stay centred. */
  .side.mini{width:68px;flex:0 0 68px;padding:20px 10px}
  .side.mini .lb,.side.mini .ct,.side.mini .bt,.side.mini .sidefoot{display:none}
  .side.mini .nav,.side.mini .brand{justify-content:center;gap:0;padding-left:0;padding-right:0}
  .side.mini .brand{flex-direction:column;gap:10px}
  .side.mini .collapse svg{transform:rotate(180deg)}
  .sidefoot{color:var(--faint);font-size:12px;padding:10px 12px 0;font-family:var(--serif);font-style:italic}

  .main{flex:1;min-width:0;display:flex;flex-direction:column}
  .wrap{padding:28px 32px 12px;max-width:1280px;width:100%;margin:0 auto;flex:1}
  .view{display:none} .view.on{display:block;animation:rise .28s ease both}
  @keyframes rise{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}

  /* page header */
  .ph{margin:0 0 22px}
  .eyebrow{margin:0 0 6px;font-size:11px;font-weight:700;letter-spacing:.14em;text-transform:uppercase;
           color:var(--gold)}
  .ph h1{margin:0;font-family:var(--serif);font-weight:600;font-size:34px;line-height:1.1;
         letter-spacing:-.02em}
  .ph .lede{margin:6px 0 0;color:var(--muted);font-size:14px}
  h2{font-family:var(--serif);font-weight:600;font-size:20px;letter-spacing:-.01em;margin:30px 0 10px}
  .muted{color:var(--muted);font-size:13px}
  label{font-size:12px;font-weight:600;color:var(--muted);display:block;margin-bottom:5px}

  /* ------------------------------------------------------------ finance */
  .cards{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px;margin-bottom:26px}
  .card{background:var(--surface);border:1px solid var(--line);border-radius:var(--r);
        padding:16px 18px;box-shadow:var(--shadow-sm);min-width:0}
  .card .l{font-size:12px;font-weight:600;color:var(--muted);margin-bottom:8px;letter-spacing:.01em}
  .card .v{font-family:var(--serif);font-size:22px;font-weight:600;letter-spacing:-.01em;
           font-variant-numeric:lining-nums tabular-nums;white-space:nowrap;overflow:hidden;
           text-overflow:ellipsis}
  .card .s{font-size:12px;color:var(--muted);margin-top:6px}
  .card .s.warn{color:var(--warn);font-weight:600}
  .card .v.in{color:var(--in)} .card .v.out{color:var(--out)}
  .big{grid-column:span 2;padding:22px 24px;box-shadow:var(--shadow);position:relative;overflow:hidden}
  .big .v{font-size:34px}
  .big::after{content:"";position:absolute;right:-40px;top:-40px;width:150px;height:150px;
              border-radius:50%;background:radial-gradient(circle,var(--gold-soft),transparent 70%);
              pointer-events:none}
  .big + .big{background:linear-gradient(135deg,var(--accent-soft),var(--surface) 70%)}
  .meter{height:6px;border-radius:999px;background:var(--surface-2);margin-top:14px;overflow:hidden}
  .meter i{display:block;height:100%;border-radius:999px;background:linear-gradient(90deg,var(--accent),var(--gold))}

  /* segmented controls: finance tabs and the week/month switch */
  .tabs,.seg{display:inline-flex;gap:2px;padding:4px;border-radius:12px;background:var(--sunken);
             border:1px solid var(--line)}
  .tabs{margin-bottom:14px}
  .tab,.seg button{background:transparent;border:0;color:var(--muted);padding:8px 16px;border-radius:9px;
       cursor:pointer;font:600 13px var(--sans);transition:background .15s,color .15s,box-shadow .15s}
  .tab:hover,.seg button:hover{color:var(--fg)}
  .tab.on,.seg button.on{background:var(--surface);color:var(--fg);box-shadow:var(--shadow-sm)}

  .tablewrap{overflow-x:auto;border:1px solid var(--line);border-radius:var(--r);
             background:var(--surface);box-shadow:var(--shadow-sm)}
  table{border-collapse:collapse;width:100%;min-width:820px}
  th,td{padding:6px 10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:middle}
  thead tr:first-child th{padding-top:12px;font-size:11px;letter-spacing:.08em;text-transform:uppercase;
       color:var(--muted);font-weight:700;white-space:nowrap;border-bottom:0}
  th.s{cursor:pointer;user-select:none} th.s:hover{color:var(--fg)}
  th .ar{opacity:.5;font-size:10px}
  tr.filters th{padding-top:2px;padding-bottom:10px}
  tr.filters input{padding:6px 9px;font-size:12px;background:var(--surface-2);border-color:transparent}
  tbody tr{transition:background .12s}
  tbody tr:hover{background:color-mix(in srgb,var(--surface-2) 60%,transparent)}

  /* inputs: quiet until touched, so the ledger reads like a sheet, not a form */
  input,select,textarea{background:var(--surface);color:var(--fg);border:1px solid var(--line);
       border-radius:var(--r-sm);padding:8px 10px;font:14px var(--sans);width:100%;
       transition:border-color .15s,box-shadow .15s,background .15s}
  input::placeholder,textarea::placeholder{color:var(--faint)}
  input:hover,select:hover,textarea:hover{border-color:var(--line-2)}
  input:focus,select:focus,textarea:focus{outline:none;border-color:var(--accent);
       box-shadow:0 0 0 3px color-mix(in srgb,var(--accent) 22%,transparent)}
  tbody input,tbody select{background:transparent;border-color:transparent}
  tbody tr:hover input,tbody tr:hover select{border-color:var(--line)}
  tbody input:focus,tbody select:focus{background:var(--surface)}
  td.amt input{text-align:right;font-variant-numeric:tabular-nums;font-weight:600}
  td.amt input:disabled{background:transparent;color:var(--gold);font-weight:700;border-color:transparent}
  td.ic{display:flex;align-items:center;gap:8px}
  td.ic .tw{flex:0 0 auto;line-height:1}
  .cr{flex:0 0 auto;width:38px;display:inline-flex;align-items:center;justify-content:center;gap:3px;
      background:var(--surface-2);border:0;border-radius:999px;color:var(--muted);
      font-size:10px;padding:4px 0;cursor:pointer;line-height:1}
  .cr:hover{background:var(--accent-soft);color:var(--accent)}
  .cr b{font-size:11px;font-weight:700}
  .cr.ph{background:transparent;cursor:default}
  /* sub-items hug their parent: tighter rows, no divider until the last child */
  tr.sub{background:color-mix(in srgb,var(--surface-2) 55%,transparent)}
  tr.sub td{padding-top:1px;padding-bottom:1px}
  tr.sub td.ic{padding-left:28px}
  tr.sub input,tr.sub select{padding:5px 9px;font-size:13px}
  tr.hask td,tr.sub td{border-bottom:0}
  tr.sub.lastsub td{border-bottom:1px solid var(--line);padding-bottom:6px}
  tr.sub .tw{color:var(--gold)}
  td.act{white-space:nowrap;text-align:right}
  .pg{display:flex;gap:8px;align-items:center;justify-content:flex-end;padding:12px 14px;flex-wrap:wrap;
      color:var(--muted);font-size:13px}
  .empty{padding:36px;text-align:center;color:var(--muted);font-family:var(--serif);font-style:italic}
  .mctl{display:none;gap:8px;margin-bottom:12px}
  .mctl input{flex:1} .mctl select{width:auto}
  #notes{min-height:140px;line-height:1.6;background:var(--surface);box-shadow:var(--shadow-sm)}

  /* ------------------------------------------------------------ buttons */
  .btn{background:var(--surface);border:1px solid var(--line);color:var(--fg);border-radius:999px;
       padding:6px 13px;font:600 12px var(--sans);cursor:pointer;white-space:nowrap;
       transition:border-color .15s,background .15s,color .15s}
  .btn:hover{border-color:var(--accent);color:var(--accent)}
  .btn.del{color:var(--out);background:transparent;border-color:transparent;padding:6px 9px}
  .btn.del:hover{background:var(--out-soft);border-color:transparent;color:var(--out)}
  .btn:disabled{opacity:.4;cursor:default}
  .bar{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:0 0 14px}
  button.primary{background:var(--accent);color:var(--accent-fg);border:0;padding:11px 26px;
       border-radius:999px;font:700 14px var(--sans);cursor:pointer;box-shadow:var(--shadow);
       transition:transform .12s,filter .15s}
  button.primary:hover{filter:brightness(1.06)}
  button.primary:active{transform:scale(.97)}
  textarea{min-height:120px;font:14px/1.6 var(--sans);resize:vertical}
  .ok{color:var(--in);font-size:13px;font-weight:600}
  code{font-size:12px;background:var(--surface-2);padding:1px 6px;border-radius:6px}

  /* ------------------------------------------------------------ calendar */
  .calbar{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin:0 0 16px}
  .calbar .ttl{font-family:var(--serif);font-weight:600;font-size:24px;letter-spacing:-.01em;
               min-width:200px;margin:0 6px}
  .calbar #ksearch{margin-left:auto}
  .navbtn{width:34px;height:34px;padding:0;display:inline-flex;align-items:center;justify-content:center;
          font-size:16px}
  .cal{border:1px solid var(--line);border-radius:18px;overflow:hidden;background:var(--surface);
       box-shadow:var(--shadow)}
  .calhead{display:grid;grid-template-columns:repeat(7,minmax(0,1fr));background:var(--surface-2);
           border-bottom:1px solid var(--line)}
  .calhead div{padding:10px 8px;font-size:11px;color:var(--muted);font-weight:700;text-align:left;
               letter-spacing:.1em;text-transform:uppercase}
  .calgrid{display:grid;grid-template-columns:repeat(7,minmax(0,1fr))}
  .day{border-top:1px solid var(--line);border-left:1px solid var(--line);min-height:118px;
       padding:8px;display:flex;flex-direction:column;gap:4px;position:relative;
       min-width:0;overflow:hidden;transition:background .12s}
  .calgrid .day:nth-child(-n+7){border-top:0}
  .day:nth-child(7n+1){border-left:0}
  .day:hover{background:color-mix(in srgb,var(--surface-2) 45%,transparent)}
  .day.out{background:color-mix(in srgb,var(--sunken) 55%,transparent)}
  .day.out .dn{opacity:.45}
  .day.over{background:var(--accent-soft);box-shadow:inset 0 0 0 2px var(--accent)}
  .dn{font-size:13px;font-weight:600;color:var(--muted);width:26px;height:26px;display:flex;
      align-items:center;justify-content:center;flex:0 0 auto;font-variant-numeric:tabular-nums}
  .day.today .dn{background:var(--accent);color:var(--accent-fg);border-radius:50%;font-weight:700;
                 box-shadow:0 0 0 3px var(--accent-soft)}
  .day .plus{position:absolute;top:8px;right:8px;opacity:0;background:var(--surface);
       border:1px solid var(--line);border-radius:50%;width:24px;height:24px;color:var(--muted);
       font-size:15px;cursor:pointer;line-height:1;padding:0;transition:opacity .12s}
  .day:hover .plus{opacity:1}
  .day .plus:hover{color:var(--accent);border-color:var(--accent)}
  /* each pill carries its status colour in --c; the tint and the edge come from it */
  .pill{--c:var(--muted);display:flex;align-items:center;gap:6px;
        background:color-mix(in srgb,var(--c) 13%,var(--surface));border:0;
        border-left:3px solid var(--c);border-radius:7px;padding:5px 8px;font:500 12px var(--sans);
        cursor:pointer;text-align:left;width:100%;max-width:100%;color:var(--fg);min-width:0;
        transition:transform .12s,box-shadow .12s}
  .pill:hover{box-shadow:var(--shadow);transform:translateY(-1px)}
  .pill .pt{flex:1 1 0;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .pill .pc{font-size:10px;color:var(--muted);flex:0 0 auto;font-weight:600}
  .pill.done .pt{text-decoration:line-through;color:var(--muted)}
  .pill.cont{opacity:.75}
  .pill.cont .pt{font-weight:400}
  .cal.week .day{min-height:320px}
  .more{font:600 11px var(--sans);color:var(--accent);background:transparent;border:0;cursor:pointer;
        text-align:left;padding:2px 4px;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .nodate{margin-top:8px}
  .nodate h2{display:flex;align-items:center;gap:10px}
  .nodate .list{display:flex;flex-wrap:wrap;gap:8px}
  .nodate .pill{width:auto;max-width:300px;padding:8px 12px;font-size:13px}

  /* hover tooltip -- the pills truncate, so this is where the full text lives */
  .tip{position:fixed;z-index:60;max-width:300px;background:var(--surface);color:var(--fg);
       border:1px solid var(--line);border-radius:12px;padding:11px 13px;font-size:12px;
       line-height:1.5;box-shadow:var(--shadow-lg);pointer-events:none;
       opacity:0;transform:translateY(-3px);transition:opacity .12s,transform .12s;display:none}
  .tip.on{display:block;opacity:1;transform:none}
  .tip .tth{font-family:var(--serif);font-weight:600;font-size:15px;margin-bottom:6px;
            white-space:normal;word-break:break-word}
  .tip .ttr{display:flex;gap:6px;align-items:center;color:var(--muted);margin-top:3px}
  .tip .sdot{width:8px;height:8px;border-radius:50%;flex:0 0 8px}
  .tip ul{margin:8px 0 0;padding-left:16px}
  .tip li{margin:2px 0;color:var(--muted)}
  .tip li.d{text-decoration:line-through}

  /* ------------------------------------------------------------ drawer */
  .ov{position:fixed;inset:0;background:rgba(30,22,12,.35);backdrop-filter:blur(3px);
      -webkit-backdrop-filter:blur(3px);z-index:50;display:none}
  .ov.on{display:block;animation:fade .2s ease both}
  @keyframes fade{from{opacity:0}to{opacity:1}}
  .drw{position:fixed;top:0;right:0;bottom:0;width:min(460px,100%);background:var(--surface);
       border-left:1px solid var(--line);z-index:51;transform:translateX(102%);box-shadow:var(--shadow-lg);
       transition:transform .26s cubic-bezier(.2,.8,.2,1);overflow:auto;padding:22px 24px 28px;
       display:flex;flex-direction:column;gap:8px}
  .drw.on{transform:none}
  .drw h3{margin:0 0 8px;font-family:var(--serif);font-weight:600;font-size:22px;
          display:flex;align-items:center;gap:8px;letter-spacing:-.01em}
  .drw h3 .x{margin-left:auto;width:34px;height:34px;padding:0}
  .drw label{margin:10px 0 2px}
  .stsel{display:flex;gap:6px;flex-wrap:wrap}
  .stsel button{flex:1;min-width:92px;background:var(--surface);border:1px solid var(--line);
        color:var(--muted);border-radius:999px;padding:9px;font:600 12px var(--sans);cursor:pointer;
        display:flex;align-items:center;justify-content:center;gap:7px;transition:all .15s}
  .stsel button .dot{width:8px;height:8px;border-radius:50%;background:currentColor}
  .stsel button.on{border-width:1.5px}
  .ck{display:flex;align-items:center;gap:10px;padding:4px 6px;border-radius:8px}
  .ck:hover{background:var(--surface-2)}
  .ck input[type=checkbox]{width:17px;height:17px;flex:0 0 17px;accent-color:var(--accent)}
  .ck .cx{flex:1;font-size:14px;background:transparent;border-color:transparent;padding:3px 4px;color:var(--fg)}
  .ck.done .cx{text-decoration:line-through;color:var(--muted)}
  .ck .btn{padding:3px 7px}
  .trow{display:flex;gap:8px;margin-top:6px;flex-wrap:wrap;align-items:center}
  .whos{display:flex;gap:8px;flex-wrap:wrap;margin-top:4px}
  .who{display:flex;align-items:center;gap:7px;font-size:13px;font-weight:600;color:var(--fg);margin:0;
       background:var(--surface);border:1px solid var(--line);border-radius:999px;padding:6px 13px;
       cursor:pointer;transition:border-color .15s,background .15s}
  .who:hover{border-color:var(--accent)}
  .who:has(input:checked){background:var(--accent-soft);border-color:var(--accent);color:var(--accent)}
  .who input{width:15px;height:15px;accent-color:var(--accent);margin:0}
  .chip{font-size:11px;font-weight:700;color:var(--muted);background:var(--surface-2);
        border-radius:999px;padding:2px 9px;font-family:var(--sans)}
  .chip.pr{color:var(--in);background:var(--in-soft)}

  /* ------------------------------------------------------------ settings */
  .panel{background:var(--surface);border:1px solid var(--line);border-radius:var(--r);
         padding:20px 22px;margin-bottom:16px;box-shadow:var(--shadow-sm)}
  .sh{font-family:var(--serif);font-size:18px;font-weight:600;margin:0 0 12px;letter-spacing:-.01em}
  .grid2{display:grid;grid-template-columns:1fr 1fr;gap:18px;align-items:start}
  .sm{font-size:12px;margin-top:6px}
  .banner{border-radius:12px;padding:12px 16px;font-size:13px;font-weight:600;
          background:var(--surface-2);display:flex;align-items:center;gap:8px;margin-bottom:18px}
  .banner.ok{background:var(--in-soft);color:var(--in)}
  .banner.warn{background:var(--warn-soft);color:var(--warn)}
  .prow{display:flex;gap:8px;margin-top:8px;align-items:center}
  .prow input{flex:1;min-width:120px}

  /* ------------------------------------------------------------ save bar */
  .savebar{position:sticky;bottom:0;z-index:15;padding:12px 32px 16px;display:flex;gap:12px;
           align-items:center;flex-wrap:wrap;
           background:linear-gradient(180deg,transparent,var(--bg) 38%)}
  .savebar .muted{font-size:12px}

  @media (max-width: 1100px){
    .cards{grid-template-columns:repeat(2,minmax(0,1fr))}
  }
  @media (max-width: 760px){
    /* sidebar becomes an app-style bottom tab bar */
    .app{flex-direction:column}
    .side,.side.mini{position:fixed;left:0;right:0;bottom:0;top:auto;width:auto;height:auto;flex:none;
          z-index:40;flex-direction:row;align-items:stretch;justify-content:space-around;gap:0;
          padding:6px 6px calc(6px + env(safe-area-inset-bottom));border-right:0;
          border-top:1px solid var(--line);background:color-mix(in srgb,var(--surface) 92%,transparent);
          backdrop-filter:blur(12px);-webkit-backdrop-filter:blur(12px)}
    .brand,.collapse,.sidefoot{display:none}
    .nav,.side.mini .nav{flex:1;flex-direction:column;gap:3px;padding:7px 4px;font-size:11px;
          justify-content:center;align-items:center;position:relative;margin:0;border-radius:12px}
    .nav.on{background:transparent}
    .nav.on .nic{background:var(--accent-soft);border-radius:999px;padding:2px 14px;box-sizing:content-box}
    .side.mini .lb,.nav .lb{display:block;flex:none}
    .nav .ct,.side.mini .ct{display:block;position:absolute;top:2px;left:calc(50% + 8px);
          font-size:9px;padding:0 5px;background:var(--out);color:#fff}
    .main{padding-bottom:calc(64px + env(safe-area-inset-bottom))}
    .wrap{padding:20px 16px 8px}
    .ph h1{font-size:28px}
    .cards{grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}
    .card{padding:13px 14px}
    .card .v{font-size:17px}
    .big{padding:18px}
    .big .v{font-size:28px}
    .tabs{display:flex} .tab{flex:1}
    .mctl{display:flex}
    .bar .muted{display:none}
    .tablewrap{overflow-x:visible;background:transparent;border:0;box-shadow:none}
    table{min-width:0} thead{display:none}
    tbody{display:flex;flex-direction:column;gap:10px}
    tbody tr{display:block;padding:12px 14px;border:1px solid var(--line);border-radius:var(--r);
             background:var(--surface);box-shadow:var(--shadow-sm)}
    tbody tr:hover{background:var(--surface)}
    tbody td{display:flex;align-items:center;gap:10px;border:0;padding:3px 0}
    tbody td::before{content:attr(data-l);color:var(--muted);font-size:11px;font-weight:700;
          text-transform:uppercase;letter-spacing:.06em;min-width:76px;flex:0 0 76px}
    tbody td.act{justify-content:flex-end;gap:8px;padding-top:10px;margin-top:6px;
          border-top:1px dashed var(--line)}
    tbody td.act::before{content:''}
    tbody input,tbody select{background:var(--surface-2);border-color:transparent}
    tr.sub{margin:-6px 0 0 18px;border-left:3px solid var(--gold);background:var(--surface-2)}
    tr.sub input,tr.sub select{background:var(--surface)}
    tr.sub td.ic{padding-left:0}
    tbody tr.sub td,tbody tr.hask td{border-bottom:0}
    td.amt input{text-align:left}
    .pg{justify-content:center}
    .calbar{gap:6px}
    .calbar .ttl{min-width:0;flex:1 1 100%;order:-1;margin:0 0 4px;font-size:22px}
    .calbar #ksearch{max-width:none!important;flex:1 1 100%;margin-left:0}
    .cal{border-radius:14px}
    .calhead div{font-size:9px;padding:7px 4px;letter-spacing:.06em;text-align:center}
    .day{min-height:64px;padding:4px 3px;gap:3px;align-items:center}
    .dn{width:24px;height:24px;font-size:12px}
    .day .plus{display:none}
    .pill,.pill:hover{height:5px;padding:0;border:0;border-radius:3px;background:var(--c);
          transform:none;box-shadow:none}
    .pill .pt,.pill .pc{display:none}
    .cal.week .day{min-height:150px;align-items:stretch}
    .cal.week .pill,.cal.week .pill:hover{height:auto;padding:4px 6px;border-left:3px solid var(--c);
          background:color-mix(in srgb,var(--c) 13%,var(--surface));font-size:11px}
    .cal.week .pill .pt{display:block}
    .nodate .pill,.nodate .pill:hover{height:auto;padding:8px 12px;border-left:3px solid var(--c);
          background:color-mix(in srgb,var(--c) 13%,var(--surface))}
    .nodate .pill .pt{display:block}
    .drw{padding:18px 18px calc(24px + env(safe-area-inset-bottom));border-left:0}
    .grid2{grid-template-columns:1fr}
    .panel{padding:16px}
    .savebar{bottom:calc(64px + env(safe-area-inset-bottom));padding:10px 16px}
    .savebar .muted{display:none}
    button.primary{flex:1}
  }
  @media (prefers-reduced-motion: reduce){
    *{animation:none!important;transition:none!important}
  }
</style></head>
<body>
<div class="app">
  <aside class="side" id="side">
    <div class="brand">
      <svg class="nic" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 7 8.5 3h7L12 7Z"/>
        <circle cx="12" cy="14.5" r="6"/></svg>
      <span class="bt">__TITLE__</span>
      <button class="collapse" id="collapse" onclick="toggleSide()" title="Lipat sidebar">
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M15 5 8 12l7 7"/></svg>
      </button>
    </div>
    <button class="nav on" id="nav-fin" onclick="setView('fin')" title="Keuangan">
      <svg class="nic" viewBox="0 0 24 24" aria-hidden="true"><path d="M3 7h18v12H3z"/>
        <circle cx="12" cy="13" r="2.6"/></svg>
      <span class="lb">Keuangan</span></button>
    <button class="nav" id="nav-kan" onclick="setView('kan')" title="To-do">
      <svg class="nic" viewBox="0 0 24 24" aria-hidden="true"><path d="M4 5h16v15H4z"/>
        <path d="m8 12 2.6 2.6L16 9.4"/></svg>
      <span class="lb">To-do</span><span class="ct" id="kan-ct">0</span></button>
    <button class="nav" id="nav-set" onclick="setView('set')" title="Settings">
      <svg class="nic" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="3.2"/>
        <path d="M12 3v2.2M12 18.8V21M3 12h2.2M18.8 12H21M5.6 5.6l1.6 1.6M16.8 16.8l1.6 1.6M18.4 5.6l-1.6 1.6M7.2 16.8l-1.6 1.6"/></svg>
      <span class="lb">Settings</span></button>
    <button class="nav theme" id="nav-theme" onclick="toggleTheme()" title="Ganti tema terang/gelap">
      <svg class="nic" viewBox="0 0 24 24" aria-hidden="true"><path d="M20 14.5A8 8 0 0 1 9.5 4 8 8 0 1 0 20 14.5Z"/></svg>
      <span class="lb" id="theme-lb">Tema gelap</span></button>
    <div class="sidefoot">dirancang berdua &middot; @bang</div>
  </aside>

  <main class="main">
    <div class="wrap">

      <!-- ============== KEUANGAN ============== -->
      <section id="v-fin" class="view on">
        <header class="ph">
          <p class="eyebrow">__TITLE__</p>
          <h1>Keuangan</h1>
          <p class="lede">Uang yang sudah ada, yang akan datang, dan semua rencana pengeluaran.</p>
        </header>
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
        <header class="ph">
          <p class="eyebrow">__TITLE__</p>
          <h1>To-do</h1>
          <p class="lede">Semua yang harus dikerjakan, di tanggalnya masing-masing.</p>
        </header>
        <div class="calbar">
          <button class="btn navbtn" onclick="shift(-1)" aria-label="sebelumnya">&lsaquo;</button>
          <button class="btn" onclick="today()">Hari ini</button>
          <button class="btn navbtn" onclick="shift(1)" aria-label="berikutnya">&rsaquo;</button>
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

      <!-- ============== SETTINGS ============== -->
      <section id="v-set" class="view">
        <header class="ph">
          <p class="eyebrow">__TITLE__</p>
          <h1>Settings</h1>
          <p class="lede">Siapa yang diingatkan lewat email, dan kapan.</p>
        </header>
        <div id="mailstatus" class="banner"></div>

        <div class="panel">
        <h3 class="sh">Pengirim</h3>
        <div class="grid2">
          <div><label>Alamat pengirim</label>
            <input id="m-from" placeholder="wedding@domainmu.com"
                   oninput="mset('from_email',this.value)">
            <div class="muted sm">harus sudah <b>verified sender</b> di Brevo</div></div>
          <div><label>Nama pengirim</label>
            <input id="m-fromname" placeholder="Wedding Planner"
                   oninput="mset('from_name',this.value)"></div>
        </div>

        </div>
        <div class="panel">
        <h3 class="sh">Daftar penerima</h3>
        <div class="muted sm">Nama di sini yang muncul sebagai pilihan di tiap to-do.</div>
        <div id="m-people"></div>
        <button class="btn" style="margin-top:8px" onclick="addPerson()">+ Tambah orang</button>

        </div>
        <div class="panel">
        <h3 class="sh">Default</h3>
        <div class="grid2">
          <div><label>Penerima default</label>
            <div class="whos" id="m-default-to"></div>
            <div class="muted sm">dipakai kalau to-do-nya nggak milih siapa-siapa</div></div>
          <div><label>Jarak pengingat default</label>
            <select id="m-lead" onchange="mset('default_lead',this.value)"></select>
            <label style="margin-top:10px">Jam default</label>
            <input id="m-time" type="time" onchange="mset('default_time',this.value)">
            <div class="muted sm">dipakai untuk to-do yang punya tanggal tapi tanpa jam</div></div>
        </div>

        </div>
        <div class="panel">
        <h3 class="sh">Saklar</h3>
        <label class="who" style="width:max-content">
          <input type="checkbox" id="m-on" onchange="mset('enabled',this.checked)">
          Pengingat email aktif</label>

        <div class="bar" style="margin:16px 0 0">
          <button class="btn" onclick="mailTest()">Kirim email tes</button>
          <span id="m-testmsg" class="muted sm"></span>
        </div>
        </div>
        <div class="muted sm" style="margin-top:14px">
          Kunci Brevo (API key / SMTP password) tetap di <code>.env</code> server, nggak
          pernah dikirim ke halaman ini.
        </div>
      </section>

    </div>

    <div class="savebar">
      <button class="primary" onclick="save()">Simpan</button>
      <button class="btn" onclick="reloadPlan()" title="ambil data terbaru dari server">&#8635; Muat ulang</button>
      <span id="status" class="ok"></span>
      <span class="muted">Simpan terakhir yang menang.</span>
    </div>
  </main>
</div>
<div class="tip" id="tip" aria-hidden="true"></div>
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
  ['fin','kan','set'].forEach(function(k){
    document.getElementById('v-'+k).className='view'+(v===k?' on':'');
    document.getElementById('nav-'+k).className='nav'+(v===k?' on':'');
  });
  try{ localStorage.setItem('view',v); }catch(e){}
  if(v==='kan') renderBoard();
  if(v==='set') renderSettings();
}
function curTheme(){
  const forced=document.documentElement.getAttribute('data-theme');
  if(forced) return forced;
  return matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light';
}
function paintThemeLabel(){
  const el=document.getElementById('theme-lb');
  if(el) el.textContent=curTheme()==='dark'?'Tema terang':'Tema gelap';
}
function toggleTheme(){
  const next=curTheme()==='dark'?'light':'dark';
  document.documentElement.setAttribute('data-theme',next);
  try{ localStorage.setItem('theme',next); }catch(e){}
  paintThemeLabel();
}
paintThemeLabel();
function toggleSide(){
  const el=document.getElementById('side'), mini=el.classList.toggle('mini');
  try{ localStorage.setItem('mini',mini?'1':''); }catch(e){}
}
try{ if(localStorage.getItem('mini')) document.getElementById('side').classList.add('mini'); }catch(e){}

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
/* Sub-items win only once one of them carries a number; until then the
   parent's own estimate stands (see amount_of in plan.py). */
const kidSum = e => kids(e.id).reduce((a,c)=>a+amountOf(c),0);
const amountOf = e => { const s=kidSum(e); return s || (Number(e.amount)||0); };
const blankCount = () => { const par=new Set(DATA.entries.filter(e=>e.parent).map(e=>e.parent));
  return DATA.entries.filter(e=>!par.has(e.id) && !(Number(e.amount)||0)).length; };
const countTop = k => DATA.entries.filter(e=>e.kind===k && !e.parent).length;

function updateSummary(){
  const tops=DATA.entries.filter(e=>!e.parent);
  const t=(k,s)=>tops.filter(e=>e.kind===k&&e.status===s).reduce((a,e)=>a+amountOf(e),0);
  const ia=t('income','actual'), ie=t('income','expected'), ea=t('expense','actual'), ee=t('expense','expected');
  const cards=[
    ['Uang di tangan', rp(ia-ea), 'diterima - dibayar', (ia-ea)>=0?'in':'out', true],
    ['Saldo proyeksi', rp((ia+ie)-(ea+ee)),
       'semua pemasukan - pengeluaran' + (blankCount()? ' · '+blankCount()+' baris belum ada nominal':''),
       ((ia+ie)-(ea+ee))>=0?'in':'out', true],
    ['Pemasukan diterima', rp(ia), '', 'in', false],
    ['Pemasukan diharapkan', rp(ie), '', 'in', false],
    ['Pengeluaran dibayar', rp(ea), '', 'out', false],
    ['Pengeluaran rencana', rp(ee), '', 'out', false],
  ];
  /* how much of everything coming in is already spoken for */
  const used=(ia+ie)>0?Math.min(100,Math.round((ea+ee)/(ia+ie)*100)):0;
  const meter='<div class="meter" title="'+used+'% pemasukan sudah dialokasikan"><i style="width:'+used+'%"></i></div>'+
              '<div class="s">'+used+'% dari total pemasukan sudah dialokasikan</div>';
  document.getElementById('cards').innerHTML = cards.map(function(c,i){
    return '<div class="card'+(c[4]?' big':'')+'"><div class="l">'+c[0]+'</div>'+
           '<div class="v '+c[3]+'">'+c[1]+'</div>'+
           (c[2]?'<div class="s'+(/belum ada nominal/.test(c[2])?' warn':'')+'">'+c[2]+'</div>':'')+
           (i===1?meter:'')+
           '</div>'; }).join('');
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
  /* Two different questions, and they must not share one flag:
       hasKids  -- draw the fold caret, so sub-items are reachable at all
       computed -- the amount is derived from them, so lock the input
     A parent whose sub-items have no numbers yet still HAS sub-items. */
  const k=kids(e.id), hasKids=k.length>0, ksum=kidSum(e), computed=ksum>0;
  const amt=computed?ksum:(Number(e.amount)||0);
  const open=hasKids&&SUBOPEN.has(e.id);
  const cls=(isSub?'sub':'')+(open?' hask':'')+(isSub&&isLast?' lastsub':'');
  const caret=isSub?'<span class="tw">&#8627;</span>'
    : hasKids ? '<button class="cr" title="buka/tutup rincian" onclick="togg(\''+e.id+'\')">'+
        (open?'&#9662;':'&#9656;')+'<b>'+k.length+'</b></button>'
    : '<span class="cr ph"></span>';
  const sel='<select onchange="upd(\''+e.id+'\',\'status\',this.value)">'+
    '<option value="actual"'+(e.status==='actual'?' selected':'')+'>Sudah</option>'+
    '<option value="expected"'+(e.status==='expected'?' selected':'')+'>Rencana</option></select>';
  return '<tr class="'+cls+'" data-id="'+e.id+'">'+
    '<td data-l="Status">'+sel+'</td>'+
    '<td class="ic" data-l="Item">'+caret+'<input value="'+esc(e.item)+'" '+
      'placeholder="'+(isSub?'rincian...':'mis. Administrasi KUA')+'" oninput="upd(\''+e.id+'\',\'item\',this.value)"></td>'+
    '<td class="amt" data-l="Nominal"><input inputmode="numeric" '+(computed?'disabled title="total dari sub-item (isi nominalnya di sub-item)"':'')+' '+
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
/* status colours: taupe -> amber -> sage, readable on both themes */
const KST={todo:['Rencana','#9a8a76'],doing:['Proses','#c98a34'],done:['Selesai','#5f9470']};
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
/* A to-do with an end date occupies every day from due to due_end. */
const isRange = t => !!(t.due && t.due_end && t.due_end > t.due);
const rangeDays = t => isRange(t)
  ? Math.round((new Date(t.due_end+'T00:00') - new Date(t.due+'T00:00'))/86400000)+1 : 1;
const spans = (t,ds) => isRange(t) ? (ds>=t.due && ds<=t.due_end) : (t.due||'')===ds;
const tasksOn  = ds => topTasks().filter(t=>spans(t,ds));

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
  if(!MAIL.ready || !t.due || t.status==='done') return false;
  if(!isRange(t) && (t.remind||'')==='off') return false;
  return !!((t.remind_to||'').trim() || (MAIL.eff_to||'').trim());
}
function pillHtml(t,ds){
  const st=KST[t.status]||KST.todo, ks=tKids(t.id), done=ks.filter(k=>k.status==='done').length;
  const run=isRange(t), cont=run&&ds&&ds!==t.due;
  const day=run&&ds?Math.round((new Date(ds+'T00:00')-new Date(t.due+'T00:00'))/86400000)+1:0;
  return '<button class="pill'+(t.status==='done'?' done':'')+(run?' run':'')+
    (cont?' cont':'')+'" draggable="'+(cont?'false':'true')+'"'+
    ' style="--c:'+st[1]+'"'+
    ' onmouseenter="tipShow(event,\'' + t.id + '\')" onmouseleave="tipHide()"'+
    ' ondragstart="dstart(event,\'' + t.id + '\')" ondragend="dend(event)"'+
    ' onclick="openTask(\'' + t.id + '\')">'+
    '<span class="pt">'+esc(t.title||'(tanpa judul)')+'</span>'+
    (run&&day?'<span class="pc">'+day+'/'+rangeDays(t)+'</span>':'')+
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
    shown.map(function(t){return pillHtml(t,ds);}).join('')+
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

/* ---- hover tooltip ---- */
let TIPT=null;
function tipShow(ev,id){
  const t=tById(id); if(!t) return;
  clearTimeout(TIPT);
  const el=document.getElementById('tip');
  const st=KST[t.status]||KST.todo, ks=tKids(t.id);
  const done=ks.filter(k=>k.status==='done').length;
  let when='';
  if(isRange(t)) when=fmtDay(t.due)+' &rarr; '+fmtDay(t.due_end)+' &middot; '+rangeDays(t)+' hari';
  else if(t.due) when=fmtDay(t.due);
  const rows=[];
  if(when) rows.push('<div class="ttr">&#128197; '+when+(t.time?', jam '+esc(t.time):'')+'</div>');
  if(t.category) rows.push('<div class="ttr">&#127991; #'+esc(t.category)+'</div>');
  if(armed(t)) rows.push('<div class="ttr">&#9993; '+esc(remindSummary(t))+'</div>');
  if(ks.length) rows.push('<div class="ttr">&#9745; '+done+'/'+ks.length+' selesai</div>');
  el.innerHTML='<div class="tth">'+esc(t.title||'(tanpa judul)')+'</div>'+
    '<div class="ttr"><span class="sdot" style="background:'+st[1]+'"></span>'+st[0]+'</div>'+
    rows.join('')+
    (t.detail?'<div class="ttr" style="white-space:normal">'+esc(t.detail.slice(0,160))+
      (t.detail.length>160?'...':'')+'</div>':'')+
    (ks.length?'<ul>'+ks.slice(0,5).map(function(k){
      return '<li class="'+(k.status==='done'?'d':'')+'">'+esc(k.title)+'</li>'; }).join('')+
      (ks.length>5?'<li>+'+(ks.length-5)+' lagi</li>':'')+'</ul>':'');
  el.classList.add('on');
  tipPlace(ev.currentTarget);
}
function tipPlace(anchor){
  const el=document.getElementById('tip'), r=anchor.getBoundingClientRect();
  const w=el.offsetWidth, h=el.offsetHeight, pad=8;
  let left=r.left, top=r.bottom+6;
  if(left+w>innerWidth-pad) left=Math.max(pad,innerWidth-w-pad);
  if(top+h>innerHeight-pad) top=Math.max(pad,r.top-h-6);
  el.style.left=left+'px'; el.style.top=top+'px';
}
function tipHide(){ clearTimeout(TIPT);
  TIPT=setTimeout(function(){ document.getElementById('tip').classList.remove('on'); },60); }
function fmtDay(ds){
  if(!ds) return '';
  const d=new Date(ds+'T00:00');
  return DAYS[(d.getDay()+6)%7]+', '+d.getDate()+' '+MONTHS[d.getMonth()].slice(0,3)+' '+d.getFullYear();
}
function remindSummary(t){
  if(isRange(t)) return 'tiap hari jam '+(t.time||MAIL.eff_time||'09:00');
  const lead=t.remind||MAIL.eff_lead;
  const to=(t.remind_to||'').trim()||MAIL.eff_to||'';
  return fmtLead(lead)+' sebelumnya'+(to?' \u2192 '+to:'');
}
addEventListener('scroll',function(){ document.getElementById('tip').classList.remove('on'); },true);

/* ---- detail drawer ---- */
function openTask(id){ SEL=id; tipHide(); renderDrw();
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
    '<label>Tanggal</label>'+
    '<div class="trow" style="margin:0">'+
      '<input style="flex:1;min-width:130px" type="date" value="'+esc(c.due)+'" '+
        'onchange="setDue(\'' + c.id + '\',this.value)" title="mulai">'+
      '<span class="muted" style="align-self:center;font-size:12px">s/d</span>'+
      '<input style="flex:1;min-width:130px" type="date" value="'+esc(c.due_end||'')+'" '+
        'onchange="setEnd(\'' + c.id + '\',this.value)" title="kosong = satu hari saja">'+
    '</div>'+
    '<div class="muted sm">isi tanggal kedua kalau to-do-nya berjalan beberapa hari '+
      '&mdash; pengingatnya dikirim tiap hari</div>'+
    '<label>Jam</label>'+
    '<input type="time" value="'+esc(c.time)+'" oninput="setTime(\'' + c.id + '\',this.value)" '+
      'title="kosong = jam '+esc(MAIL.eff_time||'09:00')+'">'+
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
function setTime(id,v){ tupd(id,'time',v); }  /* nothing on screen depends on it; don't steal focus */

/* ---- reminder controls (email, via Brevo) ---- */
function leadOpts(){
  const out=[['','ikut Settings ('+fmtLead(MAIL.eff_lead)+')'],['off','jangan ingatkan']];
  (MAIL.leads||[]).forEach(function(l,i){ out.push([l,(MAIL.lead_labels||[])[i]||l]); });
  return out;
}
function fmtLead(l){
  const i=(MAIL.leads||[]).indexOf(l);
  return i===-1?(l||'-'):(MAIL.lead_labels||[])[i];
}
function remindHtml(c){
  if(!MAIL.ready)
    return '<label>Pengingat</label><div class="muted" style="font-size:12px">'+
           'email belum jalan: '+esc(MAIL.why||'belum dikonfigurasi')+
           ' &mdash; <a href="#" onclick="setView(\'set\');return false">buka Settings</a></div>';
  const to=(c.remind_to||'').split(',').map(s=>s.trim().toLowerCase()).filter(Boolean);
  const opts=leadOpts().map(function(l){
    return '<option value="'+l[0]+'"'+((c.remind||'')===l[0]?' selected':'')+'>'+l[1]+'</option>';
  }).join('');
  const who=(MAIL.people||[]).filter(p=>p.name).map(function(p){
    const n=p.name, on=to.indexOf(n.toLowerCase())!==-1;
    return '<label class="who"><input type="checkbox" '+(on?'checked':'')+
      ' onchange="setWho(\''+c.id+'\',\''+esc(n)+'\',this.checked)"> '+esc(n)+'</label>';
  }).join('') || '<span class="muted" style="font-size:12px">daftar penerima masih kosong &mdash; '+
                 'isi di <a href="#" onclick="setView(\'set\');return false">Settings</a></span>';
  if(isRange(c)){
    const n=rangeDays(c);
    return '<label>Pengingat email</label>'+
      '<div class="banner ok" style="font-size:12px">&#9993; Tiap hari jam '+
        esc(c.time||MAIL.eff_time||'09:00')+', '+n+' hari ('+esc(c.due)+' &rarr; '+esc(c.due_end)+')</div>'+
      '<div class="whos">'+who+'</div>'+
      (to.length?'':'<div class="muted sm">belum dipilih &rarr; pakai default ('+
        esc(MAIL.eff_to||'belum diatur')+')</div>');
  }
  const note = !c.due ? 'kasih tanggal dulu biar bisa diingatkan'
    : (c.remind==='off' ? 'pengingat dimatikan untuk to-do ini'
    : (to.length?'':'belum dipilih &rarr; pakai default ('+esc(MAIL.eff_to||'belum diatur')+')'));
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
function setDue(id,v){ tupd(id,'due',v); renderDrw(); renderBoard(); }
function setEnd(id,v){ tupd(id,'due_end',v); renderDrw(); renderBoard(); }
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
function dstart(ev,id){ DRAG=id; tipHide(); ev.dataTransfer.effectAllowed='move';
  try{ev.dataTransfer.setData('text/plain',id);}catch(e){} }
function dend(ev){ DRAG=null; }
function dover(ev,ds){ ev.preventDefault(); const c=document.getElementById('d-'+ds); if(c)c.classList.add('over'); }
function dleave(ds){ const c=document.getElementById('d-'+ds); if(c)c.classList.remove('over'); }
function drop(ev,ds){ ev.preventDefault();
  const id=DRAG||(ev.dataTransfer?ev.dataTransfer.getData('text/plain'):'');
  const t=id?tById(id):null;
  if(t){
    if(isRange(t)){                       /* move the whole run, keep its length */
      const shift=Math.round((new Date(ds+'T00:00')-new Date(t.due+'T00:00'))/86400000);
      const e=new Date(t.due_end+'T00:00'); e.setDate(e.getDate()+shift);
      t.due=ds; t.due_end=iso(e);
    } else t.due=ds;
  }
  DRAG=null; renderBoard(); }

/* ================= SETTINGS =================
   MAIL holds what the server merged from plan.json + .env. Edits go straight
   back into it and ride along on the next Simpan, so one save covers
   everything on every screen. */
/* Typing must never rebuild the field being typed into, or the input loses
   focus after every keystroke. So each piece of the screen renders on its
   own, and an edit only redraws the parts that actually depend on it. */
function mset(k,v){ MAIL[k]=v; if(k==='enabled') renderBanner(); }
function mailPeople(){ return MAIL.people || (MAIL.people=[]); }
function pset(i,k,v){
  const p=mailPeople()[i]; if(!p) return;
  p[k]=v;
  if(k==='name') renderDefaultTo();   /* the checkbox labels follow the names */
}
function addPerson(){
  mailPeople().push({name:'',email:''});
  renderPeople(); renderDefaultTo();
  const rows=document.querySelectorAll('#m-people .prow');
  if(rows.length){ const inp=rows[rows.length-1].querySelector('input'); if(inp) inp.focus(); }
}
function pdel(i){ mailPeople().splice(i,1); renderPeople(); renderDefaultTo(); }
function toList(){ return (MAIL.default_to||'').split(',').map(s=>s.trim().toLowerCase()).filter(Boolean); }
function setDefaultTo(name,on){
  const cur=(MAIL.default_to||'').split(',').map(s=>s.trim()).filter(Boolean);
  const i=cur.map(s=>s.toLowerCase()).indexOf(name.toLowerCase());
  if(on&&i===-1) cur.push(name);
  if(!on&&i!==-1) cur.splice(i,1);
  MAIL.default_to=cur.join(','); renderDefaultTo();
}
function renderBanner(){
  const b=document.getElementById('mailstatus');
  const ready=MAIL.ready&&MAIL.enabled!==false;
  b.className='banner '+(ready?'ok':'warn');
  b.innerHTML=ready
    ? '&#10003; Pengingat aktif &middot; lewat '+esc(MAIL.transport)+' &middot; zona '+esc(MAIL.tz)
    : '&#9888; Belum jalan: '+esc(MAIL.why||'belum lengkap')+
      ' <span class="muted sm">(status dicek ulang setelah Simpan)</span>';
}
function renderPeople(){
  document.getElementById('m-people').innerHTML=mailPeople().map(function(p,i){
    return '<div class="prow">'+
      '<input placeholder="nama (mis. dian)" value="'+esc(p.name)+'" oninput="pset('+i+',\'name\',this.value)">'+
      '<input placeholder="email" type="email" value="'+esc(p.email)+'" oninput="pset('+i+',\'email\',this.value)">'+
      '<button class="btn del" onclick="pdel('+i+')">&#10005;</button></div>'; }).join('')
    || '<div class="muted sm">belum ada. tambahkan minimal satu orang.</div>';
}
function renderDefaultTo(){
  const sel=toList();
  document.getElementById('m-default-to').innerHTML=mailPeople().filter(p=>p.name.trim()).map(function(p){
    const on=sel.indexOf(p.name.trim().toLowerCase())!==-1;
    return '<label class="who"><input type="checkbox" '+(on?'checked':'')+
      ' onchange="setDefaultTo(\''+esc(p.name.trim())+'\',this.checked)"> '+esc(p.name)+'</label>';
  }).join('') || '<span class="muted sm">isi daftar penerima dulu</span>';
}
function renderSettings(){
  renderBanner();
  document.getElementById('m-from').value=MAIL.from_email||'';
  document.getElementById('m-fromname').value=MAIL.from_name||'';
  document.getElementById('m-time').value=MAIL.default_time||MAIL.eff_time||'';
  document.getElementById('m-on').checked=MAIL.enabled!==false;

  const leads=(MAIL.leads||[]), labels=(MAIL.lead_labels||[]);
  document.getElementById('m-lead').innerHTML=leads.map(function(l,i){
    return '<option value="'+l+'"'+((MAIL.default_lead||MAIL.eff_lead)===l?' selected':'')+'>'+
           esc(labels[i]||l)+'</option>'; }).join('');

  renderPeople(); renderDefaultTo();
}
async function mailTest(){
  const el=document.getElementById('m-testmsg');
  el.textContent='mengirim...';
  try{
    const r=await fetch('/api/mailtest?token='+encodeURIComponent(TOKEN),
      {method:'POST',headers:{'content-type':'application/json'},
       body:JSON.stringify({mail:MAIL,to:''})});
    const j=await r.json();
    el.textContent=j.message||'selesai';
  }catch(e){ el.textContent='gagal: '+e; }
}

/* ================= save ================= */
/* The bot writes to the same file from WhatsApp. This page holds whatever it
   loaded, so a plain save would silently wipe anything added since. Check the
   server's revision first and let the human decide. */
async function serverStamp(){
  try{
    const r=await fetch('/api/plan?token='+encodeURIComponent(TOKEN));
    if(!r.ok) return null;
    return (await r.json()).updated_at || null;
  }catch(e){ return null; }
}
async function reloadPlan(){
  const st=document.getElementById('status'); st.textContent='memuat ulang...';
  try{
    const r=await fetch('/api/plan?token='+encodeURIComponent(TOKEN));
    adopt(await r.json());
    st.textContent='dimuat ulang \u2713'; setTimeout(function(){st.textContent='';},2500);
  }catch(e){ st.textContent='gagal memuat: '+e.message; }
}
function adopt(d){
  DATA=d; DATA.entries=DATA.entries||[]; DATA.tasks=DATA.tasks||[];
  DATA.entries.forEach(e=>{ if(!e.parent) e.parent=''; });
  DATA.tasks.forEach(t=>{ if(!t.parent) t.parent=''; });
  document.getElementById('notes').value=DATA.notes||'';
  render(); if(VIEW==='kan') renderBoard(); if(VIEW==='set') renderSettings();
}
async function save(){
  const stamp=await serverStamp();
  if(stamp && DATA.updated_at && stamp!==DATA.updated_at){
    const ok=confirm('Data di server sudah berubah sejak halaman ini dibuka '+
      '(mungkin dari bot WhatsApp).\n\nOK = timpa dengan yang di layar ini.\n'+
      'Cancel = batal, muat ulang data terbaru.');
    if(!ok){ await reloadPlan(); return; }
  }
  const body={mail:MAIL,
    entries:DATA.entries.filter(e=>e.item||e.amount||kids(e.id).length),
    tasks:DATA.tasks.filter(t=>(t.title||'').trim()),
    notes:document.getElementById('notes').value };
  const st=document.getElementById('status'); st.textContent='menyimpan...';
  try{
    const r=await fetch('/api/plan?token='+encodeURIComponent(TOKEN),
      {method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(body)});
    if(!r.ok) throw new Error(r.status);
    adopt(await r.json());
    st.textContent='tersimpan ✓'; setTimeout(function(){st.textContent='';},2500);
  }catch(e){ st.textContent='gagal menyimpan: '+e.message; }
}

document.getElementById('notes').value = DATA.notes || '';
render();
</script>
</body></html>"""
