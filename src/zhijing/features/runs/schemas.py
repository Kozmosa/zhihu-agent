"""Durable workflow contracts; configuration contains labels, never endpoints or keys."""

from typing import Literal

from pydantic import Field, field_validator

from zhijing.domain.models import Schema
from zhijing.features.companion.schemas import CompanionRequest, CompanionResult, Task

RunStatus = Literal[
    "pending", "running", "succeeded", "partial", "failed", "interrupted", "cancelled", "timed_out"
]
StepStatus = Literal["pending", "running", "succeeded", "failed", "interrupted", "cancelled"]


class RunRequest(CompanionRequest):
    tasks: list[Task] = Field(
        default_factory=lambda: ["reading", "cards", "knowledge"], min_length=1, max_length=5
    )
    prepare_only: bool = False
    timeout_seconds: int = Field(600, ge=1, le=3600)
    max_attempts: int = Field(3, ge=1, le=5)

    @field_validator("tasks")
    @classmethod
    def unique_tasks(cls, value):
        if len(value) != len(set(value)):
            raise ValueError("tasks must not contain duplicates")
        return value


class RunError(Schema):
    code: str
    message: str
    retryable: bool = True


class RunStep(Schema):
    task: Task
    status: StepStatus = "pending"
    attempts: int = 0
    provider: str | None = None
    model: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    error: RunError | None = None


class RunRecord(Schema):
    id: str
    status: RunStatus = "pending"
    request: RunRequest
    source_ids: list[str]
    provider: str
    model: str | None = None
    attempts: int = 0
    cancel_requested: bool = False
    created_at: str
    updated_at: str
    started_at: str | None = None
    finished_at: str | None = None
    steps: list[RunStep]
    result: CompanionResult


class RunSummary(Schema):
    id: str
    source_id: str
    status: RunStatus
    tasks: list[Task]
    succeeded_steps: int
    total_steps: int
    attempts: int
    provider: str
    model: str | None = None
    cancel_requested: bool
    created_at: str
    updated_at: str
    finished_at: str | None = None


class RunPage(Schema):
    items: list[RunSummary]
    total: int
    offset: int
    limit: int
    has_more: bool
