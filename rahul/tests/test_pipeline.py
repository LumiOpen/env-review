import contextlib
import copy
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from rlaudit.cli import main
from rlaudit.manifest import validate
from rlaudit.pipeline import compare, execute, require_compute
from rlaudit.snapshot import freeze, sha256, verify
from rlaudit.slurm import submit


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.tasks = self.root / "tasks.jsonl"
        self.tasks.write_text(json.dumps({"task_id":"toy", "domain":"toy", "prompt":"Equivalent integers", "metadata":{}, "files":{}}) + "\n")
        self.driver = self.root / "driver.py"
        shutil.copyfile(ROOT / "examples/drivers/toy_reward.py", self.driver)
        self.config = {
            "schema_version":"rlaudit.pipeline/v1", "name":"test",
            "sources":[{"id":"tasks", "path":"tasks.jsonl"}, {"id":"driver", "path":"driver.py"}],
            "adapter":{"kind":"local_jsonl", "source":"tasks"},
            "checks":["schema", "code_static"],
            "probes":[{"id":"numeric", "task_ids":["toy"], "executor":"trusted_process", "scope":"component",
                       "command":["{python}", "{source:driver}"],
                       "cases":[{"id":"grouped", "input":{"answer":"1,000"}}, {"id":"plain", "input":{"answer":"1000"}}],
                       "relation":{"kind":"invariant", "justification":"Both encode integer1000", "tolerance":0}}],
            "execution":{"allow_trusted_process":True},
        }
        self.manifest = self.root / "pipeline.json"
        self.save()

    def save(self):
        self.manifest.write_text(json.dumps(self.config))

    def compute(self):
        return patch.dict(os.environ, {"SLURM_JOB_PARTITION":"amd-tw-verification", "SLURM_JOB_ID":"unit-test"})

    def test_manifest_rejects_typos_unsafe_execution_and_nonfinite_data(self):
        for change in [
            lambda c: c.update(checkz=[]),
            lambda c: c["execution"].update(partition="other"),
            lambda c: c["execution"].update(allow_trusted_process=False),
            lambda c: c["probes"][0]["relation"].update(tolerance=float("nan")),
            lambda c: c["probes"][0]["cases"][0].pop("input"),
        ]:
            candidate = copy.deepcopy(self.config)
            change(candidate)
            with self.assertRaises(ValueError):
                validate(candidate)

    def test_noop_audit_is_rejected_and_schema_cannot_be_disabled(self):
        config = copy.deepcopy(self.config)
        config.update(checks=[], probes=[])
        with self.assertRaisesRegex(ValueError, "at least one"):
            validate(config)
        config["checks"] = ["code_static"]
        self.assertEqual(validate(config)["checks"], ["schema", "code_static"])

    def test_invalid_task_schema_blocks_probes_and_marks_data_errors(self):
        self.tasks.write_text(json.dumps({"task_id":"toy", "metadata":{}, "files":{}}) + "\n")
        self.config["checks"] = ["code_static"]
        self.save()
        with self.compute():
            report = execute(self.manifest, self.root / "invalid")
        self.assertEqual(report["status"], "completed_with_data_errors")
        self.assertEqual(report["coverage"]["probes"]["skipped_requested_probes"], 1)
        self.assertEqual(report["probe_results"], [])

    def test_bad_record_does_not_block_independent_valid_probe_target(self):
        records = [
            {"task_id":"toy", "domain":"toy", "prompt":"Equivalent integers", "metadata":{}, "files":{}},
            {"task_id":"bad", "domain":"code", "prompt":"Malformed metadata", "metadata":"invalid", "files":{}},
        ]
        self.tasks.write_text("".join(json.dumps(task) + "\n" for task in records))
        self.config["probes"][0]["task_ids"] = ["bad", "toy"]
        self.save()
        with self.compute():
            report = execute(self.manifest, self.root / "partial")
        self.assertEqual(report["status"], "completed_with_data_errors")
        self.assertEqual([r["task_id"] for r in report["probe_results"]], ["toy"])
        self.assertEqual(report["probe_results"][0]["scores"], [1.0, 0.0])
        coverage = report["coverage"]["probes"]
        self.assertEqual(coverage["skipped_requested_probes"], 0)
        self.assertEqual(coverage["skipped_probe_task_targets"], [{"probe_id":"numeric", "task_id":"bad"}])

    def test_adapter_errors_are_preserved_and_block_their_probe_target(self):
        adapted = {
            "tasks":[{"task_id":"toy", "domain":"toy", "prompt":"Incomplete source", "metadata":{}, "files":{}}],
            "observations":[{"task_id":"toy", "status":"error", "summary":"Malformed required source field"}],
            "coverage":{"selected":1},
        }
        with self.compute(), patch("rlaudit.adapters.normalize", return_value=adapted):
            report = execute(self.manifest, self.root / "adapter-error")
        self.assertEqual(report["status"], "completed_with_data_errors")
        self.assertEqual(report["probe_results"], [])
        self.assertEqual(report["findings"][0]["status"], "error")
        self.assertEqual(report["findings"][0]["check_id"], "adapter")

    def test_opaque_task_ids_never_become_filesystem_paths(self):
        tid = "external/env:task ../two words"
        self.tasks.write_text(json.dumps({"task_id":tid,"domain":"toy","prompt":"opaque ID", "metadata":{},"files":{}})+"\n")
        self.config["probes"][0]["task_ids"] = [tid]
        self.save()
        with self.compute():
            report = execute(self.manifest, self.root / "opaque")
        self.assertEqual(report["probe_results"][0]["task_id"], tid)
        self.assertEqual(len(list((self.root / "opaque/probes/numeric").iterdir())), 1)

    def test_login_execution_is_rejected(self):
        with patch.dict(os.environ, {"SLURM_JOB_PARTITION":"login", "SLURM_JOB_ID":""}):
            with self.assertRaisesRegex(ValueError, "Slurm job"):
                require_compute()

    def test_replay_uses_snapshot_after_original_changes(self):
        with self.compute():
            first = execute(self.manifest, self.root / "first")
            self.driver.write_text("raise RuntimeError('changed original must not execute')")
            with contextlib.redirect_stdout(io.StringIO()):
                code = main(["replay", str(self.root / "first"), "--output", str(self.root / "second"), "--backend", "current"])
        self.assertEqual(code, 0)
        self.assertEqual(first["finding_counts"], {"candidate":1})
        self.assertEqual(first["probe_results"][0]["scores"], [1.0,0.0])
        self.assertEqual(first["coverage"]["checks"]["code_static"]["skipped"], 1)
        self.assertTrue(compare(self.root / "first", self.root / "second")["reproduced"])

    def test_recorded_engine_can_replay_without_repository_package(self):
        with self.compute():
            execute(self.manifest, self.root / "recorded")
            result = subprocess.run([str(self.root / "recorded/replay.sh"),
                                     "--output", str(self.root / "from-recorded-engine"), "--backend", "current"],
                                    cwd=self.root, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(compare(self.root / "recorded", self.root / "from-recorded-engine")["reproduced"])

    def test_tampered_snapshot_and_added_artifacts_are_detected(self):
        with self.compute():
            execute(self.manifest, self.root / "run")
        run = self.root / "run"
        (run / "extra.txt").write_text("unrecorded")
        with self.assertRaisesRegex(ValueError, "added or missing"):
            verify(run)
        (run / "extra.txt").unlink()
        (run / "inputs/driver/driver.py").write_text("changed")
        with self.assertRaisesRegex(ValueError, "snapshot changed"):
            verify(run)

    def test_added_symlink_directory_is_detected(self):
        with self.compute():
            execute(self.manifest, self.root / "linked")
        (self.root / "linked/extra-dir").symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symlink"):
            verify(self.root / "linked")

    def test_probe_failure_is_inconclusive_not_zero_reward(self):
        self.driver.write_text("print('not a JSON reward')")
        with self.compute():
            report = execute(self.manifest, self.root / "bad")
        self.assertEqual(report["status"], "completed_with_inconclusive_probes")
        self.assertEqual(report["finding_counts"], {})
        self.assertIsNone(report["probe_results"][0]["scores"])
        self.assertEqual(verify(self.root / "bad")["status"], "verified")

    def test_source_mutation_by_trusted_driver_fails_run(self):
        self.driver.write_text("import json,sys\nfrom pathlib import Path\np=json.load(sys.stdin)\nPath(p['sources']['tasks']).write_text('modified')\nprint(json.dumps({'reward':1}))\n")
        with self.compute(), self.assertRaisesRegex(ValueError, "snapshot changed"):
            execute(self.manifest, self.root / "mutating")
        state = json.loads((self.root / "mutating/state.json").read_text())
        self.assertEqual(state["status"], "failed")

    def test_directory_snapshot_preserves_name_empty_dirs_and_executable_bit(self):
        source = self.root / "bundle-name"
        (source / "empty").mkdir(parents=True)
        executable = source / "driver.sh"
        executable.write_text("#!/bin/sh\nexit 0\n")
        executable.chmod(0o755)
        config = copy.deepcopy(self.config)
        config["sources"].append({"id":"bundle", "path":"bundle-name"})
        locked, provenance, sources = freeze(validate(config), self.manifest, self.root / "frozen")
        self.assertEqual(sources["bundle"].name, "bundle-name")
        self.assertTrue((sources["bundle"] / "empty").is_dir())
        self.assertTrue((sources["bundle"] / "driver.sh").stat().st_mode & 0o111)
        self.assertEqual(provenance["sources"][-1]["files"][0]["path"], "driver.sh")

    def test_symlinks_bad_pins_and_size_budget_are_rejected(self):
        for label in ["symlink", "pin", "budget"]:
            with self.subTest(label=label):
                config = copy.deepcopy(self.config)
                if label == "symlink":
                    link = self.root / "link.py"
                    link.symlink_to(self.driver)
                    config["sources"][1]["path"] = "link.py"
                elif label == "pin":
                    config["sources"][1]["sha256"] = "0" * 64
                else:
                    config["execution"]["max_source_bytes"] = 1
                with self.assertRaises(ValueError):
                    freeze(validate(config), self.manifest, self.root / label)

    def test_slurm_submission_uses_argv_and_runs_whole_worker(self):
        with patch("rlaudit.slurm.subprocess.run", return_value=SimpleNamespace(returncode=0, stdout="Site filter\n12345;cluster\n", stderr="")) as mocked:
            result = submit(validate(self.config), self.manifest, self.root / "queued")
        self.assertEqual(result["job_id"], "12345")
        self.assertIn("--partition=amd-tw-verification", mocked.call_args.args[0])
        script = Path(result["script"]).read_text()
        self.assertIn("rlaudit _worker", script)
        submitted = json.loads((Path(result["job_directory"]) / "pipeline.json").read_text())
        self.assertEqual(Path(submitted["sources"][0]["path"]), self.tasks)

    def test_submission_rejects_source_nesting_before_mutating_source(self):
        source = self.root / "source"
        source.mkdir()
        config = copy.deepcopy(self.config)
        config["sources"].append({"id":"bundle", "path":"source"})
        with self.assertRaisesRegex(ValueError, "nested"):
            submit(validate(config), self.manifest, source / "run")
        self.assertEqual(list(source.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
