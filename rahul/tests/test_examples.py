"""Static consistency checks for the checked-in, synthetic local fixtures."""
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "examples/local/pipeline.json"
TASKS_PATH = ROOT / "examples/local/tasks.jsonl"


class LocalExampleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        cls.tasks = [json.loads(line) for line in TASKS_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]
        cls.task_by_id = {task["task_id"]: task for task in cls.tasks}

    def test_pipeline_sources_resolve_relative_to_config(self):
        sources = {source["id"]: source for source in self.config["sources"]}
        self.assertEqual(set(sources), {"tasks", "driver"})
        for source in sources.values():
            self.assertTrue((CONFIG_PATH.parent / source["path"]).resolve().is_file())
        self.assertEqual(self.config["adapter"]["source"], "tasks")
        self.assertEqual(self.config["adapter"]["kind"], "local_jsonl")

    def test_task_records_have_canonical_shape_and_unique_ids(self):
        self.assertEqual(len(self.tasks), 2)
        self.assertEqual(len(self.task_by_id), len(self.tasks))
        sources = {source["id"]: source for source in self.config["sources"]}
        for task in self.tasks:
            self.assertEqual(set(task), {"task_id", "domain", "prompt", "metadata", "files"})
            self.assertIsInstance(task["task_id"], str)
            self.assertIsInstance(task["prompt"], str)
            self.assertIsInstance(task["metadata"], dict)
            for ref in task["files"].values():
                self.assertIn(ref["source"], sources)
                source_path = (CONFIG_PATH.parent / sources[ref["source"]]["path"]).resolve()
                self.assertTrue(source_path.is_file())
                self.assertIn(ref["path"], ("", ".", source_path.name))

    def test_probe_task_ids_and_cases_match_the_examples(self):
        probes = {probe["id"]: probe for probe in self.config["probes"]}
        self.assertEqual(set(probes), {"format-reward-equivalence", "toy-state-reward-transition"})
        for probe in probes.values():
            self.assertTrue(set(probe["task_ids"]).issubset(self.task_by_id))
            self.assertEqual(len(probe["cases"]), 2)
            self.assertEqual(len({case["id"] for case in probe["cases"]}), 2)
            self.assertIn(probe["relation"]["kind"], {"invariant", "nondecreasing", "expected"})
            self.assertTrue(probe["relation"]["justification"])
            self.assertEqual(probe["executor"], "trusted_process")
            self.assertEqual(probe["scope"], "component")

        format_cases = probes["format-reward-equivalence"]["cases"]
        self.assertEqual([case["input"]["answer"] for case in format_cases], ["1,000", "1000"])
        self.assertEqual(set(probes["format-reward-equivalence"]["task_ids"]), {"format-reward"})
        state_probe = probes["toy-state-reward-transition"]
        self.assertEqual(set(state_probe["task_ids"]), {"toy-state"})
        self.assertEqual(state_probe["relation"]["kind"], "expected")
        self.assertEqual(state_probe["relation"]["values"], [0.1, 0.2])
        self.assertEqual([case["input"]["action"] for case in state_probe["cases"]], [1, 2])
        self.assertEqual(self.task_by_id["toy-state"]["metadata"]["probe_status"], "scoped_reward_transition_checked")
        self.assertIn("no broader state dynamics", self.task_by_id["toy-state"]["metadata"]["limitations"])
        self.assertTrue(self.config["execution"]["allow_trusted_process"])
        self.assertEqual(self.config["execution"]["partition"], "amd-tw-verification")


if __name__ == "__main__":
    unittest.main()
