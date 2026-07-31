"""Découverte de PROVIDERS candidats via Tavily (wave 2 §8) — pour les sports bloqués
`EXTERNAL_PROVIDER_REQUIRED`.

RÈGLE DURE : Tavily sert UNIQUEMENT à découvrir des SOURCES candidates. Il ne devient
JAMAIS une source de probabilités, de features statistiques, ni un dataset d'entraînement.
Aucune page web arbitraire n'est promue en donnée réelle : une `ProviderCandidate` est un
POINTEUR à valider (accès structuré, historique, identité, licence) avant toute intégration.

Réutilise le client Tavily existant (`tavily.TavilyClient`, cf. src/agents/search/tools.py).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlparse


@dataclass(frozen=True)
class ProviderCandidate:
    provider_name: str
    source_url: str
    snippet: str
    sports: tuple[str, ...] = ()
    structured_access: str = "UNKNOWN"       # API | DATASET | HTML | UNKNOWN
    auth_required: str = "UNKNOWN"           # YES | NO | UNKNOWN
    provenance: str = "tavily_discovery"
    validation_status: str = "DISCOVERED"    # DISCOVERED = trouvé, PAS validé ni exploité

    @property
    def domain(self) -> str:
        return _norm_domain(self.source_url)


def _norm_domain(url: str) -> str:
    try:
        return urlparse(url).netloc.lower().removeprefix("www.")
    except Exception:
        return ""


# Indices heuristiques (transparents) d'accès structuré — jamais une preuve, juste un tri.
_DATASET_HINTS = ("github.com", "kaggle.com", ".csv", "/datasets", "data.")
_API_HINTS = ("api.", "/api", "developer.", "rapidapi.com")


def _classify(url: str, snippet: str) -> tuple[str, str]:
    low = f"{url} {snippet}".lower()
    if any(h in low for h in _API_HINTS):
        access = "API"
    elif any(h in low for h in _DATASET_HINTS):
        access = "DATASET"
    else:
        access = "HTML"
    auth = "YES" if any(k in low for k in ("api key", "api_key", "token", "subscription", "sign up")) else "UNKNOWN"
    return access, auth


def _to_candidates(results: list[dict]) -> list[ProviderCandidate]:
    out: list[ProviderCandidate] = []
    seen: set[str] = set()
    for r in results:
        url = r.get("url") or ""
        if not url:
            continue
        dom = _norm_domain(url)
        if dom in seen:
            continue
        seen.add(dom)
        snippet = (r.get("content") or r.get("snippet") or "")[:400]
        access, auth = _classify(url, snippet)
        out.append(ProviderCandidate(
            provider_name=dom, source_url=url, snippet=snippet,
            structured_access=access, auth_required=auth))
    return out


def discover_provider_candidates(
    query: str, *, max_results: int = 8, search=None,
) -> list[ProviderCandidate]:
    """Interroge Tavily et renvoie des `ProviderCandidate` (statut DISCOVERED — jamais
    validées ni exploitées). `search` injectable pour les tests hermétiques."""
    if search is None:   # pragma: no cover (réseau réel)
        from tavily import TavilyClient
        client = TavilyClient()
        def search(q):
            return client.search(query=q, max_results=max_results, search_depth="advanced")
    data = search(query)
    results = data.get("results", []) if isinstance(data, dict) else list(data)
    return _to_candidates(results)
