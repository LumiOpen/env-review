"""Contract tests use inert, temporary source fixtures, never dataset execution."""

import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from eval_audit.structural import InspectionError, main, screen_environment


class StructuralTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = self.root / "task_one"
        self.env.mkdir()
        self.write("manifest.json", {"uploads": []})
        self.write("verifier_meta.json", {"items": [], "check_code": ""})
        self.write("verify.py", "def verify():\n    return {}\n")

    def write(self, name, value):
        path = self.env / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2)
                        if not isinstance(value, str) else value, encoding="utf-8")

    def meta(self, items, code=""):
        self.write("verifier_meta.json", {"items": items, "check_code": code})

    def signals(self, inventory=None):
        return screen_environment(self.env, inventory)

    def detectors(self, inventory=None):
        return [s["detector_id"] for s in self.signals(inventory)]

    def test_clean_and_unknown_are_not_negative_labels(self):
        self.meta([{"id": "quality", "method": "llm", "weight": "0.5"}])
        self.assertEqual([], self.signals())

    def test_candidate_contract_and_exact_evidence_lines(self):
        self.meta([{"id": "x", "method": "rule", "fn": "absent"}])
        signals = self.signals(set())
        self.assertEqual(["rule_function_missing"], [s["detector_id"] for s in signals])
        for signal in signals:
            self.assertEqual({"detector_id", "task_id", "category", "claim", "evidence",
                              "assumptions", "severity"}, set(signal))
            self.assertEqual("task_one", signal["task_id"])
            self.assertTrue(signal["assumptions"])
            for evidence in signal["evidence"]:
                path = self.env / evidence["path"]
                lines = path.read_text().splitlines()
                self.assertEqual("\n".join(lines[evidence["line_start"] - 1:evidence["line_end"]]),
                                 evidence["quote"])

    def test_bad_json_and_python_are_distinct(self):
        self.write("manifest.json", '{\n  "uploads": [\n}')
        self.write("verify.py", "def broken(:\n")
        self.assertCountEqual(["invalid_json", "invalid_python"], self.detectors())

    def test_embedded_code_syntax_has_real_json_evidence(self):
        self.meta([], "def broken(:\n")
        signal = self.signals()[0]
        self.assertEqual("invalid_check_code", signal["detector_id"])
        self.assertIn("check_code", signal["evidence"][0]["quote"])
        self.assertIn("decoded line 1", signal["claim"])

    def test_nonstandard_json_constants_also_check_nonfinite_weight(self):
        self.write("verifier_meta.json", '{"items":[{"id":"x","weight":NaN}]}')
        self.assertCountEqual(["invalid_json", "weight_nonfinite"], self.detectors())

    def test_nonstandard_constant_evidence_ignores_strings(self):
        self.write("verifier_meta.json", '{\n"note": "NaN",\n"items": [{"id":"x", "weight":Infinity}]\n}')
        signal = next(s for s in self.signals() if s["detector_id"] == "invalid_json")
        self.assertEqual(3, signal["evidence"][0]["line_start"])
        self.assertIn("Infinity", signal["evidence"][0]["quote"])

    def test_parser_resource_limits_are_gaps_not_invalid_json(self):
        with mock.patch("eval_audit.structural.json.loads", side_effect=RecursionError("parser limit")):
            with self.assertRaises(InspectionError):
                self.signals()

    def test_minified_metadata_item_spans_and_decoys(self):
        self.write("verifier_meta.json", '{"note":"items", "items":[{"id":"a","weight":0},{"id":"b","weight":0}]}')
        self.assertEqual(["weights_all_zero"], self.detectors())

    def test_duplicate_ids_include_both_occurrences(self):
        self.meta([{"id": "重复"}, {"id": "重复"}])
        signal = self.signals()[0]
        self.assertEqual("duplicate_item_id", signal["detector_id"])
        self.assertEqual(2, len(signal["evidence"]))
        self.assertNotEqual(signal["evidence"][0]["line_start"], signal["evidence"][1]["line_start"])

    def test_malformed_metadata_is_a_candidate_not_a_scanner_crash(self):
        for value in ([], {"items": {}}, {"items": [None]}, {"items": [{"id": []}]},
                      {"items": [], "check_code": []}):
            with self.subTest(value=value):
                self.write("verifier_meta.json", value)
                self.assertIn("malformed_metadata", self.detectors())

    def test_missing_fn_field(self):
        self.meta([{"id": "x", "method": "rule"}])
        self.assertIn("rule_function_missing", self.detectors())

    def test_helper_and_import_and_assignment_bindings_are_not_missing(self):
        for code in ("def check(ws):\n    return {}\n", "from external import check\n", "check = external_callable\n"):
            with self.subTest(code=code):
                self.meta([{"id": "x", "method": "rule", "fn": "check"}], code)
                self.assertNotIn("rule_function_missing", self.detectors(set()))
        self.meta([{"id": "x", "method": "rule", "fn": "check"}])
        self.write("_helpers.py", "def check(ws):\n    return {}\n")
        self.assertNotIn("rule_function_missing", self.detectors(set()))

    def test_nested_function_does_not_supply_module_binding(self):
        self.meta([{"id": "x", "method": "rule", "fn": "check"}],
                  "def outer():\n    def check(ws):\n        pass\n")
        self.assertIn("rule_function_missing", self.detectors(set()))

    def test_dynamic_namespace_and_uncached_helper_are_unknown(self):
        for code in ("from external import *\n", "globals()['check'] = callback\n",
                     "install_checks(globals())\n"):
            with self.subTest(code=code):
                self.meta([{"id": "x", "method": "rule", "fn": "check"}], code)
                self.assertNotIn("rule_function_missing", self.detectors(set()))
        self.meta([{"id": "x", "method": "rule", "fn": "check"}])
        inventory = {"general/envs/task_one/_helpers.py"}
        self.assertNotIn("rule_function_missing", self.detectors(inventory))
        self.assertNotIn("rule_function_missing", self.detectors())

    def test_weight_types_follow_float_conversion(self):
        for weight, expected in ((None, "weight_malformed"), ({}, "weight_malformed"),
                                 ("bad", "weight_malformed"), ("NaN", "weight_nonfinite"),
                                 (float("inf"), "weight_nonfinite"), (-0.1, "weight_negative")):
            with self.subTest(weight=weight):
                self.meta([{"id": "x", "weight": weight}])
                self.assertIn(expected, self.detectors())

    def test_all_zero_weights_require_nonempty_nongate_set(self):
        self.meta([{"id": "x", "weight": 0}, {"id": "gate", "gate": True, "weight": 1}])
        self.assertIn("weights_all_zero", self.detectors())
        self.meta([{"id": "x", "weight": 0}, {"id": "implicit"}])
        self.assertNotIn("weights_all_zero", self.detectors())
        self.meta([{"id": "gate", "gate": True, "weight": 0}])
        self.assertNotIn("weights_all_zero", self.detectors())

    def test_implicit_sanity_weight_is_only_a_signal(self):
        self.meta([{"id": "quality", "tier": "critical", "weight": 0.3},
                   {"id": "sanity", "tier": "sanity"}])
        signal = self.signals()[0]
        self.assertEqual("implicit_sanity_weight", signal["detector_id"])
        self.assertEqual("review_signal", signal["category"])
        for sanity, other in (({"gate": True}, {"weight": 0.3}), ({"weight": 1}, {"weight": 0.3}),
                              ({}, {"weight": 1}), ({}, {})):
            self.meta([{"id": "quality", "tier": "critical", **other},
                       {"id": "sanity", "tier": "sanity", **sanity}])
            self.assertNotIn("implicit_sanity_weight", self.detectors())

    def test_uploads_use_authoritative_inventory_and_directory_prefixes(self):
        self.write("manifest.json", {"uploads": [{"source": "./workspace"}, {"source": "missing"}],
                                     "verifier": {"uploads": [{"source": "verify.py"}]}})
        inventory = {"general/envs/task_one/workspace/document.txt", "general/envs/task_one/missing_elsewhere"}
        signals = self.signals(inventory)
        self.assertEqual(["upload_source_absent"], [s["detector_id"] for s in signals])
        self.assertIn("missing", signals[0]["claim"])
        self.assertEqual([], self.signals())

    def test_upload_relative_parent_paths_resolve_and_absolute_paths_are_unknown(self):
        self.write("manifest.json", {"uploads": [{"source": "../shared.py"}, {"source": "/generated/path"}]})
        self.assertEqual([], self.signals({"general/envs/shared.py"}))

    def test_local_assets_satisfy_upload_existence(self):
        self.write("workspace/a.txt", "hello")
        self.write("manifest.json", {"uploads": [{"source": "workspace"}]})
        self.assertEqual([], self.signals(set()))

    def test_missing_core_files_are_inspection_gaps(self):
        (self.env / "verify.py").unlink()
        with self.assertRaises(InspectionError):
            self.signals()

    def test_source_is_never_executed(self):
        marker = self.root / "executed"
        code = f"from pathlib import Path\nPath({str(marker)!r}).touch()\n"
        self.write("verify.py", code)
        self.meta([], code)
        self.signals()
        self.assertFalse(marker.exists())

    def test_cli_reports_denominators_counts_and_gaps(self):
        self.meta([{"id": "a", "weight": -1}])
        (self.root / "uncached").mkdir()
        inventory = self.root / "inventory.raw"
        inventory.write_text(json.dumps({"siblings": [{"rfilename": "general/envs/task_one/verify.py"}]}))
        output = self.root / "report.json"
        with contextlib.redirect_stdout(io.StringIO()):
            status = main(["--root", str(self.root), "--inventory", str(inventory), "--output", str(output)])
        self.assertEqual(0, status)
        report = json.loads(output.read_text())
        self.assertEqual(2, report["environments_discovered"])
        self.assertEqual(1, report["environments_inspected"])
        self.assertEqual(1, report["environments_uninspectable"])
        self.assertEqual({"weight_negative": 1}, report["signals_by_detector"])
        self.assertEqual({"task_one": 1}, report["signals_by_task"])
        self.assertEqual(1, len(report["errors"]))
        self.assertEqual("candidates_only", report["review_status"])


if __name__ == "__main__":
    unittest.main()
