"""Un changement d'horaire ne crée pas une nouvelle rencontre.

L'identité canonique d'AXON porte le coup d'envoi. Winamax republie sans cesse
l'heure de départ en tennis, où un match commence quand le précédent libère le
court : une rencontre a été annoncée sous DOUZE horaires, sur 2 h 50. Chaque
republication fabriquait une rencontre neuve, et une décision prise sous
l'horaire de 18 h 00 ne pouvait plus s'apparier avec sa clôture prise sous 18 h 50.

Deux règles se croisent ici, et les confondre casse tout :

    classification historique  ≠  admissibilité à la preuve

Une cote relevée à 18 h 13 quand le départ était annoncé à 18 h 30 EST une
clôture — 17 minutes d'avance. Si le match glisse ensuite à 18 h 50, elle reste
une CLOSING dans le store, avec son horodatage et sa phase intacts ; elle cesse
seulement d'avoir le droit de PROUVER une maturité, parce qu'elle a cessé de
mesurer une ligne de clôture.

Le risque symétrique est la fusion abusive : deux rencontres réellement
distinctes ne doivent JAMAIS se confondre au prétexte que les participants sont
les mêmes. Les séries MLB — mêmes équipes deux soirs de suite — sont le cas qui
l'exige, et plusieurs tests ci-dessous ne servent qu'à l'interdire.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from src.agents.quant.betting_engine.clv.clv import clv_readiness
from src.agents.quant.betting_engine.clv.collect import FENETRE_CLOTURE
from src.agents.quant.betting_engine.clv.eligibility import (
    CLOSING_OUTSIDE_FINAL_SCHEDULE_WINDOW,
    CLOSING_POST_KICKOFF,
    ELIGIBLE,
    eligible,
    evaluate,
    exclusions,
)
from src.agents.quant.betting_engine.clv.identity import (
    historique_horaires,
    stable_event_id,
)
from src.agents.quant.betting_engine.clv.observation import (
    ObservationPhase,
    OddsObservation,
)

_JOUR = datetime(2026, 8, 8, tzinfo=timezone.utc)


def h(heure: str) -> datetime:
    """« 18:30 » -> l'instant correspondant du jour de référence."""
    hh, mm = (int(x) for x in heure.split(":"))
    return _JOUR + timedelta(hours=hh, minutes=mm)


def _obs(sid, kickoff, a, phase, cote=2.0, *, sport="tennis", competition="tour",
         protagonistes="player_a=a|player_b=b", selection="player_a",
         bookmaker="winamax"):
    """Une observation telle que le collecteur l'écrirait à l'instant `a`.

    `kickoff` est le départ ANNONCÉ à cet instant : il entre dans l'identité
    canonique, exactement comme en production.
    """
    return OddsObservation(
        event_id=f"event:{sport}:{competition}:{kickoff:%Y-%m-%dT%H:%M:%S}Z:{protagonistes}",
        market_type="MATCH_WINNER", selection=selection, bookmaker=bookmaker,
        decimal_odds=Decimal(str(cote)), observed_at=a, phase=phase,
        source="synthetic", source_event_id=sid, run_id=None)


def _raison(observation, lot):
    return evaluate(observation, historique_horaires(lot)).raison


# ══ §1 — l'identité survit au report ═══════════════════════════════════════════
def test_l_identite_stable_survit_a_un_report():
    tot = _obs("W1", h("18:30"), h("16:00"), ObservationPhase.DECISION)
    tard = _obs("W1", h("18:50"), h("18:32"), ObservationPhase.CLOSING)

    assert tot.event_id != tard.event_id            # l'identité canonique a bougé
    assert tot.stable_event_id == tard.stable_event_id


def test_l_identite_stable_survit_a_douze_reports():
    """Le cas réel : douze horaires annoncés pour une même rencontre."""
    lot = [_obs("W1", h("17:40") + timedelta(minutes=10 * i),
                h("17:00") + timedelta(minutes=10 * i), ObservationPhase.DECISION)
           for i in range(12)]

    assert len({o.event_id for o in lot}) == 12
    assert len({o.stable_event_id for o in lot}) == 1


