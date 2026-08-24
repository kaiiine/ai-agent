from __future__ import annotations

import re
import textwrap
from typing import Any, Dict, List, Literal, Optional
from urllib.parse import urlparse

from langchain_core.tools import tool

from ...infra.settings import settings


# ── Helpers ───────────────────────────────────────────────────────────────────

def _domain_of(url: str) -> str:
    try:
        return urlparse(url).netloc.lower()
    except Exception:
        return ""


def _first_content(d: Dict[str, Any]) -> str:
    """Retourne le meilleur contenu textuel d'un résultat, quelle que soit la clé."""
    for key in ("raw_content", "content", "snippet", "body", "text", "summary"):
        v = d.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _normalize(s: str) -> str:
    return re.sub(r"\s+", " ", s, flags=re.UNICODE).strip()


def _clip(s: str, max_chars: int = 600) -> str:
    s = _normalize(s)
    if len(s) <= max_chars:
        return s
    cut = s.rfind(". ", 0, max_chars)
    return s[: cut if cut > 0 else max_chars].rstrip() + "…"


def _score(d: Dict[str, Any]) -> float:
    try:
        return float(d.get("score", 0))
    except Exception:
        return 0.0


def _ensure_list(obj: Any) -> List[Dict[str, Any]]:
    if isinstance(obj, list):
        return obj
    if isinstance(obj, dict):
        r = obj.get("results", [])
        return r if isinstance(r, list) else []
    return []


def _cle_url(url: str) -> str:
    """Identité d'un résultat, pour dédoublonner entre moteurs.

    Deux moteurs rendent la même page avec des URL qui ne sont pas identiques au
    caractère près : `https://` ou `http://`, `www.` ou non, slash final,
    paramètres de suivi. Comparer les chaînes brutes laisserait passer des
    doublons que l'utilisateur compterait comme deux sources.
    """
    try:
        p = urlparse(url)
        hote = p.netloc.lower().removeprefix("www.")
        return f"{hote}{p.path.rstrip('/')}"
    except Exception:                                        # noqa: BLE001
        return url


def _ddg_period(days: int) -> str:
    """Convertit un nombre de jours en timelimit DuckDuckGo."""
    if days <= 1:
        return "d"
    if days <= 7:
        return "w"
    return "m"


# ── Tool 1 : recherche web approfondie (Tavily) ───────────────────────────────

