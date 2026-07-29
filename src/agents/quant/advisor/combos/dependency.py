"""Classification de dépendance d'une paire de legs COMPATIBLE (Lot 9, PRD §14).

Ordre de priorité contractuel, unique et déterministe :
  INCOMPATIBLE > STRUCTURALLY_DEPENDENT > STATISTICALLY_DEPENDENT > UNKNOWN
  > INDEPENDENT_ENOUGH.

Stratégie STRUCTURELLE V1 (aucun registre sportif, aucune interprétation de
chaînes libres). `INDEPENDENT_ENOUGH` = « aucun mécanisme de dépendance connu
identifié à partir des infos structurelles » — un proxy prudent, JAMAIS une
preuve d'indépendance. Dépendances non détectées (contexte de compétition
partagé, enjeux croisés, météo/calendrier, facteurs externes) = limites connues
V1, couvertes partiellement par la marge de sécurité du pricing."""

from __future__ import annotations

from ..domain.candidates import CandidateBet
from ..domain.enums import DependencyStatus


def classify(a: CandidateBet, b: CandidateBet) -> DependencyStatus:
    """Symétrique : classify(A, B) == classify(B, A)."""
    if a.event_id == b.event_id:
        # Même marché + sélections différentes = mutuellement exclusives (fait
        # STRUCTUREL, sans interprétation de libellés).
        if a.market_id == b.market_id and a.selection != b.selection:
            return DependencyStatus.INCOMPATIBLE
        # Même événement, autre marché : dépendance structurelle (pas de règle
        # jointe explicite en V1).
        return DependencyStatus.STRUCTURALLY_DEPENDENT

    # Événements distincts.
    shared = set(a.participant_ids) & set(b.participant_ids)
    if shared:
        return DependencyStatus.STATISTICALLY_DEPENDENT      # pas d'estimation jointe en V1
    if not a.participant_ids or not b.participant_ids:
        return DependencyStatus.UNKNOWN                       # disjonction non vérifiable -> refus V1
    return DependencyStatus.INDEPENDENT_ENOUGH
