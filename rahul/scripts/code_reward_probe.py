#!/usr/bin/env python3
#SBATCH --job-name=mimo-code-reward-probe
#SBATCH --partition=amd-tw-verification
#SBATCH --nodelist=tus1-p15-g62
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=4G
#SBATCH --time=00:12:00
#SBATCH --output=/shared_silo/scratch/rahul.aralikatte@amd.com/random/hackathon26/research/mimo/code_review/logs/code_reward_probe-%j.out
#SBATCH --error=/shared_silo/scratch/rahul.aralikatte@amd.com/random/hackathon26/research/mimo/code_review/logs/code_reward_probe-%j.err
"""Bounded, network-isolated Code reward probe. Submit with sbatch; do not run on login.

This reproduces the pinned setup and reward shell operations inside two fresh
Docker containers. It never mounts host paths or the Docker socket into them.
The verifier command comes byte-for-byte from the pinned dataset patch.
"""

import ast
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
REVIEW = ROOT / "research/mimo/code_review"
SOURCE = REVIEW / "sources"
TASK = REVIEW / "snapshots/format-code-task-002069"
PATCH = TASK / "test.patch"
ORIGINAL = SOURCE / "pytago_198034521b4d/examples"
IMAGE = (
    "docker.io/xiaomimimo/mimo-v2.6-rl-oss@"
    "sha256:88326a734ec3abb1fa9d44744796f819880f4801a74b940965d488ca69fd8b24"
)
JOB_ID = os.environ.get("SLURM_JOB_ID")
if not JOB_ID:
    raise SystemExit("Run only through sbatch on amd-tw-verification")
OUT = REVIEW / "runtime_probe" / JOB_ID
OUT.mkdir(parents=True, exist_ok=True)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(label, args, *, timeout=60, stdin=None, check=False):
    start = time.monotonic()
    try:
        result = subprocess.run(args, input=stdin, text=True, capture_output=True, timeout=timeout)
        record = {"returncode": result.returncode, "timed_out": False,
                  "duration_sec": round(time.monotonic() - start, 3)}
        (OUT / f"{label}.stdout").write_text(result.stdout)
        (OUT / f"{label}.stderr").write_text(result.stderr)
    except subprocess.TimeoutExpired as exc:
        record = {"returncode": None, "timed_out": True,
                  "duration_sec": round(time.monotonic() - start, 3)}
        (OUT / f"{label}.stdout").write_bytes(exc.stdout or b"")
        (OUT / f"{label}.stderr").write_bytes(exc.stderr or b"")
    if check and (record["timed_out"] or record["returncode"] != 0):
        raise RuntimeError(f"{label} failed: {record}")
    return record


def dexec(cid, label, command, *, timeout=60, check=False, stdin=None):
    args = ["docker", "exec", "-i", "-w", "/testbed", cid, "/bin/bash", "-c", command]
    return run(label, args, timeout=timeout, check=check, stdin=stdin)


def pinned_source_contract():
    """Take literal setup commands and reset methods from the pinned source AST."""
    base = ast.parse((SOURCE / "base.py").read_text())
    code = ast.parse((SOURCE / "opensource_code.py").read_text())
    base_cls = next(n for n in base.body if isinstance(n, ast.ClassDef) and n.name == "DatasetEnvironment")
    code_cls = next(n for n in code.body if isinstance(n, ast.ClassDef) and n.name == "OpenSourceCodeEnvironment")

    def attr(cls, name):
        for n in cls.body:
            if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in n.targets):
                return ast.literal_eval(n.value)
        raise KeyError(name)

    methods = [n for n in base_cls.body if isinstance(n, ast.FunctionDef) and
               n.name in ("get_patch_touched_files", "build_reset_test_files_cmd")]
    wrapper = ast.ClassDef(name="PinnedReset", bases=[], keywords=[], body=methods, decorator_list=[])
    module = ast.fix_missing_locations(ast.Module(body=[wrapper], type_ignores=[]))
    ns = {"re": re}
    exec(compile(module, str(SOURCE / "base.py"), "exec"), ns)
    return {
        "history_purge": attr(code_cls, "_PURGE_GIT_HISTORY"),
        "residue_scrub": attr(base_cls, "_RESIDUE_SCRUB_GLOBAL"),
        "global_cache_scrub": attr(base_cls, "_GLOBAL_CACHE_SCRUB"),
        "clean_keep": list(dict.fromkeys(attr(base_cls, "_CLEAN_KEEP_COMMON") + attr(base_cls, "_CLEAN_KEEP_UNKNOWN"))),
        "reset": ns["PinnedReset"](),
    }


