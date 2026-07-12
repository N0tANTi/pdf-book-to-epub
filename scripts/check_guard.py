#!/usr/bin/env python3
"""
校对护栏：Agent 每改完一个 chunk 必须跑这个脚本自检。

用法:
    python check_guard.py chunks/chunk_0001.md proofread/chunk_0001.md

检查:
    1. 正文字符量变化 <= 12%（剥离 Markdown 语法后比较）
    2. 脚注标记 [^fnN] 一个都不能丢
    3. 汉字集合差异抽样展示（帮助发现"顺手改字"）

退出码 0 = 通过；非 0 = 拒绝，Agent 必须重做该块。
"""
import re
import sys
from pathlib import Path


def strip_md(t: str) -> str:
    t = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", t)
    t = re.sub(r"\[\^fn\d+\]", "", t)
    return re.sub(r"[#>\s|*_\-\[\]()!`~]", "", t)


def main():
    orig_p, edit_p = Path(sys.argv[1]), Path(sys.argv[2])
    orig, edit = orig_p.read_text(encoding="utf-8"), edit_p.read_text(encoding="utf-8")

    o, e = strip_md(orig), strip_md(edit)
    ratio = abs(len(e) - len(o)) / max(len(o), 1)
    print(f"正文量: {len(o)} -> {len(e)} (变化 {ratio:.1%})")
    ok = True
    if ratio > 0.12:
        print("FAIL: 正文量变化超过 12%，疑似删改正文"); ok = False

    fn_o = set(re.findall(r"\[\^fn\d+\]", orig))
    fn_e = set(re.findall(r"\[\^fn\d+\]", edit))
    lost = fn_o - fn_e
    if lost:
        print(f"FAIL: 丢失脚注标记 {sorted(lost)}"); ok = False

    diff_chars = set(re.findall(r"[\u4e00-\u9fff]", o)) ^ set(re.findall(r"[\u4e00-\u9fff]", e))
    if diff_chars:
        print(f"注意: 汉字集合差异 {len(diff_chars)} 个: {''.join(sorted(diff_chars))[:50]}")
        print("（差异应仅来自删除的页眉残留等，如出现正文用字请检查是否误改）")

    print("PASS" if ok else "REJECTED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
