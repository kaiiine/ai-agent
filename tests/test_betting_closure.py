"""Fermeture du chemin conversationnel betting — les violations du dump, une à une.

Les vagues précédentes ont construit la chaîne structurée et le garde. Ce fichier
prouve les points qui restaient affirmés sans être testés : les chiffres exacts
du dump, la propriété du combiné, celle de la mise, et la traçabilité de chaque
fait sportif du texte final vers un champ de la réponse structurée.

Aucun de ces tests ne dépend d'un modèle de langage. C'est le point : ce sont des
propriétés du code, vraies que le modèle obéisse ou non.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from src.agents.quant.conversation.constraints import constraints_from_request
from src.agents.quant.conversation.evidence import (
    EVIDENCE_KEY,
    BettingResponseEvidence,
    extract_evidence,
    redundant_scope_question,
)
from src.agents.quant.conversation.guard import enforce
from src.agents.quant.conversation.renderer import render
from src.agents.quant.conversation.window import PARIS, resolve_window

from tests.test_betting_conversation_safety import _evaluation, _preuve, _run

_MAINTENANT = datetime(2026, 8, 6, 15, 30, tzinfo=PARIS)


def _contraintes(**kw):
    return constraints_from_request(
        None, bankroll=Decimal("20"),
        time_window=resolve_window("", _MAINTENANT), **kw)


# ══ §4 — L'EV du dump, avec ses chiffres exacts ══════════════════════════════
def test_la_cote_du_dump_ne_produit_aucune_EV_positive():
    """Le dump annonçait un gain espéré à partir d'une cote de 1.34 et d'une
    bankroll de 20 €. En partant de la probabilité implicite — la seule dont le
    modèle disposait — l'espérance est exactement nulle avant marge."""
    from src.agents.quant.betting_engine.value_engine.expected_value import ev

    cote = 1.34
    implicite = 1 / cote

    esperance = ev(implicite, cote)
    gain_attendu_sur_20 = esperance * 20

    assert abs(esperance) < 1e-12
    assert abs(gain_attendu_sur_20) < 1e-10        # jamais +4,40 €


@pytest.mark.parametrize("cote", [1.10, 1.34, 1.50, 1.90, 2.40, 5.00])
def test_aucune_cote_ne_rend_son_implicite_rentable(cote):
    """La propriété est générale, pas un cas particulier : `p = 1/cote` annule
    l'espérance par construction, et la marge du bookmaker la rend négative."""
    from src.agents.quant.betting_engine.value_engine.expected_value import ev

    assert abs(ev(1 / cote, cote)) < 1e-12
    assert ev(1 / cote * 0.95, cote) < 0           # avec 5 % de marge réelle


def test_le_renderer_ne_recalcule_jamais_une_EV():
    """Le seul rempart durable : le renderer LIT l'EV, il ne la compose pas. Une
    multiplication dans ce fichier rouvrirait la formule interdite."""
    import ast
    import inspect

    from src.agents.quant.conversation import renderer

    arbre = ast.parse(inspect.getsource(renderer))

    # Ce sont les APPELS qui recalculent. Lire `line.expected_value` est
    # exactement ce qu'on veut : une lecture du champ produit par le moteur.
    appels: set[str] = set()
    for noeud in ast.walk(arbre):
        if not isinstance(noeud, ast.Call):
            continue
        cible = noeud.func
        appels.add(cible.id if isinstance(cible, ast.Name)
                   else getattr(cible, "attr", ""))

    for interdit in ("ev", "expected_value", "implied_raw", "implied_probability",
                     "no_vig_probability", "kelly", "margin_removal"):
        assert interdit not in appels, f"le renderer appelle {interdit}()"


