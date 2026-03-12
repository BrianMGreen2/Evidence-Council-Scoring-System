"""
evidence_council.reviewer
=========================

Review council interface for governance decisions.

Modules
-------
tasks
    ReviewTask, ReviewQueue, and ReviewVerdict. ReviewTask objects are
    emitted by GovernanceEvaluator when no layer clears the 0.98 threshold
    or when the top-2 composite scores fall within CLOSE_CALL_MARGIN.

    The reviewer_id field on ReviewTask accepts both human (human:name)
    and agent (agent:council-name) identifiers — the same interface works
    for human reviewers today and an agent council as it is built out.

ui/
    React dashboard (reviewer_ui.jsx) providing a queue interface for
    pending ReviewTask objects. Consumes the same ReviewTask structure
    emitted by GovernanceEvaluator.
"""

from evidence_council.reviewer.tasks import (
    ReviewTask,
    ReviewQueue,
    ReviewVerdict,
)

__all__ = [
    "ReviewTask",
    "ReviewQueue",
    "ReviewVerdict",
]
