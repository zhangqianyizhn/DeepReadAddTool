import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from DeepRead.agent.logger import JsonlLogger
from DeepRead.agent.runner import _invoke_generated_corpus_tool, run_agent
from DeepRead.agent.search_session import (
    SearchSessionState,
    ToolBudgetState,
    canonical_tool_request,
    chunk_id_for_result,
    normalize_requested_top_k,
)
from DeepRead.tool.retrieval import DocIndex
from DeepRead.tool.schema import make_tools_schema


def _hit(paragraph_index: int, text: str) -> dict:
    return {
        "score": 1.0,
        "ref": {
            "doc_id": "7",
            "node_id": "12",
            "hit_paragraph_index": paragraph_index,
            "paragraph_indexes": [paragraph_index - 1, paragraph_index],
        },
        "text": text,
        "neighbors": [],
    }


class SearchSessionStateTest(unittest.TestCase):
    def test_generated_portfolio_forwards_model_selected_capability(self) -> None:
        received = {}

        def portfolio(question, corpus, top_k, capability):
            received.update(
                question=question,
                corpus=corpus,
                top_k=top_k,
                capability=capability,
            )
            return {"ok": True, "results": []}

        result = _invoke_generated_corpus_tool(
            portfolio,
            "Which policy applies?",
            [{"doc_id": "7", "pages": []}],
            3,
            "policy_cluster_retriever",
        )

        self.assertTrue(result["ok"])
        self.assertEqual(received["question"], "Which policy applies?")
        self.assertEqual(received["top_k"], 3)
        self.assertEqual(received["capability"], "policy_cluster_retriever")

    def test_canonical_tool_request_ignores_case_whitespace_and_top_k(self) -> None:
        first = canonical_tool_request(
            "bm25_search",
            {"query": "  Revenue   Growth ", "scope": "DOC", "top_k": 1},
        )
        second = canonical_tool_request(
            "bm25_search",
            {"query": "revenue growth", "scope": "doc", "top_k": 5},
        )
        self.assertEqual(first, second)

    def test_tool_budget_blocks_duplicate_and_structure_loops(self) -> None:
        budget = ToolBudgetState()
        args = {"query": "restructuring costs", "doc_id": "4"}
        self.assertIsNone(
            budget.register(
                "search_document_structure",
                args,
                max_identical_calls=1,
                max_search_calls=5,
                max_structure_search_calls=2,
            )
        )
        self.assertIn(
            "Duplicate",
            budget.register(
                "search_document_structure",
                {**args, "top_k": 10},
                max_identical_calls=1,
                max_search_calls=5,
                max_structure_search_calls=2,
            ),
        )
        self.assertIsNone(
            budget.register(
                "search_document_structure",
                {"query": "impairment charges", "doc_id": "4"},
                max_identical_calls=1,
                max_search_calls=5,
                max_structure_search_calls=2,
            )
        )
        self.assertIn(
            "budget exhausted",
            budget.register(
                "search_document_structure",
                {"query": "income statement", "doc_id": "4"},
                max_identical_calls=1,
                max_search_calls=5,
                max_structure_search_calls=2,
            ),
        )

    def test_jsonl_loggers_share_a_lock_for_the_same_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = str(Path(temp_dir) / "deepread_run.log")
            first = JsonlLogger(path)
            first.log("first")
            second = JsonlLogger(path)

            self.assertIs(first._lock, second._lock)
            self.assertEqual(len(Path(path).read_text(encoding="utf-8").splitlines()), 1)

    def test_per_query_mode_preloads_directory_and_removes_structure_tool(self) -> None:
        class FakeIndex:
            neighbor_window = None
            nodes_by_doc = {"1": {}}

            @staticmethod
            def overview() -> str:
                return "- (doc_id=1) [42] Financial Statements"

        class FakeLogger:
            def log(self, *args, **kwargs) -> None:
                pass

        sent_payloads = []

        def fake_chat(**kwargs):
            sent_payloads.append(kwargs["payload"])
            return {"choices": [{"message": {"content": "done"}}]}

        with patch(
            "DeepRead.agent.runner.http_chat_completions", side_effect=fake_chat
        ):
            answer = run_agent(
                model="test",
                base_url=None,
                doc_index=FakeIndex(),
                user_question="question",
                logger=FakeLogger(),
                max_rounds=1,
                preload_directory_structure=True,
                query_id="sample:0",
            )

        self.assertEqual(answer, "done")
        payload = sent_payloads[0]
        self.assertIn("Financial Statements", payload["messages"][0]["content"])
        self.assertNotIn("get_doc_structure", payload["messages"][0]["content"])
        self.assertNotIn(
            "get_doc_structure",
            [tool["function"]["name"] for tool in payload["tools"]],
        )

    def test_title_route_uses_complete_original_question(self) -> None:
        class FakeIndex:
            neighbor_window = None
            nodes_by_doc = {"1": {}}

            def __init__(self) -> None:
                self.received_query = None

            def search_document_titles(self, query: str, top_k: int) -> dict:
                self.received_query = query
                return {"ok": True, "results": []}

        class FakeLogger:
            def log(self, *args, **kwargs) -> None:
                pass

        responses = [
            {
                "choices": [
                    {
                        "message": {
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "title-call",
                                    "type": "function",
                                    "function": {
                                        "name": "search_document_titles",
                                        "arguments": '{"query":"FY2022"}',
                                    },
                                }
                            ],
                        }
                    }
                ]
            },
            {"choices": [{"message": {"content": "done"}}]},
        ]
        index = FakeIndex()
        with patch(
            "DeepRead.agent.runner.http_chat_completions",
            side_effect=lambda **_: responses.pop(0),
        ):
            answer = run_agent(
                model="test",
                base_url=None,
                doc_index=index,
                user_question="What was PepsiCo EBITDA in FY2022?",
                logger=FakeLogger(),
                max_rounds=2,
                enable_document_title_search=True,
            )

        self.assertEqual(answer, "done")
        self.assertEqual(index.received_query, "What was PepsiCo EBITDA in FY2022?")

    def test_generated_corpus_search_receives_read_only_structure_inventory(self) -> None:
        class FakeIndex:
            neighbor_window = None
            doc_id_map = {"7": "paper-seven.md"}
            nodes_by_doc = {
                "7": {
                    "12": {
                        "title": "Experimental Results",
                        "paragraphs": [{"content": "secret body text"}],
                        "_model_token_count": 23,
                    }
                }
            }

        class FakeLogger:
            def log(self, *args, **kwargs) -> None:
                pass

        received = {}

        def generated_tool(question, corpus, top_k):
            received.update(question=question, corpus=corpus, top_k=top_k)
            return {"results": [{"doc_id": "7", "node_id": "12"}]}

        responses = [
            {
                "choices": [
                    {
                        "message": {
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "generated-call",
                                    "type": "function",
                                    "function": {
                                        "name": "generated_corpus_search",
                                        "arguments": '{"question":"shortened", "top_k":1}',
                                    },
                                }
                            ],
                        }
                    }
                ]
            },
            {"choices": [{"message": {"content": "done"}}]},
        ]
        with patch(
            "DeepRead.agent.runner.http_chat_completions",
            side_effect=lambda **_: responses.pop(0),
        ):
            answer = run_agent(
                model="test",
                base_url=None,
                doc_index=FakeIndex(),
                user_question="Full scientific question?",
                logger=FakeLogger(),
                max_rounds=2,
                enable_generated_corpus_search=True,
                generated_corpus_tool=generated_tool,
                agent_topk_max=1,
            )

        self.assertEqual(answer, "done")
        self.assertEqual(received["question"], "Full scientific question?")
        self.assertEqual(received["top_k"], 1)
        self.assertEqual(received["corpus"][0]["doc_id"], "7")
        self.assertEqual(received["corpus"][0]["title"], "paper-seven.md")
        self.assertEqual(received["corpus"][0]["source_name"], "paper-seven.md")
        self.assertEqual(received["corpus"][0]["sections"][0]["node_id"], "12")
        self.assertNotIn("paragraphs", received["corpus"][0]["sections"][0])
        self.assertNotIn("secret body text", json.dumps(received["corpus"]))

    def test_generated_gate_fallback_hides_tool_and_tool_instructions(self) -> None:
        class FakeIndex:
            neighbor_window = None
            doc_id_map = {"7": "paper-seven.md"}
            nodes_by_doc = {"7": {}}

        class FakeLogger:
            def __init__(self) -> None:
                self.events = []

            def log(self, event, **kwargs) -> None:
                self.events.append((event, kwargs))

        preview_calls = []

        def generated_tool(question, corpus, top_k):
            preview_calls.append((question, top_k))
            return {"results": [{"doc_id": "7", "text": "weak preview"}]}

        def generated_gate(question, preview):
            self.assertEqual(question, "Conceptual question?")
            self.assertEqual(len(preview["results"]), 1)
            return {
                "decision": "FALLBACK",
                "confidence": 0.9,
                "reason": "not applicable",
            }

        payloads = []

        def fake_chat(**kwargs):
            payloads.append(kwargs["payload"])
            return {"choices": [{"message": {"content": "baseline answer"}}]}

        logger = FakeLogger()
        with patch("DeepRead.agent.runner.http_chat_completions", side_effect=fake_chat):
            answer = run_agent(
                model="test",
                base_url=None,
                doc_index=FakeIndex(),
                user_question="Conceptual question?",
                logger=logger,
                max_rounds=1,
                enable_generated_corpus_search=True,
                generated_corpus_tool=generated_tool,
                generated_corpus_gate=generated_gate,
                additional_instructions=["GENERATED_TOOL_ONLY_MARKER"],
            )

        self.assertEqual(answer, "baseline answer")
        self.assertEqual(len(preview_calls), 1)
        tool_names = {
            tool["function"]["name"] for tool in payloads[0].get("tools", [])
        }
        self.assertNotIn("generated_corpus_search", tool_names)
        self.assertNotIn(
            "GENERATED_TOOL_ONLY_MARKER", payloads[0]["messages"][0]["content"]
        )
        gate_events = [row for row in logger.events if row[0] == "generated_tool_gate"]
        self.assertEqual(gate_events[0][1]["decision"], "FALLBACK")

    def test_generated_gate_use_keeps_tool_available(self) -> None:
        class FakeIndex:
            neighbor_window = None
            doc_id_map = {"7": "paper-seven.md"}
            nodes_by_doc = {"7": {}}

        class FakeLogger:
            def log(self, *args, **kwargs) -> None:
                pass

        calls = []

        def generated_tool(question, corpus, top_k):
            calls.append(question)
            return {"results": [{"doc_id": "7", "text": "strong evidence"}]}

        responses = [
            {
                "choices": [
                    {
                        "message": {
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "gated-call",
                                    "type": "function",
                                    "function": {
                                        "name": "generated_corpus_search",
                                        "arguments": '{"question":"ignored", "top_k":1}',
                                    },
                                }
                            ],
                        }
                    }
                ]
            },
            {"choices": [{"message": {"content": "tool answer"}}]},
        ]
        with patch(
            "DeepRead.agent.runner.http_chat_completions",
            side_effect=lambda **_: responses.pop(0),
        ):
            answer = run_agent(
                model="test",
                base_url=None,
                doc_index=FakeIndex(),
                user_question="Table question?",
                logger=FakeLogger(),
                max_rounds=2,
                enable_generated_corpus_search=True,
                generated_corpus_tool=generated_tool,
                generated_corpus_gate=lambda question, preview: {
                    "decision": "USE_TOOL",
                    "confidence": 0.95,
                },
                agent_topk_max=1,
            )

        self.assertEqual(answer, "tool answer")
        self.assertEqual(calls, ["Table question?", "Table question?"])

    def test_agent_top_k_is_clamped(self) -> None:
        self.assertEqual(normalize_requested_top_k(None, 1, 10), 1)
        self.assertEqual(normalize_requested_top_k("6", 1, 10), 6)
        self.assertEqual(normalize_requested_top_k(99, 1, 10), 10)
        self.assertEqual(normalize_requested_top_k(0, 1, 10), 1)

    def test_repeat_hits_are_marked_and_lower_ranked_hits_fill_page(self) -> None:
        state = SearchSessionState()
        first = state.paginate(
            {"ok": True, "results": [_hit(1, "one"), _hit(2, "two")]},
            requested_top_k=2,
            round_id=1,
            candidate_top_k=2,
        )
        self.assertEqual([r["text"] for r in first["results"]], ["one", "two"])
        self.assertTrue(all(r["status"] == "NEW_RESULT" for r in first["results"]))

        candidate_top_k = state.candidate_top_k(2, 50)
        self.assertEqual(candidate_top_k, 4)
        second = state.paginate(
            {
                "ok": True,
                "results": [
                    _hit(1, "one"),
                    _hit(2, "two"),
                    _hit(3, "three"),
                    _hit(4, "four"),
                ],
            },
            requested_top_k=2,
            round_id=2,
            candidate_top_k=candidate_top_k,
        )
        self.assertEqual(
            [r.get("text") for r in second["results"] if r["status"] == "NEW_RESULT"],
            ["three", "four"],
        )
        seen_results = [
            r
            for r in second["results"]
            if r["status"] == "ALREADY_SEEN_FULL_TEXT_AVAILABLE_IN_HISTORY"
        ]
        self.assertEqual(len(seen_results), 2)
        self.assertEqual(
            seen_results[0]["status"],
            "ALREADY_SEEN_FULL_TEXT_AVAILABLE_IN_HISTORY",
        )
        self.assertEqual(second["pagination"]["returned_new_results"], 2)

    def test_tool_schema_exposes_optional_agent_top_k(self) -> None:
        fake_index = type("FakeIndex", (), {"neighbor_window": None})()
        tools = make_tools_schema(
            fake_index, enable_semantic=True, suggested_top_k=1, max_top_k=8
        )
        search_tools = [
            tool["function"]
            for tool in tools
            if tool["function"]["name"].endswith("search")
            or tool["function"]["name"] == "semantic_retrieval"
        ]
        self.assertEqual(len(search_tools), 5)
        for tool in search_tools:
            top_k = tool["parameters"]["properties"]["top_k"]
            self.assertEqual(top_k["default"], 1)
            self.assertEqual(top_k["maximum"], 8)
            self.assertNotIn("top_k", tool["parameters"]["required"])

    def test_chunk_identity_is_stable_across_search_methods(self) -> None:
        index = DocIndex(
            [
                {
                    "doc_id": "1",
                    "id": "2",
                    "title": "Acquisitions",
                    "paragraphs": ["The acquisition consideration was $10 million."],
                    "children": [],
                }
            ],
            neighbor_window=(0, 0),
        )
        bm25_hit = index.bm25_search("acquisition", top_k=1)["results"][0]
        regex_hit = index.regex_search("acquisition", top_k=1)["results"][0]
        self.assertEqual(chunk_id_for_result(bm25_hit), "1/2/0")
        self.assertEqual(
            chunk_id_for_result(bm25_hit), chunk_id_for_result(regex_hit)
        )

    def test_runner_uses_agent_top_k_and_visible_pagination(self) -> None:
        class FakeIndex:
            neighbor_window = None
            nodes_by_doc = {"7": {}}

            def __init__(self) -> None:
                self.requested_sizes = []

            def bm25_search(self, *, top_k: int, **kwargs) -> dict:
                self.requested_sizes.append(top_k)
                return {
                    "ok": True,
                    "results": [
                        _hit(index, f"text-{index}") for index in range(1, top_k + 1)
                    ],
                }

        class FakeLogger:
            def log(self, *args, **kwargs) -> None:
                pass

        tool_call = {
            "type": "function",
            "function": {
                "name": "bm25_search",
                "arguments": '{"query":"revenue","scope":"full","top_k":2}',
            },
        }
        responses = [
            {
                "choices": [
                    {
                        "message": {
                            "content": "",
                            "tool_calls": [{**tool_call, "id": "call-1"}],
                        }
                    }
                ]
            },
            {
                "choices": [
                    {
                        "message": {
                            "content": "",
                            "tool_calls": [{**tool_call, "id": "call-2"}],
                        }
                    }
                ]
            },
            {"choices": [{"message": {"content": "done"}}]},
        ]
        sent_payloads = []

        def fake_chat(**kwargs):
            sent_payloads.append(kwargs["payload"])
            return responses.pop(0)

        index = FakeIndex()
        with patch(
            "DeepRead.agent.runner.http_chat_completions", side_effect=fake_chat
        ):
            answer = run_agent(
                model="test",
                base_url=None,
                doc_index=index,
                user_question="question",
                logger=FakeLogger(),
                max_rounds=3,
                disable_regex=True,
                agent_topk_max=10,
                pagination_candidate_limit=50,
            )

        self.assertEqual(answer, "done")
        self.assertEqual(index.requested_sizes, [2, 4])
        tool_messages = [
            message
            for message in sent_payloads[-1]["messages"]
            if message["role"] == "tool"
        ]
        second_page = json.loads(tool_messages[-1]["content"])
        seen_results = [
            result
            for result in second_page["results"]
            if result["status"] == "ALREADY_SEEN_FULL_TEXT_AVAILABLE_IN_HISTORY"
        ]
        self.assertEqual(len(seen_results), 2)
        self.assertEqual(
            [
                result["text"]
                for result in second_page["results"]
                if result["status"] == "NEW_RESULT"
            ],
            ["text-3", "text-4"],
        )


if __name__ == "__main__":
    unittest.main()
