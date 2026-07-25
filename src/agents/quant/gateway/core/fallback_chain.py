"""Orchestration du fallback entre providers — sélection hiérarchique déterministe.

Éligibilité (§8.1) et départage (§8.2) fondés sur le provider_coverage_registry :
seules les couvertures FULL/PARTIAL vérifiées sont candidates (GW-FR-005), jamais
UNVERIFIED/ABSENT. Le score composite reste écarté (ADR-006).

Découplage core→sport : ce module n'importe AUCUN module sportif concret. Il
obtient schéma, normalizers et validateur via get_sport_module(sport) (GW-FR-001).
Les registres de couverture/compétition sont de la config cross-sport, pas des
modules sportifs — les importer est légitime.

Axe de données : `data_type` (RESULTS/STANDINGS/FIXTURES, §5.2), pas un "endpoint"
provider. La méthode provider appelée en découle (STANDINGS → fetch_standings,
sinon → fetch_league_fixtures).
"""

from __future__ import annotations
from datetime import datetime, timezone

from src.agents.quant.gateway.core.provider_registry import REGISTRY, FALLBACK_ORDER
from src.agents.quant.gateway.core import quality
from src.agents.quant.gateway.core.point_in_time_store import write as store_write, last_snapshot
from src.agents.quant.gateway.cache.operational_cache import cache_get, cache_set
from src.agents.quant.gateway.core.identity_resolver import IdentityResolver
from src.agents.quant.gateway.core.errors import NoDataAvailableError
from src.agents.quant.gateway.core.decision_log import log_decision
from src.agents.quant.gateway.sports.registry import get_sport_module
from src.agents.quant.gateway.sports.errors import PayloadValidationError
from src.agents.quant.gateway.registries.competition_registry import get_competition
from src.agents.quant.gateway.registries.provider_coverage_registry import (
    usable_providers, get_coverage, CoverageStatus,
)
from src.agents.quant.gateway.normalizers.canonical_models import (
    CanonicalPayload,
    DataEnvelope,
    match_to_dict,
    match_from_dict,
    standing_to_dict,
    standing_from_dict,
)

MIN_DATA_QUALITY = 0.5

# Compteur local très simple, en mémoire (reset par process) — approxime le
# quota restant en l'absence de suivi fiable côté providers (PRD §8.4).
_request_counts: dict[str, int] = {}
_LOCAL_QUOTA_PER_PROCESS = {"football_data_org": 8, "api_sports": 80}


def _has_quota(provider_name: str) -> bool:
    return _request_counts.get(provider_name, 0) < _LOCAL_QUOTA_PER_PROCESS.get(provider_name, 999_999)


def _record_request(provider_name: str) -> None:
    _request_counts[provider_name] = _request_counts.get(provider_name, 0) + 1


def _capability_for(data_type: str) -> str:
    return "standings" if data_type == "STANDINGS" else "fixtures"


def _eligible_providers(sport: str, competition_id: str, season: str, data_type: str) -> list[str]:
    """Candidats §8.1, ordonnés §8.2.

    §8.1 (élimination) : couverture FULL/PARTIAL vérifiée (GW-FR-005) · compétition
    active · le SportModule déclare un normalizer pour ce provider · capability du
    provider · quota.
    §8.2 (départage) : FULL avant PARTIAL · data_quality décroissant · priorité
    déclarée (FALLBACK_ORDER) · query_cost croissant.
    """
    competition = get_competition(competition_id)
    if competition is None or competition.status != "active":
        return []

    module_normalizers = get_sport_module(sport).normalizers()
    capability_attr = _capability_for(data_type)

    candidates: list[str] = []
    for provider_name in usable_providers(competition_id, season, data_type):
        entry = REGISTRY.get(provider_name)
        if entry is None:
            continue
        if provider_name not in module_normalizers:
            continue
        if not getattr(entry.provider.capabilities(sport), capability_attr, False):
            continue
        if not _has_quota(provider_name):
            continue
        candidates.append(provider_name)

    order = FALLBACK_ORDER.get(sport, [])

    def sort_key(name: str) -> tuple:
        cov = get_coverage(name, competition_id, season, data_type)
        status_rank = 0 if cov and cov.status == CoverageStatus.FULL else 1
        priority = order.index(name) if name in order else 999
        return (status_rank, -quality.data_quality(name, data_type), priority, REGISTRY[name].provider.query_cost)

    return sorted(candidates, key=sort_key)


