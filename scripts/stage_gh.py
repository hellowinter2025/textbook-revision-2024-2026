# -*- coding: utf-8 -*-
"""把 13 套对照 PDF 与总览报告同步到 gh-upload/"""
import os, shutil, sys
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pipe2

ROOT = 'gh-upload'
os.makedirs(os.path.join(ROOT, 'pdf'), exist_ok=True)
os.makedirs(os.path.join(ROOT, 'docs'), exist_ok=True)
rows = []
for tk in pipe2.TASKS:
    d = os.path.join('对比结果', tk['label'])
    fs = [x for x in os.listdir(d) if x.endswith('.pdf') and '更新' not in x]
    if not fs:
        print('!! 缺', tk['label']); continue
    src = os.path.join(d, sorted(fs)[0])
    dst = os.path.join(ROOT, 'pdf', '修改页对照_%s.pdf' % tk['label'])
    shutil.copy2(src, dst)
    rows.append((tk['label'], os.path.getsize(dst)))
shutil.copy2('对比结果/改版对照总览.md', os.path.join(ROOT, 'docs', '改版对照总览.md'))
keep = {'修改页对照_%s.pdf' % l for l, _ in rows}
for f in os.listdir(os.path.join(ROOT, 'pdf')):
    if f not in keep:
        os.remove(os.path.join(ROOT, 'pdf', f)); print('删除多余', f)
tot = sum(s for _, s in rows)
print('共 %d 套，合计 %.1f MB' % (len(rows), tot / 1e6))
for l, s in sorted(rows, key=lambda x: -x[1]):
    print('   %-18s %6.1f MB' % (l, s / 1e6))
print('--- gh-upload 文件清单 ---')
for dp, dn, fn in os.walk(ROOT):
    if '.git' in dp: continue
    for f in fn:
        print('   ', (dp + '/' + f).replace('\\', '/'))
