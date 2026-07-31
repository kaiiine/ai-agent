"""Découverte de providers via Tavily (wave 2 §8) — hermétique (search injecté).

Prouve : Tavily produit des POINTEURS (ProviderCandidate, statut DISCOVERED), jamais
une probabilité/feature/dataset promu. Classement d'accès transparent, dédup par domaine.
"""

from __future__ import annotations

from src.agents.quant.gateway.providers.provider_discovery import (
    ProviderCandidate, discover_provider_candidates,
)

_FAKE = {"results": [
    {"url": "https://github.com/JeffSackmann/tennis_atp", "content": "ATP tennis match data CSV, players, dates, surfaces, results 1968-present"},
    {"url": "https://github.com/JeffSackmann/tennis_atp/tree/master", "content": "duplicate domain"},
    {"url": "https://api-tennis.com/documentation", "content": "Tennis API, requires API key subscription"},
    {"url": "https://www.somesportsblog.com/predictions", "content": "our model says player X wins with 72% probability"},
]}


def test_returns_candidates_not_probabilities():
    cands = discover_provider_candidates("tennis historical data", search=lambda q: _FAKE)
    assert all(isinstance(c, ProviderCandidate) for c in cands)
    assert all(c.validation_status == "DISCOVERED" for c in cands)   # jamais "validé/exploité"
    # dédup par domaine (github.com une seule fois).
    assert len({c.domain for c in cands}) == len(cands)


def test_access_and_auth_classification():
    cands = {c.domain: c for c in discover_provider_candidates("tennis", search=lambda q: _FAKE)}
    assert cands["github.com"].structured_access == "DATASET"
    assert cands["api-tennis.com"].structured_access == "API"
    assert cands["api-tennis.com"].auth_required == "YES"           # « API key subscription »


def test_blog_probability_is_only_a_pointer_never_a_source():
    # Un blog affichant « 72% » reste un POINTEUR HTML DISCOVERED — jamais une proba/feature.
    cands = {c.domain: c for c in discover_provider_candidates("tennis", search=lambda q: _FAKE)}
    blog = cands["somesportsblog.com"]
    assert blog.structured_access == "HTML" and blog.validation_status == "DISCOVERED"
