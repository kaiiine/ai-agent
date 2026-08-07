"""Collecte odds_history OPÉRATIONNELLE (BE-FR-015) : scan/replay -> OddsObservation
-> store -> CLV mesurable. Hermétique. Prouve que le temps qui passe (DECISION puis
CLOSING) produit les paires dont la CLV a besoin, avec une provenance honnête et
Decimal préservé. Aucune donnée fabriquée : les cotes proviennent d'une capture,
marquée SYNTHÉTIQUE (jamais présentée comme réelle).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from src.agents.quant.betting_engine.bookmakers.bookmaker_registry import BookmakerEventResolver
from src.agents.quant.betting_engine.bookmakers.winamax.record_replay import synthetic_capture
from src.agents.quant.betting_engine.clv import (
    JsonlOddsHistoryStore,
    MEASURABLE,
    NOT_YET_MEASURABLE,
    ObservationPhase,
    clv_readiness,
    record_from_capture,
)
from src.agents.quant.gateway.core.identity_resolver import CanonicalEntity, IdentityResolver

_KO_EPOCH = 1772359200          # 2026-03-01T18:00:00Z


def _resolver():
    identity = IdentityResolver([
        CanonicalEntity("team:football:fra:psg", "Paris Saint Germain",
                        ["PSG", "Paris SG", "Paris Saint-Germain"], {}),
        CanonicalEntity("team:football:fra:marseille", "Marseille",
                        ["OM", "Olympique de Marseille"], {})])
    comp = lambda ev: (("competition:football:fra:ligue1", "RESOLVED", "competition_table")
                        if ev.raw_tournament_id == "4" else (None, "UNRESOLVED", "none"))
    return BookmakerEventResolver(identity, competition_resolver=comp)


def _fl1_state(*, home_odds):
    """PRELOADED_STATE synthétique fidèle (PSG vs OM, Ligue 1). L'instant d'observation
    des cotes est fixé au REPLAY (`now`), pas dans l'état."""
    return {
        "matches": {"77001": {
            "sportId": 1, "tournamentId": 4, "isOutright": False,
            "competitor1Id": 1301, "competitor1Name": "Paris Saint-Germain",
            "competitor2Id": 1302, "competitor2Name": "Marseille",
            "matchStart": _KO_EPOCH, "status": "PREMATCH"}},
        "bets": {"9001": {"matchId": 77001, "betType": 1, "betTypeName": "Résultat",
                          "template": "3way", "betTypeIsLive": False, "outcomes": [501, 502, 503]}},
        "outcomes": {"501": {"code": "1", "label": "PSG"},
                     "502": {"code": "x", "label": "Nul"},
                     "503": {"code": "2", "label": "OM"}},
        "odds": {"501": home_odds, "502": 4.30, "503": 6.10},
        "tournaments": {"4": {"tournamentName": "Ligue 1"}},
    }


def _capture(*, home_odds):
    return synthetic_capture(_fl1_state(home_odds=home_odds), "football")


def test_recording_a_scan_persists_canonical_observations(tmp_path):
    store = JsonlOddsHistoryStore(tmp_path / "odds.jsonl")
    t0 = datetime(2026, 3, 1, 10, 0, tzinfo=timezone.utc)
    summary = record_from_capture(
        _capture(home_odds=2.10), event_resolver=_resolver(), store=store,
        phase=ObservationPhase.DECISION, run_id="run-decision", now=t0)
    assert summary.events_recorded == 1
    assert summary.observations_written == 3            # home/draw/away
    obs = store.all()
    assert {o.selection for o in obs} == {"home", "draw", "away"}
    home = next(o for o in obs if o.selection == "home")
    assert home.decimal_odds == Decimal("2.1") and isinstance(home.decimal_odds, Decimal)
    assert home.source == "synthetic"                   # provenance honnête, jamais "réel"
    assert home.event_id.startswith("event:")           # identité canonique


def test_decision_then_closing_makes_clv_measurable(tmp_path):
    store = JsonlOddsHistoryStore(tmp_path / "odds.jsonl")
    resolver = _resolver()
    # Le coup d'envoi de la fixture est à 10:00 UTC. La CLÔTURE doit le PRÉCÉDER :
    # ce test enregistrait sa « clôture » à 17:30, soit sept heures et demie APRÈS
    # le début du match. Ce qu'il appariait n'était pas une ligne de clôture mais
    # une cote de direct, qui intègre le score — et la CLV en sortait mesurable.
    t_decision = datetime(2026, 2, 28, 10, 0, tzinfo=timezone.utc)   # la veille
    t_closing = datetime(2026, 3, 1, 9, 55, tzinfo=timezone.utc)     # 5 min avant

    # Avant toute collecte : CLV non mesurable.
    assert clv_readiness(store.all()).status == NOT_YET_MEASURABLE

    record_from_capture(_capture(home_odds=2.10), event_resolver=resolver,
                        store=store, phase=ObservationPhase.DECISION, now=t_decision)
    # Décision seule : toujours non mesurable (pas de clôture).
    assert clv_readiness(store.all()).status == NOT_YET_MEASURABLE

    record_from_capture(_capture(home_odds=1.90), event_resolver=resolver,
                        store=store, phase=ObservationPhase.CLOSING, now=t_closing)
    readiness = clv_readiness(store.all())
    assert readiness.status == MEASURABLE                # la paire décision/clôture existe
    assert readiness.n_complete_pairs == 3               # home/draw/away appariés
    assert readiness.mean_clv is not None                # valeur réelle, jamais None->0


