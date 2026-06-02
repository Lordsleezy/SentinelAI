"""Phase 10 — submission placeholders only (not implemented)."""
from __future__ import annotations

from workers.earn.research.models import SubmissionPlaceholders


def empty_submission_placeholders() -> SubmissionPlaceholders:
    return SubmissionPlaceholders(
        submission_draft=None,
        impact_analysis=None,
        reproduction_steps=None,
        note="Automatic bounty submission is not enabled. Complete human review first.",
    )
