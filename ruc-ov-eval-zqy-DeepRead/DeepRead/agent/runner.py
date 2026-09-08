from __future__ import annotations

import hashlib
import json
from typing import Any, Callable, Dict, List, Optional, Tuple

from .llm import (
    _preview_messages,
    _preview_tool_calls,
    http_chat_completions,
    sanitize_for_vllm,
    should_sanitize_for_vllm,
)
from ..prompt.system import build_system_prompt
from ..tool.fallback import fallback_tool_calls_from_text, strip_function_calls_block_any, strip_inline_tool_calls
from ..tool.schema import make_tools_schema
from .search_session import SearchSessionState, ToolBudgetState, normalize_requested_top_k


def _build_generated_corpus_inventory(
    doc_index: DocIndex,
    generated_corpus_inventory: Optional[Dict[str, Dict[str, Any]]],
) -> List[Dict[str, Any]]:
    corpus_inventory: List[Dict[str, Any]] = []
    for doc_id, source_name in doc_index.doc_id_map.items():
        sections: List[Dict[str, Any]] = []
        doc_nodes = doc_index.nodes_by_doc.get(str(doc_id), {}) or {}
        for node_id, node in doc_nodes.items():
            sections.append(
                {
                    "node_id": str(node_id),
                    "title": str(node.get("title", "")),
                    "paragraph_count": len(node.get("paragraphs", [])),
                    "token_count": int(
                        node.get(
                            "_model_token_count",
                            len(node.get("_tokens", [])),
                        )
                    ),
                }
            )
        item: Dict[str, Any] = {
            "doc_id": str(doc_id),
            "source_name": str(source_name),
            # Generated-tool runtime contract exposes both source_name and title.
            # For corpus files the canonical document title is the source name.
            "title": str(source_name),
            "sections": sections,
        }
        paper_key = str(source_name)
        if paper_key.endswith("_doc"):
            paper_key = paper_key[:-4]
        extra = (generated_corpus_inventory or {}).get(paper_key)
        if isinstance(extra, dict):
            # Trusted preprocessing supplies read-only canonical units. The legacy
            # `pages` field name does not imply PDF access.
            item["pages"] = extra.get("pages") or []
        corpus_inventory.append(item)
    return corpus_inventory


def _invoke_generated_corpus_tool(
    tool: Callable[..., Dict[str, Any]],
    question: str,
    corpus_inventory: List[Dict[str, Any]],
    top_k: int,
    capability: Optional[str] = None,
) -> Dict[str, Any]:
    """Invoke a single generated tool or a portfolio dispatcher.

    The optional capability is selected by the Student model and merely
    forwarded. The harness does not route questions or encode dataset rules.
    """
    selected = str(capability or "").strip()
    if selected:
        return tool(question, corpus_inventory, top_k, selected)
    return tool(question, corpus_inventory, top_k)


