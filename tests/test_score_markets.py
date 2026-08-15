"""Marchés de SCORE — marge et total — pour les sports à points.

Ce que ces tests protègent n'est pas la qualité des modèles : elle est mesurée
par le benchmark, et le benchmark est reproductible. C'est la chaîne autour
d'eux — les refus. Un modèle de score se trompe silencieusement de trois façons,
et chacune produit une probabilité parfaitement plausible :

- en pricant une PORTÉE qu'il ne couvre pas (mi-temps, quart-temps) ;
- en attribuant un handicap au MAUVAIS CAMP, ce qui inverse exactement la
  prédiction ;
- en appliquant les notes d'un championnat à un autre.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.agents.quant.betting_engine.markets.capability import (
    BET_TYPES_SCORE_RENCONTRE,
    CapabilityStatus,
    resolve_model,
)
from src.agents.quant.betting_engine.markets.families import MarketFamily
from src.agents.quant.betting_engine.markets.pricing import PricingStatus
from src.agents.quant.betting_engine.markets.selection_binding import (
    canonicaliser_selections,
    slot_du_handicap,
)
from src.agents.quant.betting_engine.sports.score_distribution import (
    ScoreGame,
    ScoreParams,
    SequentialScoreRatings,
    cibles_marge,
    cibles_total,
    lignes_autour,
    run_score_walk_forward,
)
from src.agents.quant.betting_engine.sports.score_pricer import ScorePricer

_T = datetime(2026, 2, 20, 18, 0, tzinfo=timezone.utc)


# ══ La grammaire du handicap, mesurée sur 548 marchés réels ═════════════════
@pytest.mark.parametrize("handicap,code,slot", [
    (-10.5, "yes", "slot_1"),      # « Seattle Storm -10.5 » : slot_1 donne
    (-10.5, "no", "slot_2"),       # « Portland Fire +10.5 »
    (9.5, "no", "slot_1"),         # « Seattle Storm +9.5 » : slot_1 reçoit
    (9.5, "yes", "slot_2"),        # « Portland Fire -9.5 »
    (-8.5, "yes", "slot_1"),       # NFL : « Los Angeles Rams -8.5 »
    (0.5, "no", "slot_1"),         # NFL : « Los Angeles Rams +0.5 »
])
def test_le_signe_du_handicap_designe_le_camp(handicap, code, slot):
    """Le sujet du handicap vient du SIGNE de `hcp`, jamais du libellé. Les
    couples ci-dessus sont des marchés réels : la règle a été vérifiée sur 548
    d'entre eux, et les seuls écarts portaient sur l'orthographe du nom
    (« L.A. Sparks » pour « Los Angeles Sparks »)."""
    assert slot_du_handicap(handicap, code) == slot


def test_un_handicap_nul_ne_designe_personne():
    """« slot_1 +0 » et « slot_2 −0 » ne se distinguent plus, et le règlement
    d'une égalité exacte serait à deviner. Deux raisons de refuser."""
    assert slot_du_handicap(0.0, "yes") is None
    assert slot_du_handicap(0.0, "no") is None


def test_les_issues_d_un_handicap_se_lient_aux_roles():
    binding = canonicaliser_selections(
        family=MarketFamily.HANDICAP, codes=["yes", "no"],
        roles={"slot_1": "home", "slot_2": "away"}, parameters={"handicap": -5.5})

    assert binding.complete
    assert binding.par_code == {"yes": "home", "no": "away"}


def test_un_handicap_sans_valeur_numerique_ne_se_lie_pas():
    """Sans `hcp`, aucune issue n'est attribuable — et une issue attribuée au
    mauvais camp est une prédiction exactement inversée."""
    binding = canonicaliser_selections(
        family=MarketFamily.HANDICAP, codes=["yes", "no"],
        roles={"slot_1": "home", "slot_2": "away"}, parameters={})

    assert not binding.complete


# ══ Capacité : la portée vient du betType, jamais du libellé ════════════════
@pytest.mark.parametrize("sport_id,famille,cle,valeur", [
    (2, MarketFamily.TOTALS, "line", 220.5),
    (2, MarketFamily.HANDICAP, "handicap", -5.5),
    (16, MarketFamily.TOTALS, "line", 44.5),
    (16, MarketFamily.HANDICAP, "handicap", 3.5),
])
def test_le_marche_de_la_rencontre_est_couvert(sport_id, famille, cle, valeur):
    resolution = resolve_model(
        winamax_sport_id=sport_id, family=famille,
        context={cle: valeur,
                 "source_family_id": BET_TYPES_SCORE_RENCONTRE[sport_id][famille]})

    assert resolution.status is CapabilityStatus.MODEL_AVAILABLE


