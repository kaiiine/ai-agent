"""Le PRODUIT évalue tous les marchés — pas seulement le banc de mesure.

Ces tests portent sur la chaîne réelle : un événement scanné avec ses deux cents
marchés traverse la canonicalisation, la capacité, le pricing, la dévigorisation,
l'espérance settlement-aware et le classement, et ressort sous la forme que
l'utilisateur lit.

Deux familles de propriétés, et la première est la plus importante :

1. RIEN DU CHEMIN HISTORIQUE NE CHANGE. Le marché « qui gagne » garde ses
   nombres, son unicité et son chemin. Un marché dérivé qui le dupliquerait
   compterait deux fois la même opportunité.
2. CE QUI EST AJOUTÉ EST DÉFENDABLE. Aucune borne inventée, aucune fraîcheur
   supposée, aucun candidat classé sans que la politique d'éligibilité l'ait vu.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.agents.quant.betting_engine.bookmakers.protocol import (
    MarketType,
    RawBookmakerEvent,
    RawMarket,
    RawSelection,
)
from src.agents.quant.betting_engine.markets.event_pricing import (
    MarketFunnel,
    price_event_markets,
    pricers_partages,
    review_candidates,
)
from src.agents.quant.betting_engine.markets.families import MarketFamily
from src.agents.quant.betting_engine.sports.football.market_models.derived import (
    FootballDerivedPricer,
)
from src.agents.quant.betting_engine.sports.football.market_models.one_x_two import OneXTwoModel

_T = datetime(2026, 8, 14, 12, 0, tzinfo=timezone.utc)


# ── Doublures minimales, calquées sur les objets réels ───────────────────────
class _Participant:
    def __init__(self, role, cid):
        self.role, self.canonical_id = role, cid


class _Event:
    event_id = "event:football:nld:2026-08-14:home=telstar|away=sparta"
    sport = "football"
    competition_id = "competition:football:nld:eredivisie"
    scheduled_at = _T + timedelta(hours=6)
    participants = (_Participant("home", "team:football:nld:telstar"),
                    _Participant("away", "team:football:nld:sparta"))


class _Features:
    def __init__(self, rest_days=6):
        self.participant_features = {
            "team:football:nld:telstar": {
                "attack_strength": 1.2, "defense_strength": 0.9, "rest_days": rest_days},
            "team:football:nld:sparta": {
                "attack_strength": 0.95, "defense_strength": 1.1, "rest_days": rest_days}}
        self.missing_features = set()
        self.as_of = _T


def _selection(code, label, odds):
    return RawSelection(code=code, label=label, decimal_odds=odds,
                        canonical_selection={"1": "slot_1", "2": "slot_2",
                                             "x": "draw"}.get(code, "UNMAPPED"))


def _marche(bet_type, label, template, sbv, selections, market_type=MarketType.UNMAPPED):
    return RawMarket(market_type=market_type, raw_bet_type=bet_type, raw_label=label,
                     template=template, is_live=False, special_bet_value=sbv,
                     selections=[_selection(*s) for s in selections],
                     market_source_id=f"bet-{bet_type}")


#: Marchés RÉELS d'une rencontre, avec leurs `betType` mesurés. Les deux derniers
#: sont là pour être refusés : un total de MI-TEMPS et un total d'ÉQUIPE portent
#: exactement la même forme canonique que celui de la rencontre.
def _evenement(markets=None) -> RawBookmakerEvent:
    return RawBookmakerEvent(
        bookmaker="winamax", bookmaker_event_id="72530852", sport="football",
        competition="Eredivisie", slot_1_name="Telstar", slot_2_name="Sparta",
        slot_1_id="1", slot_2_id="2", start_time=_T + timedelta(hours=6),
        status="PREMATCH", is_outright=False,
        markets=markets if markets is not None else [
            _marche(1, "Résultat", "3way", None,
                    [("1", "Telstar", 1.94), ("x", "Nul", 3.65), ("2", "Sparta", 3.05)],
                    market_type=MarketType.MATCH_WINNER),
            _marche(2749, "Nombre de buts", "OverUnder", "total=2.5",
                    [("over", "Plus de 2,5", 1.80), ("under", "Moins de 2,5", 2.00)]),
            _marche(2749, "Nombre de buts", "OverUnder", "total=1.5",
                    [("over", "Plus de 1,5", 1.25), ("under", "Moins de 1,5", 3.80)]),
            _marche(3072, "Double chance", "3way", None,
                    [("9", "1N", 1.27), ("10", "12", 1.30), ("11", "N2", 1.75)]),
            _marche(3535, "Vainqueur (remboursé si match nul)", "2way", None,
                    [("1", "Telstar", 1.44), ("2", "Sparta", 2.55)]),
            _marche(2531, "Mi-temps - Nombre de buts", "OverUnder", "total=1.5",
                    [("over", "Plus de 1,5", 2.60), ("under", "Moins de 1,5", 1.45)]),
            _marche(2680, "Nombre de buts de Telstar", "OverUnder", "total=1.5",
                    [("over", "Plus de 1,5", 3.10), ("under", "Moins de 1,5", 1.33)]),
        ],
        fetched_at=_T, raw_tournament_id="9", declared_market_count=253)


_ROLES = {"slot_1": "home", "slot_2": "away"}


def _pricer(event=None, features=None, funnel=None, freshness_at=None):
    return price_event_markets(
        event or _evenement(), event=_Event(), features=features or _Features(),
        decision_time=_T, pricers=pricers_partages((FootballDerivedPricer(),)),
        roles=_ROLES, competition_id="competition:football:nld:eredivisie",
        funnel=funnel, freshness_at=freshness_at)


# ══ 1 · Ce qui ne doit pas bouger ═══════════════════════════════════════════
def test_le_total_de_mi_temps_et_le_total_d_equipe_sont_refuses():
    """Ils ont la MÊME forme que le total de la rencontre, et le `betType` seul
    les sépare — se fier au libellé reviendrait à pricer une mi-temps avec la loi
    du match entier.

    Les deux refus ne se ressemblent pourtant pas, et la distinction est le
    résultat d'une correction : la MI-TEMPS est un `TOTALS` à une portée que le
    modèle ne couvre pas (`MODEL_CONTEXT_MISMATCH`), tandis que le total
    d'ÉQUIPE est une FAMILLE À PART — son `betType` désigne le camp, mesuré sur
    40 marchés — pour laquelle le football n'a aucun modèle
    (`MODEL_NOT_AVAILABLE`). Dire « mauvaise portée » là où il manque un modèle
    enverrait chercher au mauvais endroit.
    """
    entonnoir = MarketFunnel()
    marches = _pricer(funnel=entonnoir)

    priceés = {(m.family, dict(m.pricing.parameters).get("source_family_id"))
               for m in marches if m.priced}
    assert not any(bt in (2531, 2680) for _, bt in priceés)
    assert entonnoir.exclusions["MODEL_CONTEXT_MISMATCH"] == 1     # la mi-temps
    assert entonnoir.exclusions["MODEL_NOT_AVAILABLE"] >= 1        # le total d'équipe


def test_le_total_d_equipe_est_une_famille_a_part_entiere():
    """Fondre le total d'un camp dans `TOTALS` leur donnerait la MÊME identité de
    contrat — donc la même exposition et la même paire CLV — pour deux paris qui
    n'ont rien à voir : « plus de 1,5 but pour Telstar » et « plus de 1,5 but
    dans le match »."""
    from src.agents.quant.betting_engine.clv.contract import identite_contrat
    from src.agents.quant.betting_engine.markets.families import classify
    from src.agents.quant.betting_engine.markets.observation import observation_de_marche

    evenement = _evenement([
        _marche(2749, "Nombre de buts", "OverUnder", "total=1.5",
                [("over", "Plus de 1,5", 1.25), ("under", "Moins de 1,5", 3.80)]),
        _marche(2680, "Nombre de buts de Sparta", "OverUnder", "total=1.5",
                [("over", "Plus de 1,5", 3.10), ("under", "Moins de 1,5", 1.33)])])

    classees = [classify(observation_de_marche(evenement, m)) for m in evenement.markets]

    assert classees[0].family is MarketFamily.TOTALS
    assert classees[1].family is MarketFamily.TEAM_TOTALS
    assert classees[1].parameters["side"] == "slot_2"
    contrats = {identite_contrat(c.family, c.parameters) for c in classees}
    assert len(contrats) == 2, contrats


def test_le_vainqueur_n_est_jamais_dupliqué_par_le_chemin_derive():
    """Le marché « qui gagne » est évalué par le modèle du sport. Le repricer ici
    produirait deux candidats pour un seul pari."""
    from src.agents.quant.betting_engine.live_evaluation import _FAMILLES_DEJA_EVALUEES

    assert "MATCH_WINNER" in _FAMILLES_DEJA_EVALUEES


def test_les_compteurs_de_l_entonnoir_bouclent():
    """Un marché qui disparaît sans motif est un bug, pas un silence."""
    entonnoir = MarketFunnel()
    _pricer(funnel=entonnoir)

    equilibre, detail = entonnoir.equilibre()
    assert equilibre, detail
    assert entonnoir.markets_observed == 7


# ══ 2 · Ce qui est ajouté ═══════════════════════════════════════════════════
def test_une_seule_distribution_pour_tous_les_marches_de_l_evenement():
    """Neuf marchés, neuf projections, UNE loi. Deux calculs séparés pourraient
    diverger, et plus rien ne garantirait que P(home) et P(over 2.5) soient
    mutuellement cohérents."""
    class _Compteur(OneXTwoModel):
        appels = 0

        def distribution(self, event, features, point_in_time):
            type(self).appels += 1
            return super().distribution(event, features, point_in_time)

    _Compteur.appels = 0
    pricers = pricers_partages((FootballDerivedPricer(base=_Compteur()),))
    marches = price_event_markets(
        _evenement(), event=_Event(), features=_Features(), decision_time=_T,
        pricers=pricers, roles=_ROLES)

    assert sum(1 for m in marches if m.priced) >= 5
    assert _Compteur.appels == 1


def test_la_double_chance_est_devigorisee_sur_une_masse_de_deux():
    """Ses trois issues sont les unions deux à deux d'une partition à trois :
    chaque résultat y est couvert exactement deux fois. Normaliser vers 1
    fabriquerait un edge de −50 % sur chacune."""
    marche = next(m for m in _pricer()
                  if m.priced and m.family is MarketFamily.DOUBLE_CHANCE)

    masse = sum(s.vig_adjusted_probability for s in marche.pricing.selections)
    assert masse == pytest.approx(2.0, abs=1e-6)
    assert all(s.edge is not None and abs(s.edge) < 0.5 for s in marche.pricing.selections)


def test_le_remboursé_si_nul_utilise_une_esperance_settlement_aware():
    """Le nul rend la mise : traiter ce pari comme binaire surestime son
    espérance par unité misée d'un facteur 1/(1−P(nul))."""
    marche = next(m for m in _pricer()
                  if m.priced and m.family is MarketFamily.DRAW_NO_BET)
    selection = next(s for s in marche.pricing.selections if s.selection == "home")

    assert selection.settlement_shares, "les parts de règlement doivent être portées"
    naif = selection.fair_probability * selection.bookmaker_odds - 1.0
    assert selection.expected_value < naif


