"""`BettingResponseEvidence` — la provenance d'une réponse de pari (§2, §24).

Une réponse actionnable est interdite sans cet objet. Il ne décrit pas ce que le
modèle a dit ; il décrit ce que la chaîne structurée a RÉELLEMENT fait pendant le
tour courant : quand le scan a commencé, quelle fenêtre, quels sports, combien
d'événements, quel verdict, quel identifiant d'audit.

C'est aussi ce qui rend l'affirmation vérifiable. Une phrase comme « le moteur a
retourné BET » n'a de valeur que si un `audit_id` la désigne ; sans lui, elle est
indiscernable d'une phrase inventée — y compris pour celui qui la relit.

L'objet voyage DANS le `ToolMessage` du tour, pas dans un registre parallèle : la
preuve est ainsi le message lui-même, et non une affirmation à son sujet.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping, Sequence

EVIDENCE_KEY = "betting_evidence"
TOOL_NAME = "betting_recommend"


@dataclass(frozen=True)
class BettingResponseEvidence:
    request_id: str
    run_id: str
    scan_started_at: datetime
    scan_completed_at: datetime
    window_start: datetime
    window_end: datetime
    sports_scanned: tuple[str, ...]
    event_ids: tuple[str, ...]
    recommendation_outcome: str
    audit_id: str
    events_scanned: int = 0
    events_in_window: int = 0
    events_evaluated: int = 0
    reason_counts: Mapping[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "run_id": self.run_id,
            "scan_started_at": self.scan_started_at.isoformat(),
            "scan_completed_at": self.scan_completed_at.isoformat(),
            "window_start": self.window_start.isoformat(),
            "window_end": self.window_end.isoformat(),
            "sports_scanned": list(self.sports_scanned),
            "event_ids": list(self.event_ids),
            "recommendation_outcome": self.recommendation_outcome,
            "audit_id": self.audit_id,
            "events_scanned": self.events_scanned,
            "events_in_window": self.events_in_window,
            "events_evaluated": self.events_evaluated,
            "reason_counts": dict(self.reason_counts),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "BettingResponseEvidence":
        return cls(
            request_id=payload["request_id"],
            run_id=payload["run_id"],
            scan_started_at=datetime.fromisoformat(payload["scan_started_at"]),
            scan_completed_at=datetime.fromisoformat(payload["scan_completed_at"]),
            window_start=datetime.fromisoformat(payload["window_start"]),
            window_end=datetime.fromisoformat(payload["window_end"]),
            sports_scanned=tuple(payload.get("sports_scanned") or ()),
            event_ids=tuple(payload.get("event_ids") or ()),
            recommendation_outcome=payload["recommendation_outcome"],
            audit_id=payload["audit_id"],
            events_scanned=int(payload.get("events_scanned", 0)),
            events_in_window=int(payload.get("events_in_window", 0)),
            events_evaluated=int(payload.get("events_evaluated", 0)),
            reason_counts=dict(payload.get("reason_counts") or {}),
        )


#: Les seuls verdicts qui autorisent une réponse ACTIONNABLE (§18). Tout le
#: reste — revue, aucune opportunité, aucun événement évaluable, échec — permet
#: d'expliquer, jamais de proposer une mise ni une procédure de placement.
ACTIONABLE_OUTCOMES = frozenset({"RECOMMENDED"})


def extract_evidence(messages: Sequence[Any]) -> BettingResponseEvidence | None:
    """Preuve produite pendant le TOUR COURANT, ou `None`.

    « Tour courant » = depuis le dernier message humain. Une preuve d'un tour
    antérieur ne prouve rien du tour présent : les cotes ont bougé, la fenêtre a
    glissé, et un match de la réponse précédente a peut-être commencé. C'est
    précisément la réutilisation d'une ancienne sortie qui produit des cotes
    périmées présentées comme actuelles (§20).
    """
    for message in reversed(current_turn(messages)):
        if _role(message) != "tool" or getattr(message, "name", None) != TOOL_NAME:
            continue
        payload = _json(message)
        if payload and isinstance(payload.get(EVIDENCE_KEY), dict):
            try:
                return BettingResponseEvidence.from_dict(payload[EVIDENCE_KEY])
            except (KeyError, ValueError):
                return None
    return None


#: Outils dont la sortie est STRUCTURÉE : leur présence dans le tour prouve
#: qu'un moteur a réellement tourné — sans pour autant autoriser une mise, qui
#: exige la preuve complète (`betting_recommend`).
STRUCTURED_TOOLS = frozenset({
    TOOL_NAME, "ev_analyze", "probability_compute",
    "parlay_analyze", "same_match_combo_analyze",
})


def current_turn(messages: Sequence[Any]) -> list[Any]:
    """Messages produits depuis le dernier message humain."""
    debut = 0
    for index, message in enumerate(messages):
        if _role(message) == "human":
            debut = index + 1
    return list(messages[debut:])


def has_structured_output(messages: Sequence[Any]) -> bool:
    """Un outil structuré a-t-il répondu pendant le tour courant ?

    Distinct de `extract_evidence` : ici on constate qu'un moteur a tourné, pas
    qu'une recommandation existe. « ev_analyze a retourné ABSTAIN » est une
    phrase vraie dans ce cas ; « le moteur a retourné BET » ne l'est pas pour
    autant.
    """
    return any(
        _role(message) == "tool"
        and getattr(message, "name", None) in STRUCTURED_TOOLS
        and isinstance(_json(message), dict)
        for message in current_turn(messages)
    )


def _role(message: Any) -> str:
    role = getattr(message, "type", None)
    return role if isinstance(role, str) else ""


def _json(message: Any) -> dict | None:
    content = getattr(message, "content", None)
    if not isinstance(content, str):
        return None
    try:
        payload = json.loads(content)
    except (ValueError, TypeError):
        return None
    return payload if isinstance(payload, dict) else None
