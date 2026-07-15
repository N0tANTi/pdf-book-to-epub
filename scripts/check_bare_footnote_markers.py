#!/usr/bin/env python3
"""Find likely OCR-lost footnote markers left as plain digits in Markdown."""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("markdown", type=Path)
    parser.add_argument("--allow", action="append", default=[], help="Regex for a reviewed ordinary-number context to ignore (repeatable).")
    args = parser.parse_args()

    text = args.markdown.read_text(encoding="utf-8")
    text = re.sub(r"^\[\^fn\d+\]:.*$", "", text, flags=re.M)
    candidate = re.compile(r"(?<=[。！？…）”’])([1-9]\d?)(?![\d.])")
    allowed = [re.compile(pattern) for pattern in args.allow]
    found = []

    for match in candidate.finditer(text):
        start, end = max(0, match.start() - 90), min(len(text), match.end() + 90)
        excerpt = re.sub(r"\s+", " ", text[start:end])
        following = text[match.end():match.end() + 3]
        if following.startswith(("世纪", "年后", "年间", "年内")) or any(pattern.search(excerpt) for pattern in allowed):
            continue
        line = text.count("\n", 0, match.start()) + 1
        found.append((line, match.group(1), excerpt))

    for line, number, excerpt in found:
        print(f"{line}\t{number}\t{excerpt}")
    print(f"UNREVIEWED_BARE_FOOTNOTE_CANDIDATES={len(found)}")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
