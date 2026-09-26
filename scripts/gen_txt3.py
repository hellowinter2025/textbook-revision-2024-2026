# -*- coding: utf-8 -*-
"""生成《2024 版与 2026 版教材改动清单》自然语言版 TXT。

句式（可直接摘抄进文章）：
    课文《哦，香雪》中，将“A”修改成了“B”。
    课文《喜看稻菽千重浪》中，删去了“A”。
    课文《琵琶行》中，增加了“A”。

    py _preview/gen_txt3.py [输出文件]
"""
import os, re, sys, json, io
sys.stdout.reconfigure(encoding='utf-8')
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..'))
sys.path.insert(0, HERE)
import fitz, pipe2, titlemap

OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, '对比结果/2024版与2026版教材改动清单.txt')
JROOT = os.path.join(ROOT, 'gh-upload/json')
CUT = 300                       # 单侧引文截断
INLINE = 40                     # 两侧都不超过这个长度 → 写成一句话
WRAP = 42                       # 长引文折行宽度（中文双宽，42 字约 84 列）
BRK1 = '。！？；：'
BRK2 = '，、）】”'
CN_NUM = '零一二三四五六七八九十'
LATIN = re.compile(r'[A-Za-z]')
CJK = re.compile(r'[\u4e00-\u9fff]')


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


BAD_TITLE = re.compile(
    r'^(第\s*[一二三四五六七八九十百\d]+\s*[章节课单元篇]$|附录|活动课|目录|前言|导言|后记|'
    r'Text notes|Grammar notes|Wordlist|Notes|Contents)')


def good_title(t):
    t = (t or '').strip().replace('　', '')
    if not (3 <= len(t) <= 20): return ''
    if BAD_TITLE.match(t): return ''
    if LATIN.search(t):
        if t[0].isupper() and len(re.findall(r"[A-Za-z][A-Za-z'’\-]*", t)) >= 2:
            return t
        return ''
    return t if len(CJK.findall(t)) >= 3 else ''


# 数学、英语的版式标题识别不可靠（数学会把正文句子当成节标题，英语是 Text notes 之类），
# 这两门直接用页码定位，避免给出错的课文名。
NO_TITLE = ('数学', '英语')


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


def where(book, c, kw=''):
    """返回句子开头那半句：语文写「课文《X》中」，其它学科写「《X》一节中」，
    识别不到标题就写「第 N 页处」。"""
    t = title_of(book, c, kw)
    if t:
        return ('课文《%s》中' % t) if kw == '课文' else ('《%s》一节中' % t)
    pages = c.get('old_pages') or c.get('new_pages') or []
    return ('%s处' % pages_txt(pages)) if pages else '某处'


# ---------------- 组织输出 ----------------
L = []
def w(s=''): L.append(s)


def one_change(book, c, ind='　　', kw=''):
    o, n = q(c['old']), q(c['new'])
    cnt = c.get('count', 1)
    tail = '（同一页上共有 %d 处一模一样的改动）' % cnt if cnt > 1 else ''
    wh = where(book, c, kw)
    ty = c['type']
    if max(len(o), len(n)) <= INLINE:
        if ty == '修改':
            w('%s%s，将“%s”修改成了“%s”。%s' % (ind, wh, o, n, tail))
        elif ty == '删除':
            w('%s%s，删去了“%s”。%s' % (ind, wh, o, tail))
        else:
            w('%s%s，增加了“%s”。%s' % (ind, wh, n, tail))
        return
    if ty == '修改': head = '%s%s，有一处文字被改写。%s' % (ind, wh, tail)
    elif ty == '删除': head = '%s%s，删去了一段文字。%s' % (ind, wh, tail)
    else: head = '%s%s，增加了一段文字。%s' % (ind, wh, tail)
    w(head)
    p2 = ind + '　　'
    if ty in ('修改', '删除'):
        for x in wrap(o + '”', p2 + '改动前：“', p2 + '　　'):
            w(x)
    if ty in ('修改', '新增'):
        for x in wrap(n + '”', p2 + '改动后：“', p2 + '　　'):
            w(x)


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