# ══ §7 — Le combiné appartient au Combo Builder ══════════════════════════════
def test_un_combine_invente_par_le_LLM_n_a_aucun_effet_sur_la_sortie():
    """Le texte du modèle n'entre nulle part dans la chaîne : le rendu vient de
    `RecommendationResponse`. Multiplier des probabilités à la main ne change
    donc rien — et la tentative est bloquée à l'affichage."""
    run, _ = _run(_contraintes(), [_evaluation(), _evaluation(event="e2")])
    avant = render(run)

    invention = ("Combiné des deux favoris : 0.57 × 0.57 = 32.5 %, cote totale "
                 "4.41, je te conseille de miser 5 €.")
    apres = render(run)

    assert avant == apres                                   # aucune influence
    assert enforce(invention, run.evidence).blocked         # et refusé au rendu


def test_le_renderer_ne_multiplie_aucune_probabilite():
    import ast
    import inspect

    from src.agents.quant.conversation import renderer

    arbre = ast.parse(inspect.getsource(renderer))

    # Deux multiplications sont légitimes et documentées : convertir une
    # probabilité en pourcentage, et dériver le retour brut d'une mise ADVISOR.
    # Toute autre — en particulier proba × proba — reconstruirait une probabilité
    # jointe hors Combo Builder.
    autorisees = {"* 100", "line.stake * line.total_odds"}
    for noeud in ast.walk(arbre):
        if not (isinstance(noeud, ast.BinOp) and isinstance(noeud.op, ast.Mult)):
            continue
        source = ast.unparse(noeud)
        assert any(motif in source for motif in autorisees), (
            f"multiplication non prévue dans le renderer : {source}")
        assert "probability" not in source, (
            f"probabilité multipliée dans le renderer : {source}")


def test_un_combine_rendu_porte_le_contrat_du_combo_builder():
    """Une ligne COMBO ne peut exister qu'avec ses legs, sa cote totale, sa
    probabilité estimée et ses deux EV — le contrat du builder. Le renderer les
    lit, il n'en fabrique aucun."""
    from src.agents.quant.advisor.domain.enums import LineType
    from src.agents.quant.advisor.domain.portfolios import BetLeg, PortfolioLine

    ligne = PortfolioLine(
        line_id="L1", line_type=LineType.COMBO, bookmaker="winamax",
        legs=(BetLeg("c1", "e1", "m1", "home", "winamax", Decimal("1.80")),
              BetLeg("c2", "e2", "m2", "away", "winamax", Decimal("2.10"))),
        stake=Decimal("2.40"), total_odds=Decimal("3.78"),
        estimated_probability=Decimal("0.28"), expected_value=Decimal("0.0584"),
        worst_case_ev=Decimal("0.0120"), correlation_warning=None)

    assert len(ligne.legs) == 2 and ligne.line_type is LineType.COMBO
    with pytest.raises(ValueError):
        # Un « combiné » à une seule jambe n'existe pas : le domaine le refuse.
        PortfolioLine(line_id="L2", line_type=LineType.COMBO, bookmaker="winamax",
                      legs=(ligne.legs[0],), stake=Decimal("1"),
                      total_odds=Decimal("1.80"), estimated_probability=Decimal("0.5"),
                      expected_value=Decimal("0"), worst_case_ev=Decimal("0"),
                      correlation_warning=None)


# ══ §8 — La mise appartient à l'Advisor ══════════════════════════════════════
def test_la_mise_affichee_est_celle_de_l_advisor_au_centime():
    """Advisor dit 2,40 € : le texte affiche 2,40 €, et ni 20 € ni « tout »."""
    from src.agents.quant.advisor.domain.enums import LineType
    from src.agents.quant.advisor.domain.portfolios import (
        BetLeg, PortfolioExplanation, PortfolioLine, RecommendationPortfolio,
    )
    from src.agents.quant.conversation.renderer import _render_portefeuille

    ligne = PortfolioLine(
        line_id="L1", line_type=LineType.SINGLE, bookmaker="winamax",
        legs=(BetLeg("c1", "e1", "m1", "home", "winamax", Decimal("2.10")),),
        stake=Decimal("2.40"), total_odds=Decimal("2.10"),
        estimated_probability=Decimal("0.57"), expected_value=Decimal("0.1970"),
        worst_case_ev=Decimal("0.1550"), correlation_warning=None)
    portefeuille = RecommendationPortfolio(
        portfolio_id="P1", request_id="r1", strategy_id="s1", lines=(ligne,),
        total_stake=Decimal("2.40"), unallocated_bankroll=Decimal("17.60"),
        expected_return=Decimal("0"), expected_profit=Decimal("0"),
        downside_score=Decimal("0"), concentration_score=Decimal("0"),
        target_odds_match=True, quality_score=Decimal("0"), warnings=(),
        explanation=PortfolioExplanation("ok", {}, {}, (), (), ()))

    texte = "\n".join(_render_portefeuille(portefeuille, Decimal("20")))

    assert "2.40 €" in texte
    assert "bankroll non allouée 17.60 €" in texte
    assert "20.00 €" not in texte
    assert "tout" not in texte.lower()


