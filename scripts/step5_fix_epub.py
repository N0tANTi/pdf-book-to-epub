#!/usr/bin/env python3
"""
Step 5.5: EPUB 后处理修复（pandoc 输出的通病 + 本书残留问题）

用法: python step5_fix_epub.py 输入.epub 输出.epub [--cover media里的文件名]

做的事:
  1. 给章末 <aside epub:type="footnote"> 注入可见编号 "N."（兼容不支持弹窗脚注的阅读器）
  2. <h2>*</h2> 之类的分节符标题 -> <hr/>，并从 nav.xhtml / toc.ncx 目录中移除对应条目
  3. 标题文本替换（--fix-title '错误=>正确'，可多次，用于修 OCR 错字标题）
  4. 指定标题降级为题词引用块（--epigraph '标题文本'，可多次）
  5. 从目录移除指定标题条目（--drop-toc '标题文本'，可多次；正文保留，只清目录）
  6. --cover 指定封面图（media/ 下文件名），写入 opf 的 cover 元数据
"""
import argparse
import re
import shutil
import sys
import zipfile
from pathlib import Path


def repack(src_dir: Path, out_path: Path):
    """mimetype 必须第一个且不压缩，否则不是合法 EPUB。"""
    with zipfile.ZipFile(out_path, "w") as zf:
        zf.write(src_dir / "mimetype", "mimetype", compress_type=zipfile.ZIP_STORED)
        for p in sorted(src_dir.rglob("*")):
            rel = p.relative_to(src_dir)
            if p.is_file() and str(rel) != "mimetype":
                zf.write(p, str(rel), compress_type=zipfile.ZIP_DEFLATED)


def clean_toc(root: Path, titles: set[str]):
    """从 nav.xhtml 和 toc.ncx 移除标题文本在 titles 中的条目。"""
    nav = root / "EPUB" / "nav.xhtml"
    if nav.exists():
        t = nav.read_text(encoding="utf-8")
        for title in titles:
            t = re.sub(
                rf"<li[^>]*>\s*<a [^>]*>{re.escape(title)}</a>\s*</li>\s*", "", t
            )
        nav.write_text(t, encoding="utf-8")
    ncx = root / "EPUB" / "toc.ncx"
    if ncx.exists():
        t = ncx.read_text(encoding="utf-8")
        for title in titles:
            t = re.sub(
                rf"<navPoint[^>]*>\s*<navLabel>\s*<text>{re.escape(title)}</text>.*?</navPoint>\s*",
                "", t, flags=re.S,
            )
        # navPoint playOrder 无需连续，阅读器普遍容忍；如需严格可重编号
        ncx.write_text(t, encoding="utf-8")


