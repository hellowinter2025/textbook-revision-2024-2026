# -*- coding: utf-8 -*-
"""把比对结果导出为结构化 JSON，供 GitHub 仓库使用者直接取用。

    py _preview/export_json.py [输出目录]

产出：
    <out>/index.json            总索引（科目 / 册 / 统计 / 文件清单）
    <out>/<科目·版本>.json       每科一份（含各册各改动组）
    <out>/all.json              全部合并成一份
"""
import os, sys, json, io
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pipe2

OUT = sys.argv[1] if len(sys.argv) > 1 else 'gh-upload/json'
os.makedirs(OUT, exist_ok=True)


def conv_ranges(r):
    """{'0': [[3,8]]} → {'1': [[3,8]]}（页号改 0-based → 1-based）"""
    if not r:
        return {}
    out = {}
    for k, v in r.items():
        try:
            p = int(k) + 1
        except ValueError:
            continue
        out[str(p)] = [list(x) for x in v]
    return out


def build_subject(tk):
    pairs, miss = pipe2.task_pairs(tk)
    books = []
    tot_g = tot_c = 0
    for op, np_, short in pairs:
        ip = os.path.join(pipe2.ITEMS_DIR, tk['key'], short + '.json')
        if not os.path.exists(ip):
            books.append({
                'name': short,
                'old_pdf': op.replace('\\', '/'), 'new_pdf': np_.replace('\\', '/'),
                'groups': 0, 'changes': 0,
                'note': '旧版为纯扫描件（无文字层），无法逐字比对',
                'items': [],
            })
            continue
        items = json.load(open(ip, encoding='utf-8'))
        keep, stat = pipe2.clean_book(items, short)
        groups = []
        for gi, (gk, grp) in enumerate(keep, 1):
            ch = []
            for ci, it in enumerate(grp, 1):
                rec = {
                    'no': ci,
                    'type': it['type'],
                    'old': pipe2.strip_ctrl(it['old']),
                    'new': pipe2.strip_ctrl(it['new']),
                    'old_pages': it['p24'], 'new_pages': it['p26'],
                    'old_ranges': conv_ranges(it.get('r24')),
                    'new_ranges': conv_ranges(it.get('r26')),
                }
                if it.get('n', 1) > 1:
                    rec['count'] = it['n']
                if it.get('a24'):
                    rec['old_anchor'] = it['a24']
                if it.get('a26'):
                    rec['new_anchor'] = it['a26']
                ctx = pipe2.strip_ctrl(it.get('ctx', ''))
                if ctx:
                    rec['context'] = ctx
                ch.append(rec)
            g = {
                'group': gi,
                'old_pages': list(gk[0]),
                'new_pages': list(gk[1]),
                'changes': ch,
            }
            wi = pipe2.whole_item(grp)
            if wi is not None:
                g['whole'] = wi['type']
                g['whole_chars'] = len(pipe2.strip_ctrl(wi['old'] or wi['new']))
            groups.append(g)
        n = sum(it.get('n', 1) for _, g in keep for it in g)
        tot_g += stat['groups']; tot_c += n
        books.append({
            'name': short,
            'old_pdf': op.replace('\\', '/'), 'new_pdf': np_.replace('\\', '/'),
            'groups': stat['groups'], 'changes': n,
            'raw_diff_items': stat['raw'],
            'items': groups,
        })
    return {
        'subject': tk['label'],
        'key': tk['key'],
        'old_dir': tk['old'], 'new_dir': tk['new'],
        'totals': {'books': len(pairs), 'groups': tot_g, 'changes': tot_c},
        'not_included': miss,
        'books': books,
    }


TOT = {'subjects': 0, 'books': 0, 'groups': 0, 'changes': 0}
index = {
    'generated_for': '高中教材 2024 版 ⇄ 2026 版 改动页对照',
    'fields': {
        'group': '改动组序号（与 PDF 里「改动组 N / M」一致）',
        'old_pages / new_pages': '该组涉及的旧版 / 新版页码（1-based）',
        'changes[].type': '修改 / 新增 / 删除',
        'changes[].old / new': '旧版 / 新版文字（已剔除书眉、图表内部文字等噪声）',
        'changes[].count': '同页完全相同的改动合并数（PDF 里显示 ×N），无该字段即为 1',
        'changes[].old_ranges / new_ranges': '标红区间：页号 → [[起始字符序号, 结束字符序号]]',
        'changes[].old_anchor / new_anchor': '纯新增/删除时的位置锚点 [页号, 字符序号, 0|1]，'
                                              '1 表示画在前一字符右边缘',
        'changes[].context': '差异处上下文，“⟦⟧” 标出插入/删除位置',
        'whole': '该组是整篇新增/整篇删除（值即 新增 / 删除）',
    },
    'subjects': [],
}
allsub = []
for tk in pipe2.TASKS:
    s = build_subject(tk)
    with io.open(os.path.join(OUT, s['subject'] + '.json'), 'w', encoding='utf-8') as f:
        json.dump(s, f, ensure_ascii=False, indent=1)
    allsub.append(s)
    index['subjects'].append({
        'subject': s['subject'],
        'file': s['subject'] + '.json',
        'books': s['totals']['books'],
        'groups': s['totals']['groups'],
        'changes': s['totals']['changes'],
        'not_included': s['not_included'],
    })
    TOT['subjects'] += 1
    TOT['books'] += s['totals']['books']
    TOT['groups'] += s['totals']['groups']
    TOT['changes'] += s['totals']['changes']
index['totals'] = TOT
with io.open(os.path.join(OUT, 'index.json'), 'w', encoding='utf-8') as f:
    json.dump(index, f, ensure_ascii=False, indent=1)
with io.open(os.path.join(OUT, 'all.json'), 'w', encoding='utf-8') as f:
    json.dump({'generated_for': index['generated_for'], 'totals': TOT, 'subjects': allsub},
              f, ensure_ascii=False, indent=1)

print('导出到', OUT)
for e in index['subjects']:
    print('   %-18s %d 册 %4d 组 %5d 处  %s' % (e['subject'], e['books'], e['groups'],
                                                e['changes'], e['file']))
print('   合计 %d 套 / %d 册 / %d 组 / %d 处' % (TOT['subjects'], TOT['books'], TOT['groups'], TOT['changes']))
for f in sorted(os.listdir(OUT)):
    print('   %-34s %6.1f KB' % (f, os.path.getsize(os.path.join(OUT, f)) / 1024))
