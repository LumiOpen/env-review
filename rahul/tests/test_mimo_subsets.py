"""Regression tests for inert Cyber, Webdev, and Music parquet normalization."""

import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from rlaudit.adapters import normalize, run_checks  # noqa: E402
from rlaudit.manifest import validate  # noqa: E402


@unittest.skipUnless(importlib.util.find_spec("pyarrow") is not None, "optional pyarrow unavailable")
class MimoSubsetTests(unittest.TestCase):
    def _normalize_rows(self, domain, rows, adapter=None):
        import pyarrow as pa
        import pyarrow.parquet as pq

        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / f"{domain}.parquet"
            pq.write_table(pa.Table.from_pylist(rows), source)
            result = normalize({"kind": f"mimo_{domain}", "source": "subset", **(adapter or {})},
                               {"subset": source})
            expected_hash = hashlib.sha256(source.read_bytes()).hexdigest()
        return result, expected_hash

    def test_all_domains_preserve_source_row_and_native_id(self):
        for domain in ("cyber", "webdev", "music"):
            with self.subTest(domain=domain):
                instance = {"instance_id": "native-1", "problem_statement": "Build it", "extra": [1, 2]}
                extra = ({"src_id": "song-1", "lang": "en", "bpm": 120} if domain == "music" else
                         {"instance_id": "native-1", "instance_json": json.dumps(instance), "index": 7})
                row = {"prompt": [{"role": "system", "content": "Context"},
                                  {"role": "user", "content": "Do the task"}],
                       "data_source": {"cyber": "arvo", "webdev": "blackbox/webdev", "music": "music"}[domain],
                       "reward_model": {"style": "rule", "ground_truth": "x"},
                       "extra_info": extra}
                result, expected_hash = self._normalize_rows(domain, [row])
                self.assertEqual(result["coverage"],
                                 {"kind": f"mimo_{domain}", "total": 1, "selected": 1, "skipped": 0})
                self.assertEqual(result["observations"], [])
                task = result["tasks"][0]
                self.assertEqual(task["task_id"], f"mimo-{domain}-000000")
                self.assertEqual(task["domain"], domain)
                self.assertEqual(task["prompt"], "Context\n\nDo the task")
                self.assertEqual(task["metadata"]["row"], row)
                self.assertEqual(task["metadata"]["row_index"], 0)
                self.assertEqual(task["metadata"]["extra_info"], extra)
                self.assertEqual(task["metadata"]["source_id"],
                                 "song-1" if domain == "music" else "native-1")
                self.assertEqual(task["metadata"]["instance"], {} if domain == "music" else instance)
                self.assertEqual(task["files"]["row_source"],
                                 {"source": "subset", "path": f"{domain}.parquet", "sha256": expected_hash})

    def test_selection_and_malformed_rows_keep_evidence(self):
        rows = [
            {"data_source": "arvo", "prompt": [{"role": "user", "content": "Valid"}],
             "extra_info": {"instance_id": "one", "instance_json": '{"problem_statement":"valid"}'}},
            {"data_source": "arvo", "prompt": [{"role": "user", "content": None}],
             "extra_info": {"instance_id": None, "instance_json": "{broken"}},
        ]
        result, _ = self._normalize_rows("cyber", rows, {"ids": ["mimo-cyber-000001"]})
        self.assertEqual(result["coverage"],
                         {"kind": "mimo_cyber", "total": 2, "selected": 1, "skipped": 1})
        task = result["tasks"][0]
        self.assertEqual(task["task_id"], "mimo-cyber-000001")
        self.assertEqual(task["prompt"], "")
        self.assertEqual(task["metadata"]["instance"], {})
        self.assertEqual(task["metadata"]["row_index"], 1)
        self.assertEqual({item["summary"] for item in result["observations"]},
                         {"extra_info.instance_id is missing or invalid", "prompt messages have invalid structure",
                          "prompt messages contain no text", "instance_json is invalid JSON: Expecting property name enclosed in double quotes"})
        self.assertTrue(all(item["status"] == "error" and item["detail"]["row_index"] == 1
                            for item in result["observations"]))
        with self.assertRaisesRegex(ValueError, "unknown task IDs"):
            self._normalize_rows("cyber", rows, {"ids": ["missing"]})

    def test_wrong_data_source_is_a_row_error_with_source_evidence(self):
        row = {"data_source": "music", "prompt": [{"role": "user", "content": "Investigate"}],
               "extra_info": {"instance_id": "case-1",
                              "instance_json": '{"instance_id":"case-1"}'}}
        result, _ = self._normalize_rows("cyber", [row])
        self.assertEqual(result["tasks"][0]["metadata"]["row"]["data_source"], "music")
        self.assertEqual(result["observations"],
                         [{"task_id": "mimo-cyber-000000", "status": "error",
                           "summary": "data_source disagrees with adapter kind",
                           "detail": {"row_index": 0, "actual": "music", "expected": "arvo"}}])

    def test_repeated_native_ids_are_visible_even_when_one_row_selected(self):
        rows = [{"data_source": "music", "prompt": [{"role": "user", "content": prompt}],
                 "extra_info": {"src_id": "song-1", "bpm": 120}}
                for prompt in ("First variation", "Second variation")]
        result, _ = self._normalize_rows("music", rows, {"ids": ["mimo-music-000001"]})
        self.assertEqual(result["coverage"]["selected"], 1)
        self.assertEqual(result["tasks"][0]["task_id"], "mimo-music-000001")
        self.assertEqual(result["observations"],
                         [{"task_id": "mimo-music-000001", "summary": "repeated native source ID",
                           "detail": {"source_id": "song-1", "count": 2, "row_indices": [0, 1],
                                      "row_indices_truncated": False}}])

    def test_manifest_requires_pinned_pyarrow_for_each_subset(self):
        for domain in ("cyber", "webdev", "music"):
            with self.subTest(domain=domain):
                config = {"schema_version": "rlaudit.pipeline/v1", "name": "subset",
                          "sources": [{"id": "subset", "path": "subset.parquet"}],
                          "adapter": {"kind": f"mimo_{domain}", "source": "subset"},
                          "checks": ["mimo_contract"]}
                with self.assertRaisesRegex(ValueError, "pyarrow version pin"):
                    validate(config)
                config["execution"] = {"dependencies": {"pyarrow": "24.0.0"}}
                normalized = validate(config)
                self.assertEqual(normalized["checks"], ["schema", "mimo_contract"])

    def test_domain_checks_skip_invalid_task_schema(self):
        valid = {"task_id": "mimo-music-000000", "domain": "music", "prompt": "compose",
                 "metadata": {"row_index": 0, "row": {}, "extra_info": {}, "instance": {}}, "files": {}}
        invalid = {**valid, "task_id": "broken", "metadata": "invalid"}
        result = run_checks([invalid, valid], ["schema", "code_static", "general_contract", "mimo_contract"])
        self.assertTrue(any(item["task_id"] == "broken" and item["summary"] == "Invalid normalized task fields"
                            for item in result["findings"]))
        self.assertEqual(result["coverage"]["code_static"]["skip_reasons"],
                         {"invalid_task_schema": 1, "unsupported_domain": 1})
        self.assertEqual(result["coverage"]["general_contract"]["skip_reasons"],
                         {"invalid_task_schema": 1, "unsupported_domain": 1})
        self.assertEqual(result["coverage"]["mimo_contract"]["skip_reasons"],
                         {"invalid_task_schema": 1})

    def test_pinned_subsets_fully_normalize_when_available(self):
        raw = Path(__file__).resolve().parents[1] / "research" / "mimo" / "other_subsets" / "raw"
        expected = {"cyber": 1000, "webdev": 2093, "music": 1000}
        if not all((raw / f"{domain}.parquet").is_file() for domain in expected):
            self.skipTest("pinned MiMo subset files are not present")
        for domain, count in expected.items():
            with self.subTest(domain=domain):
                source = raw / f"{domain}.parquet"
                adapter = {"kind": f"mimo_{domain}", "source": "subset"}
                first = normalize(adapter, {"subset": source})
                second = normalize(adapter, {"subset": source})
                self.assertEqual(first, second)
                self.assertEqual(first["coverage"]["total"], count)
                self.assertEqual(len(first["tasks"]), count)
                self.assertEqual(first["observations"], [])
                self.assertEqual(len({task["task_id"] for task in first["tasks"]}), count)
                self.assertEqual(run_checks(first["tasks"], ["schema"])["findings"], [])


if __name__ == "__main__":
    unittest.main()
