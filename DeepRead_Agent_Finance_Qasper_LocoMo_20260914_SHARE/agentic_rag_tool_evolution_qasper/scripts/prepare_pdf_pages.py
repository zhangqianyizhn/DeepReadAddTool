from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path

import fitz

from common import PDF_PAGES, ROOT, SPLIT_DIR, load_json, save_json, say


PDF_DIR = ROOT / "data" / "pdfs"


def download(paper_id: str, path: Path) -> None:
    if path.exists() and path.stat().st_size > 10_000:
        return
    url = f"https://arxiv.org/pdf/{paper_id}"
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Qasper-RAG-research/1.0 (academic experiment)"},
    )
    last_error: Exception | None = None
    for attempt in range(1, 4):
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                payload = response.read()
            if not payload.startswith(b"%PDF"):
                raise RuntimeError("response is not a PDF")
            temporary = path.with_suffix(".pdf.part")
            temporary.write_bytes(payload)
            temporary.replace(path)
            return
        except Exception as exc:
            last_error = exc
            if attempt < 3:
                time.sleep(10 * attempt)
    raise RuntimeError(f"download failed for {paper_id}: {last_error}")


def extract(path: Path) -> list[dict[str, object]]:
    pages = []
    with fitz.open(path) as document:
        for number, page in enumerate(document, start=1):
            text = page.get_text("text", sort=True).strip()
            if text:
                pages.append({"page_number": number, "text": text})
    return pages


def main() -> int:
    manifest = load_json(SPLIT_DIR / "SPLIT_MANIFEST.json")
    paper_ids = sorted(
        paper_id
        for split_ids in manifest["paper_ids"].values()
        for paper_id in split_ids
    )
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    inventory = load_json(PDF_PAGES) if PDF_PAGES.exists() else {}
    failures: list[dict[str, str]] = []
    for index, paper_id in enumerate(paper_ids, start=1):
        if paper_id in inventory and inventory[paper_id].get("pages"):
            say(f"[PDF复用] {index}/{len(paper_ids)} {paper_id}")
            continue
        say(f"[PDF准备] {index}/{len(paper_ids)} {paper_id}")
        path = PDF_DIR / f"{paper_id}.pdf"
        try:
            download(paper_id, path)
            pages = extract(path)
            if not pages:
                raise RuntimeError("PDF text extraction returned no pages")
            inventory[paper_id] = {
                "paper_id": paper_id,
                "pdf_name": path.name,
                "pages": pages,
            }
            save_json(PDF_PAGES, inventory)
            time.sleep(2)
        except Exception as exc:
            failures.append({"paper_id": paper_id, "error": str(exc)})
            say(f"[PDF警告] {paper_id}: {exc}")
    coverage = len(inventory) / len(paper_ids)
    save_json(ROOT / "data" / "PDF_PREPARATION_REPORT.json", {
        "expected": len(paper_ids),
        "prepared": len(inventory),
        "coverage": coverage,
        "failures": failures,
    })
    if coverage < 0.9:
        raise RuntimeError(f"PDF覆盖率只有{coverage:.1%}，不足以继续实验。")
    print(f"[PDF完成] {len(inventory)}/{len(paper_ids)}篇，覆盖率={coverage:.1%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
