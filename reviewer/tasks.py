"""
evidence_council/reviewer/tasks.py

ReviewTask, ReviewQueue, and ReviewVerdict.

ReviewTask is the unit of work emitted by GovernanceEvaluator when:
  - No evidence layer clears the 0.98 CI threshold (reason: "no_passing_layer")
  - Top-2 qualifying layers are within CLOSE_CALL_MARGIN (reason: "close_call")
  - A reviewer explicitly rejects the proposed winner (reason: "reviewer_rejection")

ReviewQueue is an in-memory ordered queue of pending tasks. It is intentionally
simple — persistence is handled by KnowledgeLayer, not by the queue itself.
The queue is the runtime routing mechanism; the knowledge layer is the audit trail.

reviewer_id convention
----------------------
Both human and agent reviewers use the same identifier format:
    human:<name>       e.g. "human:alice", "human:reviewer-1"
    agent:<name>       e.g. "agent:council-alpha", "agent:safety-reviewer"

This allows the same ReviewTask structure and ReviewQueue to serve both
human reviewers (today) and a council of agents (as it is built out) without
interface changes.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Callable, Iterator, Optional

if TYPE_CHECKING:
    # Avoid circular import — CandidateResult is defined in evaluator.py
    from evidence_council.evaluator import CandidateResult


# ---------------------------------------------------------------------------
# ReviewVerdict
# ---------------------------------------------------------------------------

class ReviewVerdict(str, Enum):
    """
    Possible outcomes of a reviewer decision.

    APPROVED:  Reviewer confirms the proposed (or explicitly chosen) winner.
               The winning layer is committed as the final governance decision.
               The knowledge layer is patched with the verdict and reviewer_id.

    REJECTED:  Reviewer rejects the proposed winner. If alternative qualifying
               layers exist, the task may be re-queued with reason
               "reviewer_rejection" for a second review pass.

    DEFERRED:  Reviewer cannot decide now. Task remains in the queue at
               elevated priority for re-review. Useful for async agent councils
               that need additional context before committing.
    """
    APPROVED = "approved"
    REJECTED = "rejected"
    DEFERRED = "deferred"


# ---------------------------------------------------------------------------
# ReviewTask
# ---------------------------------------------------------------------------

@dataclass
class ReviewTask:
    """
    A single unit of work for the review council.

    Emitted by GovernanceEvaluator; consumed by human reviewers via the
    dashboard UI or by agent reviewers via GovernanceEvaluator.apply_reviewer_decision().

    Fields
    ------
    task_id:            Unique identifier (UUID4). Stable across re-queues.
    reason:             Why this task was created. One of:
                            "no_passing_layer"   — no layer cleared 0.98
                            "close_call"         — top-2 within CLOSE_CALL_MARGIN
                            "reviewer_rejection" — prior reviewer rejected winner
    probe:              The probe name from the originating evaluation.
    detector:           The detector name from the originating evaluation.
    qualifying_results: All CandidateResult objects that cleared the threshold.
                        Empty list when reason is "no_passing_layer".
    all_results:        All evaluated CandidateResult objects, passing or not.
    proposed_winner:    The algorithmically-selected best candidate, or None.
    status:             Current task status. One of:
                            "pending"   — awaiting review
                            "approved"  — reviewer confirmed winner
                            "rejected"  — reviewer rejected proposed winner
                            "deferred"  — reviewer deferred decision
    reviewer_id:        ID of the reviewer who acted on this task, or None.
                        Convention: "human:<name>" or "agent:<name>".
    reviewer_notes:     Free-text notes from the reviewer, or None.
    created_at:         ISO-8601 UTC timestamp of task creation.
    resolved_at:        ISO-8601 UTC timestamp of resolution, or None.
    priority:           Integer priority for queue ordering. Lower = higher priority.
                        Deferred tasks are re-queued at priority - 1 (elevated).
    parent_task_id:     task_id of the task this was re-queued from, if any.
    """

    task_id:             str = field(default_factory=lambda: str(uuid.uuid4()))
    reason:              str = "no_passing_layer"
    probe:               str = ""
    detector:            str = ""
    qualifying_results:  list["CandidateResult"] = field(default_factory=list)
    all_results:         list["CandidateResult"] = field(default_factory=list)
    proposed_winner:     Optional["CandidateResult"] = None
    status:              str = "pending"
    reviewer_id:         Optional[str] = None
    reviewer_notes:      Optional[str] = None
    created_at:          str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    resolved_at:         Optional[str] = None
    priority:            int = 0
    parent_task_id:      Optional[str] = None

    # ------------------------------------------------------------------
    # Status helpers
    # ------------------------------------------------------------------

    @property
    def is_pending(self) -> bool:
        return self.status == "pending"

    @property
    def is_resolved(self) -> bool:
        return self.status in ("approved", "rejected")

    @property
    def is_deferred(self) -> bool:
        return self.status == "deferred"

    # ------------------------------------------------------------------
    # Resolution
    # ------------------------------------------------------------------

    def resolve(
        self,
        verdict: ReviewVerdict,
        reviewer_id: str,
        notes: Optional[str] = None,
    ) -> None:
        """
        Apply a reviewer verdict to this task.

        Sets status, reviewer_id, reviewer_notes, and resolved_at.
        Does NOT patch the knowledge layer — that is handled by
        GovernanceEvaluator.apply_reviewer_decision() which calls this
        method and then patches the knowledge layer records.

        Args:
            verdict:     ReviewVerdict enum value.
            reviewer_id: Reviewer identifier. Convention: "human:<name>" or
                         "agent:<name>".
            notes:       Optional free-text rationale.
        """
        self.status       = verdict.value
        self.reviewer_id  = reviewer_id
        self.reviewer_notes = notes
        if verdict != ReviewVerdict.DEFERRED:
            self.resolved_at = datetime.now(timezone.utc).isoformat()

    def requeue_as_rejection(self) -> "ReviewTask":
        """
        Create a new ReviewTask to handle a reviewer rejection.

        The new task inherits qualifying_results and all_results from the
        original, increments priority (elevated), and sets reason to
        "reviewer_rejection". The parent_task_id links back to this task
        for audit trail purposes.

        Returns:
            A new ReviewTask with status "pending" and elevated priority.
        """
        return ReviewTask(
            reason="reviewer_rejection",
            probe=self.probe,
            detector=self.detector,
            qualifying_results=self.qualifying_results,
            all_results=self.all_results,
            proposed_winner=self.proposed_winner,
            priority=self.priority - 1,        # lower int = higher priority
            parent_task_id=self.task_id,
        )

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def summary(self) -> dict:
        """
        Lightweight serialisable summary for logging and dashboard display.
        Does not include full CandidateResult objects.
        """
        return {
            "task_id":         self.task_id,
            "reason":          self.reason,
            "probe":           self.probe,
            "detector":        self.detector,
            "status":          self.status,
            "priority":        self.priority,
            "created_at":      self.created_at,
            "resolved_at":     self.resolved_at,
            "reviewer_id":     self.reviewer_id,
            "reviewer_notes":  self.reviewer_notes,
            "parent_task_id":  self.parent_task_id,
            "n_qualifying":    len(self.qualifying_results),
            "n_evaluated":     len(self.all_results),
            "proposed_winner": (
                self.proposed_winner.layer.name if self.proposed_winner else None
            ),
        }


# ---------------------------------------------------------------------------
# ReviewQueue
# ---------------------------------------------------------------------------

class ReviewQueue:
    """
    In-memory ordered queue of pending ReviewTask objects.

    Tasks are sorted by priority (ascending integer — lower = higher urgency)
    then by created_at (ascending — older tasks first within same priority).

    Persistence is handled by KnowledgeLayer, not by the queue. The queue is
    the runtime routing mechanism for the current process; KnowledgeLayer is
    the durable audit trail across processes and restarts.

    Usage
    -----
        queue = ReviewQueue()
        queue.enqueue(task)

        # Blocking iteration (e.g. in a review agent loop):
        for task in queue:
            decision = agent.review(task)
            task.resolve(decision.verdict, decision.reviewer_id, decision.notes)
            evaluator.apply_reviewer_decision(task, ...)
            if task.status == ReviewVerdict.REJECTED:
                queue.enqueue(task.requeue_as_rejection())
    """

    def __init__(self) -> None:
        self._tasks: list[ReviewTask] = []

    # ------------------------------------------------------------------
    # Queue operations
    # ------------------------------------------------------------------

    def enqueue(self, task: ReviewTask) -> None:
        """
        Add a task to the queue and re-sort by priority then created_at.

        Args:
            task: ReviewTask to enqueue. Must have status "pending".
        """
        if not task.is_pending:
            raise ValueError(
                f"Only pending tasks can be enqueued. "
                f"Task {task.task_id} has status '{task.status}'."
            )
        self._tasks.append(task)
        self._sort()

    def dequeue(self) -> Optional[ReviewTask]:
        """
        Remove and return the highest-priority pending task, or None if empty.
        """
        if not self._tasks:
            return None
        return self._tasks.pop(0)

    def peek(self) -> Optional[ReviewTask]:
        """Return the highest-priority task without removing it."""
        return self._tasks[0] if self._tasks else None

    def enqueue_many(self, tasks: list[ReviewTask]) -> None:
        """Enqueue multiple tasks and sort once."""
        for task in tasks:
            if not task.is_pending:
                raise ValueError(
                    f"Only pending tasks can be enqueued. "
                    f"Task {task.task_id} has status '{task.status}'."
                )
            self._tasks.append(task)
        self._sort()

    def remove(self, task_id: str) -> bool:
        """
        Remove a task by task_id. Returns True if found and removed.
        Useful for cancelling a task that was resolved out-of-band.
        """
        before = len(self._tasks)
        self._tasks = [t for t in self._tasks if t.task_id != task_id]
        return len(self._tasks) < before

    # ------------------------------------------------------------------
    # Filtering and inspection
    # ------------------------------------------------------------------

    def pending(self) -> list[ReviewTask]:
        """All tasks currently in the queue (all are pending by invariant)."""
        return list(self._tasks)

    def by_reason(self, reason: str) -> list[ReviewTask]:
        """Filter tasks by reason string."""
        return [t for t in self._tasks if t.reason == reason]

    def by_probe(self, probe: str) -> list[ReviewTask]:
        """Filter tasks by probe name."""
        return [t for t in self._tasks if t.probe == probe]

    def find(self, task_id: str) -> Optional[ReviewTask]:
        """Find a task by task_id without removing it."""
        return next((t for t in self._tasks if t.task_id == task_id), None)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def size(self) -> int:
        return len(self._tasks)

    @property
    def is_empty(self) -> bool:
        return len(self._tasks) == 0

    # ------------------------------------------------------------------
    # Iteration
    # ------------------------------------------------------------------

    def __iter__(self) -> Iterator[ReviewTask]:
        """
        Iterate over tasks in priority order, dequeuing each as it is yielded.
        New tasks enqueued during iteration will be yielded if their priority
        puts them ahead of remaining tasks.
        """
        while self._tasks:
            yield self._tasks.pop(0)

    def __len__(self) -> int:
        return self.size

    def __repr__(self) -> str:
        return f"ReviewQueue(size={self.size})"

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _sort(self) -> None:
        """Sort by priority asc, then created_at asc (FIFO within priority)."""
        self._tasks.sort(key=lambda t: (t.priority, t.created_at))