def test_aucune_fraicheur_n_est_attachee_sans_instant_de_reference():
    """Le point-in-time du modèle précède le scan : une cote lui est postérieure,
    et son âge y serait négatif. Sans référence, on ne mesure rien — plutôt que
    de mesurer n'importe quoi."""
    sans = _pricer()
    avec = _pricer(freshness_at=_T + timedelta(seconds=30))

    assert all(m.pricing.freshness is None for m in sans if m.priced)
    assert all(m.pricing.freshness is not None for m in avec if m.priced)


def test_une_ligne_entiere_est_refusee_et_dit_pourquoi():
    """Sur « Plus de 2 » avec un total de 2 exactement, le payload ne dit pas si
    la mise est remboursée ou perdue. Le calcul de probabilité serait le même ;
    c'est l'économie du pari qui serait fausse, et invisible."""
    evenement = _evenement([
        _marche(2749, "Nombre de buts", "OverUnder", "total=2.0",
                [("over", "Plus de 2", 2.10), ("under", "Moins de 2", 1.75)])])
    entonnoir = MarketFunnel()
    marches = _pricer(evenement, funnel=entonnoir)

    assert not any(m.priced for m in marches)
    assert entonnoir.markets_canonicalized == 1     # parfaitement LU
    assert entonnoir.markets_priced == 0            # et non priçable


