# -*- coding: utf-8 -*-
"""生成《改版对照总览.md》"""
import sys, os, json, re, io
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pipe2

L = []
def w(s=''): L.append(s)

WS = re.compile(r'\s+')
def sc(s):
    return WS.sub(' ', re.sub(r'[\x00-\x1f\x7f\ufffe]', ' ', s)).strip()

tot_books = tot_groups = tot_changes = tot_newtext = tot_delnote = 0
rows = []
for tk in pipe2.TASKS:
    pairs, miss = pipe2.task_pairs(tk)
    books = []
    for op, np_, short in pairs:
        ip = os.path.join(pipe2.ITEMS_DIR, tk['key'], short + '.json')
        if not os.path.exists(ip):
            books.append((short, None, '2024 版为扫描件／无文字层，无法逐字比对', 0, 0))
            continue
        items = json.load(open(ip, encoding='utf-8'))
        keep, stat = pipe2.clean_book(items, short)
        n = sum(it.get('n', 1) for _, g in keep for it in g)
        nnew = sum(1 for _, g in keep for it in g if it['type'] == '新增')
        ndel = sum(1 for _, g in keep for it in g if it['type'] == '删除')
        books.append((short, stat['groups'], '改动 %d 处（新增 %d／删除 %d）' % (n, nnew, ndel), n, stat['groups']))
        tot_groups += stat['groups']; tot_changes += n
    tot_books += len(pairs)
    rows.append((tk, books, miss))

w('# 改版对照总览（2024 版 ⇄ 2026 版）')
w()
w('本目录下每门课一套《修改页对照》，左栏 2024 版原页、右栏 2026 版原页，均为 A4 原尺寸矢量嵌入；')
w('浅红色框标出两版有差异的文字，编号固定排在各自那一页的右侧页边。')
w()
w('| 科目 | 册数 | 改动组 | 改动处数 | 文件 |')
w('| --- | --- | --- | --- | --- |')
for tk, books, miss in rows:
    g = sum(b[4] for b in books if b[1] is not None)
    n = sum(b[3] for b in books if b[1] is not None)
    w('| %s | %d | %d | %d | `修改页对照_%s.pdf` |' % (tk['label'], len(books), g, n, tk['label']))
w('| **合计** | **%d** | **%d** | **%d** |  |' % (tot_books, tot_groups, tot_changes))
w()
w('---')
w()
for tk, books, miss in rows:
    w('## %s' % tk['label'])
    w()
    w('| 册 | 改动组 | 说明 |')
    w('| --- | --- | --- |')
    for short, g, desc, n, gg in books:
        w('| %s | %s | %s |' % (short, g if g is not None else '—', desc))
    if miss:
        w()
        w('> 2026 版有、2024 版无对应：' + '、'.join(miss))
    w()

# 各册重要改动摘录
w('---')
w()
w('## 各册主要改动摘录')
w()
for tk, books, miss in rows:
    for short, g, desc, n, gg in books:
        if g is None: continue
        ip = os.path.join(pipe2.ITEMS_DIR, tk['key'], short + '.json')
        items = json.load(open(ip, encoding='utf-8'))
        keep, stat = pipe2.clean_book(items, short)
        picks = []
        for key, grp in keep:
            for it in grp:
                o = sc(it['old']); nn = sc(it['new'])
                if it['type'] == '修改' and len(o) <= 40 and len(nn) <= 40:
                    picks.append('“%s”→“%s”' % (o, nn))
                elif it['type'] == '删除' and len(o) <= 30:
                    picks.append('删“%s”' % o)
                elif it['type'] == '新增' and len(nn) <= 30:
                    picks.append('增“%s”' % nn)
        if not picks: continue
        w('**%s / %s**' % (tk['label'], short))
        w()
        w('　'.join(picks[:14]) + ('　…（共 %d 处）' % n if len(picks) > 14 else ''))
        w()

io.open('对比结果/改版对照总览.md', 'w', encoding='utf-8').write('\n'.join(L))
print('written', len(L), 'lines')
