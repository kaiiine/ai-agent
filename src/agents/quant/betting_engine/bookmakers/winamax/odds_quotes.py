"""Cotes Winamax CANONIQUES — au-dessus de l'UNIQUE source PRELOADED_STATE.

Point d'accès unique aux cotes brutes, partagé avec coverage/recommend/record-odds :

    WinamaxConnector.scan_catalog
      = HTTP -> PRELOADED_STATE -> parse_catalog -> events -> markets -> selections

On en extrait le marché VAINQUEUR de façon SCHEMA-AWARE : 2-way `{slot_1, slot_2}` OU
3-way `{slot_1, draw, slot_2}` — JAMAIS un `draw: None` fabriqué (c'est ce `None` qui
faisait planter l'ancien `odds_fetcher` sur les sports 2-way : `1/None` -> TypeError).

Il n'existe plus de chemin Winamax parallèle : l'ancien `odds_fetcher.py` (sportId faux
tennis=2, forme 1N2 codée en dur) est supprimé. `connector` est injectable (tests
hermétiques : un faux connecteur rejoue un PRELOADED_STATE, aucune divergence de source).
"""

from __future__ import annotations

from dataclasses import dataclass

from ..protocol import MarketType


@dataclass(frozen=True)
class OddsQuote:
    match_id: str
    competition: str
    slot_1_name: str
    slot_2_name: str
    start_time: str | None
    status: str
    odds: dict                # {"slot_1": float, "slot_2": float[, "draw": float]} — jamais None
    bookmaker: str
    fetched_at: str


def _winner_odds(event) -> dict:
    """Cotes du marché VAINQUEUR (MATCH_WINNER), par sélection canonique réellement
    présente. Aucune sélection fabriquée : un marché 2-way n'a PAS de `draw`."""
    market = next((m for m in event.markets if m.market_type is MarketType.MATCH_WINNER), None)
    if market is None:
        return {}
    return {
        s.canonical_selection: s.decimal_odds
        for s in market.selections
        if s.canonical_selection and s.canonical_selection != "UNMAPPED"
    }


def fetch_odds_quotes(sport: str = "football", team: str = "", *, connector=None) -> list[OddsQuote]:
    """Cotes vainqueur canoniques d'un sport via l'UNIQUE connecteur PRELOADED_STATE.
    `team` filtre (sous-chaîne, insensible à la casse) sur l'un des deux participants."""
    if connector is None:
        from .connector import WinamaxConnector
        connector = WinamaxConnector()
    quotes: list[OddsQuote] = []
    for ev in connector.scan_catalog(sport):
        odds = _winner_odds(ev)
        if len(odds) < 2:                        # pas de marché vainqueur exploitable -> ignoré
            continue
        quotes.append(OddsQuote(
            match_id=ev.bookmaker_event_id, competition=ev.competition,
            slot_1_name=ev.slot_1_name, slot_2_name=ev.slot_2_name,
            start_time=ev.start_time.isoformat() if ev.start_time else None,
            status=ev.status, odds=odds, bookmaker="winamax",
            fetched_at=ev.fetched_at.isoformat()))
    if team:
        t = team.lower()
        quotes = [q for q in quotes if t in q.slot_1_name.lower() or t in q.slot_2_name.lower()]
    return quotes
