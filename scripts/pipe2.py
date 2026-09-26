# -*- coding: utf-8 -*-
"""
通用「改动页对照」管线 v2 —— 支持按册并行调度

单个任务由 runjobs.py（或手工）以子进程方式调用：
    py _preview/pipe2.py one       <taskkey> <册名>    # 计算一册的逐字差异 → _preview/items/<key>/<册>.json
    py _preview/pipe2.py buildone  <taskkey> <册名>    # 生成一册的对照 PDF → _tmp_pipe/<key>/<册>.pdf
    py _preview/pipe2.py merge     <taskkey>           # 把该任务各册合并成一本 → 对比结果/<label>/修改页对照_<label>.pdf
    py _preview/pipe2.py list                          # 列出全部任务与册

核心算法与 pipe.py 相同：位置重复检测识别书眉页码并掩码（两侧取并集）、
char 级 difflib、四级伪差异剔除、插入点参考页向前跳过掩码、编号固定页边。
"""
import sys, os, re, json, fitz, difflib, traceback, time
sys.stdout.reconfigure(encoding='utf-8')

OUT_ROOT = '对比结果'
ITEMS_DIR = '_preview/items'
JOBS_LOG = '_preview/jobs'
MASK = '\uFFFE'
WS = re.compile(r'\s+')

DISP_W = 595.276
DISP_H = 841.890
MARGIN = 26.0
GAP    = 20.0
BAND   = 46.0
HEAD   = 170.0
FOOT   = 34.0
PW = MARGIN + DISP_W + GAP + DISP_W + MARGIN
PH = HEAD + DISP_H + FOOT
X_L = MARGIN
X_R = MARGIN + DISP_W + GAP
Y0  = HEAD

CN     = 'china-s'
BANDC  = (0.106, 0.165, 0.420)
RED    = (0.784, 0.063, 0.129)
FILLC  = (1.000, 0.588, 0.588)
LINE   = (0.62, 0.64, 0.68)
GRAY   = (0.42, 0.44, 0.48)
FILL_OP = 0.34

TASKS = [
    dict(key='M语文统编', label='语文·统编版', old='2024/1-语文',
         new='2026_去水印/语文/统编版', words=['语文']),
    dict(key='A数学苏教', label='数学·苏教版', old='2024/2-数学',
         new='2026_去水印/数学/苏教版', words=['数学']),
    dict(key='B英语译林', label='英语·译林版', old='2024/3-英语',
         new='2026_去水印/英语/译林版', words=['英语']),
    dict(key='C物理人教', label='物理·人教版', old='2024/4-物理',
         new='2026_去水印/物理/人教版', words=['物理']),
    dict(key='D化学苏教', label='化学·苏教版', old='2024/5-化学',
         new='2026_去水印/化学/苏教版', words=['化学']),
    dict(key='E生物苏教', label='生物·苏教版', old='2024/6-生物',
         new='2026_去水印/生物学/苏教版', words=['生物学']),
    dict(key='F生物人教', label='生物·人教版', old='2024/6-生物/人教版',
         new='2026_去水印/生物学/人教版', words=['生物学']),
    dict(key='G数学A版', label='数学·人教A版', old='2024/2-数学/人教版',
         new='2026_去水印/数学/人教A版', words=['数学'], old_filter='（A版）'),
    dict(key='H数学B版', label='数学·人教B版', old='2024/2-数学/人教版',
         new='2026_去水印/数学/人教版（B版）（主编：高存明）', words=['数学'],
         old_filter='（B版）'),
    dict(key='I地理人教', label='地理·人教版', old='2024/9-地理/人教版',
         new='2026_去水印/地理/人教版', words=['地理']),
    dict(key='J地理鲁教', label='地理·鲁教版', old='2024/9-地理',
         new='2026_去水印/地理/鲁教版', words=['地理']),
    dict(key='K思想政治', label='思想政治·统编版', old='2024/7-政治',
         new='2026_去水印/思想政治/统编版', words=['思想政治']),
    dict(key='L历史',     label='历史·统编版', old='2024/8-历史',
         new='2026_去水印/历史/统编版', words=['历史']),
]

def task_by_key(k):
    for t in TASKS:
        if t['key'] == k: return t
    return None

def joblog(key, short):
    os.makedirs(JOBS_LOG, exist_ok=True)
    safe = re.sub(r'[\\/:*?"<>|]', '_', '%s__%s' % (key, short))
    return open(os.path.join(JOBS_LOG, safe + '.log'), 'w', encoding='utf-8')

def strip_ctrl(s):
    s = re.sub(r'[\x00-\x1f\x7f\ufffe]', ' ', s)
    s = ''.join(ch if ch.isprintable() or ch >= '\u2500' else ' ' for ch in s)
    return WS.sub(' ', s).strip()

def cut(s, n):
    return s if len(s) <= n else s[:n] + '…'

def merge_ranges(rs):
    rs = sorted(rs); out = []
    for a, b in rs:
        if out and a <= out[-1][1]: out[-1][1] = max(out[-1][1], b)
        else: out.append([a, b])
    return out

def merge_rects(rects, rowtol=4.0, gaptol=7.0):
    if not rects: return []
    rows = {}
    for r in rects:
        rows.setdefault(round(r.y0 / rowtol), []).append(r)
    out = []
    for k in sorted(rows):
        line = sorted(rows[k], key=lambda x: x.x0)
        cur = fitz.Rect(line[0])
        for r in line[1:]:
            if r.x0 - cur.x1 <= gaptol: cur |= r
            else: out.append(cur); cur = fitz.Rect(r)
        out.append(cur)
    return out

