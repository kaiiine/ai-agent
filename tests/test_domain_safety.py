"""Le modèle a-t-il des données sur la population ACTUELLE ?

Le cas réel qui a motivé ce garde-fou : `Frosinone - Juventus`, servi par le
catalogue live avec des espérances allant jusqu'à +95 %. L'audit a montré que
l'edge n'était pas une opportunité mais une extrapolation — Frosinone n'a AUCUNE
rencontre observée depuis 810 jours, le corpus Serie A ayant cessé de la décrire
après sa relégation.

Ce qui est vérifié ici est une propriété des DONNÉES, jamais la taille de l'EV :
une grosse espérance peut être réelle, et une espérance médiocre sur une équipe
hors domaine reste tout aussi indéfendable.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.agents.quant.betting_engine.markets.domain import (
    CHAMP_AGE,
    CYCLE_SAISON_JOURS,
    DomainStatus,
    verifier_domaine,
)
from src.agents.quant.betting_engine.markets.families import MarketFamily
from src.agents.quant.betting_engine.markets.pricing import PricingStatus
from src.agents.quant.betting_engine.sports.football.market_models.derived import (
    FootballDerivedPricer,
)

#: Âges RÉELLEMENT mesurés sur six rencontres de Serie A du catalogue live.
AGES_MESURES = {"atalanta": 84, "sassuolo": 82, "bologna": 83, "lazio": 83,
                "genoa": 82, "napoli": 82, "parma": 82, "cagliari": 82,
                "inter": 83, "monza": 447, "juventus": 82, "frosinone": 810}


class _P:
    def __init__(self, role, cid):
        self.role, self.canonical_id = role, cid


class _Event:
    event_id = "event:football:domaine"

    def __init__(self, dom="team:h", ext="team:a"):
        self.participants = (_P("home", dom), _P("away", ext))


class _Features:
    def __init__(self, ages: dict, attaque=1.1, defense=0.95):
        self.participant_features = {
            cid: {"attack_strength": attaque, "defense_strength": defense,
                  **({CHAMP_AGE: age} if age is not None else {})}
            for cid, age in ages.items()}
        self.missing_features = set()
        self.as_of = datetime(2026, 8, 1, tzinfo=timezone.utc)


def _contexte(features):
    return {"features": features,
            "point_in_time": datetime(2026, 8, 2, tzinfo=timezone.utc)}


# ── La mesure sépare, sans cas limite ────────────────────────────────────────

def test_les_equipes_de_la_saison_courante_sont_dans_le_domaine():
    for a, b in (("atalanta", "sassuolo"), ("genoa", "napoli"), ("parma", "cagliari")):
        check = verifier_domaine(_Event(a, b), _Features({a: AGES_MESURES[a],
                                                          b: AGES_MESURES[b]}))
        assert check.status is DomainStatus.IN_DOMAIN, (a, b)
        assert check.usable


@pytest.mark.parametrize("equipe,age", [("frosinone", 810), ("monza", 447)])
def test_une_equipe_reléguee_sort_du_domaine(equipe, age):
    """Les deux seules valeurs aberrantes de la mesure sont les deux équipes
    reléguées. Leur identité n'a pas changé — leur appartenance, si."""
    check = verifier_domaine(_Event(equipe, "juventus"),
                             _Features({equipe: age, "juventus": 82}))
    assert check.status is DomainStatus.INSUFFICIENT_CURRENT_DOMAIN_HISTORY
    assert check.hors_domaine == (equipe,)
    assert str(age) in check.reason
    assert not check.usable


def test_la_coupure_ne_traverse_aucun_cas_reel():
    """Entre 84 jours et 447 jours, la population mesurée ne contient RIEN. La
    valeur exacte du cycle n'est donc pas discriminante — c'est l'ordre de
    grandeur qui l'est, et c'est ce qui rend la borne défendable."""
    dedans = [a for a in AGES_MESURES.values() if a <= CYCLE_SAISON_JOURS]
    dehors = [a for a in AGES_MESURES.values() if a > CYCLE_SAISON_JOURS]
    assert max(dedans) == 84 and min(dehors) == 447
    assert min(dehors) > 4 * max(dedans)


