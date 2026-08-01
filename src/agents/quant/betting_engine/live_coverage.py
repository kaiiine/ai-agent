"""Couverture d'ÉVALUATION du chemin live produit (Unité A).

Un sport à modèle VALIDÉ embarque son propre dataset historique (provenance api-sports
vérifiée + fingerprint) : c'est la couverture pour l'évaluation POINT-IN-TIME, même quand
aucun provider LIVE n'expose la saison courante (le registre de couverture provider vit
dans ~/.axon et n'est vérifié que jusqu'à 2025). Sans cela, le gate `usable_providers`
bloque TOUT événement de la saison courante en `COMPETITION_NOT_COVERED`, y compris pour
une compétition dont le modèle est réellement disponible.

Invariants : (1) la couverture provider RÉELLE prime toujours (on ne la remplace jamais,
on complète seulement quand elle est absente) ; (2) seule une compétition CANONIQUE d'un
sport à modèle validé obtient la couverture « embarquée » — donc seulement après un mapping
compétition VÉRIFIÉ (un tournoi non mappé n'a pas de competition_id et n'arrive pas ici) ;
(3) atteindre le modèle ne crée AUCUN risque money : il reste EXPERIMENTAL -> ABSTAIN, et
la fraîcheur/qualité captent la staleness d'un dataset embarqué plus ancien que le match.
"""

from __future__ import annotations

from src.agents.quant.gateway.registries.provider_coverage_registry import usable_providers

from .sports.model_registry import VALIDATED_MODELS

EMBEDDED_DATASET = "embedded_dataset"


def _sport_of(competition_id: str | None) -> str | None:
    parts = (competition_id or "").split(":")
    return parts[1] if len(parts) >= 2 and parts[0] == "competition" else None


def evaluation_coverage_check(competition_id: str, season: str, data_type: str) -> list[str]:
    """Providers utilisables pour ÉVALUER cette compétition. Provider live réel d'abord ;
    à défaut, dataset embarqué du modèle validé (couverture point-in-time)."""
    providers = list(usable_providers(competition_id, season, data_type))
    if providers:
        return providers
    if _sport_of(competition_id) in VALIDATED_MODELS:
        return [EMBEDDED_DATASET]
    return []
