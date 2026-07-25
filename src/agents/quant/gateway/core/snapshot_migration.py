"""Migration one-shot des snapshots v1 vers le format Vague 0.

Les snapshots antérieurs à la migration typée (schema_version NULL) portent :
- un axe ancien ("fixtures"/"standings") au lieu d'un data_type §5.2,
- des canonical_id PLATS (team:psg, league:ligue1) au lieu de typés,
- aucun schema_version.

Cette migration, pour chaque snapshot v1 entièrement résoluble :
1. remappe les IDs plats → typés (via le registre d'identités courant),
2. déduit le data_type : "standings" → STANDINGS ; "fixtures" → SPLIT en
   FIXTURES (à venir) + RESULTS (score présent),
3. écrit de NOUVEAUX snapshots (schema_version="football/1.0"), en préservant
   fetched_at (point-in-time).

APPEND-ONLY : les lignes v1 ne sont JAMAIS supprimées (elles deviennent inertes,
jamais requêtées sous le nouvel axe). Un backup horodaté est fait avant écriture.
Un snapshot dont un ID plat n'est pas résoluble (ex. équipe reléguée absente du
registre courant) est LAISSÉ tel quel et signalé — jamais migré à moitié.
"""

from __future__ import annotations
import json
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from src.agents.quant.gateway.core.point_in_time_store import (
    STORE_DB, write as store_write, _content_hash, _connection,
)
from src.agents.quant.gateway.core.identity_data import TEAMS
from src.agents.quant.gateway.registries.competition_registry import COMPETITIONS

SCHEMA_VERSION = "football/1.0"


def _flat_to_typed() -> dict[str, str]:
    """Map ID plat → ID typé, dérivée du registre courant (slug = dernier segment)."""
    mapping: dict[str, str] = {}
    for team in TEAMS:
        mapping["team:" + team.canonical_id.split(":")[-1]] = team.canonical_id
    for competition_id in COMPETITIONS:
        mapping["league:" + competition_id.split(":")[-1]] = competition_id
    return mapping


def _remap_entity_id(entity_id: str, mapping: dict[str, str]) -> str | None:
    """`league:ligue1:2025` → `competition:football:fra:ligue1:2025` (garde la saison)."""
    flat_competition, _, season = entity_id.rpartition(":")
    typed = mapping.get(flat_competition)
    return f"{typed}:{season}" if typed else None


def _remap_match(match: dict, mapping: dict[str, str]) -> dict | None:
    home = mapping.get(match["home_team_id"])
    away = mapping.get(match["away_team_id"])
    league = mapping.get(match["league_id"])
    if not (home and away and league):
        return None
    return {**match, "home_team_id": home, "away_team_id": away, "league_id": league}


def _remap_standing(row: dict, mapping: dict[str, str]) -> dict | None:
    team = mapping.get(row["team_id"])
    return {**row, "team_id": team} if team else None


def _is_result(match: dict) -> bool:
    return match.get("goals_home") is not None and match.get("goals_away") is not None


@dataclass
class MigrationReport:
    backup_path: str | None = None
    migrated: list[dict] = field(default_factory=list)   # {old_entity, old_data_type, old_hash, new: [...]}
    skipped: list[dict] = field(default_factory=list)     # {old_entity, reason, unresolved}


def _new_payloads(old_data_type: str, payload: dict, mapping: dict) -> tuple[dict[str, dict], list[str]]:
    """Retourne ({data_type: payload_remappé}, ids_non_résolus)."""
    unresolved: list[str] = []
    if old_data_type == "standings":
        rows = []
        for row in payload.get("standings", []):
            remapped = _remap_standing(row, mapping)
            (rows.append(remapped) if remapped else unresolved.append(row["team_id"]))
        return {"STANDINGS": {"kind": "standings", "matches": [], "standings": rows}}, unresolved

    # "fixtures" → split FIXTURES / RESULTS
    remapped_matches = []
    for match in payload.get("matches", []):
        remapped = _remap_match(match, mapping)
        if remapped:
            remapped_matches.append(remapped)
        else:
            unresolved.extend([match["home_team_id"], match["away_team_id"]])
    results = [m for m in remapped_matches if _is_result(m)]
    fixtures = [m for m in remapped_matches if not _is_result(m)]
    return {
        "RESULTS": {"kind": "fixtures", "matches": results, "standings": []},
        "FIXTURES": {"kind": "fixtures", "matches": fixtures, "standings": []},
    }, unresolved


def migrate(db_path: Path | None = None, apply: bool = True) -> MigrationReport:
    """Migre les snapshots v1 (schema_version NULL).

    apply=True  : backup horodaté puis migration en place.
    apply=False : dry-run — opère sur une COPIE jetable, ne touche JAMAIS
                  l'original (ni schéma ni données), pour inspecter avant/après.
    """
    path = Path(db_path or STORE_DB)
    if not path.exists():
        return MigrationReport()

    if not apply:
        tmp_dir = Path(tempfile.mkdtemp())
        try:
            copy = tmp_dir / path.name
            shutil.copy2(path, copy)
            report = _migrate_in_place(copy)
            report.backup_path = None   # dry-run : aucun backup réel, original intact
            return report
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    backup_path = str(path) + ".bak-" + datetime.now().strftime("%Y%m%d%H%M%S")
    shutil.copy2(path, backup_path)   # backup AVANT toute écriture
    report = _migrate_in_place(path)
    report.backup_path = backup_path
    return report


def _migrate_in_place(path: Path) -> MigrationReport:
    report = MigrationReport()
    mapping = _flat_to_typed()

    # Aligne le schéma (rename endpoint->data_type, ajoute schema_version/horodatages)
    # pour pouvoir lire les lignes v1 sous le nouvel axe.
    _connection(path).close()

    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    v1_rows = conn.execute(
        "SELECT sport, entity_id, data_type, provider, fetched_at, content_hash, payload "
        "FROM data_snapshot WHERE schema_version IS NULL"
    ).fetchall()
    conn.close()

    for row in v1_rows:
        payload = json.loads(row["payload"])
        new_entity = _remap_entity_id(row["entity_id"], mapping)
        new_payloads, unresolved = _new_payloads(row["data_type"], payload, mapping)

        if new_entity is None or unresolved:
            report.skipped.append({
                "old_entity": row["entity_id"],
                "reason": "entity non résoluble" if new_entity is None else "IDs non résolus",
                "unresolved": sorted(set(unresolved))[:10],
            })
            continue

        new_entries = []
        for new_data_type, new_payload in new_payloads.items():
            new_hash = _content_hash(new_payload, SCHEMA_VERSION)
            new_entries.append({
                "data_type": new_data_type,
                "new_entity": new_entity,
                "new_hash": new_hash,
                "n_matches": len(new_payload["matches"]),
                "n_standings": len(new_payload["standings"]),
            })
            store_write(
                sport=row["sport"],
                entity_id=new_entity,
                data_type=new_data_type,
                provider=row["provider"],
                payload=new_payload,
                request_fingerprint=f"migrated-from-v1:{row['entity_id']}:{row['data_type']}",
                fetched_at=datetime.fromisoformat(row["fetched_at"]),
                schema_version=SCHEMA_VERSION,
                db_path=path,
            )

        report.migrated.append({
            "old_entity": row["entity_id"],
            "old_data_type": row["data_type"],
            "old_hash": row["content_hash"],
            "new": new_entries,
        })

    return report
