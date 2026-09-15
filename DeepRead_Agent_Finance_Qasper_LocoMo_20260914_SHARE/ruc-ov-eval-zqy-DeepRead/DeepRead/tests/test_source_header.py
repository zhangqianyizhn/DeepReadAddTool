import os
import tempfile
import unittest

from DeepRead.index.markdown_parser import (
    ensure_source_header,
    parse_markdown_to_corpus,
)


class SourceHeaderTest(unittest.TestCase):
    def test_header_is_searchable_structural_content_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            md_path = os.path.join(temp_dir, "report.md")
            with open(md_path, "w", encoding="utf-8") as file:
                file.write("# Management Discussion\n\nRevenue increased.\n")

            ensure_source_header(md_path, "COCACOLA_2021_10K")
            ensure_source_header(md_path, "COCACOLA_2021_10K")

            with open(md_path, "r", encoding="utf-8") as file:
                content = file.read()
            self.assertEqual(content.count("# Source Document:"), 1)

            corpus = parse_markdown_to_corpus(md_path)
            source_node = corpus["nodes"][0]
            self.assertEqual(
                source_node["title"], "Source Document: COCACOLA_2021_10K"
            )
            self.assertEqual(
                source_node["paragraphs"], ["Source name: COCACOLA_2021_10K"]
            )


if __name__ == "__main__":
    unittest.main()
