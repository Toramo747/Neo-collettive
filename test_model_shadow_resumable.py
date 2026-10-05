# SPDX-License-Identifier: BUSL-1.1
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools import model_shadow_resumable as resumable
from tools.model_shadow_batch import _write_jsonl_private, llm_judge
from tools.model_shadow_privacy_check import check_value
from tools.model_shadow_diagnostics import failure_payload, write_stage


class ResumableBatchTests(unittest.TestCase):
    def archive(self, folder, count=4):
        private = Path(folder) / "private"
        private.mkdir()
        rows = [{"id": "synthetic-" + str(i), "normalized_text": "Synthetic example " + str(i),
                 "source": "web", "structural_signals": {}, "date": "2026-10-05"}
                for i in range(count)]
        _write_jsonl_private(private / "train.jsonl", rows)
        for split in ("public", "hidden"):
            _write_jsonl_private(private / (split + ".jsonl"), [])
        return private, rows

    def run_batch(self, private, output, judge):
        args = ["batch", "--private-dir", str(private), "--output-dir", str(output),
                "--max-judge-cases", "3"]
        with patch("sys.argv", args), patch.object(resumable, "judge_private_archive", judge), \
                contextlib.redirect_stdout(io.StringIO()):
            return resumable.main()

    def test_interrupted_chunk_resumes_after_completed_cases(self):
        with tempfile.TemporaryDirectory() as folder:
            private, rows = self.archive(folder)
            output = Path(folder) / "out"

            def interrupted(chunk, **kwargs):
                for row in resumable._read_jsonl(chunk / "train.jsonl")[:2]:
                    kwargs["on_labeled"](dict(row, eligible_for_training=False))
                raise RuntimeError("synthetic private exception https://private.example/case")

            with self.assertRaises(RuntimeError):
                self.run_batch(private, output, interrupted)
            self.assertEqual(resumable.import_status(private)["batch_remaining"], 2)
            self.assertFalse(resumable.import_status(private)["import_allowed"])
            seen = []

            def finish(chunk, **kwargs):
                for row in resumable._read_jsonl(chunk / "train.jsonl"):
                    seen.append(row["id"])
                    kwargs["on_labeled"](dict(row, eligible_for_training=False))

            self.assertEqual(self.run_batch(private, output, finish), 0)
            self.assertEqual(seen, [row["id"] for row in rows[2:]])
            metrics = json.loads((output / "metrics.json").read_text())
            self.assertTrue(metrics["batch_complete"])
            self.assertFalse(metrics["student_available"])
            self.assertFalse(metrics["promotion_eligible"])
            self.assertTrue(resumable.import_status(private)["import_allowed"])

    def test_changed_labeler_policy_rejudges_existing_labels(self):
        with tempfile.TemporaryDirectory() as folder:
            private, rows = self.archive(folder, 1)
            labeled = dict(
                rows[0],
                _source_signature=resumable._source_signature(rows[0]),
                _labeler_revision=0,
            )
            _write_jsonl_private(private / "train_labeled.jsonl", [labeled])
            self.assertFalse(resumable.import_status(private)["import_allowed"])

    def test_changed_source_is_rejudged(self):
        with tempfile.TemporaryDirectory() as folder:
            private, rows = self.archive(folder, 1)
            labeled = dict(
                rows[0],
                _source_signature=resumable._source_signature(rows[0]),
                _labeler_revision=int(resumable.REGISTRY["consensus"]["policy_version"]),
            )
            _write_jsonl_private(private / "train_labeled.jsonl", [labeled])
            self.assertTrue(resumable.import_status(private)["import_allowed"])
            rows[0]["normalized_text"] = "Changed synthetic example"
            _write_jsonl_private(private / "train.jsonl", rows)
            self.assertFalse(resumable.import_status(private)["import_allowed"])

    def test_hidden_label_change_invalidates_finished_cache(self):
        with tempfile.TemporaryDirectory() as folder:
            private, rows = self.archive(folder)
            old = resumable._manifest_hash(rows, private)
            _write_jsonl_private(private / "hidden.jsonl", [{"final_label": "buyer_tool_search"}])
            self.assertNotEqual(old, resumable._manifest_hash(rows, private))

    def test_failed_atomic_write_preserves_previous_labels(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "train_labeled.jsonl"
            _write_jsonl_private(path, [{"id": "old"}])
            before = path.read_bytes()
            with self.assertRaises(TypeError):
                _write_jsonl_private(path, [{"id": "new"}, {"unserializable": object()}])
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(list(Path(folder).glob(".labels-*")), [])

    def test_failure_diagnostic_does_not_leak_exception_message(self):
        try:
            raise ValueError("private@example.test https://private.example/case secret text")
        except ValueError as exc:
            safe = resumable.safe_failure(exc)
        check_value(safe)
        self.assertEqual(safe["error_type"], "ValueError")
        encoded = json.dumps(safe)
        self.assertNotIn("private", encoded)
        self.assertNotIn("secret text", encoded)

    def test_unknown_exception_class_is_not_reflected(self):
        PrivateDomainError = type("PrivateDomainError", (Exception,), {})
        safe = resumable.safe_failure(PrivateDomainError("private"))
        self.assertEqual(safe["error_type"], "MODEL_ERROR")

    def test_oversized_prompt_abstains_without_a_model_call(self):
        class BoundedLLM:
            def n_ctx(self):
                return 1024

            def tokenize(self, prompt):
                return list(prompt)

            def create_chat_completion(self, **kwargs):
                raise AssertionError("oversized input must not reach inference")

        vote, fields = llm_judge(BoundedLLM(), "界" * 1800, {})
        self.assertEqual(vote["confidence"], 0.0)
        self.assertEqual(vote["diagnostic"], "first_invalid")
        self.assertEqual(fields["canonical_problem"], "")

    def test_native_crash_reports_fixed_stage_and_exit_code(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "stage.json"
            with patch.dict("os.environ", {"MODEL_SHADOW_STAGE_PATH": str(path)}):
                write_stage("llm_inference")
            safe = failure_payload(132, path)
            check_value(safe)
            self.assertEqual(safe["reason"], "ILLEGAL_CPU_INSTRUCTION")
            self.assertEqual(safe["failure_stage"], "llm_inference")

    def test_native_diagnostic_rejects_untrusted_stage_and_invalid_files(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "stage.json"
            for content in ('{"stage":"https://private.example"}', '{"stage":[]}', '[]', 'invalid'):
                path.write_text(content)
                safe = failure_payload(132, path)
                check_value(safe)
                self.assertEqual(safe["failure_stage"], "unknown")
            path.unlink()
            self.assertEqual(failure_payload(132, path)["failure_stage"], "unknown")


if __name__ == "__main__":
    unittest.main()