def test_un_age_non_mesurable_ne_vaut_pas_un_feu_vert():
    """Troisième état : ne pas savoir n'est pas la même chose que constater."""
    check = verifier_domaine(_Event(), _Features({"team:h": None, "team:a": None}))
    assert check.status is DomainStatus.NOT_MEASURABLE
    assert not check.usable


# ── Le garde-fou ne regarde pas l'espérance ──────────────────────────────────

def test_le_garde_ne_lit_jamais_l_esperance():
    """Une grosse EV peut être réelle. Le rejet vient de la donnée, jamais du
    chiffre.

    Le contrôle porte sur le CODE, pas sur la prose : on inspecte les noms
    réellement manipulés par le module (AST), sinon la docstring qui explique
    « ce garde ne lit pas l'EV » ferait échouer le test qui le vérifie.
    """
    import ast
    import inspect

    from src.agents.quant.betting_engine.markets import domain

    arbre = ast.parse(inspect.getsource(domain))
    noms = {n.id for n in ast.walk(arbre) if isinstance(n, ast.Name)}
    noms |= {n.attr for n in ast.walk(arbre) if isinstance(n, ast.Attribute)}
    noms |= {n.arg for n in ast.walk(arbre) if isinstance(n, ast.arg)}
    for interdit in ("expected_value", "edge", "odds", "ev", "bookmaker_odds",
                     "fair_probability", "probability_low"):
        assert interdit not in noms, interdit


def test_le_pricer_refuse_avec_un_statut_propre():
    """`MODEL_DOMAIN_MISMATCH` : le modèle couvre la famille et la portée, mais
    pas la population. Distinct de `DATA_NOT_AVAILABLE` — ici les données
    existent, elles sont périmées pour la question posée."""
    prix = FootballDerivedPricer().price(
        event=_Event("team:frosinone", "team:juventus"),
        family=MarketFamily.TOTALS, parameters={"line": 2.5, "source_family_id": 2749},
        context=_contexte(_Features({"team:frosinone": 810, "team:juventus": 82})))
    assert prix.status is PricingStatus.MODEL_DOMAIN_MISMATCH
    assert "810" in prix.abstention_reasons[0]
    assert not prix.selections


def test_une_rencontre_du_domaine_reste_pricee():
    """Aucune autre rencontre ne doit être écartée : le garde ne se déclenche que
    sur la preuve."""
    prix = FootballDerivedPricer().price(
        event=_Event("team:genoa", "team:napoli"),
        family=MarketFamily.TOTALS, parameters={"line": 2.5, "source_family_id": 2749},
        context=_contexte(_Features({"team:genoa": 82, "team:napoli": 82})))
    assert prix.status is PricingStatus.PRICED
    assert prix.selections


@pytest.mark.parametrize("famille,params", [
    (MarketFamily.MATCH_WINNER, {}),
    (MarketFamily.DOUBLE_CHANCE, {"source_family_id": 3072}),
    (MarketFamily.DRAW_NO_BET, {"source_family_id": 3535}),
    (MarketFamily.TOTALS, {"line": 1.5, "source_family_id": 2749}),
])
def test_le_refus_vaut_pour_toutes_les_familles_du_meme_evenement(famille, params):
    """Le domaine est une propriété de l'ÉVÉNEMENT : si le modèle ne connaît pas
    la population, aucune de ses lectures ne vaut mieux qu'une autre."""
    prix = FootballDerivedPricer().price(
        event=_Event("team:frosinone", "team:juventus"), family=famille,
        parameters=params,
        context=_contexte(_Features({"team:frosinone": 810, "team:juventus": 82})))
    assert prix.status is PricingStatus.MODEL_DOMAIN_MISMATCH
