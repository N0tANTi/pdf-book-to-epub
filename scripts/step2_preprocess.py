#!/usr/bin/env python3
"""
Step 2: 确定性预处理（针对 MinerU 输出调优）

用法:
    python step2_preprocess.py <工作目录> [--fix-cjk-spaces] [--header-pattern 正则]

输入:  {work}/raw.md（必需）+ {work}/content_list.json（可选，用于找回脚注）
输出:  {work}/clean.md
       {work}/footnotes_recovered.md   （从 content_list.json 抢救回的脚注，带页码）
       {work}/chunks/chunk_*.md
       {work}/preprocess_report.txt

处理内容（全部确定性，宁可漏做不可做错）:
    1. 删除纯页码行；统计并删除全书重复 >=8 次的短行（页眉页脚）
    2. 行级断行合并（ABBYY 式逐行输出）
    3. 段落级跨页合并（MinerU 式：段末无终止标点 + 下段以续接字开头 -> 合并）
       例：'指称一个问' + '题，而这个问题…' -> 合并
    4. 脚注标记归一：$^{[1]}$ / $^{1}$ -> 顺序编号 [^fn1] [^fn2] ...
       （原书每页从[1]重编号，无法机械配对，配对交给 step3 的 Agent）
    5. 从 content_list.json 找回被 MinerU 排除的脚注正文块 -> footnotes_recovered.md
    6. --fix-cjk-spaces: 删除汉字之间的孤立空格（ABBYY 常见病，MinerU 输出勿开）
"""
import argparse
import json
import re
from collections import Counter
from pathlib import Path

CJK = r"\u4e00-\u9fff"
END_PUNCT = "。！？…”』」）)!?:：;；"
HEADING = re.compile(r"^\s{0,3}#{1,6}\s")
LIST_ITEM = re.compile(r"^\s*([-*+]|\d+[.、)）]|[①-⑳]|\[\d+\])\s*")
PAGE_NUM = re.compile(r"^\s*(?:[-–—·\s]*\d{1,4}[-–—·\s]*|第\s*\d+\s*[页頁])\s*$")
IMG_LINE = re.compile(r"^\s*!\[")
SUP_MARK = re.compile(r"\s*\$\^\{?\[?(\d+)\]?\}?\$")  # $^{[1]}$ / $^{1}$ / $^[1]$


def detect_repeated_lines(lines, min_repeat=8):
    counter = Counter(
        ln.strip() for ln in lines
        if 0 < len(ln.strip()) <= 30 and not HEADING.match(ln) and not IMG_LINE.match(ln)
    )
    return {t for t, n in counter.items() if n >= min_repeat}


def is_plain_text(block: str) -> bool:
    s = block.lstrip()
    return bool(s) and not (HEADING.match(s) or IMG_LINE.match(s)
                            or s.startswith((">", "|", "$$", "```")))


TOC_ENTRY = re.compile(r"[…⋯·.]{2,}\s*\d+\s*$")  # 目录行："第一章 献祭 …… 1"


def para_should_merge(prev: str, nxt: str) -> bool:
    """跨页断段判定：上段末尾无终止标点，下段是普通正文且以小写/汉字续接。

    上段必须 >= 40 字符：被页边界切断的段落必然填满了上一页，
    而书名页短行（"周莽译"）、目录条目等虽无标点但很短，不应合并。
    """
    if not is_plain_text(prev) or not is_plain_text(nxt):
        return False
    p = prev.rstrip()
    n = nxt.lstrip()
    if len(p) < 40 or not p or p[-1] in END_PUNCT:
        return False
    if TOC_ENTRY.search(p) or TOC_ENTRY.search(n):
        return False
    return bool(re.match(f"[{CJK}a-z，、]", n))


def join_para(a: str, b: str) -> str:
    a, b = a.rstrip(), b.lstrip()
    if re.search(r"[A-Za-z]-$", a) and re.match(r"[a-z]", b):
        return a[:-1] + b
    if re.search(f"[{CJK}]$", a):
        return a + b
    return a + " " + b


