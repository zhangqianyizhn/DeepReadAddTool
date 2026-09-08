from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path


DEFAULT_INDICES = [0, 46, 56, 113, 126]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build an isolated five-document FinanceBench smoke dataset."
    )
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    source = args.source.resolve()
    output = args.output.resolve()
    raw_path = source / "data" / "financebench_open_source.jsonl"
    rows = [json.loads(line) for line in raw_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    selected = [(index, rows[index]) for index in DEFAULT_INDICES]

    doc_names = [row["doc_name"] for _, row in selected]
    if len(set(doc_names)) != len(selected):
        raise ValueError(f"Smoke selection must contain five unique documents: {doc_names}")

    data_dir = output / "data"
    markdown_dir = output / "markdown"
    pdf_dir = output / "pdfs"
    for directory in (data_dir, markdown_dir, pdf_dir):
        directory.mkdir(parents=True, exist_ok=True)

    copied = []
    for _, row in selected:
        doc_name = row["doc_name"]
        md_source = source / "markdown" / f"{doc_name}.md"
        pdf_source = source / "pdfs" / f"{doc_name}.pdf"
        if md_source.exists():
            destination = markdown_dir / md_source.name
            shutil.copy2(md_source, destination)
            kind = "markdown"
        elif pdf_source.exists():
            destination = pdf_dir / pdf_source.name
            shutil.copy2(pdf_source, destination)
            kind = "pdf"
        else:
            raise FileNotFoundError(f"No Markdown/PDF found for {doc_name}")
        copied.append({"doc_name": doc_name, "kind": kind, "path": str(destination)})

    mini_raw = data_dir / "financebench_open_source.jsonl"
    mini_raw.write_text(
        "".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for _, row in selected),
        encoding="utf-8",
    )
    manifest = {
        "source": str(source),
        "selected": [
            {
                "original_global_index": index,
                "financebench_id": row.get("financebench_id"),
                "doc_name": row["doc_name"],
                "question": row["question"],
            }
            for index, row in selected
        ],
        "copied_documents": copied,
    }
    (output / "selection_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
