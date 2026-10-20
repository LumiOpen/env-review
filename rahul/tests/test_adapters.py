"""Focused source-only tests for adapter normalization and static checks."""

import base64
import gzip
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from rlaudit.adapters import normalize, run_checks  # noqa: E402


def _task(task_id, *, domain="toy", files=None, metadata=None):
    return {"task_id": task_id, "domain": domain, "prompt": "A prompt",
            "metadata": metadata or {}, "files": files or {}}


def _archive(mapping):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w") as archive:
        for name, value in mapping.items():
            content = value.encode()
            header = tarfile.TarInfo(name)
            header.size = len(content)
            archive.addfile(header, io.BytesIO(content))
    return base64.b64encode(gzip.compress(output.getvalue())).decode("ascii")


def _new_archive_patch(encoded):
    return ("diff --git a/.build_env/mimo_build_env.tar.gz.b64 "
            "b/.build_env/mimo_build_env.tar.gz.b64\n"
            "new file mode 100644\n--- /dev/null\n"
            "+++ b/.build_env/mimo_build_env.tar.gz.b64\n"
            "@@ -0,0 +1 @@\n+" + encoded + "\n")


class AdapterTests(unittest.TestCase):
    def test_local_jsonl_selects_sorted_ids_and_hashes_file_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            driver = root / "driver.py"
            driver.write_text("score = 1\n", encoding="utf-8")
            records = root / "tasks.jsonl"
            refs = {"driver": {"source": "driver", "path": ""}}
            records.write_text("\n".join(json.dumps(_task(i, files=refs)) for i in ("z", "a", "m")) + "\n")
            sources = {"tasks": records, "driver": driver}
            result = normalize({"kind": "local_jsonl", "source": "tasks", "ids": ["z", "a"], "limit": 1}, sources)
            self.assertEqual([task["task_id"] for task in result["tasks"]], ["a"])
            self.assertEqual(result["coverage"], {"kind": "local_jsonl", "total": 3, "selected": 1, "skipped": 2})
            self.assertEqual(result["tasks"][0]["files"]["driver"],
                             {"source": "driver", "path": "driver.py", "sha256": hashlib.sha256(driver.read_bytes()).hexdigest()})
            with self.assertRaisesRegex(ValueError, "unknown task IDs"):
                normalize({"kind": "local_jsonl", "source": "tasks", "ids": ["absent"]}, sources)

    def test_local_jsonl_rejects_invalid_json_and_unsafe_file_references(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            records = root / "tasks.jsonl"
            records.write_text("{broken}\n")
            with self.assertRaisesRegex(ValueError, "invalid JSONL"):
                normalize({"kind": "local_jsonl", "source": "tasks"}, {"tasks": records})
            data = root / "data"
            data.mkdir()
            (data / "valid.txt").write_text("ok")
            for ref, message in [({"source": "data", "path": "../tasks.jsonl"}, "escapes"),
                                 ({"source": "missing", "path": "x"}, "unknown source"),
                                 ({"source": "data", "path": "valid.txt", "sha256": "0" * 64}, "hash mismatch")]:
                with self.subTest(ref=ref):
                    records.write_text(json.dumps(_task("one", files={"input": ref})) + "\n")
                    with self.assertRaisesRegex(ValueError, message):
                        normalize({"kind": "local_jsonl", "source": "tasks"},
                                  {"tasks": records, "data": data})

    def test_general_missing_files_are_observations_and_existing_files_are_mapped(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle = root / "task-a"
            bundle.mkdir()
            (bundle / "verifier_meta.json").write_text(json.dumps({"items": [{"id": "rubric-a", "method": "llm"}]}))
            result = normalize({"kind": "mimo_general", "source": "general"}, {"general": root})
            task = result["tasks"][0]
            self.assertEqual(task["task_id"], "task-a")
            self.assertEqual(task["metadata"]["verifier_meta"]["items"][0]["id"], "rubric-a")
            self.assertEqual(set(task["files"]), {"verifier_meta"})
            self.assertEqual({item["summary"] for item in result["observations"]},
                             {"missing instruction.md", "missing manifest.json"})
            self.assertEqual(run_checks([task], ["general_contract"])["findings"], [])

    def test_general_contract_reports_explicit_rubric_inconsistencies_only(self):
        task = _task("g", domain="general", metadata={"verifier_meta": {"items": [
            {"id": "same", "method": "rule", "weight": -1}, {"id": "same", "method": "llm"}]}})
        findings = run_checks([task], ["general_contract"])["findings"]
        self.assertEqual({finding["summary"] for finding in findings},
                         {"Duplicate rubric ID", "Rule rubric lacks function name", "Rubric has invalid weight"})
        self.assertTrue(all(finding["evidence_level"] == "static" for finding in findings))
        self.assertFalse(any(finding["status"] == "confirmed" for finding in findings))

    def test_code_archive_is_read_in_memory_and_command_flag_is_candidate(self):
        encoded = _archive({".build_env/test_command.sh": "pytest tests/test_math.py || true\n",
                            "../../outside": "untrusted data"})
        task = _task("c", domain="code", metadata={"instance": {"test_patch": _new_archive_patch(encoded)}})
        findings = run_checks([task], ["code_static"])["findings"]
        self.assertEqual([finding["status"] for finding in findings], ["candidate"])
        self.assertIn("masks nonzero", findings[0]["summary"])

    @unittest.skipUnless(importlib.util.find_spec("pyarrow") is not None, "optional pyarrow unavailable")
    def test_code_parquet_retains_full_instance_without_executing_patch(self):
        import pyarrow as pa
        import pyarrow.parquet as pq

        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "code.parquet"
            instance = {"instance_id": "code-1", "problem_statement": "Implement negation.",
                        "test_patch": _new_archive_patch(_archive({
                            ".build_env/test_command.sh": "pytest tests/test_negation.py\n"})),
                        "extra_field": {"keep": [1, 2]}}
            pq.write_table(pa.Table.from_pylist([{"extra_info": {"instance_json": json.dumps(instance)}}]), source)
            result = normalize({"kind": "mimo_code", "source": "code"}, {"code": source})
            task = result["tasks"][0]
            self.assertEqual(task["task_id"], "code-1")
            self.assertEqual(task["metadata"]["instance"], instance)
            self.assertEqual(task["metadata"]["patch_analysis"]["commands"][0]["text"],
                             "pytest tests/test_negation.py\n")
            self.assertEqual(task["files"]["row_source"]["path"], "code.parquet")

    def test_invalid_archive_does_not_fall_back_to_extraction_wrapper(self):
        patch = _new_archive_patch("not base64") + (
            "diff --git a/mimo_test_command.sh b/mimo_test_command.sh\n"
            "new file mode 100755\n--- /dev/null\n+++ b/mimo_test_command.sh\n"
            "@@ -0,0 +1 @@\n+pytest test_fake.py || true\n")
        task = _task("c", domain="code", metadata={"instance": {"test_patch": patch}})
        findings = run_checks([task], ["code_static"])["findings"]
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["status"], "observation")
        self.assertIn("invalid base64", findings[0]["summary"])

    def test_schema_duplicates_and_unsupported_check_coverage(self):
        tasks = [_task("x"), _task("x"), _task("g", domain="general")]
        result = run_checks(tasks, ["schema", "code_static", "general_contract"])
        self.assertEqual(sum(f["summary"] == "Duplicate task ID" for f in result["findings"]), 1)
        self.assertEqual(result["coverage"]["code_static"],
                         {"eligible": 0, "evaluated": 0, "skipped": 3,
                          "skip_reasons": {"unsupported_domain": 3}})
        self.assertEqual(result["coverage"]["general_contract"]["skipped"], 2)


if __name__ == "__main__":
    unittest.main()
