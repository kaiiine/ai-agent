"""record-odds RÉELLEMENT multisport, pour les SEPT sports — hermétique.

La CLV est le dernier bloqueur commun aux quatorze modèles. Ce fichier répond à
une question d'exploitation, pas d'architecture : pour chaque sport, la chaîne
DÉCISION -> CLÔTURE -> paire fonctionne-t-elle réellement ?

Trois sports y étaient couverts, deux autres ailleurs, et deux — hockey et
tennis — n'étaient prouvés nulle part alors que l'historique réel contient déjà
leurs décisions. Ils y sont désormais, avec leurs deux formes de marché
particulières : le hockey settle en 3-way sur le temps réglementaire, le tennis
oppose `player_a`/`player_b` et non `home`/`away`.

Aucune cote fabriquée : elles viennent d'une capture marquée SYNTHÉTIQUE.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.agents.quant.gateway.core.identity_resolver import IdentityResolver
from src.agents.quant.betting_engine.bookmakers.bookmaker_registry import BookmakerEventResolver
from src.agents.quant.betting_engine.bookmakers.winamax.record_replay import synthetic_capture
from src.agents.quant.betting_engine.clv import (
    MEASURABLE, JsonlOddsHistoryStore, ObservationPhase, clv_readiness, record_from_capture,
)
from src.agents.quant.betting_engine.sports.identity_aggregate import all_sport_teams

_KO = 1772359200          # 2026-03-01T10:00:00Z (le commentaire disait 18:00Z)

# Une CLÔTURE se prend AVANT le coup d'envoi. Ce test la prenait six heures après,
# c'est-à-dire en plein match : la cote appariée était une cote de direct.
_COUP_ENVOI = datetime(2026, 3, 1, 10, 0, tzinfo=timezone.utc)
_AVANT_COUP_ENVOI = _COUP_ENVOI - timedelta(minutes=5)

# (sportId Winamax, tournamentId, compétition canonique, hôte, visiteur, sélections attendues)
_2WAY = ("home", "away")
CASES = {
    "baseball": (3, 4101, "competition:baseball:usa:mlb",
                 "Boston Red Sox", "Minnesota Twins", _2WAY, "2way"),
    "american_football": (16, 4102, "competition:american_football:usa:nfl",
                          "Las Vegas Raiders", "Cincinnati Bengals", _2WAY, "2way"),
    "volleyball": (23, 4103, "competition:volleyball:ita:serie_a1",
                   "Vero Volley W", "Bergamo W", _2WAY, "2way"),
    "basketball": (2, 4104, "competition:basketball:usa:nba",
                   "Boston Celtics", "Los Angeles Lakers", _2WAY, "2way"),
    # Le hockey settle sur le temps RÉGLEMENTAIRE : le nul y est une issue.
    "hockey": (4, 4105, "competition:hockey:usa:nhl",
               "Anaheim Ducks", "Arizona Coyotes", ("home", "draw", "away"), "3way"),
    "football": (1, 4106, "competition:football:fra:ligue1",
                 "Paris Saint Germain", "Marseille", ("home", "draw", "away"), "3way"),
    # Le tennis n'a ni hôte ni visiteur : ses issues sont les deux joueurs.
    "tennis": (5, 4107, "competition:tennis:atp:tour",
               "Abdulla M.", "Abel M.", ("player_a", "player_b"), "2way"),
}


def _resolver(tournament_id, canonical):
    comp = lambda ev: ((canonical, "RESOLVED", "competition_table")
                       if str(ev.raw_tournament_id) == str(tournament_id)
                       else (None, "UNRESOLVED", "none"))
    # Résolveur MULTISPORT partagé (identité agrégée des 6 sports).
    return BookmakerEventResolver(IdentityResolver(list(all_sport_teams())), competition_resolver=comp)


def _capture(sport, sport_id, tournament_id, home, away, home_odds, gabarit):
    trois = gabarit == "3way"
    issues = [701, 702, 703] if trois else [701, 702]
    labels = {"701": {"code": "1", "label": home}, "702": {"code": "2", "label": away}}
    cotes = {"701": home_odds, "702": 2.10}
    if trois:
        labels["703"] = {"code": "x", "label": "Nul"}
        cotes["703"] = 4.30
        issues = [701, 703, 702]
    state = {
        "matches": {"90001": {
            "sportId": sport_id, "tournamentId": tournament_id, "isOutright": False,
            "competitor1Id": 3001, "competitor1Name": home,
            "competitor2Id": 3002, "competitor2Name": away,
            "matchStart": _KO, "status": "PREMATCH"}},
        # Winamax nomme « Résultat » un marché à trois issues et « Vainqueur » un
        # marché à deux : la table de correspondance ne connaît pas
        # ("Vainqueur", "3way"), et refuse donc — correctement — de deviner.
        "bets": {"9003": {"matchId": 90001, "betType": 1,
                          "betTypeName": "Résultat" if trois else "Vainqueur",
                          "template": gabarit, "betTypeIsLive": False, "outcomes": issues}},
        "outcomes": labels,
        "odds": cotes,
        "tournaments": {str(tournament_id): {"tournamentName": str(tournament_id)}}}
    return synthetic_capture(state, sport)


@pytest.mark.parametrize("sport", list(CASES))
def test_la_chaine_clv_fonctionne_pour_chaque_sport(sport, tmp_path):
    """DÉCISION -> CLÔTURE -> paire, pour chacun des sept sports."""
    sport_id, tid, canonical, home, away, attendues, gabarit = CASES[sport]
    store = JsonlOddsHistoryStore(tmp_path / "odds.jsonl")
    t0 = _COUP_ENVOI - timedelta(days=1)          # décision la veille
    resolver = _resolver(tid, canonical)

    dec = record_from_capture(_capture(sport, sport_id, tid, home, away, 1.80, gabarit),
                              event_resolver=resolver, store=store,
                              phase=ObservationPhase.DECISION, now=t0)
    assert dec.events_recorded == 1, sport
    assert dec.observations_written == len(attendues), sport
    assert {o.selection for o in store.all()} == set(attendues), sport

    record_from_capture(_capture(sport, sport_id, tid, home, away, 1.60, gabarit),
                        event_resolver=resolver, store=store,
                        phase=ObservationPhase.CLOSING, now=_AVANT_COUP_ENVOI)
    r = clv_readiness(store.all())
    assert r.status == MEASURABLE, sport
    assert r.n_complete_pairs == len(attendues) and r.n_events == 1, sport


@pytest.mark.parametrize("sport", list(CASES))
def test_aucun_sport_n_accepte_une_cloture_apres_le_coup_d_envoi(sport, tmp_path):
    """Le garde de clôture vaut pour les sept, pas seulement là où on l'a écrit."""
    sport_id, tid, canonical, home, away, _attendues, gabarit = CASES[sport]
    store = JsonlOddsHistoryStore(tmp_path / "odds.jsonl")

    resume = record_from_capture(
        _capture(sport, sport_id, tid, home, away, 1.60, gabarit),
        event_resolver=_resolver(tid, canonical), store=store,
        phase=ObservationPhase.CLOSING, now=_COUP_ENVOI + timedelta(hours=3))

    assert resume.events_recorded == 0 and resume.events_started == 1, sport
    assert store.all() == [], sport
