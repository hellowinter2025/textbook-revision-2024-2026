# -*- coding: utf-8 -*-
"""并行生成改动清单 TXT：每个学科一个子进程（所在句提取要逐页抽字符，串行太慢）。"""
import os, sys, json, io, subprocess, time
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..'))
from concurrent.futures import ThreadPoolExecutor
PY = sys.executable
N = int(sys.argv[1]) if len(sys.argv) > 1 else 7

idx = json.load(io.open(os.path.join(ROOT, 'gh-upload/json/index.json'), encoding='utf-8'))
jobs = [i for i, e in enumerate(idx['subjects']) if e['file']]
t0 = time.time()
def run(i):
    r = subprocess.run([PY, '-X', 'utf8', os.path.join(HERE, 'gen_txt3.py'), 'part', str(i)],
                       cwd=ROOT, capture_output=True, encoding='utf-8', errors='replace')
    return i, r.returncode, (r.stdout or '').strip(), (r.stderr or '').strip()
done = 0
with ThreadPoolExecutor(max_workers=N) as ex:
    for i, rc, out, err in ex.map(run, jobs):
        done += 1
        print('[%d/%d] %-24s rc=%d %s %s' % (done, len(jobs),
              idx['subjects'][i]['subject'], rc, out.replace('\n', ' ')[:60],
              ('ERR ' + err.splitlines()[-1][:90]) if err else ''))
print('part 阶段 %.0fs' % (time.time() - t0))
r = subprocess.run([PY, '-X', 'utf8', os.path.join(HERE, 'gen_txt3.py'), 'join'],
                   cwd=ROOT, capture_output=True, encoding='utf-8', errors='replace')
print((r.stdout or '').strip())
if r.stderr.strip(): print('ERR', r.stderr.strip()[:400])
print('总计 %.0fs' % (time.time() - t0))