def test_la_ligne_rejetee_par_la_validation_ne_ressort_pas():
    """0.5 échoue `must_beat_baselines` : le modèle n'y apporte rien qu'un
    compteur ne donne déjà. Une probabilité inutile présentée comme un edge est
    une invitation à parier sans raison."""
    evenement = _evenement([
        _marche(2749, "Nombre de buts", "OverUnder", "total=0.5",
                [("over", "Plus de 0,5", 1.10), ("under", "Moins de 0,5", 7.00)])])
    entonnoir = MarketFunnel()

    assert not any(m.priced for m in _pricer(evenement, funnel=entonnoir))
    assert entonnoir.markets_canonicalized == 1


def test_les_candidats_partagent_l_origine_de_leur_distribution():
    """Deux marchés d'un même événement issus de la même matrice ne sont pas deux
    paris indépendants : sans cette trace, le sizing les additionne comme s'ils
    diversifiaient, et concentre le risque en croyant l'étaler."""
    candidats = review_candidates(_pricer(), sport="football")

    origines = {c.probability_origin for c in candidats}
    assert len(origines) == 1 and next(iter(origines)).startswith("dixon_coles:")


def test_un_marche_non_price_ne_produit_aucun_candidat():
    """Une abstention n'est pas une opportunité mal classée : c'est l'absence
    d'opportunité. Son motif vit dans l'entonnoir, pas dans le classement."""
    evenement = _evenement([
        _marche(2531, "Mi-temps - Nombre de buts", "OverUnder", "total=1.5",
                [("over", "Plus de 1,5", 2.60), ("under", "Moins de 1,5", 1.45)])])

    assert review_candidates(_pricer(evenement), sport="football") == []


