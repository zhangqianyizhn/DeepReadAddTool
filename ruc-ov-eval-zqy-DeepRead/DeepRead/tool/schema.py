from __future__ import annotations

from typing import Any, Dict, List


def _neighbor_hint_sentence(doc_index: DocIndex) -> str:
    nw = doc_index.neighbor_window
    if nw is None:
        return ""
    up, down = nw
    return f" Neighbor expansion is enabled: returned hits may include up to {int(up)} paragraph(s) above and {abs(int(down))} paragraph(s) below the matched paragraph."


def make_tools_schema(
    doc_index: DocIndex,
    enable_semantic: bool = False,
    enable_document_inventory_search: bool = False,
    enable_generated_corpus_search: bool = False,
    suggested_top_k: int = 1,
    max_top_k: int = 10,
) -> List[Dict[str, Any]]:
    nh = _neighbor_hint_sentence(doc_index)
    maximum = max(1, int(max_top_k))
    suggested = max(1, min(int(suggested_top_k), maximum))
    top_k_property: Dict[str, Any] = {
        "type": "integer",
        "minimum": 1,
        "maximum": maximum,
        "default": suggested,
        "description": (
            f"Number of new full-text results requested (suggested {suggested}, "
            f"maximum {maximum}). Increase it when broader recall is needed. "
            "Previously returned chunks may additionally appear as compact marker "
            "entries in the ranked results list."
        ),
    }

    tools: List[Dict[str, Any]] = [
        {
            "type": "function",
            "function": {
                "name": "document_inventory_search",
                "description": (
                    "Rank the available corpus documents using document metadata so "
                    "subsequent retrieval can be scoped to the most likely company, "
                    "fiscal period, quarter, and filing type. This is an automatically "
                    "generated candidate capability and does not search document bodies."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "question": {
                            "type": "string",
                            "description": "The complete original user question.",
                        },
                        "top_k": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 20,
                            "default": 5,
                        },
                    },
                    "required": ["question"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "generated_corpus_search",
                "description": (
                    "Use an AI-generated corpus-navigation capability. A system prompt "
                    "may expose either one capability or an adaptive portfolio. It "
                    "receives the complete question plus a read-only dataset-specific "
                    "corpus inventory. The inventory contains document and section "
                    "metadata and may contain trusted normalized text units supplied "
                    "by the experiment. It returns a bounded ranked result set and "
                    "cannot modify the corpus."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "question": {
                            "type": "string",
                            "description": "The complete original user question.",
                        },
                        "capability": {
                            "type": "string",
                            "description": (
                                "Optional AI-generated capability name. Supply this only "
                                "when the system prompt exposes an adaptive portfolio of "
                                "multiple generated tools; choose exactly one listed name "
                                "per call. Omit it for a single generated tool."
                            ),
                        },
                        "top_k": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 20,
                            "default": 5,
                        },
                    },
                    "required": ["question"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "search_document_titles",
                "description": (
                    "Cheaply route a question to likely documents by searching document "
                    "names only (company, year, quarter, report type). Use this first when "
                    "the question names a company or report, then inspect the returned "
                    "doc_id and search content within that document. This does not expose "
                    "all document structures or body text."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "top_k": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 20,
                            "default": 5,
                        },
                    },
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "search_document_structure",
                "description": (
                    "Search section-heading titles inside one chosen document and return "
                    "only a few matching nodes. Prefer this after document-title routing; "
                    "it is much cheaper than requesting the document's complete structure."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "doc_id": {"type": "string"},
                        "top_k": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 20,
                            "default": 5,
                        },
                    },
                    "required": ["query", "doc_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_doc_structure",
                "description": (
                    "Retrieve the Directory Structure of one or more documents. "
                    "Pass a list of doc_id strings to get their Directory Structure. "
                    "If doc_ids is omitted or null, returns only the total document count and id range."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "doc_id": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "List of doc_id values to inspect (e.g. [\"1\", \"3\"]). Omit to get the id range only."
                        }
                    },
                    "required": [],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "read_section",
                "description": "Read a specific paragraph range from the specified document node. Returns paragraphs from start_paragraph (inclusive) to end_paragraph (exclusive).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "doc_id": {"type": "string"},
                        "node_id": {"type": "string"},
                        "start_paragraph": {"type": "integer", "minimum": 0},
                        "end_paragraph": {
                            "type": "integer",
                            "minimum": -1,
                            "description": "Exclusive end paragraph; use -1 to read to the end of the node.",
                        },
                    },
                    "required": ["doc_id", "node_id", "start_paragraph", "end_paragraph"],
                },
            },
        }
    ]

    bm25_props: Dict[str, Any] = {
        "query": {"type": "string"},
        "scope": {"type": "string", "enum": ["full", "doc"], "default": "full"},
        "doc_id": {"type": "string", "default": None},
        "top_k": dict(top_k_property),
    }
    regex_props: Dict[str, Any] = {
        "pattern": {"type": "string"},
        "scope": {"type": "string", "enum": ["full", "doc"], "default": "full"},
        "doc_id": {"type": "string", "default": None},
        "top_k": dict(top_k_property),
    }
    vector_props: Dict[str, Any] = {
        "query": {"type": "string"},
        "scope": {"type": "string", "enum": ["full", "doc"], "default": "full"},
        "doc_id": {"type": "string", "default": None},
        "top_k": dict(top_k_property),
    }
    hybrid_props: Dict[str, Any] = {
        "query": {"type": "string"},
        "scope": {"type": "string", "enum": ["full", "doc"], "default": "full"},
        "doc_id": {"type": "string", "default": None},
        "top_k": dict(top_k_property),
    }

    tools.extend(
        [
            {
                "type": "function",
                "function": {
                    "name": "bm25_search",
                    "description": "Perform BM25-based text retrieval." + nh,
                    "parameters": {"type": "object", "properties": bm25_props, "required": ["query", "scope"]},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "regex_search",
                    "description": "Search for text patterns using regex." + nh,
                    "parameters": {"type": "object", "properties": regex_props, "required": ["pattern", "scope"]},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "vector_search",
                    "description": "Perform embedding-based retrieval using cosine similarity." + nh,
                    "parameters": {"type": "object", "properties": vector_props, "required": ["query", "scope"]},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "hybrid_search",
                    "description": "Fuse BM25 and embedding retrieval results with adjustable weights (internal)." + nh,
                    "parameters": {"type": "object", "properties": hybrid_props, "required": ["query", "scope"]},
                },
            },
        ]
    )

    if enable_semantic:
        semantic_props: Dict[str, Any] = {
            "query": {"type": "string"},
            "scope": {"type": "string", "enum": ["full", "doc"], "default": "full"},
            "doc_id": {"type": "string", "default": None},
            "top_k": dict(top_k_property),
        }
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": "semantic_retrieval",
                    "description": "Semantic Retrieval: stage-1 recall + rerank internally. Neighbor expansion (if enabled) applies ONLY after reranking on final results." + nh,
                    "parameters": {"type": "object", "properties": semantic_props, "required": ["query", "scope"]},
                },
            }
        )

    if not enable_document_inventory_search:
        tools = [
            tool
            for tool in tools
            if (tool.get("function") or {}).get("name")
            != "document_inventory_search"
        ]
    if not enable_generated_corpus_search:
        tools = [
            tool
            for tool in tools
            if (tool.get("function") or {}).get("name")
            != "generated_corpus_search"
        ]
    return tools
