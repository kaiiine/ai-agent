"""Tests for src/agents/search/tools.py — web_research_report, web_search_news."""
import pytest
from unittest.mock import patch, MagicMock, call


def _make_tavily_client(results):
    """Return a mock TavilyClient that .search() returns the given results list."""
    mock_client = MagicMock()
    mock_client.search.return_value = {"results": results}
    return mock_client


def _tavily_results(n=3):
    return [
        {"title": f"Article {i}", "url": f"http://r{i}.com",
         "content": f"Content {i}", "score": float(i)}
        for i in range(n)
    ]


# TavilyClient and DDGS are imported inside the tool functions, so patch at the package level
_TAVILY_CLS = "tavily.TavilyClient"
_DDGS_CLS   = "ddgs.DDGS"


# ── web_research_report — DDGS import bug regression ─────────────────────────

def test_web_research_report_fallback_imports_ddgs():
    """
    Regression: DDGS was called without 'from ddgs import DDGS' in the Tavily fallback.
    When Tavily returns < 3 results, the fallback must not raise NameError.
    """
    from src.agents.search.tools import web_research_report

    mock_client = _make_tavily_client(_tavily_results(1))  # < 3 → triggers DDG fallback

    mock_ddgs_instance = MagicMock()
    mock_ddgs_instance.text.return_value = [
        {"title": "DDG result", "href": "http://ddg.com", "body": "DDG content"},
    ]

    with patch(_TAVILY_CLS, return_value=mock_client), \
         patch(_DDGS_CLS, return_value=mock_ddgs_instance):
        result = web_research_report.invoke({"query": "test query"})

    assert isinstance(result, str)
    assert "test query" in result


def test_web_research_report_always_queries_ddg():
    """DuckDuckGo is a COMPLEMENT now, not a fallback — it always runs.

    This test used to assert the opposite: with ≥ 3 Tavily results, DDGS.text()
    must NOT be called. That gate made the second engine almost never fire —
    measured on four real queries, it fired ZERO times — so its coverage was
    installed (the package is there, no API key) and never used.

    Nothing legitimate was traded away: DuckDuckGo costs no credit, and latency
    did not move (2.4 / 1.9 / 3.3 / 1.5 s after, against 3.0 / 1.5 / 3.3 / 2.3 s
    before). Distinct domains across the same four queries went from 27 to 33.
    """
    from src.agents.search.tools import web_research_report

    mock_client = _make_tavily_client(_tavily_results(5))

    mock_ddgs_instance = MagicMock()
    mock_ddgs_instance.text.return_value = [
        {"title": "DDG only", "href": "http://ddg-only.com", "body": "…"},
    ]

    with patch(_TAVILY_CLS, return_value=mock_client), \
         patch(_DDGS_CLS, return_value=mock_ddgs_instance):
        result = web_research_report.invoke({"query": "python async"})

    mock_ddgs_instance.text.assert_called_once()
    assert "python async" in result
    assert "ddg-only.com" in result, "the second engine must reach the report"


def test_web_research_report_merges_without_duplicates():
    """The same page found by both engines counts once.

    Without normalisation, `http://r1.com` and `https://www.r1.com/` would be
    listed as two separate sources — the user would count coverage that does
    not exist.
    """
    from src.agents.search.tools import web_research_report

    mock_client = _make_tavily_client(_tavily_results(3))

    mock_ddgs_instance = MagicMock()
    mock_ddgs_instance.text.return_value = [
        {"title": "same page", "href": "https://www.r1.com/", "body": "…"},
    ]

    with patch(_TAVILY_CLS, return_value=mock_client), \
         patch(_DDGS_CLS, return_value=mock_ddgs_instance):
        result = web_research_report.invoke({"query": "dedup"})

    # Compter les occurrences BRUTES serait faux : chaque résultat figure dans
    # la liste des sources ET dans son bloc de citation, où l'URL apparaît deux
    # fois. On compte les ENTRÉES numérotées de la liste de sources.
    import re
    entrees = [l for l in result.splitlines() if re.match(r"^\s*\d+\.\s+\*\*", l)]
    assert sum(1 for l in entrees if "r1.com" in l) <= 1