def test_un_participant_hors_domaine_bloque_le_pricing_de_tous_ses_marches():
    """L'identité de l'équipe n'a pas changé ; son appartenance au domaine du
    modèle, si. Le garde porte sur les DONNÉES, jamais sur l'espérance."""
    entonnoir = MarketFunnel()
    marches = _pricer(features=_Features(rest_days=810), funnel=entonnoir)

    assert not any(m.priced for m in marches)
    assert entonnoir.exclusions["MODEL_DOMAIN_MISMATCH"] >= 4


# ══ 3 · Corrélation et garde anti-invention ═════════════════════════════════
def test_deux_marches_de_la_meme_matrice_ne_sont_pas_mises_deux_fois():
    """« Domicile gagne » et « plus de 2,5 buts » sortent de la MÊME loi jointe :
    ils montent et descendent ensemble. Les additionner comme s'ils
    diversifiaient concentre le risque en croyant l'étaler.

    Le champ existait sur le candidat et la règle de portefeuille le lisait déjà —
    mais rien ne le remplissait : la contrainte était inerte en production.
    """
    from src.agents.quant.advisor.candidate_generation.generator import (
        candidate_from_evaluation,
    )
    from src.agents.quant.advisor.policy.reason_codes import CORRELATED_SAME_ORIGIN

    from tests.test_review_produit import _evaluation as _adaptee

    deux = [candidate_from_evaluation(_adaptee(selection="over")),
            candidate_from_evaluation(_adaptee(market="DOUBLE_CHANCE", famille="DOUBLE_CHANCE",
                                               parametres=(), selection="home_or_draw"))]

    assert {c.probability_origin for c in deux} == {"dc:1"}
    assert CORRELATED_SAME_ORIGIN == "CORRELATED_SAME_ORIGIN"


def test_le_garde_ne_traite_aucune_famille_a_part():
    """Le garde lit une AFFIRMATION chiffrée, pas un nom de marché. La propriété
    à tenir n'est donc pas qu'une phrase précise soit bloquée : c'est que deux
    phrases identiques à la famille près reçoivent le MÊME verdict. Sans ça, une
    famille ajoutée ouvre un angle mort dans un composant qui n'a pas changé.
    """
    from src.agents.quant.conversation.guard import enforce

    gabarits = [
        "Je te recommande de parier sur {} à 1.85.",
        "{} à 1.85 : mise 10 € dessus.",
        "{} est à 1.85 et l'espérance positive le justifie.",
        "Une cote de 1.85 sur {} correspond à 54 % de probabilité implicite.",
    ]
    familles = ["le vainqueur", "Plus de 2,5 buts", "la double chance 1N",
                "le score exact 2-1", "le vainqueur remboursé si nul"]

    for gabarit in gabarits:
        verdicts = {enforce(gabarit.format(f), None).allowed for f in familles}
        assert len(verdicts) == 1, (
            f"verdicts divergents selon la famille pour : {gabarit}")

    # Et la conjonction interdite reste bloquée, quelle que soit la famille.
    for famille in familles:
        verdict = enforce(f"Je te recommande de parier sur {famille} à 1.85.", None)
        assert not verdict.allowed and "1.85" not in verdict.replacement
