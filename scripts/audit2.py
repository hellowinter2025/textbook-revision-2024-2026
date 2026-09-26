# -*- coding: utf-8 -*-
"""逐组审计：检查左右两页内容是否对应、条目是否为「句子 ⇄ 碎片」错配。

    py _preview/audit2.py <任务key>
输出 _preview/audit/<key>.txt
"""
import sys, os, re, json, difflib, traceback, time
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fitz
import pipe2

OUT = '_preview/audit'
PUNCT = re.compile('[，。；：、？！,.;:?!]')
CJK = re.compile(r'[\u4e00-\u9fff]')
JUNK = re.compile(r'[\u0530-\u058f\u0590-\u05ff\u0600-\u06ff\u0700-\u074f'
                  '\u0900-\u0dff\u0e00-\u0eff\u0f00-\u0fff\u1000-\u109f'
                  '\u10a0-\u10ff\u1200-\u137f\u1780-\u17ff\u1a00-\u1aaf'
                  '\u1b00-\u1b7f\ue000-\uf8ff\ufffe]')


def kind(t):
    t = pipe2.strip_ctrl(t)
    if not t: return 'empty'
    if len(t) >= 15 and PUNCT.search(t): return 'sentence'
    if len(t) <= 10 and not PUNCT.search(t): return 'fragment'
    return 'text'


def junk_ratio(t):
    t = pipe2.strip_ctrl(t)
    if not t: return 0.0
    return len(JUNK.findall(t)) / len(t)


def page_text(doc, pno, thr):
    if not (0 <= pno < doc.page_count): return ''
    return ''.join(c[0] for c in pipe2.page_chars(doc[pno], set(), thr))


def run(key):
    tk = pipe2.task_by_key(key)
    os.makedirs(OUT, exist_ok=True)
    LOG = open(os.path.join(OUT, key + '.txt'), 'w', encoding='utf-8')
    def pr(*a): print(*a, file=LOG); LOG.flush()
    pairs, _ = pipe2.task_pairs(tk)
    for op, np_, short in pairs:
        ip = os.path.join(pipe2.ITEMS_DIR, key, short + '.json')
        if not os.path.exists(ip):
            pr('=== %s  === （无 items，跳过）' % short); continue
        items = json.load(open(ip, encoding='utf-8'))
        keep, stat = pipe2.clean_book(items, short)
        try:
            dA = fitz.open(op); dB = fitz.open(np_)
        except Exception as e:
            pr('!! %s 打不开 %s' % (short, e)); continue
        thrA = pipe2.doc_thr(dA); thrB = pipe2.doc_thr(dB)
        cache = {}
        def pt(doc, pno, thr, tag):
            k = (tag, pno)
            if k not in cache: cache[k] = page_text(doc, pno, thr)
            return cache[k]
        pr('=== %s  === 保留 %d 组 / %d 处' % (short, stat['groups'], stat['kept']))
        for gi, (gk, grp) in enumerate(keep, 1):
            l = ''.join(pt(dA, p - 1, thrA, 'A') for p in gk[0])
            r = ''.join(pt(dB, p - 1, thrB, 'B') for p in gk[1])
            sim = 0.0
            if l and r:
                sim = difflib.SequenceMatcher(None, l[:1500], r[:1500]).ratio()
            flags = []
            has_mod = any(it['type'] == '修改' and pipe2.strip_ctrl(it['old'])
                          and pipe2.strip_ctrl(it['new']) for it in grp)
            # 纯新增/纯删除的组，左（右）侧是「位置参考页」，与另一侧本就不同，不做相似度判据
            if has_mod and l and r and sim < 0.30:
                flags.append('左右页相似度低 %.2f' % sim)
            if gk[0] and gk[1] and abs(gk[0][0] - gk[1][0]) > 3:
                flags.append('页码相差 %d' % abs(gk[0][0] - gk[1][0]))
            det = []
            for it in grp:
                ko, kn = kind(it['old']), kind(it['new'])
                jo, jn = junk_ratio(it['old']), junk_ratio(it['new'])
                if {ko, kn} == {'sentence', 'fragment'}:
                    flags.append('句子⇄碎片错配')
                if max(jo, jn) > 0.35:
                    flags.append('疑似乱码/符号 %.2f' % max(jo, jn))
                det.append('%s [%s→%s] “%s” → “%s”' % (
                    it['type'], ko, kn,
                    pipe2.cut(pipe2.strip_ctrl(it['old']), 34),
                    pipe2.cut(pipe2.strip_ctrl(it['new']), 34)))
            mark = '!! ' if flags else '   '
            pr('%s组%-3d 2024p%-14s ⇄ 2026p%-14s sim=%.2f %s'
               % (mark, gi, ','.join(map(str, gk[0])), ','.join(map(str, gk[1])), sim,
                  ' / '.join(sorted(set(flags)))))
            if flags:
                for d in det[:8]: pr('        ' + d)
        dA.close(); dB.close()
    LOG.close()
    return key


if __name__ == '__main__':
    if len(sys.argv) > 1:
        run(sys.argv[1])
    else:
        for tk in pipe2.TASKS:
            run(tk['key'])
