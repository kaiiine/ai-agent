"""Enregistreur `odds_history` (BE-FR-015) : rend la collecte CLV OPÉRATIONNELLE.

Transforme un scan/replay bookmaker en `OddsObservation` canoniques persistées, en
réutilisant la MÊME canonicalisation que `evaluate_live_event` (résolution identité +
`canonicalize_market`) — aucune logique dupliquée, aucune recomputation de cote. La
PROVENANCE est honnête : `record_from_capture` propage la `source` de la capture
(`SOURCE_LIVE` d'un vrai fetch réseau, `SOURCE_SYNTHETIC` d'une fixture) — jamais une
capture synthétique présentée comme réelle.

Aucune donnée n'est fabriquée : on n'écrit que des cotes réellement observées (ou
rejouées d'une capture réelle). Le temps qui passe, en rejouant DECISION puis CLOSING,
produit les paires dont la CLV a besoin (cf. `clv.clv_readiness`).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from ..bookmakers.canonical_binding import build_canonical_event
from ..bookmakers.market_canonicalizer import canonicalize_market, resolve_participant_roles
from ..bookmakers.protocol import MarketType
from .observation import ObservationPhase, OddsObservation


@dataclass(frozen=True)
class RecordSummary:
    observations_written: int
    events_recorded: int
    events_skipped: int


def _first_1x2_market(raw_event):
    for market in raw_event.markets:
        if market.market_type is MarketType.MATCH_WINNER and market.template == "3way":
            return market
    return None


def record_odds(
    events,
    *,
    event_resolver,
    store,
    phase: ObservationPhase,
    source: str,
    run_id: str | None = None,
    role_resolver=None,
) -> RecordSummary:
    """Canonicalise chaque événement et persiste ses cotes 1X2 comme `OddsObservation`.

    Un événement non résolu / sans marché 1X2 / non canonicalisable est IGNORÉ (compté),
    jamais fabriqué. `observed_at` = l'instant d'observation réel de la cote
    (`OddsSnapshot.observed_at`, issu de `fetched_at`). La cote float du contrat BE est
    convertie en `Decimal` via `str` (aucun artefact binaire)."""
    written = recorded = skipped = 0
    for raw_event in events:
        mapping = event_resolver.resolve_event(raw_event)
        if not mapping.is_usable:
            skipped += 1
            continue
        market = _first_1x2_market(raw_event)
        if market is None:
            skipped += 1
            continue
        role_resolution = resolve_participant_roles(raw_event, role_resolver)
        canon = canonicalize_market(raw_event, market, mapping, role_resolution)
        if not canon.is_ok:
            skipped += 1
            continue
        event = build_canonical_event(raw_event, mapping, role_resolver)
        for snap in canon.snapshots:
            store.append(OddsObservation(
                event_id=event.event_id,
                market_type=snap.market_type,
                selection=snap.selection,
                bookmaker=snap.bookmaker,
                decimal_odds=Decimal(str(snap.decimal_odds)),
                observed_at=snap.observed_at,
                phase=phase,
                source=source,
                source_event_id=raw_event.bookmaker_event_id,
                run_id=run_id,
            ))
            written += 1
        recorded += 1
    return RecordSummary(written, recorded, skipped)


def record_from_capture(
    capture, *, event_resolver, store, phase: ObservationPhase,
    run_id: str | None = None, now=None,
) -> RecordSummary:
    """Rejoue une capture Winamax et enregistre ses cotes. La `source` persistée est
    celle de la capture (LIVE réel vs SYNTHÉTIQUE) — provenance jamais falsifiée. `now`
    fixe l'instant d'observation des cotes (fetched_at) : un scan DECISION puis un scan
    CLOSING ultérieur produisent la paire attendue par la CLV."""
    from ..bookmakers.winamax.record_replay import replay
    events = replay(capture, now=now)
    return record_odds(events, event_resolver=event_resolver, store=store,
                       phase=phase, source=capture.source, run_id=run_id)
