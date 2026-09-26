# -*- coding: utf-8 -*-
"""把 JSON / 脚本 / 文档同步到 gh-upload，并按最新统计改写 README 的表格与总数。"""
import os, re, io, sys, json, shutil
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..'))
sys.path.insert(0, HERE)
import pipe2

GH = os.path.join(ROOT, 'gh-upload')

# 1) 脚本
for f in ('pipe2.py', 'runjobs.py', 'dewm.py', 'export_json.py', 'audit2.py', 'audit_run.py',
          'mkdiag3.py', 'verifyfast.py', 'gen_overview.py', 'gen_txt.py', 'gen_txt3.py',
          'gen_txt_run.py', 'titlemap.py', 'sync_gh.py', 'copynew.py', 'gh.py', 'push_gh.py'):
    src = os.path.join(HERE, f)
    if not os.path.exists(src):
        print('!! 缺脚本', f); continue
    dst = os.path.join(GH, 'scripts', f)
    if os.path.exists(dst) and open(src, 'rb').read() == open(dst, 'rb').read():
        continue
    shutil.copy2(src, dst)
print('脚本已同步')

# 2) 文档
for a, b in (('对比结果/改版对照总览.md', 'docs/改版对照总览.md'),
             ('对比结果/对照结果审计报告.md', 'docs/对照结果审计报告.md'),
             ('对比结果/2024版与2026版教材改动清单.txt', 'docs/2024版与2026版教材改动清单（自然语言版）.txt')):
    s = os.path.join(ROOT, a); d = os.path.join(GH, b)
    os.makedirs(os.path.dirname(d), exist_ok=True)
    shutil.copy2(s, d)
print('文档已同步')

# 3) README 表格与总数
idx = json.load(io.open(os.path.join(GH, 'json/index.json'), encoding='utf-8'))
rows = []
for e in idx['subjects']:
    p = os.path.join(GH, 'pdf', '修改页对照_%s.pdf' % e['subject'])
    if e['file']:
        d = json.load(io.open(os.path.join(GH, 'json', e['file']), encoding='utf-8'))['totals']
        rows.append((e['subject'], d['books'], d['groups'], d['changes'],
                     os.path.getsize(p) / 1e6 if os.path.exists(p) else 0))
    else:
        rows.append((e['subject'], 0, 0, 0, 0))
tbl = ['| 文件 | 科目 | 册数 | 改动组 | 改动处数 | 体积 |', '| --- | --- | ---: | ---: | ---: | ---: |']
for s, b, g, c, sz in rows:
    if b == 0:
        tbl.append('| — | %s | — | — | — | — |' % s)
    else:
        tbl.append('| `修改页对照_%s.pdf` | %s | %d | %d | %d | %.1f MB |' % (s, s, b, g, c, sz))
T = idx['totals']
tbl.append('')
tbl.append('合计 **%d 套 · %d 册 · %d 个改动组 · %d 处改动**（共 %.0f MB）'
           % (T['subjects'], T['books'], T['groups'], T['changes'],
              sum(x[4] for x in rows)))

rp = os.path.join(GH, 'README.md')
s = io.open(rp, encoding='utf-8').read()
i = s.find('| 文件 | 科目 | 册数 | 改动组 | 改动处数 | 体积 |')
j = s.find('\n\n', i)
assert i > 0 and j > i, 'README 表格定位失败'
s = s[:i] + '\n'.join(tbl) + s[j:]
s = re.sub(r'13 套 68 册 [\d]+ 处改动', '13 套 68 册 %d 处改动' % T['changes'], s)
s = re.sub(r'13 套 68 册，[\d]+ 处改动', '13 套 68 册，%d 处改动' % T['changes'], s)
io.open(rp, 'w', encoding='utf-8').write(s)
print('README 表格已更新，合计 %d 组 / %d 处' % (T['groups'], T['changes']))

# 4) 清单
n = 0; tot = 0
for dp, dn, fn in os.walk(GH):
    if '.git' in dp.split(os.sep): continue
    for f in fn:
        p = os.path.join(dp, f); n += 1; tot += os.path.getsize(p)
print('仓库工作副本 %d 个文件 / %.1f MB' % (n, tot / 1e6))
