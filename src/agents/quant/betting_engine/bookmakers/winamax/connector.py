"""Scan du catalogue Winamax -> `RawBookmakerEvent` (en slots).

Le parsing (`parse_catalog`) est une fonction pure, testable hors-ligne sur un
`PRELOADED_STATE` enregistré. `WinamaxConnector.scan_catalog` ajoute seulement
la récupération réseau.

NB : ce connecteur REMPLACE à terme `src/agents/quant/odds_fetcher.py` (gelé,
Dette #3), qui étiquette `home`/`away` en dur et embarque des `sportId` erronés
(ex. tennis=2). Ici les identifiants suivent la cartographie réelle (tennis=5,
basketball=2, baseball=3) et l'ordre est conservé en slots, sans home/away.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import requests

from ..protocol import (
    BookmakerConnector,
    MarketType,
    RawBookmakerEvent,
    RawMarket,
    RawSelection,
)
from . import market_mapping

BASE_URL = "https://www.winamax.fr/paris-sportifs/sports"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.8",
}
TIMEOUT = 20
STATE_MARKER = "var PRELOADED_STATE = "

# sportId Winamax — AUTORITÉ : le snapshot/scan live réel (probe 2026-08-01, tous HTTP 200
# + PRELOADED_STATE valide), JAMAIS l'odds_fetcher gelé (IDs faux : tennis=2). C'est la
# SEULE table nom->sportId ; tous les composants (coverage/recommend/record-odds/tool)
# passent par ce connecteur. golf/F1 sont OUTRIGHT (parse_catalog les exclut -> 0 event
# pairwise, honnête) ; les sports hors-saison rendent 0 event sans erreur.
SPORT_IDS: dict[str, int] = {
    "football": 1,
    "basketball": 2,
    "baseball": 3,
    "hockey": 4,
    "tennis": 5,
    "handball": 6,
    "golf": 9,                 # outright (vainqueur d'épreuve) -> aucun match 2-comp
    "rugby": 12,
    "afl": 13,
    "american_football": 16,   # NFL — payload « Vainqueur » 2-way vérifié
    "table_tennis": 20,
    "volleyball": 23,          # payload « Vainqueur » 2-way vérifié
    "badminton": 31,
    "mma": 117,
    "formula1": 40,            # outright -> aucun match 2-comp
}


def _fetch_state(sport_id: int) -> dict:
    """Télécharge la page sport et extrait le JSON `PRELOADED_STATE`."""
    resp = requests.get(f"{BASE_URL}/{sport_id}", headers=HEADERS, timeout=TIMEOUT)
    resp.raise_for_status()

    html = resp.text
    start = html.find(STATE_MARKER)
    if start == -1:
        raise RuntimeError(
            "PRELOADED_STATE introuvable — Winamax a changé sa page ou servi "
            "une page anti-bot."
        )
    start += len(STATE_MARKER)
    state, _ = json.JSONDecoder().raw_decode(html[start:])
    return state


def _to_dt(epoch: int | None) -> datetime | None:
    if not epoch:
        return None
    return datetime.fromtimestamp(epoch, tz=timezone.utc)


def _str_or_none(value) -> str | None:
    return None if value is None else str(value)


def _build_selections(
    bet: dict, outcomes: dict, odds: dict, bookmaker: str
) -> list[RawSelection]:
    selections: list[RawSelection] = []
    for oid in bet.get("outcomes", []):
        outcome = outcomes.get(str(oid))
        odd = odds.get(str(oid))
        if outcome is None or odd is None:
            continue  # cote sans outcome / outcome vide : ignoré (carto §14)
        code = outcome.get("code", "")
        selections.append(
            RawSelection(
                code=code,
                label=outcome.get("label", ""),
                decimal_odds=float(odd),
                canonical_selection=market_mapping.map_selection_code(code),
            )
        )
    return selections


def _build_markets(
    match_id: str, bets_by_match: dict, outcomes: dict, odds: dict, bookmaker: str
) -> list[RawMarket]:
    markets: list[RawMarket] = []
    for bet in bets_by_match.get(match_id, []):
        selections = _build_selections(bet, outcomes, odds, bookmaker)
        if not selections:
            continue
        markets.append(
            RawMarket(
                market_type=market_mapping.map_market(
                    bet.get("betTypeName", ""), bet.get("template", "")
                ),
                raw_bet_type=int(bet.get("betType", 0)),
                raw_label=bet.get("betTypeName", ""),
                template=bet.get("template", ""),
                is_live=bool(bet.get("betTypeIsLive", False)),
                special_bet_value=bet.get("specialBetValue"),
                selections=selections,
            )
        )
    return markets


def sports_from_state(state: dict) -> dict[int, str]:
    """Extrait la liste des sports (sportId -> nom) d'un `PRELOADED_STATE` — pur, testable."""
    out: dict[int, str] = {}
    for sid, s in (state.get("sports") or {}).items():
        try:
            key = int(sid)
        except (TypeError, ValueError):
            continue
        name = s.get("sportName") if isinstance(s, dict) else s
        out[key] = str(name) if name else str(sid)
    return out


