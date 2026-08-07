"""Fraîcheur et couverture — mesurées pour de vrai, ou déclarées non mesurables.

Le rapport de la vague précédente annonçait « FRESHNESS_UNKNOWN généralisé ». La
mesure a montré autre chose : deux causes distinctes produisaient le même
symptôme, et une troisième affirmation du rapport était simplement fausse.

  1. `gateway.data_freshness` codait `sport="football"` en dur. Pour une
     compétition de baseball, elle allait chercher des données de football,
     obtenait NoDataAvailableError et rendait `None` — la fraîcheur devenait
     « inconnue » pour un motif faux.

  2. Un `degraded=True` était traité comme une absence de mesure. Or il dit que
     la BASE est plus faible (`fetched_at` au lieu de `published_time`), pas que
     la mesure manque. Les confondre transformait une fraîcheur mesurée à 0,0001
     — donc une donnée manifestement périmée — en « inconnue », c'est-à-dire en
     un doute plus favorable que la mesure elle-même.

Ces tests portent sur le CONTRAT, pas sur un sport : c'est ce qui les rend
valides pour les schémas 2-way comme 3-way.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.agents.quant.betting_engine.live_evaluation import (
    LiveEvaluationStatus as S,
)

#: MÊME instant que le harnais live réutilisé plus bas : une date locale
#: décalerait toutes les fraîcheurs relatives sans que le test ne le dise.
from tests.test_live_evaluation import _DECISION  # noqa: E402


# ══ §2 — Le sport vient de l'identifiant, jamais d'un défaut ═════════════════
@pytest.mark.parametrize("competition,sport", [
    ("competition:football:fra:ligue1", "football"),
    ("competition:baseball:usa:mlb", "baseball"),
    ("competition:tennis:atp:tour", "tennis"),
    ("competition:hockey:usa:nhl", "hockey"),
])
def test_le_sport_est_lu_sur_l_identifiant_de_competition(competition, sport):
    from src.agents.quant.gateway.gateway import _sport_of

    assert _sport_of(competition) == sport


@pytest.mark.parametrize("identifiant", ["", "bidon", "team:football:psg", "competition"])
def test_un_identifiant_non_canonique_ne_donne_aucun_sport(identifiant):
    """On ne devine pas un sport : un identifiant hors forme rend `None`, et la
    fraîcheur sera honnêtement non mesurable."""
    from src.agents.quant.gateway.gateway import _sport_of

    assert _sport_of(identifiant) is None


def test_un_sport_non_couvert_par_la_gateway_rend_none_sans_lever():
    """Les six sports non-football n'ont aucun module Gateway. Le dire par `None`
    est correct ; aller chercher des données de FOOTBALL pour eux ne l'était
    pas."""
    from src.agents.quant.gateway import gateway

    assert gateway.data_freshness("competition:baseball:usa:mlb", "2026") is None


# ══ §3 — degraded ≠ non mesurable ════════════════════════════════════════════
def _resultat(freshness):
    """Le harnais live existant, avec la fraîcheur qu'on veut éprouver. On
    réutilise sa Gateway complète : construire la nôtre reviendrait à réimplémenter
    `recent_form` et `standings_strength` pour tester la fraîcheur."""
    from tests.test_live_evaluation import _FreshGateway, _run

    return _run(_FreshGateway(freshness))


def _mesure(score, effective, *, degraded):
    from src.agents.quant.gateway.gateway import DataFreshness

    return DataFreshness(
        freshness_score=score, effective_time=effective,
        basis="fetched_at" if degraded else "published_time",
        degraded=degraded, stale=False)


def test_une_mesure_degradee_est_propagee_et_signalee():
    """Le cœur du correctif : la base est faible, la mesure existe. On propage le
    score ET on signale la dégradation — l'un sans l'autre ment dans un sens ou
    dans l'autre."""
    from src.agents.quant.betting_engine.live_evaluation import _FRESHNESS_DEGRADED

    res = _resultat(_mesure(0.42, _DECISION - timedelta(hours=1), degraded=True))

    assert res.status is S.EVALUATED
    assert res.freshness_score == 0.42
    assert _FRESHNESS_DEGRADED in res.warnings


def test_une_mesure_fiable_est_propagee_sans_avertissement():
    from src.agents.quant.betting_engine.live_evaluation import _FRESHNESS_DEGRADED

    res = _resultat(_mesure(0.95, _DECISION - timedelta(minutes=5), degraded=False))

    assert res.freshness_score == 0.95
    assert _FRESHNESS_DEGRADED not in res.warnings


def test_une_absence_de_donnee_reste_non_mesurable():
    """`None` veut dire qu'aucun horodatage n'est exploitable. Le contrat interdit
    d'en faire un zéro comme d'en faire une fraîcheur."""
    assert _resultat(None).freshness_score is None