def run_agent(
    model: str,
    base_url: Optional[str],
    doc_index: DocIndex,
    user_question: str,
    logger: JsonlLogger,
    max_rounds: int = 50,
    temperature: float = 0.0,
    api_key: Optional[str] = None,
    default_headers: Optional[Dict[str, str]] = None,
    enable_multimodal: bool = False,
    enable_vector: bool = False,
    enable_hybrid: bool = False,
    enable_semantic: bool = False,
    disable_bm25: bool = False,
    disable_regex: bool = False,
    disable_read: bool = False,
    embed_api_key: Optional[str] = None,
    embed_base_url: Optional[str] = None,
    embedding_model: Optional[str] = None,
    neighbor_window: Optional[Tuple[int, int]] = None,
    bm25_topk: int = 1,
    regex_topk: int = 1,
    vector_topk: int = 1,
    hybrid_topk: int = 1,
    hybrid_topk_bm25: int = 30,
    hybrid_topk_vec: int = 30,
    hybrid_bm25_weight: float = 0.5,
    hybrid_vector_weight: float = 0.5,
    semantic_stage1_method: str = "vector",
    semantic_topk1: int = 30,
    semantic_topk2: int = 1,
    semantic_stage1_hybrid_topk_bm25: int = 30,
    semantic_stage1_hybrid_topk_vec: int = 30,
    rerank_api_key: Optional[str] = None,
    rerank_base_url: str = "https://api.siliconflow.cn/v1",
    rerank_model: str = "Qwen/Qwen3-Reranker-8B",
    tool_fallback: bool = True,
    enable_reasoning: bool = True,
    collected_texts: Optional[List[str]] = None,
    enable_session_pagination: bool = True,
    agent_topk_max: int = 10,
    pagination_candidate_limit: int = 50,
    additional_instructions: Optional[List[str] | str] = None,
    preload_directory_structure: bool = False,
    enable_document_title_search: bool = False,
    enable_document_inventory_search: bool = False,
    document_inventory_tool: Optional[
        Callable[[str, List[Dict[str, str]], int], Dict[str, Any]]
    ] = None,
    enable_generated_corpus_search: bool = False,
    generated_corpus_tool: Optional[
        Callable[[str, List[Dict[str, Any]], int], Dict[str, Any]]
    ] = None,
    generated_corpus_inventory: Optional[Dict[str, Dict[str, Any]]] = None,
    generated_corpus_gate: Optional[
        Callable[[str, Dict[str, Any]], Dict[str, Any]]
    ] = None,
    enable_structure_title_search: bool = False,
    max_identical_tool_calls: int = 0,
    max_search_tool_calls: int = 0,
    max_structure_search_calls: int = 0,
    query_id: Optional[str] = None,
) -> str:
    query_id = query_id or hashlib.sha1(user_question.encode('utf-8')).hexdigest()[:16]

    # Optional fail-closed gate for an AI-generated tool. The gate sees only the
    # question and the tool's read-only preview. A fallback decision hides both
    # the tool and its dedicated instructions, restoring the baseline tool set.
    if enable_generated_corpus_search and generated_corpus_gate is not None:
        gate_output: Dict[str, Any] = {}
        preview: Dict[str, Any] = {}
        try:
            if generated_corpus_tool is None:
                raise RuntimeError("generated corpus tool is not loaded")
            inventory = _build_generated_corpus_inventory(
                doc_index, generated_corpus_inventory
            )
            raw_preview = generated_corpus_tool(user_question, inventory, 1)
            preview = raw_preview if isinstance(raw_preview, dict) else {}
            raw_gate = generated_corpus_gate(user_question, preview)
            gate_output = raw_gate if isinstance(raw_gate, dict) else {}
            decision = str(gate_output.get("decision") or "").strip().upper()
            use_tool = bool(gate_output.get("use_tool")) or decision == "USE_TOOL"
            # An empty preview can never provide useful evidence, regardless of
            # a malformed or over-confident generated gate decision.
            if not isinstance(preview.get("results"), list) or not preview["results"]:
                use_tool = False
            logger.log(
                "generated_tool_gate",
                query_id=query_id,
                decision="USE_TOOL" if use_tool else "FALLBACK",
                confidence=gate_output.get("confidence"),
                reason=gate_output.get("reason"),
                preview_result_count=len(preview.get("results") or []),
            )
        except Exception as exc:
            use_tool = False
            logger.log(
                "generated_tool_gate_error",
                query_id=query_id,
                error=f"{type(exc).__name__}: {exc}",
                decision="FALLBACK",
            )
        if not use_tool:
            enable_generated_corpus_search = False
            additional_instructions = []

    tools = make_tools_schema(
        doc_index,
        enable_semantic=enable_semantic,
        enable_document_inventory_search=enable_document_inventory_search,
        enable_generated_corpus_search=enable_generated_corpus_search,
        suggested_top_k=bm25_topk,
        max_top_k=agent_topk_max,
    )
    if preload_directory_structure:
        tools = [
            t
            for t in tools
            if (t.get("function") or {}).get("name") != "get_doc_structure"
        ]

    if not enable_document_title_search:
        tools = [
            t
            for t in tools
            if (t.get("function") or {}).get("name") != "search_document_titles"
        ]
    if not enable_document_inventory_search:
        tools = [
            t
            for t in tools
            if (t.get("function") or {}).get("name")
            != "document_inventory_search"
        ]
    if not enable_generated_corpus_search:
        tools = [
            t
            for t in tools
            if (t.get("function") or {}).get("name")
            != "generated_corpus_search"
        ]
    if not enable_structure_title_search:
        tools = [
            t
            for t in tools
            if (t.get("function") or {}).get("name") != "search_document_structure"
        ]

    if disable_bm25:
        tools = [t for t in tools if (t.get("function") or {}).get("name") != "bm25_search"]
    if disable_regex:
        tools = [t for t in tools if (t.get("function") or {}).get("name") != "regex_search"]
    if not enable_vector:
        tools = [t for t in tools if (t.get("function") or {}).get("name") != "vector_search"]
    if not enable_hybrid:
        tools = [t for t in tools if (t.get("function") or {}).get("name") != "hybrid_search"]
    if not enable_semantic:
        tools = [t for t in tools if (t.get("function") or {}).get("name") != "semantic_retrieval"]
    if disable_read:
        tools = [t for t in tools if (t.get("function") or {}).get("name") != "read_section"]

    tool_names = [(t.get("function") or {}).get("name") for t in tools]
    system_prompt = build_system_prompt(
        doc_index,
        tool_names,
        enable_reasoning=enable_reasoning,
        additional_instructions=additional_instructions,
        preload_directory_structure=preload_directory_structure,
    )

    messages: List[Dict[str, Any]] = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_question}]
    prev_msg_count = 1
    search_session = SearchSessionState()
    tool_budget = ToolBudgetState()
    search_tool_names = {
        "document_inventory_search",
        "generated_corpus_search",
        "bm25_search",
        "regex_search",
        "vector_search",
        "hybrid_search",
        "semantic_retrieval",
    }

    do_sanitize = should_sanitize_for_vllm(base_url)

    effective_neighbor_window: Optional[Tuple[int, int]] = neighbor_window if neighbor_window is not None else doc_index.neighbor_window

    for round_id in range(1, max_rounds + 1):
        req_payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",
            "temperature": temperature,
            "stream": False,
            "include_reasoning": bool(enable_reasoning),
        }

        logger.log("llm_request", query_id=query_id, round=round_id, base_url=base_url, context_delta_preview=_preview_messages(messages[prev_msg_count:]))
        prev_msg_count = len(messages)

        payload_to_send = sanitize_for_vllm(req_payload, allow_tools=True) if do_sanitize else req_payload

        try:
            resp = http_chat_completions(query_id=query_id, api_key=api_key, base_url=base_url, payload=payload_to_send, default_headers=default_headers, logger=logger)
        except Exception as exc:
            logger.log("llm_http_error", query_id=query_id, error=str(exc), round=round_id)
            resp = {}

        msg = (resp.get("choices") or [{}])[0].get("message", {})  # type: ignore

        reasoning_content = None
        if enable_reasoning:
            for rf in ["reasoning", "reasoning_content", "thinking", "internal_monologue"]:
                if msg.get(rf) is not None:
                    reasoning_content = msg.get(rf)
                    break

        tool_calls = msg.get("tool_calls")
        recovered_from_text = False
        recovered_meta: Dict[str, Any] = {}

        content_str = msg.get("content") or ""
        reasoning_str = reasoning_content or ""

        if not tool_calls and tool_fallback:
            rec = fallback_tool_calls_from_text(content_str) or fallback_tool_calls_from_text(reasoning_str)
            if rec:
                tool_calls, recovered_meta = rec
                recovered_from_text = True
                logger.log(
                    "tool_calls_recovered_from_text",
                    query_id=query_id,
                    round=round_id,
                    recovered=_preview_tool_calls(tool_calls),
                    recovered_kind=recovered_meta.get("kind"),
                )

        assistant_entry: Dict[str, Any] = {"role": "assistant"}

        content_for_history = msg.get("content")
        if isinstance(content_for_history, str) and recovered_from_text:
            content_for_history = strip_function_calls_block_any(content_for_history)
            if recovered_meta.get("kind") == "inline_json" and recovered_meta.get("spans"):
                content_for_history = strip_inline_tool_calls(content_for_history, recovered_meta["spans"])

        if content_for_history is None:
            content_for_history = ""
        assistant_entry["content"] = content_for_history

        if enable_reasoning and reasoning_content:
            assistant_entry["reasoning"] = reasoning_content

        if tool_calls:
            assistant_entry["tool_calls"] = tool_calls

        messages.append(assistant_entry)

        logger.log(
            "llm_response",
            query_id=query_id,
            round=round_id,
            content=msg.get("content"),
            reasoning_content=reasoning_content if enable_reasoning else None,
            tool_calls=_preview_tool_calls(tool_calls),
            context_delta_preview=_preview_messages(messages[prev_msg_count:]) if tool_calls else None,
        )

        if tool_calls:
            prev_msg_count = len(messages)

        if not tool_calls:
            final_answer = (msg.get("content") or "").strip()
            if final_answer:
                logger.log("final_answer", query_id=query_id, answer=final_answer, context_delta_preview=_preview_messages(messages[prev_msg_count:]))
                return final_answer

            if enable_reasoning and (reasoning_content is not None) and str(reasoning_content).strip():
                logger.log("llm_thinking_only", query_id=query_id, round=round_id, reasoning_preview=str(reasoning_content)[:2000])
            else:
                logger.log("llm_empty_message", query_id=query_id, round=round_id)
            continue

        for tc in tool_calls or []:
            tool_name = (tc.get("function") or {}).get("name")
            try:
                args_raw = (tc.get("function") or {}).get("arguments")
                args = args_raw if isinstance(args_raw, dict) else json.loads(args_raw or "{}")
            except Exception as exc:
                logger.log("tool_args_parse_error", query_id=query_id, tool=tool_name, raw=str(args_raw), error=str(exc))
                args = {}

            logger.log("tool_call", query_id=query_id, tool=tool_name, args=args, tool_call_id=tc.get("id"))

            try:
                requested_top_k: Optional[int] = None
                candidate_top_k: Optional[int] = None
                budget_error = tool_budget.register(
                    str(tool_name),
                    args,
                    max_identical_calls=max_identical_tool_calls,
                    max_search_calls=max_search_tool_calls,
                    max_structure_search_calls=max_structure_search_calls,
                )
                if budget_error:
                    out = {
                        "ok": False,
                        "error": budget_error,
                        "budget": {
                            "search_calls_used": tool_budget.search_calls,
                            "structure_search_calls_used": tool_budget.structure_search_calls,
                        },
                    }
                    logger.log(
                        "tool_budget_block",
                        query_id=query_id,
                        tool=tool_name,
                        args=args,
                        reason=budget_error,
                    )
                elif tool_name == "document_inventory_search":
                    if document_inventory_tool is None:
                        out = {
                            "ok": False,
                            "error": "generated document inventory tool is not loaded",
                        }
                    else:
                        documents = [
                            {
                                "doc_id": str(doc_id),
                                "source_name": str(source_name),
                            }
                            for doc_id, source_name in doc_index.doc_id_map.items()
                        ]
                        out = document_inventory_tool(
                            str(args.get("question") or user_question),
                            documents,
                            normalize_requested_top_k(args.get("top_k"), 5, 20),
                        )
                        if isinstance(out, dict):
                            out.setdefault("ok", True)
                elif tool_name == "generated_corpus_search":
                    if generated_corpus_tool is None:
                        out = {
                            "ok": False,
                            "error": "generated corpus search tool is not loaded",
                        }
                    else:
                        corpus_inventory = _build_generated_corpus_inventory(
                            doc_index, generated_corpus_inventory
                        )
                        out = _invoke_generated_corpus_tool(
                            generated_corpus_tool,
                            # Always preserve the complete original question. Agent-written
                            # shorthand can drop the paper title or the scientific entity
                            # that the generated structural ranker needs.
                            user_question,
                            corpus_inventory,
                            normalize_requested_top_k(args.get("top_k"), 5, 20),
                            args.get("capability"),
                        )
                        if isinstance(out, dict):
                            out.setdefault("ok", True)
                elif tool_name == "get_doc_structure":
                    raw_ids = args.get("doc_id")
                    doc_ids = [str(d) for d in raw_ids] if isinstance(raw_ids, list) else None
                    out = doc_index.get_doc_structure(doc_ids=doc_ids)
                elif tool_name == "search_document_titles":
                    out = doc_index.search_document_titles(
                        # Route from the complete original question. Agent-written
                        # shorthand often drops the company name and leaves only a
                        # non-discriminative year such as "FY2022".
                        query=user_question,
                        top_k=normalize_requested_top_k(
                            args.get("top_k"), 5, 20
                        ),
                    )
                elif tool_name == "search_document_structure":
                    out = doc_index.search_document_structure(
                        query=args.get("query", user_question),
                        doc_id=str(args.get("doc_id", "")),
                        top_k=normalize_requested_top_k(
                            args.get("top_k"), 5, 20
                        ),
                    )
                elif tool_name == "read_section":
                    out = doc_index.read_section(
                        doc_id=args.get("doc_id"),
                        node_id=args.get("node_id"),
                        start_paragraph=int(args.get("start_paragraph", 0)),
                        end_paragraph=int(args.get("end_paragraph", -1)),
                        include_images=enable_multimodal,
                    )
                elif tool_name == "bm25_search":
                    requested_top_k = normalize_requested_top_k(
                        args.get("top_k"), bm25_topk, agent_topk_max
                    )
                    candidate_top_k = (
                        search_session.candidate_top_k(
                            requested_top_k, pagination_candidate_limit
                        )
                        if enable_session_pagination
                        else requested_top_k
                    )
                    out = doc_index.bm25_search(
                        query=args.get("query", ""),
                        scope=args.get("scope", "full"),
                        doc_id=args.get("doc_id"),
                        top_k=candidate_top_k,
                        include_images=enable_multimodal,
                        neighbor_window=effective_neighbor_window,
                    )
                elif tool_name == "regex_search":
                    requested_top_k = normalize_requested_top_k(
                        args.get("top_k"), regex_topk, agent_topk_max
                    )
                    candidate_top_k = (
                        search_session.candidate_top_k(
                            requested_top_k, pagination_candidate_limit
                        )
                        if enable_session_pagination
                        else requested_top_k
                    )
                    out = doc_index.regex_search(
                        pattern=args.get("pattern", ""),
                        scope=args.get("scope", "full"),
                        doc_id=args.get("doc_id"),
                        top_k=candidate_top_k,
                        include_images=enable_multimodal,
                        neighbor_window=effective_neighbor_window,
                    )
                elif tool_name == "vector_search":
                    requested_top_k = normalize_requested_top_k(
                        args.get("top_k"), vector_topk, agent_topk_max
                    )
                    candidate_top_k = (
                        search_session.candidate_top_k(
                            requested_top_k, pagination_candidate_limit
                        )
                        if enable_session_pagination
                        else requested_top_k
                    )
                    out = doc_index.vector_search(
                        query=args.get("query", ""),
                        scope=args.get("scope", "full"),
                        doc_id=args.get("doc_id"),
                        top_k=candidate_top_k,
                        include_images=enable_multimodal,
                        embed_api_key=embed_api_key,
                        embed_base_url=embed_base_url,
                        embed_model=embedding_model,
                        neighbor_window=effective_neighbor_window,
                    )
                elif tool_name == "hybrid_search":
                    requested_top_k = normalize_requested_top_k(
                        args.get("top_k"), hybrid_topk, agent_topk_max
                    )
                    candidate_top_k = (
                        search_session.candidate_top_k(
                            requested_top_k, pagination_candidate_limit
                        )
                        if enable_session_pagination
                        else requested_top_k
                    )
                    out = doc_index.hybrid_search(
                        query=args.get("query", ""),
                        scope=args.get("scope", "full"),
                        doc_id=args.get("doc_id"),
                        top_k=candidate_top_k,
                        bm25_weight=float(hybrid_bm25_weight),
                        vector_weight=float(hybrid_vector_weight),
                        top_k_bm25=max(int(hybrid_topk_bm25), candidate_top_k),
                        top_k_vec=max(int(hybrid_topk_vec), candidate_top_k),
                        include_images=enable_multimodal,
                        embed_api_key=embed_api_key,
                        embed_base_url=embed_base_url,
                        embed_model=embedding_model,
                        neighbor_window=effective_neighbor_window,
                    )
                elif tool_name == "semantic_retrieval":
                    requested_top_k = normalize_requested_top_k(
                        args.get("top_k"), semantic_topk2, agent_topk_max
                    )
                    candidate_top_k = (
                        search_session.candidate_top_k(
                            requested_top_k, pagination_candidate_limit
                        )
                        if enable_session_pagination
                        else requested_top_k
                    )
                    out = doc_index.semantic_retrieval(
                        query=args.get("query", ""),
                        scope=args.get("scope", "full"),
                        doc_id=args.get("doc_id"),
                        stage1_method=str(semantic_stage1_method),
                        top_k1=max(int(semantic_topk1), candidate_top_k),
                        top_k2=candidate_top_k,
                        stage1_hybrid_topk_bm25=int(semantic_stage1_hybrid_topk_bm25),
                        stage1_hybrid_topk_vec=int(semantic_stage1_hybrid_topk_vec),
                        include_images=enable_multimodal,
                        embed_api_key=embed_api_key,
                        embed_base_url=embed_base_url,
                        embed_model=embedding_model,
                        rerank_api_key=rerank_api_key,
                        rerank_base_url=rerank_base_url,
                        rerank_model=rerank_model,
                        neighbor_window=effective_neighbor_window,
                        hybrid_bm25_weight=float(hybrid_bm25_weight),
                        hybrid_vector_weight=float(hybrid_vector_weight),
                    )
                else:
                    out = {"ok": False, "error": f"Tool '{tool_name}' not implemented"}

                if (
                    enable_session_pagination
                    and tool_name in search_tool_names
                    and requested_top_k is not None
                    and candidate_top_k is not None
                ):
                    out = search_session.paginate(
                        out,
                        requested_top_k=requested_top_k,
                        round_id=round_id,
                        candidate_top_k=candidate_top_k,
                    )

                messages.append({"role": "tool", "tool_call_id": tc.get("id"), "content": json.dumps(out, ensure_ascii=False)})

                if collected_texts is not None and isinstance(out, dict) and out.get("ok", True):
                    if tool_name in ("bm25_search", "regex_search", "vector_search", "hybrid_search", "semantic_retrieval"):
                        for r in out.get("results", []):
                            if r.get("text"):
                                collected_texts.append(r["text"])
                            for nb in r.get("neighbors", []):
                                if isinstance(nb, dict) and nb.get("type") == "text" and nb.get("text"):
                                    collected_texts.append(nb["text"])
                    elif tool_name == "read_section":
                        for p in out.get("paragraphs", []):
                            if isinstance(p, dict) and p.get("type") == "text" and p.get("text"):
                                collected_texts.append(p["text"])
                
                if (
                    enable_multimodal
                    and tool_name in ("bm25_search", "regex_search", "vector_search", "hybrid_search", "semantic_retrieval")
                    and isinstance(out, dict)
                ):
                    seen_keys = set()
                    mm_items: List[Dict[str, Any]] = []
                    for r in out.get("results", []):
                        neighbors = r.get("neighbors") or []
                        ref = r.get("ref") or {}
                        did = str(ref.get("doc_id"))
                        nid = str(ref.get("node_id"))
                        for item in neighbors:
                            if isinstance(item, dict):
                                item_type = item.get("type") or "text"
                                par_idx = int(item.get("paragraph_index", -1))
                                key = (did, nid, par_idx, item_type)
                                if key in seen_keys:
                                    continue
                                seen_keys.add(key)
                                tagged = dict(item)
                                tagged["paragraph_index"] = par_idx
                                mm_items.append(tagged)
                    if mm_items:
                        messages.append({"role": "user", "content": mm_items})

                logger.log(
                    "tool_result",
                    query_id=query_id,
                    tool=tool_name,
                    ok=bool(out.get("ok", True)) if isinstance(out, dict) else True,
                    result=out,
                    context_delta_preview=_preview_messages(messages[prev_msg_count:]),
                )
                prev_msg_count = len(messages)

            except Exception as exc:
                err = {"ok": False, "error": str(exc)}
                messages.append({"role": "tool", "tool_call_id": tc.get("id"), "content": json.dumps(err, ensure_ascii=False)})
                logger.log(
                    "tool_result",
                    query_id=query_id,
                    tool=tool_name,
                    ok=False,
                    error=str(exc),
                    result=err,
                    context_delta_preview=_preview_messages(messages[prev_msg_count:]),
                )
                prev_msg_count = len(messages)

    logger.log("max_rounds_reached", query_id=query_id, max_rounds=max_rounds)
    return "(Reached maximum rounds, no final answer generated)"
