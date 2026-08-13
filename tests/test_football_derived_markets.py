"""Marchés football dérivés — cohérence probabiliste et refus démontrés.

Trois modèles indépendants qui prédisent le même match finissent par se
contredire : P(home) élevé d'un côté, P(over 2.5) incompatible de l'autre, et
rien pour le signaler. Ici tout descend d'une seule loi jointe, et ces tests
vérifient que les relations logiques entre marchés tiennent — c'est le seul
moyen de le savoir sans attendre qu'un pari le prouve.

Ils vérifient AUSSI les refus. Un refus démontré vaut mieux qu'une probabilité
inventée : ligne entière au règlement inconnu, restriction de période, masse de
probabilité sortie du domaine où la grille représente la loi.
"""

from __future__ import annotations

import pytest

from src.agents.quant.betting_engine.markets.families import MarketFamily
from src.agents.quant.betting_engine.markets.pricing import PricingStatus
from src.agents.quant.betting_engine.sports.football.market_models.derived import (
    MASSE_HORS_GRILLE_MAX,
    FootballDerivedPricer,
    btts,
    double_chance,
    draw_no_bet,
    exact_score,
    issues_1x2,
    masse_hors_grille,
    totals,
)
from src.agents.quant.dixon_coles import DEFAULT_RHO, score_matrix

TOLERANCE = 1e-9


def _matrices():
    """Des matchs de profils différents — favori net, équilibré, faible scoring."""
    profils = [
        ({"attack": 1.2, "defense": 0.9}, {"attack": 0.95, "defense": 1.1}),
        ({"attack": 1.0, "defense": 1.0}, {"attack": 1.0, "defense": 1.0}),
        ({"attack": 0.6, "defense": 1.4}, {"attack": 0.7, "defense": 1.3}),
        ({"attack": 1.8, "defense": 0.5}, {"attack": 0.5, "defense": 1.9}),
    ]
    return [score_matrix(d, e, DEFAULT_RHO) for d, e in profils]


@pytest.fixture(params=range(4))
def matrix(request):
    return _matrices()[request.param]


# ── §4 : cohérence probabiliste transversale ─────────────────────────────────

def test_le_1x2_somme_a_un(matrix):
    assert abs(sum(issues_1x2(matrix).values()) - 1.0) < TOLERANCE


def test_le_plus_moins_somme_a_un(matrix):
    for ligne in (0.5, 1.5, 2.5, 3.5, 4.5):
        t = totals(matrix, ligne)
        assert abs(t["over"] + t["under"] - 1.0) < TOLERANCE, ligne


def test_les_deux_equipes_marquent_somme_a_un(matrix):
    b = btts(matrix)
    assert abs(b["yes"] + b["no"] - 1.0) < TOLERANCE


def test_la_double_chance_est_l_union_exacte_du_1x2(matrix):
    """Relation logique, pas approximation : une union d'issues disjointes est la
    somme de leurs probabilités."""
    p, dc = issues_1x2(matrix), double_chance(matrix)
    assert abs(dc["home_or_draw"] - (p["home"] + p["draw"])) < TOLERANCE
    assert abs(dc["home_or_away"] - (p["home"] + p["away"])) < TOLERANCE
    assert abs(dc["draw_or_away"] - (p["draw"] + p["away"])) < TOLERANCE
    # Chaque issue apparaît dans exactement deux des trois unions.
    assert abs(sum(dc.values()) - 2.0) < TOLERANCE


def test_le_rembourse_si_nul_est_la_conditionnelle(matrix):
    """P(home | pas de nul) — et non P(home) renormalisé n'importe comment."""
    p, dnb = issues_1x2(matrix), draw_no_bet(matrix)
    reste = p["home"] + p["away"]
    assert abs(dnb["home"] - p["home"] / reste) < TOLERANCE
    assert abs(dnb["home"] + dnb["away"] - 1.0) < TOLERANCE
    # Le favori le reste : la conditionnelle ne renverse jamais l'ordre.
    assert (dnb["home"] > dnb["away"]) == (p["home"] > p["away"])


