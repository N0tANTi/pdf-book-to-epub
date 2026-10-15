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

## 注释方式：在首次制作样章 EPUB 前询问一次

书内数据的配对与校对完成后、第一次导出样章 EPUB 前，若用户尚未选择，询问：

> 这本书的注释希望用哪种方式？
> 1. **数字跳转注释**：正文显示数字编号，点击跳到章末注释，点击编号返回正文，适合需要通用跳转的阅读场景。
> 2. **微信读书弹窗注释（“注”字卡片）**：专门适配微信读书，正文显示“注”字图片，点击在当前页弹出注释内容，减少来回跳转。

- 把选择写入本书规则文件：`annotation_style: jump` 或 `annotation_style: weread-card`，并记录目标阅读器；样章、整书和修订沿用该选择。
- 如果用户已在对话中选定，或本书已有规则记录，直接沿用，不重复询问。用户明确改选时更新记录。
- 用户未答复时继续文字提取、脚注配对和校对；保持问题待答，正式 EPUB 导出前取得选择，不把沉默当作同意。只交付 Markdown 时无需询问 EPUB 的显示方式。
- 两种方式的注释原文与配对规则相同，保留 Markdown 脚注数据。只在导出阶段切换显示方式；本技能不替代翻译逐段核对。
- 微信读书方案使用已在本项目用户环境中验证的 B 式图片标记；它不是各阅读器通用的弹窗保证，具体客户端仍以样章实测为准。不要用不可点击的普通“注”字或未经验证的混合链接替代。

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
3. 对每本书先跑一次全文漏转标号扫描：
   ```bash
   python scripts/check_bare_footnote_markers.py work/书名/final.md
   ```
   命中的是“句末普通黑色数字”的**候选项**，不能批量删除。必须逐项对照
   `content_list.json` 的 `page_footnote` 和原 PDF 页图：有对应脚注的改为
   `[^fnN]` 并补全定义；确认是年份、页码等正文数字的才可用 `--allow` 留下，
   并在交付记录中说明理由。

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
- [ ] EPUB 导航层级必须以原书目录页为唯一准则：只保留原目录实际列出的篇、章、界槛等条目；正文中的“第一节／第二节／余论”等未列入原目录的小节不得进入侧栏导航
- [ ] 若 Pandoc 根据 `##` 自动生成了额外导航项，导出后必须同时重建 `EPUB/nav.xhtml` 与 `EPUB/toc.ncx`；不能只改其中一个，因为不同阅读器可能读取不同的目录索引

## Step 5 — 导出 EPUB

```bash
pandoc work/书名/final.md -o 书名.epub \
  --metadata title="书名" --metadata author="作者" --metadata lang=zh-CN \
  --toc --toc-depth=3 --split-level=2 --resource-path=work/书名

# 必跑的后处理：注入脚注可见编号（pandoc 的 epub3 脚注是无编号的 aside，
# 不识别相应弹窗标记的阅读器可能显示为无序号段落堆）
# 同时可设封面、兜底清理漏网的分节符标题
python scripts/step5_fix_epub.py 书名.epub 书名_final.epub --cover file0.jpg --note-style jump
# 若用户选择“微信读书弹窗注释”，改用：
python scripts/step5_fix_epub.py 书名.epub 书名_final.epub --cover file0.jpg --note-style weread-card
```

两种显示方式：`jump` 保留正文数字引用及章末跳转；`weread-card` 在通用修复后调用
`epub_note_style.py`，把正文引用替换为裸 `img.qqreader-footnote`，注释全文写入经 XML 转义的
`alt`，图片不再包裹跳转链接。图片资产由 `assets/note.png` 提供并注册进 OPF manifest。
原正文引用 ID、注释完整 XHTML 和章末编号返回链接均保留。该方案的弹窗为纯文字；
图片、复杂公式及富文本的完整版本仍在章末，不应声称弹窗保留所有富文本。
脚本为了兼容旧命令默认 `jump`；这不是助手在用户未选择时静默替用户决定的理由。

