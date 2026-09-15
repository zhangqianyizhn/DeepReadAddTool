from __future__ import annotations

from typing import Any

from common import CANONICAL_UNITS, SPLIT_DIR, load_json, save_json, sha256_file


def units(item: dict[str, Any]) -> list[dict[str, Any]]:
    conversation = item.get("conversation") or {}
    summaries = item.get("session_summary") or {}
    result: list[dict[str, Any]] = []
    session_index = 1
    while f"session_{session_index}" in conversation:
        session_key = f"session_{session_index}"
        date = str(conversation.get(f"session_{session_index}_date_time") or "")
        summary = str(summaries.get(f"session_{session_index}_summary") or "")
        if summary:
            result.append(
                {
                    "page_number": len(result) + 1,
                    "unit_index": len(result) + 1,
                    "section_name": f"Session {session_index}",
                    "session_index": session_index,
                    "date_time": date,
                    "speaker": "SUMMARY",
                    "dia_id": "",
                    "text": summary,
                }
            )
        for turn in conversation.get(session_key) or []:
            speaker = str(turn.get("speaker") or "")
            text = str(turn.get("text") or "").strip()
            if not text:
                continue
            result.append(
                {
                    "page_number": len(result) + 1,
                    "unit_index": len(result) + 1,
                    "section_name": f"Session {session_index}",
                    "session_index": session_index,
                    "date_time": date,
                    "speaker": speaker,
                    "dia_id": str(turn.get("dia_id") or turn.get("id") or ""),
                    "text": f"{speaker}: {text}" if speaker else text,
                }
            )
        session_index += 1
    return result


def main() -> int:
    manifest_path = SPLIT_DIR / "SPLIT_MANIFEST.json"
    corpus = load_json(SPLIT_DIR / "corpus.json")
    manifest = load_json(manifest_path)
    inventory = {
        str(item["sample_id"]): {
            "sample_id": str(item["sample_id"]),
            "title": f"Chat History: {item['sample_id']}",
            "representation": "canonical_locomo_sessions",
            "pages": units(item),
        }
        for item in corpus
    }
    if any(not item["pages"] for item in inventory.values()):
        raise RuntimeError("At least one LocoMo conversation has no canonical units.")
    marker = CANONICAL_UNITS.with_name("CANONICAL_INVENTORY_MANIFEST.json")
    payload = {
        "inventory_schema": 2,
        "corpus_sha256": sha256_file(SPLIT_DIR / "corpus.json"),
        "source_sha256": manifest["source_sha256"],
        "conversation_count": len(inventory),
        "conversation_ids": sorted(inventory),
        "representation": "canonical LocoMo sessions, summaries, dates, speakers and utterances",
    }
    if CANONICAL_UNITS.exists() or marker.exists():
        if not CANONICAL_UNITS.exists() or not marker.exists():
            raise RuntimeError("Canonical inventory is partially present; refusing overwrite.")
        # The canonical inventory depends on the full corpus, not on Train/Dev/Test
        # protocol wording. Older manifests used the hash of the entire split
        # manifest, so even an explanatory-text edit caused a false mismatch.
        # Only migrate derived metadata after verifying the actual inventory is
        # byte-for-byte equivalent as parsed JSON.
        if load_json(CANONICAL_UNITS) != inventory:
            raise RuntimeError("Canonical inventory belongs to another corpus.")
        if load_json(marker) != payload:
            save_json(marker, payload)
            print("[MIGRATE] Canonical inventory metadata updated; corpus content is unchanged.")
        print(f"[REUSE] Canonical inventory: {len(inventory)} conversations.")
        return 0
    save_json(CANONICAL_UNITS, inventory)
    save_json(marker, payload)
    print(
        f"[CANONICAL] {len(inventory)} conversations, "
        f"{sum(len(item['pages']) for item in inventory.values())} session/utterance units."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
