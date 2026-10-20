"""Focused checks of explicit MiMo task and pinned grader contracts."""

import importlib.util
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from rlaudit.mimo_contracts import check_task, coverage_limits  # noqa: E402


def task(domain, instance=None, extra=None, prompt=""):
    return {"task_id": "row-1", "domain": domain, "prompt": prompt,
            "metadata": {"instance": instance or {}, "extra_info": extra or {}}, "files": {}}


class ContractTests(unittest.TestCase):
    def test_cyber_valid_and_different_grader_target(self):
        description = "AddressSanitizer: heap-buffer-overflow in function `parse` in file `src/x.c`"
        base = task("cyber", {"instance_id": "arvo_1", "docker_image": "arvo-rl:v1-arvo-1",
                              "description": description}, {"instance_id": "arvo_1"}, description)
        self.assertEqual(check_task(base), [])
        base["prompt"] = description.replace("`parse`", "`other`")
        findings = check_task(base)
        self.assertEqual([(f["status"], f["summary"]) for f in findings],
                         [("candidate", "Cyber prompt and grader target description differ")])

    def test_cyber_unparseable_target_and_image_mismatch(self):
        item = task("cyber", {"instance_id": "arvo_1", "docker_image": "arvo-rl:v1-arvo-2",
                               "description": "unparseable description"}, {"instance_id": "arvo_1"},
                    "unparseable description")
        findings = check_task(item)
        self.assertEqual({f["summary"] for f in findings},
                         {"Cyber description has no parseable target function",
                          "Cyber description has no parseable sanitizer and error type",
                          "Cyber image tag and instance ID differ"})

    def test_cyber_missing_description_uses_statement_fallback(self):
        description = "AddressSanitizer: heap-buffer-overflow in function `parse` in file `src/x.c`"
        item = task("cyber", {"instance_id": "arvo_1", "docker_image": "arvo-rl:v1-arvo-1",
                               "problem_statement": description + "\nReproduce this target."},
                    {"instance_id": "arvo_1"}, description)
        self.assertEqual(check_task(item), [])
        item["metadata"]["instance"]["description"] = ""
        self.assertEqual({f["summary"] for f in check_task(item)},
                         {"Cyber effective target description is missing"})

    def test_webdev_query_and_identifiers(self):
        base = task("webdev", {"instance_id": "x", "task_id": "x", "category": "website",
                               "docker_image": "webdev-rl-opensource:v2", "problem_statement": "Build a site"},
                    {"instance_id": "x"}, "Build a site")
        self.assertEqual(check_task(base), [])
        base["metadata"]["instance"]["task_id"] = "y"
        base["prompt"] = "Build a game"
        self.assertEqual({f["summary"] for f in check_task(base)},
                         {"Webdev prompt and grading query differ", "Webdev task identifiers differ"})

    def test_music_positive_constraints_and_coverage(self):
        base = task("music", extra={"nvoice_want": 3, "bpm": 129, "meter": "4/4"})
        self.assertEqual(check_task(base), [])
        base["metadata"]["extra_info"] = {"nvoice_want": 0, "bpm": True, "meter": "4/0"}
        self.assertEqual(len(check_task(base)), 3)
        self.assertEqual(len(coverage_limits({"cyber", "webdev", "music"})), 3)
        self.assertEqual(check_task(task("code")), [])

    def test_reviewed_webdev_arithmetic_component(self):
        path = ROOT / "examples" / "drivers" / "mimo_webdev_reward.py"
        spec = importlib.util.spec_from_file_location("mimo_webdev_reward", path)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        reward_one = module.load_component(ROOT / "research" / "mimo" / "other_subsets" / "contracts"
                                           / "sources" / "group_pick.py")
        self.assertEqual(reward_one(0.5, 0.9, 0), (0.0, []))
        self.assertEqual(reward_one(0.5, 0.9, 1), (0.8333, []))


if __name__ == "__main__":
    unittest.main()