def make_weread_safe(root: Path):
    """Avoid WeRead turning EPUB semantic markup into a long Guide list."""
    removed = 0
    for xf in sorted((root / "EPUB" / "text").glob("*.xhtml")):
        text = xf.read_text(encoding="utf-8")
        text, count = re.subn(
            r'\s+epub:type="(?:frontmatter|titlepage|cover|bodymatter|noteref|footnotes|footnote)"',
            "", text,
        )
        removed += count
        xf.write_text(text, encoding="utf-8")

    nav = root / "EPUB" / "nav.xhtml"
    if nav.exists():
        text = nav.read_text(encoding="utf-8")
        toc_open = re.search(r'<nav\b[^>]*epub:type="toc"[^>]*>.*?<ol>', text, re.S)
        if toc_open and '>目录</a>' not in text:
            text = text[:toc_open.end()] + '\n        <li><a href="nav.xhtml">目录</a></li>' + text[toc_open.end():]
        nav.write_text(text, encoding="utf-8")

    ncx = root / "EPUB" / "toc.ncx"
    if ncx.exists():
        text = ncx.read_text(encoding="utf-8")
        if '<content src="nav.xhtml"/>' not in text:
            point = ('\n    <navPoint id="navPoint-toc" playOrder="1">\n'
                     '      <navLabel><text>目录</text></navLabel>\n'
                     '      <content src="nav.xhtml"/>\n'
                     '    </navPoint>')
            text = text.replace("<navMap>", "<navMap>" + point, 1)
            order = 0
            def renumber(_match):
                nonlocal order
                order += 1
                return f'playOrder="{order}"'
            text = re.sub(r'playOrder="\d+"', renumber, text)
        ncx.write_text(text, encoding="utf-8")

    opf = root / "EPUB" / "content.opf"
    if opf.exists():
        text = opf.read_text(encoding="utf-8")
        text = re.sub(r'\s*<guide>.*?</guide>\s*', "\n", text, flags=re.S)
        nav_item = re.search(r'<item\s+id="([^"]+)"[^>]*href="nav.xhtml"', text)
        if nav_item and not re.search(rf'<itemref\s+idref="{re.escape(nav_item.group(1))}"', text):
            text = re.sub(r'(<spine\b[^>]*>)', rf'\1\n    <itemref idref="{nav_item.group(1)}" linear="yes"/>', text, count=1)
        opf.write_text(text, encoding="utf-8")
    return removed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src", type=Path)
    ap.add_argument("dst", type=Path)
    ap.add_argument("--cover", default=None, help="media/ 下的封面文件名，如 file0.jpg")
    ap.add_argument("--fix-title", action="append", default=[],
                    help="标题替换，格式 '错=>对'，可多次")
    ap.add_argument("--epigraph", action="append", default=[],
                    help="降级为题词引用的标题文本，可多次")
    ap.add_argument("--drop-toc", action="append", default=[],
                    help="仅从目录移除的标题文本，可多次")
    args = ap.parse_args()

    tmp = Path("_epub_fix_tmp")
    if tmp.exists():
        shutil.rmtree(tmp)
    with zipfile.ZipFile(args.src) as zf:
        zf.extractall(tmp)

    text_dir = tmp / "EPUB" / "text"
    removed_toc_titles = set(args.drop_toc)
    n_fn = n_hr = n_epi = 0

    for xf in sorted(text_dir.glob("*.xhtml")):
        t = xf.read_text(encoding="utf-8")

        # 1. 脚注编号注入：编号本身是返回正文的链接。
        # Pandoc 的正文引用 id 为 fnrefN；不要额外插入箭头字符，
        # 否则部分阅读器会因字体缺字显示为问号或乱码。
        def _num(m):
            nonlocal n_fn
            n_fn += 1
            num = m.group(2)
            return (
                f'{m.group(1)}<p>'
                f'<a href="#fnref{num}" class="footnote-back" '
                f'role="doc-backlink"><b>{num}.</b></a> '
            )
        t = re.sub(
            r'(<aside [^>]*id="fn(\d+)"[^>]*>\s*)<p>(?!\s*<a\b[^>]*class="footnote-back")',
            _num, t,
        )

        # OCR/Markdown 公式标记经脚注替换后可能遗留一个闭合 $。
        # 只删除紧贴脚注引用链接的 $，避免误改正文中的数学符号。
        t = re.sub(
            r'(<a [^>]*class="footnote-ref"[^>]*>.*?</a>)\$', r'\1', t
        )

        # 有些扫描书的脚注正文仍以 ①、② 等原页码标记起首。
        # EPUB 已给出全书可跳转编号，保留两套编号既冗余又易混淆。
        t = re.sub(
            r'(<a [^>]*class="footnote-back"[^>]*><b>\d+\.</b></a>\s*)'
            r'[①②③④⑤⑥⑦⑧⑨⑩]', r'\1', t
        )

        # 2. 分节符标题 -> hr
        new_t, k = re.subn(r"<h[1-6][^>]*>\s*[*＊]{1,3}\s*</h[1-6]>", "<hr/>", t)
        if k:
            n_hr += k
            removed_toc_titles.add("*")
        t = new_t

        # 3. 标题错字修复
        for pair in args.fix_title:
            bad, good = pair.split("=>")
            t = t.replace(bad, good)

        # 4. 题词降级
        for epi in args.epigraph:
            new_t, k = re.subn(
                rf"<h[1-6][^>]*>\s*{re.escape(epi)}\s*</h[1-6]>",
                f'<blockquote><p><em>{epi}</em></p></blockquote>', t,
            )
            if k:
                n_epi += k
                removed_toc_titles.add(epi)
            t = new_t

        xf.write_text(t, encoding="utf-8")

    # nav/ncx 里的标题错字也要修
    for navf in [tmp / "EPUB" / "nav.xhtml", tmp / "EPUB" / "toc.ncx"]:
        if navf.exists():
            t = navf.read_text(encoding="utf-8")
            for pair in args.fix_title:
                bad, good = pair.split("=>")
                t = t.replace(bad, good)
            navf.write_text(t, encoding="utf-8")

    clean_toc(tmp, removed_toc_titles)
    n_weread_semantics = make_weread_safe(tmp)

    # 6. 封面
    if args.cover:
        opf = tmp / "EPUB" / "content.opf"
        t = opf.read_text(encoding="utf-8")
        m = re.search(rf'<item id="([^"]+)" href="media/{re.escape(args.cover)}"', t)
        if m:
            item_id = m.group(1)
            t = t.replace(
                f'<item id="{item_id}" href="media/{args.cover}"',
                f'<item id="{item_id}" properties="cover-image" href="media/{args.cover}"',
            )
            t = t.replace("</metadata>", f'<meta name="cover" content="{item_id}" /></metadata>')
            opf.write_text(t, encoding="utf-8")
            print(f"封面已设为 media/{args.cover}")
        else:
            print(f"警告: opf 中未找到 media/{args.cover}", file=sys.stderr)

    repack(tmp, args.dst)
    shutil.rmtree(tmp)
    print(f"WeRead Guide 兼容处理：移除正文 epub:type {n_weread_semantics} 处；目录页已加入阅读顺序")
    print(f"脚注编号注入: {n_fn} 条 | 分节符转hr: {n_hr} 处 | 题词降级: {n_epi} 处")
    print(f"目录移除条目: {sorted(removed_toc_titles)}")
    print(f"输出: {args.dst}")


if __name__ == "__main__":
    main()