def test_le_score_exact_reconstitue_le_1x2(matrix):
    """La relation la plus exigeante : agréger la grille des scores doit rendre
    EXACTEMENT le 1X2. Si les deux divergent, l'un des deux ment."""
    scores = exact_score(matrix, max_buts=10)
    p = issues_1x2(matrix)
    home = sum(v for k, v in scores.items()
               if k != "other" and int(k.split(":")[0]) > int(k.split(":")[1]))
    assert abs(home - p["home"]) < 1e-9


def test_le_score_exact_somme_a_un_avec_son_issue_other(matrix):
    """La source expose « other » : la troncature de la grille affichée est une
    issue réelle, pas un résidu à jeter."""
    scores = exact_score(matrix, max_buts=5)
    assert abs(sum(scores.values()) - 1.0) < TOLERANCE
    assert scores["other"] >= 0.0
    assert len(scores) == 37                       # 6×6 + other, comme la capture


def test_les_totaux_sont_monotones(matrix):
    """P(over) décroît quand la ligne monte. Une inversion signalerait une erreur
    de comptage bien avant qu'un pari ne la révèle."""
    valeurs = [totals(matrix, l)["over"] for l in (0.5, 1.5, 2.5, 3.5, 4.5, 5.5)]
    assert all(a >= b for a, b in zip(valeurs, valeurs[1:])), valeurs


def test_btts_et_totals_restent_compatibles(matrix):
    """Les deux équipes marquent implique au moins deux buts : P(BTTS) ≤ P(over 1.5)."""
    assert btts(matrix)["yes"] <= totals(matrix, 1.5)["over"] + TOLERANCE


# ── Masse hors grille : mesurée, jamais supposée ─────────────────────────────

def test_la_masse_hors_grille_est_negligeable_a_intensite_realiste():
    assert masse_hors_grille(1.5, 1.2) < 1e-6


def test_la_masse_hors_grille_explose_aux_bornes_admises():
    """Les bornes de force (`STRENGTH_MAX=3`) autorisent des intensités où la
    grille ne représente plus la loi — et la renormalisation le cacherait."""
    assert masse_hors_grille(13.5, 10.8) > 0.5


# ── Refus démontrés ──────────────────────────────────────────────────────────

class _Participant:
    def __init__(self, role, cid):
        self.role, self.canonical_id = role, cid


class _Event:
    event_id = "event:football:test"
    participants = (_Participant("home", "team:h"), _Participant("away", "team:a"))


class _Features:
    def __init__(self, attack=1.0, defense=1.0):
        self.participant_features = {
            "team:h": {"attack_strength": attack, "defense_strength": defense},
            "team:a": {"attack_strength": attack, "defense_strength": defense}}
        self.missing_features = set()
        from datetime import datetime, timezone
        self.as_of = datetime(2026, 8, 1, tzinfo=timezone.utc)


def _contexte(features=None):
    from datetime import datetime, timezone
    return {"features": features or _Features(),
            "point_in_time": datetime(2026, 8, 2, tzinfo=timezone.utc)}


def test_une_ligne_entiere_est_refusee_avec_son_motif():
    """28 des 60 totaux football observés sont sur ligne entière. Le règlement
    d'un total exactement égal à la ligne n'est pas démontré par le payload."""
    pricer = FootballDerivedPricer()
    resultat = pricer.price(event=_Event(), family=MarketFamily.TOTALS,
                            parameters={"line": 2.0, "source_family_id": 2749}, context=_contexte())
    assert resultat.status is PricingStatus.RULE_NOT_DEMONSTRATED
    assert "remboursement" in resultat.abstention_reasons[0]
    assert not resultat.selections
    assert not pricer.supports(MarketFamily.TOTALS, {"line": 2.0, "source_family_id": 2749})