def _nba_resolver():
    identity = IdentityResolver([
        CanonicalEntity("team:basketball:usa:celtics", "Boston Celtics", ["Celtics"], {}),
        CanonicalEntity("team:basketball:usa:lakers", "Los Angeles Lakers", ["LA Lakers"], {})])
    comp = lambda ev: (("competition:basketball:usa:nba", "RESOLVED", "competition_table")
                        if ev.raw_tournament_id == "55" else (None, "UNRESOLVED", "none"))
    return BookmakerEventResolver(identity, competition_resolver=comp)


def _nba_state(*, home_odds):
    return {
        "matches": {"88001": {
            "sportId": 2, "tournamentId": 55, "isOutright": False,
            "competitor1Id": 2001, "competitor1Name": "Boston Celtics",
            "competitor2Id": 2002, "competitor2Name": "Los Angeles Lakers",
            "matchStart": _KO_EPOCH, "status": "PREMATCH"}},
        "bets": {"9002": {"matchId": 88001, "betType": 1, "betTypeName": "Vainqueur",
                          "template": "2way", "betTypeIsLive": False, "outcomes": [601, 602]}},
        "outcomes": {"601": {"code": "1", "label": "BOS"}, "602": {"code": "2", "label": "LAL"}},
        "odds": {"601": home_odds, "602": 2.10},
        "tournaments": {"55": {"tournamentName": "NBA"}}}


def test_multisport_records_two_way_sport(tmp_path):
    # §2 : la collecte CLV n'est plus football-only — un sport 2-way (basket) est enregistré.
    store = JsonlOddsHistoryStore(tmp_path / "odds.jsonl")
    # Coup d'envoi de la fixture : 10:00 UTC. La décision le précède, la clôture aussi.
    t0 = datetime(2026, 2, 28, 10, tzinfo=timezone.utc)
    cap = synthetic_capture(_nba_state(home_odds=1.80), "basketball")
    summary = record_from_capture(cap, event_resolver=_nba_resolver(), store=store,
                                  phase=ObservationPhase.DECISION, now=t0)
    assert summary.events_recorded == 1
    assert summary.observations_written == 2            # home/away, PAS de nul (2-way)
    assert {o.selection for o in store.all()} == {"home", "away"}
    # DECISION puis CLOSING -> CLV mesurable, comme le football.
    record_from_capture(synthetic_capture(_nba_state(home_odds=1.60), "basketball"),
                        event_resolver=_nba_resolver(), store=store,
                        phase=ObservationPhase.CLOSING,
                        now=datetime(2026, 3, 1, 9, 55, tzinfo=timezone.utc))
    r = clv_readiness(store.all())
    assert r.status == MEASURABLE and r.n_complete_pairs == 2


def test_unresolved_events_are_skipped_never_fabricated(tmp_path):
    store = JsonlOddsHistoryStore(tmp_path / "odds.jsonl")
    t0 = datetime(2026, 3, 1, 10, 0, tzinfo=timezone.utc)
    # Résolveur qui ne résout AUCUNE équipe -> événement ignoré, rien fabriqué.
    empty = BookmakerEventResolver(IdentityResolver([]),
                                   competition_resolver=lambda ev: (None, "UNRESOLVED", "none"))
    summary = record_from_capture(_capture(home_odds=2.10), event_resolver=empty,
                                  store=store, phase=ObservationPhase.DECISION, now=t0)
    assert summary.observations_written == 0 and summary.events_skipped == 1
    assert store.all() == []


# ══ §10 — Une CLÔTURE ne peut pas être une cote de direct ═══════════════════
# La phase était choisie par un drapeau de ligne de commande, sans aucun garde.
# Un planificateur réglé une heure trop tard aurait rempli l'historique de cotes
# de direct étiquetées « clôture », et rien ne l'aurait signalé : le calcul de
# CLV apparie sans discuter deux observations bien formées. Les tests eux-mêmes
# enregistraient leur clôture sept heures après le coup d'envoi.
_COUP_ENVOI = datetime(2026, 3, 1, 10, 0, tzinfo=timezone.utc)


def _etat(*, home_odds, statut="PREMATCH", debut=None):
    etat = _fl1_state(home_odds=home_odds)
    etat["matches"]["77001"]["status"] = statut
    if debut is not None:
        etat["matches"]["77001"]["matchStart"] = int(debut.timestamp())
    return etat


def _enregistrer_cloture(tmp_path, *, quand, statut="PREMATCH", debut=None):
    store = JsonlOddsHistoryStore(tmp_path / "odds.jsonl")
    resume = record_from_capture(
        synthetic_capture(_etat(home_odds=1.90, statut=statut, debut=debut), "football"),
        event_resolver=_resolver(), store=store,
        phase=ObservationPhase.CLOSING, now=quand)
    return resume, store


