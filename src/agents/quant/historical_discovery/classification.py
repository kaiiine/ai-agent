"""Classer une source AVANT de s'en servir — et le verdict n'est jamais un avis.

Une source découverte se présente toujours bien : elle contient les données
cherchées, elle répond, elle a l'air structurée. Ce sont des propriétés
INDÉPENDANTES, et une seule qui manque suffit à rendre le reste inutilisable.
Une archive parfaite dont la licence est muette ne peut pas alimenter un dataset ;
un dataset libre dont on ne sait pas rattacher les équipes non plus.

D'OÙ SIX AXES, PAS UN SCORE. Un score moyennerait « licence inconnue » avec
« très bien structuré » et produirait un chiffre honorable pour une source
inexploitable. Ici `USABLE` est une CONJONCTION : tout doit passer, et ce qui
bloque est nommé.

MESURÉ, PAS SUPPOSÉ. Chaque axe porte la preuve qui l'a établi (`evidence`) :
code HTTP relevé, fichier de licence lu, identifiant croisé. Une classification
sans preuve reste `UNKNOWN`, et `UNKNOWN` ne vaut jamais « oui ».
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

# ── Les douze étiquettes du contrat (§5) ────────────────────────────────────
REACHABLE = "REACHABLE"
AUTH_REQUIRED = "AUTH_REQUIRED"
PAID_REQUIRED = "PAID_REQUIRED"
LICENSE_OK = "LICENSE_OK"
LICENSE_UNCLEAR = "LICENSE_UNCLEAR"
PROVENANCE_VERIFIED = "PROVENANCE_VERIFIED"
STRUCTURED = "STRUCTURED"
UNSTRUCTURED = "UNSTRUCTURED"
IDENTITY_COMPATIBLE = "IDENTITY_COMPATIBLE"
POINT_IN_TIME_CAPABLE = "POINT_IN_TIME_CAPABLE"
USABLE = "USABLE"
NOT_USABLE = "NOT_USABLE"


class Axe(str, Enum):
    """Un axe non mesuré vaut UNKNOWN — jamais une valeur favorable."""

    OUI = "OUI"
    NON = "NON"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class AxeMesure:
    valeur: Axe
    evidence: str = ""

    @property
    def acquis(self) -> bool:
        return self.valeur is Axe.OUI


INCONNU = AxeMesure(Axe.UNKNOWN)


@dataclass(frozen=True)
class SourceClassification:
    """Ce qu'on sait vraiment d'une source, axe par axe.

    `access` distingue trois situations que « accessible » confondrait : ouvert,
    derrière une clé qu'on possède peut-être, derrière un paiement. La troisième
    est un STOP (§20) — jamais un achat automatique.
    """

    source: str
    reachable: AxeMesure = INCONNU
    licence: AxeMesure = INCONNU          # OUI = licence lue ET compatible
    licence_id: str = ""                  # SPDX ou citation exacte
    provenance: AxeMesure = INCONNU
    structured: AxeMesure = INCONNU
    identity_compatible: AxeMesure = INCONNU
    point_in_time_capable: AxeMesure = INCONNU
    auth_required: bool = False
    paid_required: bool = False
    notes: str = ""
    #: Axes exigés pour `USABLE`. Modifiable par sport, jamais pour faire passer
    #: une source : c'est le contrat, pas un réglage.
    requis: tuple[str, ...] = ("reachable", "licence", "provenance",
                               "structured", "identity_compatible",
                               "point_in_time_capable")

    # ── Verdict ─────────────────────────────────────────────────────────────
    @property
    def blockers(self) -> tuple[str, ...]:
        """Ce qui empêche l'usage, nommé. Vide = utilisable."""
        manquants = []
        if self.paid_required:
            manquants.append(PAID_REQUIRED)
        for axe in self.requis:
            mesure: AxeMesure = getattr(self, axe)
            if not mesure.acquis:
                manquants.append(_ETIQUETTE_MANQUE[axe](mesure))
        return tuple(manquants)

    @property
    def is_usable(self) -> bool:
        return not self.blockers

    @property
    def verdict(self) -> str:
        return USABLE if self.is_usable else NOT_USABLE

    @property
    def labels(self) -> tuple[str, ...]:
        """Les étiquettes §5 réellement acquises — pour lecture humaine."""
        out = []
        if self.reachable.acquis:
            out.append(REACHABLE)
        if self.auth_required:
            out.append(AUTH_REQUIRED)
        if self.paid_required:
            out.append(PAID_REQUIRED)
        out.append(LICENSE_OK if self.licence.acquis else LICENSE_UNCLEAR)
        if self.provenance.acquis:
            out.append(PROVENANCE_VERIFIED)
        out.append(STRUCTURED if self.structured.acquis else UNSTRUCTURED)
        if self.identity_compatible.acquis:
            out.append(IDENTITY_COMPATIBLE)
        if self.point_in_time_capable.acquis:
            out.append(POINT_IN_TIME_CAPABLE)
        out.append(self.verdict)
        return tuple(out)

    def as_dict(self) -> dict:
        return {
            "source": self.source,
            "licence_id": self.licence_id,
            "labels": list(self.labels),
            "verdict": self.verdict,
            "blockers": list(self.blockers),
            "auth_required": self.auth_required,
            "paid_required": self.paid_required,
            "evidence": {axe: getattr(self, axe).evidence for axe in self.requis},
            "notes": self.notes,
        }


#: Comment nommer un axe qui n'est pas acquis. `NON` et `UNKNOWN` ne sont pas la
#: même panne : l'un est un refus mesuré, l'autre une mesure jamais faite.
_ETIQUETTE_MANQUE = {
    "reachable": lambda m: "NOT_REACHABLE" if m.valeur is Axe.NON else "REACHABILITY_UNKNOWN",
    "licence": lambda m: "LICENSE_INCOMPATIBLE" if m.valeur is Axe.NON else LICENSE_UNCLEAR,
    "provenance": lambda m: "PROVENANCE_UNVERIFIED",
    "structured": lambda m: UNSTRUCTURED,
    "identity_compatible": lambda m: "IDENTITY_INCOMPATIBLE" if m.valeur is Axe.NON
                                     else "IDENTITY_UNVERIFIED",
    "point_in_time_capable": lambda m: "TEMPORAL_LEAKAGE_RISK" if m.valeur is Axe.NON
                                       else "POINT_IN_TIME_UNVERIFIED",
}
