# -*- coding: utf-8 -*-
"""抽样几何核查（每 4 页取 1 页），比全量快 4 倍"""
import sys, os, fitz
sys.stdout.reconfigure(encoding='utf-8')
DISP_W=595.276; DISP_H=841.890; MARGIN=26.0; GAP=20.0; HEAD=170.0
X_L=MARGIN; X_R=MARGIN+DISP_W+GAP; Y0=HEAD
EXP_L=X_L+DISP_W-16.5; EXP_R=X_R+DISP_W-16.5
FILLC=(1.0,0.588,0.588); RED=(0.784,0.063,0.129)
LOG=open('_preview/verifyfast_log.txt','w',encoding='utf-8')
def pr(*a): print(*a,file=LOG); LOG.flush()
def near(a,b): return a is not None and all(abs(a[i]-b[i])<0.02 for i in range(3))
files=[os.path.join(dp,f) for dp,dn,fn in os.walk('对比结果') for f in fn
       if f.startswith('修改页对照_') and f.endswith('.pdf') and '_旧版备份' not in dp]
files.sort()
T=dict(boxes=0,badges=0,badx=0,ovl=0,empty=0,mark=0,cmp=0)
pr('%-34s %5s %5s %6s %6s %5s %5s' % ('文件','抽样页','对照','红框','编号','越界','压框'))
for p in files:
    d=fitz.open(p); PW=d[0].rect.width
    keep=[]
    for i in range(0,d.page_count,4):
        pg=d[i]
        head=''.join(sp['text'] for b in pg.get_text('dict')['blocks']
                     for l in b.get('lines',[]) for sp in l['spans'] if sp['bbox'][1]<40)
        if '整篇' in head: continue
        L=fitz.Rect(X_L,Y0,X_L+DISP_W,Y0+DISP_H); R=fitz.Rect(X_R,Y0,X_R+DISP_W,Y0+DISP_H)
        wL=len(pg.get_text('words',clip=L)); wR=len(pg.get_text('words',clip=R))
        if wL<3 and wR<3: continue
        keep.append((i,pg,wL,wR))
    b_=bd_=bx_=ov_=em_=mk_=0
    for i,pg,wL,wR in keep:
        badges=[];boxes=[];vlines=[];mL=mR=0
        for dr in pg.get_drawings():
            f=dr.get('fill');r=fitz.Rect(dr['rect'])
            if r.width>60 and r.height>60: continue
            inL=X_L-1<=r.x0 and r.x1<=X_L+DISP_W+1
            inR=X_R-1<=r.x0 and r.x1<=X_R+DISP_W+1
            if not (inL or inR): continue
            if near(f,RED) and 12.9<=r.width<=14.1 and 12.9<=r.height<=14.1: badges.append(r)
            elif near(f,RED) and r.width<5:
                vlines.append(r); (mL:=mL) if False else None
                if (r.x0+r.x1)/2 < X_L+DISP_W+GAP/2: mL+=1
                else: mR+=1
            elif near(f,FILLC):
                boxes.append(r)
                if (r.x0+r.x1)/2 < X_L+DISP_W+GAP/2: mL+=1
                else: mR+=1
        b_+=len(boxes); bd_+=len(badges)
        if wL<5: em_+=1
        if wR<5: em_+=1
        if mL==0: mk_+=1
        if mR==0: mk_+=1
        for b in badges:
            exp=EXP_L if b.x0<X_L+DISP_W+GAP/2 else EXP_R
            if abs(b.x0-exp)>0.6: bx_+=1
            for x in boxes:
                if not (b & x).is_empty: ov_+=1; break
    pr('%-34s %5d %5d %6d %6d %5d %5d' % (os.path.basename(p)[:34],len(keep),len(keep),b_,bd_,bx_,ov_))
    T['boxes']+=b_; T['badges']+=bd_; T['badx']+=bx_; T['ovl']+=ov_; T['empty']+=em_; T['mark']+=mk_
    d.close()
pr('---- 抽样合计 对照页 %d  红框 %d  编号 %d  越界 %d  压框 %d  栏空 %d  无标记 %d'
   % (T['cmp'],T['boxes'],T['badges'],T['badx'],T['ovl'],T['empty'],T['mark']))
LOG.close()
