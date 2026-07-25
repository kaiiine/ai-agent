"""Orchestration du fallback entre providers — sélection hiérarchique déterministe (PRD §4.4).

v1 : pas de provider_score composite (facteurs non calibrés sur données réelles) —
une cascade de critères éliminatoires, dans l'ordre : capability → saison → quota
→ priorité déclarée → coût. data_quality est calculé après coup et peut faire
échouer un candidat (passage au suivant), freshness_score est exposé dans la
DataEnvelope mais ne discrimine pas entre providers en v1 (fixtures/standings
décrivent la même date d'événement quel que soit le provider — un gate utile
surtout le jour où des endpoints type "injuries" seront ajoutés).
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
# get_sport_module est le mécanisme de découplage core->sport (GW-FR-001) : core
# n'importe jamais un module sportif CONCRET, il passe par le registre. Utilisé
# ici pour le schema_version (C4) ; le câblage complet des normalizers via ce
# même point d'accès est fait à C5.
from src.agents.quant.gateway.sports.registry import get_sport_module
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


def _eligible_providers(sport: str, endpoint: str, season: str) -> list[str]:
    """Capability + saison + quota, dans l'ordre de priorité déclaré, départagé par coût."""
    order = FALLBACK_ORDER.get(sport, [])
    eligible = []
    for name in order:
        entry = REGISTRY.get(name)
        if entry is None:
            continue
        caps = entry.provider.capabilities(sport)
        if not getattr(caps, endpoint, False):
            continue
        if not entry.provider.is_available(sport, season):
            continue
        if not _has_quota(name):
            continue
        eligible.append(name)
    return sorted(eligible, key=lambda n: (order.index(n), REGISTRY[n].provider.query_cost))


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


def fetch_league_data(
    sport: str,
    endpoint: str,  # "fixtures" | "standings"
    provider_league_ids: dict[str, str],  # {"football_data_org": "FL1", "api_sports": "61"}
    league_canonical_id: str,
    season: str,
    resolver: IdentityResolver,
    date_from: str | None = None,
    date_to: str | None = None,
) -> DataEnvelope:
    """Récupère fixtures/standings d'une ligue via le premier provider éligible.

    Ne lève jamais d'exception réseau vers l'appelant : si tous les providers
    échouent, retombe sur le dernier snapshot connu du point_in_time_store
    (stale=True). Lève NoDataAvailableError seulement si rien n'existe nulle part.
    """
    cache_key = f"{sport}:{endpoint}:{league_canonical_id}:{season}:{date_from}:{date_to}"
    cached = cache_get(cache_key, endpoint)
    if cached is not None:
        canonical = _deserialize(cached["canonical"])
        effective_time = canonical.published_time or canonical.event_time or datetime.fromisoformat(cached["fetched_at"])
        log_decision(sport, endpoint, league_canonical_id, season, cached["provider"], "CACHE_HIT", [])
        return DataEnvelope(
            payload=canonical,
            provider=cached["provider"],
            event_time=canonical.event_time,
            published_time=canonical.published_time,
            available_to_model_time=datetime.fromisoformat(cached["fetched_at"]),
            fetched_at=datetime.fromisoformat(cached["fetched_at"]),
            ingested_at=datetime.now(timezone.utc),
            data_quality=quality.data_quality(cached["provider"], endpoint),
            freshness_score=quality.freshness_score(effective_time, datetime.now(timezone.utc), endpoint),
        )

    errors: list[str] = []

    for provider_name in _eligible_providers(sport, endpoint, season):
        entry = REGISTRY[provider_name]
        provider_league_id = provider_league_ids.get(provider_name)
        if not provider_league_id:
            continue

        try:
            _record_request(provider_name)
            fetched_at = datetime.now(timezone.utc)

            if endpoint == "fixtures":
                raw = entry.provider.fetch_league_fixtures(sport, provider_league_id, season, date_from, date_to)
                canonical = entry.normalizer.normalize_fixtures(raw, resolver, league_canonical_id, season)
            else:
                raw = entry.provider.fetch_standings(sport, provider_league_id, season)
                canonical = entry.normalizer.normalize_standings(raw, resolver, league_canonical_id)

            effective_time = canonical.published_time or canonical.event_time or fetched_at
            data_quality_score = quality.data_quality(provider_name, endpoint)
            if data_quality_score < MIN_DATA_QUALITY:
                errors.append(f"{provider_name}: data_quality {data_quality_score} < seuil {MIN_DATA_QUALITY}")
                continue

            ingested_at = datetime.now(timezone.utc)
            schema_version = get_sport_module(sport).schema_version
            store_write(
                sport=sport,
                entity_id=f"{league_canonical_id}:{season}",
                endpoint=endpoint,
                provider=provider_name,
                payload=_serialize(canonical),
                request_fingerprint=f"{provider_league_id}:{season}:{date_from}:{date_to}",
                fetched_at=fetched_at,
                schema_version=schema_version,
                provider_entity_id=provider_league_id,   # ID natif de la compétition chez le provider
                event_time=canonical.event_time,          # None explicite tant que (b) n'est pas fait (C7)
                published_time=canonical.published_time,   # idem
                available_to_model_time=fetched_at,
                ingested_at=ingested_at,
            )
            cache_set(
                cache_key, endpoint,
                {"canonical": _serialize(canonical), "provider": provider_name, "fetched_at": fetched_at.isoformat()},
            )
            log_decision(sport, endpoint, league_canonical_id, season, provider_name, "LIVE_FETCH", errors)

            return DataEnvelope(
                payload=canonical,
                provider=provider_name,
                event_time=canonical.event_time,
                published_time=canonical.published_time,
                available_to_model_time=fetched_at,
                fetched_at=fetched_at,
                ingested_at=ingested_at,
                data_quality=data_quality_score,
                freshness_score=quality.freshness_score(effective_time, fetched_at, endpoint),
            )
        except Exception as e:
            errors.append(f"{provider_name}: {e}")
            continue

    # entity_id inclut la saison : un snapshot 2024 ne doit jamais servir de recours
    # pour une requête saison 2026 (ce serait de la fausse fraîcheur silencieuse).
    snapshot = last_snapshot(sport, f"{league_canonical_id}:{season}", endpoint)
    if snapshot is None:
        log_decision(sport, endpoint, league_canonical_id, season, None, "NO_DATA_AVAILABLE", errors)
        raise NoDataAvailableError(
            f"Aucune donnée pour {sport}/{endpoint}/{league_canonical_id} (saison {season}). "
            f"Providers essayés : {'; '.join(errors) if errors else 'aucun éligible'}."
        )

    # GW-FR-009 : un snapshot stocké sous un schéma incompatible n'est jamais
    # réinterprété avec le schéma courant — échec explicite plutôt que silence.
    stored_schema = snapshot.get("schema_version")
    if not get_sport_module(sport).is_schema_compatible(stored_schema or ""):
        log_decision(sport, endpoint, league_canonical_id, season, snapshot["provider"], "SCHEMA_INCOMPATIBLE", errors)
        raise NoDataAvailableError(
            f"Dernier snapshot pour {sport}/{endpoint}/{league_canonical_id} (saison {season}) sous "
            f"schema_version {stored_schema!r}, incompatible avec le schéma courant du sport. "
            f"Réécriture nécessaire (cf. migration des snapshots)."
        )

    log_decision(sport, endpoint, league_canonical_id, season, snapshot["provider"], "STALE_FALLBACK", errors)
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
        data_quality=quality.data_quality(snapshot["provider"], endpoint),
        freshness_score=quality.freshness_score(fetched_at, datetime.now(timezone.utc), endpoint),
        stale=True,
    )