def test_sans_identifiant_bookmaker_le_comportement_est_inchange():
    """Repli explicite : sans preuve de stabilité, l'ancienne identité fait foi."""
    sans = OddsObservation(
        event_id="event:test:e1", market_type="MATCH_WINNER", selection="home",
        bookmaker="winamax", decimal_odds=Decimal("2.0"), observed_at=h("12:00"),
        phase=ObservationPhase.DECISION, source="synthetic")

    assert stable_event_id(sans) == sans.event_id


def test_un_changement_d_identifiant_bookmaker_ne_fusionne_pas():
    """Si Winamax change d'identifiant, on obtient deux rencontres — jamais une
    fusion devinée. Perdre une paire est réparable ; en inventer une, non."""
    a = _obs("W1", h("18:30"), h("16:00"), ObservationPhase.DECISION)
    b = _obs("W2", h("18:30"), h("18:20"), ObservationPhase.CLOSING)

    assert a.stable_event_id != b.stable_event_id
    assert clv_readiness([a, b]).n_events == 0


# ══ §3/§8 — la clôture d'avant report reste au store, mais ne prouve plus ══════
def test_la_cloture_d_avant_report_reste_une_cloture_dans_le_store():
    """Le cas nommé au §8 : honnête à 18 h 13, dépassée à 18 h 50."""
    tot = _obs("W1", h("18:30"), h("18:13"), ObservationPhase.CLOSING)
    tard = _obs("W1", h("18:50"), h("18:32"), ObservationPhase.CLOSING)

    assert tot.phase is ObservationPhase.CLOSING              # jamais reclassée
    assert tot.observed_at == h("18:13")                      # jamais réhorodatée
    assert tot.scheduled_kickoff_as_observed == h("18:30")    # point-in-time intact
    assert evaluate(tot).raison == ELIGIBLE                   # honnête à l'instant T


def test_mais_elle_devient_inadmissible_a_la_preuve():
    tot = _obs("W1", h("18:30"), h("18:13"), ObservationPhase.CLOSING)
    tard = _obs("W1", h("18:50"), h("18:32"), ObservationPhase.CLOSING)

    assert _raison(tot, [tot, tard]) == CLOSING_OUTSIDE_FINAL_SCHEDULE_WINDOW


def test_et_la_vraie_cloture_d_apres_report_devient_admissible():
    tot = _obs("W1", h("18:30"), h("18:13"), ObservationPhase.CLOSING)
    tard = _obs("W1", h("18:50"), h("18:32"), ObservationPhase.CLOSING)

    assert _raison(tard, [tot, tard]) == ELIGIBLE


def test_le_motif_de_derive_est_distinct_du_legacy():
    """Les deux exclusions ne se corrigent pas de la même façon : les confondre
    enverrait attendre le temps qui passe au lieu de capturer plus tard."""
    tot = _obs("W1", h("18:30"), h("18:13"), ObservationPhase.CLOSING)
    tard = _obs("W1", h("18:50"), h("18:32"), ObservationPhase.CLOSING)

    assert exclusions([tot, tard]) == {CLOSING_OUTSIDE_FINAL_SCHEDULE_WINDOW: 1}


def test_reports_repetes_ne_laissent_admissible_que_la_derniere_cloture():
    lot = [_obs("W1", h("18:30"), h("18:13"), ObservationPhase.CLOSING),
           _obs("W1", h("18:50"), h("18:33"), ObservationPhase.CLOSING),
           _obs("W1", h("19:10"), h("18:53"), ObservationPhase.CLOSING)]

    assert [_raison(o, lot) for o in lot] == [
        CLOSING_OUTSIDE_FINAL_SCHEDULE_WINDOW,
        CLOSING_OUTSIDE_FINAL_SCHEDULE_WINDOW,
        ELIGIBLE,
    ]


