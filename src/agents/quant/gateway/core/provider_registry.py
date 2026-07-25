"""Registre déclaratif des providers — ajouter un provider = l'enregistrer ici,
pas modifier fallback_chain.py.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Any

from src.agents.quant.gateway.providers.football_data_org_provider import FootballDataOrgProvider
from src.agents.quant.gateway.providers.api_sports_provider import ApiSportsProvider
# Normalizers déplacés sous sports/football/ (C1). Ce couplage core -> sport est
# transitoire : à C5, fallback_chain obtiendra les normalizers via get_sport_module,
# et provider_registry n'en portera plus.
from src.agents.quant.gateway.sports.football.normalizers.football_data_org import FootballDataOrgNormalizer
from src.agents.quant.gateway.sports.football.normalizers.api_sports import ApiSportsNormalizer


@dataclass(frozen=True)
class ProviderEntry:
    provider: Any        # SportsDataProvider
    normalizer: Any       # ProviderNormalizer
    doc_url: str


REGISTRY: dict[str, ProviderEntry] = {
    "football_data_org": ProviderEntry(
        provider=FootballDataOrgProvider(),
        normalizer=FootballDataOrgNormalizer(),
        doc_url="https://www.football-data.org/documentation/quickstart",
    ),
    "api_sports": ProviderEntry(
        provider=ApiSportsProvider(),
        normalizer=ApiSportsNormalizer(),
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
