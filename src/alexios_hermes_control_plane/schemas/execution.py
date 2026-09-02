from enum import StrEnum

from pydantic import Field, model_validator

from alexios_hermes_control_plane.schemas.common import StrictModel


class MutationType(StrEnum):
    TITLE = "TITLE"
    CONTENT = "CONTENT"


class WordPressTarget(StrictModel):
    site_id: str
    url: str


class WordPressSnapshot(StrictModel):
    site_id: str
    post_id: int = Field(ge=1)
    url: str
    slug: str
    status: str
    title_raw: str
    content_raw: str
    modified_gmt: str | None = None


class WordPressMutation(StrictModel):
    mutation_id: str
    site_id: str
    target_url: str
    post_id: int = Field(ge=1)
    mutation_type: MutationType
    value: str = Field(min_length=1, max_length=250000)
    reason: str = Field(min_length=3, max_length=2000)
    evidence_ids: list[str] = Field(default_factory=list, max_length=50)


class ImplementationPlan(StrictModel):
    summary: str = Field(min_length=3, max_length=3000)
    mutations: list[WordPressMutation] = Field(default_factory=list, max_length=3)

    @model_validator(mode="after")
    def enforce_single_target_per_mutation(self) -> "ImplementationPlan":
        ids = [item.mutation_id for item in self.mutations]
        if len(ids) != len(set(ids)):
            raise ValueError("mutation_id values must be unique")
        return self


class MutationReceipt(StrictModel):
    mutation_id: str
    site_id: str
    post_id: int
    target_url: str
    status: str
    before_sha256: str
    after_sha256: str | None = None
    backup_path: str | None = None
    validation_error: str | None = None
    rolled_back: bool = False
