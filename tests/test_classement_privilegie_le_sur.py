"""« Sécurité d'abord, rendement ensuite » — et pas un mélange pondéré.

Constaté sur un run réel, cinq sélections affichées dans cet ordre :

    Fulham double chance   cote 1.74   p 78,9 %   EV +37,3 %
    Fulham vainqueur DNB   cote 2.45   p 69,9 %   EV +49,8 %
    Bonzi B.               cote 2.70   p 44,9 %   EV +21,3 %
    Marozsan F.            cote 1.98   p 62,3 %   EV +23,1 %
    Texas Rangers          cote 2.05   p 64,7 %   EV +24,7 %

Le score de revue valait `value(EV) × fiabilité × (qualité+fraîcheur)/2` : aucun
terme de probabilité, et `value` SATURE à `ev_cap`. Les cinq EV valant +21 % à
+50 %, toutes étaient à `value = 1` — l'ordre ne tenait plus qu'à la qualité des
données, ce qui est indiscernable du hasard.

La saturation elle-même est délibérée (cf. `test_le_profil_sature_au_dela_de_son_plafond`).
Le défaut était qu'une fois saturée, PLUS RIEN ne départageait.

Une première correction multipliait un terme de probabilité au score, pondéré
par profil (0,85 / 0,60 / 0,25). Elle a été RETIRÉE : ces trois nombres ne
venaient d'aucun banc de mesure, et surtout un mélange pondéré laisse toujours
un gros EV racheter une probabilité nettement plus faible. L'arbitrage était
caché derrière un poids.

Ce qui le remplace est LEXICOGRAPHIQUE et explicite : en posture de sûreté, la
bande de probabilité décide, l'espérance départage à l'intérieur d'une bande.

Ce que ces tests ne garantissent PAS :

  - que les paris passent. Probabilité et rendement sont opposés par
    construction — le bookmaker price ≈ 1/cote.
  - que `probability_low` soit une vraie borne basse. Tant qu'un modèle est
    EXPERIMENTAL, elle RÉPÈTE l'estimation ponctuelle et se signale
    `NOT_ESTIMATED` (cf. `one_x_two.py`). Classer « prudemment » aujourd'hui,
    c'est classer sur l'estimation ponctuelle. La chaîne est correcte, la
    matière ne l'est pas encore.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from src.agents.quant.betting_engine.markets.families import MarketFamily
from src.agents.quant.betting_engine.markets.review_ranking import (
    Comparability, ECART_SECTION, ProductStatus, RankedCandidate,
    RecommendationPosture, ReviewCandidate, _trier, probabilite_de_surete,
)


def _candidat(nom: str, probabilite: float, cote: float) -> ReviewCandidate:
    return ReviewCandidate(
        source_event_id=nom, sport="football", competition="c",
        family=MarketFamily.MATCH_WINNER, parameters={}, context={},
        selection=nom, bookmaker_odds=cote, implied_probability=1 / cote,
        vig_adjusted_probability=1 / cote, fair_probability=probabilite,
        probability_low=probabilite, probability_low_status="ESTIMATED",
        expected_value=0.0, maturity="EXPERIMENTAL",
        freshness=0.9, data_quality=0.95, probability_origin="dixon_coles")


#: (libellé, probabilité prudente, espérance, cote) — le run réel.
REEL = [
    ("Fulham DC",  0.789, 0.373, 1.74),
    ("Fulham DNB", 0.699, 0.498, 2.45),
    ("Bonzi",      0.449, 0.213, 2.70),
    ("Marozsan",   0.623, 0.231, 1.98),
    ("Texas",      0.647, 0.247, 2.05),
]


@pytest.fixture
def rangs() -> list[RankedCandidate]:
    """Score composite IDENTIQUE pour tous : c'est l'état réel une fois la
    valeur saturée, et il isole l'effet de l'ordre."""
    return [
        RankedCandidate(_candidat(nom, p, cote), Comparability.COMPARABLE,
                        ProductStatus.REVIEW, Decimal("0.5"), Decimal(str(ev)))
        for nom, p, ev, cote in REEL
    ]


def test_en_surete_l_ordre_est_celui_des_probabilites(rangs):
    """L'exigence centrale : Fulham DC (79 %) devant Bonzi (45 %), quel que soit
    le rapport cote/probabilité de ce dernier."""
    ordre = [r.candidate.selection for r in _trier(rangs, RecommendationPosture.SAFETY_FIRST)]
    assert ordre == ["Fulham DC", "Fulham DNB", "Texas", "Marozsan", "Bonzi"]


def test_un_meilleur_rendement_ne_rachete_jamais_une_probabilite_plus_basse(rangs):
    """Ce qu'un score pondéré autorisait, et que l'ordre lexicographique interdit.

    « Fulham DNB » a la MEILLEURE espérance du lot (+49,8 %) et reste second,
    derrière une sélection moins rentable mais plus probable.
    """
    classe = _trier(rangs, RecommendationPosture.SAFETY_FIRST)
    meilleur_ev = max(rangs, key=lambda r: r.expected_value_low)
    assert meilleur_ev.candidate.selection == "Fulham DNB"
    assert classe[0].candidate.selection == "Fulham DC"

    probabilites = [probabilite_de_surete(r.candidate)[0] for r in classe]
    assert probabilites == sorted(probabilites, reverse=True), (
        "une probabilité inférieure est passée devant une supérieure")


def test_l_esperance_ne_departage_qu_a_probabilite_strictement_egale(rangs):
    """Le tri est CONTINU : plus de bandes, donc plus de falaise.

    Une version antérieure regroupait par paliers de 5 points pour laisser l'EV
    trancher à l'intérieur d'un palier. C'était arbitraire et discontinu — 0,55
    et 0,53, distants de deux points, tombaient de part et d'autre d'une
    frontière. L'espérance ne départage désormais qu'à probabilité, qualité et
    fraîcheur STRICTEMENT égales.
    """
    from decimal import Decimal as D

    egaux = [
        RankedCandidate(_candidat("faible_ev", 0.70, 1.50), Comparability.COMPARABLE,
                        ProductStatus.REVIEW, D("0.5"), D("0.10")),
        RankedCandidate(_candidat("fort_ev", 0.70, 2.50), Comparability.COMPARABLE,
                        ProductStatus.REVIEW, D("0.5"), D("0.40")),
    ]
    classe = _trier(egaux, RecommendationPosture.SAFETY_FIRST)
    assert classe[0].candidate.selection == "fort_ev"


def test_la_posture_valeur_doit_etre_demandee_pour_inverser_la_priorite(rangs):
    """L'EV ne devient primaire QUE si la valeur est explicitement demandée."""
    ordre = [r.candidate.selection for r in _trier(rangs, RecommendationPosture.VALUE_FIRST)]
    assert ordre[0] == "Fulham DNB", "en posture VALEUR, la meilleure espérance mène"
    assert _trier(rangs, RecommendationPosture.SAFETY_FIRST)[0].candidate.selection == "Fulham DC"


