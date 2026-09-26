# 比对脚本

把两版教材（2024 版 / 2026 版）逐字比对，输出左右对照的标注 PDF，并导出结构化 JSON。
本目录是完整可复现的脚本集，纯 Python（PyMuPDF + numpy + requests/PySocks）。

---

## 依赖

```bash
pip install pymupdf numpy requests pysocks
```

## 期望的数据目录

```
<项目根>/
├─ 2024/
│   ├─ 1-语文/*.pdf             ← 旧版，按科目分目录
│   ├─ 2-数学/*.pdf
│   ├─ 3-英语/*.pdf  …
│   └─ 2-数学/人教版/*.pdf       ← 同科目下的其他版本放子目录
├─ 2026/                        ← 新版【带水印原件】；若拿到的 PDF 没水印可跳过 dewm.py
│   └─ <科目>/<出版社>/*.pdf
├─ 2026_去水印/                 ← 新版【净版】，比对用这一份
│   └─ <科目>/<出版社>/*.pdf
├─ 对比结果/                     ← 输出：<科目·版本>/修改页对照_<科目·版本>.pdf
└─ _preview/                    ← 中间产物与日志
    ├─ items/<taskkey>/<册>.json   ← 逐册差异（可复用，重跑时自动跳过）
    ├─ jobs/<key>__<册>.log        ← 每册子进程日志
    ├─ runjobs_log.txt             ← 调度日志
    └─ audit/<key>.txt             ← 逐组审计报告
```

`pipe2.py` 顶部的 `TASKS` 配置表把「科目 → 旧版目录 / 新版目录 / 书名前缀 / 版本过滤」串起来，改科目只改这张表即可：

```python
dict(key='D化学苏教', label='化学·苏教版', old='2024/5-化学',
     new='2026_去水印/化学/苏教版', words=['化学'])
# old_filter / new_filter 是可选的正则，用来在目录里筛出特定版本
#   例：数学人教A版的 old_filter='（A版）'
```

---

## 流程

```bash
# 0) 可选：新版 PDF 先去水印（2026/ → 2026_去水印/）
py scripts/dewm.py                    # 自动发现 2026/ 下所有含 PDF 的目录
py scripts/dewm.py 数学/人教A版        # 只处理某一个子目录

# 1) 看配对情况（输出在 _preview/runjobs_log.txt，不打印到终端）
py scripts/runjobs.py status

# 2) 逐册算差异（务必后台跑；68 册 / 16 核 12 并发约 22 分钟）
py scripts/runjobs.py diff 12
#   单册调试：py scripts/pipe2.py one D化学苏教 "必修 第一册"

# 3) 生成单册对照页 + 按科目合并（约 5 分钟）
py scripts/runjobs.py build 12

# 4) 逐组审计 + 版面核查
py scripts/audit_run.py 12
py scripts/mkdiag3.py

# 5) 导出结构化 JSON
py scripts/export_json.py gh-upload/json

# 6) 生成总览报告
py scripts/gen_overview.py
```

Windows 上跑长任务要脱离终端，否则约 10 分钟会被杀、日志半截：

```powershell
Start-Process -FilePath "py" -ArgumentList "scripts/runjobs.py","diff","12" -WindowStyle Hidden
```

---

## 脚本说明

| 脚本 | 作用 |
| --- | --- |
| `pipe2.py` | **核心**。`one`（算一册差异）/ `buildone`（生成一册对照页）/ `merge`（按科目合并）/ `list` |
| `runjobs.py` | 并行调度：`diff [并发]` / `build [并发]` / `status`。**按册拆独立子进程**——`difflib` 是纯 Python、占 GIL，多线程没用；16 核跑 12 并发 |
| `dewm.py` | 去 Acrobat 水印（三类形态，见下） |
| `export_json.py` | 导出 `index.json` / `<科目>.json` / `all.json` |
| `audit2.py` / `audit_run.py` | 逐改动组审计（左右页文本相似度、页码偏移、条目是否成句） |
| `mkdiag3.py` | 版面核查：编号越界 / 编号压框 / 左右栏空白 / 对照页某侧无标记 |
| `verifyfast.py` | 抽样几何核查（每 4 页取 1） |
| `gen_overview.py` | 生成 `对比结果/改版对照总览.md` |
| `copynew.py` / `stage_gh.py` | 把新科目并入 `2026/`；把成品同步到上传目录 |
| `gh.py` | GitHub API 小工具（`whoami` / `repos` / `create`），从 Windows 凭据管理器取令牌 |
| `push_gh.py` | 提交并推送（令牌只写进仓库本地 git 配置，推完删除并校验无残留） |

---

## 算法要点

1. **逐字对齐**：整本书字符按页串起来（丢空白，书眉页码单独掩码），`difflib.SequenceMatcher` 做字符级比对。**不做按页对齐**——新版常有整段增删，页码会错位。
2. **掩码书眉页码** `mask_positions()`：某 y（3pt 分桶）在 >35% 页面都有文字 → 判为书眉/页码。**两侧取掩码位置并集**，否则两版书眉偏 2~3pt 会造出成片假差异；连续掩码**折叠成一个字符**。
3. **图/表内部文字过滤**（最关键，否则左右会配错）——新版常把整张图从位图改成矢量重排（例：元素周期表），这类文字抽取顺序与阅读顺序不一致，四道过滤：
   1. **按册自适应字号阈值** `doc_thr()` = 正文体字号（字符数加权众数）× 0.78，上限 9.6pt；
   2. **行内乱序短行**：同行字符 x 回跳且总字数 ≤16 → 整行丢（限定短行以免误伤数学公式行）；
   3. **标签堆** `is_label_soup()`：中文几乎都是零散单字（run<4 占比 ≥50%）→ 判为表格标签；
   4. **句子⇄碎片**：一侧 ≥15 字有句读、另一侧 ≤10 字无句读 → 只保留句子那侧。
4. **伪差异剔除**：掩码后两侧都空 / 删除与新增文字完全相同（整段搬家）/ 组内字符集合净零 / 缺 ToUnicode 表抽出的乱码。
5. **插入删除点的位置参考页**：取插入点**向前最近的「真实字符」**（跳过掩码），在其右边缘画红色竖线；不要直接取后一个字符——插入点落在页边界会跳到下一页。
6. **矢量嵌入**：`page.show_pdf_page(rect, srcdoc, pageno)`，不要 `get_pixmap` + `insert_image`（栅格化会糊）。
7. **整篇新增/删除**：单侧 ≥800 字且跨 ≥3 页即认定。删除只出说明页、新增逐页附原文。

## 去水印的三类形态

| 形态 | 判定 | 处理 |
| --- | --- | --- |
| Watermark 注释 | `/Subtype/Watermark` | 删注释 |
| 自包含水印 Form | `/Private/Watermark`，BBox 远小于整页、内部无 `Do` | 整条流置空 |
| **页面内容外壳 Form** | BBox≈整页、内部有 `/FmN Do` | **只能挖掉** `/Artifact <</Subtype /Watermark>>BDC…EMC` 段（按 BDC/BMC/EMC 配平扫描）；置空会毁掉整页正文 |

验证方式：逐块报改动区域，正确结果只落在页眉 y1–3% 与页脚 y97–99% 两条带内；单块纵向占比 >15% 说明误删了正文。

## 审计注意

- **纯新增/纯删除的组，另一侧是「位置参考页」，相似度天然低，必须排除相似度判据**，否则会大面积误报。
- 版面核查里「某侧无标记」要先排除封面页（封面左右栏是图例文字，会被当成对照页）。
- 典型终态：编号越界 0、压框 0、栏空 0、对照页某侧无标记 0。
