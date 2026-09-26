# -*- coding: utf-8 -*-
"""生成《2024 版与 2026 版教材改动清单》自然语言版 TXT（带「所在句」）。

句式：
    课文《哦，香雪》中，将“A”修改成了“B”。
    　　（所在句：……前文【A→B】后文……）

短改动（任一侧 ≤ CTX_MAX 字）额外给出改动所在的整句，并把改动点标成
【旧→新】/【删：…】/【增：…】，解决「只看『把 A 改成 B』不知道出处」的问题。

    py gen_txt3.py part <学科序号>   # 只处理一个学科，写 _preview/txtparts/<i>.txt
    py gen_txt3.py join              # 拼头部 + 各学科 + 尾部 → 对比结果/…txt
    py gen_txt3.py                   # 单进程全量（备用）
"""
import os, re, sys, json, io
sys.stdout.reconfigure(encoding='utf-8')
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..'))
sys.path.insert(0, HERE)
import fitz, pipe2, titlemap

OUT = os.environ.get('TXT_OUT', os.path.join(ROOT, '对比结果/2024版与2026版教材改动清单.txt'))
PARTS = os.path.join(HERE, 'txtparts')
JROOT = os.path.join(ROOT, 'gh-upload/json')
CUT = 300                       # 长引文截断
INLINE = 40                     # 两侧都不超过这个长度 → 写成一句话
CTX_MAX = INLINE                # 只要是写成单行的改动（任一侧 ≤ 此长度）都给出「所在句」，
                                # 不留"裸句"；>INLINE 的整段改写本身已给改动前/改动后
CTX_PAD = 56                    # 所在句向两侧最多各取这么多字
WRAP = 42                       # 折行宽度（中文双宽，42 字约 84 列）
BRK1 = '。！？；：'
BRK2 = '，、）】”'
SENT_END = '。！？；…?!'
SENT_TAIL = '”’）】》'
CN_NUM = '零一二三四五六七八九十'
LATIN = re.compile(r'[A-Za-z]')
CJK = re.compile(r'[\u4e00-\u9fff]')
BAD_TITLE = re.compile(
    r'^(第\s*[一二三四五六七八九十百\d]+\s*[章节课单元篇]$|附录|活动课|目录|前言|导言|后记|'
    r'Text notes|Grammar notes|Wordlist|Notes|Contents)')
NO_TITLE = ('数学', '英语')