def test_un_report_au_lendemain_disqualifie_la_cloture_de_la_veille():
    """Cas réel mesuré : une « clôture » relevée 20 heures avant le départ."""
    veille = _obs("W1", h("18:00"), h("17:33"), ObservationPhase.CLOSING)
    lendemain = _obs("W1", _JOUR + timedelta(days=1, hours=14),
                     h("17:40"), ObservationPhase.CLOSING)

    assert _raison(veille, [veille, lendemain]) == CLOSING_OUTSIDE_FINAL_SCHEDULE_WINDOW


def test_un_horaire_avance_est_lu_dans_l_ordre_d_annonce_pas_au_maximum():
    """Un match peut aussi être AVANCÉ. « Le dernier coup d'envoi connu » est
    alors celui annoncé en dernier — 18 h 40 — et non le plus tardif des horaires
    vus — 19 h 00. Prendre le maximum ferait passer pour valable une cote relevée
    après le départ réel."""
    tot = _obs("W1", h("19:00"), h("17:00"), ObservationPhase.DECISION)
    avance = _obs("W1", h("18:40"), h("18:00"), ObservationPhase.DECISION)

    calendrier = historique_horaires([tot, avance])
    identite = tot.stable_event_id

    assert calendrier.horaires(identite) == (h("19:00"), h("18:40"))   # ordre d'annonce
    assert calendrier.dernier(identite) == h("18:40")                  # jamais le maximum


def test_le_minorant_strict_refuse_une_cloture_posterieure_au_depart_final():
    """Garde DÉFENSIVE, et je la nomme comme telle : le collecteur refuse déjà
    d'écrire après le coup d'envoi annoncé, si bien qu'une clôture postérieure à
    un départ AVANCÉ n'est pas atteignable avec son comportement actuel. La règle
    « 0 < avance » ne coûte rien et couvre le jour où ce ne serait plus vrai."""
    calendrier = historique_horaires(
        [_obs("W1", h("18:40"), h("18:00"), ObservationPhase.DECISION)])
    perimee = _obs("W1", h("19:00"), h("18:45"), ObservationPhase.CLOSING)

    verdict = evaluate(perimee, calendrier)

    assert verdict.lead_time == timedelta(minutes=15)        # honnête à l'instant T
    assert verdict.raison == CLOSING_OUTSIDE_FINAL_SCHEDULE_WINDOW


def test_aucune_cloture_posterieure_au_coup_d_envoi_n_est_jamais_admise():
    """Refus déjà porté par la classification point-in-time : il reste prioritaire,
    pour que le motif rendu nomme la faute la plus ancienne."""
    tardive = _obs("W1", h("18:30"), h("18:35"), ObservationPhase.CLOSING)

    assert _raison(tardive, [tardive]) == CLOSING_POST_KICKOFF


def test_un_horaire_inchange_laisse_la_cloture_admissible():
    """Garde-fou : le nouveau verdict ne doit rien exclure quand rien ne bouge."""
    lot = [_obs("W1", h("18:30"), h("18:05"), ObservationPhase.CLOSING),
           _obs("W1", h("18:30"), h("18:15"), ObservationPhase.CLOSING)]

    assert [_raison(o, lot) for o in lot] == [ELIGIBLE, ELIGIBLE]


def test_la_fenetre_de_cloture_n_est_pas_modifiee():
    """La mission change la RÉFÉRENCE, jamais la largeur de la fenêtre."""
    pile = _obs("W1", h("18:30"), h("18:30") - FENETRE_CLOTURE, ObservationPhase.CLOSING)
    juste_avant = _obs("W1", h("18:30"),
                       h("18:30") - FENETRE_CLOTURE - timedelta(minutes=1),
                       ObservationPhase.CLOSING)

    assert _raison(pile, [pile]) == ELIGIBLE
    assert _raison(juste_avant, [juste_avant]) != ELIGIBLE


# ══ §6 — appariement à travers le report ═══════════════════════════════════════
def test_la_decision_s_apparie_avec_la_cloture_d_apres_report():
    """Le gain de la mission : ces deux observations portent des horaires
    différents et appartiennent pourtant à la même rencontre."""
    lot = [_obs("W1", h("18:30"), h("16:00"), ObservationPhase.DECISION, 2.10),
           _obs("W1", h("18:50"), h("18:32"), ObservationPhase.CLOSING, 2.00)]

    lecture = clv_readiness(eligible(lot))

    assert lecture.n_complete_pairs == 1 and lecture.n_events == 1
    assert lecture.mean_clv == pytest.approx(Decimal("0.05"), abs=1e-9)


