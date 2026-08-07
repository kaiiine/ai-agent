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
from ..core.market_model import FOOTBALL_1X2, MarketSchema
from ..sports.model_registry import VALIDATED_MODELS
from .observation import ObservationPhase, OddsObservation

# Schéma de collecte MULTISPORT (§2) : le marché « vainqueur » d'un sport dépend de son
# nombre d'issues, JAMAIS d'une hypothèse football. 3-way (football/hockey réglementaire)
# vs 2-way (basket/baseball/NFL/volley). Dérivé du registre de modèles validés.
_TWO_WAY = MarketSchema("MATCH_WINNER", "2way", ("home", "away"), ("slot_1", "slot_2"), False)


@dataclass(frozen=True)
class RecordSummary:
    observations_written: int
    events_recorded: int
    events_skipped: int
    #: Événements écartés parce que le marché avait déjà commencé alors qu'on
    #: enregistrait une CLÔTURE. Compté à part : ce n'est pas un défaut de
    #: résolution, c'est une capture arrivée trop tard.
    events_started: int = 0


def closing_is_valid(raw_event, observed_at) -> bool:
    """Cette observation peut-elle être une CLÔTURE ?

    Une clôture est la DERNIÈRE cote observée avant l'ouverture du jeu. Après le
    coup d'envoi, ce que le bookmaker affiche est une cote de direct : elle
    intègre le score et n'a plus rien à voir avec la ligne de clôture. L'écrire
    comme CLOSING ne produirait pas une mesure imprécise mais une mesure d'autre
    chose — et une CLV calculée dessus paraîtrait excellente ou catastrophique
    sans qu'aucune des deux ne veuille dire quoi que ce soit.

    La phase était choisie par un drapeau de ligne de commande, sans aucun garde.
    Un planificateur réglé une heure trop tard aurait rempli l'historique de
    cotes de direct étiquetées « clôture », et rien ne l'aurait signalé : le
    calcul de CLV, lui, apparie sans discuter deux observations bien formées.

    Deux signaux, et le plus prudent gagne : l'horaire annoncé et le statut du
    bookmaker. Un événement sans horaire connu est refusé — on ne peut pas
    affirmer qu'il n'a pas commencé.
    """
    if str(getattr(raw_event, "status", "")).upper() == "LIVE":
        return False
    debut = getattr(raw_event, "start_time", None)
    if debut is None or observed_at is None:
        return False
    return observed_at <= debut


def _schema_for_sport(sport: str) -> MarketSchema | None:
    """Schéma du marché vainqueur pour un sport collecté (None si sport non modélisé).

    SOURCE UNIQUE : le schéma DÉCLARÉ par le modèle live enregistré (il porte les vraies
    issues canoniques — `home/away`, `home/draw/away`, ou `player_a/player_b` en tennis).
    On ne re-dérive un schéma générique que pour un sport validé sans module live."""
    from ..sports.registry import SPORT_MODULES
    module = SPORT_MODULES.get(sport)
    schema = getattr(getattr(module, "model", None), "schema", None)
    if schema is not None:
        return schema
    model = VALIDATED_MODELS.get(sport)
    if model is None:
        return None
    return FOOTBALL_1X2 if model.outcomes == 3 else _TWO_WAY


def _find_winner_market(raw_event, schema: MarketSchema):
    for market in raw_event.markets:
        if market.market_type.value == schema.market_type and market.template == schema.template:
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
    convertie en `Decimal` via `str` (aucun artefact binaire).

    En phase CLOSING, un événement déjà commencé est écarté (cf.
    `closing_is_valid`) : une cote de direct n'est pas une ligne de clôture."""
    written = recorded = skipped = started = 0
    for raw_event in events:
        schema = _schema_for_sport(raw_event.sport)
        if schema is None:                       # sport non modélisé : rien à collecter (visible, pas fabriqué)
            skipped += 1
            continue
        mapping = event_resolver.resolve_event(raw_event)
        if not mapping.is_usable:
            skipped += 1
            continue
        market = _find_winner_market(raw_event, schema)
        if market is None:
            skipped += 1
            continue
        role_resolution = resolve_participant_roles(raw_event, role_resolver)
        canon = canonicalize_market(raw_event, market, mapping, role_resolution, schema=schema)
        if not canon.is_ok:
            skipped += 1
            continue
        event = build_canonical_event(raw_event, mapping, role_resolver)
        # Le garde s'applique APRÈS la canonicalisation : un événement déjà
        # commencé reste compté comme tel, et non confondu avec un événement
        # illisible. Les deux se corrigent différemment — l'un en avançant le
        # planificateur, l'autre en complétant un référentiel.
        if phase is ObservationPhase.CLOSING and canon.snapshots:
            if not closing_is_valid(raw_event, canon.snapshots[0].observed_at):
                started += 1
                continue
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
    return RecordSummary(written, recorded, skipped, started)


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
