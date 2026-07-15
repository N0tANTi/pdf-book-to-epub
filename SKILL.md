---
name: pdf-book-to-epub
description: 把扫描版 PDF 书籍转换为高质量 Markdown 和 EPUB。流程为 MinerU API 识别 -> 脚本预处理 -> Agent 按规则逐块结构校对 -> 对图核查疑点 -> Pandoc 导出 EPUB。当用户要求转换 PDF 书籍、修复 OCR 结果排版、或提到"转 md / 转 epub / 电子书"时使用本 skill。
---

# PDF 书籍 → Markdown → EPUB

## 总流程

```
step1(脚本,MinerU API) -> step2(脚本,确定性清洗) -> step3(你自己,结构校对)
    -> step4(你自己,对图核查) -> step5(pandoc,出EPUB)
```

工作目录约定为 `work/<书名>/`。依赖：`pip install requests pypdf pymupdf`，系统需有 pandoc。

## Step 1 — MinerU 识别

需要环境变量 `MINERU_API_TOKEN`（用户在 mineru.net API 管理页创建）。
若未设置，提示用户设置，**不要**让用户把 token 贴进对话。

```bash
python scripts/step1_mineru_ocr.py 书.pdf --out work/书名 --lang ch
```

- 超过 190 页自动分卷（API 限制 200 页/文件，1000 页/天高优先级额度）
- 产出 `raw.md`、`content_list.json`、`images/`
- **content_list.json 必须保留**：MinerU 常把页底脚注归为"废弃块"排除在
  Markdown 外，脚注正文只能从这份 JSON 里找回

## Step 2 — 确定性预处理

```bash
python scripts/step2_preprocess.py work/书名            # MinerU 输出
python scripts/step2_preprocess.py work/书名 --fix-cjk-spaces   # ABBYY 输出才加此项
```

做的事：删页码/重复页眉、合并跨页断段、把 `$^{[1]}$` 归一为顺序编号
`[^fn1]...`、从 content_list.json 抢救脚注到 `footnotes_recovered.md`、切块。

**跑完必须做两件事**：
1. 打开 `preprocess_report.txt`，向用户展示被删除的重复行，确认无误伤
2. 检查抢救到的脚注条数；若为 0 且正文里有 `[^fn]` 标记，警告用户脚注
   可能彻底丢失，需要用 render_page.py 从原 PDF 补录

## Step 3 — 结构校对（由你逐块完成，不调用任何外部接口）

先读规则文件（`rules/<书名>.md`，不存在则复制 `references/规则模板.md`
让用户填写，或你抽查 3 个 chunk 与原书 PDF 对照后起草再请用户确认）。

然后对 `chunks/chunk_*.md` **逐块**处理，每块：

1. 读入 chunk，按规则执行且**仅执行**以下操作：
   - 按标题映射表统一 `#` 层级
   - 合并/拆分被切错的段落
   - 将 `[^fnN]` 与 `footnotes_recovered.md` 中对应页的脚注配对，
     把脚注正文以 `[^fnN]: 内容` 形式追加到该块末尾
   - 删除残留页眉、水印行、CIP 版权页等规则中指明的杂质
   - 修复列表、引文块、加粗等 Markdown 语法
2. **铁律（违反即整块作废）**：
   - 禁止改写、增删、润色任何正文字词——即使你确信是 OCR 错字
   - 禁止翻译、调整语序、"修正"语病
   - 疑似 OCR 错误：保持原样，记入 `work/<书名>/suspects.md`，
     格式：`chunk_0007 | 原文片段 | 怀疑原因 | 估计页码`
3. 写入 `proofread/chunk_*.md`，然后**必须**运行护栏自检：
   ```bash
   python scripts/check_guard.py chunks/chunk_0007.md proofread/chunk_0007.md
   ```
   REJECTED 则重做该块。护栏检查正文量变化（±12%）和脚注标记完整性。
4. 每 10 块向用户汇报一次进度和 suspects 数量。

全部完成后合并：`cat proofread/chunk_*.md > work/<书名>/final.md`
（按文件名顺序，确认 shell 展开顺序正确，或用 python 拼接）。

## Step 4 — 对图核查（异常触发式，只查 suspects）

对 `suspects.md` 里的每一条：

