"""Competition Registry — identité des compétitions (PRD v2 §7.1, GW-FR-002).

Identité SEULE : aucun ID provider ici (la couverture vit dans
provider_coverage_registry). Stockage YAML versionné en git — peu volumineux,
édité à la main (arbitrage Vague 0).

canonical_id typé (ADR-008) : competition:{sport}:{scope}:{slug}. Le `scope`
est un code de zone football (fra, eng, eur...), distinct du `country_code`
ISO 3166-1 alpha-2 (FR, GB...).

⚠ NE PAS "corriger" le scope vers ISO 3166-1 alpha-2 (fr, gb, eu).
Le PRD mentionne « ISO alpha-2 » mais ses exemples utilisent fra/eng/eur, et
c'est VOLONTAIRE : en football, l'Angleterre, l'Écosse, le pays de Galles et
l'Irlande du Nord sont des zones distinctes qui partageraient toutes le code
ISO alpha-2 « GB ». Un scope ISO produirait competition:football:gb:premier_league
ET competition:football:gb:scottish_premiership → collision. Les codes de zone
football 3 lettres (eng/sco/wal/nir, style FIFA) les distinguent. Le country_code
ISO reste correct comme métadonnée (GB), mais n'est PAS l'axe d'identité.
Passer le scope en ISO réintroduirait une collision d'identité — exactement le
genre de bug qu'ADR-008 existe pour empêcher.
"""

from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path

import yaml

_DATA = Path(__file__).parent / "data" / "competitions.yaml"

_COMPETITION_TYPES = {"league", "cup", "continental_cup", "tour_event", "series"}
_STATUSES = {"draft", "active", "deprecated"}


@dataclass(frozen=True)
class Competition:
    canonical_id: str                    # ex. "competition:football:fra:ligue1"
    sport: str
    name: str
    country_code: str | None             # ISO 3166-1 alpha-2 ; None si international
    competition_type: str                # league | cup | continental_cup | tour_event | series
    tier: int | None
    status: str                          # draft | active | deprecated


def _validate(item: dict) -> None:
    cid = item.get("canonical_id", "")
    parts = cid.split(":")
    if len(parts) != 4 or parts[0] != "competition":
        raise ValueError(f"canonical_id de compétition invalide (attendu competition:sport:scope:slug) : {cid!r}")
    if parts[1] != item.get("sport"):
        raise ValueError(f"sport incohérent avec le canonical_id : {cid!r} vs sport={item.get('sport')!r}")
    if item.get("competition_type") not in _COMPETITION_TYPES:
        raise ValueError(f"competition_type invalide : {item.get('competition_type')!r}")
    if item.get("status") not in _STATUSES:
        raise ValueError(f"status invalide : {item.get('status')!r}")


def _load() -> dict[str, Competition]:
    raw = yaml.safe_load(_DATA.read_text(encoding="utf-8")) or []
    competitions: dict[str, Competition] = {}
    for item in raw:
        _validate(item)
        comp = Competition(
            canonical_id=item["canonical_id"],
            sport=item["sport"],
            name=item["name"],
            country_code=item.get("country_code"),
            competition_type=item["competition_type"],
            tier=item.get("tier"),
            status=item["status"],
        )
        competitions[comp.canonical_id] = comp
    return competitions


COMPETITIONS: dict[str, Competition] = _load()


def get_competition(canonical_id: str) -> Competition | None:
    return COMPETITIONS.get(canonical_id)


def active_competitions(sport: str | None = None) -> list[Competition]:
    return [
        c for c in COMPETITIONS.values()
        if c.status == "active" and (sport is None or c.sport == sport)
    ]
