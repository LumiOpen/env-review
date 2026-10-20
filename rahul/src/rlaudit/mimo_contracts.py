"""Bounded, source-backed checks for pinned MiMo Cyber, Webdev and Music rows.

These checks inspect normalized dataset metadata only. They do not open task
images, execute target programs, render pages, call judges, or score music.
"""

from __future__ import annotations

import re


CHECK_ID = "mimo_contract"
_ARVO_FUNC = re.compile(r"in function `([^`]+)`")
_ARVO_KIND = re.compile(r"(\S+):\s+(\S+)")
_METER = re.compile(r"([1-9]\d*)/([1-9]\d*)\Z")


def _finding(task: dict, status: str, summary: str, evidence: list[dict],
             limitations: list[str] | None = None) -> dict:
    return {"check_id": CHECK_ID, "task_id": task["task_id"], "status": status,
            "evidence_level": "static", "summary": summary, "evidence": evidence,
            "limitations": limitations or []}


def _meta(task: dict) -> tuple[dict, dict, dict]:
    metadata = task.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    instance = metadata.get("instance")
    extra = metadata.get("extra_info")
    row = metadata.get("row")
    return (instance if isinstance(instance, dict) else {},
            extra if isinstance(extra, dict) else {},
            row if isinstance(row, dict) else {})


def _cyber(task: dict, instance: dict, extra: dict) -> list[dict]:
    findings = []
    # Match dict.get(key, fallback): an absent description uses the full statement,
    # while a present empty/non-string description does not trigger the fallback.
    description_source = ("metadata.instance.description" if "description" in instance
                          else "metadata.instance.problem_statement")
    description = instance.get("description", instance.get("problem_statement", ""))
    if not isinstance(description, str) or not description:
        findings.append(_finding(task, "error", "Cyber effective target description is missing",
                                 [{"source": description_source}],
                                 ["ARVO setup reads description or a missing-key problem_statement fallback to configure the expected crash target."]))
    else:
        # Match the pinned arvo.py extraction rules, without importing environment code.
        if not _ARVO_FUNC.search(description):
            findings.append(_finding(task, "error", "Cyber description has no parseable target function",
                                     [{"source": description_source, "value": description[:300]}],
                                     ["Pinned ARVO setup raises ValueError before grading this row."]))
        if not _ARVO_KIND.match(description):
            findings.append(_finding(task, "candidate", "Cyber description has no parseable sanitizer and error type",
                                     [{"source": description_source, "value": description[:300]}],
                                     ["The grading server compares these strings; a runtime crash was not attempted."]))
        prompt = task.get("prompt")
        if "description" in instance and isinstance(prompt, str) and prompt.strip() and prompt.strip() != description.strip():
            findings.append(_finding(task, "candidate", "Cyber prompt and grader target description differ",
                                     [{"source": "task.prompt", "value": prompt[:300]},
                                      {"source": description_source, "value": description[:300]}],
                                     ["The task may intentionally include additional instructions; review the difference before treating it as a defect."]))
    outer_id, inner_id = extra.get("instance_id"), instance.get("instance_id")
    if isinstance(outer_id, str) and isinstance(inner_id, str) and outer_id != inner_id:
        findings.append(_finding(task, "error", "Cyber outer and inner instance IDs differ",
                                 [{"source": "metadata.extra_info.instance_id", "value": outer_id},
                                  {"source": "metadata.instance.instance_id", "value": inner_id}]))
    image = instance.get("docker_image")
    if not isinstance(image, str) or not image:
        findings.append(_finding(task, "candidate", "Cyber target image is missing",
                                 [{"source": "metadata.instance.docker_image"}],
                                 ["The referenced image contents and registry availability were not checked."]))
    elif isinstance(inner_id, str) and inner_id and image != f"arvo-rl:v1-{inner_id.replace('arvo_', 'arvo-', 1)}":
        findings.append(_finding(task, "candidate", "Cyber image tag and instance ID differ",
                                 [{"source": "metadata.instance.docker_image", "value": image},
                                  {"source": "metadata.instance.instance_id", "value": inner_id}],
                                 ["Image aliases may be intentional; image contents were not checked."]))
    return findings


