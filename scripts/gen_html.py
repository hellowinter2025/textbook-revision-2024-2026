# -*- coding: utf-8 -*-
"""把改动清单 TXT 渲染成自包含的单页 HTML（侧栏导航 + 搜索 + 修订着色）。

    py _preview/gen_html.py [TXT] [HTML]
"""
import io, os, re, sys, json
sys.stdout.reconfigure(encoding='utf-8')
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..'))

SRC = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, '对比结果/2024版与2026版教材改动清单.txt')
DST = sys.argv[2] if len(sys.argv) > 2 else os.path.join(ROOT, '对比结果/2024版与2026版教材改动清单.html')

FW = '\u3000'
RE_SUBJ = re.compile(r'^[一二三四五六七八九十]+、(.*)$')
RE_GROUP = re.compile(r'^◆ 改动组 (\d+)（(.*)）$')
RE_WHOLE = re.compile(r'^◆ 整篇(新增|删除)（对应改动组 (\d+)）$')
RE_INFO = re.compile(r'^全书 \d+ 个改动组、\d+ 处改动。$')
RE_PARAS = re.compile(r'^(改动前|改动后|删去内容|新增内容)：')


def esc(s):
    return (s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
             .replace('"', '&quot;'))


def indent(l):
    n = 0
    while n < len(l) and l[n] == FW:
        n += 1
    return n


def parse(path):
    raw = io.open(path, encoding='utf-8-sig').read().splitlines()
    out = {'title': '', 'sub': '', 'stats': [], 'note': [], 'subjects': []}
    cur = book = grp = chg = None
    mode = 'head'
    for l in raw:
        if not l.strip():
            continue
        t = l.strip(FW).rstrip()
        ind = indent(l)
        if ind == 0:
            m = RE_SUBJ.match(l)
            if m and '、' in l:
                cur = {'name': m.group(1).strip(), 'books': []}
                out['subjects'].append(cur)
                book = grp = chg = None
                mode = 'body'
                continue
            if l.startswith('【'):
                book = {'name': l.strip('【】').strip(), 'info': '', 'note': '', 'groups': []}
                if cur is None:
                    cur = {'name': '', 'books': []}; out['subjects'].append(cur)
                cur['books'].append(book)
                grp = chg = None
                continue
            if mode == 'head':
                if not out['title']:
                    out['title'] = t; continue
                if t.startswith('（'):
                    out['sub'] = t; continue
                if t.startswith('共 ') or t.startswith('生成日期'):
                    out['stats'].append(t); continue
                if t.startswith('阅读说明') or set(t) <= set('－'):
                    continue
                if re.match(r'^\d+\.', t) or out['note']:
                    out['note'].append(t)
            continue
        if ind == 2:
            m = RE_GROUP.match(t)
            if m:
                grp = {'no': int(m.group(1)), 'pages': m.group(2), 'whole': None,
                       'sent': '', 'changes': []}
                book['groups'].append(grp); chg = None
                continue
            m = RE_WHOLE.match(t)
            if m:
                grp = {'no': int(m.group(2)), 'pages': '', 'whole': m.group(1),
                       'sent': '', 'changes': []}
                book['groups'].append(grp); chg = None
                continue
            if RE_INFO.match(t):
                book['info'] = t; continue
            if t.startswith('两版逐字比对未发现差异'):
                book['note'] = t; continue
            if grp is not None and grp.get('whole') and not grp['sent'] and t.endswith('。'):
                grp['sent'] = t; continue
            if grp is None:
                continue
            chg = {'t': t, 'ctx': '', 'paras': []}
            grp['changes'].append(chg)
            continue
        if ind in (4, 5):
            if t.startswith('（所在句：'):
                if chg: chg['ctx'] = t
                continue
            m = RE_PARAS.match(t)
            if m and chg:
                chg['paras'].append({'k': m.group(1), 'v': t[m.end():]})
                continue
            if chg and chg['paras']:
                chg['paras'][-1]['v'] += t
            continue
        if ind >= 6 and chg is not None:
            if ind == 6 and chg['paras']:
                chg['paras'][-1]['v'] += t
            elif ind == 7 and chg['ctx']:
                chg['ctx'] += t
            continue

    # 说明书：把折行的续行并进上一条
    note = []
    for n in out['note']:
        if re.match(r'^\d+\.', n) or not note:
            note.append(n)
        else:
            note[-1] += n
    out['note'] = note

    # 「所在句」去掉 TXT 里的外层包装（渲染时由标签代替），并标出「数据表碎片」行
    RE_CJK = re.compile(r'[\u4e00-\u9fff]')
    nfrag = 0
    for s in out['subjects']:
        for b in s['books']:
            for g in b['groups']:
                for c in g['changes']:
                    v = c['ctx']
                    if v:
                        if v.startswith('（所在句：'): v = v[len('（所在句：'):]
                        if v.endswith('）'): v = v[:-1]
                        c['ctx'] = v
                    # 无汉字、无空格、含数字 → 元素周期表/原子量表这类数据表被重排后的碎片
                    if v and not RE_CJK.search(v) and ' ' not in v and re.search(r'\d', v):
                        c['frag'] = 1; nfrag += 1
    out['__nfrag'] = nfrag

    for s in out['subjects']:
        s['groups'] = sum(len(b['groups']) for b in s['books'])
        s['changes'] = sum(len(g['changes']) for b in s['books'] for g in b['groups'])
    return out


