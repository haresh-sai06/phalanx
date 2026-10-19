"""Shared types for Phalanx findings and agent state."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


Severity = Literal["critical", "high", "medium", "low", "info"]
Category = Literal["security", "functional", "ux"]


@dataclass
class Finding:
    title: str
    category: Category
    severity: Severity
    url: str
    evidence: str
    fingerprint: str
    persona: str = "explorer"
    repro_steps: list[str] = field(default_factory=list)
    cvss_hint: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AgentState:
    """LangGraph state. Kept as a plain dict-compatible dataclass."""
    base_url: str
    max_steps: int = 40
    mode: str = "heuristic"  # heuristic | llm
    visited: list[str] = field(default_factory=list)
    queue: list[str] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    cookies: dict[str, str] = field(default_factory=dict)
    step: int = 0
    notes: list[str] = field(default_factory=list)
    known_rides: list[int] = field(default_factory=list)
    done: bool = False