微信读书 Guide 兼容性：`step5_fix_epub.py` 会从正文 XHTML 中移除会被微信读书误解为 Guide 条目的
`epub:type="bodymatter"`、`noteref`、`footnotes`、`footnote` 等语义标记，同时删除旧 EPUB2 `<guide>`，避免出现一长串
`Pages / 1、2、3… / footnotes / fn1…`。数字跳转模式保留实际链接、可见编号和返回正文链接；微信读书弹窗模式保留引用 ID、注释完整内容和返回正文链接。脚本还会把可点击的“目录”页加入阅读顺序和侧栏目录。

脚注导出验收（必须做）：

- 正文中的每个脚注引用必须仍在原段落内；不能因为脚注标记而拆出新段落或强制换行。
- 检查并清除紧跟脚注引用的残留 `$`、`?`、替换方框等乱码符号；仅删除紧贴引用链接的残留符号，不能误删正文中的数学内容。
- 脚注条目只显示一套全书编号。去掉条目开头遗留的 `①/②/...` 等原页码序号。
- 脚注可见编号本身必须是返回正文对应引用的链接（`href="#fnrefN"`）；不要额外添加箭头或其他符号，因为部分阅读器会将缺字形渲染成 `?`。
- 打包前在 EPUB XHTML 中抽查：脚注引用数、返回链接数相等；`</a>$` 和脚注编号后紧跟的圈号均为 0。
- 微信读书弹窗模式另查：每个原引用对应一个未包裹链接的 `img.qqreader-footnote`，`alt` 非空且与对应注释全文一致（去掉编号和返回链接）；XML 转义后引号、`&`、多段文字均无截断；图标已登记在 manifest。图片引用数按原引用计，多个引用指向同一注释时不按唯一注释数误判。样章在微信读书中检查“点击注→弹出内容→关闭仍在原位置”，不要把 ZIP/XML 检查说成客户端验证。
- 对照原 PDF 抽查每章开头：正文中不能遗留紧贴引文句末的普通黑色 `1、2、3…`。这类数字若原书页底存在对应注释，必须恢复为 `[^fnN]` 并补齐脚注正文；若原书无对应注释，才可删除残留数字。
- **全文硬性验收**：导出前必须运行 `check_bare_footnote_markers.py`；除已记录的
  `--allow` 正文数字外，输出必须是 `UNREVIEWED_BARE_FOOTNOTE_CANDIDATES=0`。每一项
  修复都要同时核对“正文标号、脚注正文、原 PDF 页脚”三者，避免把正文数字误当脚注，
  也避免出现有黑色标号却没有脚注内容的孤儿引用。

导出后用 `python -c "import zipfile; zipfile.ZipFile('书名_final.epub').testzip()"`
做完整性检查，并提醒用户在阅读器里抽查：目录、脚注编号与跳转、封面。抽查目录时必须确认条目数和层级与原书目录页一致，且不含正文小节。

## 首次处理一本新书时

不要直接跑整本。先抽一章（选脚注密集的）走完整流程，把发现的问题
写进规则文件，与用户确认规则后再跑全书。抽章方法见
`references/规则模板.md` 末尾。

## 常见坑

- MinerU 脚注在 content_list.json 而不在 md：不要以为书没有脚注
- 原书脚注每页从 [1] 重新编号：配对必须结合页码，不能只看编号
- 扫描 App 水印（如"某某系统"字样）会被识别为正文：加进规则的删除项
- 目录页的"第X章 …… 页码"行不要当成标题；Pandoc 自动目录只能作为初稿，最终导航必须按原书目录页逐项复核，必要时重建 nav.xhtml 与 toc.ncx
- 每天 1000 页 MinerU 高优先级额度：多本书要排期
- pandoc 的 EPUB3 脚注天生无可见编号：必须跑 step5_fix_epub.py 注入
- 微信上传前必须跑 step5_fix_epub.py：否则微信读书可能将 Pandoc 的 bodymatter / footnote 语义标签误显示为 Guide 中的 Pages 和 footnotes 清单
- 标题不在正文护栏保护范围内：标题错字要在 Step 4.5 单独对图核查
- 章内 `*` 分节符和章首题词是标题误判的高发区：Step 4.5 清单逐项过