@pytest.mark.parametrize("bet_type,motif", [
    (2532, "mi-temps"),          # « Mi-temps - Nombre de points »
    (2877, "total d'équipe"),    # « Nombre de points de Dallas Wings »
    (3722, "prop de joueur"),    # « Nombre de points du joueur - … »
])
def test_les_autres_portees_sont_refusees_par_leur_betType(bet_type, motif):
    """Elles portent la MÊME famille canonique et les MÊMES paramètres que le
    marché de la rencontre. Mesuré : le total d'équipe change de `betType` avec
    l'équipe (2877 Dallas Wings, 2474 Indiana Fever) — aucune table ne dit lequel
    des deux camps un betType inconnu désigne."""
    resolution = resolve_model(
        winamax_sport_id=2, family=MarketFamily.TOTALS,
        context={"line": 220.5, "source_family_id": bet_type})

    assert resolution.status is CapabilityStatus.MODEL_CONTEXT_MISMATCH, motif


def test_une_ligne_hors_du_support_evalue_est_refusee():
    """Le benchmark balaie ±3 écarts-types ; au-delà, la loi n'a pas été
    confrontée à l'historique. Extrapoler une distribution hors de son domaine de
    validation est exactement ce que la masse hors grille du football interdit."""
    resolution = resolve_model(
        winamax_sport_id=2, family=MarketFamily.TOTALS,
        context={"line": 183.5, "source_family_id": 2766})   # ligne WNBA réelle

    assert resolution.status is CapabilityStatus.MODEL_CONTEXT_MISMATCH


def test_une_ligne_entiere_est_refusee():
    """Le règlement d'une égalité exacte n'est pas démontré par la source."""
    resolution = resolve_model(
        winamax_sport_id=16, family=MarketFamily.TOTALS,
        context={"line": 44.0, "source_family_id": 2767})

    assert resolution.status is CapabilityStatus.MODEL_CONTEXT_MISMATCH


# ══ Le modèle : point-in-time, et rien d'autre ══════════════════════════════
def _corpus(n=120):
    """Un corpus synthétique où le domicile marque systématiquement plus."""
    debut = datetime(2025, 1, 1, tzinfo=timezone.utc)
    equipes = [f"t{i}" for i in range(8)]
    jeux = []
    for i in range(n):
        dom, ext = equipes[i % 8], equipes[(i + 3) % 8]
        jeux.append(ScoreGame(f"g{i}", debut + timedelta(days=i), dom, ext,
                              100 + (i % 7), 95 + (i % 5)))
    return jeux


_PARAMS = ScoreParams(baseline_points=100.0, k=0.05, home_edge=3.0,
                      min_prior_games=5, min_prior_residuals=20)


def test_aucune_prediction_avant_d_avoir_de_quoi_en_faire():
    """Sous le seuil d'historique, les notes valent encore leur initialisation :
    ce ne serait pas une prédiction faible, ce serait la valeur par défaut
    déguisée. Et sans dispersion mesurée, il n'y a pas de distribution du tout."""
    notes = SequentialScoreRatings(_PARAMS)
    assert notes.predict("t0", "t1") is None

    for game in _corpus(60):
        notes.update(game)
    assert notes.predict("t0", "t1") is not None


def test_la_dispersion_ne_vient_que_des_residus_anterieurs():
    """Un écart-type calculé sur des matchs postérieurs serait une fuite — et
    invisible, puisque la probabilité resterait plausible."""
    notes = SequentialScoreRatings(_PARAMS)
    jeux = _corpus(60)
    for game in jeux[:30]:
        notes.update(game)
    avant = notes.predict("t0", "t1")
    for game in jeux[30:]:
        notes.update(game)
    apres = notes.predict("t0", "t1")

    assert avant is not None and apres is not None
    assert avant.n_residuals == 30 and apres.n_residuals == 60


def test_le_walk_forward_ne_price_jamais_un_match_qu_il_a_deja_vu():
    """La prédiction précède la mise à jour, jamais l'inverse."""
    jeux = _corpus(120)
    cibles = cibles_total(lignes_autour(200, pas=5, combien=1))
    run = run_score_walk_forward(jeux, params=_PARAMS, targets=cibles, law="NORMAL")

    assert run.n_predicted < run.n_games          # le démarrage à froid est exclu
    assert run.n_predicted > 0
    for cible in cibles:
        assert len(run.runs[cible.key].predictions) == run.n_predicted


@pytest.mark.parametrize("loi", ["NORMAL", "POISSON", "NEGBIN"])
def test_chaque_loi_rend_une_partition(loi):
    jeux = _corpus(120)
    cibles = cibles_total(lignes_autour(200, pas=5, combien=1)) + cibles_marge([-2.5, 2.5])
    run = run_score_walk_forward(jeux, params=_PARAMS, targets=cibles, law=loi)

    for cible in cibles:
        for probs, _ in run.runs[cible.key].predictions:
            assert sum(probs.values()) == pytest.approx(1.0, abs=1e-9)
            assert all(0.0 <= p <= 1.0 for p in probs.values())