def test_une_demi_ligne_est_pricee():
    pricer = FootballDerivedPricer()
    resultat = pricer.price(event=_Event(), family=MarketFamily.TOTALS,
                            parameters={"line": 2.5, "source_family_id": 2749}, context=_contexte())
    assert resultat.status is PricingStatus.PRICED
    assert {s.selection for s in resultat.selections} == {"over", "under"}
    assert abs(resultat.masse_totale - 1.0) < 1e-9
    assert resultat.probability_origin.startswith("dixon_coles:")


def test_un_total_d_equipe_est_refuse_bien_qu_indiscernable_par_ses_parametres():
    """Le piège le plus discret de tout le chantier.

    « Nombre de buts » (betType 2749) et « Nombre de buts de Chicago Fire »
    (2680) ont la MÊME famille canonique, le MÊME template, la MÊME ligne et
    AUCUN paramètre structuré qui les distingue : le sujet n'existe que dans le
    libellé. Une acceptation fondée sur l'absence de restriction les aurait donc
    tous deux pricés avec la loi du total du match — un total d'équipe évalué
    avec la distribution des deux équipes réunies.
    """
    pricer = FootballDerivedPricer()
    equipe = {"line": 1.5, "source_family_id": 2680}     # « Nombre de buts de … »
    assert not pricer.supports(MarketFamily.TOTALS, equipe)

    resultat = pricer.price(event=_Event(), family=MarketFamily.TOTALS,
                            parameters=equipe, context=_contexte())
    assert resultat.status is PricingStatus.MODEL_CONTEXT_MISMATCH
    assert "2749" in resultat.abstention_reasons[0]
    assert not resultat.selections


def test_une_restriction_de_periode_est_refusee():
    """Un Plus/Moins de mi-temps n'est pas un Plus/Moins de match."""
    pricer = FootballDerivedPricer()
    resultat = pricer.price(event=_Event(), family=MarketFamily.TOTALS,
                            parameters={"line": 1.5, "periodnr": "1", "source_family_id": 2531}, context=_contexte())
    assert resultat.status is PricingStatus.MODEL_CONTEXT_MISMATCH
    assert "periodnr" in resultat.abstention_reasons[0]


def test_un_match_hors_domaine_est_refuse_et_non_renormalise():
    """Aux intensités extrêmes la grille tronque 90 % de la masse ; la
    renormalisation produirait des nombres d'apparence normale."""
    pricer = FootballDerivedPricer()
    resultat = pricer.price(event=_Event(), family=MarketFamily.MATCH_WINNER,
                            parameters={}, context=_contexte(_Features(3.0, 3.0)))
    assert resultat.status is PricingStatus.DATA_NOT_AVAILABLE
    assert "masse hors grille" in resultat.abstention_reasons[0]


def test_le_derive_n_herite_pas_de_la_validation_du_parent():
    """§5 : un marché dérivé porte sa PROPRE identité de modèle, donc sa propre
    maturité. Hériter de la version du 1X2 ferait hériter de sa validation."""
    from src.agents.quant.betting_engine.sports.football.market_models.one_x_two import OneXTwoModel

    assert FootballDerivedPricer.model_version != OneXTwoModel.model_version
    resultat = FootballDerivedPricer().price(
        event=_Event(), family=MarketFamily.TOTALS,
        parameters={"line": 2.5, "source_family_id": 2749}, context=_contexte())
    assert resultat.maturity == "EXPERIMENTAL"


def test_le_1x2_derive_rend_exactement_les_memes_nombres_que_le_modele_existant():
    """§1/§11 : la généralisation ne doit rien changer au marché principal."""
    from src.agents.quant.betting_engine.sports.football.market_models.one_x_two import OneXTwoModel

    features, contexte = _Features(1.2, 0.9), _contexte(_Features(1.2, 0.9))
    modele = OneXTwoModel()
    matrix = modele.distribution(_Event(), contexte["features"], contexte["point_in_time"])
    attendu = issues_1x2(matrix)

    resultat = FootballDerivedPricer().price(
        event=_Event(), family=MarketFamily.MATCH_WINNER, parameters={}, context=contexte)
    obtenu = {s.selection: s.fair_probability for s in resultat.selections}
    for issue in ("home", "draw", "away"):
        assert abs(obtenu[issue] - attendu[issue]) < 1e-12


