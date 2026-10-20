"""Catalog contracts, exercised with temporary YAML rather than corpus code."""

import contextlib
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest

import yaml

from eval_audit.catalog import build_index, main, validate_catalog


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.dataset = {
            "schema_version": "1", "id": "hf:org/sample",
            "source": {"provider": "huggingface", "url": "https://huggingface.co/datasets/org/sample", "revision": "a" * 40},
            "review_status": "exploring", "task_identity": {"fields": ["config", "split", "row_index"]},
        }
        self.finding = {
            "schema_version": "1", "id": "ER-01234567", "dataset": "hf:org/sample", "revision": "a" * 40,
            "title": "Source and grader disagree", "status": "candidate", "category": "grader_mismatch",
            "tasks": [{"id": "row:3", "config": "general", "split": "train", "row_index": 3}],
            "problem": {"description": "A check expects a different field.", "expected": "Read the declared field.", "actual": "The check reads another field."},
            "evidence": [{"source": "general/train.json", "quote": "field: expected", "line_start": 2, "line_end": 3}],
            "validation": {"method": "static", "summary": "Compared the declaration with the check at the pinned revision.", "assumptions": [], "not_run": ["Runtime grading"]},
            "provenance": {"discovered_by": "reviewer"},
        }
        self.write_dataset()
        self.write_finding()

    def write(self, relative, document):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(document if isinstance(document, str) else yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
        return path

    def write_dataset(self, document=None, directory="org/sample"):
        return self.write(f"env/{directory}/dataset.yaml", self.dataset if document is None else document)

    def write_finding(self, document=None, directory="org/sample", filename=None):
        document = self.finding if document is None else document
        return self.write(f"env/{directory}/findings/{filename or document['id']}.yaml", document)

    def messages(self):
        return "\n".join(error["message"] for error in validate_catalog(self.root))

    def test_valid_row_and_directory_tasks(self):
        self.finding["tasks"].append({"id": "directory-task", "path": "general/envs/directory-task"})
        self.write_finding()
        self.assertEqual([], validate_catalog(self.root))
        index = build_index(self.root)
        self.assertEqual("1", index["schema_version"])
        self.assertEqual(2, len(index["tasks"]))
        self.assertEqual("candidate", index["findings"][0]["status"])
        self.assertEqual("a" * 40, index["tasks"][0]["findings"][0]["source_revision"])

    def test_queued_dataset_without_findings(self):
        (self.root / "env/org/sample/findings/ER-01234567.yaml").unlink()
        self.dataset["review_status"] = "queued"
        self.write_dataset()
        self.assertEqual([], validate_catalog(self.root))
        index = build_index(self.root)
        self.assertEqual([], index["findings"])
        self.assertEqual([], index["tasks"])
        self.assertEqual("queued", index["datasets"][0]["review_status"])

    def test_historical_source_revision_is_preserved(self):
        self.finding["revision"] = "b" * 40
        self.write_finding()
        self.assertEqual([], validate_catalog(self.root))
        self.assertEqual("b" * 40, build_index(self.root)["findings"][0]["source_revision"])

    def test_malformed_yaml_and_unsafe_tags_are_errors(self):
        for text in ("schema_version: [", "!!python/object/apply:os.system ['false']", "!!map [a, b]"):
            with self.subTest(text=text):
                self.write_dataset(text)
                self.assertTrue(validate_catalog(self.root))

    def test_duplicate_yaml_keys_include_nested_keys(self):
        for text in ("id: first\nid: second\n", "validation:\n  summary: first\n  summary: second\n"):
            with self.subTest(text=text):
                self.write("env/org/sample/findings/ER-01234567.yaml", text)
                self.assertIn("duplicate", self.messages().lower())

    def test_recursive_yaml_and_non_json_values_are_errors(self):
        for text in ("task_identity: &recursive {value: *recursive}\n", "task_identity: {date: 2020-01-01}\n",
                     "task_identity: {number: .nan}\n", "task_identity: {1: value}\n"):
            with self.subTest(text=text):
                self.write_dataset(text)
                self.assertTrue(validate_catalog(self.root))

    def test_schema_rejects_extra_keys_except_task_identity(self):
        self.dataset["task_identity"]["custom"] = {"description": "Freeform", "exact": True}
        self.write_dataset()
        self.assertEqual([], validate_catalog(self.root))
        for target in (self.finding, self.finding["problem"], self.finding["validation"],
                       self.finding["tasks"][0], self.finding["evidence"][0], self.finding["provenance"]):
            with self.subTest(target=list(target)):
                target["unexpected"] = True
                self.write_finding()
                self.assertIn("Additional properties", self.messages())
                del target["unexpected"]
        self.write_finding()
        self.dataset["source"]["unexpected"] = True
        self.write_dataset()
        self.assertIn("Additional properties", self.messages())

    def test_required_fields_enums_and_pins(self):
        for field, value in (("schema_version", 1), ("revision", "main"), ("id", "ER-invalid"),
                             ("status", "approved"), ("category", "security"), ("title", "  "), ("tasks", []), ("evidence", [])):
            with self.subTest(field=field):
                finding = copy.deepcopy(self.finding)
                finding[field] = value
                self.write_finding(finding, filename="ER-01234567")
                self.assertTrue(validate_catalog(self.root))
        finding = copy.deepcopy(self.finding)
        del finding["validation"]
        self.write_finding(finding)
        self.assertIn("required", self.messages())

    def test_dataset_directory_source_and_finding_references_must_match(self):
        self.dataset["id"] = "hf:org/other"
        self.write_dataset()
        self.assertIn("identity", self.messages())
        self.dataset["id"] = "hf:org/sample"
        self.dataset["source"]["url"] = "https://huggingface.co/datasets/org/other"
        self.write_dataset()
        self.assertIn("URL", self.messages())
        self.dataset["source"]["url"] = "https://huggingface.co/datasets/org/sample"
        self.write_dataset()
        self.finding["dataset"] = "hf:org/other"
        self.write_finding()
        self.assertIn("dataset reference", self.messages())

    def test_filename_matches_finding_id(self):
        self.finding["id"] = "ER-ffffffff"
        self.write_finding(filename="ER-01234567")
        self.assertIn("filename", self.messages())

    def test_duplicate_finding_ids_across_datasets(self):
        dataset = copy.deepcopy(self.dataset)
        dataset["id"] = "hf:another/data"
        dataset["source"]["url"] = "https://huggingface.co/datasets/another/data"
        self.write_dataset(dataset, "another/data")
        finding = copy.deepcopy(self.finding)
        finding["dataset"] = "hf:another/data"
        self.write_finding(finding, "another/data")
        self.assertIn("Duplicate finding id", self.messages())

    def test_duplicate_task_ids_within_a_finding_are_errors(self):
        self.finding["tasks"].append({"id": "row:3", "row_index": 4})
        self.write_finding()
        self.assertIn("Duplicate task id", self.messages())

    def test_row_indices_are_nonnegative_integers_not_booleans(self):
        for value in (-1, True, 1.5, "1"):
            self.finding["tasks"][0]["row_index"] = value
            self.write_finding()
            self.assertTrue(validate_catalog(self.root))

    def test_source_and_task_paths_are_safe(self):
        for source in ("../secret", "a/../b", "/tmp/a", "C:/temp/a", "C:\\temp\\a", ".", "a\x00b", "https://example.org/file"):
            with self.subTest(source=source):
                self.finding["evidence"][0]["source"] = source
                self.write_finding()
                self.assertTrue(validate_catalog(self.root))
        self.finding["evidence"][0]["source"] = "general/not-cached.json"
        self.finding["tasks"][0]["path"] = "../task"
        self.write_finding()
        self.assertTrue(validate_catalog(self.root))
        del self.finding["tasks"][0]["path"]
        self.write_finding()
        self.assertEqual([], validate_catalog(self.root))

    def test_evidence_ranges_and_json_pointer(self):
        for fields in ({"line_start": 3, "line_end": 2}, {"line_start": 0}, {"line_end": 2},
                       {"line_start": True}, {"json_pointer": "items/0"}, {"json_pointer": "/items/~2"}):
            self.finding["evidence"] = [{"source": "data.json", "quote": "source", **fields}]
            self.write_finding()
            self.assertTrue(validate_catalog(self.root))
        self.finding["evidence"] = [{"source": "data.json", "quote": "source", "json_pointer": "/items/~0~1"}]
        self.write_finding()
        self.assertEqual([], validate_catalog(self.root))

    def test_confirmed_and_fixed_require_nonempty_validation_summary(self):
        for status in ("confirmed", "fixed"):
            self.finding["status"] = status
            self.finding["validation"]["summary"] = "  "
            self.write_finding()
            self.assertTrue(validate_catalog(self.root))

    def test_every_review_status_is_indexed_without_promotion(self):
        for status in ("candidate", "confirmed", "behavior_only", "disputed", "rejected", "fixed"):
            self.finding["status"] = status
            self.write_finding()
            index = build_index(self.root)
            self.assertEqual(status, index["findings"][0]["status"])
            self.assertEqual(status, index["tasks"][0]["findings"][0]["status"])

    def test_answer_exposure_and_environment_specification_are_independent_categories(self):
        for category in ("answer_exposure", "environment_specification"):
            with self.subTest(category=category):
                self.finding["category"] = category
                self.write_finding()
                self.assertEqual([], validate_catalog(self.root))
                index = build_index(self.root)
                self.assertEqual(category, index["findings"][0]["category"])
                self.assertEqual(category, index["tasks"][0]["findings"][0]["category"])
                self.assertEqual("candidate", index["findings"][0]["status"])

    def test_template_fits_schema_after_setting_dataset_reference(self):
        template = Path(__file__).resolve().parents[1] / "templates/finding.yaml"
        finding = yaml.safe_load(template.read_text())
        finding["dataset"] = self.dataset["id"]
        self.write_finding(finding)
        self.assertEqual([], validate_catalog(self.root))

    def test_orphan_finding_cannot_be_silently_skipped(self):
        (self.root / "env/org/sample/dataset.yaml").unlink()
        self.assertIn("manifest", self.messages())

    def test_finding_yml_extension_is_reported(self):
        path = self.root / "env/org/sample/findings/ER-01234567.yaml"
        path.rename(path.with_suffix(".yml"))
        self.assertIn(".yaml", self.messages())

    def test_index_groups_identical_task_references_and_preserves_statuses(self):
        second = copy.deepcopy(self.finding)
        second.update(id="ER-00000000", status="behavior_only")
        self.write_finding(second)
        index = build_index(self.root)
        self.assertEqual(["ER-00000000", "ER-01234567"], [f["id"] for f in index["findings"]])
        self.assertEqual(1, len(index["tasks"]))
        refs = index["tasks"][0]["findings"]
        self.assertEqual(["behavior_only", "candidate"], [ref["status"] for ref in refs])
        self.assertEqual(["a" * 40, "a" * 40], [ref["source_revision"] for ref in refs])
        self.assertEqual(index, build_index(self.root))

    def test_index_separates_identical_task_locators_at_different_revisions(self):
        second = copy.deepcopy(self.finding)
        second.update(id="ER-00000000", status="behavior_only", revision="b" * 40)
        self.write_finding(second)
        tasks = build_index(self.root)["tasks"]
        self.assertEqual(2, len(tasks))
        self.assertEqual(["a" * 40, "b" * 40], [task["source_revision"] for task in tasks])
        self.assertEqual(["ER-01234567", "ER-00000000"], [task["findings"][0]["id"] for task in tasks])
        for task in tasks:
            self.assertEqual("row:3", task["id"])
            self.assertEqual(3, task["row_index"])
            self.assertEqual(1, len(task["findings"]))
            self.assertEqual(task["source_revision"], task["findings"][0]["source_revision"])

    def test_index_does_not_merge_distinct_row_locations(self):
        second = copy.deepcopy(self.finding)
        second["id"] = "ER-00000000"
        second["tasks"][0]["config"] = "another"
        self.write_finding(second)
        self.assertEqual(2, len(build_index(self.root)["tasks"]))

    def test_index_refuses_invalid_catalog_and_cli_preserves_existing_output(self):
        self.finding["status"] = "invalid"
        self.write_finding()
        with self.assertRaises(ValueError):
            build_index(self.root)
        output = self.write("reports/index.json", "existing output\n")
        with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(1, main(["index", "--root", str(self.root), "--output", str(output)]))
        self.assertEqual("existing output\n", output.read_text())

    def test_cli_validation_and_deterministic_index(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(0, main(["validate", "--root", str(self.root)]))
            self.assertEqual(0, main(["index", "--root", str(self.root), "--output", "reports/index.json"]))
        path = self.root / "reports/index.json"
        content = path.read_text()
        self.assertEqual(build_index(self.root), json.loads(content))
        with contextlib.redirect_stdout(io.StringIO()):
            main(["index", "--root", str(self.root), "--output", "reports/index.json"])
        self.assertEqual(content, path.read_text())

    def test_error_shape_and_missing_root(self):
        errors = validate_catalog(self.root / "missing")
        self.assertTrue(errors)
        self.assertEqual({"path", "location", "message"}, set(errors[0]))


if __name__ == "__main__":
    unittest.main()