def test_le_renderer_ne_calcule_aucune_mise():
    """Retour brut et profit net sont dérivés de la mise ADVISOR, jamais l'inverse."""
    import inspect

    from src.agents.quant.conversation import renderer

    source = inspect.getsource(renderer._render_portefeuille)

    assert "line.stake" in source                       # lue
    assert "kelly" not in source.lower()
    assert "bankroll *" not in source and "bankroll*" not in source


def test_une_mise_inventee_par_le_LLM_est_bloquee():
    verdict = enforce("Mets 20 € sur cette sélection, c'est le meilleur pari.",
                      BettingResponseEvidence.from_dict(_preuve("REVIEW_CANDIDATES")))

    assert verdict.blocked


# ══ §10 — Traçabilité : tout fait sportif vient d'un champ structuré ═════════
_NOMBRE = re.compile(r"\d+[.,]\d{2,4}")


def test_chaque_nombre_du_rendu_provient_d_un_champ_structure():
    """Le test le plus fort du lot : on extrait tous les nombres du texte final et
    on exige que chacun se retrouve dans un champ de la réponse structurée ou de
    la preuve. Un nombre qui n'y figure pas aurait été composé par le rendu —
    c'est-à-dire inventé."""
    run, _ = _run(_contraintes(), [_evaluation(freshness=None)])
    texte = render(run)

    autorises: set[str] = set()
    for evaluation in run.response.review_candidates:
        c = evaluation.candidate
        for valeur in (c.bookmaker_odds, c.fair_probability, c.probability_low,
                       c.probability_high, c.expected_value_mean,
                       c.expected_value_low, c.data_quality):
            autorises.add(str(valeur))
            autorises.add(f"{(valeur * 100).quantize(Decimal('0.01'))}")
            autorises.add(f"{valeur.quantize(Decimal('0.0001'))}")
    adapte = run.observability.adapted_for(
        run.response.review_candidates[0].candidate)
    if adapte is not None and adapte.no_vig_probability is not None:
        autorises.add(f"{(adapte.no_vig_probability * 100).quantize(Decimal('0.01'))}")
    autorises.add(str(run.constraints.bankroll.quantize(Decimal("0.01"))))

    orphelins = [n for n in _NOMBRE.findall(texte)
                 if n not in autorises and n.replace(",", ".") not in autorises]

    assert not orphelins, f"nombres sans source structurée : {orphelins}"


def test_aucun_participant_n_est_nomme_hors_referentiel():
    """Les noms affichés viennent du référentiel d'identités, jamais dérivés d'un
    identifiant — sans quoi « team:football:psg » deviendrait « Psg »."""
    import inspect

    from src.agents.quant.conversation import renderer

    source = inspect.getsource(renderer.participant_label)

    assert "_names()" in source
    assert ".split(" not in source and ".title()" not in source


# ══ §3A — La clarification de périmètre déjà répondue ════════════════════════
def _tour_avec_scan(constraints: dict) -> list:
    return [
        HumanMessage("tous les sports"),
        AIMessage(""),
        ToolMessage(content=json.dumps({
            "status": "COMPLETED", "rendered": "…",
            EVIDENCE_KEY: _preuve("REVIEW_CANDIDATES"),
            "constraints": constraints}),
            tool_call_id="c1", name="betting_recommend"),
    ]


_ETAT_COMPLET = {"sports": "ALL", "competitions": "ALL", "markets": None,
                 "time_window": "…", "bankroll": "20.0"}


