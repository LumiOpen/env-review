"""Build small rlaudit JSONL inputs/manifests from reviewed, pinned sources.

This preparation only reads local metadata and writes configuration files.
Environment imports and execution belong to Slurm compute jobs.
"""
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "research/prime"
DATASETS = {"verifiers": "0.3.0", "datasets": "4.3.0", "pyarrow": "24.0.0"}
ENVS = {
    "reverse_text": ("will", "reverse-text", "9523b627a28d"),
    "countdown": ("sami", "countdown", "e821f68a918d"),
    "wordle": ("apple999", "wordle", "7cea003c4fb9"),
}


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def source(sid, path, sha=None):
    path = Path(path)
    # Keep configs relocatable from the examples directory.
    relative = "../" + path.relative_to(ROOT).as_posix()
    item = {"id": sid, "path": relative}
    if path.is_file():
        item["sha256"] = sha or hashlib.sha256(path.read_bytes()).hexdigest()
    return item


def probe(pid, task_id, cases, relation, command):
    return {"id": pid, "task_ids": [task_id], "command": command, "cases": cases,
            "relation": relation, "executor": "trusted_process", "scope": "component"}


def pair(pid, task_id, first, second, values, reason, command):
    return probe(pid, task_id, [{"id": "reference", "input": first}, {"id": "variant", "input": second}],
                 {"kind": "expected", "values": values, "tolerance": 1e-12, "justification": reason}, command)


def completion(text):
    return {"completion": text}


def arithmetic(expr):
    return completion(f"<reasoning>Compute using the displayed expression.</reasoning><solution>{expr}</solution>")


def guesses(words):
    return {"calls": [{"tool": "guess", "args": {"word": word}} for word in words]}


