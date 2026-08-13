"""Acquisition football-data.org — la saison COURANTE, gratuitement.

api-sports expose tout l'historique mais son plan Free s'arrête à 2024
(« Free plans do not have access to this season, try from 2022 »). Pour la saison
en cours, football-data.org est la seule source gratuite disponible ici — sondé
le 2026-08-13 : 13 compétitions, dont trois NON onboardées et immédiatement
accessibles :

    BSA  Campeonato Brasileiro Série A   1 355 rencontres terminées (2023-2026)
    CL   UEFA Champions League             503 rencontres terminées (2023-2025)
    CLI  Copa Libertadores                 591 rencontres terminées (2023-2026)

Ce module ne fait que CONVERTIR. Il ne décide ni de la maturité d'un modèle, ni
de ce qui est misable : ce sont deux étages plus haut.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime

_BASE = "https://api.football-data.org/v4"

#: Code football-data.org -> identité canonique AXON. Le sens de la lecture
#: compte : le canonique est la vérité, le code provider n'en est qu'une clé.
COMPETITIONS = {
    "BSA": "competition:football:bra:serie_a",
    "CL": "competition:football:eur:champions_league",
    "CLI": "competition:football:sam:libertadores",
}


@dataclass(frozen=True)
class ResultatBrut:
    """Ce que le provider a rendu, avant toute canonisation."""

    provider_match_id: str
    competition_code: str
    season: str
    home_provider_id: str
    home_name: str
    away_provider_id: str
    away_name: str
    kickoff: datetime
    status: str
    goals_home: int | None
    goals_away: int | None


def _slug(nom: str) -> str:
    import re
    import unicodedata

    sans_accent = "".join(
        c for c in unicodedata.normalize("NFD", nom)
        if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", "_", sans_accent.lower()).strip("_")


def identite_equipe(scope: str, nom: str) -> str:
    """`team:football:{scope}:{slug}` — stable tant que le nom du club l'est.

    `scope` est le PAYS DU CLUB, jamais la région de la compétition. Dérivé de la
    compétition, Flamengo devenait `team:football:bra:cr_flamengo` en Série A et
    `team:football:sam:cr_flamengo` en Libertadores : deux identités pour un seul
    club, donc un historique coupé en deux et une appartenance multi-compétitions
    impossible à représenter. Un club ne change pas d'identité en changeant de
    compétition — c'est toute la raison d'être du référentiel saisonnier.

    Le slug part du NOM et pas de l'identifiant provider : une identité canonique
    ne doit pas dépendre du fournisseur qui l'a fait connaître, sinon changer de
    source créerait un doublon d'équipe.
    """
    return f"team:football:{scope}:{_slug(nom)}"


def scope_du_club(nom: str, pays_par_club: dict[str, str], *, defaut: str = "unk") -> str:
    """Code pays du club, en minuscules. `unk` quand la source ne le dit pas —
    un scope inventé fusionnerait deux clubs homonymes de pays différents."""
    code = (pays_par_club or {}).get(nom) or ""
    return code.lower() if code else defaut


def parse_matches(payload: list[dict], competition_code: str) -> list[ResultatBrut]:
    """Convertit la réponse `/matches` sans rien inventer."""
    bruts: list[ResultatBrut] = []
    for m in payload:
        domicile, exterieur = m.get("homeTeam") or {}, m.get("awayTeam") or {}
        score = ((m.get("score") or {}).get("fullTime") or {})
        if not domicile.get("name") or not exterieur.get("name"):
            continue                      # un match sans les deux camps n'est pas exploitable
        bruts.append(ResultatBrut(
            provider_match_id=str(m.get("id", "")),
            competition_code=competition_code,
            season=str((m.get("season") or {}).get("startDate", ""))[:4],
            home_provider_id=str(domicile.get("id", "")),
            home_name=domicile["name"],
            away_provider_id=str(exterieur.get("id", "")),
            away_name=exterieur["name"],
            kickoff=datetime.fromisoformat(m["utcDate"].replace("Z", "+00:00")),
            status=m.get("status", ""),
            goals_home=score.get("home"),
            goals_away=score.get("away"),
        ))
    return bruts


def vers_canonique(bruts, *, scope: str = "unk", pays_par_club: dict[str, str] | None = None):
    """`ResultatBrut` -> `CanonicalMatch`, en écartant ce qui n'a pas de score.

    Un match sans score n'est pas un résultat : le garder avec des buts à `None`
    ferait entrer un `0-0` fantôme dans le premier calcul qui somme des buts.

    `pays_par_club` donne le scope RÉEL de chaque club (endpoint `/teams`). Sans
    lui, `scope` s'applique à tous — acceptable pour une ligue nationale, faux
    pour une compétition inter-ligues où les clubs viennent de partout.
    """
    from src.agents.quant.gateway.sports.football.canonical_facts import CanonicalMatch

    canoniques = []
    for b in bruts:
        if b.status != "FINISHED" or b.goals_home is None or b.goals_away is None:
            continue
        canoniques.append(CanonicalMatch(
            canonical_match_id=f"fdo:{b.competition_code}:{b.provider_match_id}",
            league_id=COMPETITIONS[b.competition_code],
            season=b.season,
            home_team_id=identite_equipe(
                scope_du_club(b.home_name, pays_par_club, defaut=scope), b.home_name),
            away_team_id=identite_equipe(
                scope_du_club(b.away_name, pays_par_club, defaut=scope), b.away_name),
            kickoff=b.kickoff,
            status="FINISHED",
            goals_home=b.goals_home,
            goals_away=b.goals_away))
    return canoniques


def fetch_matches(competition_code: str, saison: int, *, timeout: int = 60) -> list[dict]:
    """Appel réseau. Isolé pour que la conversion reste testable hors ligne."""
    import requests

    cle = os.environ.get("FOOTBALL_DATA_ORG_KEY", "")
    if not cle:
        raise RuntimeError("FOOTBALL_DATA_ORG_KEY manquant dans .env")
    reponse = requests.get(
        f"{_BASE}/competitions/{competition_code}/matches",
        headers={"X-Auth-Token": cle}, params={"season": saison}, timeout=timeout)
    reponse.raise_for_status()
    return reponse.json().get("matches", [])