# ── §2 : l'économie vient du moteur existant, jamais recalculée ──────────────

def test_l_economie_delegue_au_value_engine():
    """Une seule cote, pas de marché complet : pas de dévigorisation possible,
    et l'edge se calcule alors contre la probabilité implicite BRUTE — déclarée
    comme telle."""
    from src.agents.quant.betting_engine.value_engine.expected_value import ev

    resultat = FootballDerivedPricer().price(
        event=_Event(), family=MarketFamily.TOTALS,
        parameters={"line": 2.5, "source_family_id": 2749}, context=_contexte())
    over = next(s for s in resultat.selections if s.selection == "over")

    avec_cote = over.with_odds(1.90)
    assert avec_cote.expected_value == pytest.approx(ev(over.fair_probability, 1.90), abs=1e-12)
    assert abs(avec_cote.implied_probability - 1 / 1.90) < 1e-12
    assert abs(avec_cote.edge - (over.fair_probability - 1 / 1.90)) < 1e-12
    assert avec_cote.vig_adjusted_probability is None      # absence DÉCLARÉE
    # Sans cote, aucune économie n'est inventée.
    assert over.expected_value is None and over.edge is None


# ── §7 : la marge se retire sur le MARCHÉ, jamais sur une sélection ───────────

def test_la_marge_est_retiree_sur_l_ensemble_coherent_du_marche():
    """1/cote n'est pas une probabilité bookmaker : elle contient la marge. La
    comparer à une probabilité de modèle fabrique un edge négatif artificiel de
    l'ordre de la marge — soit l'ordre de grandeur de l'edge recherché."""
    resultat = FootballDerivedPricer().price(
        event=_Event(), family=MarketFamily.TOTALS,
        parameters={"line": 2.5, "source_family_id": 2749}, context=_contexte())

    avec = resultat.with_market_odds({"over": 1.90, "under": 1.90})
    over = next(s for s in avec.selections if s.selection == "over")

    assert over.market_overround == pytest.approx(2 / 1.90, abs=1e-6)    # ≈ 1,0526
    assert over.vig_adjusted_probability == pytest.approx(0.5, abs=1e-9)
    assert over.implied_probability > over.vig_adjusted_probability      # la marge
    assert over.edge == pytest.approx(over.fair_probability - 0.5, abs=1e-9)


def test_un_marche_incomplet_ne_pretend_pas_connaitre_la_marge():
    """Une seule issue cotée ne donne aucune information sur la marge : l'absence
    est déclarée, jamais comblée."""
    resultat = FootballDerivedPricer().price(
        event=_Event(), family=MarketFamily.TOTALS,
        parameters={"line": 2.5, "source_family_id": 2749}, context=_contexte())

    partiel = resultat.with_market_odds({"over": 1.90})
    over = next(s for s in partiel.selections if s.selection == "over")
    assert over.vig_adjusted_probability is None
    assert over.market_overround is None


def test_la_double_chance_se_devigorise_sur_ses_trois_issues():
    """Trois issues qui se chevauchent : leur somme implicite dépasse largement 1
    (chaque résultat est couvert deux fois). La dévigorisation proportionnelle
    reste la convention du moteur, appliquée à l'ensemble cohérent du marché."""
    resultat = FootballDerivedPricer().price(
        event=_Event(), family=MarketFamily.DOUBLE_CHANCE,
        parameters={"source_family_id": 3072}, context=_contexte())
    avec = resultat.with_market_odds(
        {"home_or_draw": 1.30, "home_or_away": 1.28, "draw_or_away": 1.55})

    sans_marge = [s.vig_adjusted_probability for s in avec.selections]
    assert all(p is not None for p in sans_marge)
    # Cible 2, pas 1 : chaque résultat est couvert par exactement deux des trois
    # unions. Normaliser vers 1 aurait fabriqué un edge de −50 % par issue.
    assert avec.masse_attendue == 2.0
    assert sum(sans_marge) == pytest.approx(2.0, abs=1e-6)
    assert avec.selections[0].market_overround == pytest.approx(
        sum(1 / c for c in (1.30, 1.28, 1.55)) / 2, abs=1e-6)
    # …et la masse du modèle vise la même cible : les deux sont comparables.
    assert avec.masse_totale == pytest.approx(2.0, abs=1e-9)