def _serialize(canonical: CanonicalPayload) -> dict:
    return {
        "kind": canonical.kind,
        "matches": [match_to_dict(m) for m in canonical.matches],
        "standings": [standing_to_dict(s) for s in canonical.standings],
    }


def _deserialize(data: dict) -> CanonicalPayload:
    return CanonicalPayload(
        kind=data["kind"],
        matches=[match_from_dict(m) for m in data.get("matches", [])],
        standings=[standing_from_dict(s) for s in data.get("standings", [])],
    )


def _is_empty(canonical: CanonicalPayload) -> bool:
    return not canonical.matches and not canonical.standings


def fetch_league_data(
    sport: str,
    data_type: str,                    # "RESULTS" | "STANDINGS" | "FIXTURES" (§5.2)
    league_canonical_id: str,          # canonical_id de compétition
    season: str,
    resolver: IdentityResolver,
    date_from: str | None = None,
    date_to: str | None = None,
) -> DataEnvelope:
    """Récupère les données d'une compétition via le premier provider éligible.

    Ne lève jamais d'exception réseau vers l'appelant : si tous les providers
    échouent, retombe sur le dernier snapshot connu (stale=True) — sous réserve
    de compatibilité de schéma (GW-FR-009). Lève NoDataAvailableError sinon.

    Point-in-time : le refus de donnée postérieure (§8.3) n'est pas applicable
    ici — fetch_league_data ne prend pas de paramètre point_in_time (la discipline
    walk-forward est portée par le consommateur, pas par la récupération pré-match).
    """
    module = get_sport_module(sport)
    schema_version = module.schema_version

    cache_key = f"{sport}:{data_type}:{league_canonical_id}:{season}:{date_from}:{date_to}"
    cached = cache_get(cache_key, data_type)
    if cached is not None:
        canonical = _deserialize(cached["canonical"])
        cached_fetched_at = datetime.fromisoformat(cached["fetched_at"])
        effective_time = canonical.published_time or canonical.event_time or cached_fetched_at
        log_decision(sport, data_type, league_canonical_id, season, cached["provider"], "CACHE_HIT", [])
        return DataEnvelope(
            payload=canonical,
            provider=cached["provider"],
            event_time=canonical.event_time,
            published_time=canonical.published_time,
            available_to_model_time=cached_fetched_at,
            fetched_at=cached_fetched_at,
            ingested_at=datetime.now(timezone.utc),
            data_quality=quality.data_quality(cached["provider"], data_type),
            freshness_score=quality.freshness_score(effective_time, datetime.now(timezone.utc), data_type),
        )

    module_normalizers = module.normalizers()
    errors: list[str] = []

    for provider_name in _eligible_providers(sport, league_canonical_id, season, data_type):
        entry = REGISTRY[provider_name]
        coverage = get_coverage(provider_name, league_canonical_id, season, data_type)
        provider_competition_id = coverage.provider_competition_id if coverage else None
        if not provider_competition_id:
            continue
        normalizer = module_normalizers[provider_name]

        try:
            _record_request(provider_name)
            fetched_at = datetime.now(timezone.utc)

            if data_type == "STANDINGS":
                raw = entry.provider.fetch_standings(sport, provider_competition_id, season)
                canonical = normalizer.normalize_standings(raw, resolver, league_canonical_id)
            else:
                raw = entry.provider.fetch_league_fixtures(sport, provider_competition_id, season, date_from, date_to)
                canonical = normalizer.normalize_fixtures(raw, resolver, league_canonical_id, season)

            # GW-FR-007 : validation du payload AVANT toute écriture dans le store.
            module.validate_payload(canonical, data_type)

            # §8.3 : résultat vide alors que la couverture annonce FULL → fallback.
            # Vide alors que PARTIAL → légitime, retourné tel quel (pas de fallback).
            if _is_empty(canonical) and coverage.status == CoverageStatus.FULL:
                errors.append(f"{provider_name}: unexpected_empty (couverture FULL)")
                log_decision(sport, data_type, league_canonical_id, season, provider_name, "unexpected_empty", errors)
                continue

            data_quality_score = quality.data_quality(provider_name, data_type)
            if data_quality_score < MIN_DATA_QUALITY:
                errors.append(f"{provider_name}: quality_below_threshold ({data_quality_score})")
                continue

            effective_time = canonical.published_time or canonical.event_time or fetched_at
            ingested_at = datetime.now(timezone.utc)
            store_write(
                sport=sport,
                entity_id=f"{league_canonical_id}:{season}",
                endpoint=data_type,
                provider=provider_name,
                payload=_serialize(canonical),
                request_fingerprint=f"{provider_competition_id}:{season}:{date_from}:{date_to}",
                fetched_at=fetched_at,
                schema_version=schema_version,
                provider_entity_id=provider_competition_id,
                event_time=canonical.event_time,          # None explicite tant que (b) n'est pas fait (C7)
                published_time=canonical.published_time,   # idem
                available_to_model_time=fetched_at,
                ingested_at=ingested_at,
            )
            cache_set(
                cache_key, data_type,
                {"canonical": _serialize(canonical), "provider": provider_name, "fetched_at": fetched_at.isoformat()},
            )
            log_decision(sport, data_type, league_canonical_id, season, provider_name, "LIVE_FETCH", errors)

            return DataEnvelope(
                payload=canonical,
                provider=provider_name,
                event_time=canonical.event_time,
                published_time=canonical.published_time,
                available_to_model_time=fetched_at,
                fetched_at=fetched_at,
                ingested_at=ingested_at,
                data_quality=data_quality_score,
                freshness_score=quality.freshness_score(effective_time, fetched_at, data_type),
            )
        except PayloadValidationError as e:
            errors.append(f"{provider_name}: schema_violation ({e})")
            continue
        except Exception as e:
            errors.append(f"{provider_name}: {e}")
            continue

    # entity_id inclut la saison : un snapshot 2024 ne sert jamais de recours pour 2025.
    snapshot = last_snapshot(sport, f"{league_canonical_id}:{season}", data_type)
    if snapshot is None:
        log_decision(sport, data_type, league_canonical_id, season, None, "NO_DATA_AVAILABLE", errors)
        raise NoDataAvailableError(
            f"Aucune donnée pour {sport}/{data_type}/{league_canonical_id} (saison {season}). "
            f"Providers essayés : {'; '.join(errors) if errors else 'aucun éligible'}."
        )

    # GW-FR-009 : un snapshot sous schéma incompatible n'est jamais réinterprété.
    stored_schema = snapshot.get("schema_version")
    if not module.is_schema_compatible(stored_schema or ""):
        log_decision(sport, data_type, league_canonical_id, season, snapshot["provider"], "SCHEMA_INCOMPATIBLE", errors)
        raise NoDataAvailableError(
            f"Dernier snapshot pour {sport}/{data_type}/{league_canonical_id} (saison {season}) sous "
            f"schema_version {stored_schema!r}, incompatible avec le schéma courant. Réécriture nécessaire."
        )

    log_decision(sport, data_type, league_canonical_id, season, snapshot["provider"], "STALE_FALLBACK", errors)
    canonical = _deserialize(snapshot["payload"])
    fetched_at = datetime.fromisoformat(snapshot["fetched_at"])
    return DataEnvelope(
        payload=canonical,
        provider=snapshot["provider"],
        event_time=canonical.event_time,
        published_time=canonical.published_time,
        available_to_model_time=fetched_at,
        fetched_at=fetched_at,
        ingested_at=datetime.now(timezone.utc),
        data_quality=quality.data_quality(snapshot["provider"], data_type),
        freshness_score=quality.freshness_score(fetched_at, datetime.now(timezone.utc), data_type),
        stale=True,
    )
