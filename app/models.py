"""Domain data models and typed schemas for the clip2 pipeline."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class JobRecord:
    """Active or persisted job record in current_job.json."""

    job_id: str
    url: str
    run_id: str | None = None
    started_at: str | None = None
    status: str = "running"
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> JobRecord:
        return cls(
            job_id=str(data.get("job_id", "")),
            url=str(data.get("url", "")),
            run_id=data.get("run_id"),
            started_at=data.get("started_at"),
            status=str(data.get("status", "running")),
            error=data.get("error"),
        )


@dataclass(slots=True)
class CandidateClip:
    """Targeted candidate window for LLM clip selection."""

    id: int
    window_start: float
    window_end: float
    peak_time: float
    peak_score: float
    types: dict[str, float] = field(default_factory=dict)
    start: float = 0.0
    end: float = 0.0
    reason: str = ""
    llm_used: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CandidateClip:
        return cls(
            id=int(data["id"]),
            window_start=float(data["window_start"]),
            window_end=float(data["window_end"]),
            peak_time=float(data["peak_time"]),
            peak_score=float(data["peak_score"]),
            types=dict(data.get("types", {})),
            start=float(data.get("start", 0.0)),
            end=float(data.get("end", 0.0)),
            reason=str(data.get("reason", "")),
            llm_used=bool(data.get("llm_used", False)),
        )


@dataclass(slots=True)
class ActivityBin:
    """Time-binned audio and transcription activity."""

    index: int
    time: str
    start: float
    end: float
    words: int
    loud: float
    laugh: float
    scream: float
    shout: float
    music: float
    rel_db: float
    windows: int = 0
    speech: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ActivitySummary:
    """Full activity breakdown including bins, minute aggregates, and heatmap."""

    duration: float
    bin_seconds: int
    bins: list[dict[str, Any]]
    heatmap: list[dict[str, Any]]
    minutes: list[dict[str, Any]]
    totals: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class StageOverview:
    """Overview status and readiness of a pipeline stage."""

    id: str
    title: str
    number: int
    description: str
    status: str
    ready: bool
    summary: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class TargetedResult:
    """Metadata result from targeted clip selection."""

    status: str
    mode: str
    path: str
    updated_at: str
    finished_at: str
    error: str | None
    summary: dict[str, Any] = field(default_factory=dict)
    previews: list[dict[str, Any]] = field(default_factory=list)
    files: list[dict[str, Any]] = field(default_factory=list)
    selections: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