# ── La ligne rejetée par la validation ────────────────────────────────────────

def test_la_ligne_0_5_rejetee_par_la_validation_ne_price_plus():
    """Rejet MESURÉ, pas prudentiel : sur 7 397 rencontres, le Brier du modèle
    (0,1208) ne bat pas la fréquence point-in-time (0,1206). La probabilité n'est
    pas absurde — elle est inutile, et une probabilité inutile présentée comme un
    edge invite à parier sans raison.

    Le statut le dit : `VALIDATION_REJECTED`, pas `MODEL_NOT_AVAILABLE`. Le
    premier veut dire « essayé, mesuré, refusé » ; le second « personne n'a
    essayé ». Les confondre perdrait l'information la plus chère du chantier.
    """
    from src.agents.quant.betting_engine.markets.capability import (
        LIGNES_TOTALS_REJETEES, resolve_model)

    assert 0.5 in LIGNES_TOTALS_REJETEES
    pricer = FootballDerivedPricer()
    params = {"line": 0.5, "source_family_id": 2749}
    assert not pricer.supports(MarketFamily.TOTALS, params)

    resultat = pricer.price(event=_Event(), family=MarketFamily.TOTALS,
                            parameters=params, context=_contexte())
    assert resultat.status is PricingStatus.VALIDATION_REJECTED
    assert "must_beat_baselines" in resultat.abstention_reasons[0]
    assert not resultat.selections

    # Et la capacité ne l'annonce plus non plus. Le registre voit « des capacités
    # TOTALS football existent, aucune n'accepte cette ligne » -> mismatch de
    # contexte ; le pricer, lui, sait POURQUOI et le dit : VALIDATION_REJECTED.
    # Les deux niveaux disent vrai, le second est le plus précis.
    capacite = resolve_model(winamax_sport_id=1, family=MarketFamily.TOTALS, context=params)
    assert capacite.status.value == "MODEL_CONTEXT_MISMATCH"


def test_le_rejet_est_par_ligne_et_non_par_famille():
    """Rejeter la famille entière pour une de ses lignes coûterait cinq marchés
    valides ; en garder une invalidée en coûterait la confiance."""
    pricer = FootballDerivedPricer()
    for ligne in (1.5, 2.5, 3.5, 4.5, 5.5):
        params = {"line": ligne, "source_family_id": 2749}
        assert pricer.supports(MarketFamily.TOTALS, params), ligne
        assert pricer.price(event=_Event(), family=MarketFamily.TOTALS,
                            parameters=params, context=_contexte()).status is PricingStatus.PRICED


# ── §3 : les familles câblées, et le refus de portée ──────────────────────────

def _obs_famille(bet_type: int, **extra):
    """Les paramètres tels que la classification les produirait."""
    return {"source_family_id": bet_type, **extra}


@pytest.mark.parametrize("famille,bet_type,issues", [
    (MarketFamily.DOUBLE_CHANCE, 3072, {"home_or_draw", "home_or_away", "draw_or_away"}),
    (MarketFamily.DRAW_NO_BET, 3535, {"home", "away"}),
])
def test_les_familles_de_la_rencontre_sont_pricees(famille, bet_type, issues):
    resultat = FootballDerivedPricer().price(
        event=_Event(), family=famille, parameters=_obs_famille(bet_type),
        context=_contexte())
    assert resultat.status is PricingStatus.PRICED
    assert {s.selection for s in resultat.selections} == issues
    assert resultat.probability_origin.startswith("dixon_coles:")


#: Le support RÉEL du marché football « Score exact » : 35 scores + `other`.
#: Mesuré sur la capture — le bookmaker n'expose pas `5:5`.
SUPPORT_SCORE_EXACT = tuple(
    f"{x}:{y}" for y in range(6) for x in range(6) if (x, y) != (5, 5)) + ("other",)