def create_container(case):
    args = ["docker", "create", "--network", "none", "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges", "--pids-limit", "128",
            "--memory", "4g", "--cpus", "2", "--entrypoint", "/bin/sh",
            IMAGE, "-c", "sleep 700"]
    result = subprocess.run(args, text=True, capture_output=True, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(f"docker create failed: {result.stderr[:500]}")
    cid = result.stdout.strip()
    run(f"{case}_start", ["docker", "start", cid], timeout=30, check=True)
    return cid


def copy_to(cid, source, target, label):
    return run(label, ["docker", "cp", str(source), f"{cid}:{target}"], timeout=30, check=True)


def run_case(case, contract):
    cid = create_container(case)
    record = {"case": case, "image": IMAGE, "anti_hack_cleanup": True, "container_id": cid[:12]}
    try:
        dexec(cid, f"{case}_safe_directory", "git config --global --add safe.directory /testbed", check=True)
        dexec(cid, f"{case}_git_exists", "git rev-parse --git-dir", check=True)
        base = subprocess.run(["docker", "exec", "-w", "/testbed", cid,
                               "git", "rev-parse", "HEAD"], text=True, capture_output=True, timeout=30)
        if base.returncode != 0 or not re.fullmatch(r"[a-f0-9]{40}", base.stdout.strip()):
            raise RuntimeError("Could not capture valid base HEAD")
        base_ref = base.stdout.strip()
        record["base_ref"] = base_ref
        record["history_purge"] = dexec(cid, f"{case}_history_purge",
            contract["history_purge"].format(base=base_ref), timeout=180, check=True)
        dexec(cid, f"{case}_history_check", f"test -z \"$(git rev-list --all --not {base_ref})\"", check=True)

        # The public image requires anti_hack_cleanup=true; row language is absent,
        # so DatasetEnvironment uses the unknown-language keep list and no pip install.
        residue = ("rm -rf /testbed/node_modules/.cache /testbed/node_modules/.vitest 2>/dev/null; "
                   + contract["residue_scrub"])
        record["residue_scrub"] = dexec(cid, f"{case}_residue_scrub", residue, timeout=120)
        excludes = " ".join(f"--exclude={name}" for name in contract["clean_keep"])
        record["artifact_scrub"] = dexec(cid, f"{case}_artifact_scrub",
                                          f"git clean -fdx {excludes}", timeout=120)
        record["global_cache_scrub"] = dexec(cid, f"{case}_global_cache_scrub",
                                              contract["global_cache_scrub"], timeout=120)
        dexec(cid, f"{case}_fixture_initially_absent",
              "test ! -e examples/bitwisenot.py && test ! -e examples/bitwisenot.go", check=True)

        # Agent action after setup, before reward. Only the candidate adds files.
        if case == "fixture_only":
            dexec(cid, f"{case}_fixture_mutation",
                  "test -f examples/helloworld.py && test -f examples/helloworld.go && "
                  "cp examples/helloworld.py examples/bitwisenot.py && "
                  "cp examples/helloworld.go examples/bitwisenot.go", check=True)
        dexec(cid, f"{case}_stage", "git add -A >/dev/null 2>&1", check=True)
        diff = subprocess.run(["docker", "exec", "-w", "/testbed", cid, "git",
                               "-c", "core.fileMode=false", "diff", "HEAD"],
                              capture_output=True, timeout=60)
        (OUT / f"{case}.model.patch").write_bytes(diff.stdout)
        if diff.returncode != 0:
            raise RuntimeError("Model diff capture failed")
        record["model_patch_sha256"] = sha256(OUT / f"{case}.model.patch")
        record["model_patch_bytes"] = len(diff.stdout)
        names = subprocess.run(["docker", "exec", "-w", "/testbed", cid,
                                "git", "diff", "--name-only", "HEAD"],
                               text=True, capture_output=True, timeout=30, check=True).stdout.splitlines()
        record["model_patch_paths"] = names
        if case == "baseline" and names:
            raise RuntimeError(f"Baseline changed tracked paths during setup: {names}")
        if case == "fixture_only" and sorted(names) != ["examples/bitwisenot.go", "examples/bitwisenot.py"]:
            raise RuntimeError(f"Fixture mutation changed unexpected paths: {names}")

        # These are the same reset method and patch bytes used by the pinned reward.
        reset_cmd = 'git() { command git -c core.hooksPath=/dev/null "$@"; }\n' + \
                    contract["reset"].build_reset_test_files_cmd(PATCH.read_text(), base_ref)
        record["reset_before"] = dexec(cid, f"{case}_reset_before", reset_cmd, check=True)
        copy_to(cid, PATCH, "/tmp/_opensource_code_test.patch", f"{case}_copy_patch")
        record["apply_patch"] = dexec(cid, f"{case}_apply_patch",
                                       "git apply --verbose /tmp/_opensource_code_test.patch", check=True)
        dexec(cid, f"{case}_remove_patch_transfer", "rm -f /tmp/_opensource_code_test.patch", check=True)
        try:
            # Dataset timeout is 1800 s; the host probe cap is 180 s and any
            # timeout is reported as inconclusive rather than as a wrong answer.
            verdict = dexec(cid, f"{case}_verifier", "bash /testbed/mimo_test_command.sh", timeout=180)
            record["verifier"] = verdict
            record["reward_if_completed"] = (1.0 if verdict["returncode"] == 0 else 0.0) if not verdict["timed_out"] else None
        finally:
            record["reset_after"] = dexec(cid, f"{case}_reset_after", reset_cmd, timeout=60)

        if case == "fixture_only":
            copy_to(cid, ORIGINAL / "bitwisenot.py", "/tmp/original_bitwisenot.py", f"{case}_copy_original_py")
            copy_to(cid, ORIGINAL / "bitwisenot.go", "/tmp/original_bitwisenot.go", f"{case}_copy_original_go")
            direct = r'''from pathlib import Path
from pytago import python_to_go
source = Path('/tmp/original_bitwisenot.py').read_text()
expected = Path('/tmp/original_bitwisenot.go').read_text()
try:
    actual = python_to_go(source)
except Exception as exc:
    print(type(exc).__name__ + ': ' + str(exc))
    raise SystemExit(2)
print('matches_reported_expected=' + str(actual == expected))
print('actual=' + repr(actual[:500]))
raise SystemExit(0 if actual == expected else 1)
'''
            record["original_repro"] = run(f"{case}_original_repro",
                ["docker", "exec", "-i", "-w", "/testbed", cid, "python", "-"],
                stdin=direct, timeout=90)
        return record
    finally:
        subprocess.run(["docker", "rm", "-f", cid], capture_output=True, timeout=30)


def main():
    if "amd-tw-verification" not in os.environ.get("SLURM_JOB_PARTITION", ""):
        raise RuntimeError("This probe requires amd-tw-verification")
    run("docker_server", ["docker", "version", "--format", "{{.Server.Version}}"], timeout=20, check=True)
    run("image_present", ["docker", "image", "inspect", IMAGE, "--format", "{{.Id}}"], timeout=20, check=True)
    contract = pinned_source_contract()
    metadata = {"runtime_commit": "c3df8469f250b15e7906487a6d52be4c1827a509",
                "image": IMAGE, "test_patch_sha256": sha256(PATCH),
                "base_source_sha256": sha256(SOURCE / "base.py"),
                "code_source_sha256": sha256(SOURCE / "opensource_code.py"),
                "original_fixture_sha256": {p.name: sha256(p) for p in ORIGINAL.glob("bitwisenot.*")},
                "job_id": JOB_ID,
                "deviations": ["Uses Docker shell adapter rather than full MimoAgent pod backend",
                               "Host verifier timeout capped at 180 seconds rather than row's 1800 seconds; timeout is inconclusive"]}
    (OUT / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    results = []
    for case in ("baseline", "fixture_only"):
        try:
            results.append(run_case(case, contract))
        except Exception as exc:
            results.append({"case": case, "probe_error": repr(exc)})
            break
        finally:
            (OUT / "results.json").write_text(json.dumps(results, indent=2) + "\n")
    print(json.dumps({"output": str(OUT), "results": results}, indent=2))
    if len(results) != 2 or any("probe_error" in x for x in results):
        raise SystemExit(4)
    baseline, candidate = results
    summary = {
        "baseline_reward": baseline.get("reward_if_completed"),
        "fixture_only_reward": candidate.get("reward_if_completed"),
        "original_prompt_repro_returncode": candidate.get("original_repro", {}).get("returncode"),
        "candidate_source_paths": candidate.get("model_patch_paths"),
        "score_passes_while_repro_fails": (
            baseline.get("reward_if_completed") == 0.0
            and candidate.get("reward_if_completed") == 1.0
            and candidate.get("original_repro", {}).get("returncode") not in (None, 0)
        ),
        "interpretation_limit": "Inspect pytest and direct-repro logs to confirm failure causes; Docker adapter reproduces pinned shell sequence but is not MimoAgent's pod backend.",
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
