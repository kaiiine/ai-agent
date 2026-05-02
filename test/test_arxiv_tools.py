"""Tests for src/agents/arxiv/tools.py — arxiv_search, arxiv_get_paper."""
import pytest
from unittest.mock import patch, MagicMock
import xml.etree.ElementTree as ET

_NS = "http://www.w3.org/2005/Atom"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_atom_xml(entries: list[dict]) -> bytes:
    """Build a minimal Atom XML response like the arXiv API returns."""
    root = ET.Element(f"{{{_NS}}}feed")
    for e in entries:
        entry = ET.SubElement(root, f"{{{_NS}}}entry")
        ET.SubElement(entry, f"{{{_NS}}}id").text = f"https://arxiv.org/abs/{e['id']}"
        ET.SubElement(entry, f"{{{_NS}}}title").text = e.get("title", "Test Title")
        ET.SubElement(entry, f"{{{_NS}}}summary").text = e.get("abstract", "Test abstract.")
        ET.SubElement(entry, f"{{{_NS}}}published").text = e.get("published", "2024-01-15T00:00:00Z")
        for author_name in e.get("authors", ["Alice", "Bob"]):
            author = ET.SubElement(entry, f"{{{_NS}}}author")
            ET.SubElement(author, f"{{{_NS}}}name").text = author_name
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _mock_urlopen(xml_bytes: bytes):
    """Return a context manager mock that yields an object with .read()."""
    mock_resp = MagicMock()
    mock_resp.read.return_value = xml_bytes
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    return mock_resp


# ── arxiv_search ──────────────────────────────────────────────────────────────

def test_arxiv_search_returns_papers():
    from src.agents.arxiv.tools import arxiv_search

    xml = _make_atom_xml([
        {"id": "2301.07041", "title": "RAG paper", "authors": ["Smith"]},
        {"id": "2302.00001", "title": "LLM paper", "authors": ["Jones"]},
    ])
    with patch("urllib.request.urlopen", return_value=_mock_urlopen(xml)):
        result = arxiv_search.invoke({"query": "retrieval augmented generation"})

    assert result["status"] == "ok"
    assert result["count"] == 2
    assert len(result["papers"]) == 2


def test_arxiv_search_paper_fields():
    from src.agents.arxiv.tools import arxiv_search

    xml = _make_atom_xml([{
        "id": "2301.07041",
        "title": "RAG paper",
        "authors": ["Smith", "Jones"],
        "abstract": "We present a method.",
        "published": "2024-03-10T00:00:00Z",
    }])
    with patch("urllib.request.urlopen", return_value=_mock_urlopen(xml)):
        result = arxiv_search.invoke({"query": "rag"})

    paper = result["papers"][0]
    assert paper["id"] == "2301.07041"
    assert paper["title"] == "RAG paper"
    assert "Smith" in paper["authors"]
    assert paper["published"] == "2024-03-10"
    assert "arxiv.org/abs/2301.07041" in paper["url"]
    assert "arxiv.org/pdf/2301.07041" in paper["pdf"]


def test_arxiv_search_with_category():
    from src.agents.arxiv.tools import arxiv_search

    xml = _make_atom_xml([{"id": "2301.07041", "title": "CS paper"}])
    with patch("urllib.request.urlopen", return_value=_mock_urlopen(xml)) as mock_open:
        arxiv_search.invoke({"query": "transformers", "category": "cs.CL"})

    # The URL built should contain the category restriction
    call_url = mock_open.call_args[0][0]
    assert "cat%3Acs.CL" in call_url or "cat:cs.CL" in call_url


def test_arxiv_search_without_category_uses_default_filter():
    from src.agents.arxiv.tools import arxiv_search

    xml = _make_atom_xml([{"id": "2301.07041", "title": "ML paper"}])
    with patch("urllib.request.urlopen", return_value=_mock_urlopen(xml)) as mock_open:
        arxiv_search.invoke({"query": "transformers"})

    call_url = mock_open.call_args[0][0]
    assert "cs.AI" in call_url or "cat%3Acs" in call_url