def test_le_score_exact_price_le_support_reellement_propose():
    """36 issues, pas 37 : le support vient du MARCHÉ. Une grille 6×6 supposée
    aurait pricé un `5:5` inexistant et sous-estimé `other` d'autant."""
    contexte = _contexte()
    contexte["offered_selections"] = SUPPORT_SCORE_EXACT
    resultat = FootballDerivedPricer().price(
        event=_Event(), family=MarketFamily.EXACT_SCORE,
        parameters=_obs_famille(2643), context=contexte)
    assert resultat.status is PricingStatus.PRICED
    assert len(resultat.selections) == 36
    assert {s.selection for s in resultat.selections} == set(SUPPORT_SCORE_EXACT)
    assert abs(resultat.masse_totale - 1.0) < 1e-9

    autre = next(s for s in resultat.selections if s.selection == "other")
    explicites = sum(s.fair_probability for s in resultat.selections if s.selection != "other")
    assert autre.fair_probability == pytest.approx(1.0 - explicites, abs=1e-12)


def test_le_score_exact_refuse_un_support_inconnu():
    """Sans les sélections réelles, on ne price pas : une grille supposée est une
    hypothèse sur les données."""
    resultat = FootballDerivedPricer().price(
        event=_Event(), family=MarketFamily.EXACT_SCORE,
        parameters=_obs_famille(2643), context=_contexte())
    assert resultat.status is PricingStatus.DATA_NOT_AVAILABLE
    assert "support du marché inconnu" in resultat.abstention_reasons[0]


def test_sans_issue_other_un_support_incomplet_fait_abstenir():
    """§12 : pas de renormalisation trompeuse. Un support qui ne couvre pas la
    distribution et n'offre pas `other` gonflerait chaque probabilité affichée."""
    contexte = _contexte()
    contexte["offered_selections"] = ("0:0", "1:0", "0:1", "1:1")   # ~40 % de la masse
    resultat = FootballDerivedPricer().price(
        event=_Event(), family=MarketFamily.EXACT_SCORE,
        parameters=_obs_famille(2643), context=contexte)
    assert resultat.status is PricingStatus.DATA_NOT_AVAILABLE
    assert "renormaliser" in resultat.abstention_reasons[0]


@pytest.mark.parametrize("famille,bet_type,quoi", [
    (MarketFamily.DRAW_NO_BET, 3439, "mi-temps"),
    (MarketFamily.EXACT_SCORE, 3046, "mi-temps"),
    (MarketFamily.DOUBLE_CHANCE, 3403, "mi-temps"),
    (MarketFamily.TOTALS, 2531, "mi-temps"),
])
def test_une_autre_portee_est_refusee_meme_sans_parametre_de_portee(famille, bet_type, quoi):
    """LE cas qui justifie tout le dispositif : « Mi-temps - Vainqueur (remboursé
    si match nul) » (betType 3439) ne porte AUCUN `periodnr`. Sa forme canonique
    et ses paramètres sont identiques à ceux du marché de la rencontre. Sans le
    contrôle du betType, il serait pricé avec la loi du match entier — une
    probabilité de fin de match vendue pour une mi-temps.
    """
    params = _obs_famille(bet_type)
    if famille is MarketFamily.TOTALS:
        params["line"] = 1.5
    pricer = FootballDerivedPricer()
    assert not pricer.supports(famille, params), quoi

    resultat = pricer.price(event=_Event(), family=famille,
                            parameters=params, context=_contexte())
    assert resultat.status is PricingStatus.MODEL_CONTEXT_MISMATCH
    assert str(bet_type) in resultat.abstention_reasons[0]
    assert not resultat.selections


