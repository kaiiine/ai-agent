"""Normalizer api-sports → faits canoniques, pour les sports à deux équipes.

Basket, baseball, football américain, hockey et volley décrivent la même chose :
deux équipes, un score, un instant, un statut. Un normalizer par sport aurait été
cinq copies du même parcours, donc cinq endroits où corriger le même oubli — et
l'histoire de ce provider montre que les oublis y sont coûteux : `Final/OT` avec
`short=None` avait écarté treize rencontres sans rien signaler.

Une seule classe, paramétrée par l'espace d'identités du produit. C'est le seul
point où les sports diffèrent vraiment : api-sports numérote ses équipes
séparément par produit, si bien que l'équipe 132 du basket n'a rien à voir avec
l'équipe 132 du hockey. Les confondre rattacherait des rencontres à la mauvaise
franchise en silence.
"""

from __future__ import annotations

from datetime import datetime

from src.agents.quant.gateway.core.identity_resolver import IdentityResolver
from src.agents.quant.gateway.core.provider_protocol import RawProviderResponse
from src.agents.quant.gateway.normalizers.canonical_models import CanonicalPayload
from src.agents.quant.gateway.providers import api_sports_shape as forme
from src.agents.quant.gateway.sports.football.canonical_facts import CanonicalMatch

#: Espace d'identités api-sports par sport. Ces noms viennent du référentiel
#: existant (`SPORT_MODULES[...].known_entities()`) : les changer ici rendrait
#: toutes les rencontres non résolues.
NAMESPACES: dict[str, str] = {
    "basketball": "api_basketball",
    "baseball": "api_baseball",
    "american_football": "api_american_football",
    "hockey": "api_hockey",
    "volleyball": "api_volleyball",
}


class ApiSportsPairwiseNormalizer:
    """Traduit un lot de rencontres brutes en `CanonicalMatch`.

    `CanonicalMatch` porte des noms venus du football (`goals_home`) alors qu'il
    s'agit ici de points ou de sets. Le champ décrit un SCORE ; le renommer
    traverserait le point-in-time store, ses snapshots déjà écrits et leur
    version de schéma, pour un gain de vocabulaire. La structure, elle, est
    exactement la bonne.
    """

    def __init__(self, sport: str) -> None:
        self.sport = sport
        self.namespace = NAMESPACES[sport]

    def normalize_fixtures(
        self, raw: RawProviderResponse, resolver: IdentityResolver,
        league_id: str, season: str,
    ) -> CanonicalPayload:
        matches = []
        for jeu in raw.payload.get("fixtures", []):
            domicile, exterieur = forme.equipes(jeu)
            if not domicile.get("id") or not exterieur.get("id"):
                continue
            home_id, home_statut = resolver.canonicalize(
                self.namespace, str(domicile["id"]), "team")
            away_id, away_statut = resolver.canonicalize(
                self.namespace, str(exterieur["id"]), "team")
            # Jamais de rattachement par proximité de nom : une équipe non
            # résolue est écartée, pas devinée.
            if home_statut != "RESOLVED" or away_statut != "RESOLVED":
                continue
            quand = forme.instant(jeu)
            if not quand:
                continue
            sd, se = forme.scores(jeu)
            termine = forme.statut(jeu) in forme.TERMINES
            matches.append(CanonicalMatch(
                canonical_match_id=f"api_sports:{self.sport}:{forme.identifiant(jeu)}",
                league_id=league_id,
                season=season,
                home_team_id=home_id,
                away_team_id=away_id,
                kickoff=datetime.fromisoformat(quand),
                status="FINISHED" if termine else "SCHEDULED",
                goals_home=sd if termine else None,
                goals_away=se if termine else None,
            ))
        # api-sports n'horodate pas la mise à jour d'un lot de rencontres :
        # `published_time` reste None, donc fraîcheur DÉGRADÉE et signalée. C'est
        # la même honnêteté que pour le football chez ce provider.
        return CanonicalPayload(kind="fixtures", matches=matches, published_time=None)

    def normalize_standings(
        self, raw: RawProviderResponse, resolver: IdentityResolver, league_id: str,
    ) -> CanonicalPayload:
        """Non sondé hors football : rien plutôt qu'une structure supposée.

        `capabilities(sport).standings` vaut False pour ces sports, donc la
        chaîne de fallback ne choisit jamais ce provider pour un STANDINGS. Cette
        méthode existe pour honorer le protocole, pas pour être appelée.
        """
        return CanonicalPayload(kind="standings", standings=[])
