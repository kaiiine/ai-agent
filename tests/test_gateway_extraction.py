"""C7 — extraction (b) event_time/published_time des deux providers + freshness réel.

Vérifie la SYMÉTRIE : chaque normalizer gère explicitement published_time pour
ses data_types. La disponibilité réelle est complémentaire (football-data.org
horodate les matchs via lastUpdated ; api_sports horodate les classements via
update), mais aucun provider n'est ignoré.
"""

from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path

from src.agents.quant.gateway.core.provider_protocol import RawProviderResponse
from src.agents.quant.gateway.core.identity_resolver import IdentityResolver
from src.agents.quant.gateway.core.identity_data import TEAMS
from src.agents.quant.gateway.sports.football.normalizers.football_data_org import FootballDataOrgNormalizer
from src.agents.quant.gateway.sports.football.normalizers.api_sports import ApiSportsNormalizer

FIXTURES = Path(__file__).parent / "fixtures"
_RESOLVER = IdentityResolver(TEAMS)
_L1 = "competition:football:fra:ligue1"


def _raw(payload):
    return RawProviderResponse(payload=payload, provider="p", fetched_at=datetime.now(timezone.utc))


# ── football-data.org : matchs horodatés (lastUpdated), classements NON ──────────

def test_fdo_fixtures_extract_published_time():
    payload = json.loads((FIXTURES / "fl1_2025_matches.json").read_text())
    result = FootballDataOrgNormalizer().normalize_fixtures(_raw(payload), _RESOLVER, _L1, "2025")
    assert result.published_time is not None            # extrait de lastUpdated
    assert result.event_time is None                    # batch : pas d'événement unique


def test_fdo_standings_have_no_published_time():
    payload = json.loads((FIXTURES / "fl1_2025_standings.json").read_text())
    result = FootballDataOrgNormalizer().normalize_standings(_raw(payload), _RESOLVER, _L1)
    assert result.published_time is None                # football-data.org n'horodate pas les classements


# ── api_sports : classements horodatés (update), matchs NON ─────────────────────

def test_apisports_standings_extract_published_time():
    raw = _raw({"standings": [{"league": {"standings": [[
        {"rank": 1, "team": {"id": 85}, "points": 85, "all": {"played": 34}, "update": "2025-05-30T00:00:00+00:00"},
        {"rank": 2, "team": {"id": 81}, "points": 78, "all": {"played": 34}, "update": "2025-05-28T00:00:00+00:00"},
    ]]}}]})
    result = ApiSportsNormalizer().normalize_standings(raw, _RESOLVER, _L1)
    assert result.published_time == datetime(2025, 5, 30, tzinfo=timezone.utc)   # max(update)


def test_apisports_fixtures_have_no_published_time():
    raw = _raw({"fixtures": [{
        "fixture": {"id": 1, "date": "2024-08-16T18:45:00+00:00", "status": {"short": "FT"}},
        "teams": {"home": {"id": 85}, "away": {"id": 81}}, "goals": {"home": 2, "away": 1},
    }]})
    result = ApiSportsNormalizer().normalize_fixtures(raw, _RESOLVER, _L1, "2024")
    assert result.published_time is None                # api_sports n'horodate pas les fixtures


# ── Enveloppe : la fraîcheur reflète la présence/absence de published_time ──────

def test_envelope_freshness_real_when_published_time_present(offline_gateway):
    from src.agents.quant.gateway.core.fallback_chain import fetch_league_data
    from src.agents.quant.gateway.gateway import _resolver
    env = fetch_league_data(sport="football", data_type="RESULTS",
                            league_canonical_id=_L1, season="2025", resolver=_resolver)
    assert env.published_time is not None
    assert env.freshness_basis == "published_time"
    assert env.freshness_degraded is False


def test_envelope_freshness_degraded_when_no_published_time(offline_gateway):
    from src.agents.quant.gateway.core.fallback_chain import fetch_league_data
    from src.agents.quant.gateway.gateway import _resolver
    # football-data.org standings : pas de published_time -> fraîcheur dégradée, SIGNALÉE.
    env = fetch_league_data(sport="football", data_type="STANDINGS",
                            league_canonical_id=_L1, season="2025", resolver=_resolver)
    assert env.published_time is None
    assert env.freshness_basis == "fetched_at"
    assert env.freshness_degraded is True


def test_envelope_carries_v2_identity(offline_gateway):
    from src.agents.quant.gateway.core.fallback_chain import fetch_league_data
    from src.agents.quant.gateway.gateway import _resolver
    env = fetch_league_data(sport="football", data_type="STANDINGS",
                            league_canonical_id=_L1, season="2025", resolver=_resolver)
    assert env.sport == "football"
    assert env.competition_id == _L1
    assert env.data_type == "STANDINGS"
    assert env.schema_version == "football/1.0"
    assert env.provider_entity_id == "FL1"       # ID natif compétition chez le provider