```bash
python scripts/render_page.py 原书.pdf <估计页码>
```

然后你**直接查看**生成的 `page_images/pXXXX.png`，对照原书图像确认：
- 确为 OCR 错误 -> 在 final.md 中修正，并在 suspects.md 标注"已修正"
- 原文如此 -> 标注"原文如此"
- 图像也无法辨认 -> 标注"存疑"，留给用户裁决

不要全书对图，成本应正比于错误密度而不是页数。

## Step 4.5 — 标题树审查（导出前必做，目录质量取决于这一步）

```bash
grep -n '^#' work/书名/final.md
```

把标题树打印出来，对照原书目录页逐条检查：

- [ ] 前置页已删除：书名页、CIP 版权页、编委会名单不应出现在标题树里
- [ ] 分节符不是标题：原书章内的 `*` / `＊＊＊` 分隔符必须写成 `---`
  （水平线），写成 `# *` 会变成一个叫"*"的章
- [ ] 题词/引语不是标题：章首的短句题词应为 `>` 引用块
- [ ] 层级统一：所有"第X章"必须同级（建议 H1），前言/总序/结论/参考文献
  与章同级
- [ ] **标题错字核查**：护栏只保护正文，标题是校对中允许改动的对象，
  因此标题里的 OCR 错字（如"刍民"/"初民"形近误认）不会被护栏拦截——
  对标题树里每个可疑标题用 render_page.py 对图确认
- [ ] 原书目录页本身已删除（EPUB 目录由 pandoc 生成，保留会重复）

## Step 5 — 导出 EPUB

```bash
pandoc work/书名/final.md -o 书名.epub \
  --metadata title="书名" --metadata author="作者" --metadata lang=zh-CN \
  --toc --toc-depth=3 --split-level=2 --resource-path=work/书名

# 必跑的后处理：注入脚注可见编号（pandoc 的 epub3 脚注是无编号的 aside，
# 微信读书/多看/Kindle 等不支持弹窗脚注的阅读器会显示为无序号段落堆）
# 同时可设封面、兜底清理漏网的分节符标题
python scripts/step5_fix_epub.py 书名.epub 书名_final.epub --cover file0.jpg
```

脚注导出验收（必须做）：

- 正文中的每个脚注引用必须仍在原段落内；不能因为脚注标记而拆出新段落或强制换行。
- 检查并清除紧跟脚注引用的残留 `$`、`?`、替换方框等乱码符号；仅删除紧贴引用链接的残留符号，不能误删正文中的数学内容。
- 脚注条目只显示一套全书编号。去掉条目开头遗留的 `①/②/...` 等原页码序号。
- 脚注可见编号本身必须是返回正文对应引用的链接（`href="#fnrefN"`）；不要额外添加箭头或其他符号，因为部分阅读器会将缺字形渲染成 `?`。
- 打包前在 EPUB XHTML 中抽查：脚注引用数、返回链接数相等；`</a>$` 和脚注编号后紧跟的圈号均为 0。

导出后用 `python -c "import zipfile; zipfile.ZipFile('书名_final.epub').testzip()"`
做完整性检查，并提醒用户在阅读器里抽查：目录、脚注编号与跳转、封面。

## 首次处理一本新书时

不要直接跑整本。先抽一章（选脚注密集的）走完整流程，把发现的问题
写进规则文件，与用户确认规则后再跑全书。抽章方法见
`references/规则模板.md` 末尾。

## 常见坑

- MinerU 脚注在 content_list.json 而不在 md：不要以为书没有脚注
- 原书脚注每页从 [1] 重新编号：配对必须结合页码，不能只看编号
- 扫描 App 水印（如"某某系统"字样）会被识别为正文：加进规则的删除项
- 目录页的"第X章 …… 页码"行不要当成标题：EPUB 由 pandoc --toc 自动生成
- 每天 1000 页 MinerU 高优先级额度：多本书要排期
- pandoc 的 EPUB3 脚注天生无可见编号：必须跑 step5_fix_epub.py 注入
- 标题不在正文护栏保护范围内：标题错字要在 Step 4.5 单独对图核查
- 章内 `*` 分节符和章首题词是标题误判的高发区：Step 4.5 清单逐项过
