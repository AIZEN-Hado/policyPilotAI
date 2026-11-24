"""
Input validation models and guardrails using Pydantic.
"""
from __future__ import annotations

import re
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


class ClaimType(str, Enum):
    MEDICAL    = "medical"
    PROPERTY   = "property"
    AUTO       = "auto"
    LIFE       = "life"
    LIABILITY  = "liability"
    TRAVEL     = "travel"
    OTHER      = "other"


class DecisionLabel(str, Enum):
    COVERED              = "COVERED"
    PARTIALLY_COVERED    = "PARTIALLY_COVERED"
    EXCLUDED             = "EXCLUDED"
    REQUIRES_MORE_INFO   = "REQUIRES_MORE_INFO"
    UNKNOWN              = "UNKNOWN"


class ClaimRequest(BaseModel):
    """Incoming claim submitted by a claimant or adjuster."""

    claimant_name:  Optional[str]   = Field(None, max_length=120)
    policy_number:  Optional[str]   = Field(None, max_length=50)
    claim_type:     ClaimType       = Field(..., description="Type of insurance claim")
    incident_date:  Optional[str]   = Field(None, description="Date of incident (YYYY-MM-DD)")
    claim_amount:   Optional[float] = Field(None, ge=0)
    description:    str             = Field(
        ...,
        min_length=20,
        max_length=4000,
        description="Detailed description of the claim",
    )

    @field_validator("description")
    @classmethod
    def no_pii_keywords(cls, v: str) -> str:
        if re.search(r"\b\d{3}-\d{2}-\d{4}\b", v):
            raise ValueError(
                "Description appears to contain a Social Security Number. "
                "Please remove all PII before submitting."
            )
        return v


class DecisionResponse(BaseModel):
    """Structured coverage decision returned by the engine."""

    decision:         DecisionLabel
    confidence:       float         = Field(..., ge=0.0, le=1.0)
    reasoning:        str
    relevant_clauses: List[str]     = Field(default_factory=list)
    exclusions_noted: List[str]     = Field(default_factory=list)
    recommendation:   str           = ""