def test_une_cloture_avant_le_coup_d_envoi_est_enregistree(tmp_path):
    resume, store = _enregistrer_cloture(tmp_path, quand=_COUP_ENVOI - timedelta(minutes=5))

    assert resume.events_recorded == 1 and resume.events_started == 0
    assert len(store.all()) == 3


def test_une_cloture_apres_le_coup_d_envoi_est_refusee(tmp_path):
    """Le cas exact que le produit laissait passer."""
    resume, store = _enregistrer_cloture(tmp_path, quand=_COUP_ENVOI + timedelta(hours=7))

    assert resume.events_recorded == 0
    assert resume.events_started == 1        # compté, jamais silencieux
    assert store.all() == []


def test_un_evenement_en_direct_est_refuse_meme_avant_l_horaire_annonce(tmp_path):
    """Un match retardé démarre parfois avant que l'horaire annoncé soit corrigé.
    Le statut du bookmaker prime : `LIVE` veut dire que le jeu a commencé."""
    resume, _ = _enregistrer_cloture(
        tmp_path, quand=_COUP_ENVOI - timedelta(minutes=5), statut="LIVE")

    assert resume.events_recorded == 0 and resume.events_started == 1


def test_un_evenement_sans_horaire_ne_peut_pas_cloturer(tmp_path):
    """Sans horaire, rien ne permet d'affirmer que le match n'a pas commencé.
    Le doute ne produit pas une observation — il produit un refus compté."""
    store = JsonlOddsHistoryStore(tmp_path / "odds.jsonl")
    etat = _fl1_state(home_odds=1.90)
    etat["matches"]["77001"].pop("matchStart")
    resume = record_from_capture(
        synthetic_capture(etat, "football"), event_resolver=_resolver(), store=store,
        phase=ObservationPhase.CLOSING, now=_COUP_ENVOI - timedelta(minutes=5))

    assert resume.observations_written == 0
    assert store.all() == []


def test_un_match_reporte_plus_tard_reste_cloturable(tmp_path):
    """Un report DÉPLACE le coup d'envoi ; il ne l'annule pas. La clôture reste
    possible tant que le nouveau départ n'est pas atteint."""
    reporte = _COUP_ENVOI + timedelta(days=1)
    resume, store = _enregistrer_cloture(
        tmp_path, quand=_COUP_ENVOI + timedelta(hours=2), debut=reporte)

    assert resume.events_recorded == 1 and len(store.all()) == 3


def test_la_phase_decision_n_est_pas_bornee_par_le_coup_d_envoi(tmp_path):
    """Le garde ne vise QUE la clôture. Une décision est datée par l'utilisateur
    qui l'a prise ; la contraindre ici reviendrait à réécrire son historique."""
    store = JsonlOddsHistoryStore(tmp_path / "odds.jsonl")
    resume = record_from_capture(
        _capture(home_odds=2.10), event_resolver=_resolver(), store=store,
        phase=ObservationPhase.DECISION, now=_COUP_ENVOI + timedelta(hours=7))

    assert resume.events_recorded == 1


def test_aucune_paire_n_est_fabriquee_quand_la_cloture_est_refusee(tmp_path):
    """Bout en bout : une décision valide plus une clôture trop tardive ne
    produisent PAS une CLV. C'est le résultat qui compte — une paire fabriquée
    aurait fait avancer un critère de maturité sur une mesure fausse."""
    store = JsonlOddsHistoryStore(tmp_path / "odds.jsonl")
    record_from_capture(_capture(home_odds=2.10), event_resolver=_resolver(),
                        store=store, phase=ObservationPhase.DECISION,
                        now=_COUP_ENVOI - timedelta(days=1))
    record_from_capture(_capture(home_odds=1.90), event_resolver=_resolver(),
                        store=store, phase=ObservationPhase.CLOSING,
                        now=_COUP_ENVOI + timedelta(hours=7))

    assert clv_readiness(store.all()).status == NOT_YET_MEASURABLE


def test_plusieurs_clotures_proches_du_coup_d_envoi_ne_gonflent_pas_l_echantillon(tmp_path):
    """Un planificateur qui rescanne toutes les cinq minutes ne crée pas cinq
    observations indépendantes : l'appariement retient UNE paire par marché."""
    store = JsonlOddsHistoryStore(tmp_path / "odds.jsonl")
    record_from_capture(_capture(home_odds=2.10), event_resolver=_resolver(),
                        store=store, phase=ObservationPhase.DECISION,
                        now=_COUP_ENVOI - timedelta(days=1))
    for minutes in (20, 15, 10, 5):
        record_from_capture(_capture(home_odds=1.90), event_resolver=_resolver(),
                            store=store, phase=ObservationPhase.CLOSING,
                            now=_COUP_ENVOI - timedelta(minutes=minutes))

    lecture = clv_readiness(store.all())

    assert lecture.status == MEASURABLE
    assert lecture.n_complete_pairs == 3      # home/draw/away, une paire chacun
    assert lecture.n_events == 1              # UNE rencontre, pas quatre
