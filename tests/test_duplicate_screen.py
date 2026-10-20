"""Contract tests use inert, in-memory row fixtures, never dataset execution."""

import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from eval_audit.duplicate_screen import (
    InspectionError,
    build_report,
    group_by_prompt,
    is_sentinel_reference,
    main,
    normalize_reference,
    screen_rows,
)


def row(index, prompt, reference, passrate=None, rollouts=8, task_id=None):
    return {"task_id": task_id or f"task-{index}", "row_index": index, "prompt": prompt,
            "reference": reference, "passrate": passrate, "total_rollouts": rollouts,
            "total_correct_rollouts": None if passrate is None else passrate * rollouts,
            "shard": "train-00000-of-00001.parquet", "subset": "math"}


class NormalizeReferenceTests(unittest.TestCase):
    def test_collapses_cosmetic_latex(self):
        for left, right in [(r"2\sqrt 2", r"2\sqrt{2}"), (r"20^\circ", "20"),
                            (r"1600 \text{ square centimeters}", "1600"),
                            ("1/2", r"\frac{1}{2}"), (r"a>\frac12", r"a>\frac{1}{2}"),
                            (" 1000 ", "1000"), ("0", "000"), ("b = a^2c", "a^2c")]:
            with self.subTest(left=left, right=right):
                self.assertEqual(normalize_reference(left), normalize_reference(right))

    def test_preserves_genuinely_different_values(self):
        for left, right in [("27", "45"), ("31", "61"), ("554", "-1"), ("230", "-1")]:
            with self.subTest(left=left, right=right):
                self.assertNotEqual(normalize_reference(left), normalize_reference(right))

    def test_missing_reference_is_empty(self):
        self.assertEqual("", normalize_reference(None))

    def test_sentinels_recognized_without_claiming_others_valid(self):
        self.assertTrue(is_sentinel_reference("-1"))
        self.assertTrue(is_sentinel_reference(" N/A "))
        self.assertFalse(is_sentinel_reference("0"))
        self.assertFalse(is_sentinel_reference("554"))


class ScreenRowsTests(unittest.TestCase):
    def detectors(self, rows):
        return sorted({c["detector_id"] for c in screen_rows(rows)})

    def test_unique_prompts_raise_no_signal(self):
        rows = [row(0, "alpha", "1", 0.5), row(1, "beta", "2", 0.25)]
        self.assertEqual([], screen_rows(rows))

    def test_duplicate_prompt_reported_with_every_locator(self):
        rows = [row(0, "alpha", "1", 0.5), row(7, "alpha", "1", 0.5)]
        [candidate] = screen_rows(rows)
        self.assertEqual("duplicate_prompt", candidate["detector_id"])
        self.assertEqual([0, 7], [t["row_index"] for t in candidate["tasks"]])
        self.assertEqual(["task-0", "task-7"], [t["task_id"] for t in candidate["tasks"]])

    def test_conflicting_and_notation_variants_are_distinguished(self):
        conflicting = [row(0, "alpha", "27", 0.125), row(1, "alpha", "45", 0.625)]
        self.assertIn("conflicting_reference", self.detectors(conflicting))
        self.assertNotIn("notation_variant_reference", self.detectors(conflicting))

        notation = [row(0, "alpha", r"2\sqrt 2", 0.0), row(1, "alpha", r"2\sqrt{2}", 0.625)]
        self.assertIn("notation_variant_reference", self.detectors(notation))
        self.assertNotIn("conflicting_reference", self.detectors(notation))

    def test_passrate_compared_only_when_references_agree(self):
        # A conflicting reference explains a differing pass rate, so do not also flag it.
        self.assertNotIn("unstable_passrate",
                         self.detectors([row(0, "alpha", "27", 0.125), row(1, "alpha", "45", 0.625)]))
        self.assertIn("unstable_passrate",
                      self.detectors([row(0, "alpha", "27", 0.125), row(1, "alpha", "27", 0.625)]))

    def test_single_rollout_of_difference_is_not_a_signal(self):
        rows = [row(0, "alpha", "27", 0.500), row(1, "alpha", "27", 0.625)]
        self.assertNotIn("unstable_passrate", self.detectors(rows))

    def test_granularity_follows_the_largest_rollout_count(self):
        rows = [row(0, "alpha", "27", 0.0, rollouts=4), row(1, "alpha", "27", 0.25, rollouts=4)]
        self.assertNotIn("unstable_passrate", self.detectors(rows))

    def test_missing_passrate_never_fabricates_a_spread(self):
        rows = [row(0, "alpha", "27", None), row(1, "alpha", "27", 0.625)]
        self.assertNotIn("unstable_passrate", self.detectors(rows))

    def test_sentinel_reference_flagged_on_unique_rows_too(self):
        [candidate] = screen_rows([row(0, "alpha", "-1", 0.0)])
        self.assertEqual("sentinel_reference", candidate["detector_id"])
        self.assertEqual([0], [t["row_index"] for t in candidate["tasks"]])

    def test_grouping_preserves_split_order(self):
        groups = group_by_prompt([row(5, "alpha", "1"), row(2, "beta", "2"), row(9, "alpha", "1")])
        self.assertEqual([[5, 9], [2]], [[r["row_index"] for r in g] for g in groups.values()])


class ReportTests(unittest.TestCase):
    def test_report_separates_denominators_from_candidates(self):
        rows = [row(0, "alpha", "27", 0.125), row(1, "alpha", "45", 0.625), row(2, "beta", "3", 0.5)]
        report = build_report(rows, Path("/snapshot"), "math")
        self.assertEqual(3, report["rows_inspected"])
        self.assertEqual(2, report["distinct_prompts"])
        self.assertEqual(2, report["rows_with_any_signal"])
        self.assertEqual("candidates_only", report["review_status"])
        self.assertIn("conflicting_reference", report["signals_by_detector"])
        self.assertTrue(report["limitations"])

    def test_report_is_json_serializable_without_nan(self):
        report = build_report([row(0, "alpha", "1", 0.5)], Path("/snapshot"), None)
        json.dumps(report, allow_nan=False)

    def test_cli_requires_a_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
                main(["--root", str(Path(temp) / "absent"), "--output", str(Path(temp) / "out.json")])

    def test_missing_shards_are_an_inspection_error_not_an_empty_result(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises((InspectionError, SystemExit)):
                main(["--root", temp, "--output", str(Path(temp) / "out.json")])


if __name__ == "__main__":
    unittest.main()
