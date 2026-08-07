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


def live_freshness_capability(competition_id: str) -> str:
    """La fraîcheur live est-elle MESURABLE pour cette compétition ?

    Ce statut était ÉCRIT dans chaque évaluateur de maturité — `FRESHNESS_MEASURABLE`
    en littéral pour douze modèles, `FRESHNESS_NOT_MEASURABLE` pour deux. Un critère
    REQUIS vers SUPPORTED tenait donc à une constante, pas à une mesure.

    Sondé, l'écart était réel : `gateway.data_freshness()` rend `None` pour le
    basket, le baseball, le football américain, le hockey et le volley — la
    Gateway n'a de chaîne de providers que pour le football. Cinq modèles
    déclaraient PASS sur un critère que leur chemin de décision ne peut pas
    honorer, et n'attendaient plus que la CLV pour être dits SUPPORTED.

    La capacité se lit maintenant là où elle existe : la COUVERTURE RÉELLE d'un
    provider pour cette compétition, à la SAISON EN COURS. C'est bien la saison
    en cours qui compte — la fraîcheur se mesure au point de décision, c'est-à-dire
    aujourd'hui. Un provider qui ne sert que des saisons passées alimente
    l'entraînement, jamais l'horodatage d'une décision.

    Deux versions trop permissives ont précédé celle-ci, et chacune aurait
    recréé le faux PASS qu'elle prétendait corriger :

    - lire la présence du sport dans `FALLBACK_ORDER` : brancher les cinq
      produits api-sports y aurait fait entrer cinq sports dont le plan gratuit
      refuse justement la saison en cours ;
    - lire la couverture au registre : le dataset tennis embarqué y figure en
      FULL pour la saison en cours, et il est bien réel — mais il n'est pas un
      provider de la Gateway, et la chaîne ne peut donc rien horodater avec lui.

    La question exacte est : la chaîne de fallback saurait-elle SERVIR cette
    donnée aujourd'hui ? Elle est posée à la chaîne elle-même, qui porte déjà sa
    règle d'éligibilité — plutôt que réécrite ici, où elle divergerait.

    Lecture LOCALE et déterministe — le rapport de readiness ne doit dépendre
    d'aucun appel réseau.
    """
    from src.agents.quant.betting_engine.maturity import (
        FRESHNESS_MEASURABLE,
        FRESHNESS_NOT_MEASURABLE,
    )
    from src.agents.quant.gateway.core.fallback_chain import capable_providers
    from src.agents.quant.gateway.gateway import current_season

    sport = _sport_of(competition_id)
    if sport is None:
        return FRESHNESS_NOT_MEASURABLE
    servants = capable_providers(sport, competition_id, current_season(), "RESULTS")
    return FRESHNESS_MEASURABLE if servants else FRESHNESS_NOT_MEASURABLE
