#!/usr/bin/env python3
"""
Step 1: 调用 MinerU 官方 API，把本地 PDF 解析为 Markdown + content_list.json

用法:
    export MINERU_API_TOKEN='你的token'    # 不要写进脚本！
    python step1_mineru_ocr.py 书.pdf --out ./work/书名 --lang ch

功能:
    - 超过 190 页的 PDF 自动分卷（API 限制单文件 200 页 / 200MB）
    - 申请预签名 URL -> PUT 上传 -> 轮询 -> 下载 zip -> 解压合并
    - 输出: {out}/raw.md（原始合并 Markdown）
            {out}/content_list.json（区块级结构标签，供校对用）
            {out}/images/（书中插图）
"""
import argparse
import json
import os
import shutil
import sys
import time
import zipfile
from pathlib import Path

import requests

API_BASE = "https://mineru.net/api/v4"
MAX_PAGES_PER_PART = 190  # 官方上限 200，留余量
POLL_INTERVAL = 15        # 秒
POLL_TIMEOUT = 3600       # 单批最长等待 1 小时


def get_token() -> str:
    token = os.environ.get("MINERU_API_TOKEN")
    if not token:
        sys.exit("请先设置环境变量 MINERU_API_TOKEN（不要把 token 写进脚本或提交到 git）")
    return token


def split_pdf(pdf_path: Path, tmp_dir: Path) -> list[Path]:
    """超过页数上限时用 pypdf 分卷，返回分卷文件列表（按顺序）。"""
    from pypdf import PdfReader, PdfWriter

    reader = PdfReader(str(pdf_path))
    total = len(reader.pages)
    if total <= MAX_PAGES_PER_PART:
        return [pdf_path]

    parts = []
    tmp_dir.mkdir(parents=True, exist_ok=True)
    for i in range(0, total, MAX_PAGES_PER_PART):
        writer = PdfWriter()
        for p in range(i, min(i + MAX_PAGES_PER_PART, total)):
            writer.add_page(reader.pages[p])
        part_path = tmp_dir / f"{pdf_path.stem}_part{i // MAX_PAGES_PER_PART + 1:02d}.pdf"
        with open(part_path, "wb") as f:
            writer.write(f)
        parts.append(part_path)
    print(f"[split] 共 {total} 页，分为 {len(parts)} 卷")
    return parts


def submit_batch(files: list[Path], token: str, lang: str, model_version: str) -> str:
    """申请上传 URL 并 PUT 上传，返回 batch_id。上传完成后系统自动提交解析任务。"""
    header = {"Content-Type": "application/json", "Authorization": f"Bearer {token}"}
    payload = {
        "files": [
            {
                "name": f.name,
                "data_id": f.stem,
                "is_ocr": True,       # 扫描版书籍强制走 OCR
                "language": lang,
            }
            for f in files
        ],
        "model_version": model_version,
    }
    r = requests.post(f"{API_BASE}/file-urls/batch", headers=header, json=payload, timeout=60)
    r.raise_for_status()
    result = r.json()
    if result["code"] != 0:
        sys.exit(f"申请上传 URL 失败: {result['msg']}")

    batch_id = result["data"]["batch_id"]
    urls = result["data"]["file_urls"]
    for f, url in zip(files, urls):
        with open(f, "rb") as fh:
            up = requests.put(url, data=fh, timeout=600)
        if up.status_code != 200:
            sys.exit(f"上传失败: {f.name} (HTTP {up.status_code})")
        print(f"[upload] {f.name} OK")
    return batch_id


def poll_batch(batch_id: str, token: str) -> dict[str, str]:
    """轮询直到全部完成，返回 {data_id: full_zip_url}。"""
    header = {"Authorization": f"Bearer {token}"}
    deadline = time.time() + POLL_TIMEOUT
    while time.time() < deadline:
        r = requests.get(f"{API_BASE}/extract-results/batch/{batch_id}", headers=header, timeout=60)
        r.raise_for_status()
        items = r.json()["data"]["extract_result"]
        states = {it["file_name"]: it["state"] for it in items}
        done = {it["data_id"]: it["full_zip_url"] for it in items if it["state"] == "done"}
        failed = [it for it in items if it["state"] == "failed"]
        if failed:
            for it in failed:
                print(f"[failed] {it['file_name']}: {it.get('err_msg', '')}", file=sys.stderr)
            sys.exit("有分卷解析失败，请检查后重试")
        if len(done) == len(items):
            return done
        prog = ", ".join(f"{k}:{v}" for k, v in states.items())
        print(f"[poll] {prog}")
        time.sleep(POLL_INTERVAL)
    sys.exit("轮询超时")


def download_and_merge(zip_urls: dict[str, str], part_order: list[str], out_dir: Path):
    """按分卷顺序下载 zip、解压、合并 markdown 和 content_list。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    img_dir = out_dir / "images"
    img_dir.mkdir(exist_ok=True)

    merged_md = []
    merged_content = []
    page_offset = 0

    for idx, data_id in enumerate(part_order):
        url = zip_urls[data_id]
        tmp = out_dir / f"_tmp_{data_id}"
        tmp.mkdir(exist_ok=True)
        zpath = tmp / "result.zip"
        with requests.get(url, stream=True, timeout=600) as r:
            r.raise_for_status()
            with open(zpath, "wb") as f:
                shutil.copyfileobj(r.raw, f)
        with zipfile.ZipFile(zpath) as zf:
            zf.extractall(tmp)

        # markdown（zip 里是 full.md 或 {name}.md）
        md_files = list(tmp.glob("*.md"))
        if md_files:
            merged_md.append(md_files[0].read_text(encoding="utf-8"))

        # content_list.json：区块级结构（type/text/page_idx），校对环节的关键输入
        cl_files = list(tmp.glob("*content_list.json"))
        if cl_files:
            blocks = json.loads(cl_files[0].read_text(encoding="utf-8"))
            max_page = 0
            for b in blocks:
                if "page_idx" in b:
                    max_page = max(max_page, b["page_idx"])
                    b["page_idx"] += page_offset
                b["part"] = idx + 1
            merged_content.extend(blocks)
            page_offset += max_page + 1

        # 图片
        for img in tmp.rglob("images/*"):
            shutil.copy(img, img_dir / img.name)

        shutil.rmtree(tmp)
        print(f"[merge] {data_id} 完成")

    (out_dir / "raw.md").write_text("\n\n".join(merged_md), encoding="utf-8")
    (out_dir / "content_list.json").write_text(
        json.dumps(merged_content, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(f"\n完成。输出:\n  {out_dir / 'raw.md'}\n  {out_dir / 'content_list.json'}\n  {img_dir}/")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf", type=Path)
    ap.add_argument("--out", type=Path, required=True, help="输出目录，如 ./work/书名")
    ap.add_argument("--lang", default="ch", help="ch/en/japan 等，默认 ch")
    ap.add_argument("--model-version", default="vlm", help="vlm（默认，效果好）或 pipeline")
    args = ap.parse_args()

    token = get_token()
    parts = split_pdf(args.pdf, args.out / "_parts")
    batch_id = submit_batch(parts, token, args.lang, args.model_version)
    print(f"[batch] batch_id = {batch_id}")
    zip_urls = poll_batch(batch_id, token)
    download_and_merge(zip_urls, [p.stem for p in parts], args.out)


if __name__ == "__main__":
    main()
