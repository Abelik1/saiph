# SPDX-License-Identifier: AGPL-3.0-or-later
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id() -> str:
    return uuid4().hex


@dataclass
class TranscriptSegment:
    id: str
    track: int
    start: float
    end: float
    raw_text: str
    text: str
    avg_logprob: float | None = None
    no_speech_prob: float | None = None
    revisions: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TranscriptSegment":
        return cls(**data)


@dataclass
class Annotation:
    id: str
    body: str
    scope: Literal["project", "transcript", "segments"]
    segment_ids: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SummaryRecord:
    mode: Literal["brief", "detailed", "meeting"]
    content: str
    model: str
    source_revision: str
    generated_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ProjectManifest:
    id: str
    name: str
    created_at: str = field(default_factory=utc_now)
    version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TranscriptionJob:
    id: str
    source_path: str
    project_path: str
    transcript_id: str = field(default_factory=new_id)
    model: str = "turbo"
    device: Literal["auto", "cuda", "cpu"] = "auto"
    language: str = "auto"
    batch_seconds: int = 600

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TranscriptionJob":
        return cls(**data)


@dataclass
class Reminder:
    id: str
    title: str
    due_at: str | None = None
    recurrence: str | None = None
    kind: Literal["timer", "reminder", "stopwatch", "break"] = "reminder"
    attention: Literal["gentle", "noticeable", "urgent"] = "noticeable"
    status: Literal["active", "paused", "completed", "cancelled", "snoozed"] = "active"
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

