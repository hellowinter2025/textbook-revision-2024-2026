# -*- coding: utf-8 -*-
"""
并行调度器：把每册的 diff / build 拆成独立子进程跑，16 核跑满。

    py _preview/runjobs.py diff  [并发数]     # 计算所有缺 items 的册
    py _preview/runjobs.py build [并发数]     # 生成所有缺单册 PDF 的册，然后按科目合并
    py _preview/runjobs.py status             # 查看进度
"""
import sys, os, subprocess, time
from concurrent.futures import ThreadPoolExecutor, as_completed
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pipe2

PY = sys.executable
LOG = open('_preview/runjobs_log.txt', 'a', encoding='utf-8')
def pr(*a):
    print(*a, file=LOG); LOG.flush()

ENV = dict(os.environ, PYTHONIOENCODING='utf-8')
CF = 0x08000000 if os.name == 'nt' else 0     # CREATE_NO_WINDOW

def call(args):
    r = subprocess.run([PY, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                        'pipe2.py')] + list(args), capture_output=True,
                       encoding='utf-8', errors='replace', env=ENV,
                       creationflags=CF, cwd=os.getcwd())
    out = (r.stdout or '').strip()
    if r.returncode != 0:
        out += '  [exit %d] %s' % (r.returncode, (r.stderr or '')[-200:])
    return out

def run(jobs, workers, label):
    if not jobs:
        pr('%s：没有待处理项' % label); return
    pr('%s：%d 个作业，并发 %d' % (label, len(jobs), workers))
    t0 = time.time(); done = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(call, j): j for j in jobs}
        for f in as_completed(futs):
            j = futs[f]
            try: msg = f.result()
            except Exception as e: msg = '!! 异常 %s' % e
            done += 1
            pr('[%d/%d] %s  (%.0fs)' % (done, len(jobs), msg, time.time() - t0))
    pr('%s 完毕，用时 %.0fs' % (label, time.time() - t0))

def status():
    for tk in pipe2.TASKS:
        pairs, miss = pipe2.task_pairs(tk)
        ni = nb = 0
        for op, np_, s in pairs:
            if os.path.exists(os.path.join(pipe2.ITEMS_DIR, tk['key'], s + '.json')): ni += 1
            if os.path.exists(os.path.join('_tmp_pipe', tk['key'], s + '.pdf')): nb += 1
        pr('%-16s %-16s 配对%-3d 缺%-2d  items %2d/%2d  单册PDF %2d/%2d'
           % (tk['key'], tk['label'], len(pairs), len(miss), ni, len(pairs), nb, len(pairs)))
        for m in miss:
            pr('        2024 无对应：%s' % m)

def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else 'status'
    if mode == 'status':
        status(); return
    allp = []
    for tk in pipe2.TASKS:
        pairs, _ = pipe2.task_pairs(tk)
        for op, np_, s in pairs:
            allp.append((tk['key'], s))
    if mode == 'diff':
        jobs = [('one', k, s) for k, s in allp
                if not os.path.exists(os.path.join(pipe2.ITEMS_DIR, k, s + '.json'))]
        run(jobs, int(sys.argv[2]) if len(sys.argv) > 2 else 10, 'diff')
    elif mode == 'build':
        jobs = [('buildone', k, s) for k, s in allp
                if os.path.exists(os.path.join(pipe2.ITEMS_DIR, k, s + '.json'))
                and not os.path.exists(os.path.join('_tmp_pipe', k, s + '.pdf'))]
        run(jobs, int(sys.argv[2]) if len(sys.argv) > 2 else 10, 'buildone')
        mj = [('merge', tk['key']) for tk in pipe2.TASKS]
        run(mj, 4, 'merge')
    else:
        pr('未知模式', mode)

if __name__ == '__main__':
    pr('########## %s %s' % (time.strftime('%H:%M:%S'), ' '.join(sys.argv[1:])))
    main()
    LOG.close()
