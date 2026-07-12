# pdf-book-to-epub

一个 [Agent Skill](https://docs.claude.com/en/docs/claude-code/skills)，把**扫描版 PDF 书籍**转换为排版正确、脚注完整的 Markdown 和 EPUB，适合放进电子阅读器阅读。

适用于 Claude Code 等支持 Skills 的 AI 编程助手。

## 设计思路

核心原则是**让每一层只做它擅长且不会犯错的事**：

```
MinerU API          确定性脚本            Agent 逐块校对         Agent 对图核查      pandoc
(识别+版面结构) --> (页码/页眉/断段/     --> (标题层级/脚注配对/  --> (只核查疑点，  --> EPUB + 后处理
                    脚注抢救，纯正则)        杂质清理，禁止改写正文)   成本∝错误密度)     (脚注编号注入)
```

- **识别层用专用 OCR 模型**（MinerU）而非通用 VLM 逐页看图：便宜、快、
  不会产生"幻觉式篡改"（把认不清的字脑补成通顺的错词）
- **确定性任务交给正则**：删页码、合并跨页断段这类活不浪费 LLM token，
  也不引入随机性
- **Agent 只做结构编辑，禁止改写正文**：每块改完必须通过护栏脚本
  （字符量比对 ±12% + 脚注标记完整性），不通过整块作废
- **对图核查是异常触发式的**：只把疑点所在页渲染成图核对，
  成本正比于错误密度而不是页数

## 安装

```bash
git clone https://github.com/<你的用户名>/pdf-book-to-epub.git
cp -r pdf-book-to-epub ~/.claude/skills/
pip install requests pypdf pymupdf
# 另需 pandoc: https://pandoc.org/installing.html
```

需要一个 [MinerU](https://mineru.net) 免费 API token（每天 1000 页高优先级额度），
设置为环境变量 `MINERU_API_TOKEN`。**不要把 token 写进任何文件或对话。**

## 使用

在 Claude Code 中直接说：

> 帮我把 某某书.pdf 转成 epub

Agent 会按 SKILL.md 的流程走：识别 → 预处理 → 建立本书专属规则文件 →
逐块校对 → 对图核查疑点 → 导出。**建议第一次先让它只处理一章**（选脚注
密集的），确认规则文件后再跑全书。

## 目录结构

```
SKILL.md                      Agent 工作流程（含校对铁律与护栏机制）
scripts/
  step1_mineru_ocr.py         MinerU API 调用，自动分卷（>190页）与结果合并
  step2_preprocess.py         确定性清洗：页眉页脚/跨页断段/脚注标记归一/脚注抢救
  check_guard.py              校对护栏：Agent 每改一块必须通过的自检
  render_page.py              渲染 PDF 指定页为 PNG，供 Agent 对图核查
  step5_fix_epub.py           EPUB 后处理：脚注编号注入/封面/分节符清理
references/
  规则模板.md                  每本书专属校对规则的模板
```

## 已知限制

- MinerU 常把页底脚注归类为"废弃块"排除在 Markdown 外，本 skill 会从
  content_list.json 抢救，但请务必保留解析结果 zip 中的 JSON 文件
- 原书脚注通常每页从 [1] 重新编号，配对依赖页码信息，由 Agent 完成
- 标题不在正文护栏的保护范围内，标题错字需在导出前的标题树审查中对图确认
- 竖排/繁体古籍未经充分测试

## License

MIT
