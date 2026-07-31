"""Couverture UNIVERSELLE tous-sports (wave 3 §20/§24/§32/§39).

Croise le CATALOGUE Winamax réellement découvert (sportId -> nom, live) avec le registre
DÉCLARATIF des modèles validés. Pour CHAQUE sport exposé par Winamax — quelle que soit sa
popularité — produit une ligne : modèle disponible ? maturité ? bloqueur ? Un sport
découvert sans modèle n'est jamais ignoré : il devient `SPORT_DISCOVERED_MODEL_UNAVAILABLE`
(dette OBSERVABLE). Ainsi AXON « voit tout Winamax » et signale toute NOUVELLE capability
non modélisée sans qu'on ait pré-écrit le nom du sport.
"""

from __future__ import annotations

from dataclasses import dataclass

from .sports.model_registry import BY_WINAMAX_SPORT_ID, model_maturity

SPORT_DISCOVERED_MODEL_UNAVAILABLE = "SPORT_DISCOVERED_MODEL_UNAVAILABLE"


@dataclass(frozen=True)
class SportCoverageRow:
    winamax_sport_id: int
    sport_name: str                    # nom Winamax (catalogue)
    canonical_sport: str | None        # clé canonique si un modèle validé existe
    model_capable: bool
    market_type: str | None
    outcomes: int | None
    methodology: str | None
    model_version: str | None
    maturity: str                      # EXPERIMENTAL / SUPPORTED / UNAVAILABLE
    blocker: str | None                # None si model_capable


@dataclass(frozen=True)
class UniversalCoverage:
    sports_discovered: int
    sports_model_capable: int
    sports_supported: int
    rows: tuple[SportCoverageRow, ...]


def universal_coverage(discovered_sports: dict[int, str]) -> UniversalCoverage:
    """`discovered_sports` = sortie de `connector.discover_sports()` (catalogue live)."""
    rows: list[SportCoverageRow] = []
    for sid, name in sorted(discovered_sports.items()):
        model = BY_WINAMAX_SPORT_ID.get(sid)
        if model is None:
            rows.append(SportCoverageRow(
                sid, name, None, False, None, None, None, None, "UNAVAILABLE",
                SPORT_DISCOVERED_MODEL_UNAVAILABLE))
        else:
            rows.append(SportCoverageRow(
                sid, name, model.sport, True, model.market_type, model.outcomes,
                model.methodology, model.model_version, model_maturity(model), None))
    # Tri : model-capable d'abord, puis par sportId.
    rows.sort(key=lambda r: (not r.model_capable, r.winamax_sport_id))
    return UniversalCoverage(
        sports_discovered=len(rows),
        sports_model_capable=sum(1 for r in rows if r.model_capable),
        sports_supported=sum(1 for r in rows if r.maturity == "SUPPORTED"),
        rows=tuple(rows))
