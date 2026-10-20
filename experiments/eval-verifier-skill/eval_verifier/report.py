"""Structured findings schema, severity scoring, and JSON report output."""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class Severity(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"

    def __lt__(self, other: "Severity") -> bool:
        order = [Severity.INFO, Severity.LOW, Severity.MEDIUM, Severity.HIGH, Severity.CRITICAL]
        return order.index(self) < order.index(other)


@dataclass
class Finding:
    module: str
    severity: Severity
    title: str
    description: str
    metric: str | None = None
    value: float | None = None
    threshold: float | None = None
    known_bug: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict:
        d = asdict(self)
        d["severity"] = self.severity.value
        return d


@dataclass
class ModuleResult:
    module: str
    status: str          # "ok" | "findings" | "skipped" | "error"
    findings: list[Finding] = field(default_factory=list)
    error: str | None = None
    duration_s: float | None = None

    def as_dict(self) -> dict:
        return {
            "module": self.module,
            "status": self.status,
            "error": self.error,
            "duration_s": self.duration_s,
            "findings": [f.as_dict() for f in self.findings],
        }


@dataclass
class Report:
    target: str
    target_type: str
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    module_results: list[ModuleResult] = field(default_factory=list)

    @property
    def all_findings(self) -> list[Finding]:
        return [f for mr in self.module_results for f in mr.findings]

    @property
    def overall_risk(self) -> Severity:
        if not self.all_findings:
            return Severity.INFO
        return max(f.severity for f in self.all_findings)

    def summary(self) -> dict:
        counts: dict[str, int] = {s.value: 0 for s in Severity}
        for f in self.all_findings:
            counts[f.severity.value] += 1
        return {
            "overall_risk": self.overall_risk.value,
            "finding_counts": counts,
            "total_findings": len(self.all_findings),
        }

    def as_dict(self) -> dict:
        return {
            "target": self.target,
            "target_type": self.target_type,
            "timestamp": self.timestamp,
            "summary": self.summary(),
            "module_results": [mr.as_dict() for mr in self.module_results],
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.as_dict(), indent=indent)

    def save(self, path: str) -> None:
        with open(path, "w") as fh:
            fh.write(self.to_json())