def recover_footnotes(work: Path) -> int:
    """从 content_list.json 抢救脚注/被丢弃块，输出 footnotes_recovered.md。"""
    cl_path = work / "content_list.json"
    if not cl_path.exists():
        return -1
    blocks = json.loads(cl_path.read_text(encoding="utf-8"))
    notes = []
    for b in blocks:
        btype = str(b.get("type", "")).lower()
        text = (b.get("text") or "").strip()
        if not text:
            continue
        looks_like_note = bool(re.match(r"^\[?\d+\]?\s|^[①-⑳]", text))
        if "footnote" in btype or "discarded" in btype or (btype == "text" and False) \
           or (looks_like_note and "abandon" in btype):
            notes.append((b.get("page_idx", -1), text))
        elif looks_like_note and btype in ("footnote", "discarded", "abandon"):
            notes.append((b.get("page_idx", -1), text))
    # 宽松兜底：所有 type 含 footnote/discard/abandon 的块
    if not notes:
        for b in blocks:
            btype = str(b.get("type", "")).lower()
            text = (b.get("text") or "").strip()
            if text and any(k in btype for k in ("foot", "discard", "abandon")):
                notes.append((b.get("page_idx", -1), text))
    if notes:
        notes.sort(key=lambda x: x[0])
        out = ["# 从 content_list.json 抢救的脚注（含页码，供 Agent 配对）\n"]
        out += [f"[页 {p}] {t}" for p, t in notes]
        (work / "footnotes_recovered.md").write_text("\n\n".join(out), encoding="utf-8")
    return len(notes)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("work", type=Path)
    ap.add_argument("--fix-cjk-spaces", action="store_true",
                    help="删除汉字间空格（ABBYY 输出用，MinerU 勿开）")
    ap.add_argument("--header-pattern", default=None)
    ap.add_argument("--chunk-chars", type=int, default=6000)
    args = ap.parse_args()

    raw = (args.work / "raw.md").read_text(encoding="utf-8").replace("\r\n", "\n")
    report = []

    # --- 脚注标记归一（先做，避免后续处理破坏 $..$）---
    fn_counter = [0]
    def _sub(m):
        fn_counter[0] += 1
        return f"[^fn{fn_counter[0]}]"
    raw = SUP_MARK.sub(_sub, raw)
    report.append(f"归一脚注标记: {fn_counter[0]} 处 -> [^fn1..fn{fn_counter[0]}]")

    if args.fix_cjk_spaces:
        before = raw
        raw = re.sub(f"(?<=[{CJK}]) +(?=[{CJK}])", "", raw)
        report.append(f"删除汉字间空格: {len(before) - len(raw)} 个")

    lines = raw.split("\n")
    repeated = detect_repeated_lines(lines)
    if repeated:
        report.append("判定为页眉/页脚并删除的重复行:")
        report.extend(f"  {t!r}" for t in sorted(repeated))
    extra = re.compile(args.header_pattern) if args.header_pattern else None

    kept, removed_pages = [], 0
    for ln in lines:
        s = ln.strip()
        if PAGE_NUM.match(ln):
            removed_pages += 1
            continue
        if s in repeated or (extra and extra.search(s)):
            continue
        kept.append(ln)
    report.append(f"删除纯页码行: {removed_pages} 行")

    # --- 行级合并（ABBYY 式；MinerU 输出通常一段一行，几乎不触发）---
    merged_lines, line_merges = [], 0
    for ln in kept:
        if merged_lines and is_plain_text(merged_lines[-1]) and is_plain_text(ln) \
           and merged_lines[-1].rstrip() and merged_lines[-1].rstrip()[-1] not in END_PUNCT \
           and ln.strip():
            # 仅当两行都是普通文本且上一行"未说完"才在行级合并
            merged_lines[-1] = join_para(merged_lines[-1], ln)
            line_merges += 1
        else:
            merged_lines.append(ln)
    text = "\n".join(merged_lines)
    report.append(f"行级断行合并: {line_merges} 次")

    # --- 段落级跨页合并 ---
    paras = re.split(r"\n{2,}", text)
    out_paras, para_merges = [], 0
    for p in paras:
        if out_paras and para_should_merge(out_paras[-1], p):
            out_paras[-1] = join_para(out_paras[-1], p)
            para_merges += 1
        else:
            out_paras.append(p)
    report.append(f"段落级跨页合并: {para_merges} 次")
    text = "\n\n".join(p for p in out_paras if p.strip()) + "\n"

    (args.work / "clean.md").write_text(text, encoding="utf-8")

    n_notes = recover_footnotes(args.work)
    if n_notes == -1:
        report.append("!! 未找到 content_list.json —— 无法抢救脚注。"
                      "请保留 MinerU zip 里的 *content_list.json 放入工作目录")
    else:
        report.append(f"从 content_list.json 抢救脚注块: {n_notes} 条"
                      + ("" if n_notes else " !! 为 0，可能需要检查 middle.json 或重新解析"))

    # --- 切块 ---
    chunks_dir = args.work / "chunks"
    chunks_dir.mkdir(exist_ok=True)
    for old in chunks_dir.glob("chunk_*.md"):
        old.unlink()
    blocks, cur, cur_len = [], [], 0
    for ln in text.split("\n"):
        if HEADING.match(ln) and cur_len > args.chunk_chars * 0.5:
            blocks.append("\n".join(cur)); cur, cur_len = [], 0
        cur.append(ln); cur_len += len(ln)
        if cur_len > args.chunk_chars * 1.5:
            blocks.append("\n".join(cur)); cur, cur_len = [], 0
    if cur:
        blocks.append("\n".join(cur))
    for i, b in enumerate(blocks, 1):
        (chunks_dir / f"chunk_{i:04d}.md").write_text(b, encoding="utf-8")
    report.append(f"切分为 {len(blocks)} 块 -> {chunks_dir}/")

    (args.work / "preprocess_report.txt").write_text("\n".join(report), encoding="utf-8")
    print("\n".join(report))


if __name__ == "__main__":
    main()
