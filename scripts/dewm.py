# -*- coding: utf-8 -*-
"""
2026 新科目 PDF 去水印

水印三种形态：
  A. Watermark 注释（/Type/Annot/Subtype/Watermark）—— 删注释
  B. 自包含水印 Form XObject（BBox 远小于整页、内部不引用其它 XObject）—— 整条流置空
  C. Acrobat 把「整页内容 + 水印」包在一起的外壳 Form（BBox 接近整页、内部有 /FmN Do）
     —— 绝不能置空！只把 `/Artifact <</Subtype /Watermark …>>BDC … EMC` 这一块挖掉

校验：① 渲染比对（改动像素占比 + 改动区域）
      ② 页脚区（y>93%）残留文字比对——水印文字必须消失
"""
import sys, os, re, fitz, traceback
import numpy as np
sys.stdout.reconfigure(encoding='utf-8')

SRC_ROOTS = None          # None = 自动发现 2026/ 下所有含 PDF 的目录
DST_ROOT = '2026_去水印'

TAG = sys.argv[1] if len(sys.argv) > 1 else 'all'
TAG_SAFE = re.sub(r'[\\/:*?"<>|]', '_', TAG)
os.makedirs('_preview', exist_ok=True)
LOG = open('_preview/dewm_log_%s.txt' % TAG_SAFE, 'w', encoding='utf-8')
def pr(*a):
    print(*a, file=LOG); LOG.flush()

def discover():
    out = []
    for dp, dn, fn in os.walk('2026'):
        if os.path.normpath(dp) == '2026':
            continue
        if any(f.lower().endswith('.pdf') for f in fn):
            out.append(dp.replace('\\', '/'))
    return sorted(out)

ARK = re.compile(rb'/Artifact\s*<<[^>]*?/Subtype\s*/Watermark[^>]*?>>\s*(?:BDC|BMC)')
TOK = re.compile(rb'\b(?:BDC|BMC|EMC)\b')
BBOX = re.compile(r'/BBox\s*\[([^\]]*)\]')
DOOP = re.compile(rb'/[A-Za-z0-9_.]+\s+Do\b')

def tobytes(s):
    return s.encode('latin-1', 'replace') if isinstance(s, str) else s

def excise_artifact(stream):
    out = tobytes(stream)
    for _ in range(20):
        m = ARK.search(out)
        if not m: break
        start = m.start(); i = m.end(); depth = 1; end = None
        while True:
            t = TOK.search(out, i)
            if not t: break
            if t.group(0) == b'EMC':
                depth -= 1
                if depth == 0: end = t.end(); break
            else:
                depth += 1
            i = t.end()
        if end is None:
            out = out[:start]; break
        out = out[:start] + out[end:]
    return out

def tail_text(doc, pno):
    if not (0 <= pno < doc.page_count): return []
    pg = doc[pno]; h = pg.rect.height; out = []
    for bl in pg.get_text('dict')['blocks']:
        for l in bl.get('lines', []):
            for sp in l['spans']:
                if sp['bbox'][1] > h * 0.93 and sp['text'].strip():
                    out.append(sp['text'].strip())
    return out

def clean(path, dst):
    doc = fitz.open(path)
    page_area = max((p.rect.width * p.rect.height) for p in doc)
    n_ann = n_blank = n_excise = 0
    for page in doc:                                     # A
        for a in list(page.annots() or []):
            try:
                if a.type[0] == 25:
                    page.delete_annot(a); n_ann += 1
            except Exception:
                pass
    targets = []
    for x in range(1, doc.xref_length()):
        try:
            obj = doc.xref_object(x, compressed=True)
        except Exception:
            continue
        if obj and '/Private/Watermark' in obj:
            targets.append((x, obj))
    for x, obj in targets:                               # B / C
        try:
            if not doc.xref_is_stream(x):
                continue
            stream = tobytes(doc.xref_stream(x) or b'')
            m = BBOX.search(obj)
            small = True
            if m:
                try:
                    v = [float(t) for t in m.group(1).split()]
                    if len(v) == 4:
                        small = abs((v[2] - v[0]) * (v[3] - v[1])) < 0.30 * page_area
                except Exception:
                    small = True
            nested = bool(DOOP.search(stream))
            if small and not nested:
                doc.update_stream(x, b''); n_blank += 1
            else:
                new = excise_artifact(stream)
                if new != stream:
                    doc.update_stream(x, new); n_excise += 1
        except Exception:
            pr('     !! xref %s 失败 %s' % (x, traceback.format_exc().splitlines()[-1]))
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    doc.save(dst, garbage=4, deflate=True, clean=True)
    doc.close()
    return n_ann, n_blank, n_excise, len(targets)