# ---------------- 小工具 ----------------
def cn(i):
    if i < 10: return CN_NUM[i]
    if i == 10: return '十'
    if i < 20: return '十' + CN_NUM[i - 10]
    if i < 100:
        s = CN_NUM[i // 10] + '十'
        return s if i % 10 == 0 else s + CN_NUM[i % 10]
    return str(i)


def q(t):
    t = pipe2.strip_ctrl(t)
    return t[:CUT] + '……' if len(t) > CUT else t


def pages_txt(ps):
    ps = sorted(ps)
    if not ps: return ''
    segs, s0, prev = [], ps[0], ps[0]
    for p in ps[1:]:
        if p == prev + 1: prev = p; continue
        segs.append((s0, prev)); s0 = prev = p
    segs.append((s0, prev))
    return '、'.join('第 %d 页' % a if a == b else '第 %d–%d 页' % (a, b) for a, b in segs)


def wrap(s, first, cont):
    if len(s) <= WRAP + 6: return [first + s]
    out, pos = [], 0
    while pos < len(s):
        if len(s) - pos <= WRAP + 6:
            out.append((first if not out else cont) + s[pos:]); break
        win = s[pos:pos + WRAP]; cut = -1
        for i in range(len(win) - 1, max(0, len(win) - 20), -1):
            if win[i] in BRK1: cut = i + 1; break
        if cut < 0:
            for i in range(len(win) - 1, max(0, len(win) - 20), -1):
                if win[i] in BRK2: cut = i + 1; break
        if cut < 0: cut = WRAP
        out.append((first if not out else cont) + s[pos:pos + cut]); pos += cut
    return out


# ---------------- 课文 / 章节名 ----------------
TM = titlemap.load_all()


def good_title(t):
    t = (t or '').strip().replace('　', '')
    if not (3 <= len(t) <= 20): return ''
    if BAD_TITLE.match(t): return ''
    if LATIN.search(t):
        if t[0].isupper() and len(re.findall(r"[A-Za-z][A-Za-z'’\-]*", t)) >= 2:
            return t
        return ''
    return t if len(CJK.findall(t)) >= 3 else ''


def title_of(book, c, kw=''):
    if kw == 'off': return ''
    if c['type'] == '新增' or not c.get('old_pages'):
        path, pages = book.get('new_pdf'), c.get('new_pages') or []
    else:
        path, pages = book.get('old_pdf'), c.get('old_pages') or []
    if not path or not pages: return ''
    m = TM.get(os.path.abspath(path))
    if not m: return ''
    return good_title(m.get(int(pages[0]), ''))


def where(book, c, kw='', cx=None):
    """句子的定位半句。用「所在页开头」的栏目名校正课文名 —— 单元研习任务、学习提示
    这类栏目页不属于任何一篇课文，按上一课继承标题会张冠李戴。"""
    if cx is not None:
        try:
            if c['type'] == '新增' or not c.get('old_ranges'):
                rr, side = c.get('new_ranges') or {}, 'B'
            else:
                rr, side = c.get('old_ranges') or {}, 'A'
            if rr:
                k = sorted(rr, key=lambda x: int(x))[0]
                head = cx.text(side, int(k) - 1)[:90]
                for wd in ('单元研习任务', '单元学习任务', '学习提示', '单元学习'):
                    if wd in head:
                        return wd + '中'
        except Exception:
            pass
    t = title_of(book, c, kw)
    if t:
        return ('课文《%s》中' % t) if kw == '课文' else ('《%s》一节中' % t)
    pages = c.get('old_pages') or c.get('new_pages') or []
    return ('%s处' % pages_txt(pages)) if pages else '某处'


# ---------------- 「所在句」提取 ----------------
class Ctx:
    """按册缓存；字符表必须和比对阶段用同一个掩码集合，否则下标会对不上。"""

    def __init__(self, old_pdf, new_pdf):
        self.dA = fitz.open(old_pdf)
        self.dB = fitz.open(new_pdf)
        self.mk = pipe2.mask_positions(self.dA) | pipe2.mask_positions(self.dB)
        self.tA = pipe2.doc_thr(self.dA)
        self.tB = pipe2.doc_thr(self.dB)
        self.cache = {}

    def text(self, side, pno):
        key = (side, pno)
        if key not in self.cache:
            d = self.dA if side == 'A' else self.dB
            t = self.tA if side == 'A' else self.tB
            if 0 <= pno < d.page_count:
                self.cache[key] = ''.join(c[0] for c in pipe2.page_chars(d[pno], self.mk, t))
            else:
                self.cache[key] = ''
        return self.cache[key]

    def close(self):
        try: self.dA.close(); self.dB.close()
        except Exception: pass


def sentence_marked(txt, s, e, mark):
    """把 txt[s:e] 换成 mark，并向两侧扩到句读边界，返回带上下文的句子。"""
    if not txt: return ''
    n = len(txt)
    s = max(0, min(s, n)); e = max(s, min(e, n))
    a = s
    while a > 0 and txt[a - 1] not in SENT_END and s - a < CTX_PAD:
        a -= 1
    b = e
    while b < n and b - e < CTX_PAD:
        if txt[b] in SENT_END:
            b += 1
            while b < n and txt[b] in SENT_TAIL: b += 1
            break
        if txt[b] in SENT_TAIL and b > e: b += 1; continue
        b += 1
    head = '……' if a > 0 else ''
    tail = '……' if b < n else ''
    body = txt[a:s] + mark + txt[e:b]
    body = body.replace(pipe2.MASK, '')
    return head + body + tail


def ctx_line(book, c, cx):
    """返回「所在句」的完整文字（含标记），取不到返回空串。"""
    if cx is None: return ''
    ty = c['type']
    try:
        if ty == '新增':
            rr = c.get('new_ranges') or {}
            key = sorted(rr, key=lambda x: int(x))[:1]
            if not key: return ''
            pno = int(key[0]) - 1; s, e = rr[key[0]][0]
            return sentence_marked(cx.text('B', pno), s, e, '【增：%s】' % c['new'])
        rr = c.get('old_ranges') or {}
        key = sorted(rr, key=lambda x: int(x))[:1]
        if not key: return ''
        pno = int(key[0]) - 1; s, e = rr[key[0]][0]
        if ty == '删除':
            return sentence_marked(cx.text('A', pno), s, e, '【删：%s】' % c['old'])
        return sentence_marked(cx.text('A', pno), s, e, '【%s→%s】' % (c['old'], c['new']))
    except Exception:
        return ''


# ---------------- 组织输出 ----------------
def whole_title(book, g):
    key = 'new' if g['whole'] == '新增' else 'old'
    pages = g['new_pages'] if g['whole'] == '新增' else g['old_pages']
    path = book.get('new_pdf' if key == 'new' else 'old_pdf')
    try:
        d = fitz.open(path)
        title, _ = pipe2.find_title(d, [p - 1 for p in pages]); d.close()
        return title
    except Exception:
        return ''


def one_change(L, book, c, cx, ind='　　', kw=''):
    o, n = q(c['old']), q(c['new'])
    cnt = c.get('count', 1)
    tail = '（同一页上共有 %d 处一模一样的改动）' % cnt if cnt > 1 else ''
    wh = where(book, c, kw, cx)
    ty = c['type']
    if max(len(o), len(n)) <= INLINE:
        if ty == '修改':
            L.append('%s%s，将“%s”修改成了“%s”。%s' % (ind, wh, o, n, tail))
        elif ty == '删除':
            L.append('%s%s，删去了“%s”。%s' % (ind, wh, o, tail))
        else:
            L.append('%s%s，增加了“%s”。%s' % (ind, wh, n, tail))
        if max(len(o), len(n)) <= CTX_MAX:
            sent = ctx_line(book, c, cx)
            if sent:
                for x in wrap('（所在句：%s）' % sent, ind + '　　', ind + '　　　　　'):
                    L.append(x)
        return
    if ty == '修改': L.append('%s%s，有一处文字被改写。%s' % (ind, wh, tail))
    elif ty == '删除': L.append('%s%s，删去了一段文字。%s' % (ind, wh, tail))
    else: L.append('%s%s，增加了一段文字。%s' % (ind, wh, tail))
    p2 = ind + '　　'
    if ty in ('修改', '删除'):
        for x in wrap(o + '”', p2 + '改动前：“', p2 + '　　'): L.append(x)
    if ty in ('修改', '新增'):
        for x in wrap(n + '”', p2 + '改动后：“', p2 + '　　'): L.append(x)


def book_pdf(book):
    return book.get('old_pdf'), book.get('new_pdf')


def build_subject(nsub, entry):
    with io.open(os.path.join(JROOT, entry['file']), encoding='utf-8') as f:
        d = json.load(f)
    t = d['totals']
    L = []
    L.append('')
    L.append('')
    L.append('%s、%s' % (cn(nsub), d['subject']))
    L.append('＝' * 40)
    L.append('　　%d 册 · %d 个改动组 · %d 处改动' % (t['books'], t['groups'], t['changes']))
    kw = '课文' if '语文' in d['subject'] else ''
    if any(x in d['subject'] for x in NO_TITLE): kw = 'off'
    for book in d['books']:
        L.append('')
        L.append('【%s】' % book['name'])
        L.append('－' * 34)
        if book.get('note'):
            L.append('　　%s。' % book['note']); continue
        if book['groups'] == 0:
            L.append('　　两版逐字比对未发现差异。'); continue
        L.append('　　全书 %d 个改动组、%d 处改动。' % (book['groups'], book['changes']))
        cx = None
        op, np_ = book_pdf(book)
        need = any(not g.get('whole') and any(max(len(c['old']), len(c['new'])) <= CTX_MAX
                                              for c in g['changes'])
                   for g in book['items'])
        if need and op and np_ and os.path.exists(op) and os.path.exists(np_):
            try: cx = Ctx(op, np_)
            except Exception: cx = None
        try:
            for g in book['items']:
                L.append('')
                if g.get('whole'):
                    title = whole_title(book, g)
                    nm = '《%s》' % title if title else '一篇课文'
                    if g['whole'] == '删除':
                        L.append('　　◆ 整篇删除（对应改动组 %d）' % g['group'])
                        L.append('　　2026 版整篇删去了课文%s，原文在 2024 版%s，约 %d 字。'
                                 % (nm, pages_txt(g['old_pages']), g.get('whole_chars', 0)))
                    else:
                        L.append('　　◆ 整篇新增（对应改动组 %d）' % g['group'])
                        L.append('　　2026 版整篇增加了课文%s，在 2026 版%s，约 %d 字。'
                                 % (nm, pages_txt(g['new_pages']), g.get('whole_chars', 0)))
                    continue
                L.append('　　◆ 改动组 %d（2024 版%s ⇄ 2026 版%s）'
                         % (g['group'], pages_txt(g['old_pages']), pages_txt(g['new_pages'])))
                for c in g['changes']:
                    one_change(L, book, c, cx, kw=kw)
        finally:
            if cx: cx.close()
    return L


def header():
    with io.open(os.path.join(JROOT, 'index.json'), encoding='utf-8') as f:
        index = json.load(f)
    TOT = index['totals']
    L = []
    L.append('2024 版 ⇄ 2026 版　高中教材改动清单')
    L.append('（自然语言版，句子可直接摘抄）')
    L.append('')
    L.append('　　共 %d 套教材 · %d 册 · %d 个改动组 · %d 处改动'
             % (TOT['subjects'], TOT['books'], TOT['groups'], TOT['changes']))
    L.append('　　生成日期：2026-09-26')
    L.append('')
    L.append('阅读说明')
    L.append('－' * 34)
    L.append('1. 每条都是一句完整的话：“课文《…》中，将“A”修改成了“B”。”')
    L.append('   也可以直接摘成“……中将“A”修改成了“B””。')
    L.append('2. 书名号里是该册的课文名（非语文学科为章节名）；数学、英语两门课本章节版式')
    L.append('   不便识别，直接写成“第 N 页处”。')
    L.append('3. 每条改动下面再给一行“（所在句：……【A→B】……）”——就是这处改动所在的那一整句，')
    L.append('   方括号里是改动点：【A→B】表示这里由 A 改成了 B，')
    L.append('   【删：A】表示这里删掉了 A，【增：A】表示这里新增了 A，')
    L.append('   句首句尾的“……”表示这句太长、两头做了截断。')
    L.append('4. 较长或整段改写的分行写成“改动前／改动后”，按标点折行（这类本身已是段落级语境）；')
    L.append('   超过 %d 字的在 %d 字处截断，用“……”表示，全文见同一目录的 PDF 或仓库 json 目录。' % (CUT, CUT))
    L.append('5. “×N”表示同一页上有若干处一模一样的改动。')
    L.append('6. “◆ 改动组 N”是《修改页对照》PDF 里的编号，便于回查。')
    return L, index


def footer(index):
    T = index['totals']
    return ['', '',
            '＝' * 40,
            '（全文完）共 %d 套教材、%d 册、%d 个改动组、%d 处改动。'
            % (T['subjects'], T['books'], T['groups'], T['changes']),
            '＝' * 40]


def write(path, lines):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    txt = '\n'.join(lines) + '\n'
    with io.open(path, 'w', encoding='utf-8-sig', newline='\r\n') as f:
        f.write(txt)
    return len(lines), len(txt)


def do_part(i):
    _, index = header()
    e = index['subjects'][i]
    if not e['file']:
        print('学科 %d 无数据，跳过' % i); return
    L = build_subject(i + 1, e)
    os.makedirs(PARTS, exist_ok=True)
    n, c = write(os.path.join(PARTS, '%02d.txt' % i), L)
    print('学科 %-22s %d 行 / %.1f KB' % (e['subject'], n, c / 1024))


def do_join():
    hd, index = header()
    L = list(hd)
    for i in range(len(index['subjects'])):
        p = os.path.join(PARTS, '%02d.txt' % i)
        if os.path.exists(p):
            L.extend(io.open(p, encoding='utf-8-sig').read().splitlines())
        else:
            L.append('')
            L.append('')
            L.append('%s、%s' % (cn(i + 1), index['subjects'][i]['subject']))
            L.append('　　（本学科本次未生成）')
    L.extend(footer(index))
    while L and L[-1] == '': L.pop()
    L.append('')
    n, c = write(OUT, L)
    print('已写出 %s' % OUT)
    print('   %d 行 / %d 字符 / %.1f KB' % (n, c, os.path.getsize(OUT) / 1024))


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else 'all'
    if mode == 'part':
        do_part(int(sys.argv[2]))
    elif mode == 'join':
        do_join()
    else:
        hd, index = header()
        L = list(hd)
        for i, e in enumerate(index['subjects']):
            if not e['file']: continue
            L.extend(build_subject(i + 1, e))
        L.extend(footer(index))
        while L and L[-1] == '': L.pop()
        L.append('')
        n, c = write(OUT, L)
        print('已写出 %s' % OUT)
        print('   %d 行 / %d 字符 / %.1f KB' % (n, c, os.path.getsize(OUT) / 1024))


if __name__ == '__main__':
    main()
