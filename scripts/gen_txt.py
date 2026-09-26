# -*- coding: utf-8 -*-
"""生成《2024 版 ⇄ 2026 版 高中教材改动清单》纯文本文档。

自然语言逐条描述，按学科、分册排列，方便直接摘抄编辑。
    py _preview/gen_txt.py [输出文件]
"""
import os, sys, json, io
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fitz
import pipe2

OUT = sys.argv[1] if len(sys.argv) > 1 else '对比结果/2024版与2026版教材改动清单.txt'
JROOT = 'gh-upload/json'
CUT = 300                                   # 单侧引文截断长度

CN_NUM = '零一二三四五六七八九十'


def cn(i):
    if i <= 10:
        return CN_NUM[i] if i < 10 else '十'
    if i < 20:
        return '十' + CN_NUM[i - 10]
    if i < 100:
        s = CN_NUM[i // 10] + '十'
        return s if i % 10 == 0 else s + CN_NUM[i % 10]
    return str(i)


def q(t, cut=CUT):
    """把一段文字处理成可读的引文。"""
    t = pipe2.strip_ctrl(t)
    if not t:
        return ''
    if len(t) > cut:
        return t[:cut] + '……'
    return t


def pages_txt(ps):
    ps = sorted(ps)
    if not ps:
        return '—'
    if len(ps) == 1:
        return '第 %d 页' % ps[0]
    # 连续页码压成区间
    segs, s0, prev = [], ps[0], ps[0]
    for p in ps[1:]:
        if p == prev + 1:
            prev = p
            continue
        segs.append((s0, prev)); s0 = prev = p
    segs.append((s0, prev))
    return '、'.join('第 %d 页' % a if a == b else '第 %d–%d 页' % (a, b) for a, b in segs)


INLINE = 30                                 # 两侧都不超过这个长度就写成一行
WRAP = 40                                   # 长引文折行宽度（中文字符按双宽算，40 字约 80 列）
BREAK_AFTER = '。！？；：'                    # 优先在这些标点后断行
BREAK_AFTER2 = '，、）】”'


def wrap(s, first, cont):
    """按标点把长引文折成多行，便于在编辑器里阅读和摘抄。"""
    if len(s) <= WRAP + 6:
        return [first + s]
    out, pos = [], 0
    while pos < len(s):
        if len(s) - pos <= WRAP + 6:
            out.append((first if not out else cont) + s[pos:])
            break
        win = s[pos:pos + WRAP]
        cut = -1
        for i in range(len(win) - 1, max(0, len(win) - 22), -1):
            if win[i] in BREAK_AFTER:
                cut = i + 1; break
        if cut < 0:
            for i in range(len(win) - 1, max(0, len(win) - 22), -1):
                if win[i] in BREAK_AFTER2:
                    cut = i + 1; break
        if cut < 0:
            cut = WRAP
        out.append((first if not out else cont) + s[pos:pos + cut])
        pos += cut
    return out


def describe(c, indent='        '):
    """把一个改动描述成自然语言。短句写成一行，长段落分行写，便于阅读。"""
    o, n = q(c['old']), q(c['new'])
    t = c['type']
    cnt = c.get('count', 1)
    tail = ''
    if cnt > 1:
        tail = '（同一页上共有 %d 处一模一样的改动）' % cnt
    pad = indent + '    '
    if max(len(o), len(n)) <= INLINE:
        if t == '修改':
            return ['%d. 修改：把「%s」改为「%s」%s' % (c['no'], o, n, tail)]
        if t == '删除':
            return ['%d. 删除：删去了「%s」%s' % (c['no'], o, tail)]
        if t == '新增':
            return ['%d. 新增：增加了「%s」%s' % (c['no'], n, tail)]
        return ['%d. %s：「%s」→「%s」' % (c['no'], t, o, n)]
    # 长条目：分行 + 按标点折行
    if t == '修改':
        return ['%d. 修改：这一处文字被改写了。%s' % (c['no'], tail)] + \
               wrap(o + '」', pad + '改动前：「', pad + '　　　　') + \
               wrap(n + '」', pad + '改动后：「', pad + '　　　　')
    if t == '删除':
        return ['%d. 删除：这一处文字被删掉了。%s' % (c['no'], tail)] + \
               wrap(o + '」', pad + '删去内容：「', pad + '　　　　　')
    if t == '新增':
        return ['%d. 新增：这一处增加了一段文字。%s' % (c['no'], tail)] + \
               wrap(n + '」', pad + '新增内容：「', pad + '　　　　　')
    return (['%d. %s：' % (c['no'], t)]
            + wrap(o + '」', pad + '「', pad + '')
            + wrap(n + '」', pad + '「', pad + ''))


def whole_title(book, g):
    """整篇新增／删除时，取课文标题。"""
    if not g.get('whole'):
        return ''
    key = 'new' if g['whole'] == '新增' else 'old'
    pages = g['new_pages'] if g['whole'] == '新增' else g['old_pages']
    path = book.get('new_pdf' if key == 'new' else 'old_pdf')
    try:
        d = fitz.open(path)
        title, _ = pipe2.find_title(d, [p - 1 for p in pages])
        d.close()
        return title
    except Exception:
        return ''


L = []
def w(s=''):
    L.append(s)


L.append('2024 版 ⇄ 2026 版　高中教材改动清单')
L.append('')
L.append('按学科、分册逐条列出，用自然语言描述每一处改动，可直接摘抄编辑。')
L.append('')
L.append('一式 13 套教材 · 68 册 · 962 个改动组 · 2150 处改动')
L.append('生成日期：2026-09-26')
L.append('')
L.append('=' * 66)
L.append('说明')
L.append('=' * 66)
L.append('1. 每一条都写明了「改了什么」。「改动组 N」与《修改页对照》PDF 里的编号一一对应。')
L.append('2. 页号是原书页码。箭头左边是 2024 版的页号，右边是 2026 版的页号。')
L.append('3. 一眼看得清的短句写成一行；较长或整段改写的分行写成「改动前／改动后」。')
L.append('4. 超过 %d 字的引文在 %d 字处截断，用「……」表示；全文见同名 PDF 或 json 目录。' % (CUT, CUT))
L.append('5. 标「整篇新增」「整篇删除」的，是整篇课文级别的增删。')
L.append('6. 末尾带括号说明的，表示同一页上有若干处一模一样的改动（PDF 里显示为 ×N）。')
L.append('7. 「两版逐字比对未发现差异」表示这一册没有检出差动；若该册旧版是扫描件、')
L.append('   无法逐字比对，会在该册下单独注明。')
L.append('')


def load(subject_file):
    with io.open(os.path.join(JROOT, subject_file), encoding='utf-8') as f:
        return json.load(f)


index = load('index.json')
TOT = index['totals']
nsub = 0
for entry in index['subjects']:
    if not entry['file']:
        continue
    nsub += 1
    d = load(entry['file'])
    t = d['totals']
    L.append('')
    L.append('=' * 66)
    L.append('%s、%s' % (cn(nsub), d['subject']))
    L.append('　　%d 册 · %d 个改动组 · %d 处改动' % (t['books'], t['groups'], t['changes']))
    L.append('=' * 66)
    for book in d['books']:
        L.append('')
        if book.get('note'):
            L.append('【%s】' % book['name'])
            L.append('-' * 66)
            L.append('    %s。' % book['note'])
            continue
        if book['groups'] == 0:
            L.append('【%s】' % book['name'])
            L.append('-' * 66)
            L.append('    两版逐字比对未发现差异。')
            continue
        L.append('【%s】　%d 个改动组、%d 处改动' % (book['name'], book['groups'], book['changes']))
        L.append('-' * 66)
        for g in book['items']:
            if g.get('whole'):
                title = whole_title(book, g)
                name = '《%s》' % title if title else '一篇课文'
                if g['whole'] == '删除':
                    L.append('    改动组 %d　整篇删除' % g['group'])
                    L.append('        2026 版删掉了课文%s，原文在 2024 版%s，约 %d 字。'
                             % (name, pages_txt(g['old_pages']), g.get('whole_chars', 0)))
                else:
                    L.append('    改动组 %d　整篇新增' % g['group'])
                    L.append('        2026 版增加了课文%s，位于 2026 版%s，约 %d 字。'
                             % (name, pages_txt(g['new_pages']), g.get('whole_chars', 0)))
                L.append('')
                continue
            L.append('    改动组 %d　2024 版%s　⇄　2026 版%s'
                     % (g['group'], pages_txt(g['old_pages']), pages_txt(g['new_pages'])))
            for c in g['changes']:
                for line in describe(c):
                    L.append('        ' + line)
            L.append('')
        while L and L[-1] == '':
            L.pop()

L.append('')
L.append('=' * 66)
L.append('（全文完）共 %d 套教材、%d 册、%d 个改动组、%d 处改动。'
         % (TOT['subjects'], TOT['books'], TOT['groups'], TOT['changes']))
L.append('=' * 66)

txt = '\n'.join(L) + '\n'
os.makedirs(os.path.dirname(os.path.abspath(OUT)), exist_ok=True)
with io.open(OUT, 'w', encoding='utf-8-sig', newline='\r\n') as f:
    f.write(txt)
print('已写出 %s' % OUT)
print('   %d 行 / %d 字符 / %.1f KB' % (len(L), len(txt), os.path.getsize(OUT) / 1024))