# ---------------- 书眉页码：位置重复 + 文字同质 ----------------
def _homogeneous(texts):
    """这一摞行文本像不像"书眉/页码"：完全相同，或去数字后相同，或多为短的含数字串。"""
    from collections import Counter
    m = len(texts)
    if m == 0: return False
    if Counter(texts).most_common(1)[0][1] / m >= 0.6: return True
    if Counter(re.sub(r'\d+', '#', t) for t in texts).most_common(1)[0][1] / m >= 0.6: return True
    return sum(1 for t in texts if len(t) <= 12 and re.search(r'\d', t)) / m >= 0.6


def mask_positions(doc):
    """找出书眉/页码所在的 y 桶。

    ⚠️ 只按「某 y 位置在 ≥35% 的页面都有文字」判定是错的：教材版心固定，
    每页正文的首行、末行 y 本来就恒定，会被整行误当成书眉页脚吞掉。
    （2026-09-26 语文就是这么错的：每页吞掉首行与末行，而两版该行 y 差几 pt
    时会落进不同桶 → 单侧被吞 → 制造成片假差异，表现为"一模一样却标成修改"。）

    改为双重条件：① 该 y 桶在 ≥35% 的页面都有文字；② 桶内文字高度同质。
    """
    n = doc.page_count
    buckets = {}
    for i in range(n):
        pg = doc[i]; h = pg.rect.height
        lines = {}
        for bl in pg.get_text('dict')['blocks']:
            for l in bl.get('lines', []):
                for sp in l['spans']:
                    if not sp['text'].strip(): continue
                    yc = (sp['bbox'][1] + sp['bbox'][3]) / 2
                    if yc < h * 0.14 or yc > h * 0.86:          # 只考察页边条带
                        lines.setdefault(int(yc / 3) * 3, []).append(sp['text'])
        for k, parts in lines.items():
            buckets.setdefault(k, []).append(''.join(parts).strip())
    thr = max(4, n * 0.35)
    return {k for k, txts in buckets.items()
            if len(txts) >= thr and _homogeneous(txts)}

COV_CELL = 4.0
_COV_CACHE = {}

def covered_cells(page):
    """把页面上「图形细节」（小尺寸矢量图元）铺成 4pt 网格，用于判断文字是否压在图上。"""
    key = (page.parent.name, page.number)
    if key in _COV_CACHE: return _COV_CACHE[key]
    R = page.rect; s = set()
    for d in page.get_drawings():
        r = d['rect']
        if r.width > 300 or r.height > 300: continue      # 整页背景/大色块不算
        if r.width * r.height > 5000: continue
        rr = r & R
        if rr.is_empty: continue
        for gx in range(int(rr.x0 / COV_CELL), int(rr.x1 / COV_CELL) + 1):
            for gy in range(int(rr.y0 / COV_CELL), int(rr.y1 / COV_CELL) + 1):
                s.add((gx, gy))
    _COV_CACHE[key] = s
    return s

def cover_frac(bbox, s):
    x0, y0, x1, y1 = bbox
    if x1 <= x0 or y1 <= y0: return 0.0
    tot = hit = 0
    for gx in range(int(x0 / COV_CELL), int(x1 / COV_CELL) + 1):
        for gy in range(int(y0 / COV_CELL), int(y1 / COV_CELL) + 1):
            tot += 1
            if (gx, gy) in s: hit += 1
    return hit / tot if tot else 0.0

def _fig_line(spanlist):
    """图表/表格内的文字常被逐格排版，抽取顺序与阅读顺序不一致（同一行内字符 x 坐标回跳）。
    这类行在两版之间常常整段不同，会造出「正文 ⇄ 表格标签」这种离谱配对，直接丢弃。
    判据收紧为：短行（≤16 字）且出现 **≥2 次回跳，或有 1 次 >3pt 的大回跳**——
    避免误伤数学教材里中英/正斜体混排的正文行（那只会偶尔回跳一点点）。"""
    cs = []
    for s in spanlist:
        for c in s['chars']:
            if c['c'].strip(): cs.append(c)
    if len(cs) < 2 or len(cs) > 16: return False
    xs = [c['bbox'][0] for c in cs]
    jumps = [xs[i - 1] - xs[i] for i in range(1, len(xs)) if xs[i] < xs[i - 1] - 0.6]
    return len(jumps) >= 2 or (jumps and max(jumps) > 3.0)

def page_chars(page, maskys, thr=0.0):
    rd = page.get_text('rawdict'); out = []
    cov = None
    for b in rd['blocks']:
        if b['type'] != 0: continue
        for l in b['lines']:
            if _fig_line(l['spans']): continue
            for s in l['spans']:
                if not s['chars']: continue
                st = ''.join(c['c'] for c in s['chars']).strip()
                if not st: continue
                if s['size'] < thr: continue          # 图/表内小字号矢量文字：不参与比对
                # 短文字直接压在矢量图形上（如重排成矢量的元素周期表标题与标签）
                if len(st) <= 12:
                    if cov is None: cov = covered_cells(page)
                    if cov and cover_frac(s['bbox'], cov) >= 0.85: continue
                yc = (s['bbox'][1] + s['bbox'][3]) / 2
                hit = int(yc / 3) * 3 in maskys
                for c in s['chars']:
                    ch = c['c']
                    if not ch or WS.match(ch): continue
                    if GARBLE.match(ch): continue     # 缺 ToUnicode 表抽出的乱码字符
                    tok = MASK if hit else ch
                    # 连续掩码折叠成一个，避免两侧书眉长度不同造出假差异
                    if tok == MASK and out and out[-1][0] == MASK: continue
                    out.append((tok, fitz.Rect(c['bbox'])))
    return out

_THR_CACHE = {}