def test_les_lignes_ne_sont_jamais_dedoublonnees_en_double_cible():
    """Un pas inférieur au point faisait retomber deux échelons sur la même
    demi-ligne : deux cibles de même clé écrasaient leur run commun et la
    population évaluée doublait — un `n` de 16 338 sur 8 169 rencontres."""
    lignes = lignes_autour(9.0, pas=0.75, combien=3)

    assert len(lignes) == len(set(lignes))
    assert all(l % 1 == 0.5 for l in lignes)


# ══ Le pricer live : trois refus, chacun mesuré ═════════════════════════════
class _P:
    def __init__(self, role, cid):
        self.role, self.canonical_id = role, cid


class _Event:
    event_id = "event:american_football:nfl:2026:home=x|away=y"
    competition_id = "competition:american_football:usa:nfl"

    def __init__(self, home, away, competition=None):
        self.participants = (_P("home", home), _P("away", away))
        if competition:
            self.competition_id = competition


def test_le_baseball_s_abstient_avec_le_motif_du_stop_statistique():
    """Le refus doit être LISIBLE dans l'entonnoir. Ne pas brancher le pricer
    l'aurait confondu avec « ce sport n'intéresse personne »."""
    from src.agents.quant.betting_engine.sports.baseball.score_markets import STOP_STATISTIQUE

    prix = ScorePricer("baseball").price(
        event=_Event("a", "b"), family=MarketFamily.TOTALS,
        parameters={"line": 8.5, "source_family_id": 2768}, context={"point_in_time": _T})

    assert prix.status is PricingStatus.VALIDATION_REJECTED
    assert prix.abstention_reasons[0] == STOP_STATISTIQUE


def test_une_rencontre_d_un_autre_championnat_est_refusee():
    """Appliquer des notes NBA à une rencontre WNBA produirait une probabilité
    sur des équipes que le modèle n'a jamais vues."""
    prix = ScorePricer("basketball").price(
        event=_Event("team:basketball:usa:132", "team:basketball:usa:133",
                     competition="competition:basketball:usa:wnba"),
        family=MarketFamily.TOTALS,
        parameters={"line": 220.5, "source_family_id": 2766},
        context={"point_in_time": _T})

    assert prix.status is PricingStatus.MODEL_DOMAIN_MISMATCH
    assert "wnba" in prix.abstention_reasons[0]


def test_un_participant_absent_de_l_annuaire_est_refuse():
    """Le corpus indexe ses équipes par leur identifiant de source : lui
    présenter un identifiant canonique inconnu ne trouve rien, et le refus doit
    dire que c'est le PONT qui manque, pas l'équipe."""
    prix = ScorePricer("american_football").price(
        event=_Event("team:american_football:nfl:inexistante",
                     "team:american_football:nfl:14"),
        family=MarketFamily.TOTALS,
        parameters={"line": 44.5, "source_family_id": 2767},
        context={"point_in_time": _T})

    assert prix.status is PricingStatus.MODEL_DOMAIN_MISMATCH
    assert "annuaire" in prix.abstention_reasons[0]


def test_le_handicap_price_le_domicile_du_bon_cote():
    """`hcp = -7.5` veut dire « le domicile gagne de plus de 7,5 » : sa
    probabilité doit être INFÉRIEURE à celle de `hcp = +7.5`, qui ne lui demande
    que de perdre de moins de 7,5. Inverser le signe donnerait deux probabilités
    parfaitement plausibles et exactement contraires."""
    pricer = ScorePricer("american_football")
    event = _Event("team:american_football:nfl:14", "team:american_football:nfl:31")
    contexte = {"point_in_time": _T}

    exigeant = pricer.price(event=event, family=MarketFamily.HANDICAP,
                            parameters={"handicap": -7.5, "source_family_id": 3827},
                            context=contexte)
    genereux = pricer.price(event=event, family=MarketFamily.HANDICAP,
                            parameters={"handicap": 7.5, "source_family_id": 3827},
                            context=contexte)

    assert exigeant.priced and genereux.priced
    p_exigeant = next(s for s in exigeant.selections if s.selection == "home")
    p_genereux = next(s for s in genereux.selections if s.selection == "home")
    assert p_exigeant.fair_probability < p_genereux.fair_probability


def test_tous_les_marches_d_un_evenement_partagent_leur_origine():
    """78 lignes de handicap et 81 de total sortent de la MÊME loi : sans cette
    trace, le sizing les traiterait comme des paris indépendants."""
    pricer = ScorePricer("american_football")
    event = _Event("team:american_football:nfl:14", "team:american_football:nfl:31")
    contexte = {"point_in_time": _T}

    origines = set()
    for famille, params in ((MarketFamily.TOTALS, {"line": 44.5, "source_family_id": 2767}),
                            (MarketFamily.TOTALS, {"line": 47.5, "source_family_id": 2767}),
                            (MarketFamily.HANDICAP, {"handicap": -3.5,
                                                     "source_family_id": 3827})):
        prix = pricer.price(event=event, family=famille, parameters=params,
                            context=contexte)
        assert prix.priced, (famille, params)
        origines.add(prix.probability_origin)

    assert len(origines) == 1
