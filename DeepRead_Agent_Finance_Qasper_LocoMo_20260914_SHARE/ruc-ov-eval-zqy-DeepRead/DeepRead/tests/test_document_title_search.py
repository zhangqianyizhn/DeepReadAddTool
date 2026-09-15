import unittest

from DeepRead.tool.retrieval import DocIndex


class DocumentTitleSearchTest(unittest.TestCase):
    def setUp(self) -> None:
        self.index = DocIndex(
            [
                {"id": "a", "doc_id": "1", "title": "A", "paragraphs": []},
                {"id": "b", "doc_id": "2", "title": "B", "paragraphs": []},
                {"id": "c", "doc_id": "3", "title": "C", "paragraphs": []},
            ],
            neighbor_window=None,
        )
        self.index.doc_id_map = {
            "1": "3M_2022_10K",
            "2": "BESTBUY_2024Q2_10Q",
            "3": "BOEING_2022_10K",
        }

    def test_routes_spaced_company_name_and_fiscal_period(self) -> None:
        result = self.index.search_document_titles(
            "Which Best Buy product category changed in Q2 of FY2024?",
            top_k=2,
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["results"][0]["doc_id"], "2")
        self.assertEqual(result["results"][0]["source_name"], "BESTBUY_2024Q2_10Q")

    def test_company_disambiguates_same_year(self) -> None:
        result = self.index.search_document_titles(
            "According to Boeing's 2022 annual report, what was the amount?",
            top_k=1,
        )
        self.assertEqual(result["results"][0]["doc_id"], "3")

    def test_company_name_outweighs_a_shared_year(self) -> None:
        self.index.doc_id_map["4"] = "FOOTLOCKER_2022_8K"
        self.index.doc_id_map["5"] = "PEPSICO_2022_10K"
        result = self.index.search_document_titles(
            "What was PepsiCo's EBITDA in FY2022?",
            top_k=5,
        )
        self.assertEqual(result["results"][0]["source_name"], "PEPSICO_2022_10K")

    def test_common_finance_company_aliases(self) -> None:
        self.index.doc_id_map.update(
            {
                "4": "JOHNSON_JOHNSON_2022_10K",
                "5": "JPMORGAN_2022_10K",
            }
        )
        jnj = self.index.search_document_titles("Are JnJ FY2022 financials growing?", 3)
        jpm = self.index.search_document_titles("Are JPM gross margins stable?", 3)
        self.assertEqual(jnj["results"][0]["source_name"], "JOHNSON_JOHNSON_2022_10K")
        self.assertEqual(jpm["results"][0]["source_name"], "JPMORGAN_2022_10K")

    def test_empty_query_is_rejected(self) -> None:
        result = self.index.search_document_titles("---", top_k=5)
        self.assertFalse(result["ok"])
        self.assertEqual(result["results"], [])

    def test_searches_only_headings_in_selected_document(self) -> None:
        self.index.nodes_by_doc["2"]["b"]["title"] = "Domestic Revenue Mix"
        result = self.index.search_document_structure(
            "domestic revenue by product category",
            doc_id="2",
            top_k=3,
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["results"][0]["node_id"], "b")
        self.assertEqual(result["results"][0]["title"], "Domestic Revenue Mix")

    def test_structure_search_rejects_unknown_document(self) -> None:
        result = self.index.search_document_structure("revenue", "999")
        self.assertFalse(result["ok"])


if __name__ == "__main__":
    unittest.main()