def doc_thr(doc):
    """按册自动定「图表小字」阈值：正文体字号 × 0.78，上限 9.6pt。
    教材正文一般 10.5~12pt，图注 10pt；图/表内标签常为 4~9pt。
    这类文字在两版间常被重新排版（位图↔矢量），抽取顺序也不稳，必须排除。"""
    key = (doc.name, doc.page_count)
    if key in _THR_CACHE: return _THR_CACHE[key]
    from collections import Counter
    c = Counter()
    step = max(1, doc.page_count // 80)
    for i in range(0, doc.page_count, step):
        for b in doc[i].get_text('dict')['blocks']:
            if b['type'] != 0: continue
            for l in b.get('lines', []):
                for sp in l['spans']:
                    t = sp['text'].strip()
                    if t: c[round(sp['size'], 1)] += len(t)
    if not c:
        _THR_CACHE[key] = 0.0; return 0.0
    body = max(c.items(), key=lambda x: x[1])[0]
    thr = min(body * 0.78, 9.6)
    _THR_CACHE[key] = thr
    return thr

def build_book(doc, mk=None, thr=None):
    if mk is None: mk = mask_positions(doc)
    if thr is None: thr = doc_thr(doc)
    texts, idxmap = [], []
    for i in range(doc.page_count):
        t = ''.join(c[0] for c in page_chars(doc[i], mk, thr))
        texts.append(t); idxmap.extend((i, k) for k in range(len(t)))
    return ''.join(texts), idxmap, mk

def to_ranges(locs):
    locs = sorted(set(locs)); out = []
    for x in locs:
        if out and out[-1][1] == x: out[-1][1] = x + 1
        else: out.append([x, x + 1])
    return [[a, b] for a, b in out]

def repack(m, s, e, txt):
    if e > s:
        pages = {}
        for pg_i, loc in m[s:e]:
            pages.setdefault(pg_i, []).append(loc)
        return {str(k): to_ranges(v) for k, v in pages.items()}, None, sorted(pages.keys())
    n = len(txt)
    if n == 0 or len(m) == 0: return {}, (0, 0, 1), [0]
    pos, edge = None, 1
    for k in range(min(s, n) - 1, -1, -1):
        if txt[k] != MASK: pos, edge = k, 1; break
    if pos is None:
        for k in range(max(0, s), n):
            if txt[k] != MASK: pos, edge = k, 0; break
    if pos is None: pos, edge = max(0, min(s, n - 1)), 1
    pg_i, loc = m[pos]
    return {}, (pg_i, loc, edge), [pg_i]

# ---------------- 文件配对 ----------------
BRK = re.compile(r'^\[[^\]]+\]\s*')
def norm_name(fn):
    b = os.path.splitext(os.path.basename(fn))[0]
    b = BRK.sub('', b)
    for rep in ('（A版）', '（B版）', '(A版)', '(B版)'):
        b = b.replace(rep, '')
    return WS.sub('', b)

def short_name(fn, words):
    b = os.path.splitext(os.path.basename(fn))[0]
    b = BRK.sub('', b).replace('普通高中教科书·', '')
    for w in words:
        if b.startswith(w): b = b[len(w):]; break
    for rep in ('（A版）', '（B版）', '(A版)', '(B版)'):
        b = b.replace(rep, '')
    return b.strip()

def listpdf(d):
    try: return sorted(f for f in os.listdir(d) if f.lower().endswith('.pdf'))
    except Exception: return []

def task_pairs(tk):
    of = listpdf(tk['old']); nf = listpdf(tk['new'])
    if tk.get('old_filter'):
        of = [f for f in of if re.search(tk['old_filter'], f)]
    if tk.get('new_filter'):
        nf = [f for f in nf if re.search(tk['new_filter'], f)]
    pairs, miss = [], []
    for x in nf:
        k = norm_name(x)
        cand = [y for y in of if norm_name(y) == k]
        if cand: pairs.append((tk['old'] + '/' + cand[0], tk['new'] + '/' + x, short_name(x, tk['words'])))
        else: miss.append(x)
    return pairs, miss

def all_jobs():
    jobs = []
    for tk in TASKS:
        pairs, miss = task_pairs(tk)
        for op, np_, short in pairs:
            jobs.append((tk['key'], short))
    return jobs

# ---------------- 阶段：diff 一册 ----------------
def do_one(key, short):
    tk = task_by_key(key)
    if tk is None: return '!! 未知任务 ' + key
    lf = joblog(key, short)
    def pr(*a):
        print(*a, file=lf); lf.flush()
    pairs, _ = task_pairs(tk)
    hit = [(o, n) for o, n, s in pairs if s == short]
    if not hit: pr('!! 找不到配对', short); return '!! %s %s 无配对' % (key, short)
    op, np_ = hit[0]
    d = os.path.join(ITEMS_DIR, key); os.makedirs(d, exist_ok=True)
    out = os.path.join(d, short + '.json')
    if os.path.exists(out):
        pr('跳过已算'); return '跳过 %s / %s' % (tk['label'], short)
    t0 = time.time()
    try:
        do_ = fitz.open(op); dn_ = fitz.open(np_)
    except Exception as e:
        pr('打不开：%s' % e); return '!! %s / %s 打不开' % (tk['label'], short)
    mkA = mask_positions(do_); mkB = mask_positions(dn_); mk = mkA | mkB
    thrA = doc_thr(do_); thrB = doc_thr(dn_)
    A, mA, _ = build_book(do_, mk, thrA)
    B, mB, _ = build_book(dn_, mk, thrB)
    pr('%s  2024 %d 字 / 2026 %d 字  掩码 y=%s  图表小字阈值 %.1f/%.1f  抽取 %.0fs'
       % (short, len(A), len(B), sorted(mk)[:14], thrA, thrB, time.time() - t0))
    if len(A) < 2000 or len(B) < 2000:
        pr('!! 文字层过少 A=%d B=%d，跳过' % (len(A), len(B)))
        do_.close(); dn_.close(); return '跳过（无文字层）%s / %s' % (tk['label'], short)
    sm = difflib.SequenceMatcher(None, A, B, autojunk=False)
    raw = [[i1, i2, j1, j2] for tag, i1, i2, j1, j2 in sm.get_opcodes() if tag != 'equal']
    merged = []
    for seg in raw:
        if merged and seg[0] - merged[-1][1] < 4:
            pv = merged[-1]; pv[1], pv[3] = seg[1], seg[3]
        else: merged.append(seg)
    items = []
    for i1, i2, j1, j2 in merged:
        old, new = A[i1:i2], B[j1:j2]
        if old == new: continue
        r24, a24, p24 = repack(mA, i1, i2, A)
        r26, a26, p26 = repack(mB, j1, j2, B)
        items.append({
            'id': len(items),
            'type': '修改' if (old and new) else ('删除' if old else '新增'),
            'old': old.replace(MASK, ''), 'new': new.replace(MASK, ''),
            'nm24': old.count(MASK), 'nm26': new.count(MASK),
            'p24': [int(x) + 1 for x in p24], 'p26': [int(x) + 1 for x in p26],
            'r24': r24, 'r26': r26,
            'a24': [a24[0] + 1, a24[1], a24[2]] if a24 else None,
            'a26': [a26[0] + 1, a26[1], a26[2]] if a26 else None,
            'ctx': A[max(0, i1 - 16):i1].replace(MASK, '') + '⟦⟧' + A[i2:i2 + 16].replace(MASK, ''),
        })
    with open(out, 'w', encoding='utf-8') as f:
        json.dump(items, f, ensure_ascii=False)
    pr('opcode %d → 合并 %d → items %d，总用时 %.0fs' % (len(raw), len(merged), len(items), time.time() - t0))
    do_.close(); dn_.close()
    return 'OK   %-16s %-24s items=%-4d %.0fs' % (tk['label'], short, len(items), time.time() - t0)

# ---------------- 伪差异剔除 ----------------
def is_empty_diff(it):
    o = strip_ctrl(it['old']); n = strip_ctrl(it['new'])
    if not o and not n: return True
    om = it.get('nm24', 0) > 0 and not o
    nm = it.get('nm26', 0) > 0 and not n
    def s(x): return len(x) <= 25
    if om and nm: return True
    if om and (not n or s(n)): return True
    if nm and (not o or s(o)): return True
    return False

def drop_moves(items):
    dels, adds = {}, {}
    for it in items:
        if it['type'] == '删除':
            t = strip_ctrl(it['old'])
            if len(t) >= 10: dels.setdefault(t, []).append(it)
        elif it['type'] == '新增':
            t = strip_ctrl(it['new'])
            if len(t) >= 10: adds.setdefault(t, []).append(it)
    drop = set()
    for t, dl in dels.items():
        if t in adds:
            n = min(len(dl), len(adds[t]))
            for i in range(n):
                drop.add(id(dl[i])); drop.add(id(adds[t][i]))
    return [it for it in items if id(it) not in drop]

def is_lastpage_group(g):
    keys = ('2024年7月', '2025年7月', '2026年7月', '2024年12月', '2025年12月')
    return all(it['type'] == '删除' and strip_ctrl(it['old']) in keys for it in g)

def dedupe_group(g):
    out, idx = [], {}
    for it in g:
        sig = (it['type'], it['old'], it['new'])
        if sig in idx:
            m = out[idx[sig]]; m['n'] += 1
            for f in ('r24', 'r26'):
                for k, v in it[f].items(): m[f].setdefault(k, []).extend(v)
        else:
            idx[sig] = len(out); dd = dict(it); dd['n'] = 1; out.append(dd)
    for m in out:
        for f in ('r24', 'r26'):
            m[f] = {k: merge_ranges(v) for k, v in m[f].items()}
    return out

GARBLE = re.compile('[\u0530-\u058f\u0590-\u05ff\u0600-\u06ff\u0700-\u074f'
                    '\u0900-\u0dff\u0e00-\u0eff\u0f00-\u0fff\u1000-\u109f'
                    '\u10a0-\u10ff\u1200-\u137f\u1780-\u17ff\u1a00-\u1aaf'
                    '\u1b00-\u1b7f\ue000-\uf8ff]')

def is_garble(it):
    """部分 PDF 的子集字体缺 ToUnicode 表，抽取出来是印地/阿拉伯等乱码；
    两版乱码不同就会造出假差异 —— 该类条目直接剔除。"""
    t = strip_ctrl(it['old']) + strip_ctrl(it['new'])
    if len(t) < 4: return False
    return len(GARBLE.findall(t)) / len(t) > 0.25

PUNCT_R = re.compile(r'[，。；：、？！“”‘’…—]|(?<!\d)[.,:;?!](?!\d)')
PUNCT_CJK = re.compile(r'[，。；：、？！“”‘’…—]')
CJK_RUN = re.compile(r'[\u4e00-\u9fff]+')
HAS_LETTER = re.compile(r'[A-Za-z\u4e00-\u9fff\u0370-\u03ff\u0400-\u04ff]')
LATIN_WORD = re.compile(r'[A-Za-z]{4,}')

def is_label_soup(s):
    """图/表内部的标签串（元素周期表格子、表格数值、附录数据等）：
    中文几乎都是零散的单字（成不了词），其余全是数字/符号/拉丁字母。"""
    t = strip_ctrl(s)
    if not t: return False
    if not HAS_LETTER.search(t): return True              # 纯数字/符号
    if len(t) < 8: return False
    runs = CJK_RUN.findall(t)
    if not runs:                                          # 全拉丁：含真实单词就保留
        return False if LATIN_WORD.search(t) else True
    cjk = sum(len(r) for r in runs)
    iso = sum(len(r) for r in runs if len(r) < 4)
    return iso / cjk >= 0.5

def _sentence_like(s):
    t = strip_ctrl(s)
    return len(t) >= 15 and bool(PUNCT_R.search(t))

def _fragment(s):
    t = strip_ctrl(s)
    return len(t) <= 10 and not PUNCT_R.search(t)

def _anchor_from_r(r):
    """从标红区间里取一个「位置参考锚点」，供清空该侧文字后仍能画出红色竖线。"""
    best = None
    for k, v in (r or {}).items():
        pno = int(k)
        for s, e in v:
            if best is None or (pno, s) < best: best = (pno, s)
    return [best[0] + 1, best[1], 1] if best else None

def simplify_items(items):
    """把「图表标签」「孤立碎片」从条目里摘掉，避免出现「一整句正文 ⇄ 表格里几个字」的离谱配对。"""
    out = []; n_soup = n_frag = 0
    for it in items:
        it = dict(it)
        so = is_label_soup(it['old']); sn = is_label_soup(it['new'])
        if so or sn:
            n_soup += 1
        elif _sentence_like(it['old']) and _fragment(it['new']):
            sn = True; n_frag += 1
        elif _sentence_like(it['new']) and _fragment(it['old']):
            so = True; n_frag += 1
        if so:                                     # 清掉标签侧，但保留位置锚点
            it['a24'] = it.get('a24') or _anchor_from_r(it.get('r24'))
            it['old'] = ''; it['r24'] = {}
        if sn:
            it['a26'] = it.get('a26') or _anchor_from_r(it.get('r26'))
            it['new'] = ''; it['r26'] = {}
        o = strip_ctrl(it['old']); n = strip_ctrl(it['new'])
        if not o and not n: continue
        it['type'] = '修改' if (o and n) else ('删除' if o else '新增')
        out.append(it)
    return out, n_soup, n_frag

def clean_book(items, label):
    n0 = len(items)
    items = [it for it in items if not is_empty_diff(it)]
    n1 = len(items)
    items = [it for it in items if not is_garble(it)]
    n1b = len(items)
    items, n_soup, n_frag = simplify_items(items)
    n1c = len(items)
    items = drop_moves(items)
    groups, order = {}, []
    for it in items:
        k = (tuple(it['p24']), tuple(it['p26']))
        if k not in groups: groups[k] = []; order.append(k)
        groups[k].append(it)
    keep = []
    for k in order:
        g = groups[k]
        if is_lastpage_group(g): continue
        old = ''.join(x['old'] for x in g); new = ''.join(x['new'] for x in g)
        if sorted(old) == sorted(new): continue
        keep.append((k, dedupe_group(g)))
    stat = dict(raw=n0, after_mask=n1, after_garble=n1b, after_soup=n1c,
                soup=n_soup, frag=n_frag, after_move=len(items),
                groups=len(keep), kept=sum(len(g) for _, g in keep))
    return keep, stat

def whole_item(grp):
    for it in grp:
        if it['type'] == '删除' and len(strip_ctrl(it['old'])) >= 800 and len(it['p24']) >= 3: return it
        if it['type'] == '新增' and len(strip_ctrl(it['new'])) >= 800 and len(it['p26']) >= 3: return it
    return None

def find_title(doc, pages):
    best = (0.0, '', pages[0] if pages else 0)
    for pno in pages:
        if not (0 <= pno < doc.page_count): continue
        pg = doc[pno]; h = pg.rect.height
        for b in pg.get_text('dict')['blocks']:
            for l in b.get('lines', []):
                for sp in l['spans']:
                    t = sp['text'].strip()
                    if len(t) < 3 or sp['size'] < 18: continue
                    if sp['bbox'][1] < h * 0.05 or sp['bbox'][1] > h * 0.95: continue
                    if sp['size'] > best[0]: best = (sp['size'], t, pno)
    return best[1], best[2]

def head_band(pg, left, right):
    pg.draw_rect(fitz.Rect(0, 0, PW, BAND), color=BANDC, fill=BANDC, width=0)
    pg.insert_text((MARGIN, 30), strip_ctrl(left), fontname=CN, fontsize=14, color=(1, 1, 1))
    if right:
        r = strip_ctrl(right)
        pg.insert_text((PW - MARGIN - fitz.get_text_length(r, fontname=CN, fontsize=11), 30),
                       r, fontname=CN, fontsize=11, color=(0.86, 0.89, 1.0))

def centre_on(pg, text, y, fs, col):
    t = strip_ctrl(text)
    pg.insert_text(((PW - fitz.get_text_length(t, fontname=CN, fontsize=fs)) / 2, y),
                   t, fontname=CN, fontsize=fs, color=col)

def page_del_note(out, label, gi, total, it, dold):
    pg = out.new_page(width=PW, height=PH)
    head_band(pg, f'{label}　改动组 {gi} / {total}', '整篇删除')
    pgs = sorted({int(k) + 1 for k in it['r24'].keys()})
    a, b = (pgs[0], pgs[-1]) if pgs else (0, 0)
    title, _ = find_title(dold, [p - 1 for p in pgs])
    centre_on(pg, '整篇删除', 296, 30, RED)
    pg.draw_line(fitz.Point(PW / 2 - 150, 320), fitz.Point(PW / 2 + 150, 320), color=LINE, width=1)
    if title: centre_on(pg, f'《{title}》', 378, 23, BANDC)
    centre_on(pg, f'2024 版　第 {a}–{b} 页（共 {len(pgs)} 页）　约 {len(strip_ctrl(it["old"]))} 字',
              412, 12, GRAY)
    bx = fitz.Rect(PW / 2 - 340, 456, PW / 2 + 340, 574)
    pg.draw_rect(bx, color=(0.80, 0.82, 0.86), fill=(0.965, 0.972, 0.984), width=0.8)
    centre_on(pg, '2026 版已整体删除该课文，本对照册不再附原文。', 490, 12, (0.22, 0.24, 0.30))
    centre_on(pg, f'如需查核，请直接翻阅 2024 版第 {a}–{b} 页。', 518, 12, (0.22, 0.24, 0.30))
    centre_on(pg, '删改前后的全部文字差异，见逐字对比报告。', 550, 10, (0.50, 0.52, 0.56))
    return 1

def page_add_texts(out, label, gi, total, it, dnew):
    pgs = sorted({int(k) + 1 for k in it['r26'].keys()})
    title, tpage = find_title(dnew, [p - 1 for p in pgs])
    if title: pgs = [p for p in pgs if p >= tpage + 1] or pgs
    made = 0
    for k, pno in enumerate(pgs, 1):
        pg = out.new_page(width=PW, height=PH)
        head_band(pg, f'{label}　改动组 {gi} / {total}', f'整篇新增·原文　{k} / {len(pgs)} 页')
        t = f'《{title}》　2026 版 原书第 {pno} 页' if title else f'2026 版 原书第 {pno} 页'
        pg.insert_text((MARGIN, HEAD - 15), strip_ctrl(t), fontname=CN, fontsize=12,
                       color=(0.24, 0.24, 0.28))
        x = (PW - DISP_W) / 2
        rect = fitz.Rect(x, Y0, x + DISP_W, Y0 + DISP_H)
        pg.show_pdf_page(rect, dnew, pno - 1)
        pg.draw_rect(rect, color=LINE, width=0.7)
        made += 1
    return made

def make_cover(out, label, short, ngroups, nitems):
    cp = out.new_page(width=PW, height=PH)
    cp.draw_rect(fitz.Rect(0, 0, PW, BAND), color=BANDC, fill=BANDC, width=0)
    cp.insert_text((MARGIN, 30), f'{label}　{short}　改动页对照', fontname=CN, fontsize=18, color=(1, 1, 1))
    centre_on(cp, short, 196, 34, BANDC)
    cp.draw_line(fitz.Point(PW / 2 - 130, 220), fitz.Point(PW / 2 + 130, 220), color=LINE, width=1)
    centre_on(cp, f'{label}　2024 版　⇄　2026 版　改动页面对照', 258, 16, (0.2, 0.2, 0.24))
    centre_on(cp, f'本册共 {ngroups} 组对照页 · {nitems} 处改动', 292, 12, GRAY)
    if nitems == 0:
        centre_on(cp, '本册两版逐字比对未发现差异', 320, 14, RED)
        return cp
    lg = fitz.Rect(PW / 2 - 168, 322, PW / 2 + 168, 348)
    cp.draw_rect(lg, color=RED, fill=FILLC, fill_opacity=FILL_OP, width=1)
    centre_on(cp, '浅红色框 ＝ 该处文字在两版之间存在差异', 339, 11, (0.35, 0.08, 0.12))
    centre_on(cp, '左栏：2024 版原页　　右栏：2026 版原页　（矢量嵌入，可缩放与选中复制）', 390, 10, (0.46, 0.46, 0.5))
    centre_on(cp, '纯新增或纯删除处，另一侧显示「位置参考页」，以红色竖线标出插入点', 412, 10, (0.46, 0.46, 0.5))
    centre_on(cp, '整篇删除的课文只作说明、不附原文；整篇新增的课文逐页附上 2026 版原文', 434, 10, (0.46, 0.46, 0.5))
    centre_on(cp, '红色编号固定排在各自那一页的右侧页边', 456, 10, (0.46, 0.46, 0.5))
    return cp

def render_book(tk, of, nf, short, items, tmpdir):
    keep, stat = clean_book(items, short)
    dold = fitz.open(of); dnew = fitz.open(nf)
    out = fitz.open()
    ntotal = sum(it.get('n', 1) for _, g in keep for it in g)
    make_cover(out, tk['label'], short, len(keep), ntotal)
    cache = {'A': {}, 'B': {}}
    thrA = doc_thr(dold); thrB = doc_thr(dnew)
    # ⚠️ 必须与 diff 阶段用同一个掩码集合：掩码会把连续占位符折叠成一个字符，
    # 渲染时若传空集合，字符表长度就与 items 里的索引不同 → 红框整体错位（"标注歪了"）。
    mkr = mask_positions(dold) | mask_positions(dnew)
    self_check = []; nchk = [0]
    def get_chars(doc, key, pno):
        if pno not in cache[key]:
            cache[key][pno] = page_chars(doc[pno], mkr, thrA if key == 'A' else thrB)
        return cache[key][pno]
    for gi, (key, grp) in enumerate(keep, 1):
        wi = whole_item(grp)
        if wi is not None:
            if wi['type'] == '删除': page_del_note(out, tk['label'], gi, len(keep), wi, dold)
            else: page_add_texts(out, tk['label'], gi, len(keep), wi, dnew)
            continue
        p24 = key[0][0] - 1 if key[0] else 0
        p26 = key[1][0] - 1 if key[1] else 0
        pg = out.new_page(width=PW, height=PH)
        head_band(pg, f'{tk["label"]}　{short}　改动组 {gi} / {len(keep)}',
                  f'本组 {sum(it.get("n",1) for it in grp)} 处改动')
        ty = 70.0; maxl = 6
        for i, it in enumerate(grp[:maxl]):
            o = cut(strip_ctrl(it['old']), 20); n = cut(strip_ctrl(it['new']), 20)
            if it['type'] == '修改': line = f'[{i+1}] “{o}” → “{n}”'
            elif it['type'] == '删除': line = f'[{i+1}] 删除：“{o}”'
            else: line = f'[{i+1}] 新增：“{n}”'
            if it.get('n', 1) > 1: line += f'　×{it["n"]}'
            if len(grp) > maxl and i == maxl - 1: line += f'　…另 {len(grp)-maxl} 处'
            pg.insert_text((MARGIN, ty), line, fontname=CN, fontsize=9, color=(0.58, 0.10, 0.15))
            ty += 12.5
        def label(x, txt, extra):
            pg.insert_text((x, HEAD - 15), txt, fontname=CN, fontsize=10.5, color=(0.24, 0.24, 0.28))
            if extra:
                pg.insert_text((x + fitz.get_text_length(txt, fontname=CN, fontsize=10.5) + 10,
                                HEAD - 15), extra, fontname=CN, fontsize=8.5, color=(0.62, 0.62, 0.66))
        more24 = f'（另含第 {", ".join(str(p) for p in key[0][1:])} 页）' if len(key[0]) > 1 else ''
        more26 = f'（另含第 {", ".join(str(p) for p in key[1][1:])} 页）' if len(key[1]) > 1 else ''
        label(X_L, f'2024 版　第 {p24+1} 页', more24)
        label(X_R, f'2026 版　第 {p26+1} 页', more26)
        placed = []
        BADGE = 13.5
        CHK = []          # 框内文字自校验结果
        def put_badge(x, anch_y):
            bx = x + DISP_W - 16.5
            base = min(max(anch_y - BADGE / 2, Y0 + 0.5), Y0 + DISP_H - BADGE - 0.5)
            cand = [0.0]
            for k in range(1, 40):
                cand.append(14.5 * k); cand.append(-14.5 * k)
            by = base
            for d in cand:
                yy = base + d
                if yy < Y0 + 0.5 or yy > Y0 + DISP_H - BADGE - 0.5: continue
                r = fitz.Rect(bx, yy, bx + BADGE, yy + BADGE)
                if not any(r.intersects(q) for q in placed): by = yy; break
            bd = fitz.Rect(bx, by, bx + BADGE, by + BADGE)
            placed.append(bd)
            pg.draw_rect(bd, color=RED, fill=RED, width=0)
            if abs(by + BADGE / 2 - anch_y) > 3.5:
                pg.draw_line(fitz.Point(bx - 0.5, by + BADGE / 2),
                             fitz.Point(bx - 9.0, anch_y), color=RED, width=0.5)
            return bd
        def draw_side(x, doc, ckey, pno, field_r, field_a):
            if not (0 <= pno < doc.page_count): return 0
            rect = fitz.Rect(x, Y0, x + DISP_W, Y0 + DISP_H)
            pg.show_pdf_page(rect, doc, pno)
            chars = get_chars(doc, ckey, pno)
            sr = doc[pno].rect
            sx = DISP_W / sr.width if sr.width else 1.0
            sy = DISP_H / sr.height if sr.height else 1.0
            drawn = 0
            for idx, it in enumerate(grp):
                rr = it.get(field_r, {}).get(str(pno))
                cand = []; want = []
                if rr:
                    seen = set()
                    for s, e in rr:
                        for k in range(s, min(e, len(chars))):
                            if chars[k][0] == MASK: continue   # 书眉页脚占位符不画框
                            if k in seen: continue             # 区间可能重叠，去重
                            seen.add(k)
                            cand.append(chars[k][1]); want.append(chars[k][0])
                # 自校验：本侧框内文字应等于该条目这一侧的差异文字
                # （区间重叠时可能取到重复片段，故用互相包含判定）
                if rr:
                    got = strip_ctrl(''.join(want))
                    exp = strip_ctrl(it['old'] if field_r == 'r24' else it['new'])
                    if not (got == exp or (exp and exp in got) or (got and got in exp)):
                        CHK.append('页%s 组%d[%d] %s 期望 %r 实际 %r'
                                   % (pno + 1, gi, idx + 1, field_r, exp[:60], got[:60]))
                rects = merge_rects(cand) if cand else []
                if rects:
                    boxes = []
                    for rc in rects:
                        box = fitz.Rect(x + (rc.x0 - 1) * sx, Y0 + (rc.y0 - 1.5) * sy,
                                        x + (rc.x1 + 1) * sx, Y0 + (rc.y1 + 1.5) * sy) & rect
                        if box.is_empty: continue
                        pg.draw_rect(box, color=RED, fill=FILLC, fill_opacity=FILL_OP, width=1.0)
                        boxes.append(box); drawn += 1
                    if boxes:
                        f = min(boxes, key=lambda b: (round(b.y0 / 6), b.x0))
                        bd = put_badge(x, (f.y0 + f.y1) / 2)
                        pg.insert_text((bd.x0 + 3.0, bd.y0 + 10.6), str(idx + 1),
                                       fontname=CN, fontsize=9, color=(1, 1, 1))
                elif it.get(field_a) and it[field_a][0] - 1 == pno:
                    k = it[field_a][1]; _a = it[field_a]
                    _edge = _a[2] if len(_a) > 2 else 1
                    # 锚点若落在书眉页脚占位符上，就近找一个真实字符，避免竖线画到页边
                    if 0 <= k < len(chars) and chars[k][0] == MASK:
                        for k2 in list(range(k, min(k + 40, len(chars)))) + \
                                  list(range(k - 1, max(-1, k - 40), -1)):
                            if chars[k2][0] != MASK:
                                k = k2; break
                    if 0 <= k < len(chars):
                        cb = chars[k][1]
                        px = min(max(x + (cb.x1 if _edge else cb.x0) * sx, x + 2.0), x + DISP_W - 25.0)
                        ty0 = min(max(Y0 + cb.y0 * sy, Y0 + 18.0), Y0 + DISP_H - 2.0)
                        ty1 = min(Y0 + cb.y1 * sy, Y0 + DISP_H - 0.5)
                        pg.draw_rect(fitz.Rect(px - 1.3, ty0, px + 1.3, ty1), color=RED, fill=RED, width=0)
                        bd = put_badge(x, (ty0 + ty1) / 2)
                        pg.insert_text((bd.x0 + 3.0, bd.y0 + 10.6), str(idx + 1),
                                       fontname=CN, fontsize=9, color=(1, 1, 1))
                        drawn += 1
            return drawn
        n24 = draw_side(X_L, dold, 'A', p24, 'r24', 'a24')
        n26 = draw_side(X_R, dnew, 'B', p26, 'r26', 'a26')
        pg.draw_rect(fitz.Rect(X_L, Y0, X_L + DISP_W, Y0 + DISP_H), color=LINE, width=0.7)
        pg.draw_rect(fitz.Rect(X_R, Y0, X_R + DISP_W, Y0 + DISP_H), color=LINE, width=0.7)
        fy = PH - 14
        leg = fitz.Rect(MARGIN, fy - 9, MARGIN + 17, fy + 3)
        pg.draw_rect(leg, color=RED, fill=FILLC, fill_opacity=FILL_OP, width=0.8)
        pg.insert_text((MARGIN + 24, fy), '浅红色框 ＝ 该处文字存在差异',
                       fontname=CN, fontsize=9, color=(0.5, 0.5, 0.54))
        ft = f'2024 版 第 {p24+1} 页　｜　2026 版 第 {p26+1} 页'
        pg.insert_text((PW - MARGIN - fitz.get_text_length(ft, fontname=CN, fontsize=9.5), fy),
                       ft, fontname=CN, fontsize=9.5, color=(0.38, 0.38, 0.42))
        for m in CHK[:3]:
            self_check.append(m)
        nchk[0] += len(CHK)
    stat['chk_bad'] = nchk[0]
    stat['chk_samples'] = self_check[:10]
    os.makedirs(tmpdir, exist_ok=True)
    tp = os.path.join(tmpdir, short + '.pdf')
    out.save(tp, garbage=4, deflate=True)
    npages = out.page_count
    out.close(); dold.close(); dnew.close()
    return tp, npages, stat, ntotal

def do_buildone(key, short):
    tk = task_by_key(key)
    if tk is None: return '!! 未知任务 ' + key
    lf = joblog(key, short)
    def pr(*a):
        print(*a, file=lf); lf.flush()
    pairs, _ = task_pairs(tk)
    hit = [(o, n) for o, n, s in pairs if s == short]
    if not hit: return '!! %s %s 无配对' % (key, short)
    op, np_ = hit[0]
    ip = os.path.join(ITEMS_DIR, key, short + '.json')
    if not os.path.exists(ip):
        pr('无 items，跳过'); return '跳过（无 items）%s / %s' % (tk['label'], short)
    t0 = time.time()
    items = json.load(open(ip, encoding='utf-8'))
    tmpdir = os.path.join('_tmp_pipe', key)
    tp, npages, stat, ntotal = render_book(tk, op, np_, short, items, tmpdir)
    pr('原始 %d → 掩码后 %d → 去乱码 %d → 去标签 %d（标签%d/碎片%d）→ 搬家后 %d → 保留 %d 组 / %d 处；输出 %d 页；%.0fs'
       % (stat['raw'], stat['after_mask'], stat['after_garble'], stat.get('after_soup', stat['after_garble']),
          stat.get('soup', 0), stat.get('frag', 0), stat['after_move'],
          stat['groups'], ntotal, npages, time.time() - t0))
    if stat.get('chk_bad'):
        pr('   ⚠️ 框内文字自校验：%d 处不符' % stat['chk_bad'])
        for m in stat.get('chk_samples', []): pr('      !! %s' % m)
    else:
        pr('   ✅ 框内文字自校验通过：每一处红框/竖线下的文字都等于该处差异文字')
    return 'OK   %-16s %-24s 组=%-4d 处=%-4d 页=%-4d %.0fs' % (
        tk['label'], short, stat['groups'], ntotal, npages, time.time() - t0)

def do_merge(key):
    tk = task_by_key(key)
    if tk is None: return '!! 未知任务 ' + key
    pairs, _ = task_pairs(tk)
    tmpdir = os.path.join('_tmp_pipe', key)
    final = fitz.open(); toc = []; pos = 0
    used = 0
    for op, np_, short in pairs:
        tp = os.path.join(tmpdir, short + '.pdf')
        if not os.path.exists(tp): continue
        src = fitz.open(tp); cnt = src.page_count
        final.insert_pdf(src)
        toc.append([1, short, pos + 1])
        for i in range(1, cnt): toc.append([2, '改动组 %d' % i, pos + 1 + i])
        pos += cnt; used += 1; src.close()
    if not toc:
        final.close(); return '!! %s 没有任何册可合并' % tk['label']
    final.set_toc(toc)
    try:
        final.subset_fonts()          # 子集化 CJK 字体，可省约 30% 体积
    except Exception:
        pass
    od = os.path.join(OUT_ROOT, tk['label']); os.makedirs(od, exist_ok=True)
    fp = os.path.join(od, f'修改页对照_{tk["label"]}.pdf')
    tp2 = os.path.join(tmpdir, '合并.pdf')
    final.save(tp2, garbage=4, deflate=True)
    n = final.page_count; final.close()
    ok = False
    for _ in range(8):
        try:
            os.replace(tp2, fp); ok = True; break
        except PermissionError: time.sleep(2)
    if not ok:
        fp = os.path.join(od, f'修改页对照_{tk["label"]}_更新.pdf')
        try: os.remove(fp)
        except Exception: pass
        os.replace(tp2, fp)
    return 'DONE %-16s %2d 册 %3d 页 %5.1f MB  %s' % (tk['label'], used, n,
                                                     os.path.getsize(fp) / 1e6, fp)

def main():
    if len(sys.argv) < 2: print('usage: pipe2.py one|buildone|merge|list [...]'); return
    mode = sys.argv[1]
    if mode == 'list':
        for tk in TASKS:
            pairs, miss = task_pairs(tk)
            print('%s\t%s\t配对 %d\t缺 %d' % (tk['key'], tk['label'], len(pairs), len(miss)))
        return
    if mode == 'one':
        print(do_one(sys.argv[2], sys.argv[3]))
    elif mode == 'buildone':
        print(do_buildone(sys.argv[2], sys.argv[3]))
    elif mode == 'merge':
        print(do_merge(sys.argv[2]))
    else:
        print('未知模式', mode)

if __name__ == '__main__':
    try:
        main()
    except Exception:
        print('!! 异常\n' + traceback.format_exc())
