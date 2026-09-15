import os
import sys
import tempfile
import types
import unittest
from unittest.mock import MagicMock, patch


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(SCRIPT_DIR, ".."))
sys.path.insert(0, os.path.join(SCRIPT_DIR, "..", ".."))


def _module(name: str, **attrs):
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    sys.modules.setdefault(name, module)


# Keep this config-propagation test independent from optional runtime packages.
_module("numpy")
_module("requests")
_module("tiktoken", get_encoding=MagicMock(return_value=MagicMock()))
_module("tqdm", tqdm=lambda iterable=None, **_: iterable)
_module("volcenginesdkarkruntime", Ark=MagicMock())
_module("volcenginesdkarkruntime._exceptions", ArkRateLimitError=RuntimeError)

from src.core.deepread_store import DeepReadWrapper


class DeepReadPreloadConfigTest(unittest.TestCase):
    def _wrapper(self, enabled: bool) -> DeepReadWrapper:
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        output_dir = os.path.join(self.tempdir.name, "output")
        os.makedirs(output_dir, exist_ok=True)
        return DeepReadWrapper.from_config(
            store_path=os.path.join(self.tempdir.name, "store"),
            doc_output_dir=os.path.join(self.tempdir.name, "processed"),
            output_dir=output_dir,
            llm_cfg={
                "model": "dummy-model",
                "base_url": "http://localhost/v1",
                "api_key": "dummy-key",
            },
            store_cfg={
                "preload_directory_structure": enabled,
                "enable_document_title_search": enabled,
                "enable_structure_title_search": enabled,
                "max_identical_tool_calls": 1 if enabled else 0,
                "max_search_tool_calls": 10 if enabled else 0,
                "max_structure_search_calls": 2 if enabled else 0,
                "enable_vector": False,
                "enable_session_pagination": False,
            },
        )

    def test_from_config_propagates_enabled_flag(self) -> None:
        self.assertTrue(self._wrapper(True).preload_directory_structure)

    def test_from_config_defaults_to_disabled(self) -> None:
        self.assertFalse(self._wrapper(False).preload_directory_structure)
        self.assertFalse(self._wrapper(False).enable_document_title_search)

    def test_from_config_propagates_title_search_flag(self) -> None:
        wrapper = self._wrapper(True)
        self.assertTrue(wrapper.enable_document_title_search)
        self.assertTrue(wrapper.enable_structure_title_search)
        self.assertEqual(wrapper.max_identical_tool_calls, 1)
        self.assertEqual(wrapper.max_search_tool_calls, 10)
        self.assertEqual(wrapper.max_structure_search_calls, 2)

    def test_retrieve_passes_flag_to_agent(self) -> None:
        wrapper = self._wrapper(True)
        with (
            patch.object(wrapper, "_get_doc_index", return_value=object()),
            patch("src.core.deepread_store.run_agent", return_value="answer") as mocked,
        ):
            result = wrapper.retrieve("question", topk=1)

        self.assertEqual(result.resources[0].content, "answer")
        self.assertTrue(mocked.call_args.kwargs["preload_directory_structure"])
        self.assertTrue(mocked.call_args.kwargs["enable_document_title_search"])
        self.assertTrue(mocked.call_args.kwargs["enable_structure_title_search"])
        self.assertEqual(mocked.call_args.kwargs["max_identical_tool_calls"], 1)
        self.assertEqual(mocked.call_args.kwargs["max_search_tool_calls"], 10)
        self.assertEqual(mocked.call_args.kwargs["max_structure_search_calls"], 2)


if __name__ == "__main__":
    unittest.main()
