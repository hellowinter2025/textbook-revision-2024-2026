# -*- coding: utf-8 -*-
import sys, os, fitz
sys.stdout.reconfigure(encoding='utf-8')
DISP_W=595.276; DISP_H=841.890; MARGIN=26.0; GAP=20.0; HEAD=170.0
X_L=MARGIN; X_R=MARGIN+DISP_W+GAP; Y0=HEAD
FILLC=(1.0,0.588,0.588); RED=(0.784,0.063,0.129)
LOG=open('_preview/mkdiag3_log.txt','w',encoding='utf-8')
def pr(*a): print(*a,file=LOG); LOG.flush()
def near(a,b): return a is not None and all(abs(a[i]-b[i])<0.02 for i in range(3))
files=[os.path.join(dp,f) for dp,dn,fn in os.walk('对比结果') for f in fn
       if f.startswith('修改页对照_') and f.endswith('.pdf') and '_旧版备份' not in dp]
tot=cmp=cov=0; prob=[]
for p in sorted(files):
    d=fitz.open(p)
    for i in range(d.page_count):
        pg=d[i]; tot+=1
        head=''.join(sp['text'] for b in pg.get_text('dict')['blocks']
                     for l in b.get('lines',[]) for sp in l['spans'] if sp['bbox'][1]<45)
        L=fitz.Rect(X_L,Y0,X_L+DISP_W,Y0+DISP_H); R=fitz.Rect(X_R,Y0,X_R+DISP_W,Y0+DISP_H)
        wL=len(pg.get_text('words',clip=L)); wR=len(pg.get_text('words',clip=R))
        if wL<3 and wR<3:
            if '改动页对照' in head: cov+=1
            continue
        cmp+=1
        mL=mR=0
        for dr in pg.get_drawings():
            f=dr.get('fill');r=fitz.Rect(dr['rect'])
            if r.width>60 and r.height>60: continue
            inL=X_L-1<=r.x0 and r.x1<=X_L+DISP_W+1
            inR=X_R-1<=r.x0 and r.x1<=X_R+DISP_W+1
            if not (inL or inR): continue
            if not (near(f,FILLC) or near(f,RED)): continue
            if (r.x0+r.x1)/2 < X_L+DISP_W+GAP/2: mL+=1
            else: mR+=1
        if wL<5 or mL==0 or wR<5 or mR==0:
            prob.append((os.path.basename(p),i+1,wL,wR,mL,mR,head[:36]))
    d.close()
pr('总页数 %d  对照页 %d  封面页 %d'%(tot,cmp,cov))
pr('有内容的对照页里，某侧异常（栏空或无标记）的：%d'%len(prob))
for x in prob[:25]: pr('   %s p%-4d 左词%-4d 右词%-4d 左标记%-3d 右标记%-3d %s'%x)
LOG.close()