def test_web_research_report_returns_markdown_structure():
    from src.agents.search.tools import web_research_report

    mock_client = _make_tavily_client([
        {"title": "Test Article", "url": "http://example.com/article",
         "content": "Detailed content.", "score": 0.9},
        {"title": "Second Article", "url": "http://example.com/second",
         "content": "More content.", "score": 0.7},
        {"title": "Third Article", "url": "http://example.com/third",
         "content": "Even more.", "score": 0.5},
    ])

    with patch(_TAVILY_CLS, return_value=mock_client):
        result = web_research_report.invoke({"query": "unit testing python"})

    assert "# Recherche" in result
    assert "## Sources" in result
    assert "Test Article" in result


def test_web_research_report_tavily_error_propagates():
    """Tavily API errors are not silently swallowed — they propagate."""
    from src.agents.search.tools import web_research_report

    mock_client = MagicMock()
    mock_client.search.side_effect = Exception("API key invalid")

    with patch(_TAVILY_CLS, return_value=mock_client):
        with pytest.raises(Exception, match="API key invalid"):
            web_research_report.invoke({"query": "test"})


def test_web_research_report_days_filter_sets_topic():
    """When days > 0, topic must be overridden to 'news'."""
    from src.agents.search.tools import web_research_report

    mock_client = _make_tavily_client(_tavily_results(5))

    with patch(_TAVILY_CLS, return_value=mock_client):
        web_research_report.invoke({"query": "recent news", "days": 3})

    call_kwargs = mock_client.search.call_args.kwargs
    assert call_kwargs.get("days") == 3
    assert call_kwargs.get("topic") == "news"


# ── web_search_news ───────────────────────────────────────────────────────────

def _make_ddgs_news(articles=None):
    if articles is None:
        articles = [
            {"title": "Big news", "url": "http://news.com/1",
             "body": "Something happened.", "date": "2026-01-01", "source": "news.com"},
        ]
    mock_instance = MagicMock()
    mock_instance.news.return_value = articles
    return mock_instance


def test_web_search_news_returns_string():
    from src.agents.search.tools import web_search_news

    mock_ddgs = _make_ddgs_news()

    with patch(_DDGS_CLS, return_value=mock_ddgs):
        result = web_search_news.invoke({"query": "latest AI news"})

    assert isinstance(result, str)
    assert "Big news" in result


def test_web_search_news_no_results():
    from src.agents.search.tools import web_search_news

    mock_ddgs = MagicMock()
    mock_ddgs.news.return_value = []

    with patch(_DDGS_CLS, return_value=mock_ddgs):
        result = web_search_news.invoke({"query": "nonexistent 999xyz"})

    assert isinstance(result, str)
    assert "Aucun" in result or "aucun" in result.lower() or "résultat" in result


def test_web_search_news_period_day():
    from src.agents.search.tools import web_search_news

    mock_ddgs = _make_ddgs_news()

    with patch(_DDGS_CLS, return_value=mock_ddgs):
        web_search_news.invoke({"query": "breaking news", "period": "day"})

    kwargs = mock_ddgs.news.call_args.kwargs
    assert kwargs.get("timelimit") == "d"


def test_web_search_news_period_week():
    from src.agents.search.tools import web_search_news

    mock_ddgs = _make_ddgs_news()

    with patch(_DDGS_CLS, return_value=mock_ddgs):
        web_search_news.invoke({"query": "weekly news", "period": "week"})

    kwargs = mock_ddgs.news.call_args.kwargs
    assert kwargs.get("timelimit") == "w"


def test_web_search_news_period_month():
    from src.agents.search.tools import web_search_news

    mock_ddgs = _make_ddgs_news()

    with patch(_DDGS_CLS, return_value=mock_ddgs):
        web_search_news.invoke({"query": "monthly", "period": "month"})

    kwargs = mock_ddgs.news.call_args.kwargs
    assert kwargs.get("timelimit") == "m"


def test_web_search_news_fallback_to_text_on_news_error():
    """If DDGS.news() raises, should fall back to DDGS.text()."""
    from src.agents.search.tools import web_search_news

    mock_ddgs = MagicMock()
    mock_ddgs.news.side_effect = Exception("rate limit")
    mock_ddgs.text.return_value = [
        {"title": "Text fallback", "href": "http://x.com", "body": "content"},
    ]

    with patch(_DDGS_CLS, return_value=mock_ddgs):
        result = web_search_news.invoke({"query": "test"})

    assert isinstance(result, str)
