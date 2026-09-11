from typing import Optional

from pydantic import BaseModel, Field, field_validator

from app.config import settings


class OrganisationLink(BaseModel):
    org_name: str
    relation_type: str
    label: Optional[str] = None
    is_person: bool = False  # true for coaches referenced by personal name

    @field_validator("relation_type")
    @classmethod
    def validate_relation_type(cls, v: str) -> str:
        if v not in settings.VALID_RELATION_TYPES:
            raise ValueError(
                f"relation_type '{v}' not in allowed set: {settings.VALID_RELATION_TYPES}"
            )
        return v


class AthleteInput(BaseModel):
    full_name: str
    dob: Optional[str] = None  # ISO date string, e.g. "1995-07-05"
    disciplines: list[str] = Field(default_factory=list)
    events: list[str] = Field(default_factory=list)
    primary_location: Optional[str] = None
    state: Optional[str] = None
    organisations: list[OrganisationLink] = Field(default_factory=list)


class SeedRequest(BaseModel):
    athletes: list[AthleteInput]


class SeedSummary(BaseModel):
    athletes_created: int
    athletes_matched_existing: int
    orgs_created: int
    orgs_merged: int
    relationships_created: int
    relationships_already_existed: int
    warnings: list[str] = Field(default_factory=list)
