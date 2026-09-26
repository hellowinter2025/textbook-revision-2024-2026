# -*- coding: utf-8 -*-
"""并行跑各科目的逐组审计，并汇总可疑项。

    py _preview/audit_run.py [并发数]
"""
import sys, os, subprocess, time, glob, re
from concurrent.futures import ThreadPoolExecutor, as_completed
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pipe2

PY = sys.executable
LOG = open('_preview/audit_run_log.txt', 'w', encoding='utf-8')
def pr(*a): print(*a, file=LOG); LOG.flush()
ENV = dict(os.environ, PYTHONIOENCODING='utf-8')
CF = 0x08000000 if os.name == 'nt' else 0

def call(key):
    r = subprocess.run([PY, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                        'audit2.py'), key], capture_output=True,
                       encoding='utf-8', errors='replace', env=ENV,
                       creationflags=CF, cwd=os.getcwd())
    return key, r.returncode, (r.stderr or '')[-300:]

def main():
    workers = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    os.makedirs('_preview/audit', exist_ok=True)
    keys = [tk['key'] for tk in pipe2.TASKS]
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(call, k): k for k in keys}
        for f in as_completed(futs):
            k, rc, err = f.result()
            pr('完成 %-16s rc=%d %s' % (k, rc, err))
    pr('审计完毕 %.0fs' % (time.time() - t0))

    # 汇总
    bad = []
    tot_g = tot_i = 0
    for f in sorted(glob.glob('_preview/audit/*.txt')):
        cur = None
        for line in open(f, encoding='utf-8'):
            line = line.rstrip('\n')
            m = re.match(r'=== (.+) === 保留 (\d+) 组 / (\d+) 处', line)
            if m:
                cur = m.group(1); tot_g += int(m.group(2)); tot_i += int(m.group(3)); continue
            if line.startswith('!! '):
                bad.append((os.path.basename(f)[:-4], cur, line[3:]))
        pr('')
    pr('总保留 %d 组 / %d 处' % (tot_g, tot_i))
    pr('可疑组 %d 个' % len(bad))
    byk = {}
    for k, short, msg in bad:
        byk.setdefault((k, short), []).append(msg)
    for (k, short), msgs in sorted(byk.items()):
        pr('  %-18s %-26s %d 组可疑' % (k, short, len(msgs)))
        for m in msgs[:6]: pr('        ' + m)
    LOG.close()

if __name__ == '__main__':
    main()
