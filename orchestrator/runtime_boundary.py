"""Fail-closed adapter boundary for T-003. No external execution is enabled.

This module deliberately does not call Claude, Codex, GitHub, or a paid API.
A caller must provide two independently authenticated runtime adapters.
"""
from dataclasses import dataclass
from enum import Enum
import re

_SHA = re.compile(r"[0-9a-f]{40}\Z")
class Decision(str, Enum):
    BLOCKED = "BLOCKED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    APPROVED = "APPROVED"

@dataclass(frozen=True)
class Review:
    repository: str
    head_sha: str
    reviewer: str
    decision: Decision

def validate_review(review: Review, *, repository: str, head_sha: str,
                    implementer: str, allowed_reviewer: str) -> Decision:
    """Only a current, independent, exact-HEAD approval can pass."""
    if not _SHA.fullmatch(head_sha) or review.repository != repository:
        return Decision.BLOCKED
    if review.head_sha != head_sha:
        return Decision.BLOCKED
    if not allowed_reviewer or allowed_reviewer == implementer:
        return Decision.BLOCKED
    if review.reviewer != allowed_reviewer:
        return Decision.BLOCKED
    if review.decision not in (Decision.APPROVED, Decision.CHANGES_REQUESTED):
        return Decision.BLOCKED
    return review.decision

def runtime_enabled(*, explicit_owner_approval: bool, implementer_ready: bool,
                    reviewer_ready: bool, distinct_credentials: bool,
                    billing_approved: bool, requires_paid_api: bool) -> bool:
    """No unattended run without all prerequisites; never implies merge."""
    return all((explicit_owner_approval, implementer_ready, reviewer_ready,
                distinct_credentials, billing_approved or not requires_paid_api))