@tool("web_research_report")
def web_research_report(
    query: str,
    max_results: int = 10,
    days: int = 0,
    topic: str = "general",
    include_answer: bool = False,
) -> str:
    """
    Effectue une recherche web approfondie et retourne un rapport Markdown avec sources et citations.

    Utilise ce tool quand l'utilisateur veut :
    - rechercher des informations sur internet / le web
    - connaître des faits, de la documentation, des articles en ligne
    - faire une veille ou vérifier des données récentes sur un sujet

    Pour les ÉVÉNEMENTS RÉCENTS (< 30 jours) → préférer web_search_news qui est plus rapide et précis.
    Pour les recherches approfondies avec contexte → utiliser ce tool avec days= et topic="news".

    Mots-clés : recherche web, internet, documentation, article, wikipedia, faits, vérifier

    Args:
        query:          requête de recherche
        max_results:    nombre de sources (défaut 10)
        days:           filtrer aux derniers N jours (0 = pas de filtre).
                        Ex: days=3 pour les 3 derniers jours, days=7 pour la semaine.
        topic:          "general" (défaut) | "news" (actualités) | "finance" (marchés)
                        Utiliser "news" quand la requête concerne l'actualité récente.
        include_answer: inclure le résumé synthétique de Tavily si disponible
    Returns:
        Rapport Markdown avec sources, citations et dates.
    """
    from tavily import TavilyClient

    client = TavilyClient()

    kwargs: Dict[str, Any] = {
        "query":              query,
        "max_results":        max_results,
        "include_raw_content": "markdown",   # contenu complet en markdown (bien mieux que les snippets)
        "include_answer":     include_answer,
    }

    # Recency filtering — paramètres clés manquants dans l'ancienne version
    if days > 0:
        kwargs["days"]  = days
        kwargs["topic"] = "news"             # days= n'est supporté qu'avec topic="news"
    elif topic != "general":
        kwargs["topic"] = topic

    data: Dict[str, Any] = client.search(**kwargs)
    results: List[Dict[str, Any]] = _ensure_list(data)
    # Trié, PAS tronqué : la coupe se fait après la fusion avec DuckDuckGo,
    # sinon on garderait 10 résultats Tavily puis on en empilerait 10 autres.
    results = sorted(results, key=_score, reverse=True)

    # ── DuckDuckGo en COMPLÉMENT, plus en secours ────────────────────────────
    # Il ne se déclenchait qu'en dessous de 3 résultats Tavily, donc presque
    # jamais : mesuré sur quatre requêtes réelles, ZÉRO fois. La couverture d'un
    # second moteur était donc installée — le paquet est là, sans clé — et
    # jamais utilisée. Systématique, il apporte les pages que Tavily classe mal,
    # pour zéro crédit et un aller-retour réseau.
    try:
        from ddgs import DDGS
        tl = _ddg_period(days) if days > 0 else None
        for r in DDGS().text(query, max_results=max_results, timelimit=tl):
            results.append({
                "title":   r.get("title", ""),
                "url":     r.get("href", r.get("url", "")),
                "content": r.get("body", ""),
                "score":   0.0,
                "_source": "duckduckgo",
            })
    except Exception:                                        # noqa: BLE001
        pass   # DuckDuckGo indisponible — on continue avec ce qu'on a

    # Dédoublonnage APRÈS fusion, en gardant la PREMIÈRE occurrence : Tavily est
    # devant, et sa version d'une page porte un score et le markdown complet là
    # où DuckDuckGo ne donne qu'un extrait.
    #
    # On ne re-trie pas : les résultats DuckDuckGo ont `score: 0.0` et
    # couleraient tous en bas. L'ordre voulu est « Tavily par pertinence, puis
    # les apports du second moteur ».
    vus: set[str] = set()
    uniques: List[Dict[str, Any]] = []
    for r in results:
        cle = _cle_url(r.get("url", ""))
        if cle and cle not in vus:
            vus.add(cle)
            uniques.append(r)

    # Des places RÉSERVÉES au second moteur, sinon il n'en obtient aucune.
    # Première version mesurée : couper à `max_results` après fusion ne changeait
    # rien — Tavily remplit déjà les dix places, DuckDuckGo arrive derrière et
    # tombe hors de la coupe. Gain constaté : +2 domaines sur QUATRE requêtes,
    # et seulement là où Tavily avait rendu moins de dix résultats.
    #
    # On garde donc le haut du classement Tavily, puis on complète avec ce que
    # DuckDuckGo apporte EN PLUS, et on retombe sur Tavily si le second moteur
    # n'a rien de neuf. Le total reste borné à `max_results`.
    part_seconde = max(2, max_results // 3)
    premiers = [r for r in uniques if r.get("_source") != "duckduckgo"]
    seconds = [r for r in uniques if r.get("_source") == "duckduckgo"]

    retenus = premiers[:max_results - part_seconde] + seconds[:part_seconde]
    if len(retenus) < max_results:
        deja = {id(r) for r in retenus}
        retenus += [r for r in premiers + seconds if id(r) not in deja][
            : max_results - len(retenus)]
    results = retenus[:max_results]

    # ── Construction du rapport Markdown ──────────────────────────────────────
    sources_lines: List[str] = []
    quote_blocks: List[str] = []

    for idx, r in enumerate(results, 1):
        title = r.get("title") or "Sans titre"
        url   = r.get("url") or r.get("link") or ""
        dom   = _domain_of(url) or "source"
        text  = _first_content(r)
        date  = r.get("published_date") or r.get("date") or ""
        src   = " _(DDG)_" if r.get("_source") == "duckduckgo" else ""

        date_str = f" · {date}" if date else ""
        sources_lines.append(f"{idx}. **{title}** — _{dom}{date_str}_{src}  \n   {url}")

        if text:
            quote = _clip(text, max_chars=800)
            quote_blocks.append(
                f"### [{idx}] {title} ({dom}{date_str})\n\n> {quote}\n\n[{url}]({url})\n"
            )

    answer_md = ""
    if include_answer:
        ans = data.get("answer")
        if isinstance(ans, str) and ans.strip():
            answer_md = f"\n## Résumé Tavily\n> {_clip(ans, 600)}\n"

    parts: List[str] = [
        f"# Recherche : {query}\n",
    ]
    if days > 0:
        parts[0] += f"_Filtré aux {days} derniers jours · topic={kwargs.get('topic', 'general')}_\n"

    if answer_md:
        parts.append(answer_md)
    if sources_lines:
        parts.append("## Sources\n" + "\n".join(sources_lines))
    if quote_blocks:
        parts.append("## Extraits\n" + "\n\n".join(quote_blocks))
    if not sources_lines:
        parts.append("_Aucune source trouvée — essaie web_search_news pour les événements très récents._")

    return "\n\n".join(parts).strip()


# ── Tool 2 : recherche d'actualités en temps réel (DuckDuckGo) ───────────────

@tool("web_search_news")
def web_search_news(
    query: str,
    period: str = "week",
    max_results: int = 12,
    region: str = "fr-fr",
) -> str:
    """
    Recherche des actualités récentes via DuckDuckGo News (gratuit, sans API key, temps réel).

    Utilise ce tool quand l'utilisateur veut :
    - connaître des événements récents (dernières heures, jours ou semaine)
    - trouver des news sur une personne, une entreprise, un pays, un sport, un produit
    - vérifier ce qui s'est passé récemment sur un sujet
    - obtenir de l'actualité fraîche non disponible dans les connaissances du modèle

    Exemples de requêtes :
    - "résultats match PSG hier"
    - "news Apple aujourd'hui"
    - "élections France cette semaine"
    - "dernier rapport ChatGPT"

    Mots-clés : news, actualité, récent, aujourd'hui, hier, cette semaine, événement, résultat,
    dernières nouvelles, ce qui s'est passé, annonce, sortie, match, score, résultat sportif

    Args:
        query:       requête de recherche (en français ou en anglais)
        period:      "day"   = dernières 24h
                     "week"  = dernière semaine (défaut)
                     "month" = dernier mois
        max_results: nombre d'articles à retourner (défaut 12)
        region:      région pour les résultats ("fr-fr" défaut, "us-en", "wt-wt" = mondial)
    Returns:
        Liste d'articles avec titre, date, source et extrait.
    """
    _PERIOD_MAP = {"day": "d", "week": "w", "month": "m"}
    timelimit = _PERIOD_MAP.get(period, "w")

    try:
        from ddgs import DDGS  # noqa: F401  (vérifie que le package est dispo)
    except ImportError:
        return "❌ Package `ddgs` non installé. Lance : pip install ddgs"

    try:
        raw = DDGS().news(
            query,
            max_results=max_results,
            timelimit=timelimit,
            region=region,
        )
    except Exception as e:
        # Fallback : recherche texte si news échoue (rate limit, etc.)
        try:
            raw_text = DDGS().text(
                query,
                max_results=max_results,
                timelimit=timelimit,
                region=region,
            )
            raw = [
                {
                    "title":  r.get("title", ""),
                    "url":    r.get("href", ""),
                    "body":   r.get("body", ""),
                    "date":   "",
                    "source": _domain_of(r.get("href", "")),
                }
                for r in raw_text
            ]
        except Exception as e2:
            return f"❌ Erreur DuckDuckGo : {e} / {e2}"

    if not raw:
        return f"Aucun résultat pour « {query} » sur la période « {period} »."

    _period_labels = {"day": "dernières 24h", "week": "dernière semaine", "month": "dernier mois"}
    lines = [f"# Actualités : {query}", f"_Période : {_period_labels.get(period, period)} · {len(raw)} articles_\n"]

    for i, r in enumerate(raw, 1):
        title  = r.get("title", "Sans titre")
        url    = r.get("url", r.get("href", ""))
        body   = _clip(r.get("body", r.get("snippet", "")), max_chars=500)
        date   = r.get("date", r.get("published", ""))
        source = r.get("source", _domain_of(url))

        date_str = f" · {date}" if date else ""
        lines.append(f"### {i}. {title}")
        lines.append(f"_{source}{date_str}_  ")
        if url:
            lines.append(f"[{url}]({url})  ")
        if body:
            lines.append(f"\n> {body}")
        lines.append("")

    return "\n".join(lines).strip()