def test_arxiv_search_empty_results():
    from src.agents.arxiv.tools import arxiv_search

    xml = _make_atom_xml([])
    with patch("urllib.request.urlopen", return_value=_mock_urlopen(xml)):
        result = arxiv_search.invoke({"query": "zzz_nonexistent_topic"})

    assert result["status"] == "ok"
    assert result["count"] == 0
    assert result["papers"] == []


def test_arxiv_search_network_error():
    from src.agents.arxiv.tools import arxiv_search

    with patch("urllib.request.urlopen", side_effect=Exception("Network unreachable")):
        result = arxiv_search.invoke({"query": "rag"})

    assert result["status"] == "error"
    assert "Network unreachable" in result["error"]


def test_arxiv_search_respects_max_results():
    from src.agents.arxiv.tools import arxiv_search

    xml = _make_atom_xml([{"id": f"23{i:02d}.00001", "title": f"Paper {i}"} for i in range(3)])
    with patch("urllib.request.urlopen", return_value=_mock_urlopen(xml)) as mock_open:
        arxiv_search.invoke({"query": "test", "max_results": 3})

    call_url = mock_open.call_args[0][0]
    assert "max_results=3" in call_url


def test_arxiv_search_authors_capped_at_five():
    from src.agents.arxiv.tools import arxiv_search

    xml = _make_atom_xml([{
        "id": "2301.07041",
        "title": "Big team paper",
        "authors": [f"Author{i}" for i in range(10)],
    }])
    with patch("urllib.request.urlopen", return_value=_mock_urlopen(xml)):
        result = arxiv_search.invoke({"query": "test"})

    assert len(result["papers"][0]["authors"]) <= 5


# ── arxiv_get_paper ───────────────────────────────────────────────────────────

def test_arxiv_get_paper_by_id():
    from src.agents.arxiv.tools import arxiv_get_paper

    xml = _make_atom_xml([{
        "id": "2301.07041",
        "title": "Specific Paper",
        "abstract": "Full abstract here.",
    }])
    with patch("urllib.request.urlopen", return_value=_mock_urlopen(xml)):
        result = arxiv_get_paper.invoke({"arxiv_id": "2301.07041"})

    assert result["status"] == "ok"
    assert result["paper"]["title"] == "Specific Paper"


def test_arxiv_get_paper_strips_url():
    from src.agents.arxiv.tools import arxiv_get_paper

    xml = _make_atom_xml([{"id": "2301.07041", "title": "Paper"}])
    with patch("urllib.request.urlopen", return_value=_mock_urlopen(xml)) as mock_open:
        arxiv_get_paper.invoke({"arxiv_id": "https://arxiv.org/abs/2301.07041"})

    call_url = mock_open.call_args[0][0]
    assert "id_list=2301.07041" in call_url


def test_arxiv_get_paper_trailing_slash_url():
    from src.agents.arxiv.tools import arxiv_get_paper

    xml = _make_atom_xml([{"id": "2301.07041", "title": "Paper"}])
    with patch("urllib.request.urlopen", return_value=_mock_urlopen(xml)) as mock_open:
        arxiv_get_paper.invoke({"arxiv_id": "https://arxiv.org/abs/2301.07041/"})

    call_url = mock_open.call_args[0][0]
    assert "id_list=2301.07041" in call_url


def test_arxiv_get_paper_not_found():
    from src.agents.arxiv.tools import arxiv_get_paper

    xml = _make_atom_xml([])
    with patch("urllib.request.urlopen", return_value=_mock_urlopen(xml)):
        result = arxiv_get_paper.invoke({"arxiv_id": "9999.99999"})

    assert result["status"] == "not_found"


def test_arxiv_get_paper_network_error():
    from src.agents.arxiv.tools import arxiv_get_paper

    with patch("urllib.request.urlopen", side_effect=Exception("timeout")):
        result = arxiv_get_paper.invoke({"arxiv_id": "2301.07041"})

    assert result["status"] == "error"
    assert "timeout" in result["error"]
