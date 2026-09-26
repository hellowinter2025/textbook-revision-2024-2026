# -*- coding: utf-8 -*-
"""从教材 PDF 版式里识别「课文 / 章节」标题，建立 页 → 标题 的对照表。

标题特征：字号明显大于正文（≥ min(max(15pt, 正文×1.4), 20pt)）、单行不太长、
位于版心内、且以真汉字为主（方正数学字体会把斜体字母映射到「犭」旁生僻字，
这些字在正文体里不会出现，用它排除公式假标题）。全书重复出现 ≥2 次的字符串
判为栏目名（学习提示、单元学习任务…）排除。

    py titlemap.py list                 # 列出需要建表的文件
    py titlemap.py one old <pdf>        # 处理单个文件，写 _preview/titlemaps/<hash>.json
    py titlemap.py build 12             # 并行建表（全部旧版+新版）
    py titlemap.py probe                # 打印几册的识别结果供人工核对
    py titlemap.py show <略>            # 打印已建好的某一册页→标题
"""
import os, re, sys, json, hashlib, io, subprocess
from collections import Counter
sys.stdout.reconfigure(encoding='utf-8')
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..'))
sys.path.insert(0, HERE)
import fitz

MAPS_DIR = os.path.join(HERE, 'titlemaps')
NOT_TITLE = re.compile(
    r'^(第[一二三四五六七八九十百\d]+(单元|章节|课|讲|篇|部分)|'
    r'[\d\.、，。：；\-—　 ]+)$')
CJK = re.compile(r'[\u4e00-\u9fff]')
# 方正数学字体把斜体字母映射到「犬/爿」旁生僻字（犃犅犆犪犫狀犿犙…），不算中文
MATH_CJK = re.compile(r'[\u7280-\u72ff]')
FORMULA = re.compile(r'[=+±→←↑↓∑∫√∩∪≌△≤≥≠≈∞×÷⋅·∅∁℃°′″∠⊥∥∽≡]|[＋－＝×÷]')
LATIN_WORD = re.compile(r"[A-Za-z][A-Za-z'’\-]{1,}")


def key_of(path):
    return hashlib.md5(os.path.abspath(path).encode('utf-8')).hexdigest()[:16]


