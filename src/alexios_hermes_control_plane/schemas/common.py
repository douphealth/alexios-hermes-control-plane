from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RunMode(StrEnum):
    READ_ONLY = "READ_ONLY"
    DRAFT = "DRAFT"
    STAGING = "STAGING"
    PRODUCTION_APPROVED = "PRODUCTION_APPROVED"


class AgentStatus(StrEnum):
    SUCCESS = "SUCCESS"
    NEEDS_DATA = "NEEDS_DATA"
    FAILED = "FAILED"


class Evidence(StrictModel):
    evidence_id: str
    source: str
    summary: str
    payload: dict[str, Any] = Field(default_factory=dict)


class Finding(StrictModel):
    finding_id: str
    category: str
    title: str
    summary: str
    impact: int = Field(ge=0, le=10)
    confidence: float = Field(ge=0, le=1)
    evidence_ids: list[str] = Field(default_factory=list)
    recommended_action: str


class SpecialistOutput(StrictModel):
    status: AgentStatus
    summary: str
    findings: list[Finding] = Field(default_factory=list, max_length=10)
    evidence_ids: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list, max_length=10)
    error: str | None = None


class AgentResult(SpecialistOutput):
    agent: str
    model: str
    prompt_version: str
    provider_request_id: str | None = None
    latency_ms: int | None = Field(default=None, ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)


class Intervention(StrictModel):
    rank: int = Field(ge=1, le=3)
    title: str
    target: str
    action: str
    impact: int = Field(ge=0, le=10)
    confidence: float = Field(ge=0, le=1)
    revenue_alignment: int = Field(ge=0, le=10)
    effort: int = Field(ge=0, le=10)
    risk: str
    reversibility: int = Field(ge=0, le=10)
    time_to_signal: int = Field(ge=0, le=10)
    evidence_ids: list[str] = Field(default_factory=list)
    expected_signal: str


class JudgeOutput(StrictModel):
    interventions: list[Intervention] = Field(min_length=1, max_length=3)

    @model_validator(mode="after")
    def validate_unique_ranks(self) -> "JudgeOutput":
        ranks = [item.rank for item in self.interventions]
        if len(ranks) != len(set(ranks)):
            raise ValueError("intervention ranks must be unique")
        if sorted(ranks) != list(range(1, len(ranks) + 1)):
            raise ValueError("intervention ranks must be contiguous from 1")
        self.interventions.sort(key=lambda item: item.rank)
        return self


class PortfolioRunRequest(StrictModel):
    objective: str = Field(min_length=3, max_length=4000)
    mode: RunMode = RunMode.READ_ONLY
    sites: list[str] = Field(default_factory=list, max_length=50)


class PortfolioWorkflowInput(StrictModel):
    request: PortfolioRunRequest
    notification_chat_id: int | None = None


class PortfolioRunResult(StrictModel):
    run_id: str
    mode: RunMode
    status: str
    interventions: list[Intervention]
    specialist_results: list[AgentResult]