def _webdev(task: dict, instance: dict, extra: dict) -> list[dict]:
    findings = []
    statement = instance.get("problem_statement")
    prompt = task.get("prompt")
    if not isinstance(statement, str) or not statement.strip():
        findings.append(_finding(task, "error", "Webdev problem statement is missing",
                                 [{"source": "metadata.instance.problem_statement"}],
                                 ["The environment needs a query for screenshot grading."]))
    elif isinstance(prompt, str) and prompt.strip() and prompt.strip() != statement.strip():
        findings.append(_finding(task, "candidate", "Webdev prompt and grading query differ",
                                 [{"source": "task.prompt", "value": prompt[:300]},
                                  {"source": "metadata.instance.problem_statement", "value": statement[:300]}],
                                 ["The rendered page and external vision judgments were not inspected."]))
    identifiers = {"extra_info.instance_id": extra.get("instance_id"),
                   "instance.instance_id": instance.get("instance_id"),
                   "instance.task_id": instance.get("task_id")}
    present = {key: value for key, value in identifiers.items() if isinstance(value, str) and value}
    if len(set(present.values())) > 1:
        findings.append(_finding(task, "error", "Webdev task identifiers differ",
                                 [{"source": f"metadata.{key}", "value": value} for key, value in present.items()]))
    if instance.get("category") != "website":
        findings.append(_finding(task, "candidate", "Webdev category is not website",
                                 [{"source": "metadata.instance.category", "value": instance.get("category")}],
                                 ["The deployed environment may support other categories; its renderer was not run."]))
    if not isinstance(instance.get("docker_image"), str) or not instance["docker_image"]:
        findings.append(_finding(task, "candidate", "Webdev runtime image is missing",
                                 [{"source": "metadata.instance.docker_image"}],
                                 ["No image contents or screenshot reference was inspected."]))
    return findings


def _music(task: dict, extra: dict) -> list[dict]:
    findings = []
    for field in ("nvoice_want", "bpm"):
        value = extra.get(field)
        if type(value) is not int or value <= 0:
            findings.append(_finding(task, "error", f"Music {field} is not a positive integer",
                                     [{"source": f"metadata.extra_info.{field}", "value": value}],
                                     ["The pinned scorer does not enforce this prompt constraint."]))
    meter = extra.get("meter")
    if not isinstance(meter, str) or not _METER.fullmatch(meter):
        findings.append(_finding(task, "error", "Music meter is not a positive fraction",
                                 [{"source": "metadata.extra_info.meter", "value": meter}],
                                 ["The pinned scorer does not enforce this prompt constraint."]))
    return findings


def check_task(task: dict) -> list[dict]:
    """Return only explicit contract findings for one normalized MiMo task."""
    domain = task.get("domain")
    instance, extra, _row = _meta(task)
    if domain == "cyber":
        return _cyber(task, instance, extra)
    if domain == "webdev":
        return _webdev(task, instance, extra)
    if domain == "music":
        return _music(task, extra)
    return []


def coverage_limits(domains: set[str]) -> list[str]:
    """Describe work that static contract checks cannot settle, once per report."""
    limits = []
    if "cyber" in domains:
        limits.append("Cyber: target images, sanitizer execution, and crash-match behavior were not inspected.")
    if "webdev" in domains:
        limits.append("Webdev: rendered pages, reference screenshots, and external vision judgments were not inspected.")
    if "music" in domains:
        limits.append("Music: ABC/MIDI rendering and feature scoring were not run; pinned compute_score ignores task metadata and does not explicitly enforce requested BPM, meter, or voice count.")
    return limits
