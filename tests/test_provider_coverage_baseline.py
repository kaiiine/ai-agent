"""Baseline de couverture provider : périmètre reconnu, et invariance money.

Sept des huit compétitions domestiques avaient une identité complète et AUCUNE
entrée de couverture. Elles renvoyaient donc PROVIDER_COVERAGE_MISSING quelle que
soit la saison — un diagnostic faux, qui désignait le provider alors que le
provider répondait. Étendre la baseline change ce que le moteur DIT, jamais ce
qu'il DÉCIDE : ces tests verrouillent les deux moitiés de cette phrase.
"""

from __future__ import annotations

import pytest

from src.agents.quant.gateway.registries.competition_registry import active_competitions
from src.agents.quant.gateway.registries.provider_coverage_registry import (
    CoverageStatus,
    known_coverage,
    record_coverage,
    usable_providers,
)

SAISON = "2026"
DATA_TYPES = ("FIXTURES", "RESULTS", "STANDINGS")


@pytest.fixture
def db(tmp_path):
    """Base ISOLÉE : un test qui écrit dans ~/.axon/sports_provider_coverage.db
    modifierait la couverture réelle de l'utilisateur, donc son comportement en
    production, depuis une suite de tests."""
    path = tmp_path / "coverage.db"
    for entry in known_coverage():
        record_coverage(entry, path)
    return path


# ── périmètre reconnu ───────────────────────────────────────────────────────────
@pytest.mark.parametrize("competition", [c.canonical_id for c in active_competitions("football")])
@pytest.mark.parametrize("data_type", DATA_TYPES)
def test_toute_competition_active_a_une_couverture_verifiee(db, competition, data_type):
    """Une compétition déclarée active mais sans couverture est une promesse que le
    moteur ne peut pas tenir : elle apparaît au catalogue et refuse tout."""
    assert usable_providers(competition, SAISON, data_type, db), (
        f"{competition} / {data_type} / {SAISON} : aucun provider utilisable")


def test_la_couverture_ne_declare_que_ce_qui_a_ete_appele(db):
    """`live_call` engage : chaque entrée FULL correspond à un endpoint réellement
    interrogé. Une entrée posée « au jugé » se comporte comme une donnée fiable."""
    for entry in known_coverage():
        if entry.status is CoverageStatus.FULL:
            assert entry.verification_method in ("live_call", "fixture_checksum"), (
                f"{entry.competition_id}/{entry.data_type} déclarée FULL "
                f"par « {entry.verification_method} »")


def test_aucune_competition_uefa_n_est_declaree_couverte(db):
    """La saison courante des compétitions UEFA est refusée par le tier gratuit.
    La déclarer couverte ferait échouer l'évaluation plus loin, avec un diagnostic
    pointant le mauvais maillon."""
    for uefa in ("competition:football:eur:champions_league",
                 "competition:football:eur:europa_league",
                 "competition:football:eur:conference_league"):
        assert not usable_providers(uefa, SAISON, "RESULTS", db)


# ── invariance des décisions money ──────────────────────────────────────────────
def test_aucun_statut_de_refus_ne_produit_de_decision():
    """LE test qui compte. La couverture ne fait que déplacer un événement d'une
    cause de refus vers une autre : les deux restent des refus. Aucun chemin
    n'existe d'un statut non-EVALUATED vers un BET."""
    from src.agents.quant.betting_engine.live_evaluation import LiveEvaluationStatus
    from src.agents.quant.structured_decision import EVALUATED, _LIVE_STATUS_MAP

    for live_status, bridge_status in _LIVE_STATUS_MAP.items():
        assert live_status is not LiveEvaluationStatus.EVALUATED
        assert bridge_status != EVALUATED, (
            f"{live_status} produit {bridge_status} : un refus deviendrait évaluable")


def test_le_registre_de_couverture_ne_touche_a_aucun_calcul():
    """La couverture est un PRÉ-CHECK d'orchestration. Si un module de calcul
    l'importait, une entrée de registre pourrait déplacer une probabilité."""
    import inspect

    from src.agents.quant.betting_engine.sports.football.market_models import one_x_two
    from src.agents.quant.gateway.sports.football import derived

    for module in (one_x_two, derived):
        source = inspect.getsource(module)
        assert "provider_coverage_registry" not in source
        assert "usable_providers" not in source


def test_la_couverture_precede_les_features_dans_l_evaluation():
    """L'ordre est un invariant de coût ET de diagnostic : sonder la couverture
    après avoir construit les features attribuerait au modèle une panne de
    provider."""
    import inspect

    from src.agents.quant.betting_engine import live_evaluation

    source = inspect.getsource(live_evaluation.evaluate_live_event)
    assert source.index("coverage_check") < source.index("build_feature_set")


# ── ce que la couverture ne prétend PAS ─────────────────────────────────────────
def test_full_decrit_la_source_pas_la_richesse_du_contenu(db):
    """FULL dit « le provider répond », jamais « les données sont exploitables ».
    Au 5 août les saisons 2026-27 n'ont pas commencé : RESULTS est servi et vide.
    Confondre les deux ferait promettre au moteur ce qu'il ne peut pas tenir."""
    entries = [e for e in known_coverage()
               if e.season == SAISON and e.data_type == "RESULTS"
               and e.status is CoverageStatus.FULL
               and e.provider == "football_data_org"]
    assert entries, "aucune couverture RESULTS 2026 déclarée"
    # Les huit domestiques de 2026-27 étaient encore à zéro rencontre le 5 août :
    # leur note DOIT porter la mention. Les compétitions ouvertes le 13 août
    # avaient, elles, des rencontres réellement terminées — leur imposer la même
    # mention ferait écrire une réserve fausse.
    for entry in entries:
        assert entry.notes, f"{entry.competition_id} : FULL sans note de vérification"
        assert "vide" in entry.notes or "terminées" in entry.notes, (
            f"{entry.competition_id} : FULL sans dire si le contenu est exploitable")
