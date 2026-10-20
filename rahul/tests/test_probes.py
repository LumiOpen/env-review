import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from rlaudit.probes import _docker_memory, _docker_command, run_probes


TOY = ROOT / "examples/drivers/toy_reward.py"


class ProbeTests(unittest.TestCase):
    def test_docker_forwards_stdin_and_overrides_entrypoint(self):
        command = _docker_command("test-case", "image@sha256:" + "0"*64,
                                  ["python3", "/sources/driver"], Path("/tmp/work"),
                                  {"driver":Path("/tmp/inputs/driver.py")}, 2, "2g")
        self.assertIn("-i", command)
        self.assertIn("--network", command)
        self.assertIn("none", command)
        self.assertIn("--memory", command)
        self.assertIn("--entrypoint", command)
        self.assertEqual(command[-1], "/sources/driver")

    def test_docker_memory_matches_slurm_units(self):
        self.assertEqual(_docker_memory("2G"), "2g")
        self.assertEqual(_docker_memory("2048"), "2048m")

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.run_dir = Path(self.temp.name)
        inputs = self.run_dir / "inputs"
        inputs.mkdir()
        self.driver = inputs / "driver.py"
        shutil.copyfile(TOY, self.driver)
        self.tasks = [{"task_id": "toy", "prompt": "toy task"}]
        self.execution = {"allow_trusted_process": True}

    def probe(self, cases, relation=None):
        return [{
            "id": "p", "task_ids": ["toy"], "command": ["{python}", "{source:driver}"],
            "cases": cases, "executor": "trusted_process", "scope": "component",
            "relation": relation or {"kind": "invariant", "justification": "same integer", "tolerance": 0.0},
        }]

    def run_checked(self, probes, execution=None):
        with patch.dict(os.environ, {"SLURM_JOB_PARTITION": "amd-tw-verification", "SLURM_JOB_ID": "12345"}):
            return run_probes(probes, self.tasks, {"driver": self.driver}, self.run_dir,
                              self.execution if execution is None else execution)

    def test_format_sensitive_toy_is_candidate(self):
        cases = [{"id": "grouped", "input": {"answer": "1,000"}},
                 {"id": "plain", "input": {"answer": "1000"}}]
        result = self.run_checked(self.probe(cases))
        self.assertEqual(result["results"][0]["status"], "candidate_violation")
        self.assertEqual(result["results"][0]["scores"], [1.0, 0.0])
        self.assertEqual(result["findings"][0]["evidence_level"], "component_reproduction")
        for case in result["results"][0]["observations"]:
            self.assertTrue(Path(case["input_path"]).exists())
            self.assertTrue(Path(case["stdout_path"]).exists())
            self.assertTrue(Path(case["result_path"]).exists())
            self.assertEqual(json.loads(Path(case["stdout_path"]).read_text())["reward"], case["reward"])

    def test_nondecreasing_state_holds_only_in_sample(self):
        cases = [{"id": "a1", "input": {"state": {"position": 0}, "action": 1}},
                 {"id": "a2", "input": {"state": {"position": 0}, "action": 2}}]
        relation = {"kind": "nondecreasing", "justification": "higher action", "tolerance": 0.0}
        result = self.run_checked(self.probe(cases, relation))
        self.assertEqual(result["results"][0]["status"], "relation_holds_in_sample")
        self.assertEqual(result["results"][0]["scores"], [0.1, 0.2])
        self.assertEqual(result["findings"], [])

    def test_requires_slurm_and_trusted_opt_in(self):
        cases = [{"id": "x", "input": {"answer": "1,000"}},
                 {"id": "y", "input": {"answer": "1000"}}]
        with patch.dict(os.environ, {"SLURM_JOB_PARTITION": "login", "SLURM_JOB_ID": "12345"}):
            with self.assertRaisesRegex(ValueError, "SLURM_JOB_PARTITION"):
                run_probes(self.probe(cases), self.tasks, {"driver": self.driver}, self.run_dir,
                           self.execution)
        with patch.dict(os.environ, {"SLURM_JOB_PARTITION": "amd-tw-verification", "SLURM_JOB_ID": ""}):
            with self.assertRaisesRegex(ValueError, "SLURM_JOB_ID"):
                run_probes(self.probe(cases), self.tasks, {"driver": self.driver}, self.run_dir,
                           self.execution)
        with self.assertRaisesRegex(ValueError, "allow_trusted_process"):
            self.run_checked(self.probe(cases), {})

    def test_timeout_is_inconclusive(self):
        self.driver.write_text("import time\ntime.sleep(5)\n")
        cases = [{"id": "slow", "input": {"answer": "x"}}]
        relation = {"kind": "expected", "justification": "fixed toy", "tolerance": 0.0,
                    "values": [1.0]}
        result = self.run_checked(self.probe(cases, relation),
                                  {"allow_trusted_process": True, "timeout_seconds": 0.1})
        item = result["results"][0]
        self.assertEqual(item["status"], "inconclusive")
        self.assertEqual(item["observations"][0]["error"], "timeout")
        self.assertEqual(result["findings"], [])

    def test_malformed_and_nonfinite_are_inconclusive(self):
        for code in ("print('not json')", "print('{\"reward\": NaN}')"):
            with self.subTest(code=code), tempfile.TemporaryDirectory() as temp:
                run_dir = Path(temp)
                driver = run_dir / "inputs" / "driver.py"
                driver.parent.mkdir()
                driver.write_text(code + "\n")
                probe = self.probe([{"id": "x", "input": {"answer": "x"}}],
                                   {"kind": "expected", "justification": "fixed", "tolerance": 0.0,
                                    "values": [1.0]})
                with patch.dict(os.environ, {"SLURM_JOB_PARTITION": "amd-tw-verification", "SLURM_JOB_ID": "12345"}):
                    result = run_probes(probe, self.tasks, {"driver": driver}, run_dir,
                                        self.execution)
                self.assertEqual(result["results"][0]["status"], "inconclusive")
                self.assertEqual(result["results"][0]["observations"][0]["error"], "malformed_output")

    def test_output_cap_is_inconclusive(self):
        self.driver.write_text("print('x' * 2048)\n")
        relation = {"kind": "expected", "justification": "fixed", "tolerance": 0.0,
                    "values": [1.0]}
        result = self.run_checked(self.probe([{"id": "x", "input": {"answer": "x"}}], relation),
                                  {"allow_trusted_process": True, "max_output_bytes": 128})
        observed = result["results"][0]["observations"][0]
        self.assertEqual(observed["error"], "output_limit")
        self.assertLessEqual(Path(observed["stdout_path"]).stat().st_size, 128)

    def test_scheduler_gpu_visibility_is_preserved_without_credentials(self):
        self.driver.write_text("import json,os\nprint(json.dumps({'reward': int(os.getenv('ROCR_VISIBLE_DEVICES') == '1' and os.getenv('RLAUDIT_TEST_SECRET') is None)}))\n")
        cases = [{"id":"a", "input":{}}, {"id":"b", "input":{}}]
        relation = {"kind":"expected", "justification":"Allocation restrictions preserved; other environment excluded", "tolerance":0, "values":[1,1]}
        with patch.dict(os.environ, {"ROCR_VISIBLE_DEVICES":"1", "RLAUDIT_TEST_SECRET":"dummy"}):
            result = self.run_checked(self.probe(cases, relation))
        self.assertEqual(result["results"][0]["scores"], [1.0,1.0])

    def test_module_driver_uses_recorded_engine_and_excludes_host_pythonpath(self):
        engine = self.run_dir / "engine"
        package = engine / "rlaudit"
        package.mkdir(parents=True)
        (package / "__init__.py").write_text("")
        (package / "snapshot_probe.py").write_text(
            "import json,os,sys\n"
            "from pathlib import Path\n"
            "from importlib.util import find_spec\n"
            "print(json.dumps({'reward': int(os.getenv('PYTHONPATH') == str(Path(__file__).resolve().parents[1]) "
            "and find_spec('untrusted_host_module') is None "
            "and os.getenv('RLAUDIT_TEST_SECRET') is None)}))\n"
        )
        untrusted = self.run_dir / "untrusted-pythonpath"
        untrusted.mkdir()
        (untrusted / "untrusted_host_module.py").write_text("raise RuntimeError('must not import')\n")
        cases = [{"id": "one", "input": {}}, {"id": "two", "input": {}}]
        probes = self.probe(cases, {"kind": "expected", "values": [1, 1],
                                    "justification": "Only frozen engine imports are available"})
        probes[0]["command"] = ["{python}", "-m", "rlaudit.snapshot_probe"]
        with patch.dict(os.environ, {"PYTHONPATH": str(untrusted), "RLAUDIT_TEST_SECRET": "dummy"}):
            result = self.run_checked(probes)
        self.assertEqual(result["results"][0]["scores"], [1.0, 1.0])

    def test_case_bound_and_docker_digest(self):
        cases = [{"id": "a", "input": {"answer": "1,000"}},
                 {"id": "b", "input": {"answer": "1000"}}]
        with self.assertRaisesRegex(ValueError, "max_probe_cases"):
            self.run_checked(self.probe(cases), {"allow_trusted_process": True, "max_probe_cases": 1})
        docker = self.probe(cases)
        docker[0]["executor"] = "docker"
        docker[0]["image"] = "python:latest"
        with self.assertRaisesRegex(ValueError, "@sha256"):
            self.run_checked(docker)

    def test_relations_are_evaluated_per_task(self):
        self.tasks.append({"task_id": "other", "prompt": "second toy task"})
        self.driver.write_text(
            "import json,sys\n"
            "payload=json.load(sys.stdin)\n"
            "print(json.dumps({'reward': 0 if payload['task']['task_id']=='toy' else 1}))\n"
        )
        cases = [{"id": "first", "input": {}}, {"id": "second", "input": {}}]
        invariant = self.probe(cases, {"kind": "invariant", "justification": "constant per task"})[0]
        invariant["id"] = "invariant"
        invariant["task_ids"] = ["toy", "other"]
        expected = self.probe(cases, {"kind": "expected", "justification": "zero per case",
                                      "values": [0, 0]})[0]
        expected["id"] = "expected"
        expected["task_ids"] = ["toy", "other"]
        result = self.run_checked([invariant, expected])
        by_key = {(r["probe_id"], r["task_id"]): r for r in result["results"]}
        self.assertEqual(len(by_key), 4)
        self.assertTrue(by_key["invariant", "toy"]["relation_satisfied"])
        self.assertTrue(by_key["invariant", "other"]["relation_satisfied"])
        self.assertTrue(by_key["expected", "toy"]["relation_satisfied"])
        self.assertFalse(by_key["expected", "other"]["relation_satisfied"])
        self.assertEqual([(f["check_id"], f["task_id"]) for f in result["findings"]],
                         [("probe:expected", "other")])


if __name__ == "__main__":
    unittest.main()
