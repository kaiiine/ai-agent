from __future__ import annotations
from langchain_core.tools import tool
from langchain_tavily import TavilySearch
from tavily import TavilyClient
from ...infra.settings import settings
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse
import textwrap
import re


def build_search_tool():
    return TavilySearch(max_results=settings.search_max_results)


@tool("web_search")
def web_search(query: str, max_results: int = 5) -> dict:
    """Recherche web (Tavily). Utiliser pour collecter des infos/sources. Répond de manière complète sans rien inventer.
    Args:
      query: requête naturelle
      max_results: optionnel, par défaut settings.search_max_results
    Returns: JSON { query, results: [...] }
    """
    client = TavilyClient(api_key=settings.tavily_api_key)
    k = max_results or settings.search_max_results
    return {"query": query, "results": client.search(query=query, max_results=k)}



# --- helpers -------------------------------------------------------------

def _domain_of(url: str) -> str:
    try:
        netloc = urlparse(url).netloc
        return netloc.lower()
    except Exception:
        return ""

def _first_meaningful_text(d: Dict[str, Any]) -> str:
    """
    Essaie de trouver un contenu textuel dans un résultat Tavily, 
    en tolérant différentes clés selon les versions/params.
    """
    for key in ("content", "snippet", "body", "text", "summary"):
        v = d.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    # parfois Tavily range dans 'raw_content' ou similaire
    v = d.get("raw_content") or d.get("raw") or ""
    return v.strip() if isinstance(v, str) else ""

def _normalize_whitespace(s: str) -> str:
    s = re.sub(r"\s+", " ", s, flags=re.UNICODE).strip()
    return s

def _clip_for_quote(s: str, max_chars: int = 500) -> str:
    s = _normalize_whitespace(s)
    if len(s) <= max_chars:
        return s
    # coupe sur une limite de phrase si possible
    cut = s.rfind(". ", 0, max_chars)
    if cut == -1:
        cut = max_chars
    return s[:cut].rstrip() + "…"

def _bullet_from_text(s: str, max_chars: int = 220) -> str:
    s = _normalize_whitespace(s)
    if len(s) > max_chars:
        s = s[:max_chars].rstrip() + "…"
    return s

def _ensure_list(obj: Any) -> List[Dict[str, Any]]:
    if isinstance(obj, list):
        return obj  # déjà une liste de résultats
    if isinstance(obj, dict) and "results" in obj:
        r = obj["results"]
        return r if isinstance(r, list) else []
    return []

# --- TOOL ----------------------------------------------------------------

@tool("web_research_report")
def web_research_report(
    query: str,
    max_results: int = 10,
    quote_only: bool = True,
    include_answer: bool = False,
    search_depth: str = "advanced",
) -> str:
    """
    Recherche web (Tavily) et retourne un rapport **Markdown** très détaillé,complet, structuré et sans invention.
    - Le contenu est **exclusivement** issu des sources web.
    - Par défaut (quote_only=True), le rapport contient des **citations** + références ; aucune paraphrase libre.
    - Si quote_only=False, ajoute une section "Points à retenir" en formulations prudentes (chaque point cite une source).

    Args:
        query: Requête utilisateur.
        max_results: Nombre de résultats à agréger.
        quote_only: Si True, uniquement des extraits cités (zéro invention).
        include_answer: Si True, tente d'inclure le champ 'answer' de Tavily (quand disponible), étiqueté comme synthèse Tavily.
        search_depth: "basic" | "advanced" (si supporté par ta version Tavily).
    Returns:
        Markdown (str) commençant par "# Réponse".
    """
    client = TavilyClient()  # la clé est lue depuis TAVILY_API_KEY env var, sinon passe api_key="<...>"

    # Appel Tavily (tolérant aux kwargs selon version)
    kwargs = {"query": query, "max_results": max_results}
    # Ces kwargs peuvent ne pas exister selon la version : on essaie et on degrade gracieusement
    try:
        kwargs["search_depth"] = search_depth
    except Exception:
        pass
    try:
        kwargs["include_answer"] = include_answer
    except Exception:
        pass
    try:
        kwargs["include_raw_content"] = True
    except Exception:
        pass

    data: Dict[str, Any] = client.search(**kwargs)  # type: ignore[arg-type]
    results: List[Dict[str, Any]] = _ensure_list(data)

    # Tri léger: score décroissant si dispo
    def _score(d: Dict[str, Any]) -> float:
        s = d.get("score")
        try:
            return float(s)
        except Exception:
            return 0.0

    results = sorted(results, key=_score, reverse=True)[:max_results]

    # Prépare sections
    sources_lines: List[str] = []
    quotes_blocks: List[str] = []
    bullets: List[str] = []

    for idx, r in enumerate(results, start=1):
        title = r.get("title") or r.get("name") or "Sans titre"
        url = r.get("url") or r.get("link") or ""
        dom = _domain_of(url) or "source"
        text = _first_meaningful_text(r)

        # Lignes sources
        sources_lines.append(f"{idx}. **{title}** — _{dom}_  \n   {url}")

        # Extrait cité
        if text:
            quote = _clip_for_quote(text, max_chars=700)
            quotes_blocks.append(
                f"### [{idx}] {title} ({dom})\n\n> {quote}\n\nLien : {url}\n"
            )

            # Points prudents (si autorisés)
            if not quote_only:
                bullets.append(f"- ({idx}) {_bullet_from_text(text)}  \n")

    # Section "Résumé rapide" à partir de Tavily.answer si demandé et présent
    answer_md = ""
    if include_answer:
        ans = data.get("answer")
        if isinstance(ans, str) and ans.strip():
            # On l'étiquette clairement comme synthèse Tavily (pas nous)
            ans = _clip_for_quote(ans, max_chars=550)
            answer_md = textwrap.dedent(f"""
            ## Résumé rapide (synthèse Tavily)
            > {ans}
            """).strip()

    # Construit le Markdown final
    md_parts: List[str] = []
    md_parts.append(f"# Réponse\n\n**Requête :** _{query}_\n\n> Ce rapport compile **uniquement** des informations extraites des sources citées ci-dessous. Aucune information n’est inventée.")
    if answer_md:
        md_parts.append(answer_md)

    if sources_lines:
        md_parts.append("## Sources consultées\n" + "\n".join(sources_lines))

    if quotes_blocks:
        md_parts.append("## Extraits clés (citations)\n" + "\n\n".join(quotes_blocks))

    if not quote_only and bullets:
        md_parts.append("## Points à retenir (formulations prudentes)\n" + "\n".join(bullets))

    if not sources_lines and not quotes_blocks:
        md_parts.append("_Aucune source exploitable n’a été trouvée pour cette requête._")

    return "\n\n".join(md_parts).strip()