def parse_catalog(
    state: dict, sport: str, sport_id: int, *, now: datetime | None = None
) -> list[RawBookmakerEvent]:
    """Transforme un `PRELOADED_STATE` en événements bruts (slots), sans réseau.

    Ne retient que les événements à deux compétiteurs du sport demandé ; les
    outrights (vainqueur d'épreuve, sans deux compétiteurs) sont exclus car ils
    n'ont pas de rôle opposé à résoudre.
    """
    fetched_at = now or datetime.now(timezone.utc)
    matches = state.get("matches", {})
    bets = state.get("bets", {})
    outcomes = state.get("outcomes", {})
    odds = state.get("odds", {})
    tournaments = state.get("tournaments", {})

    bets_by_match: dict[str, list[dict]] = {}
    for bet in bets.values():
        if not bet:
            continue
        bets_by_match.setdefault(str(bet.get("matchId")), []).append(bet)

    events: list[RawBookmakerEvent] = []
    for match_id, match in matches.items():
        if match.get("sportId") != sport_id:
            continue
        if match.get("isOutright"):
            continue
        slot_1 = match.get("competitor1Name")
        slot_2 = match.get("competitor2Name")
        if not slot_1 or not slot_2:
            continue  # paris spéciaux sans deux compétiteurs

        tournament = tournaments.get(str(match.get("tournamentId")), {})
        events.append(
            RawBookmakerEvent(
                bookmaker="winamax",
                bookmaker_event_id=str(match_id),
                sport=sport,
                competition=tournament.get("tournamentName", ""),
                slot_1_name=slot_1,
                slot_2_name=slot_2,
                slot_1_id=_str_or_none(match.get("competitor1Id")),
                slot_2_id=_str_or_none(match.get("competitor2Id")),
                start_time=_to_dt(match.get("matchStart")),
                status=match.get("status", ""),
                is_outright=bool(match.get("isOutright")),
                markets=_build_markets(
                    str(match_id), bets_by_match, outcomes, odds, "winamax"
                ),
                fetched_at=fetched_at,
                sr_tournament_id=match.get("srTournamentId"),
                raw_tournament_id=_str_or_none(match.get("tournamentId")),
            )
        )
    return events


class WinamaxConnector:
    """Implémentation du contrat `BookmakerConnector` pour Winamax."""

    bookmaker = "winamax"

    def scan_catalog(self, sport: str = "football") -> list[RawBookmakerEvent]:
        sport_id = SPORT_IDS.get(sport.lower())
        if sport_id is None:
            raise ValueError(f"Sport inconnu : {sport}. Choix : {sorted(SPORT_IDS)}")
        state = _fetch_state(sport_id)
        return parse_catalog(state, sport.lower(), sport_id)

    def discover_sports(self) -> dict[int, str]:
        """Découverte DYNAMIQUE de tous les sports exposés par Winamax (sportId -> nom).
        Source de vérité = le catalogue live, jamais une whitelist codée (§1/§32) : un
        nouveau sport ajouté par Winamax apparaît sans modifier ce code."""
        return sports_from_state(_fetch_state(1))

    def market_mapping(self) -> dict:
        """Table lisible des (betTypeName, template) reconnus -> `MarketType`."""
        return {
            ("Résultat", "3way"): MarketType.MATCH_WINNER,
            ("Résultat", "2way"): MarketType.MATCH_WINNER,
            ("Vainqueur", "2way"): MarketType.MATCH_WINNER,
            ("Vainqueur", "ListOdd"): MarketType.OUTRIGHT_WINNER,
        }


# Vérification statique : WinamaxConnector honore bien le protocole.
_: BookmakerConnector = WinamaxConnector()
