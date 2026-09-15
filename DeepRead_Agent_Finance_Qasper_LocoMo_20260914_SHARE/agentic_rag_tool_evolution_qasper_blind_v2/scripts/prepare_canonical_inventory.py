from __future__ import annotations

from typing import Any

from common import (
    CANONICAL_UNITS,
    SPLIT_DIR,
    load_json,
    save_json,
    sha256_file,
)


def normalized_units(paper: dict[str, Any]) -> list[dict[str, Any]]:
    units: list[dict[str, Any]] = []

    def add(section_name: str, text: str) -> None:
        clean = str(text or "").strip()
        if not clean:
            return
        index = len(units) + 1
        units.append(
            {
                # The harness keeps the legacy page_number field for generated tools.
                # Here it is a deterministic canonical-text unit index, not a PDF page.
                "page_number": index,
                "unit_index": index,
                "section_name": section_name,
                "text": clean,
            }
        )

    add("Title", str(paper.get("title") or ""))
    add("Abstract", str(paper.get("abstract") or ""))
    for section in paper.get("full_text") or []:
        name = str(section.get("section_name") or "Body")
        for paragraph in section.get("paragraphs") or []:
            add(name, str(paragraph or ""))
    for item in paper.get("figures_and_tables") or []:
        caption = str(item.get("caption") or "").strip()
        filename = str(item.get("file") or "").strip()
        add("Figures and Tables", " | ".join(value for value in (caption, filename) if value))
    return units


def main() -> int:
    manifest_path = SPLIT_DIR / "SPLIT_MANIFEST.json"
    corpus_path = SPLIT_DIR / "corpus.json"
    manifest = load_json(manifest_path)
    corpus = load_json(corpus_path)
    inventory = {
        paper_id: {
            "paper_id": paper_id,
            "title": str(paper.get("title") or ""),
            "representation": "canonical_qasper_json_units",
            "pages": normalized_units(paper),
        }
        for paper_id, paper in corpus.items()
    }
    if any(not item["pages"] for item in inventory.values()):
        raise RuntimeError("At least one selected paper has no canonical text units.")
    payload = {
        "split_manifest_sha256": sha256_file(manifest_path),
        "source_sha256": manifest["source_sha256"],
        "paper_count": len(inventory),
        "representation": "canonical Qasper JSON only; no PDF",
    }
    marker = CANONICAL_UNITS.with_name("CANONICAL_INVENTORY_MANIFEST.json")
    if CANONICAL_UNITS.exists() or marker.exists():
        if not CANONICAL_UNITS.exists() or not marker.exists():
            raise RuntimeError("Canonical inventory is partially present; refusing implicit overwrite.")
        if load_json(marker) != payload:
            raise RuntimeError("Canonical inventory belongs to another split.")
        print(f"[REUSE] Canonical inventory: {len(inventory)} papers.")
        return 0
    save_json(CANONICAL_UNITS, inventory)
    save_json(marker, payload)
    print(
        f"[CANONICAL] {len(inventory)} papers, "
        f"{sum(len(item['pages']) for item in inventory.values())} normalized text units; PDF=disabled."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