def test_la_paire_retient_la_derniere_cloture_admissible():
    """Une ligne de clôture est le DERNIER prix avant fermeture. Retenir la
    première mesurerait la dérive du marché, pas la valeur de clôture."""
    lot = [_obs("W1", h("18:30"), h("16:00"), ObservationPhase.DECISION, 2.20),
           _obs("W1", h("18:50"), h("18:32"), ObservationPhase.CLOSING, 2.00),
           _obs("W1", h("18:50"), h("18:45"), ObservationPhase.CLOSING, 1.10)]

    # 2.20 / 1.10 - 1 = 1.0 -> c'est bien la clôture de 18:45 qui a servi.
    assert clv_readiness(eligible(lot)).mean_clv == pytest.approx(Decimal("1.0"), abs=1e-9)


def test_la_maturite_ne_compte_que_les_paires_admissibles():
    """Sans filtre, la clôture périmée forme une paire ; avec, elle disparaît."""
    lot = [_obs("W1", h("18:30"), h("16:00"), ObservationPhase.DECISION),
           _obs("W1", h("18:30"), h("18:13"), ObservationPhase.CLOSING),
           _obs("W1", h("18:50"), h("18:52"), ObservationPhase.CLOSING)]  # post-départ

    assert clv_readiness(lot).n_events == 1              # lecture brute
    assert clv_readiness(eligible(lot)).n_events == 0    # preuve de maturité


# ══ §10 — jamais de fusion de deux rencontres réellement distinctes ════════════
def test_une_serie_mlb_ne_fusionne_jamais():
    """Mêmes équipes, deux soirs de suite, deux identifiants Winamax : ce sont
    deux rencontres. Un rapprochement par participants les aurait fusionnées."""
    protagonistes = "away=3|home=25"
    soir1 = [_obs("B1", h("23:05"), h("20:00"), ObservationPhase.DECISION, 2.10,
                  sport="baseball", competition="mlb", protagonistes=protagonistes,
                  selection="home"),
             _obs("B1", h("23:05"), h("22:50"), ObservationPhase.CLOSING, 2.00,
                  sport="baseball", competition="mlb", protagonistes=protagonistes,
                  selection="home")]
    demain = _JOUR + timedelta(days=1, hours=23, minutes=5)
    soir2 = [_obs("B2", demain, demain - timedelta(hours=3), ObservationPhase.DECISION,
                  2.10, sport="baseball", competition="mlb",
                  protagonistes=protagonistes, selection="home"),
             _obs("B2", demain, demain - timedelta(minutes=15), ObservationPhase.CLOSING,
                  2.00, sport="baseball", competition="mlb",
                  protagonistes=protagonistes, selection="home")]

    lecture = clv_readiness(eligible(soir1 + soir2))

    assert lecture.n_events == 2      # deux rencontres, jamais une


def test_un_meme_affiche_de_football_a_deux_dates_reste_deux_rencontres():
    protagonistes = "home=psg|away=om"
    aller = [_obs("F1", h("19:00"), h("16:00"), ObservationPhase.DECISION, 2.10,
                  sport="football", competition="fra", protagonistes=protagonistes,
                  selection="home"),
             _obs("F1", h("19:00"), h("18:45"), ObservationPhase.CLOSING, 2.00,
                  sport="football", competition="fra", protagonistes=protagonistes,
                  selection="home")]
    plus_tard = _JOUR + timedelta(days=120, hours=19)
    retour = [_obs("F2", plus_tard, plus_tard - timedelta(hours=3),
                   ObservationPhase.DECISION, 2.10, sport="football",
                   competition="fra", protagonistes=protagonistes, selection="home"),
              _obs("F2", plus_tard, plus_tard - timedelta(minutes=15),
                   ObservationPhase.CLOSING, 2.00, sport="football",
                   competition="fra", protagonistes=protagonistes, selection="home")]

    assert clv_readiness(eligible(aller + retour)).n_events == 2