def test_un_horodatage_absent_reste_non_mesurable():
    assert _resultat(_mesure(0.9, None, degraded=False)).freshness_score is None


def test_une_donnee_trop_ancienne_est_refusee_meme_avec_base_degradee():
    """Une base faible ne dispense pas du contrôle d'ancienneté — c'est même le
    cas où il sert le plus."""
    res = _resultat(_mesure(0.0001, _DECISION - timedelta(days=30), degraded=True))

    assert res.status is S.DATA_TOO_STALE


# ══ §1-4 — `dataset_recency` ne se confond jamais avec la freshness live ═════
def _recency(dates, as_of):
    from src.agents.quant.betting_engine.dataset_recency import measure

    return measure(dates, source="corpus", as_of=as_of)


def test_un_corpus_ancien_avec_une_cote_fraiche_donne_deux_verdicts_opposes():
    """Le cas qui justifie la séparation. Les fondre ferait qu'un corpus arrêté
    en 2023 rendrait « périmée » une cote observée il y a cinq minutes."""
    from src.agents.quant.betting_engine.dataset_recency import MEASURABLE

    res = _resultat(_mesure(0.95, _DECISION - timedelta(minutes=5), degraded=False))
    corpus = _recency([_DECISION - timedelta(days=900)], _DECISION)

    assert res.freshness_score == 0.95                     # la donnée live est fraîche
    assert corpus.status == MEASURABLE and corpus.age_days == 900   # le corpus, non


def test_un_corpus_recent_sans_donnee_live_laisse_la_freshness_inconnue():
    """L'inverse : un corpus à jour ne rend pas fraîche une donnée live absente.
    `freshness_score = None` reste la seule réponse honnête."""
    from src.agents.quant.betting_engine.dataset_recency import MEASURABLE

    res = _resultat(None)
    corpus = _recency([_DECISION - timedelta(days=2)], _DECISION)

    assert res.freshness_score is None
    assert corpus.status == MEASURABLE and corpus.age_days == 2


def test_un_corpus_ancien_ne_declenche_jamais_data_too_stale():
    """Tant qu'aucune politique de récence de corpus n'existe, l'ancienneté du
    dataset ne rejette rien. Ce test tombera le jour où quelqu'un branchera la
    récence sur le gate de staleness — c'est exactement son rôle."""
    res = _resultat(_mesure(0.95, _DECISION - timedelta(minutes=5), degraded=False))

    assert res.status is S.EVALUATED


def test_la_recence_de_corpus_n_alimente_jamais_le_candidat():
    """Preuve structurelle : ni l'adaptateur ni le générateur de candidats ne
    connaissent `dataset_recency`. Le lien ne peut donc pas exister par accident."""
    import inspect

    from src.agents.quant.advisor.candidate_generation import generator
    from src.agents.quant.advisor.input_adapter import betting_engine_adapter

    for module in (betting_engine_adapter, generator):
        assert "dataset_recency" not in inspect.getsource(module)


def test_un_corpus_vide_est_non_mesurable_jamais_zero_jour():
    """« Zéro jour d'ancienneté » se lirait comme parfaitement à jour — l'exact
    contraire de ce qu'une absence de données signifie."""
    from src.agents.quant.betting_engine.dataset_recency import NOT_MEASURABLE

    vide = _recency([], _DECISION)

    assert vide.status == NOT_MEASURABLE
    assert vide.age_days is None and vide.last_observation_at is None


def test_chaque_modele_enregistre_expose_sa_recence():
    """Un modèle sans récence mesurable rendrait le diagnostic muet là où il doit
    précisément distinguer « code incomplet » de « données à accumuler »."""
    from src.agents.quant.betting_engine.dataset_recency import MEASURABLE, for_model
    from src.agents.quant.betting_engine.readiness_cli import _ASSESSORS

    muets = [cle for cle in _ASSESSORS if for_model(cle).status != MEASURABLE]

    assert not muets, f"récence de corpus non mesurable : {muets}"


def test_readiness_affiche_les_deux_grandeurs_separement():
    from src.agents.quant.betting_engine.dataset_recency import for_model
    from src.agents.quant.betting_engine.readiness_cli import _ASSESSORS, render

    lignes = "\n".join(render(_ASSESSORS["nhl"](), for_model("nhl")))

    assert "freshness live :" in lignes
    assert "dataset :" in lignes


# ══ §16 — Aucun seuil de maturité modifié ════════════════════════════════════
def test_aucun_seuil_de_maturite_n_a_bouge():
    """La mission corrige des MESURES, jamais des barres. Un seuil déplacé ferait
    passer un modèle sans qu'aucune donnée n'ait changé."""
    from src.agents.quant.betting_engine.maturity import load_maturity_policy

    p = load_maturity_policy()

    assert p.criteria["min_data_coverage"] == 0.9
    assert p.criteria["min_data_quality"] == 0.8
    assert p.criteria["min_sample_size"] == 500
    assert p.criteria["min_temporal_folds"] == 3
    assert p.criteria["max_calibration_error"] == 0.05
    assert p.criteria["min_clv_events"] == 30