def test_la_surete_est_la_posture_par_defaut(rangs):
    """Ne rien demander ne doit pas exposer au risque."""
    assert [r.candidate.selection for r in _trier(rangs)] == \
           [r.candidate.selection for r in _trier(rangs, RecommendationPosture.SAFETY_FIRST)]


def test_l_ecart_de_section_est_une_convention_d_affichage():
    """Il organise DEUX LISTES à l'écran, rien d'autre : aucune probabilité,
    aucune espérance, aucune maturité, aucune décision de mise n'en dépend. Le
    code doit continuer à le dire."""
    import inspect

    from src.agents.quant.betting_engine.markets import review_ranking

    source = inspect.getsource(review_ranking)
    assert "CONVENTION D'AFFICHAGE" in source
    assert ECART_SECTION == Decimal("0.25")


def test_aucun_poids_de_probabilite_ne_subsiste_dans_le_score():
    """Les trois poids 0,85 / 0,60 / 0,25 ne venaient d'aucun banc de mesure.
    Ce test empêche qu'ils reviennent par la porte de la configuration."""
    from src.agents.quant.advisor.ranking.profiles import load_ranking_profiles

    for nom, profil in load_ranking_profiles().items():
        assert profil.probability_weight == Decimal("0"), (
            f"{nom} remélange la probabilité au score au lieu de la classer")


def test_une_selection_trop_risquee_part_dans_sa_propre_section():
    """Bonzi ne doit pas être « 5e du même classement » : la demande était des
    paris sûrs, et une opportunité de valeur risquée est une AUTRE réponse."""
    assert ProductStatus.VALEUR_RISQUEE.value == "VALEUR_RISQUEE"


def test_la_probabilite_de_surete_dit_d_ou_elle_vient():
    """Point 3 du cahier : ne jamais faire croire qu'une borne prudente existe.

    Tant qu'un modèle est EXPERIMENTAL, `probability_low` vaut None (le contrat
    refuse de reprendre un point estimé comme minorant). La sûreté se juge alors
    sur la probabilité centrale, et le statut le DIT.
    """
    sans_borne = _candidat("x", 0.70, 2.0)
    object.__setattr__(sans_borne, "probability_low", None)
    object.__setattr__(sans_borne, "probability_low_status", "NOT_ESTIMATED")
    valeur, statut = probabilite_de_surete(sans_borne)
    assert valeur == 0.70 and statut == "NOT_ESTIMATED"

    avec_borne = _candidat("y", 0.70, 2.0)
    assert probabilite_de_surete(avec_borne) == (0.70, "ESTIMATED")


def test_le_sectionnement_est_relatif_a_ce_qui_est_offert():
    """Un plancher ABSOLU est arbitraire deux fois : il ne sait pas ce qui est
    offert ce jour-là, et il efface des candidats qui sont pourtant les meilleurs
    de leur run. Mesuré : un plancher à 60 % supprimait jusqu'aux sélections à
    55 %, tête de leur propre scan.

    La règle par défaut est donc un ÉCART à la meilleure du scan.
    """
    tete, bonzi = Decimal("0.789"), Decimal("0.449")
    assert tete - bonzi > ECART_SECTION, (
        "Bonzi doit tomber en section « valeur risquée » face à une tête à 79 %")
    # Une sélection modeste, mais la meilleure de SON scan, n'est pas sectionnée.
    assert Decimal("0.55") - Decimal("0.55") <= ECART_SECTION


def test_seul_le_profil_conservateur_pose_un_plancher_absolu():
    """Le plancher absolu reste disponible pour une demande explicite de sûreté,
    mais il n'est plus imposé par défaut — c'est un choix, pas un réglage caché."""
    from src.agents.quant.advisor.ranking.profiles import load_ranking_profiles

    profils = load_ranking_profiles()
    assert profils["conservative_v1"].min_probability >= Decimal("0.70")
    assert profils["balanced_v1"].min_probability == Decimal("0")
    assert profils["aggressive_v1"].min_probability == Decimal("0")
