import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock


OV_TEST_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OV_TEST_ROOT))

from src.pipeline import BenchmarkPipeline  # noqa: E402


class PipelineSkipIngestionTest(unittest.TestCase):
    def test_skip_ingestion_does_not_require_document_layout(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            pipeline = BenchmarkPipeline.__new__(BenchmarkPipeline)
            pipeline.output_dir = temp_dir
            pipeline.generated_file = str(Path(temp_dir) / "generated_answers.json")
            pipeline.records_file = str(Path(temp_dir) / "_pipeline_records.json")
            pipeline.store_type = "Other"
            pipeline.config = {
                "dataset_name": "test",
                "paths": {"doc_output_dir": str(Path(temp_dir) / "missing_docs")},
                "execution": {"skip_ingestion": True, "max_workers": 1},
            }
            pipeline.records = {"ingested": False, "tasks": {}}
            pipeline.metrics_summary = {}
            pipeline._records_lock = threading.Lock()
            pipeline.logger = Mock()
            pipeline.monitor = Mock()
            pipeline.adapter = Mock()
            pipeline.adapter.data_prepare.side_effect = AssertionError(
                "data_prepare must not run when ingestion is skipped"
            )
            pipeline.adapter.load_and_transform.return_value = []
            pipeline._prepare_tasks = Mock(return_value=[])
            pipeline._update_report = Mock()

            pipeline.run_generation()

            pipeline.adapter.data_prepare.assert_not_called()
            pipeline.adapter.load_and_transform.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
