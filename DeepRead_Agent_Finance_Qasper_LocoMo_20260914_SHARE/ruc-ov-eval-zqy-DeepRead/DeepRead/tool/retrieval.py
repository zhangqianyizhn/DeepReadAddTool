from __future__ import annotations

import math
import re
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from .bm25_search import bm25_search
from .hybrid_search import hybrid_search
from .read_section import read_section
from .regex_search import regex_search
from .semantic_retrieval import semantic_retrieval
from .utils import _normalize_neighbor_window, count_model_tokens, simple_tokenize
from .vector_search import vector_search


class DocIndex:
    def __init__(self, nodes: List[Dict[str, Any]], neighbor_window: Optional[Tuple[int, int]]) -> None:
        self.neighbor_window: Optional[Tuple[int, int]] = _normalize_neighbor_window(neighbor_window)

        self.nodes: Dict[str, Dict[str, Any]] = {}
        self.nodes_by_doc: Dict[str, Dict[str, Any]] = {}

        for node in nodes:
            node_id = str(node["id"])
            doc_id = str(node.get("doc_id", ""))
            node.setdefault("title", node_id)
            node.setdefault("paragraphs", [])
            node.setdefault("children", [])

            text_parts: List[str] = []
            for paragraph in node["paragraphs"]:
                if isinstance(paragraph, str):
                    text_parts.append(paragraph)
                elif isinstance(paragraph, dict):
                    content = paragraph.get("content", "")
                    if content:
                        text_parts.append(content)
                else:
                    text_parts.append(str(paragraph))
            full_text = "\n".join(text_parts) if text_parts else ""
            node["_tokens"] = simple_tokenize(full_text)
            node["_model_token_count"] = count_model_tokens(full_text)

            self.nodes[node_id] = node
            self.nodes_by_doc.setdefault(doc_id, {})
            self.nodes_by_doc[doc_id][node_id] = node

        self.node_to_doc_id: Dict[str, str] = {}
        ambiguous_node_ids = set()
        for doc_id, doc_nodes in self.nodes_by_doc.items():
            for node_id in doc_nodes.keys():
                node_key = str(node_id)
                doc_key = str(doc_id)
                if node_key in self.node_to_doc_id and self.node_to_doc_id[node_key] != doc_key:
                    ambiguous_node_ids.add(node_key)
                else:
                    self.node_to_doc_id[node_key] = doc_key
        for node_id in ambiguous_node_ids:
            self.node_to_doc_id.pop(node_id, None)

        self.par_docs: List[Dict[str, Any]] = []
        for doc_id, doc_nodes in self.nodes_by_doc.items():
            for node_id, node in doc_nodes.items():
                for paragraph_index, paragraph in enumerate(node["paragraphs"]):
                    if isinstance(paragraph, str):
                        text = paragraph
                    elif isinstance(paragraph, dict):
                        text = paragraph.get("content", "")
                    else:
                        text = str(paragraph)
                    if text:
                        tokens = simple_tokenize(text)
                        self.par_docs.append(
                            {
                                "doc_id": str(doc_id),
                                "node_id": str(node_id),
                                "p_idx": paragraph_index,
                                "text": text,
                                "tokens": tokens,
                                "len": len(tokens),
                            }
                        )

        self.N = len(self.par_docs) if self.par_docs else 1
        self.avgdl = sum(d["len"] for d in self.par_docs) / self.N

        df: Dict[str, int] = {}
        for doc in self.par_docs:
            for term in set(doc["tokens"]):
                df[term] = df.get(term, 0) + 1
        self.df = df

        self.idf: Dict[str, float] = {}
        for term, freq in df.items():
            self.idf[term] = math.log(1 + (self.N - freq + 0.5) / (freq + 0.5))

        self._vec_matrix: Optional[np.ndarray] = None
        self._vec_idmap: List[Dict[str, Any]] = []
        self._vec_model_name: Optional[str] = None
        self._vec_normalized: bool = False
        self.doc_id_map: Dict[str, str] = {}

    def overview(self) -> str:
        lines: List[str] = []
        for doc_id, doc_nodes in self.nodes_by_doc.items():
            for node_id, node in doc_nodes.items():
                lines.append(
                    f"- (doc_id={doc_id}) "
                    f"[{node_id}] {node['title']} | paragraphs={len(node['paragraphs'])} | "
                    f"tokens={node.get('_model_token_count', len(node['_tokens']))} | children={node['children']}"
                )
        return "\n".join(lines)
    
    def get_doc_structure(self, doc_ids: Optional[List[str]] = None) -> Dict[str, Any]:
        all_doc_ids = list(self.nodes_by_doc.keys())
        total = len(all_doc_ids)

        if doc_ids is None:
            return {
                "ok": True,
                "doc_id_range": f"1-{total}",
                "total_docs": total,
                "hint": "Pass specific doc_ids to get node structure.",
            }
        
        lines: List[str] = []
        missing: List[str] = []
        for did in doc_ids:
            did_str = str(did)
            doc_nodes = self.nodes_by_doc.get(did_str)
            if doc_nodes is None:
                missing.append(did_str)
                continue
            for node_id, node in doc_nodes.items():
                lines.append(
                    f"- (doc_id={did_str}) "
                    f"[{node_id}] {node['title']} | paragraphs={len(node['paragraphs'])} | "
                    f"tokens={node.get('_model_token_count', len(node['_tokens']))} | children={node['children']}"
                )

        result: Dict[str, Any] = {
            "ok": True,
            "structure": "\n".join(lines) if lines else "No matching documents found.",
        }
        if missing:
            result["missing_doc_ids"] = missing
        return result

    @staticmethod
    def _title_parts(text: str) -> List[str]:
        """Normalize a report name without sending document contents to the LLM."""
        normalized = re.sub(r"(?<=[A-Za-z])(?=\d)|(?<=\d)(?=[A-Za-z])", " ", str(text))
        return [part.lower() for part in re.findall(r"[A-Za-z]+|\d+", normalized)]

    def search_document_titles(self, query: str, top_k: int = 5) -> Dict[str, Any]:
        """Rank document names only, for cheap routing before content retrieval."""
        query_parts = self._title_parts(query)
        aliases = {
            "jnj": ["johnson"],
            "jpm": ["jpmorgan"],
        }
        for alias, expansions in aliases.items():
            if alias in query_parts:
                query_parts.extend(expansions)
        query_compact = "".join(query_parts)
        if not query_compact:
            return {"ok": False, "error": "query must contain searchable text", "results": []}

        generic = {
            "annual", "report", "quarter", "quarterly", "fiscal", "year",
            "the", "what", "which", "how", "was", "were", "is", "are",
            "10k", "10q", "20f", "8k",
        }
        ranked: List[Dict[str, Any]] = []
        for doc_id, source_name in self.doc_id_map.items():
            source_parts = self._title_parts(source_name)
            source_compact = "".join(source_parts)
            matched: List[str] = []
            score = 0.0

            # Filename components (company, year, quarter) are deliberately
            # matched against a compact query, so BESTBUY matches "Best Buy".
            raw_components = sorted({
                part.lower()
                for part in re.findall(r"[A-Za-z0-9]+", str(source_name))
            })
            for component in raw_components:
                if component and component in query_compact:
                    matched.append(component)
                    if component in generic:
                        score += 0.5
                    elif component.isdigit() and len(component) == 4:
                        score += 2.0
                    elif component.isalpha() and len(component) >= 3:
                        # Company/entity names are much more discriminative than
                        # a year shared by many reports in the same corpus.
                        score += 10.0
                    elif any(char.isalpha() for char in component):
                        score += 8.0
                    else:
                        score += 1.0

            for part in source_parts:
                if part in query_parts and part not in matched:
                    matched.append(part)
                    if part.isdigit() and len(part) == 4:
                        score += 2.0
                    elif part not in generic and len(part) >= 2:
                        score += 1.0

            # A full compact title match is unusually strong and breaks ties.
            if source_compact and source_compact in query_compact:
                score += 5.0
            if score > 0:
                ranked.append(
                    {
                        "doc_id": str(doc_id),
                        "source_name": str(source_name),
                        "score": round(score, 3),
                        "matched_terms": matched,
                    }
                )

        ranked.sort(key=lambda item: (-float(item["score"]), item["source_name"]))
        limit = max(1, min(int(top_k), 20))
        results = ranked[:limit]
        for rank, item in enumerate(results, start=1):
            item["rank"] = rank
        return {
            "ok": True,
            "query": query,
            "results": results,
            "hint": (
                "Use a candidate doc_id with get_doc_structure, then run doc-scoped "
                "content search. Fall back to full-corpus search if no title matches."
            ),
        }

    def search_document_structure(
        self,
        query: str,
        doc_id: str,
        top_k: int = 5,
    ) -> Dict[str, Any]:
        """Search heading titles inside one document without dumping its full tree."""
        did = str(doc_id)
        doc_nodes = self.nodes_by_doc.get(did)
        if doc_nodes is None:
            return {"ok": False, "error": f"unknown doc_id: {did}", "results": []}
        query_parts = self._title_parts(query)
        query_compact = "".join(query_parts)
        if not query_compact:
            return {"ok": False, "error": "query must contain searchable text", "results": []}

        generic = {
            "the", "a", "an", "of", "to", "for", "and", "or", "in", "on",
            "what", "which", "how", "is", "are", "was", "were", "fy",
        }
        ranked: List[Dict[str, Any]] = []
        for node_id, node in doc_nodes.items():
            title = str(node.get("title", ""))
            title_parts = self._title_parts(title)
            if not title_parts:
                continue
            title_compact = "".join(title_parts)
            matched = sorted(
                {
                    part
                    for part in title_parts
                    if part not in generic
                    and (part in query_parts or (len(part) >= 4 and part in query_compact))
                }
            )
            score = float(sum(2 if len(part) >= 6 else 1 for part in matched))
            if title_compact in query_compact or query_compact in title_compact:
                score += 4.0
            if score <= 0:
                continue
            ranked.append(
                {
                    "doc_id": did,
                    "node_id": str(node_id),
                    "title": title,
                    "paragraphs": len(node.get("paragraphs", [])),
                    "tokens": node.get("_model_token_count", len(node.get("_tokens", []))),
                    "score": round(score, 3),
                    "matched_terms": matched,
                }
            )

        ranked.sort(key=lambda item: (-float(item["score"]), item["title"], item["node_id"]))
        limit = max(1, min(int(top_k), 20))
        results = ranked[:limit]
        for rank, item in enumerate(results, start=1):
            item["rank"] = rank
        return {
            "ok": True,
            "query": query,
            "doc_id": did,
            "results": results,
            "hint": (
                "Search content within this doc_id or read a promising node. Try a "
                "shorter synonym query if no heading matches."
            ),
        }
        
    def _neighbor_context_for(
        self,
        doc_id: str,
        node_id: str,
        paragraph_index: int,
        include_images: bool = True,
        neighbor_window: Optional[Tuple[int, int]] = None,
    ) -> List[Dict[str, Any]]:
        window = _normalize_neighbor_window(neighbor_window if neighbor_window is not None else self.neighbor_window)
        node = (self.nodes_by_doc.get(doc_id) or {}).get(node_id) or {"paragraphs": []}
        paragraph_count = len(node.get("paragraphs", []))

        if window is None or paragraph_count == 0:
            return []

        up, down = window
        up = max(0, up)
        down = abs(down)

        neighbors: List[Dict[str, Any]] = []

        if up > 0 and paragraph_index > 0:
            start = max(0, paragraph_index - up)
            end = paragraph_index
            if start < end:
                prev_section = self.read_section(
                    doc_id=doc_id,
                    node_id=node_id,
                    start_paragraph=start,
                    end_paragraph=end,
                    include_images=include_images,
                )
                if prev_section.get("ok", True):
                    neighbors.extend(prev_section.get("paragraphs", []))

        if down > 0 and paragraph_index + 1 < paragraph_count:
            start = paragraph_index + 1
            end = min(paragraph_count, paragraph_index + 1 + down)
            if start < end:
                next_section = self.read_section(
                    doc_id=doc_id,
                    node_id=node_id,
                    start_paragraph=start,
                    end_paragraph=end,
                    include_images=include_images,
                )
                if next_section.get("ok", True):
                    neighbors.extend(next_section.get("paragraphs", []))

        return neighbors

    def read_section(
        self,
        doc_id: Optional[str],
        node_id: str,
        start_paragraph: int,
        end_paragraph: int,
        include_images: bool = True,
    ) -> Dict[str, Any]:
        return read_section(self, doc_id, node_id, start_paragraph, end_paragraph, include_images)

    def bm25_search(
        self,
        query: str,
        scope: str = "full",
        doc_id: Optional[str] = None,
        top_k: int = 2,
        k1: float = 1.5,
        b: float = 0.75,
        include_images: bool = True,
        neighbor_window: Optional[Tuple[int, int]] = None,
    ) -> Dict[str, Any]:
        return bm25_search(self, query, scope, doc_id, top_k, k1, b, include_images, neighbor_window)

    def regex_search(
        self,
        pattern: str,
        scope: str = "full",
        doc_id: Optional[str] = None,
        top_k: int = 2,
        include_images: bool = True,
        neighbor_window: Optional[Tuple[int, int]] = None,
    ) -> Dict[str, Any]:
        return regex_search(self, pattern, scope, doc_id, top_k, include_images, neighbor_window)

    def vector_search(
        self,
        query: str,
        scope: str = "full",
        doc_id: Optional[str] = None,
        top_k: int = 2,
        include_images: bool = True,
        embed_api_key: Optional[str] = None,
        embed_base_url: Optional[str] = None,
        embed_model: Optional[str] = None,
        neighbor_window: Optional[Tuple[int, int]] = None,
    ) -> Dict[str, Any]:
        return vector_search(
            self,
            query,
            scope,
            doc_id,
            top_k,
            include_images,
            embed_api_key,
            embed_base_url,
            embed_model,
            neighbor_window,
        )

    def hybrid_search(
        self,
        query: str,
        scope: str = "full",
        doc_id: Optional[str] = None,
        top_k: int = 2,
        bm25_weight: float = 0.5,
        vector_weight: float = 0.5,
        top_k_bm25: int = 20,
        top_k_vec: int = 20,
        include_images: bool = True,
        embed_api_key: Optional[str] = None,
        embed_base_url: Optional[str] = None,
        embed_model: Optional[str] = None,
        neighbor_window: Optional[Tuple[int, int]] = None,
    ) -> Dict[str, Any]:
        return hybrid_search(
            self,
            query,
            scope,
            doc_id,
            top_k,
            bm25_weight,
            vector_weight,
            top_k_bm25,
            top_k_vec,
            include_images,
            embed_api_key,
            embed_base_url,
            embed_model,
            neighbor_window,
        )

    def semantic_retrieval(
        self,
        query: str,
        scope: str = "full",
        doc_id: Optional[str] = None,
        stage1_method: str = "vector",
        top_k1: int = 30,
        top_k2: int = 5,
        stage1_hybrid_topk_bm25: int = 50,
        stage1_hybrid_topk_vec: int = 50,
        include_images: bool = True,
        embed_api_key: Optional[str] = None,
        embed_base_url: Optional[str] = None,
        embed_model: Optional[str] = None,
        rerank_api_key: Optional[str] = None,
        rerank_base_url: str = "https://api.siliconflow.cn/v1",
        rerank_model: str = "Qwen/Qwen3-Reranker-8B",
        neighbor_window: Optional[Tuple[int, int]] = None,
        hybrid_bm25_weight: float = 0.5,
        hybrid_vector_weight: float = 0.5,
    ) -> Dict[str, Any]:
        return semantic_retrieval(
            self,
            query,
            scope,
            doc_id,
            stage1_method,
            top_k1,
            top_k2,
            stage1_hybrid_topk_bm25,
            stage1_hybrid_topk_vec,
            include_images,
            embed_api_key,
            embed_base_url,
            embed_model,
            rerank_api_key,
            rerank_base_url,
            rerank_model,
            neighbor_window,
            hybrid_bm25_weight,
            hybrid_vector_weight,
        )
