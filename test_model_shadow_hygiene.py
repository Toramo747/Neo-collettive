import subprocess
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parent


class ModelShadowHygieneTests(unittest.TestCase):
    def test_hidden_jsonl_is_not_tracked_or_staged_by_workflow(self):
        tracked=subprocess.check_output(
            ["git","ls-files"],cwd=ROOT,text=True
        ).splitlines()
        self.assertFalse(any(Path(p).name=="hidden.jsonl" for p in tracked))
        workflow=(ROOT/".github/workflows/model-shadow-private-batch.yml").read_text(encoding="utf-8")
        for line in workflow.splitlines():
            if "git" in line and "add" in line:
                self.assertNotIn("hidden.jsonl",line)
        self.assertIn('$RUNNER_TEMP/model-shadow-eval/hidden.jsonl',workflow)
        self.assertIn("hidden.jsonl must never be tracked",workflow)

    def test_private_batch_report_contains_only_aggregate_field_names(self):
        source=(ROOT/"tools/model_shadow_resumable.py").read_text(encoding="utf-8")
        self.assertIn('"consensus_path"',source)
        self.assertIn('"nli_bands"',source)
        self.assertIn('"double_prompt"',source)
        self.assertIn('"labels_by_class"',source)
        self.assertIn('"labels_by_source_bucket"',source)
        report_block=source[source.index("def _write_private_batch_report"):source.index("def _write_safe")]
        for forbidden in ('"normalized_text"','"url"','"domain"','"title"','"snippet"'):
            self.assertNotIn(forbidden,report_block)

    def test_research_profile_has_default_on_environment_rollback(self):
        source=(ROOT/"cloud_mcp.py").read_text(encoding="utf-8")
        self.assertIn('os.getenv("NEO_RESEARCH_PROFILE_ENABLED", "1")',source)
        self.assertIn("arena_profile=RESEARCH_PROFILE_ENABLED",source)


if __name__=="__main__":
    unittest.main()
