"""Rafraîchit les alias Winamax des joueurs de tennis depuis un scan LIVE réel.

    python -m src.agents.quant.betting_engine.sports.tennis.refresh_aliases

Passe par l'UNIQUE source canonique (WinamaxConnector -> PRELOADED_STATE), apparie les
noms par clé normalisée (nom de famille + initiale) et FUSIONNE le résultat dans la
fixture d'alias. N'invente jamais un rattachement : une clé ambiguë ou inconnue est
ignorée. Un joueur non vu en live reste sans alias (événement non résolu, jamais deviné).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .identity import _ALIAS_FIXTURE, build_alias_table


def main(argv: list[str] | None = None) -> int:
    from ...bookmakers.winamax.connector import WinamaxConnector

    events = WinamaxConnector().scan_catalog("tennis")          # SOURCE_LIVE, aucun fallback
    names = {n for e in events for n in (e.slot_1_name, e.slot_2_name) if n}
    existing = (json.loads(_ALIAS_FIXTURE.read_text(encoding="utf-8"))
                if _ALIAS_FIXTURE.exists() else {"aliases": {}})
    merged = existing.get("aliases", {})
    added = 0
    for tour in ("atp", "wta"):
        table = build_alias_table(names, tour)
        current = merged.setdefault(tour, {})
        for dataset_name, aliases in table.items():
            slot = current.setdefault(dataset_name, [])
            for a in aliases:
                if a not in slot:
                    slot.append(a)
                    added += 1
    payload = {
        "source": "winamax PRELOADED_STATE (scan live)",
        "method": "clé normalisée (nom_de_famille, initiale) — exacte, jamais fuzzy ; "
                  "clés ambiguës et paires de double exclues",
        "refreshed_at": datetime.now(timezone.utc).isoformat(),
        "n_live_names": len(names),
        "aliases": merged,
    }
    _ALIAS_FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    _ALIAS_FIXTURE.write_text(json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True),
                              encoding="utf-8")
    total = sum(len(v) for t in merged.values() for v in t.values())
    print(f"alias tennis: +{added} nouveaux | {total} alias au total | {len(names)} noms live")
    return 0


if __name__ == "__main__":   # pragma: no cover
    raise SystemExit(main())
