"""Normalizer API-Sports → faits canoniques football.

Déplacé depuis normalizers/api_sports.py (v1). Déplacement pur : logique
inchangée, seuls les imports pointent vers sports/football/canonical_facts.
"""

from __future__ import annotations
from datetime import datetime

from src.agents.quant.gateway.core.provider_protocol import RawProviderResponse
from src.agents.quant.gateway.core.identity_resolver import IdentityResolver
from src.agents.quant.gateway.normalizers.canonical_models import CanonicalPayload
from src.agents.quant.gateway.sports.football.canonical_facts import (
    CanonicalMatch,
    CanonicalStandingRow,
)

# API-Sports utilise des codes courts (FT, NS, PST...) — on normalise vers le
# vocabulaire commun aux providers (celui de football-data.org : FINISHED,
# SCHEDULED, POSTPONED, CANCELLED...), sinon un filtre comme recent_form()
# écrirait un `if provider == ...` caché derrière une comparaison de statut.
_STATUS_MAP = {
    "FT": "FINISHED", "AET": "FINISHED", "PEN": "FINISHED",
    "NS": "SCHEDULED", "TBD": "SCHEDULED",
    "PST": "POSTPONED", "CANC": "CANCELLED", "ABD": "CANCELLED",
}


def _canonical_status(short_code: str) -> str:
    return _STATUS_MAP.get(short_code, short_code)


def _buts_reglementaires(fixture: dict) -> tuple[int | None, int | None]:
    """Le score des 90 MINUTES, jamais le score final.

    `goals` porte le score APRÈS prolongation : une rencontre finie 0-0 puis
    gagnée 1-0 en prolongation y figure « 1-0 ». Un marché 1X2 se règle au temps
    réglementaire, et `score.fulltime` le donne exactement.

    MESURÉ sur la Ligue des Champions : 22 rencontres où les deux diffèrent, dont
    10 où l'ISSUE 1X2 change — le modèle apprenait une victoire pour un nul. Le
    repli sur `goals` couvre les payloads sans bloc `score` (produits non
    football, réponses partielles), où il reste la seule valeur disponible.

    Propre au FOOTBALL : au hockey ou au basket, la prolongation fait partie du
    résultat qui règle le marché, et retrancher les points de prolongation y
    serait la même erreur en sens inverse.
    """
    plein = ((fixture.get("score") or {}).get("fulltime") or {})
    if plein.get("home") is not None and plein.get("away") is not None:
        return plein["home"], plein["away"]
    buts = fixture.get("goals") or {}
    return buts.get("home"), buts.get("away")


def _max_published(values: list[str | None]) -> datetime | None:
    """published_time du batch = mise à jour la plus récente parmi les items."""
    times = [datetime.fromisoformat(v.replace("Z", "+00:00")) for v in values if v]
    return max(times) if times else None


class ApiSportsNormalizer:
    def normalize_fixtures(
        self, raw: RawProviderResponse, resolver: IdentityResolver, league_id: str, season: str
    ) -> CanonicalPayload:
        matches = []
        for fixture in raw.payload.get("fixtures", []):
            home_id, home_status = resolver.canonicalize("api_sports", str(fixture["teams"]["home"]["id"]), "team")
            away_id, away_status = resolver.canonicalize("api_sports", str(fixture["teams"]["away"]["id"]), "team")
            if home_status != "RESOLVED" or away_status != "RESOLVED":
                continue  # jamais de rattachement par proximité de nom — on écarte l'entrée
            buts_dom, buts_ext = _buts_reglementaires(fixture)
            matches.append(CanonicalMatch(
                canonical_match_id=f"api_sports:{fixture['fixture']['id']}",
                league_id=league_id,
                season=season,
                home_team_id=home_id,
                away_team_id=away_id,
                kickoff=datetime.fromisoformat(fixture["fixture"]["date"]),
                status=_canonical_status(fixture["fixture"]["status"]["short"]),
                goals_home=buts_dom,
                goals_away=buts_ext,
            ))
        # api_sports ne fournit PAS de "lastUpdated" sur les fixtures → published_time
        # None (fraîcheur dégradée, honnête). event_time None : batch, kickoff au
        # niveau fait. (C'est football-data.org qui horodate les matchs, symétrie inverse.)
        return CanonicalPayload(kind="fixtures", matches=matches, published_time=None)

    def normalize_standings(
        self, raw: RawProviderResponse, resolver: IdentityResolver, league_id: str
    ) -> CanonicalPayload:
        data = raw.payload.get("standings", [])
        if not data:
            return CanonicalPayload(kind="standings", standings=[])

        table = data[0]["league"]["standings"][0]
        rows = []
        for row in table:
            team_id, status = resolver.canonicalize("api_sports", str(row["team"]["id"]), "team")
            if status != "RESOLVED":
                continue
            rows.append(CanonicalStandingRow(
                team_id=team_id, rank=row["rank"], played=row["all"]["played"], points=row["points"],
            ))
        # api_sports fournit `update` par ligne de classement → published_time réel
        # (mise à jour la plus récente). C'est la symétrie inverse de football-data.org.
        published = _max_published([row.get("update") for row in table])
        return CanonicalPayload(kind="standings", standings=rows, published_time=published)