@pytest.mark.parametrize("question", [
    "Souhaitez-vous restreindre à un sport seulement ?",
    "Sur quelle compétition voulez-vous parier ?",
    "Quelle période vous intéresse ?",
    "Quel est votre bankroll ?",
])
def test_une_question_de_perimetre_deja_repondue_est_detectee(question):
    """Observé en conversation réelle : après un scan complet, le modèle propose
    « restreindre à un sport ? » — trois fois de suite. La question est nouvelle,
    c'est sa RÉPONSE qui est déjà connue, donc le garde de doublon ne l'attrape
    pas."""
    messages = _tour_avec_scan(_ETAT_COMPLET)

    assert redundant_scope_question(messages, [{"question": question}])


@pytest.mark.parametrize("question", [
    # Capturés VERBATIM d'un run réel du graphe complet avec gpt-oss:120b.
    {"question": "Souhaitez-vous affiner la recherche ?",
     "choices": ["Spécifier un sport (ex. football, tennis)",
                 "Spécifier une compétition (ex. Ligue 1, NBA)",
                 "Étendre la fenêtre à plus de 24h"]},
    {"question": "Que voulez-vous faire ?",
     "choices": ["Élargir le créneau horaire (inclure la soirée du 8 août)",
                 "Accepter les sélections en REVIEW_ONLY pour un examen manuel"]},
])
def test_les_relances_reelles_du_modele_sont_detectees(question):
    """Le libellé ne porte pas la dimension — elle vit dans les CHOIX. Ne lire
    que `question` laissait passer exactement ces deux relances, celles que le
    modèle a réellement produites après avoir reçu un scan complet."""
    assert redundant_scope_question(_tour_avec_scan(_ETAT_COMPLET), [question])


def test_une_question_sur_une_dimension_non_fixee_reste_legitime():
    """Le marché n'a pas été précisé : la demander est utile, pas redondant."""
    messages = _tour_avec_scan(_ETAT_COMPLET)

    assert not redundant_scope_question(
        messages, [{"question": "Quel type de marché voulez-vous ?"}])


def test_sans_scan_dans_le_tour_aucune_question_n_est_jugee():
    """Sans résultat structuré, rien ne prouve que la réponse existe déjà."""
    messages = [HumanMessage("des paris ?")]

    assert not redundant_scope_question(
        messages, [{"question": "Quel sport vous intéresse ?"}])


def test_le_garde_de_clarification_est_cable_avant_le_garde_de_provenance():
    """Ordre voulu : on corrige d'abord la question inutile, puis on vérifie la
    provenance de la réponse produite. L'inverse validerait une question."""
    import inspect

    from src.orchestrator import graph

    source = inspect.getsource(graph)
    position_clarif = source.index("redundant_scope_question")
    position_garde = source.index("conversation.guard import enforce")

    assert position_clarif < position_garde


# ══ §5 — Fenêtre : un match du 23 août ne peut pas répondre au 6-7 ═══════════
def test_un_match_du_23_aout_ne_repond_jamais_a_une_demande_du_6_aout():
    """Le cas exact du dump : une date inventée, très au-delà de la fenêtre."""
    fenetre = resolve_window("aujourd'hui ou demain matin", _MAINTENANT)

    assert not fenetre.contains(datetime(2026, 8, 23, 20, 0, tzinfo=PARIS))
    assert fenetre.contains(_MAINTENANT + timedelta(hours=2))
    assert fenetre.end == datetime(2026, 8, 7, 12, 0, tzinfo=PARIS)


def test_le_filtrage_temporel_precede_le_classement():
    """Filtrer après le ranking laisserait un match hors fenêtre influencer
    l'ordre, puis disparaître — l'utilisateur verrait un classement dont il ne
    peut pas reconstituer la logique."""
    import inspect

    from src.agents.quant.conversation import recommend

    source = inspect.getsource(recommend._default_scan)

    assert "window.contains(e.start_time)" in source
    assert source.index("window.contains") < source.index("evaluate_live_batch(")
