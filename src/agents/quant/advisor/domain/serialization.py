"""Sérialisation JSON STABLE + round-trip de la requête (ADV-FR-028, ADV-NFR-005).

`to_jsonable` produit une structure JSON déterministe (clés triées, `frozenset`
triés, `Decimal` en chaîne — jamais `float`), pour toute dataclass du domaine.

`request_from_jsonable` reconstruit une `RecommendationRequest` (le contrat
d'ENTRÉE). La désérialisation des sorties (réponse/candidats) est différée au Lot
10 (audit/replay), là où elle sert réellement — cf. §Hors-scope Lot 1.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum

from .enums import MaturityPolicy, RiskProfile
from .requests import OddsRange, RecommendationRequest


def to_jsonable(obj):
    """Structure JSON-safe et STABLE (Decimal->str, Enum->value, frozenset trié)."""
    if is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: to_jsonable(getattr(obj, f.name)) for f in fields(obj)}
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, frozenset):
        return sorted(to_jsonable(x) for x in obj)
    if isinstance(obj, (list, tuple)):
        return [to_jsonable(x) for x in obj]
    if isinstance(obj, Mapping):
        return {k: to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (str, int, bool)) or obj is None:
        return obj
    if isinstance(obj, float):
        # float = diagnostic NON monétaire (ex. valeurs de features d'explication) ;
        # chaîne canonique déterministe. Les valeurs monétaires/probabilistes sont
        # `Decimal` (garanti par les contrats), jamais float — cette branche ne
        # relâche donc pas l'invariant « aucun float monétaire » (ADV-NFR-010).
        return repr(obj)
    raise TypeError(f"type non sérialisable : {type(obj).__name__}")


def to_json(obj) -> str:
    """JSON stable (clés triées, UTF-8)."""
    return json.dumps(to_jsonable(obj), sort_keys=True, ensure_ascii=False)


def _fset(value) -> frozenset[str] | None:
    return None if value is None else frozenset(value)


def request_from_jsonable(data: dict) -> RecommendationRequest:
    odds = data["target_total_odds"]
    return RecommendationRequest(
        request_id=data["request_id"],
        decision_time=datetime.fromisoformat(data["decision_time"]),
        bankroll=Decimal(data["bankroll"]),
        currency=data["currency"],
        allowed_sports=_fset(data["allowed_sports"]),
        allowed_competitions=_fset(data["allowed_competitions"]),
        allowed_bookmakers=_fset(data["allowed_bookmakers"]),
        allowed_market_types=_fset(data["allowed_market_types"]),
        target_total_odds=None if odds is None else OddsRange(Decimal(odds["minimum"]), Decimal(odds["maximum"])),
        max_total_stake=None if data["max_total_stake"] is None else Decimal(data["max_total_stake"]),
        max_selections=data["max_selections"],
        max_portfolios=data["max_portfolios"],
        allow_singles=data["allow_singles"],
        allow_combos=data["allow_combos"],
        max_combo_legs=data["max_combo_legs"],
        risk_profile=RiskProfile(data["risk_profile"]),
        maturity_policy=MaturityPolicy(data["maturity_policy"]),
        ranking_profile=data["ranking_profile"],
        excluded_event_ids=frozenset(data["excluded_event_ids"]),
        excluded_participant_ids=frozenset(data["excluded_participant_ids"]),
        excluded_market_types=frozenset(data["excluded_market_types"]),
    )


def request_from_json(text: str) -> RecommendationRequest:
    return request_from_jsonable(json.loads(text))
