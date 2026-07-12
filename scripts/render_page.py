#!/usr/bin/env python3
"""
把 PDF 指定页渲染成 PNG，供 Agent 直接查看核对疑似 OCR 错误。

用法:
    python render_page.py 原书.pdf 137            # 单页（1-indexed）
    python render_page.py 原书.pdf 137 140        # 页范围
输出: ./page_images/p0137.png ...
依赖: pip install pymupdf
"""
import sys
from pathlib import Path

import fitz  # pymupdf


def main():
    pdf = Path(sys.argv[1])
    start = int(sys.argv[2])
    end = int(sys.argv[3]) if len(sys.argv) > 3 else start
    out = Path("page_images")
    out.mkdir(exist_ok=True)
    doc = fitz.open(pdf)
    for p in range(start, end + 1):
        page = doc[p - 1]
        pix = page.get_pixmap(dpi=200)
        path = out / f"p{p:04d}.png"
        pix.save(path)
        print(path)


if __name__ == "__main__":
    main()
