"""CLI `axon record-odds` — collecte odds_history depuis une capture Winamax (BE-FR-015).

Thin (comme `axon recommend`) : parse les arguments, charge une capture, rejoue,
enregistre les cotes canoniques dans le store. Aucune logique métier ici. Fonctionne
HORS-LIGNE sur une capture (réelle ou synthétique) ; la provenance persistée est celle
de la capture — jamais falsifiée. Rejouer DECISION puis CLOSING accumule les paires
dont la CLV a besoin.
"""

from __future__ import annotations

import argparse
import pathlib
from datetime import datetime

from src.agents.quant.betting_engine.bookmakers.winamax.record_replay import load_capture
from src.agents.quant.betting_engine.sports.registry import build_event_resolver

from .observation import ObservationPhase
from .recorder import record_from_capture
from .store import JsonlOddsHistoryStore

_PHASES = {
    "open": ObservationPhase.OPEN,
    "intermediate": ObservationPhase.INTERMEDIATE,
    "decision": ObservationPhase.DECISION,
    "closing": ObservationPhase.CLOSING,
}


def _load_live(sport: str):   # pragma: no cover (I/O réseau réelle)
    """Capture LIVE d'un sport (SOURCE_LIVE) — scheduler-friendly (§3) : une commande,
    aucune gestion manuelle de fichier de capture. Lève si le réseau échoue (jamais un
    repli synthétique déguisé en réel)."""
    from ..bookmakers.winamax.record_replay import capture_live_state
    return capture_live_state(sport)


def main(argv: list[str] | None = None, *, live_loader=_load_live) -> int:
    p = argparse.ArgumentParser(
        prog="axon record-odds",
        description="Collecte odds_history multisport (BE-FR-015). Capture fichier OU live (§3).")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--capture", help="fichier de capture (record_replay.save_capture)")
    src.add_argument("--live", metavar="SPORT",
                     help="capture LIVE ce sport (ex. hockey, volleyball) — scheduler-ready")
    p.add_argument("--phase", choices=tuple(_PHASES), default="decision")
    p.add_argument("--store", default=None, help="chemin odds_history.jsonl (défaut : var/ repo)")
    p.add_argument("--run-id", default=None)
    p.add_argument("--now", default=None, help="instant d'observation ISO 8601 (défaut : maintenant)")
    args = p.parse_args(argv)

    capture = live_loader(args.live) if args.live else load_capture(pathlib.Path(args.capture))
    store = JsonlOddsHistoryStore(None if args.store is None else pathlib.Path(args.store))
    # Résolveur MULTISPORT via la fabrique UNIQUE : une observation CLV enregistrée
    # sous une compétition non résolue ne s'apparie jamais à sa décision.
    resolver = build_event_resolver()
    now = None if args.now is None else datetime.fromisoformat(args.now)

    summary = record_from_capture(
        capture, event_resolver=resolver, store=store,
        phase=_PHASES[args.phase], run_id=args.run_id, now=now)
    print(
        f"odds_history: {summary.observations_written} observation(s), "
        f"{summary.events_recorded} événement(s), {summary.events_skipped} ignoré(s) "
        f"[source={capture.source}, phase={args.phase}]")
    return 0


if __name__ == "__main__":   # pragma: no cover
    raise SystemExit(main())