def test_chaque_famille_et_chaque_ligne_ont_leur_propre_identite():
    """§2 : aucune maturité partagée. Deux familles qui se partageraient une
    version se promouvraient l'une l'autre — et deux lignes aussi : 1.5 et 4.5
    n'ont ni le même Brier, ni la même calibration."""
    from src.agents.quant.betting_engine.markets.capability import CAPABILITIES

    football = [c for c in CAPABILITIES if c.winamax_sport_id == 1]
    versions = [c.model_version for c in football]
    assert len(versions) == len(set(versions)), "deux capacités partagent une identité"

    totals = sorted(c.model_version for c in football if c.family is MarketFamily.TOTALS)
    assert len(totals) == 5, totals            # 5 lignes validées, 0.5 exclue
    assert all("line" in v for v in totals)
    familles = {c.family for c in football}
    assert {MarketFamily.MATCH_WINNER, MarketFamily.TOTALS, MarketFamily.DOUBLE_CHANCE,
            MarketFamily.DRAW_NO_BET, MarketFamily.EXACT_SCORE} <= familles


def test_btts_n_est_pas_cable_faute_de_marche_observe():
    """Validé statistiquement, mais aucun marché autonome dans la capture. Une
    capacité qui ne rencontre jamais son marché gonflerait la couverture sans
    rien couvrir."""
    from src.agents.quant.betting_engine.markets.capability import CAPABILITIES

    assert not any(getattr(c.family, "value", "") == "BTTS" for c in CAPABILITIES)


# ── §10 : le DNB porte sa partition de règlement ─────────────────────────────

def test_le_dnb_porte_sa_partition_inconditionnelle():
    """La probabilité AFFICHÉE reste conditionnelle (c'est ainsi que le marché se
    cote) ; l'ESPÉRANCE, elle, se calcule sur la partition inconditionnelle."""
    from src.agents.quant.betting_engine.value_engine.settlement import Settlement

    resultat = FootballDerivedPricer().price(
        event=_Event(), family=MarketFamily.DRAW_NO_BET,
        parameters={"source_family_id": 3535}, context=_contexte())
    home = next(s for s in resultat.selections if s.selection == "home")

    parts = home.settlement_shares
    assert {p.settlement for p in parts} == {Settlement.WIN, Settlement.PUSH, Settlement.LOSS}
    assert sum(p.probability for p in parts) == pytest.approx(1.0, abs=1e-9)
    # La conditionnelle affichée est bien supérieure à la part gagnante brute.
    gagnante = next(p.probability for p in parts if p.settlement is Settlement.WIN)
    assert home.fair_probability > gagnante
    assert home.fair_probability == pytest.approx(
        gagnante / (1 - next(p.probability for p in parts if p.settlement is Settlement.PUSH)),
        abs=1e-9)


def test_l_ev_du_dnb_tient_compte_du_remboursement():
    """Sans la partition, l'espérance serait celle d'un pari binaire — surestimée
    du facteur 1/(1−P(nul))."""
    from src.agents.quant.betting_engine.value_engine.expected_value import ev

    resultat = FootballDerivedPricer().price(
        event=_Event(), family=MarketFamily.DRAW_NO_BET,
        parameters={"source_family_id": 3535}, context=_contexte())
    avec = resultat.with_market_odds({"home": 1.85, "away": 1.85})
    home = next(s for s in avec.selections if s.selection == "home")

    naif = ev(home.fair_probability, 1.85)
    assert home.expected_value < naif
    assert home.expected_value == pytest.approx(
        naif * (1 - home.settlement_shares[1].probability), abs=1e-9)


def test_les_familles_sans_push_gardent_l_ev_binaire():
    """Aucune régression : là où il n'y a pas de remboursement, rien ne change."""
    from src.agents.quant.betting_engine.value_engine.expected_value import ev

    for famille, params in ((MarketFamily.TOTALS, {"line": 2.5, "source_family_id": 2749}),
                            (MarketFamily.MATCH_WINNER, {})):
        r = FootballDerivedPricer().price(event=_Event(), family=famille,
                                          parameters=params, context=_contexte())
        for s in r.selections:
            assert s.settlement_shares == ()
            avec = s.with_odds(2.10)
            assert avec.expected_value == pytest.approx(ev(s.fair_probability, 2.10), abs=1e-12)
