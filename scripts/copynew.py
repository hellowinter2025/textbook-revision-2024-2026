# -*- coding: utf-8 -*-
"""把用户直接放进 2026_去水印/ 的新科目搬到 2026/（作为带水印的原始来源），
   去水印脚本再据此重新生成 2026_去水印/ 的净版。"""
import sys, os, shutil
sys.stdout.reconfigure(encoding='utf-8')
LOG=open('_preview/copynew_log.txt','w',encoding='utf-8')
def pr(*a): print(*a,file=LOG); LOG.flush()
DIRS=['数学/人教A版','数学/人教版（B版）（主编：高存明）','历史/统编版',
      '地理/人教版','地理/鲁教版','思想政治/统编版']
for rel in DIRS:
    src=os.path.join('2026_去水印',rel); dst=os.path.join('2026',rel)
    if not os.path.isdir(src):
        pr('!! 源不存在',src); continue
    os.makedirs(dst,exist_ok=True)
    n=0
    for f in sorted(os.listdir(src)):
        if not f.lower().endswith('.pdf'): continue
        s=os.path.join(src,f); d=os.path.join(dst,f)
        if os.path.exists(d) and os.path.getsize(d)==os.path.getsize(s):
            continue
        shutil.copy2(s,d); n+=1
    pr('%-42s 复制 %d 个文件 → %s'%(rel,n,dst))
pr('done')
LOG.close()