def main():
    dataset = json.loads((BASE / "data/reverse_rows.json").read_text())
    reverse_dataset = BASE / "data/reverse_dataset"
    reverse_dataset.mkdir(parents=True, exist_ok=True)
    (reverse_dataset / "train.jsonl").write_text("".join(
        json.dumps({"prompt": row["source_prompt"], "source_row_id": row["dataset_index"]}, ensure_ascii=False) + "\n"
        for row in dataset["selected"]))
    for key, (owner, name, short_sha) in ENVS.items():
        catalog = json.loads((BASE / f"catalog/{owner}__{name}.json").read_text())["data"]
        env_dir = BASE / f"sources/{owner}__{name}__{short_sha}"
        archive = env_dir.with_suffix(".tar.gz")
        contract = ROOT / f"examples/contracts/prime_{key}.json"
        command = ["{python}", "-m", "rlaudit.verifiers_adapter", "--contract", "{source:contract}"]
        tasks, probes, extra_sources = [], [], []
        if key == "reverse_text":
            extra_sources = [source("reverse_dataset", reverse_dataset),
                             source("reverse_rows", BASE / "data/reverse_rows.json"),
                             source("raw_dataset", BASE / "data/reverse_train.parquet", dataset["sha256"]),
                             source("fixture_preparation", BASE / "data/prepare_reverse.py")]
            for fixture_index, row in enumerate(dataset["selected"]):
                index = row["dataset_index"]
                tid = f"prime-reverse-text-train-{index:04d}"
                tasks.append({"task_id": tid, "domain": "prime_reverse_text", "prompt": row["source_prompt"],
                              "metadata": {"source_row_id": index, "source_prompt": row["source_prompt"],
                                           "fixture_index": fixture_index, "expected_answer": row["answer"],
                                           "dataset_revision": dataset["revision"]}, "files": {}})
                exact = f"<reversed_text>{row['answer']}</reversed_text>"
                probes.append(pair(f"exact-reversal-{index}", tid, completion(exact),
                                   completion("<reversed_text></reversed_text>"), [1.0, 0.0],
                                   "An exact character-for-character reversal has similarity1; an empty field has similarity0 against this nonempty reference. Preserve source whitespace.", command))
            row = dataset["selected"][0]
            tid = tasks[0]["task_id"]
            exact = f"<reversed_text>{row['answer']}</reversed_text>"
            probes.append(probe("outer-xml-whitespace", tid,
                                [{"id": "plain", "input": completion(exact)},
                                 {"id": "outer-newlines", "input": completion("\n" + exact + "\n")}],
                                {"kind": "invariant", "tolerance": 0,
                                 "justification": "Only whitespace outside the XML answer field changes; the requested reversed text is identical."}, command))
            metric = dataset.get("metric_case")
            if metric is not None:
                metric_tid = f"prime-reverse-text-train-{metric['dataset_index']:04d}"
                probes.append(pair("declared-lcs-metric", metric_tid,
                                   completion(f"<reversed_text>{metric['answer']}</reversed_text>"),
                                   completion(f"<reversed_text>{metric['candidate_answer']}</reversed_text>"),
                                   [1.0, metric["expected_lcs_ratio"]],
                                   "The source calls its metric longest common subsequence similarity. Independent DP finds15 common characters in two length41 strings, giving30/82. This tests the declared metric, not whether the perturbed answer is a correct reversal.", command))
        elif key == "countdown":
            tid = "prime-countdown-seed-339-row-0"
            tasks = [{"task_id": tid, "domain": "prime_countdown",
                      "prompt": "Numbers: 2, 5, 3, 2, 50, 7\nTarget: 125",
                      "metadata": {"seed": 339, "numbers": [2, 5, 3, 2, 50, 7], "target": 125}, "files": {}}]
            extra_sources = [source("independent_oracle", BASE / "review/countdown_oracle.py"),
                             source("oracle_reproduction", BASE / "review/verify_countdown.py")]
            valid = arithmetic("(5*50)/2")
            probes.append(pair("exact-valid-versus-wrong", tid, valid, arithmetic("5+3"), [1, 0],
                               "The legal witness uses available numbers once and reaches125; 5+3 reaches8. Only the exact-match component is returned; details retain the full weighted rubric.", command))
            probes.append(pair("fractional-intermediate", tid, valid, arithmetic("(5/2)*50"), [1, 0],
                               "The prompt requires every intermediate result to be a positive integer. (5*50)/2 is legal; (5/2)*50 creates the fractional intermediate5/2. An independent AST/Fraction oracle verifies the distinction.", command))
            probes.append(pair("forbidden-exponent", tid, valid, arithmetic("5**3"), [1, 0],
                               "The prompt permits only addition, subtraction, multiplication, and division. Exponentiation is a different operation even though it reaches125 using available numeric literals.", command))
            probes.append(probe("unicode-arithmetic-operators", tid,
                                [{"id": "ascii", "input": valid}, {"id": "unicode", "input": arithmetic("(5×50)÷2")}],
                                {"kind": "invariant", "tolerance": 0,
                                 "justification": "The expressions use identical numbers and arithmetic; only standard multiplication/division glyphs differ. The pinned source explicitly normalizes these glyphs."}, command))
        else:
            answer_words = (env_dir / "wordle/data/answers.txt").read_text().splitlines()
            for answer in ("abbey", "apple"):
                index = answer_words.index(answer)
                tid = f"prime-wordle-answer-{answer}"
                wrong = "apple" if answer == "abbey" else "abbey"
                tasks.append({"task_id": tid, "domain": "prime_wordle",
                              "prompt": "Start the game. Make your first guess with the `guess` tool.",
                              "metadata": {"answer_index": index, "answer": answer}, "files": {}})
                probes.append(pair(f"solve-versus-exhaust-{answer}", tid, guesses([answer]),
                                   guesses([wrong] * 6), [1.0, 0.08],
                                   "A first-guess solve scores1. Six repeated wrong legal guesses exhaust the budget with one green each, so the documented unsolved shaping score is0.4*(1/5)=0.08.", command))
                probes.append(probe(f"invalid-nonconsumption-{answer}", tid,
                                    [{"id": "direct", "input": guesses([answer])},
                                     {"id": "invalid-first", "input": guesses(["123", answer])}],
                                    {"kind": "invariant", "tolerance": 0,
                                     "justification": "The prompt states invalid guesses do not consume a valid guess. Both sequences solve on their first valid guess; only two tool invocations are replayed, within the12-turn cap."}, command))
                probes.append(probe(f"fewer-valid-guesses-{answer}", tid,
                                    [{"id": "two-valid", "input": guesses([wrong, answer])},
                                     {"id": "one-valid", "input": guesses([answer])}],
                                    {"kind": "nondecreasing", "tolerance": 0,
                                     "justification": "The documented solve-speed preference should not lower reward when the same target is solved in fewer valid guesses."}, command))
                if answer == "apple":
                    probes.append(pair("duplicate-letter-replay", tid, guesses(["allee", "apple"]),
                                       guesses(["apply", "apple"]), [0.9, 0.9],
                                       "Both sequences solve in two valid guesses under the documented speed formula. Per-letter feedback is retained for independent duplicate-letter review; equality alone does not validate those marks.", command))
        tasks_path = BASE / f"tasks/{key}.jsonl"
        tasks_path.parent.mkdir(parents=True, exist_ok=True)
        tasks_path.write_text("".join(json.dumps(t, ensure_ascii=False) + "\n" for t in tasks))
        sources = [source("tasks", tasks_path), source("contract", contract), source(key, env_dir),
                   source("archive", archive, catalog["sha256"]),
                   source("catalog", BASE / f"catalog/{owner}__{name}.json"), *extra_sources]
        config = {
            "schema_version": "rlaudit.pipeline/v1", "name": "prime-" + key.replace("_", "-"),
            "provenance": {"hub_url": f"https://app.primeintellect.ai/dashboard/environments/{owner}/{name}",
                           "environment": f"{owner}/{name}", "archive_sha256": catalog["sha256"],
                           "version_id": catalog["version_id"], "runtime": "VERIFIERS_V0",
                           "scope": "Model-free source parser/rubric or state/tool component replay on frozen real task rows.",
                           "limitations": ["No model rollout, policy training, paid judge, or inference service.",
                                           "Framework trajectory metrics are scaffolding, not evidence of a real agent rollout.",
                                           "Findings apply to the selected package and compatible pinned framework, not every Hub environment."]},
            "sources": sources, "adapter": {"kind": "local_jsonl", "source": "tasks"},
            "checks": ["schema"], "probes": probes,
            "execution": {"partition": "amd-tw-verification", "cpus": 2, "memory": "4G", "time_limit": "00:05:00",
                          "max_source_bytes": 4 * 1024 * 1024, "max_source_files": 64, "max_tasks": 10,
                          "max_probe_cases": 20, "timeout_seconds": 45, "max_probe_seconds": 240,
                          "max_output_bytes": 262144, "allow_trusted_process": True, "dependencies": DATASETS},
        }
        write(ROOT / f"examples/prime_{key}.json", config)
        print(key, "tasks", len(tasks), "probes", len(probes), "cases", sum(len(p["cases"]) for p in probes))


if __name__ == "__main__":
    main()
