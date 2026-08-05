"""Chaque sport résout dans SON espace de noms (§8 : aucun chemin spécial caché).

`_default_deps()` construisait l'`IdentityResolver` sur le référentiel FOOTBALL quel
que soit le sport demandé. Les six autres sports étaient enregistrés dans
`SPORT_MODULES`, donc réputés atteignables — et échouaient tous en
IDENTITY_UNRESOLVED avant même d'atteindre leur modèle. Une façade générique
au-dessus d'un chemin football-spécifique : le pire des deux, parce que le registre
donnait l'apparence de la généricité.
"""

from __future__ import annotations

import pytest

from src.agents.quant.betting_engine.sports.registry import SPORT_MODULES
from src.agents.quant.betting_engine.sports.tennis.identity import _strip_accents

SPORTS = sorted(SPORT_MODULES)


def test_les_sept_sports_sont_enregistres():
    assert set(SPORTS) == {
        "american_football", "baseball", "basketball", "football",
        "hockey", "tennis", "volleyball",
    }


@pytest.mark.parametrize("sport", SPORTS)
def test_chaque_sport_expose_ses_entites(sport):
    """Un sport sans entités ne peut rien résoudre : il est enregistré et inerte."""
    assert SPORT_MODULES[sport].known_entities(), f"{sport} n'expose aucune entité"


@pytest.mark.parametrize("sport", SPORTS)
def test_les_identifiants_canoniques_portent_leur_sport(sport):
    """`team:basketball:…` / `player:tennis:…` : le sport est DANS l'identifiant.
    C'est ce qui rend un croisement inter-sports impossible plutôt qu'improbable."""
    for entity in SPORT_MODULES[sport].known_entities():
        parts = entity.canonical_id.split(":")
        assert len(parts) >= 3, f"identifiant non typé : {entity.canonical_id}"
        assert parts[0] in ("team", "player"), entity.canonical_id
        assert parts[1] == sport, (
            f"{sport} contient une entité d'un autre sport : {entity.canonical_id}")


def test_aucun_identifiant_canonique_n_est_partage_entre_deux_sports():
    """Le croisement silencieux est le risque money : un nom résolu dans le mauvais
    espace ferait tourner le modèle d'un sport sur l'événement d'un autre.

    L'unicité exigée est INTER-sports. À l'intérieur d'un sport, plusieurs entrées
    peuvent légitimement porter le même identifiant : ce sont des orthographes
    sources d'une même personne, et les réunir est le but de la canonicalisation."""
    proprietaire: dict[str, str] = {}
    for sport in SPORTS:
        for entity in SPORT_MODULES[sport].known_entities():
            autre = proprietaire.setdefault(entity.canonical_id, sport)
            assert autre == sport, (
                f"{entity.canonical_id} partagé entre {autre} et {sport}")


def test_les_variantes_orthographiques_convergent_sur_une_seule_identite():
    """`Del Potro J. M.` et `Del Potro J.M.` sont un seul joueur : les laisser
    diverger donnerait deux Elo à la même personne, chacun sur la moitié de ses
    matchs. La convergence est voulue, ce test la rend explicite."""
    entites = SPORT_MODULES["tennis"].known_entities()
    par_id: dict[str, set[str]] = {}
    for e in entites:
        par_id.setdefault(e.canonical_id, set()).add(e.canonical_name)

    fusionnes = {k: v for k, v in par_id.items() if len(v) > 1}
    assert fusionnes, "aucune variante fusionnée : la canonicalisation ne fait rien"
    for canonical_id, noms in fusionnes.items():
        radicaux = {"".join(c for c in _strip_accents(n).lower() if c.isalnum())
                    for n in noms}
        assert len(radicaux) == 1, (
            f"{canonical_id} réunit des noms qui ne sont pas de simples variantes : {noms}")


@pytest.mark.parametrize("sport", SPORTS)
def test_la_resolution_par_defaut_est_celle_du_sport_demande(sport, monkeypatch):
    """LE test de la régression : `_default_deps(sport)` ne doit jamais retomber sur
    le référentiel football. On vérifie sans I/O réelle, en neutralisant le connecteur."""
    import src.agents.quant.structured_decision as sd

    class _FauxConnecteur:
        def scan_catalog(self, sport="football"):
            return []

    monkeypatch.setattr(
        "src.agents.quant.betting_engine.bookmakers.winamax.connector.WinamaxConnector",
        _FauxConnecteur)

    deps = sd._default_deps(sport)
    attendues = {e.canonical_id for e in SPORT_MODULES[sport].known_entities()}

    trouve = None
    for entity in SPORT_MODULES[sport].known_entities():
        hit = deps["team_search"](entity.canonical_name)
        if hit:
            trouve = hit
            break

    assert trouve is not None, f"aucune entité de {sport} résolue par ses propres deps"
    assert trouve["canonical_id"] in attendues


def test_un_nom_de_football_ne_resout_pas_en_tennis(monkeypatch):
    """Le cas concret : « Lyon » est un club de football. Interrogé dans l'espace
    tennis, il ne doit rien renvoyer — surtout pas un joueur au nom proche."""
    import src.agents.quant.structured_decision as sd

    class _FauxConnecteur:
        def scan_catalog(self, sport="football"):
            return []

    monkeypatch.setattr(
        "src.agents.quant.betting_engine.bookmakers.winamax.connector.WinamaxConnector",
        _FauxConnecteur)

    assert sd._default_deps("tennis")["team_search"]("Lyon") is None
    assert sd._default_deps("football")["team_search"]("Lyon") is not None
