from __future__ import annotations
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from typing import Dict, Any, Optional

from langchain_core.tools import tool

_NS = "http://www.w3.org/2005/Atom"
_ARXIV_API = "https://export.arxiv.org/api/query"


def _fetch_arxiv(params: dict) -> list[dict]:
    url = f"{_ARXIV_API}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=15) as r:
        xml = r.read()
    root = ET.fromstring(xml)
    results = []
    for entry in root.findall(f"{{{_NS}}}entry"):
        def t(tag: str) -> str:
            el = entry.find(f"{{{_NS}}}{tag}")
            return el.text.strip() if el is not None and el.text else ""
        arxiv_id = t("id").split("/abs/")[-1]
        authors = [
            a.find(f"{{{_NS}}}name").text.strip()
            for a in entry.findall(f"{{{_NS}}}author")
            if a.find(f"{{{_NS}}}name") is not None
        ]
        results.append({
            "id": arxiv_id,
            "title": t("title").replace("\n", " "),
            "authors": authors[:5],
            "published": t("published")[:10],
            "abstract": t("summary").replace("\n", " ")[:800],
            "url": f"https://arxiv.org/abs/{arxiv_id}",
            "pdf": f"https://arxiv.org/pdf/{arxiv_id}",
        })
    return results


@tool("arxiv_search")
def arxiv_search(
    query: str,
    max_results: int = 8,
    category: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Recherche des articles scientifiques sur arXiv (IA, ML, NLP, etc.).

    Utilise ce tool quand l'utilisateur veut :
    - trouver des papers ou articles de recherche scientifique
    - faire une veille IA/ML ou NLP
    - chercher des publications académiques sur un sujet
    - préparer un état de l'art ou une bibliographie

    Mots-clés : paper, article, recherche, arXiv, IA, machine learning, NLP, publication, académique, LLM

    Args:
        query: mots-clés de recherche (ex: "RAG retrieval augmented generation", "LLM fine-tuning")
        max_results: nombre max de résultats (défaut: 8)
        category: catégorie arXiv optionnelle (ex: "cs.AI", "cs.LG", "cs.CL", "stat.ML")
    Returns:
        {"status": "ok", "papers": [{"id", "title", "authors", "published", "abstract", "url", "pdf"}, ...]}
    """
    try:
        # Restreindre aux catégories IA/ML par défaut pour éviter les faux positifs
        # (ex: "transformer" matche sinon des papiers sur transformateurs électriques)
        if category:
            search_query = f"cat:{category} AND all:{query}"
        else:
            search_query = f"(cat:cs.AI OR cat:cs.LG OR cat:cs.CL OR cat:stat.ML) AND all:{query}"

        params = {
            "search_query": search_query,
            "start": 0,
            "max_results": max_results,
            "sortBy": "relevance",
            "sortOrder": "descending",
        }
        papers = _fetch_arxiv(params)
        return {"status": "ok", "count": len(papers), "papers": papers}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@tool("arxiv_get_paper")
def arxiv_get_paper(arxiv_id: str) -> Dict[str, Any]:
    """
    Récupère les détails complets d'un paper arXiv par son identifiant ou URL.

    Utilise ce tool quand l'utilisateur veut :
    - obtenir le résumé complet d'un paper précis
    - accéder aux détails d'un article arXiv (auteurs, date, abstract)
    - lire un paper dont il a l'ID ou l'URL

    Mots-clés : paper, abstract, arXiv, article, résumé, auteurs, recherche scientifique

    Args:
        arxiv_id: ID arXiv (ex: "2301.07041") ou URL arXiv
    Returns:
        {"status": "ok", "paper": {"title", "authors", "abstract", "url", "pdf", "published"}}
    """
    try:
        # Nettoie l'ID si c'est une URL
        aid = arxiv_id.strip()
        if "arxiv.org" in aid:
            aid = aid.rstrip("/").split("/")[-1]
        params = {"id_list": aid, "max_results": 1}
        papers = _fetch_arxiv(params)
        if not papers:
            return {"status": "not_found", "error": f"Paper introuvable : {arxiv_id}"}
        return {"status": "ok", "paper": papers[0]}
    except Exception as e:
        return {"status": "error", "error": str(e)}