HTML = r'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title>
<style>
:root{
  --paper:#F6F2EA; --card:#FFF; --ink:#22252A; --dim:#6C7078; --faint:#9AA0A8;
  --line:#E6E0D6; --line2:#EFEAE1; --red:#9E2B25; --red-soft:#B4453F;
  --green:#1A6248; --gold:#A9803A;
  --sans:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Hiragino Sans GB","Microsoft YaHei","Noto Sans CJK SC",sans-serif;
  --serif:"Songti SC","SimSun","Source Han Serif SC","Noto Serif CJK SC",Georgia,serif;
  --mono:ui-monospace,SFMono-Regular,Menlo,Consolas,"Liberation Mono",monospace;
}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
body{margin:0;background:var(--paper);color:var(--ink);font-family:var(--sans);
  font-size:15px;line-height:1.75;-webkit-font-smoothing:antialiased}
.layout{display:flex;min-height:100vh;align-items:flex-start}

aside{width:290px;flex:0 0 290px;position:sticky;top:0;height:100vh;overflow-y:auto;
  background:#FBF8F3;border-right:1px solid var(--line);padding:22px 0 34px}
aside::-webkit-scrollbar{width:9px}
aside::-webkit-scrollbar-thumb{background:#DED7CB;border-radius:9px}
.brand{padding:0 20px 16px;border-bottom:1px solid var(--line2);margin-bottom:12px}
.brand h1{margin:0 0 5px;font-family:var(--serif);font-size:17px;font-weight:700;letter-spacing:.02em}
.brand p{margin:0;font-size:11.5px;color:var(--faint);letter-spacing:.04em}
.navsec{padding:6px 20px 4px;font-size:11px;color:var(--faint);letter-spacing:.14em}
.navsub>summary{list-style:none;cursor:pointer;display:flex;align-items:baseline;gap:9px;
  padding:8px 20px;font-weight:600;font-size:13.5px;border-left:3px solid transparent}
.navsub>summary::-webkit-details-marker{display:none}
.navsub>summary:hover{background:#F3EEE5}
.navsub>summary .dot{width:7px;height:7px;border-radius:50%;background:var(--red);opacity:.72;flex:0 0 7px}
.navsub>summary .cnt{margin-left:auto;font-family:var(--mono);font-size:11px;color:var(--faint);font-weight:400}
.navbook{display:flex;gap:8px;align-items:baseline;padding:5px 20px 5px 35px;font-size:12.5px;
  color:var(--dim);text-decoration:none;border-left:3px solid transparent}
.navbook:hover{background:#F3EEE5;color:var(--ink)}
.navbook .n{margin-left:auto;font-family:var(--mono);font-size:10.5px;color:var(--faint)}
.sidefoot{padding:16px 20px 0;margin-top:16px;border-top:1px solid var(--line2);
  font-size:11px;color:var(--faint);line-height:1.95}

main{flex:1 1 auto;min-width:0;padding-bottom:90px}
header.top{position:sticky;top:0;z-index:20;background:rgba(246,242,234,.93);
  backdrop-filter:saturate(180%) blur(10px);border-bottom:1px solid var(--line);padding:14px 40px 13px}
.htitle{display:flex;align-items:baseline;gap:14px;flex-wrap:wrap}
.htitle h2{margin:0;font-family:var(--serif);font-size:21px;letter-spacing:.01em}
.htitle .sub{font-size:12.5px;color:var(--dim)}
.pills{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}
.pill{font-size:12px;color:var(--dim);background:#fff;border:1px solid var(--line);
  border-radius:999px;padding:2.5px 11px}
.pill b{color:var(--red);font-family:var(--mono);font-weight:600}
.tools{display:flex;gap:10px;align-items:center;margin-top:12px;flex-wrap:wrap}
.search{position:relative;flex:1 1 280px;max-width:480px}
.search input{width:100%;padding:9px 34px;border:1px solid var(--line);border-radius:9px;background:#fff;
  font-size:13.5px;font-family:var(--sans);color:var(--ink);outline:none}
.search input:focus{border-color:var(--red-soft);box-shadow:0 0 0 3px rgba(158,43,37,.09)}
.search .ico{position:absolute;left:11px;top:50%;transform:translateY(-50%);color:var(--faint);font-size:13px}
.search .clr{position:absolute;right:9px;top:50%;transform:translateY(-50%);border:0;background:transparent;
  color:var(--faint);cursor:pointer;font-size:16px;padding:2px 6px;display:none;line-height:1}
.search .clr.on{display:block}
.seg{display:flex;border:1px solid var(--line);border-radius:9px;overflow:hidden;background:#fff}
.seg button{border:0;background:transparent;padding:8px 13px;font-size:12.5px;cursor:pointer;color:var(--dim);
  font-family:var(--sans);border-right:1px solid var(--line2)}
.seg button:last-child{border-right:0}
.seg button:hover{background:#FAF7F1}
.seg button.on{background:#F1E9DC;color:var(--red);font-weight:600}
.meta{margin-left:auto;font-size:12px;color:var(--faint);font-family:var(--mono)}
.tg{border:1px solid var(--line);background:#fff;color:var(--dim);font-size:12.5px;font-family:var(--sans);
  padding:8px 13px;border-radius:9px;cursor:pointer}
.tg b{font-family:var(--mono);font-weight:600;color:var(--faint);margin-left:3px}
.tg.on{background:#F1E9DC;color:var(--red);border-color:#E3D6C1}
.tg.on b{color:var(--red)}
.tg:hover{border-color:var(--red-soft)}

.wrap{padding:26px 40px 0;max-width:1180px}
.note{background:#FFFDF8;border:1px solid var(--line);border-radius:12px;padding:17px 22px 15px;margin-bottom:8px}
.note h3{margin:0 0 8px;font-size:11.5px;letter-spacing:.14em;color:var(--faint);font-weight:600}
.note ol{margin:0;padding-left:1.6em;color:var(--dim);font-size:13px;line-height:1.95}
.note li{margin:.2em 0}

.subj{margin:44px 0 2px;padding-bottom:9px;border-bottom:2px solid var(--ink);
  display:flex;align-items:baseline;gap:12px;flex-wrap:wrap}
.subj h2{margin:0;font-family:var(--serif);font-size:23px;font-weight:700}
.subj .cnt{font-size:12.5px;color:var(--dim)}
.subj .cnt b{font-family:var(--mono);color:var(--red)}
.book{margin:24px 0 8px;display:flex;align-items:baseline;gap:11px;flex-wrap:wrap}
.book h3{margin:0;font-family:var(--serif);font-size:17px;color:#3A3F46}
.book .info{font-size:12.5px;color:var(--faint)}
.book.empty h3{color:var(--faint)}

.card{background:var(--card);border:1px solid var(--line);border-radius:13px;margin:13px 0;
  box-shadow:0 1px 2px rgba(34,37,42,.03);overflow:hidden}
.card.whole{background:#FFFBEF;border-color:#F0E3C4}
.chead{display:flex;align-items:center;gap:11px;padding:10px 18px;background:#FCFAF6;
  border-bottom:1px solid var(--line2);font-size:12.5px;color:var(--dim);flex-wrap:wrap}
.card.whole .chead{background:#FDF6E4}
.gno{font-family:var(--mono);font-size:11.5px;font-weight:700;color:#fff;background:var(--red);
  border-radius:6px;padding:1.5px 8px}
.card.whole .gno{background:var(--gold)}
.pages{font-family:var(--mono);font-size:11.5px;color:var(--dim)}
.cbody{padding:4px 18px 13px}

.row{position:relative;padding:9px 0;border-bottom:1px dashed var(--line2)}
.row:last-child{border-bottom:0}
.row .txt{font-size:15px;line-height:1.85}
.ty{display:inline-block;font-size:10.5px;font-weight:700;border-radius:5px;padding:1px 6px;
  margin-right:8px;vertical-align:1.6px;letter-spacing:.03em}
.ty.改,.ty.删{color:#8A2B26;background:#FBEDEC}
.ty.增{color:#1A6248;background:#EAF5EF}
.ty.整{color:#8A6A22;background:#FAF0D8}
.copy{position:absolute;right:0;top:8px;border:1px solid var(--line);background:#fff;color:var(--faint);
  font-size:11px;padding:2px 8px;border-radius:6px;cursor:pointer;opacity:0;transition:.15s}
.row:hover .copy{opacity:1}
.copy:hover{color:var(--red);border-color:var(--red-soft)}

.ctx{margin:7px 0 2px;background:#FFFCF2;border-left:3px solid #E9D9A8;border-radius:0 8px 8px 0;
  padding:9px 14px 10px;font-family:var(--serif);font-size:14.5px;line-height:1.95;color:#4A4741}
.ctx .lab{display:block;font-family:var(--sans);font-size:10.5px;letter-spacing:.13em;
  color:#B09A5E;margin-bottom:3px}
details.para{background:#FAF8F4;border:1px solid var(--line2);border-radius:9px;margin:7px 0;overflow:hidden}
details.para>summary{cursor:pointer;padding:8px 14px;font-size:12.5px;color:var(--dim);list-style:none;
  display:flex;gap:9px;align-items:center}
details.para>summary::-webkit-details-marker{display:none}
details.para>summary::before{content:"▸";color:var(--faint);transition:.15s}
details.para[open]>summary::before{transform:rotate(90deg)}
details.para>summary .tag{font-size:10.5px;font-weight:700;border-radius:5px;padding:1px 7px}
.k-改动前 .tag,.k-删去内容 .tag{color:#8A2B26;background:#FBEDEC}
.k-改动后 .tag,.k-新增内容 .tag{color:#1A6248;background:#EAF5EF}
details.para .pv{padding:2px 16px 14px;font-family:var(--serif);font-size:14px;line-height:1.95;
  color:#45484E;white-space:pre-wrap;word-break:break-word}

.old{color:#A3282A;text-decoration:line-through;text-decoration-thickness:1px}
.new{color:#1A6248;font-weight:600;border-bottom:1.5px solid #9CCBB6}
.arw{color:var(--faint);margin:0 3px;font-size:12px}
.mk{border-radius:4px;padding:0 3px}
.mk.del{color:#A3282A;background:#FBEDEC;text-decoration:line-through}
.mk.add{color:#1A6248;background:#EAF5EF;border-bottom:1.5px solid #9CCBB6}
.empty-note{color:var(--faint);font-size:13.5px;padding:6px 0 14px}
#top{position:fixed;right:26px;bottom:26px;width:42px;height:42px;border-radius:50%;border:1px solid var(--line);
  background:#fff;color:var(--dim);cursor:pointer;font-size:16px;box-shadow:0 3px 12px rgba(0,0,0,.08);
  opacity:0;pointer-events:none;transition:.2s;z-index:30}
#top.on{opacity:1;pointer-events:auto}
#top:hover{color:var(--red)}
mark.hit{background:#FFF2A8;color:inherit;padding:0 1px;border-radius:2px}
.hide{display:none!important}

@media (max-width:1000px){
  .layout{display:block}
  aside{position:static;width:auto;height:auto;flex:none;border-right:0;border-bottom:1px solid var(--line)}
  #nav{max-height:240px;overflow:auto}
  header.top,.wrap{padding-left:18px;padding-right:18px}
}
@media print{
  aside,.tools,#top,.copy{display:none!important}
  body{background:#fff}
  header.top{position:static;background:#fff}
  .card{break-inside:avoid;box-shadow:none}
  .wrap{padding:0;max-width:none}
  details.para{display:block}
}
</style>
</head>
<body>
<div class="layout">
<aside>
  <div class="brand">
    <h1>2024 版 ⇄ 2026 版</h1>
    <p>高中教材改动清单 · 自然语言版</p>
  </div>
  <div class="navsec">学科 / 分册</div>
  <div id="nav"></div>
  <div class="sidefoot">__FOOT__</div>
</aside>
<main>
  <header class="top">
    <div class="htitle">
      <h2>高中教材改动清单</h2>
      <span class="sub">2024 版 ⇄ 2026 版 · 每条改动附「所在句」</span>
    </div>
    <div class="pills" id="pills"></div>
    <div class="tools">
      <div class="search">
        <span class="ico">🔍</span>
        <input id="q" type="search" placeholder="搜索改动文字、课文名、页码…（按 / 聚焦）" autocomplete="off">
        <button class="clr" id="clr" title="清空">×</button>
      </div>
      <div class="seg" id="seg">
        <button data-f="all" class="on">全部</button>
        <button data-f="改">改写</button>
        <button data-f="删">删去</button>
        <button data-f="增">新增</button>
        <button data-f="ctx">带所在句</button>
      </div>
      <button class="tg on" id="nofrag" title="化学附录的元素周期表／相对原子质量表在 2026 版被重排成矢量文字，改动会以元素符号碎片呈现，可一键隐藏">隐藏数据表碎片 <b id="nfrag">0</b></button>
      <span class="meta" id="meta"></span>
    </div>
  </header>
  <div class="wrap" id="root"></div>
</main>
</div>
<button id="top" title="回到顶部">↑</button>
<script id="data" type="application/json">__DATA__</script>
<script>
const D = JSON.parse(document.getElementById('data').textContent);
const esc = s => s.replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));

/* 【…】→ 修订着色 */
function rev(s){
  return s.replace(/【([^】]*)】/g, (m, inner) => {
    let x = inner.match(/^([\s\S]*?)→([\s\S]*)$/);
    if (x) return '<span class="old">' + x[1] + '</span><span class="arw">→</span><span class="new">' + x[2] + '</span>';
    x = inner.match(/^删：([\s\S]*)$/);
    if (x) return '<span class="mk del">' + x[1] + '</span>';
    x = inner.match(/^增：([\s\S]*)$/);
    if (x) return '<span class="mk add">' + x[1] + '</span>';
    return '<span class="mk">' + inner + '</span>';
  });
}
/* 改动句：把“A”“B”也着上色 */
function sentHTML(s){
  let h = esc(s);
  h = h.replace(/将“([^”]*)”修改成了“([^”]*)”/,
        (m,a,b) => '将<span class="old">“' + a + '”</span><span class="arw">→</span><span class="new">“' + b + '”</span>');
  h = h.replace(/删去了“([^”]*)”/, (m,a) => '删去了<span class="mk del">“' + a + '”</span>');
  h = h.replace(/增加了“([^”]*)”/, (m,a) => '增加了<span class="mk add">“' + a + '”</span>');
  return h;
}
const tyOf = t => t.includes('删去') ? '删' : (t.includes('增加了') ? '增' : '改');
const TYN = {'改':'改写','删':'删去','增':'新增','整':'整篇'};

const nav = [], root = [];
let nGroups = 0, nLines = 0, nChanges = 0, nCtx = 0;
const RE_CNT = /（同一页上共有 (\d+) 处一模一样的改动）/;
D.subjects.forEach((s, si) => {
  if (!s.books.length) return;
  const sid = 's' + si;
  nav.push(`<details class="navsub" ${si < 2 ? 'open' : ''}>
    <summary><span class="dot"></span>${esc(s.name)}<span class="cnt">${s.groups}</span></summary>
    ${s.books.map((b, bi) => `<a class="navbook" href="#${sid}b${bi}">${esc(b.name)}<span class="n">${b.groups.length}</span></a>`).join('')}
  </details>`);
  const parts = [`<section class="sj" id="${sid}">`,
    `<div class="subj"><h2>${esc(s.name)}</h2><span class="cnt">${s.books.length} 册 · <b>${s.groups}</b> 个改动组 · <b>${s.changes}</b> 处改动</span></div>`];
  s.books.forEach((b, bi) => {
    nGroups += b.groups.length;
    parts.push(`<section class="bk" id="${sid}b${bi}">`);
    parts.push(`<div class="book ${b.groups.length ? '' : 'empty'}"><h3>${esc(b.name)}</h3><span class="info">${esc(b.note || b.info || '')}</span></div>`);
    if (!b.groups.length) {
      parts.push(`</section>`);
      return;
    }
    b.groups.forEach(g => {
      if (g.whole) {
        nLines++; nChanges += 1;
        parts.push(`<div class="card whole"><div class="chead"><span class="gno">${g.whole}</span>` +
                   `<span class="pages">${esc(g.pages || '')}</span></div><div class="cbody">`);
        if (g.sent) parts.push(`<div class="row" data-ty="整"><div class="txt">${sentHTML(g.sent)}</div></div>`);
        parts.push(`</div></div>`);
        return;
      }
      parts.push(`<div class="card"><div class="chead"><span class="gno">组 ${g.no}</span>` +
                 `<span class="pages">${esc(g.pages)}</span></div><div class="cbody">`);
      g.changes.forEach(c => {
        const ty = tyOf(c.t);
        const cm = c.t.match(RE_CNT);
        nLines++; nChanges += cm ? parseInt(cm[1], 10) : 1;
        let row = `<div class="row" data-ty="${ty}"${c.frag ? ' data-frag="1"' : ''}>` +
                  `<button class="copy" title="复制这一条">复制</button>` +
                  `<div class="txt"><span class="ty ${ty}">${TYN[ty]}</span>${sentHTML(c.t)}</div>`;
        if (c.ctx) {
          nCtx++;
          row += `<div class="ctx"><span class="lab">所在句</span>${rev(esc(c.ctx))}</div>`;
        }
        c.paras.forEach(p => {
          row += `<details class="para k-${esc(p.k)}"><summary><span class="tag">${esc(p.k)}</span>` +
                 `<span>${p.v.length} 字 · 点击展开</span></summary>` +
                 `<div class="pv">${rev(esc(p.v))}</div></details>`;
        });
        parts.push(row + `</div>`);
      });
      parts.push(`</div></div>`);
    });
    parts.push(`</section>`);
  });
  parts.push(`</section>`);
  root.push(parts.join(''));
});

document.getElementById('nav').innerHTML = nav.join('');
document.getElementById('root').innerHTML = root.join('');

const nBooks = D.subjects.reduce((a, s) => a + s.books.length, 0);
document.getElementById('pills').innerHTML =
  `<span class="pill">教材 <b>${D.subjects.length}</b> 套</span>` +
  `<span class="pill">分册 <b>${nBooks}</b> 册</span>` +
  `<span class="pill">改动组 <b>${nGroups}</b></span>` +
  `<span class="pill">改动 <b>${nChanges}</b> 处</span>` +
  `<span class="pill">列表 <b>${nLines}</b> 条</span>` +
  `<span class="pill">附所在句 <b>${nCtx}</b> 条</span>`;
const nFrag = document.querySelectorAll('.row[data-frag]').length;
document.getElementById('nfrag').textContent = nFrag;

/* 复制 */
function fb(t, done){
  const ta = document.createElement('textarea');
  ta.value = t; ta.style.cssText = 'position:fixed;opacity:0';
  document.body.appendChild(ta); ta.select();
  try { document.execCommand('copy'); done(); } catch (e) {}
  document.body.removeChild(ta);
}
document.getElementById('root').addEventListener('click', e => {
  const b = e.target.closest('.copy'); if (!b) return;
  const row = b.closest('.row');
  const tel = row.querySelector('.txt');
  let out = (tel.innerText || tel.textContent || '').replace(/^(改写|删去|新增|整篇)/, '').trim();
  const cx = row.querySelector('.ctx');
  if (cx) out += '\n（所在句：' + (cx.innerText || cx.textContent || '').replace(/^所在句/, '').trim() + '）';
  const done = () => { const o = b.textContent; b.textContent = '已复制'; setTimeout(() => b.textContent = o, 1100); };
  if (navigator.clipboard && window.isSecureContext) navigator.clipboard.writeText(out).then(done).catch(() => fb(out, done));
  else fb(out, done);
});

/* 搜索 / 筛选（含命中高亮，只动文本节点，不破坏修订着色的标签） */
const qEl = document.getElementById('q'), clr = document.getElementById('clr');
const cards = [...document.querySelectorAll('.card')];
const rows  = [...document.querySelectorAll('.row')];
const txtEls = rows.map(r => r.querySelector('.txt'));
const rawTxt = txtEls.map(e => e ? e.innerHTML : '');
/* ⚠️ 用 textContent 建索引，不要用 innerText：innerText 依赖布局，隐藏元素会取到空串，
   而且在无布局环境里可能根本不存在（jsdom 就是 undefined，会让整条筛选逻辑抛异常）。 */
const plain = rows.map(r => (r.textContent || '').toLowerCase());
const bks   = [...document.querySelectorAll('.bk')];
const sjs   = [...document.querySelectorAll('.sj')];
const links = [...document.querySelectorAll('.navbook')];
let filt = 'all', hideFrag = true;

function hl(el, html, kw){
  el.innerHTML = html;
  const w = document.createTreeWalker(el, NodeFilter.SHOW_TEXT, null);
  const hits = []; let n;
  while ((n = w.nextNode())) if (n.nodeValue.toLowerCase().includes(kw)) hits.push(n);
  hits.forEach(node => {
    const v = node.nodeValue, low = v.toLowerCase();
    const frag = document.createDocumentFragment();
    let i = 0, j;
    while ((j = low.indexOf(kw, i)) !== -1) {
      if (j > i) frag.appendChild(document.createTextNode(v.slice(i, j)));
      const m = document.createElement('mark');
      m.className = 'hit'; m.textContent = v.slice(j, j + kw.length);
      frag.appendChild(m);
      i = j + kw.length;
    }
    if (i < v.length) frag.appendChild(document.createTextNode(v.slice(i)));
    if (node.parentNode) node.parentNode.replaceChild(frag, node);
  });
}
let hlSet = new Set();

function apply(){
  const kw = qEl.value.trim().toLowerCase();
  const on = !!kw || filt !== 'all' || hideFrag;
  let shown = 0;
  rows.forEach((r, i) => {
    const ok = (!kw || plain[i].includes(kw)) &&
               (filt === 'all' || (filt === 'ctx' ? !!r.querySelector('.ctx') : r.dataset.ty === filt)) &&
               (!hideFrag || r.dataset.frag !== '1');
    r.classList.toggle('hide', !ok);
    if (ok) shown++;
    const el = txtEls[i];
    if (!el) return;
    if (!kw || !ok) {
      if (hlSet.has(i)) { el.innerHTML = rawTxt[i]; hlSet.delete(i); }
    } else if (!hlSet.has(i)) { hl(el, rawTxt[i], kw); hlSet.add(i); }
  });
  cards.forEach(c => {
    const vis = [...c.querySelectorAll('.row')].some(r => !r.classList.contains('hide'));
    c.classList.toggle('hide', !vis);
  });
  bks.forEach(k => {
    const any = [...k.querySelectorAll('.card')].some(c => !c.classList.contains('hide'));
    k.classList.toggle('hide', on && !any);
  });
  sjs.forEach(s => {
    const any = [...s.querySelectorAll('.bk')].some(k => !k.classList.contains('hide'));
    s.classList.toggle('hide', on && !any);
  });
  links.forEach(a => {
    const k = document.getElementById(a.getAttribute('href').slice(1));
    a.classList.toggle('hide', !!k && k.classList.contains('hide'));
  });
  document.getElementById('meta').textContent =
    (!kw && filt === 'all' && hideFrag)
      ? `${nChanges} 处 · 已折叠 ${nFrag} 条数据表碎片`
      : (on ? `显示 ${shown} 条 / 共 ${nLines} 条` : `${nChanges} 处`);
  clr.classList.toggle('on', !!kw);
}
document.getElementById('nofrag').addEventListener('click', e => {
  hideFrag = !hideFrag;
  e.currentTarget.classList.toggle('on', hideFrag);
  apply();
});
document.getElementById('seg').addEventListener('click', e => {
  const b = e.target.closest('button'); if (!b) return;
  [...e.currentTarget.children].forEach(x => x.classList.toggle('on', x === b));
  filt = b.dataset.f; apply();
});
qEl.addEventListener('input', apply);
clr.addEventListener('click', () => { qEl.value = ''; apply(); qEl.focus(); });
document.addEventListener('keydown', e => {
  if (e.key === '/' && document.activeElement !== qEl) { e.preventDefault(); qEl.focus(); }
  if (e.key === 'Escape' && document.activeElement === qEl) { qEl.value = ''; apply(); qEl.blur(); }
});
apply();          // 初始化一次，让顶部就显示出「N 处」

/* 注意：不要用 top / parent / self / length 这类内置 window 属性名做 const —— 
   顶层的 const 与已有的不可配置全局属性同名会直接抛 SyntaxError，整页脚本全废。 */
const btnTop = document.getElementById('top');
addEventListener('scroll', () => btnTop.classList.toggle('on', scrollY > 600), {passive: true});
btnTop.addEventListener('click', () => scrollTo({top: 0, behavior: 'smooth'}));
</script>
</body>
</html>
'''


def main():
    d = parse(SRC)
    if not d['title']:
        print('!! 解析失败'); return
    foot = '<br>'.join([d['title']] + d['stats'] + ['PDF / JSON 见仓库 docs/ 与 json/'])
    html = (HTML.replace('__TITLE__', d['title'])
                .replace('__FOOT__', foot)
                .replace('__DATA__', json.dumps(d, ensure_ascii=False).replace('</', '<\\/')))
    io.open(DST, 'w', encoding='utf-8').write(html)
    ng = sum(len(b['groups']) for s in d['subjects'] for b in s['books'])
    nc = sum(len(g['changes']) for s in d['subjects'] for b in s['books'] for g in b['groups'])
    nw = sum(1 for s in d['subjects'] for b in s['books'] for g in b['groups'] if g['whole'])
    nr = sum(1 for s in d['subjects'] for b in s['books'] for g in b['groups']
             for c in g['changes'] if c['ctx'])
    print('已写出 %s' % DST)
    print('  %d 套 / %d 册 / %d 组 / %d 处改动 / %d 整篇组 / %d 条带所在句'
          % (len(d['subjects']), sum(len(s['books']) for s in d['subjects']), ng, nc, nw, nr))
    print('  %.2f MB' % (os.path.getsize(DST) / 1e6))


if __name__ == '__main__':
    main()