def render_check(src, dst, dpi=50):
    """返回 (最大单块改动占比, 描述)。把有差异的行聚成块，逐块报告面积与 y 范围。"""
    a = fitz.open(src); b = fitz.open(dst)
    worst = 0.0; text = ''
    n = min(a.page_count, b.page_count)
    step = max(1, n // 6)
    for pno in range(0, n, step):
        pa = a[pno].get_pixmap(dpi=dpi); pb = b[pno].get_pixmap(dpi=dpi)
        ha, wa = pa.height, pa.width
        if (ha, wa) != (pb.height, pb.width):
            a.close(); b.close(); return 1.0, '页面尺寸变了'
        A = np.frombuffer(pa.samples, dtype=np.uint8).reshape(ha, wa, pa.n)
        B = np.frombuffer(pb.samples, dtype=np.uint8).reshape(ha, wa, pb.n)
        d = (np.abs(A.astype(np.int16) - B.astype(np.int16)).max(axis=2) > 24)
        if d.mean() <= 0.0001: continue
        rows = np.where(d.any(axis=1))[0]
        # 聚块：相邻行间隔 > 4px 视为新块
        blocks = []; s0 = rows[0]; prev = rows[0]
        for r in rows[1:]:
            if r - prev > 4:
                blocks.append((s0, prev)); s0 = r
            prev = r
        blocks.append((s0, prev))
        parts = []
        for (y0, y1) in blocks:
            sub = d[y0:y1 + 1]
            parts.append('y%.0f%%~%.0f%%(%.2f%%)' % (y0 / ha * 100, y1 / ha * 100, sub.mean() * 100))
            if (y1 - y0) / ha > worst: worst = (y1 - y0) / ha
        text += '第%d页 ' % (pno + 1) + ' '.join(parts) + '; '
    a.close(); b.close()
    return worst, text[:220]

def main():
    only = sys.argv[1] if len(sys.argv) > 1 else None
    roots = SRC_ROOTS or discover()
    pr('本次处理目录：%s' % roots)
    done = skip = 0
    for root in roots:
        if only and only != 'all' and only not in root: continue
        for dp, dn, fn in os.walk(root):
            for f in sorted(fn):
                if not f.lower().endswith('.pdf'): continue
                src = os.path.join(dp, f)
                rel = os.path.relpath(src, '2026')
                dst = os.path.join(DST_ROOT, rel)
                if os.path.exists(dst) and os.path.getmtime(dst) > os.path.getmtime(src):
                    skip += 1; continue
                try:
                    na, nb, ne, nt = clean(src, dst)
                except Exception:
                    pr('!! 失败 %s\n%s' % (src, traceback.format_exc())); continue
                worst, desc = render_check(src, dst)
                A = fitz.open(src); B = fitz.open(dst)
                probe = [p for p in (5, 20, 50) if p < A.page_count]
                removed = set()
                for p in probe:
                    removed |= (set(tail_text(A, p)) - set(tail_text(B, p)))
                A.close(); B.close()
                flag = ''
                if worst > 0.15: flag += '  <<< 有大块改动，需人工确认'
                pr('%-50s 注释%-4d 置空%-4d 挖块%-4d | WM对象%-4d'
                   % (rel.replace('\\', '/'), na, nb, ne, nt))
                pr('        改动区域 %s%s' % (desc, flag))
                pr('        页脚已移除 %s' % (sorted(removed)[:5],))
                done += 1
    pr('== 完成 %d 本，跳过已最新 %d 本' % (done, skip))

try:
    main()
except Exception:
    pr(traceback.format_exc())
LOG.close()
