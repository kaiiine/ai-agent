"""Registre déclaratif des providers — ajouter un provider = l'enregistrer ici,
pas modifier fallback_chain.py.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Any

from src.agents.quant.gateway.providers.football_data_org_provider import FootballDataOrgProvider
from src.agents.quant.gateway.providers.api_sports_provider import ApiSportsProvider

# Un provider est une SOURCE de données cross-sport (pas un module sportif) :
# l'importer ici ne viole pas GW-FR-001. Les NORMALIZERS, eux, sont
# sport-spécifiques et vivent dans les SportModule — fallback_chain les obtient
# via get_sport_module(sport).normalizers(), plus jamais depuis ce registre
# (dette C1#1 éliminée à C5 : aucun import core -> sports/<sport>/).


@dataclass(frozen=True)
class ProviderEntry:
    provider: Any        # SportsDataProvider
    doc_url: str


REGISTRY: dict[str, ProviderEntry] = {
    "football_data_org": ProviderEntry(
        provider=FootballDataOrgProvider(),
        doc_url="https://www.football-data.org/documentation/quickstart",
    ),
    "api_sports": ProviderEntry(
        provider=ApiSportsProvider(),
        doc_url="https://www.api-football.com/documentation-v3",
    ),
}

# Ordre de priorité par sport. football-data.org d'abord : c'est le seul des
# deux à couvrir la saison en cours gratuitement.
#
# TheSportsDB (3e fallback prévu au PRD) a été testé en direct et volontairement
# exclu : la clé publique gratuite ("3") plafonne toutes les listes à 5 résultats
# (5/380 matchs de saison, 5/20 lignes de classement) — un fallback fonctionnel
# produirait un classement/une forme silencieusement tronqués. À reconsidérer
# uniquement si un tier payant lève cette limite.
FALLBACK_ORDER: dict[str, list[str]] = {
    "football": ["football_data_org", "api_sports"],
}