def test_un_sport_sans_report_se_comporte_exactement_comme_avant():
    """Non-régression : sans replanification, le nouveau verdict n'exclut rien et
    l'identité stable regroupe exactement ce que l'ancienne regroupait."""
    lot = [_obs("F1", h("19:00"), h("16:00"), ObservationPhase.DECISION, 2.10,
                sport="football", competition="fra", protagonistes="home=a|away=b",
                selection="home"),
           _obs("F1", h("19:00"), h("18:45"), ObservationPhase.CLOSING, 2.00,
                sport="football", competition="fra", protagonistes="home=a|away=b",
                selection="home")]

    assert exclusions(lot) == {}
    assert len(eligible(lot)) == len(lot)
    assert clv_readiness(eligible(lot)).n_events == 1


# ══ §12 — l'historique n'est jamais touché ═════════════════════════════════════
def test_le_filtre_ne_mute_ni_la_liste_ni_les_observations():
    lot = [_obs("W1", h("18:30"), h("18:13"), ObservationPhase.CLOSING),
           _obs("W1", h("18:50"), h("18:32"), ObservationPhase.CLOSING)]
    empreinte = [(o.event_id, o.observed_at, o.phase, o.decimal_odds,
                  o.source_event_id) for o in lot]
    copie = list(lot)

    retenues = eligible(lot)

    assert lot == copie
    assert [(o.event_id, o.observed_at, o.phase, o.decimal_odds,
             o.source_event_id) for o in lot] == empreinte
    assert all(any(r is o for o in lot) for r in retenues)   # les mêmes objets


def test_le_calendrier_est_reconstruit_jamais_stocke():
    """Aucun champ nouveau dans le store : le format sur disque est inchangé."""
    import dataclasses

    champs = {f.name for f in dataclasses.fields(OddsObservation)}

    assert "scheduled_kickoff" not in champs
    assert "stable_event_id" not in champs
    assert champs == {"event_id", "market_type", "selection", "bookmaker",
                      "decimal_odds", "observed_at", "phase", "source",
                      "source_event_id", "run_id"}


def test_l_ordre_des_observations_ne_change_aucun_verdict():
    """Déterminisme : le calendrier se trie sur l'instant d'annonce, pas sur
    l'ordre d'arrivée dans la liste."""
    lot = [_obs("W1", h("18:30"), h("18:13"), ObservationPhase.CLOSING),
           _obs("W1", h("18:50"), h("18:32"), ObservationPhase.CLOSING),
           _obs("W1", h("18:30"), h("16:00"), ObservationPhase.DECISION)]

    direct = clv_readiness(eligible(lot))
    inverse = clv_readiness(eligible(list(reversed(lot))))

    assert direct.n_events == inverse.n_events
    assert direct.mean_clv == inverse.mean_clv
    assert direct.clv_lower_bound == inverse.clv_lower_bound


# ══ §2 — chaque observation reste auditable ════════════════════════════════════
def test_chaque_observation_expose_son_horaire_tel_qu_observe():
    o = _obs("W1", h("18:30"), h("18:13"), ObservationPhase.CLOSING)

    assert o.observed_at == h("18:13")
    assert o.scheduled_kickoff_as_observed == h("18:30")
    assert evaluate(o).lead_time == timedelta(minutes=17)


def test_la_sequence_des_horaires_annonces_est_reconstructible():
    lot = [_obs("W1", h("18:30"), h("17:00"), ObservationPhase.DECISION),
           _obs("W1", h("18:50"), h("18:00"), ObservationPhase.DECISION),
           _obs("W1", h("19:10"), h("18:40"), ObservationPhase.CLOSING)]

    calendrier = historique_horaires(lot)
    identite = lot[0].stable_event_id

    assert calendrier.horaires(identite) == (h("18:30"), h("18:50"), h("19:10"))
    assert calendrier.dernier(identite) == h("19:10")
    assert calendrier.replanifiee(identite)


