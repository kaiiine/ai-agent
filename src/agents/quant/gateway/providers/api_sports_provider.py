"""Provider API-Sports — les SIX produits derrière une seule clé.

`supported_sports` valait `["football"]`. Sondée, la même clé répond HTTP 200 sur
les six produits api-sports, chacun avec son quota propre : la limite était dans
le code, pas dans le credential. Le module d'acquisition historique l'avait déjà
constaté et corrigé de son côté ; la Gateway, elle, était restée football-only.
La même limitation vivait donc à deux endroits et n'avait été levée qu'à un seul.

Ce que la sonde établit VRAIMENT (relevé du 2026-08-07, une requête par
sport-saison, comptes réels) :

    basketball  ligue 12  2024-2025 -> 1387 rencontres     2025-2026 -> refus plan
    baseball    ligue 1   2024      -> 2946                2025      -> refus plan
    am. football ligue 1  2024      ->  335                2025      -> refus plan
    hockey      ligue 57  2024      -> 1503                2025      -> refus plan
    volleyball  ligue 89  2024      ->  213                2025      -> refus plan

Le plan gratuit sert 2022-2024 et REFUSE explicitement au-delà
(« Free plans do not have access to this season »). C'est la même borne que pour
le football — d'où l'existence de football-data.org comme source de la saison en
cours. Aucun autre provider ne joue ce rôle pour les cinq autres sports : le
chemin est branché et vérifiable, la saison courante reste hors du plan.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from src.agents.quant.gateway.core.provider_protocol import (
    ProviderCapabilities,
    RawProviderResponse,
)
from src.agents.quant.stats_aggregator import _api_get

#: Saisons servies par le plan gratuit, tous produits confondus. Mesuré, pas lu
#: dans une documentation : au-delà, la réponse est HTTP 200 avec zéro rencontre
#: et un message de plan — un refus qui ressemble à une absence de données.
FREE_TIER_SEASONS = {"2022", "2023", "2024"}


@dataclass(frozen=True)
class _Produit:
    """Ce qui distingue réellement les six produits api-sports."""

    hote: str
    endpoint: str = "games"
    #: Le basket numérote ses saisons `2023-2024` ; les autres `2023`.
    saison_composee: bool = False
    #: Le classement n'est vérifié qu'en football : ne pas l'annoncer ailleurs.
    standings: bool = False


PRODUITS: dict[str, _Produit] = {
    "football": _Produit("https://v3.football.api-sports.io", endpoint="fixtures",
                         standings=True),
    "basketball": _Produit("https://v1.basketball.api-sports.io", saison_composee=True),
    "baseball": _Produit("https://v1.baseball.api-sports.io"),
    "american_football": _Produit("https://v1.american-football.api-sports.io"),
    "hockey": _Produit("https://v1.hockey.api-sports.io"),
    "volleyball": _Produit("https://v1.volleyball.api-sports.io"),
}


def annee_de_saison(season: str) -> str:
    """« 2024-2025 » -> « 2024 ». L'année de DÉBUT identifie la saison partout."""
    return str(season).split("-")[0]


def saison_provider(sport: str, season: str) -> str:
    """Saison au format attendu par le produit.

    Le basket refuse `2024` et veut `2024-2025`. Sans cette conversion, une
    demande parfaitement légitime revient vide — et une réponse vide se lit comme
    « pas de données » alors que c'est la question qui était mal posée.
    """
    produit = PRODUITS.get(sport)
    debut = annee_de_saison(season)
    if produit is None or not produit.saison_composee:
        return debut
    return f"{debut}-{int(debut) + 1}"


class ApiSportsProvider:
    name = "api_sports"
    supported_sports = sorted(PRODUITS)
    query_cost = 0.0  # gratuit sur le tier actuel

    def capabilities(self, sport: str) -> ProviderCapabilities:
        produit = PRODUITS.get(sport)
        if produit is None:
            return ProviderCapabilities()
        # `standings` n'est annoncé que là où il a été vérifié. Déclarer une
        # capacité non sondée ferait choisir ce provider pour un appel qu'il ne
        # sait peut-être pas servir.
        return ProviderCapabilities(
            fixtures=True, standings=produit.standings,
            recent_form=True, historical=True)

    def is_available(self, sport: str, season: str) -> bool:
        return sport in PRODUITS and annee_de_saison(season) in FREE_TIER_SEASONS

    def fetch_league_fixtures(
        self, sport: str, provider_league_id: str, season: str,
        date_from: str | None = None, date_to: str | None = None,
    ) -> RawProviderResponse:
        produit = PRODUITS[sport]
        params: dict = {"league": provider_league_id,
                        "season": saison_provider(sport, season)}
        if date_from:
            params["from"] = date_from
        if date_to:
            params["to"] = date_to
        data = _api_get(produit.endpoint, params, base_url=produit.hote)
        # La clé du payload reste `fixtures` quel que soit le sport : c'est le
        # vocabulaire de la Gateway, pas celui du provider.
        return RawProviderResponse(
            payload={"fixtures": data},
            provider=self.name,
            fetched_at=datetime.now(timezone.utc),
            request_metadata={"endpoint": produit.endpoint, "params": params,
                              "host": produit.hote, "sport": sport},
        )

    def fetch_standings(self, sport: str, provider_league_id: str, season: str) -> RawProviderResponse:
        produit = PRODUITS[sport]
        params = {"league": provider_league_id,
                  "season": saison_provider(sport, season)}
        data = _api_get("standings", params, base_url=produit.hote)
        return RawProviderResponse(
            payload={"standings": data},
            provider=self.name,
            fetched_at=datetime.now(timezone.utc),
            request_metadata={"endpoint": "standings", "params": params,
                              "host": produit.hote, "sport": sport},
        )

    def get_rate_limit_status(self) -> dict:
        # Chaque produit a son quota propre ; la clé les partage sans les cumuler.
        return {"limit_per_day": 100, "known_remaining": None, "per_product": True}
