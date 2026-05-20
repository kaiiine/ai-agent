"""Tests for src/agents/mermaid/tools.py — mermaid_diagram, _inject_dark_theme."""
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock


# ── _inject_dark_theme ────────────────────────────────────────────────────────

def test_inject_dark_theme_adds_directive():
    from src.agents.mermaid.tools import _inject_dark_theme
    definition = "graph TD\n  A --> B"
    result = _inject_dark_theme(definition)
    assert '%%{init' in result
    assert '"theme": "dark"' in result


def test_inject_dark_theme_does_not_duplicate():
    from src.agents.mermaid.tools import _inject_dark_theme
    definition = '%%{init: {"theme": "dark"}}%%\ngraph TD\n  A --> B'
    result = _inject_dark_theme(definition)
    assert result.count("%%{init") == 1


def test_inject_dark_theme_preserves_definition():
    from src.agents.mermaid.tools import _inject_dark_theme
    definition = "sequenceDiagram\n  Alice->>Bob: Hello"
    result = _inject_dark_theme(definition)
    assert "sequenceDiagram" in result
    assert "Alice->>Bob: Hello" in result


# ── mermaid_diagram — export_to mode ─────────────────────────────────────────

def test_mermaid_diagram_creates_file(tmp_path):
    from src.agents.mermaid.tools import mermaid_diagram

    out = tmp_path / "diagram.html"
    with patch("src.agents.mermaid.tools._open_in_browser"):
        result = mermaid_diagram.invoke({
            "definition": "graph LR\n  A --> B",
            "title": "Test",
            "export_to": str(out),
        })

    assert out.exists()
    assert "Diagramme généré" in result


def test_mermaid_diagram_file_contains_definition(tmp_path):
    from src.agents.mermaid.tools import mermaid_diagram

    out = tmp_path / "rag.html"
    definition = "graph TD\n  Query --> Retriever --> LLM"
    with patch("src.agents.mermaid.tools._open_in_browser"):
        mermaid_diagram.invoke({"definition": definition, "export_to": str(out)})

    content = out.read_text()
    assert "Retriever" in content
    assert "LLM" in content


def test_mermaid_diagram_file_contains_mermaid_cdn(tmp_path):
    from src.agents.mermaid.tools import mermaid_diagram

    out = tmp_path / "arch.html"
    with patch("src.agents.mermaid.tools._open_in_browser"):
        mermaid_diagram.invoke({"definition": "graph LR\n  A --> B", "export_to": str(out)})

    content = out.read_text()
    assert "mermaid" in content
    assert "cdn.jsdelivr.net" in content


def test_mermaid_diagram_creates_parent_dirs(tmp_path):
    from src.agents.mermaid.tools import mermaid_diagram

    out = tmp_path / "public" / "diagrams" / "arch.html"
    with patch("src.agents.mermaid.tools._open_in_browser"):
        mermaid_diagram.invoke({"definition": "graph LR\n  A --> B", "export_to": str(out)})

    assert out.exists()


def test_mermaid_diagram_opens_browser(tmp_path):
    from src.agents.mermaid.tools import mermaid_diagram

    out = tmp_path / "test.html"
    with patch("src.agents.mermaid.tools._open_in_browser") as mock_open:
        mermaid_diagram.invoke({"definition": "graph LR\n  A --> B", "export_to": str(out)})

    mock_open.assert_called_once()


def test_mermaid_diagram_title_in_file(tmp_path):
    from src.agents.mermaid.tools import mermaid_diagram

    out = tmp_path / "titled.html"
    with patch("src.agents.mermaid.tools._open_in_browser"):
        mermaid_diagram.invoke({
            "definition": "graph LR\n  A --> B",
            "title": "Architecture RAG",
            "export_to": str(out),
        })

    content = out.read_text()
    assert "Architecture RAG" in content


# ── mermaid_diagram — temp file mode ─────────────────────────────────────────

def test_mermaid_diagram_no_export_to_uses_tempfile():
    from src.agents.mermaid.tools import mermaid_diagram

    with patch("src.agents.mermaid.tools._open_in_browser") as mock_open:
        result = mermaid_diagram.invoke({"definition": "graph LR\n  A --> B"})

    mock_open.assert_called_once()
    assert "Diagramme généré" in result


def test_mermaid_diagram_tempfile_is_html():
    from src.agents.mermaid.tools import mermaid_diagram

    with patch("src.agents.mermaid.tools._open_in_browser"):
        result = mermaid_diagram.invoke({"definition": "graph LR\n  A --> B"})

    # Path in result should end with .html
    first_line = result.split("\n")[0]
    assert first_line.endswith(".html")


# ── embed snippets ────────────────────────────────────────────────────────────

def test_mermaid_diagram_returns_html_embed():
    from src.agents.mermaid.tools import mermaid_diagram

    with patch("src.agents.mermaid.tools._open_in_browser"):
        result = mermaid_diagram.invoke({"definition": "graph LR\n  A --> B"})

    assert "Embed HTML" in result
    assert 'class="mermaid"' in result


def test_mermaid_diagram_returns_react_snippet():
    from src.agents.mermaid.tools import mermaid_diagram

    with patch("src.agents.mermaid.tools._open_in_browser"):
        result = mermaid_diagram.invoke({"definition": "graph LR\n  A --> B"})

    assert "React" in result or "Next.js" in result or "useEffect" in result


# ── dark theme injection ──────────────────────────────────────────────────────

def test_mermaid_diagram_injects_dark_theme_in_html(tmp_path):
    from src.agents.mermaid.tools import mermaid_diagram

    out = tmp_path / "dark.html"
    with patch("src.agents.mermaid.tools._open_in_browser"):
        mermaid_diagram.invoke({
            "definition": "graph LR\n  A --> B",
            "export_to": str(out),
        })

    content = out.read_text()
    assert "dark" in content


# ── _open_in_browser ──────────────────────────────────────────────────────────

def test_open_in_browser_does_not_raise_when_no_opener(tmp_path):
    from src.agents.mermaid.tools import _open_in_browser

    with patch("subprocess.Popen", side_effect=FileNotFoundError):
        _open_in_browser(tmp_path / "test.html")


def test_open_in_browser_tries_xdg_open(tmp_path):
    from src.agents.mermaid.tools import _open_in_browser

    p = tmp_path / "test.html"
    p.touch()

    with patch("subprocess.Popen") as mock_popen:
        mock_popen.return_value = MagicMock()
        _open_in_browser(p)

    assert mock_popen.called
    called_cmd = mock_popen.call_args[0][0]
    assert "xdg-open" in called_cmd or "open" in called_cmd or "wslview" in called_cmd
