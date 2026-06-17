from __future__ import annotations

import re
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, model_validator


class EvidenceSource(str, Enum):
    user_statement = "user_statement"
    police_record = "police_record"
    forensic_report = "forensic_report"
    toxicology_test = "toxicology_test"
    electronic_evidence = "electronic_evidence"
    system_inference = "system_inference"
    unknown = "unknown"


class ForensicStatus(str, Enum):
    mentioned = "mentioned"
    suspected = "suspected"
    forensic_confirmed = "forensic_confirmed"
    denied = "denied"
    unknown = "unknown"
    not_available = "not_available"


class ExhibitStatus(str, Enum):
    seized = "seized"
    consumed = "consumed"
    not_seized = "not_seized"
    mentioned = "mentioned"
    suspected = "suspected"
    forensic_confirmed = "forensic_confirmed"
    denied = "denied"
    unknown = "unknown"
    not_available = "not_available"


def _slug(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9]+", "_", value.lower()).strip("_")
    return normalized[:48] or "exhibit"


def _default_exhibit_id(description: str, form: str | None) -> str:
    haystack = f"{form or ''} {description or ''}".lower()
    if "viên" in haystack or "tablet" in haystack:
        return "tablets"
    if "gói" in haystack or "bột" in haystack or "powder" in haystack or "ketamine" in haystack:
        return "powder"
    return _slug(description)


class FactConflict(BaseModel):
    path: str
    existing_value: Any
    incoming_value: Any
    existing_source: str | None = None
    incoming_source: str | None = None
    resolution: str = "needs_review"


class Actor(BaseModel):
    name: str
    role: str | None = None
    age: int | None = None
    notes: str | None = None


class Quantity(BaseModel):
    value: float | None = None
    unit: str | None = None
    raw_text: str
    object: str | None = None


class SubstanceFact(BaseModel):
    name: str
    alias: str | None = None
    quantity: Quantity | None = None
    confidence: float = 0.8
    evidence_source: EvidenceSource = EvidenceSource.user_statement


class ExhibitFact(BaseModel):
    status: ExhibitStatus = ExhibitStatus.mentioned
    description: str
    id: str | None = None
    form: str | None = None
    suspected_substance: str | None = None
    confirmed_substance: str | None = None
    forensic_status: ForensicStatus = ForensicStatus.unknown
    quantity: Quantity | None = None
    source_text: str | None = None
    evidence_source: EvidenceSource = EvidenceSource.user_statement
    confidence: float = 0.5

    @model_validator(mode="after")
    def ensure_id_and_forensic_status(self) -> "ExhibitFact":
        if not self.id:
            self.id = _default_exhibit_id(self.description, self.form)
        if self.confirmed_substance and self.forensic_status == ForensicStatus.unknown:
            self.forensic_status = ForensicStatus.forensic_confirmed
        if self.suspected_substance and self.forensic_status == ForensicStatus.unknown:
            self.forensic_status = ForensicStatus.suspected
        return self


class ExtractedFacts(BaseModel):
    actors: list[Actor] = Field(default_factory=list)
    actions: list[str] = Field(default_factory=list)
    objects: list[str] = Field(default_factory=list)
    substances: list[SubstanceFact] = Field(default_factory=list)
    exhibits: list[ExhibitFact] = Field(default_factory=list)
    quantities: list[Quantity] = Field(default_factory=list)
    consequences: list[str] = Field(default_factory=list)
    age_info: list[str] = Field(default_factory=list)
    intent: list[str] = Field(default_factory=list)
    mental_state: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    location: list[str] = Field(default_factory=list)
    article_refs: list[str] = Field(default_factory=list)
    crime_hints: list[str] = Field(default_factory=list)
    mitigating_signals: list[str] = Field(default_factory=list)
    aggravating_signals: list[str] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    structured_facts: dict[str, Any] = Field(default_factory=dict)
    conflicts: list[FactConflict] = Field(default_factory=list)
