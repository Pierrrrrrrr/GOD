"""Selective, bounded exchange between permanently independent colonies."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class WorkClass(StrEnum):
    REFLEX = "REFLEX"; FOCUSED = "FOCUSED"; DELIBERATIVE = "DELIBERATIVE"; BACKGROUND = "BACKGROUND"

class BriefResponse(StrEnum):
    ACCEPT = "ACCEPT"; CHALLENGE = "CHALLENGE"; IGNORE = "IGNORE"; COUNTERPROPOSE = "COUNTERPROPOSE"

class DigestResponse(StrEnum):
    ADOPT = "ADOPT"; TEST_INDEPENDENTLY = "TEST_INDEPENDENTLY"; REJECT = "REJECT"; PRESERVE_ALTERNATIVE = "PRESERVE_ALTERNATIVE"

@dataclass(frozen=True, slots=True)
class SisterBrief:
    source: str; core_claim: str; proposed_next_action: str; evidence_refs: tuple[str, ...]
    confidence: float; critical_assumptions: tuple[str, ...] = (); unknowns: tuple[str, ...] = ()
    capability_gaps: tuple[str, ...] = (); prediction: str = ""

@dataclass(frozen=True, slots=True)
class SisterDevelopmentDigest:
    source: str; verified_successes: tuple[str, ...]; verified_failures: tuple[str, ...]
    new_specialization: str | None; capability_acquired: str | None
    routing_improvement: str; strategy_lesson: str; evidence_refs: tuple[str, ...]; verified: bool

@dataclass(slots=True)
class SisterView:
    colony: str; reasoning: dict[str, Any]; received_briefs: list[dict[str, Any]] = field(default_factory=list)
    adopted_lessons: list[str] = field(default_factory=list); minority_hypotheses: list[str] = field(default_factory=list)


class SisterExchangePolicy:
    TRIGGERS = {"material_disagreement", "high_uncertainty", "high_impact", "prediction_failure",
                "new_capability", "verified_competence", "post_outcome_learning"}
    def __init__(self): self.rounds: dict[str, int] = {}
    def exchange(self, task_id: str, source: SisterView, target: SisterView, brief: SisterBrief,
                 response: BriefResponse, *, trigger: str, high_risk: bool = False,
                 counterproposal: str | None = None) -> bool:
        if trigger not in self.TRIGGERS: return False
        limit, used = (2 if high_risk else 1), self.rounds.get(task_id, 0)
        if used >= limit: return False
        # Only the compact brief crosses the boundary, never reasoning/private memory.
        target.received_briefs.append({**asdict(brief), "response": response.value})
        if response in {BriefResponse.CHALLENGE, BriefResponse.COUNTERPROPOSE}:
            target.minority_hypotheses.append(counterproposal or brief.core_claim)
        self.rounds[task_id] = used + 1; return True

    @staticmethod
    def apply_digest(target: SisterView, digest: SisterDevelopmentDigest,
                     response: DigestResponse) -> bool:
        if not digest.verified or not digest.evidence_refs: return False
        if response in {DigestResponse.ADOPT, DigestResponse.TEST_INDEPENDENTLY}:
            target.adopted_lessons.append(digest.strategy_lesson); return True
        if response == DigestResponse.PRESERVE_ALTERNATIVE:
            target.minority_hypotheses.append(digest.strategy_lesson)
        return False


def classify_work(message: str, *, risk: float = 0, uncertainty: float = 0) -> WorkClass:
    text = message.lower().strip()
    if text in {"hi", "hello", "status", "what are you doing?"}: return WorkClass.REFLEX
    if "background" in text: return WorkClass.BACKGROUND
    if risk >= .6 or uncertainty >= .6 or any(x in text for x in ("research", "audit", "irreversible")): return WorkClass.DELIBERATIVE
    return WorkClass.FOCUSED


def recruited_colonies(work_class: WorkClass, *, triggered: bool = False) -> tuple[str, ...]:
    if work_class == WorkClass.REFLEX: return ()
    if work_class == WorkClass.DELIBERATIVE or triggered: return ("Saphira-A", "Saphira-B")
    return ("Saphira-A",)