with io.open(os.path.join(JROOT, 'index.json'), encoding='utf-8') as f:
    index = json.load(f)
TOT = index['totals']

w('2024 版 ⇄ 2026 版　高中教材改动清单')
w('（自然语言版，句子可直接摘抄）')
w('')
w('　　共 %d 套教材 · %d 册 · %d 个改动组 · %d 处改动' % (TOT['subjects'], TOT['books'], TOT['groups'], TOT['changes']))
w('　　生成日期：2026-09-26')
w('')
w('阅读说明')
w('－' * 34)
w('1. 每条都是一句完整的话：“课文《…》中，将“A”修改成了“B”。”')
w('   也可以直接摘成“……中将“A”修改成了“B””。')
w('2. 书名号里是该册的课文名（非语文学科为章节名）；数学、英语两门课本章节版式')
w('   不便识别，直接写成“第 N 页处”。')
w('3. 过长的引文分行写成“改动前／改动后”，按标点折行；')
w('   超过 %d 字的在 %d 字处截断，用“……”表示，全文见同一目录的 PDF 或仓库 json 目录。' % (CUT, CUT))
w('4. “×N”表示同一页上有若干处一模一样的改动。')
w('5. “◆ 改动组 N”是《修改页对照》PDF 里的编号，便于回查。')

nsub = 0
for entry in index['subjects']:
    if not entry['file']: continue
    nsub += 1
    with io.open(os.path.join(JROOT, entry['file']), encoding='utf-8') as f:
        d = json.load(f)
    t = d['totals']
    w('')
    w('')
    w('%s、%s' % (cn(nsub), d['subject']))
    w('＝' * 40)
    w('　　%d 册 · %d 个改动组 · %d 处改动' % (t['books'], t['groups'], t['changes']))
    kw = '课文' if '语文' in d['subject'] else ''
    if any(x in d['subject'] for x in NO_TITLE):
        kw = 'off'
    for book in d['books']:
        w('')
        w('【%s】' % book['name'])
        w('－' * 34)
        if book.get('note'):
            w('　　%s。' % book['note']); continue
        if book['groups'] == 0:
            w('　　两版逐字比对未发现差异。'); continue
        w('　　全书 %d 个改动组、%d 处改动。' % (book['groups'], book['changes']))
        for g in book['items']:
            w('')
            if g.get('whole'):
                title = whole_title(book, g)
                nm = '《%s》' % title if title else '一篇课文'
                if g['whole'] == '删除':
                    w('　　◆ 整篇删除（对应改动组 %d）' % g['group'])
                    w('　　2026 版整篇删去了课文%s，原文在 2024 版%s，约 %d 字。'
                      % (nm, pages_txt(g['old_pages']), g.get('whole_chars', 0)))
                else:
                    w('　　◆ 整篇新增（对应改动组 %d）' % g['group'])
                    w('　　2026 版整篇增加了课文%s，在 2026 版%s，约 %d 字。'
                      % (nm, pages_txt(g['new_pages']), g.get('whole_chars', 0)))
                continue
            w('　　◆ 改动组 %d（2024 版%s ⇄ 2026 版%s）'
              % (g['group'], pages_txt(g['old_pages']), pages_txt(g['new_pages'])))
            for c in g['changes']:
                one_change(book, c, kw=kw)

w('')
w('')
w('＝' * 40)
w('（全文完）共 %d 套教材、%d 册、%d 个改动组、%d 处改动。'
  % (TOT['subjects'], TOT['books'], TOT['groups'], TOT['changes']))
w('＝' * 40)

txt = '\n'.join(L) + '\n'
os.makedirs(os.path.dirname(os.path.abspath(OUT)), exist_ok=True)
with io.open(OUT, 'w', encoding='utf-8-sig', newline='\r\n') as f:
    f.write(txt)
print('已写出 %s' % OUT)
print('   %d 行 / %d 字符 / %.1f KB' % (len(L), len(txt), os.path.getsize(OUT) / 1024))
