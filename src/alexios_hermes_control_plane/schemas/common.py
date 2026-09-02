from enum import StrEnum
from typing import Any, Literal

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


class VerificationVerdict(StrictModel):
    finding_id: str
    verdict: Literal["GROUNDED", "PARTIAL", "UNGROUNDED"]
    reason: str


class Finding(StrictModel):
    finding_id: str
    category: str
    title: str
    summary: str
    impact: int = Field(ge=0, le=10)
    confidence: float = Field(ge=0, le=1)
    evidence_ids: list[str] = Field(default_factory=list)
    recommended_action: str
    verification: Literal["GROUNDED", "PARTIAL", "UNGROUNDED", "UNVERIFIED"] = "UNVERIFIED"


class InterventionFeedbackItem(StrictModel):
    run_id: str
    intervention_rank: int = Field(ge=1, le=3)
    verdict: Literal["ADOPTED", "REJECTED", "EXECUTED_VERIFIED", "EXECUTED_NO_SIGNAL", "PARTIAL"]
    outcome_note: str | None = None
    metrics_delta: dict[str, Any] = Field(default_factory=dict)


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
    decision_score: float | None = Field(default=None, ge=0, le=100)


class VerifierOutput(StrictModel):
    verdicts: list[VerificationVerdict] = Field(default_factory=list, max_length=40)


class PortfolioRunContext(StrictModel):
    """Context assembled from ledger state and config, injected into all specialists."""

    sites: list[dict[str, str]] = Field(default_factory=list, max_length=50)
    mode: str = "READ_ONLY"
    evidence: list[Evidence] = Field(default_factory=list, max_length=100)
    evidence_note: str = "Stage-1 control-plane run; live evidence connectors are not enabled yet."
    operating_rules: list[str] = Field(default_factory=list, max_length=30)
    recent_runs: list[dict[str, Any]] = Field(default_factory=list, max_length=10)
    feedback_memory: list[InterventionFeedbackItem] = Field(default_factory=list, max_length=50)


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
