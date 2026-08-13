"""Payload Winamax -> observations de marché, sans perte.

Séparé du `connector` à dessein : celui-ci ne retient que ce que le chemin
`MATCH_WINNER` consomme (événements à deux compétiteurs, marché principal), et
c'est très bien pour ce qu'il fait. L'inventaire, lui, doit tout voir — y compris
les outrights, que `parse_catalog` écarte faute de rôle opposé à résoudre.

DEUX PAGES, DEUX PORTÉES. `/paris-sportifs/sports/{sportId}` ne sert que le
marché principal de chaque événement (`mainBetId`) ; les autres — jusqu'à 252
observés sur une seule rencontre — ne viennent qu'avec
`/paris-sportifs/match/{matchId}`. Un inventaire construit sur la seule page
catalogue afficherait donc « 1 marché par événement » et se croirait complet.
`nb_marches_annonces` conserve le `moreBets` déclaré par la source : c'est le
seul moyen de dire, sans le deviner, combien de marchés on n'a PAS regardés.
"""

from __future__ import annotations

from datetime import datetime, timezone

from ...markets.observation import RawMarketObservation, RawSelectionObservation


def _instant(epoch) -> datetime | None:
    if not epoch:
        return None
    try:
        return datetime.fromtimestamp(int(epoch), tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return None


def _flottant(valeur) -> float | None:
    """Une cote, ou rien. Une cote absente est une information — jamais un 0."""
    try:
        return float(valeur)
    except (TypeError, ValueError):
        return None


#: Champs déjà portés nommément par `RawMarketObservation`. Tout le reste du
#: `bet` part dans `extras` : c'est la règle « ne jette aucune information
#: inconnue », appliquée par différence plutôt que par liste blanche — un champ
#: ajouté demain par la source arrive donc tout seul.
_CHAMPS_REPRIS = frozenset({
    "betId", "matchId", "marketId", "specialBetValue", "outcomes", "template",
    "betTypeIsLive", "betTitle", "betTypeName", "betType", "betTypeCategoryId",
    "betTypeCategory",
})


def observations_depuis_evenement(
    match: dict,
    detail: dict,
    *,
    sport: str,
    sport_id: int,
    competition: str | None = None,
    observed_at: datetime | None = None,
    bookmaker: str = "winamax",
) -> tuple[RawMarketObservation, ...]:
    """Un événement + le payload de sa page -> une observation par marché."""
    bets = detail.get("bets") or {}
    outcomes = detail.get("outcomes") or {}
    cotes = detail.get("odds") or {}
    lu_a = observed_at or datetime.now(timezone.utc)
    event_id = str(match.get("matchId"))

    observations: list[RawMarketObservation] = []
    for bet in bets.values():
        if not bet:
            continue
        selections = tuple(
            RawSelectionObservation(
                source_selection_id=str(oid),
                code=(outcomes.get(str(oid)) or {}).get("code"),
                label=(outcomes.get(str(oid)) or {}).get("label"),
                decimal_odds=_flottant(cotes.get(str(oid))),
                competitor_id=_texte((outcomes.get(str(oid)) or {}).get("competitorId")),
                available=(outcomes.get(str(oid)) or {}).get("available"),
            )
            for oid in (bet.get("outcomes") or [])
        )
        observations.append(RawMarketObservation(
            bookmaker=bookmaker,
            sport=sport,
            sport_id=sport_id,
            competition=competition,
            competition_source_id=_texte(match.get("tournamentId")),
            source_event_id=event_id,
            event_label=match.get("title"),
            start_time=_instant(match.get("matchStart")),
            is_outright=bool(match.get("isOutright")),
            market_source_id=_texte(bet.get("betId")),
            bet_type=_entier(bet.get("betType")),
            bet_type_name=bet.get("betTypeName"),
            bet_title=bet.get("betTitle"),
            template=bet.get("template"),
            special_bet_value=bet.get("specialBetValue"),
            category_id=_entier(bet.get("betTypeCategoryId")),
            category=bet.get("betTypeCategory"),
            is_live=bet.get("betTypeIsLive"),
            selections=selections,
            observed_at=lu_a,
            extras={
                "nb_marches_annonces": match.get("moreBets"),
                "market_id_source": bet.get("marketId"),
                **{k: v for k, v in bet.items() if k not in _CHAMPS_REPRIS},
            },
        ))
    return tuple(observations)


def _texte(valeur) -> str | None:
    return None if valeur is None else str(valeur)


def _entier(valeur) -> int | None:
    try:
        return int(valeur)
    except (TypeError, ValueError):
        return None
