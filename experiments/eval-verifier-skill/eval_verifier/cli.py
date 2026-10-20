"""CLI entry point for eval-verifier."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import click

try:
    from rich.console import Console
    from rich.table import Table
    from rich import print as rprint
    _RICH = True
except ImportError:
    _RICH = False

from eval_verifier.report import Report, Severity


_SEVERITY_COLOR = {
    "CRITICAL": "bold red",
    "HIGH": "red",
    "MEDIUM": "yellow",
    "LOW": "cyan",
    "INFO": "dim",
}


def _color(text: str, severity: str) -> str:
    if not _RICH:
        return text
    style = _SEVERITY_COLOR.get(severity, "")
    return f"[{style}]{text}[/{style}]" if style else text


def _print_report(report: Report) -> None:
    summary = report.summary()

    if _RICH:
        console = Console()
        console.rule(f"[bold]eval-verifier report: {report.target}[/bold]")
        console.print(f"Target type : {report.target_type}")
        console.print(f"Timestamp   : {report.timestamp}")
        overall = summary["overall_risk"]
        console.print(f"Overall risk: {_color(overall, overall)}")
        console.print()

        counts = summary["finding_counts"]
        for sev in ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]:
            n = counts.get(sev, 0)
            if n > 0:
                console.print(f"  {_color(sev, sev)}: {n}")

        console.print()
        for mr in report.module_results:
            if mr.status == "skipped":
                console.print(f"[dim]  [{mr.module}] skipped[/dim]")
                continue
            if mr.status == "error":
                console.print(f"[red]  [{mr.module}] ERROR: {mr.error}[/red]")
                continue
            for f in mr.findings:
                sev = f.severity.value
                console.print(f"  {_color(f'[{sev}]', sev)} [{mr.module}] {f.title}")
                if f.description:
                    console.print(f"    {f.description[:200]}")
                if f.value is not None and f.threshold is not None:
                    console.print(
                        f"    value={f.value:.3f}  threshold={f.threshold:.3f}"
                    )
                if f.known_bug:
                    console.print(f"    [dim]known bug: {f.known_bug}[/dim]")
                console.print()
    else:
        print(f"=== eval-verifier: {report.target} ===")
        print(f"Overall risk: {summary['overall_risk']}")
        print(f"Findings: {summary['total_findings']}")
        for mr in report.module_results:
            for f in mr.findings:
                print(f"  [{f.severity.value}] [{mr.module}] {f.title}")


# ---------------------------------------------------------------------------
# CLI commands
# ---------------------------------------------------------------------------

@click.group()
@click.version_option()
def main() -> None:
    """eval-verifier: detect anomalies in LLM evals and RL training environments."""


@main.command("fuzz-verifier")
@click.option("--cmd", default=None,
              help="CLI command template with {pred} and {ref} placeholders.")
@click.option("--no-sympy-check", is_flag=True, default=False,
              help="Skip SymPy/antlr4 health checks.")
@click.option("--timeout", default=10.0, type=float,
              help="Per-case timeout in seconds (default 10).")
@click.option("--output", "-o", default=None,
              help="Write JSON report to this path.")
def fuzz_verifier(cmd: str | None, no_sympy_check: bool, timeout: float,
                  output: str | None) -> None:
    """Module 1: Fuzz a math verifier with equivalence pairs and edge cases."""
    from eval_verifier.modules import verifier_fuzzer

    report = Report(
        target=cmd or "sympy-health-only",
        target_type="math_verifier",
    )
    mr = verifier_fuzzer.run(
        cli_cmd=cmd,
        check_sympy=not no_sympy_check,
        timeout_s=timeout,
    )
    report.module_results.append(mr)
    _print_report(report)
    if output:
        report.save(output)
        click.echo(f"\nReport saved to {output}")
    sys.exit(0 if report.overall_risk in (Severity.INFO, Severity.LOW) else 1)


@main.command("audit-hackability")
@click.option("--dataset", default=None,
              help="HuggingFace dataset name (requires datasets extra).")
@click.option("--file", "json_file", default=None,
              help="JSON file with list of tasks: [{id, gold_solution, test_cases}].")
@click.option("--min-tests", default=5, type=int,
              help="Minimum test cases before flagging as likely hackable (default 5).")
@click.option("--sample", default=50, type=int,
              help="Number of tasks to sample for execution probes (default 50).")
@click.option("--output", "-o", default=None)
def audit_hackability(dataset: str | None, json_file: str | None,
                      min_tests: int, sample: int, output: str | None) -> None:
    """Module 2: Audit coding RL environment for hackable test suites."""
    from eval_verifier.modules.hackability import CodingTask, run as hack_run

    tasks: list[CodingTask] = []

    if json_file:
        with open(json_file) as fh:
            raw = json.load(fh)
        for item in raw:
            tasks.append(CodingTask(
                task_id=str(item.get("id", item.get("task_id", ""))),
                gold_solution=item.get("gold_solution", item.get("solution", "")),
                test_cases=item.get("test_cases", []),
                generated_tests=item.get("generated_tests", []),
            ))
    elif dataset:
        try:
            from datasets import load_dataset
        except ImportError:
            click.echo("Install datasets extra: pip install 'eval-verifier[datasets]'")
            sys.exit(2)
        ds = load_dataset(dataset, split="test")
        for i, row in enumerate(ds):
            tasks.append(CodingTask(
                task_id=str(row.get("task_id", i)),
                gold_solution=str(row.get("solution", row.get("gold_solution", ""))),
                test_cases=row.get("test_cases", []),
            ))
    else:
        click.echo("Provide --dataset or --file.")
        sys.exit(2)

    report = Report(target=dataset or json_file or "tasks", target_type="coding_env")
    mr = hack_run(tasks, min_test_cases=min_tests, sample_size=sample)
    report.module_results.append(mr)
    _print_report(report)
    if output:
        report.save(output)
    sys.exit(0 if report.overall_risk in (Severity.INFO, Severity.LOW) else 1)


@main.command("check-contamination")
@click.argument("dataset_file", type=click.Path(exists=True))
@click.option("--text-column", default="text",
              help="Column/key containing the sample text (default: 'text').")
@click.option("--ngram", "-n", default=8, type=int,
              help="N-gram size for overlap detection (default: 8).")
@click.option("--benchmarks", multiple=True,
              help="HuggingFace dataset names to check against (repeatable).")
@click.option("--output", "-o", default=None)
def check_contamination(dataset_file: str, text_column: str, ngram: int,
                        benchmarks: tuple, output: str | None) -> None:
    """Module 4: Check n-gram overlap between a training dataset and known benchmarks."""
    from eval_verifier.modules.contamination import (
        Sample, BenchmarkCorpus, run as cont_run
    )

    path = Path(dataset_file)
    if path.suffix == ".json":
        with open(path) as fh:
            raw = json.load(fh)
        if isinstance(raw, list):
            samples = [Sample(id=str(i), text=str(r.get(text_column, r) if isinstance(r, dict) else r))
                       for i, r in enumerate(raw)]
        else:
            click.echo("JSON file must contain a list.")
            sys.exit(2)
    elif path.suffix in (".jsonl", ".ndjson"):
        samples = []
        with open(path) as fh:
            for i, line in enumerate(fh):
                obj = json.loads(line)
                samples.append(Sample(id=str(i), text=str(obj.get(text_column, ""))))
    else:
        click.echo("Provide a .json or .jsonl file.")
        sys.exit(2)

    corpora = BenchmarkCorpus.defaults()
    for bm in benchmarks:
        try:
            corpora.append(BenchmarkCorpus.from_huggingface(bm, "test", text_column))
        except Exception as exc:
            click.echo(f"Warning: could not load {bm}: {exc}")

    report = Report(target=dataset_file, target_type="training_dataset")
    mr = cont_run(samples, corpora, n=ngram)
    report.module_results.append(mr)
    _print_report(report)
    if output:
        report.save(output)
    sys.exit(0 if report.overall_risk in (Severity.INFO, Severity.LOW) else 1)


@main.command("check-infra")
@click.option("--task-ids", default=None,
              help="Comma-separated list of task IDs to probe.")
@click.option("--output", "-o", default=None)
def check_infra(task_ids: str | None, output: str | None) -> None:
    """Module 6: Run infrastructure health probes (build, false-pass, empty-response, reset)."""
    from eval_verifier.modules.infra_health import SubprocessEnvironment, TaskSpec, run as infra_run

    if task_ids:
        ids = [t.strip() for t in task_ids.split(",")]
    else:
        ids = ["demo_task"]

    # Build a minimal demo environment so the command is self-contained
    tasks = {
        tid: TaskSpec(
            task_id=tid,
            gold_code="def solution(x): return x * 2",
            test_code=(
                "from solution import solution\n"
                "assert solution(2) == 4\n"
                "assert solution(0) == 0\n"
            ),
        )
        for tid in ids
    }
    env = SubprocessEnvironment(tasks)

    report = Report(target="subprocess-env", target_type="execution_env")
    mr = infra_run(env, ids)
    report.module_results.append(mr)
    _print_report(report)
    if output:
        report.save(output)
    sys.exit(0 if report.overall_risk in (Severity.INFO, Severity.LOW) else 1)


@main.command("report")
@click.argument("json_file", type=click.Path(exists=True))
def show_report(json_file: str) -> None:
    """Pretty-print a saved JSON report."""
    with open(json_file) as fh:
        data = json.load(fh)
    click.echo(json.dumps(data, indent=2))