def test_les_criteres_requis_restent_les_memes():
    from src.agents.quant.betting_engine.maturity import load_maturity_policy

    requis = {k for k, v in load_maturity_policy().required_for_support.items() if v}

    assert requis == {
        "max_calibration_error", "measurable_live_freshness", "min_data_coverage",
        "min_data_quality", "min_sample_size", "min_temporal_folds",
        "must_beat_baselines", "positive_clv",
    }


def test_la_maturite_reste_derivee_mecaniquement():
    """Aucun modèle ne devient SUPPORTED par cette wave : les statuts sont dérivés
    des critères, et les critères de données restent ceux qu'on mesure."""
    from src.agents.quant.betting_engine.readiness_cli import _ASSESSORS

    statuts = {cle: _ASSESSORS[cle]().decision.status
               for cle in ("nhl", "atp", "fl1")}

    assert set(statuts.values()) == {"EXPERIMENTAL"}


# ══ La capacité de fraîcheur est MESURÉE, jamais déclarée ═══════════════════
def test_la_capacite_de_fraicheur_suit_la_chaine_de_providers():
    """`measurable_live_freshness` est un critère REQUIS vers SUPPORTED.

    Il était ÉCRIT en littéral dans chaque évaluateur : `FRESHNESS_MEASURABLE`
    pour douze modèles, `FRESHNESS_NOT_MEASURABLE` pour deux. Sondé,
    `gateway.data_freshness()` rendait `None` pour le basket, le baseball, le
    football américain, le hockey et le volley — la Gateway n'a de chaîne de
    providers que pour le football. Cinq modèles déclaraient donc PASS sur un
    critère que leur chemin de décision ne peut pas honorer, et n'attendaient
    plus que la CLV pour être dits SUPPORTED — c'est-à-dire misables.
    """
    from src.agents.quant.betting_engine.live_coverage import live_freshness_capability
    from src.agents.quant.betting_engine.maturity import (
        FRESHNESS_MEASURABLE,
        FRESHNESS_NOT_MEASURABLE,
    )
    from src.agents.quant.gateway.core.provider_registry import FALLBACK_ORDER

    for competition, sport in [
        ("competition:football:fra:ligue1", "football"),
        ("competition:basketball:usa:nba", "basketball"),
        ("competition:baseball:usa:mlb", "baseball"),
        ("competition:american_football:usa:nfl", "american_football"),
        ("competition:hockey:usa:nhl", "hockey"),
        ("competition:volleyball:ita:serie_a1", "volleyball"),
        ("competition:tennis:atp:tour", "tennis"),
    ]:
        attendu = (FRESHNESS_MEASURABLE if sport in FALLBACK_ORDER
                   else FRESHNESS_NOT_MEASURABLE)
        assert live_freshness_capability(competition) == attendu, sport


def test_aucun_evaluateur_ne_code_en_dur_sa_capacite_de_fraicheur():
    """Un critère de maturité qui tient à une constante n'est pas un critère.

    Écrire `FRESHNESS_MEASURABLE` dans un évaluateur revient à s'auto-délivrer le
    PASS : le rapport de readiness affiche alors « freshness live exposée » sans
    que rien ne l'ait vérifié.
    """
    import ast
    import pathlib

    racine = pathlib.Path(__file__).resolve().parent.parent / "src" / "agents" / "quant"
    coupables = []
    for fichier in sorted(racine.rglob("*.py")):
        if fichier.name in ("maturity.py", "live_coverage.py"):
            continue                      # la définition et la mesure elles-mêmes
        for noeud in ast.walk(ast.parse(fichier.read_text())):
            if not isinstance(noeud, ast.keyword) or noeud.arg != "live_freshness_status":
                continue
            if isinstance(noeud.value, ast.Name) and noeud.value.id.startswith("FRESHNESS_"):
                coupables.append(f"{fichier.relative_to(racine)}:{noeud.value.lineno}")
            elif isinstance(noeud.value, ast.Constant):
                coupables.append(f"{fichier.relative_to(racine)}:{noeud.value.lineno}")

    assert not coupables, ("capacité de fraîcheur codée en dur :\n" + "\n".join(coupables))


def test_les_modeles_sans_provider_portent_le_bloqueur_de_fraicheur():
    """Bout en bout : le verdict de maturité expose le manque, il ne l'absorbe pas."""
    from src.agents.quant.betting_engine.maturity import Verdict
    from src.agents.quant.betting_engine.sports.baseball.moneyline import assess_mlb

    decision = assess_mlb().decision
    critere = next(c for c in decision.criteria if c.name == "measurable_live_freshness")

    assert critere.required
    assert critere.verdict is not Verdict.PASS
    assert decision.status == "EXPERIMENTAL"