def body_size(doc):
    """正文体字号：只统计 8–16pt（教材中文正文的常见区间）。
    不限范围的话，数学册里公式字体的 20pt+ 字符会压过正文，把阈值顶到上限。"""
    c = Counter()
    step = max(1, doc.page_count // 60)
    for i in range(0, doc.page_count, step):
        for b in doc[i].get_text('dict')['blocks']:
            if b['type'] != 0: continue
            for l in b.get('lines', []):
                for s in l['spans']:
                    t = s['text'].strip()
                    if t and 8.0 <= s['size'] <= 16.0:
                        c[round(s['size'], 1)] += len(t)
    if c:
        return max(c.items(), key=lambda x: x[1])[0]
    c = Counter()
    for i in range(0, doc.page_count, step):
        for b in doc[i].get_text('dict')['blocks']:
            if b['type'] != 0: continue
            for l in b.get('lines', []):
                for s in l['spans']:
                    if s['text'].strip(): c[round(s['size'], 1)] += len(s['text'])
    return max(c.items(), key=lambda x: x[1])[0] if c else 12.0


def body_chars(doc):
    """正文体（≤14.5pt）里出现过的汉字集合 —— 用来识别数学斜体假汉字。"""
    out = set()
    step = max(1, doc.page_count // 60)
    for i in range(0, doc.page_count, step):
        for b in doc[i].get_text('dict')['blocks']:
            if b['type'] != 0: continue
            for l in b.get('lines', []):
                for s in l['spans']:
                    if s['size'] > 14.5: continue
                    out.update(c for c in s['text'] if CJK.match(c))
    return out


def line_candidates(l):
    """把同一行里字号一致、彼此紧邻的 span 合成候选（课文名常被拆成多个 span）。"""
    sps = [s for s in l['spans'] if s['text'].strip()]
    if not sps: return []
    groups, cur = [], [sps[0]]
    for s in sps[1:]:
        if (abs(s['size'] - cur[-1]['size']) <= 0.2
                and s['bbox'][0] - cur[-1]['bbox'][2] < max(s['size'], 8) * 1.8):
            cur.append(s)
        else:
            groups.append(cur); cur = [s]
    groups.append(cur)
    return [(''.join(x['text'] for x in g).strip(),
             max(x['size'] for x in g),
             min(x['bbox'][0] for x in g)) for g in groups]


def page_titles(doc):
    """返回 ({页号(1-based): 标题}, 正文体字号, 阈值)。未识别到标题的页沿用前一页。"""
    body = body_size(doc)
    tmin = min(max(15.0, body * 1.4), 20.0)
    good_chars = body_chars(doc)
    cand = Counter(); per_page = {}
    for i in range(doc.page_count):
        pg = doc[i]; h = pg.rect.height
        got = []
        for b in pg.get_text('dict')['blocks']:
            if b['type'] != 0: continue
            for l in b.get('lines', []):
                if not (h * 0.05 < l['bbox'][1] < h * 0.30): continue   # 课文/节标题在页面顶部
                for txt, sz, x in line_candidates(l):
                    if not (2 <= len(txt) <= 30): continue
                    if sz < tmin: continue
                    if FORMULA.search(txt): continue
                    if MATH_CJK.search(txt): continue      # 方正数学斜体假汉字
                    if NOT_TITLE.match(txt): continue
                    cj = [c for c in txt if CJK.match(c)]
                    if len(cj) >= 2:
                        # 中文标题：多数汉字要在正文体里出现过（排除生僻假字）
                        if sum(1 for c in cj if c in good_chars) / len(cj) < 0.7: continue
                    else:
                        # 英文标题（如 “Back to school”“Realizing your potential”）
                        if cj: continue
                        if len(LATIN_WORD.findall(txt)) < 2: continue
                    got.append((sz, x, txt))
                    cand[txt] += 1
        if got:
            got.sort(key=lambda x: (-x[0], x[1]))
            per_page[i + 1] = got[0][2]
    # 重复出现的当作栏目名/页眉排除
    per_page = {p: t for p, t in per_page.items() if cand[t] < 2}
    out, cur = {}, ''
    for p in range(1, doc.page_count + 1):
        if p in per_page: cur = per_page[p]
        out[p] = cur
    return out, body, tmin


def all_files():
    import pipe2
    out = []
    for tk in pipe2.TASKS:
        pairs, _ = pipe2.task_pairs(tk)
        for op, np_, short in pairs:
            out.append(('old', os.path.abspath(op), tk['key'], short))
            out.append(('new', os.path.abspath(np_), tk['key'], short))
    return out


def do_one(tag, path):
    d = fitz.open(path)
    m, body, tmin = page_titles(d)
    d.close()
    os.makedirs(MAPS_DIR, exist_ok=True)
    fp = os.path.join(MAPS_DIR, '%s.json' % key_of(path))
    json.dump({'tag': tag, 'path': path, 'body': body, 'tmin': tmin,
               'map': {str(k): v for k, v in m.items()}},
              open(fp, 'w', encoding='utf-8'), ensure_ascii=False)
    n = sum(1 for v in m.values() if v)
    return fp, n


def load_all():
    """返回 {绝对路径: {页号(int): 标题}}"""
    out = {}
    if not os.path.isdir(MAPS_DIR): return out
    for f in os.listdir(MAPS_DIR):
        if not f.endswith('.json'): continue
        try:
            j = json.load(open(os.path.join(MAPS_DIR, f), encoding='utf-8'))
        except Exception:
            continue
        out[os.path.abspath(j['path'])] = {int(k): v for k, v in j['map'].items()}
    return out


def build(nproc=10):
    files = all_files()
    todo = [(t, p) for t, p, _, _ in files
            if not os.path.exists(os.path.join(MAPS_DIR, '%s.json' % key_of(p)))]
    print('需建表 %d / 共 %d' % (len(todo), len(files)))
    from concurrent.futures import ThreadPoolExecutor
    def run(a):
        tag, p = a
        r = subprocess.run([sys.executable, os.path.join(HERE, 'titlemap.py'), 'one', tag, p],
                           capture_output=True, encoding='utf-8', errors='replace')
        return (p, r.returncode)
    done = 0
    with ThreadPoolExecutor(max_workers=nproc) as ex:
        for p, rc in ex.map(run, todo):
            done += 1
            if rc: print('  !! %s rc=%d' % (os.path.basename(p), rc))
            if done % 10 == 0: print('  已处理 %d/%d' % (done, len(todo)))
    print('完成，缓存目录 %s' % MAPS_DIR)


PROBES = [
    ('语文 必修上', '2024/1-语文/普通高中教科书·语文必修 上册.pdf', (20, 65)),
    ('化学 必修一', '2024/5-化学/普通高中教科书·化学必修 第一册.pdf', (20, 40)),
    ('数学苏教 必修一', '2024/2-数学/普通高中教科书·数学必修 第一册.pdf', (20, 40)),
    ('英语 必修一', '2024/3-英语/普通高中教科书·英语必修 第一册.pdf', (5, 30)),
]


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else 'probe'
    if mode == 'one':
        fp, n = do_one(sys.argv[2], sys.argv[3])
        print('%s  → %s（%d 页有标题）' % (sys.argv[3], fp, n))
    elif mode == 'build':
        build(int(sys.argv[2]) if len(sys.argv) > 2 else 10)
    elif mode == 'list':
        for t, p, k, s in all_files():
            fp = os.path.join(MAPS_DIR, '%s.json' % key_of(p))
            print('%-4s %-12s %-22s %s' % (t, k, s, '已建' if os.path.exists(fp) else '待建'))
    elif mode == 'show':
        p = os.path.abspath(sys.argv[2])
        j = json.load(open(os.path.join(MAPS_DIR, '%s.json' % key_of(p)), encoding='utf-8'))
        m = {int(k): v for k, v in j['map'].items()}
        prev = None
        for k in sorted(m):
            if m[k] and m[k] != prev:
                print('  第%-4d页  【%s】' % (k, m[k])); prev = m[k]
    else:
        for name, rel, (a, b) in PROBES:
            p = os.path.join(ROOT, rel)
            if not os.path.exists(p): print('!! 缺 ' + rel); continue
            d = fitz.open(p)
            m, body, tmin = page_titles(d)
            print('===== %-18s 正文体 %spt，标题阈值 %spt' % (name, body, round(tmin, 1)))
            prev = None
            for pg in range(a, min(b + 1, d.page_count + 1)):
                t = m.get(pg, '')
                if t != prev:
                    print('   第%-4d页  【%s】' % (pg, t)); prev = t
            d.close()


if __name__ == '__main__':
    main()