def test_la_derive_est_chiffree_dans_le_verdict():
    """Un refus doit être auditable : de combien la clôture a-t-elle raté ?"""
    tot = _obs("W1", h("18:30"), h("18:13"), ObservationPhase.CLOSING)
    tard = _obs("W1", h("18:50"), h("18:32"), ObservationPhase.CLOSING)

    verdict = evaluate(tot, historique_horaires([tot, tard]))

    assert verdict.lead_time == timedelta(minutes=17)          # ce qu'elle croyait
    assert verdict.lead_time_final == timedelta(minutes=37)    # ce qu'il en était


# ══ Les deux clés ne doivent surtout pas fusionner ═════════════════════════════
def test_l_idempotence_du_collecteur_reste_sensible_a_l_horaire():
    """Si `market_key` devenait insensible à l'horaire, le collecteur prendrait la
    vraie clôture d'après-report pour un doublon déjà connu et ne l'écrirait
    jamais — la correction se saborderait elle-même."""
    avant = _obs("W1", h("18:30"), h("18:13"), ObservationPhase.CLOSING)
    apres = _obs("W1", h("18:50"), h("18:32"), ObservationPhase.CLOSING)

    assert avant.market_key != apres.market_key           # capture possible
    assert avant.stable_market_key == apres.stable_market_key   # appariement possible


def test_un_calendrier_ampute_ne_reouvre_pas_une_cloture_perimee():
    """Le seul mauvais sens du filtre : réadmettre. Un appelant qui filtre avant
    d'appeler doit passer le calendrier complet, sans quoi le dernier report
    manquerait et la clôture périmée redeviendrait admissible."""
    perimee = _obs("W1", h("18:30"), h("18:13"), ObservationPhase.CLOSING)
    apres_report = _obs("W1", h("18:50"), h("18:32"), ObservationPhase.CLOSING)
    complet = historique_horaires([perimee, apres_report])

    # L'appelant ne transmet que la clôture périmée, mais avec le calendrier complet.
    assert eligible([perimee]) == [perimee]                 # assiette amputée : réadmise
    assert eligible([perimee], complet) == []               # calendrier complet : refusée


def test_la_maturite_construit_son_calendrier_avant_le_routage(monkeypatch):
    """Garde-fou de bout en bout : `readiness` route les observations par modèle,
    donc son assiette est amputée. Le calendrier doit être bâti AVANT ce routage.

    La preuve est comportementale, pas textuelle : on vérifie que le calendrier
    reçu connaît une rencontre que le routage a écartée.
    """
    from src.agents.quant.betting_engine import readiness_cli
    from src.agents.quant.betting_engine.clv import eligibility as module_eligibilite
    from src.agents.quant.betting_engine.clv import store as module_store

    tennis = _obs("W1", h("18:30"), h("16:00"), ObservationPhase.DECISION)
    foot = _obs("F1", h("19:00"), h("16:00"), ObservationPhase.DECISION,
                sport="football", competition="fra",
                protagonistes="home=a|away=b", selection="home")

    class _StoreFactice:
        def all(self):
            return [tennis, foot]

    recu: dict = {}

    def _eligible_espion(observations, calendrier=None):
        recu["calendrier"] = calendrier
        return list(observations)

    monkeypatch.setattr(module_store, "JsonlOddsHistoryStore", _StoreFactice)
    monkeypatch.setattr(module_eligibilite, "eligible", _eligible_espion)

    readiness_cli.observations_collectees("atp")

    calendrier = recu.get("calendrier")
    assert calendrier is not None, "aucun calendrier transmis au filtre"
    # Le football est hors du modèle « atp » : le routage l'a écarté. Le calendrier
    # le connaît malgré tout — il a donc été bâti sur l'historique complet.
    assert calendrier.dernier(foot.stable_event_id) == h("19:00")


def test_le_collecteur_n_utilise_pas_la_cle_stable_pour_son_idempotence():
    import inspect

    from src.agents.quant.betting_engine.clv import collect

    source = inspect.getsource(collect)

    assert "stable_market_key" not in source
    assert "market_key" in source
