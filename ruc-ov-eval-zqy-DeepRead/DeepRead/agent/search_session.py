from __future__ import annotations

from dataclasses import dataclass, field
import json
import re
from typing import Any, Dict, Optional


@dataclass
class SeenChunk:
    first_seen_round: int
    times_seen: int = 1


def normalize_requested_top_k(value: Any, default: int, maximum: int) -> int:
    """Normalize an agent-provided top_k without allowing unbounded context growth."""
    try:
        requested = int(value) if value is not None else int(default)
    except (TypeError, ValueError):
        requested = int(default)
    return max(1, min(requested, max(1, int(maximum))))


def chunk_id_for_result(result: Dict[str, Any]) -> Optional[str]:
    """Return a stable ID for the search hit anchor, excluding expanded neighbors."""
    ref = result.get("ref") or {}
    doc_id = ref.get("doc_id")
    node_id = ref.get("node_id")
    paragraph_index = ref.get("hit_paragraph_index")
    if paragraph_index is None:
        paragraph_indexes = ref.get("paragraph_indexes") or []
        paragraph_index = paragraph_indexes[0] if paragraph_indexes else None
    if doc_id is None or node_id is None or paragraph_index is None:
        return None
    return f"{doc_id}/{node_id}/{int(paragraph_index)}"


def canonical_tool_request(tool_name: str, args: Dict[str, Any]) -> str:
    """Create a stable key for detecting repeated retrieval requests."""
    normalized: Dict[str, Any] = {}
    for key, value in sorted((args or {}).items()):
        # A larger top_k is a breadth adjustment, but it is still the same search
        # intent and should not bypass the duplicate guard indefinitely.
        if key == "top_k":
            continue
        if isinstance(value, str):
            value = re.sub(r"\s+", " ", value).strip().lower()
        elif isinstance(value, list):
            value = [str(item).strip().lower() for item in value]
        normalized[str(key)] = value
    return f"{tool_name}:{json.dumps(normalized, sort_keys=True, ensure_ascii=False)}"


@dataclass
class ToolBudgetState:
    """Hard per-question limits that prevent expensive retrieval loops."""

    request_counts: Dict[str, int] = field(default_factory=dict)
    search_calls: int = 0
    structure_search_calls: int = 0

    _SEARCH_TOOLS = {
        "document_inventory_search",
        "generated_corpus_search",
        "search_document_titles",
        "search_document_structure",
        "bm25_search",
        "regex_search",
        "vector_search",
        "hybrid_search",
        "semantic_retrieval",
    }
    _RETRIEVAL_TOOLS = _SEARCH_TOOLS | {"get_doc_structure", "read_section"}

    def register(
        self,
        tool_name: str,
        args: Dict[str, Any],
        *,
        max_identical_calls: int = 0,
        max_search_calls: int = 0,
        max_structure_search_calls: int = 0,
    ) -> Optional[str]:
        """Record an allowed request, or return a user-facing block reason."""
        if tool_name not in self._RETRIEVAL_TOOLS:
            return None

        request_key = canonical_tool_request(tool_name, args)
        prior = self.request_counts.get(request_key, 0)
        if max_identical_calls > 0 and prior >= max_identical_calls:
            return (
                "Duplicate retrieval request blocked. Use existing evidence, change "
                "strategy meaningfully, or provide the final answer."
            )
        if tool_name in self._SEARCH_TOOLS:
            if max_search_calls > 0 and self.search_calls >= max_search_calls:
                return (
                    "Per-question search budget exhausted. Stop searching and answer "
                    "from the best evidence already collected."
                )
            if (
                tool_name == "search_document_structure"
                and max_structure_search_calls > 0
                and self.structure_search_calls >= max_structure_search_calls
            ):
                return (
                    "Section-heading search budget exhausted. Switch to a doc-scoped "
                    "content search or answer from existing evidence."
                )

        self.request_counts[request_key] = prior + 1
        if tool_name in self._SEARCH_TOOLS:
            self.search_calls += 1
        if tool_name == "search_document_structure":
            self.structure_search_calls += 1
        return None


@dataclass
class SearchSessionState:
    """Per-agent-session retrieval history used for visible result pagination."""

    seen_chunks: Dict[str, SeenChunk] = field(default_factory=dict)

    def candidate_top_k(self, requested_top_k: int, candidate_limit: int) -> int:
        # In the worst case every previously seen chunk is ranked before the next
        # unseen hit, so retrieve requested + seen candidates in one backend call.
        return max(
            requested_top_k,
            min(int(candidate_limit), requested_top_k + len(self.seen_chunks)),
        )

    def paginate(
        self,
        search_result: Dict[str, Any],
        *,
        requested_top_k: int,
        round_id: int,
        candidate_top_k: int,
    ) -> Dict[str, Any]:
        """Return compact markers for repeats and full content for unseen hits."""
        if not isinstance(search_result, dict) or not search_result.get("ok", False):
            return search_result

        ranked_results = []
        new_result_count = 0
        seen_result_count = 0
        scanned_count = 0

        for rank, result in enumerate(search_result.get("results") or [], start=1):
            if new_result_count >= requested_top_k:
                break
            scanned_count += 1
            chunk_id = chunk_id_for_result(result)
            if chunk_id is None:
                # Preserve malformed/legacy hits rather than silently hiding them.
                ranked_results.append(result)
                new_result_count += 1
                continue

            prior = self.seen_chunks.get(chunk_id)
            if prior is not None:
                prior.times_seen += 1
                ranked_results.append(
                    {
                        "rank": rank,
                        "chunk_id": chunk_id,
                        "ref": result.get("ref"),
                        "score": result.get("score"),
                        "status": "ALREADY_SEEN_FULL_TEXT_AVAILABLE_IN_HISTORY",
                        "first_seen_round": prior.first_seen_round,
                        "times_seen": prior.times_seen,
                    }
                )
                seen_result_count += 1
                continue

            tagged = dict(result)
            tagged["chunk_id"] = chunk_id
            tagged["rank"] = rank
            tagged["status"] = "NEW_RESULT"
            ranked_results.append(tagged)
            new_result_count += 1
            self.seen_chunks[chunk_id] = SeenChunk(first_seen_round=round_id)

        out = dict(search_result)
        out["results"] = ranked_results
        out["pagination"] = {
            "requested_new_results": requested_top_k,
            "returned_new_results": new_result_count,
            "returned_seen_markers": seen_result_count,
            "scanned_candidates": scanned_count,
            "candidate_top_k": candidate_top_k,
            "total_unique_chunks_seen_in_session": len(self.seen_chunks),
            "hint": (
                "results preserves backend rank: NEW_RESULT entries contain full text; "
                "ALREADY_SEEN entries are compact references whose full text is already "
                "present in this conversation."
            ),
        }
        return out
