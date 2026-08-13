"""Un sas entre ce qu'on a trouvé et ce que le modèle apprend.

Écrire directement dans le dataset canonique rendrait toute erreur définitive et
invisible : une source mal classée, une identité fausse, un doublon, et le
prochain benchmark mesure un modèle sur des données qu'on ne sait plus
distinguer des bonnes. Le sas rend l'entrée RÉVERSIBLE et l'exclusion LISIBLE.

CE QUI EST REJETÉ RESTE. Supprimer une observation refusée effacerait la trace
de la décision, et la même source reviendrait à la découverte suivante sans que
rien ne rappelle pourquoi elle avait été écartée. Le rejet est donc un état, pas
une suppression.

L'ORDRE DES ÉTAPES EST UNE GARANTIE. Vérifier l'identité APRÈS avoir dédoublonné
apparierait sur des identifiants de sources différentes ; benchmarker avant de
vérifier la provenance validerait des données qu'on n'a pas le droit d'utiliser.
La progression est donc contrainte : on ne saute pas une étape.
"""

from __future__ import annotations

import json
import pathlib
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class StagingState(str, Enum):
    """Les états du sas (§10), dans l'ordre où ils s'obtiennent."""

    DISCOVERED = "DISCOVERED"
    FETCHED = "FETCHED"
    NORMALIZED = "NORMALIZED"
    IDENTITY_VERIFIED = "IDENTITY_VERIFIED"
    DEDUPLICATED = "DEDUPLICATED"
    PROVENANCE_VERIFIED = "PROVENANCE_VERIFIED"
    STAGED = "STAGED"
    BENCHMARKED = "BENCHMARKED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


#: Progression autorisée. `REJECTED` est atteignable depuis PARTOUT — un défaut
#: peut apparaître à n'importe quelle étape — mais rien n'en sort : une donnée
#: refusée ne se réhabilite pas en silence, elle repart d'une découverte.
_SUIVANTS: dict[StagingState, tuple[StagingState, ...]] = {
    StagingState.DISCOVERED: (StagingState.FETCHED,),
    StagingState.FETCHED: (StagingState.NORMALIZED,),
    StagingState.NORMALIZED: (StagingState.IDENTITY_VERIFIED,),
    StagingState.IDENTITY_VERIFIED: (StagingState.DEDUPLICATED,),
    StagingState.DEDUPLICATED: (StagingState.PROVENANCE_VERIFIED,),
    StagingState.PROVENANCE_VERIFIED: (StagingState.STAGED,),
    StagingState.STAGED: (StagingState.BENCHMARKED,),
    StagingState.BENCHMARKED: (StagingState.ACCEPTED,),
    StagingState.ACCEPTED: (),
    StagingState.REJECTED: (),
}

TERMINAUX = (StagingState.ACCEPTED, StagingState.REJECTED)


class TransitionInterdite(ValueError):
    """Une étape sautée est une garantie perdue, pas un raccourci."""


def transition_permise(depuis: StagingState, vers: StagingState) -> bool:
    if vers is StagingState.REJECTED:
        return depuis not in TERMINAUX
    return vers in _SUIVANTS[depuis]


