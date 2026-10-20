import unittest
from eval_audit.registry import summarize_run


class RegistryTests(unittest.TestCase):
    def test_unknown_candidates_and_unflagged_tasks_are_not_negatives(self):
        result = summarize_run("run", ["a", "b"], ["c1", "c2"], [
            {"run_id": "run", "candidate_id": "c1", "decision": "confirmed", "case_ids": ["case-1"]}
        ])
        self.assertEqual(result["candidate_count"], 2)
        self.assertEqual(result["unreviewed_count"], 1)
        self.assertEqual(result["decisions"], {"confirmed": 1})
        self.assertIsNone(result["task_false_positive_rate"])
        self.assertIsNone(result["recall"])

    def test_other_runs_do_not_contribute(self):
        result = summarize_run("run", ["a"], ["c1"], [
            {"run_id": "other", "candidate_id": "c1", "decision": "rejected", "case_ids": []}
        ])
        self.assertEqual(result["unreviewed_count"], 1)

    def test_duplicate_adjudications_and_unknown_candidates_rejected(self):
        verdict = {"run_id": "run", "candidate_id": "c1", "decision": "rejected", "case_ids": []}
        with self.assertRaises(ValueError):
            summarize_run("run", ["a"], ["c1"], [verdict, verdict])
        with self.assertRaises(ValueError):
            summarize_run("run", ["a"], [], [verdict])


if __name__ == "__main__":
    unittest.main()