@dataclass(frozen=True)
class StagedObservation:
    """Une observation dans le sas, avec l'historique de ce qu'elle a franchi.

    `history` n'est pas un journal décoratif : c'est ce qui permet de dire
    POURQUOI une donnée est en production, et de refaire le chemin quand un
    benchmark surprend.
    """

    evidence: object                       # HistoricalMatchEvidence
    state: StagingState
    batch_id: str
    history: tuple[tuple[str, str, str], ...] = ()   # (état, raison, horodatage)
    canonical_participants: tuple[str, ...] | None = None   # après IDENTITY_VERIFIED
    rejection_reason: str = ""

    def avancer(self, vers: StagingState, raison: str, *,
                horodatage: datetime | None = None,
                canonical_participants=None) -> "StagedObservation":
        if not transition_permise(self.state, vers):
            raise TransitionInterdite(
                f"{self.state.value} -> {vers.value} : étape sautée ou état terminal")
        quand = (horodatage or _utcnow()).isoformat()
        return StagedObservation(
            evidence=self.evidence,
            state=vers,
            batch_id=self.batch_id,
            history=(*self.history, (vers.value, raison, quand)),
            canonical_participants=(canonical_participants
                                    if canonical_participants is not None
                                    else self.canonical_participants),
            rejection_reason=raison if vers is StagingState.REJECTED else "")

    def rejeter(self, raison: str) -> "StagedObservation":
        return self.avancer(StagingState.REJECTED, raison)

    @property
    def is_accepted(self) -> bool:
        return self.state is StagingState.ACCEPTED

    def as_dict(self) -> dict:
        return {
            "batch_id": self.batch_id,
            "state": self.state.value,
            "rejection_reason": self.rejection_reason,
            "canonical_participants": (list(self.canonical_participants)
                                       if self.canonical_participants else None),
            "history": [list(h) for h in self.history],
            "evidence": self.evidence.as_dict(),
        }


def _utcnow() -> datetime:
    from datetime import timezone
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class BatchResult:
    """Le compte-rendu d'un passage dans le sas. Les compteurs se CONSERVENT :
    `discovered` doit égaler la somme des sorties, sinon des observations se sont
    perdues en route et le rapport ment sans le savoir."""

    batch_id: str
    sport: str
    discovered: int = 0
    fetched: int = 0
    normalized: int = 0
    identity_verified: int = 0
    duplicates: int = 0
    conflicts: int = 0
    accepted: int = 0
    rejected: dict[str, int] = field(default_factory=dict)

    @property
    def total_rejected(self) -> int:
        return sum(self.rejected.values())

    @property
    def conservation_ok(self) -> bool:
        """`discovered == accepted + rejeté + doublons + conflits`."""
        return self.discovered == (
            self.accepted + self.total_rejected + self.duplicates + self.conflicts)

    def as_dict(self) -> dict:
        return {
            "batch_id": self.batch_id, "sport": self.sport,
            "discovered": self.discovered, "fetched": self.fetched,
            "normalized": self.normalized, "identity_verified": self.identity_verified,
            "duplicates": self.duplicates, "conflicts": self.conflicts,
            "accepted": self.accepted, "rejected": dict(self.rejected),
            "total_rejected": self.total_rejected,
            "conservation_ok": self.conservation_ok,
        }


_DEFAULT_STORE = (
    pathlib.Path(__file__).resolve().parents[4]
    / "var" / "historical_discovery" / "staging.jsonl"
)


class JsonlStagingStore:
    """Append-only, `var/` repo-local, jamais `~/.axon` — même frontière que les
    autres stores du moteur. Le rejet s'écrit comme l'acceptation : c'est ce qui
    rend l'exclusion auditable plutôt que déductible d'une absence."""

    def __init__(self, path: pathlib.Path | None = None):
        self.path = pathlib.Path(path) if path is not None else _DEFAULT_STORE
        if str(self.path).startswith("~") or "~/.axon" in str(self.path):
            raise ValueError("staging : chemin ~/.axon interdit")

    def append(self, observation: StagedObservation) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(observation.as_dict(), sort_keys=True,
                               ensure_ascii=False) + "\n")

    def append_batch(self, observations) -> int:
        n = 0
        for o in observations:
            self.append(o)
            n += 1
        return n

    def iter_all(self) -> Iterator[dict]:
        if not self.path.exists():
            return
        with open(self.path, encoding="utf-8") as f:
            for ligne in f:
                if ligne.strip():
                    yield json.loads(ligne)

    def par_etat(self, state: StagingState) -> list[dict]:
        return [o for o in self.iter_all() if o["state"] == state.value]
