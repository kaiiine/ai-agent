"""Tests for src/agents/study/tools.py — save_study_file, _extract_html, _output_dir."""
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock


# ── _extract_html ─────────────────────────────────────────────────────────────

def test_extract_html_no_fence():
    from src.agents.study.tools import _extract_html
    raw = "<html><body>Hello</body></html>"
    assert _extract_html(raw) == raw.strip()


def test_extract_html_strips_markdown_fence():
    from src.agents.study.tools import _extract_html
    raw = "```html\n<html><body>Hello</body></html>\n```"
    result = _extract_html(raw)
    assert result == "<html><body>Hello</body></html>"
    assert "```" not in result


def test_extract_html_with_extra_text_around_fence():
    from src.agents.study.tools import _extract_html
    raw = "Here is the HTML:\n```html\n<html/>\n```\nEnd."
    result = _extract_html(raw)
    assert result == "<html/>"


def test_extract_html_strips_whitespace():
    from src.agents.study.tools import _extract_html
    raw = "   <html></html>   "
    assert _extract_html(raw) == "<html></html>"


# ── _output_dir ───────────────────────────────────────────────────────────────

def test_output_dir_creates_directory(tmp_path):
    from src.agents.study.tools import _output_dir
    with patch("src.agents.study.tools.Path.home", return_value=tmp_path):
        d = _output_dir()
    assert d.exists()
    assert d.is_dir()


# ── save_study_file — direct HTML mode ───────────────────────────────────────

def _valid_html():
    return "<html><head><style>body{}</style></head><body>" + "x" * 250 + "</body></html>"


def test_save_study_file_ok(tmp_path):
    from src.agents.study.tools import save_study_file

    with patch("src.agents.study.tools._output_dir", return_value=tmp_path), \
         patch("src.agents.study.tools._open_browser"):
        result = save_study_file.invoke({
            "html": _valid_html(),
            "file_type": "fiche",
            "filename": "test_fiche",
        })

    assert result["status"] == "ok"
    assert "path" in result
    assert Path(result["path"]).exists()


def test_save_study_file_creates_html_file(tmp_path):
    from src.agents.study.tools import save_study_file

    with patch("src.agents.study.tools._output_dir", return_value=tmp_path), \
         patch("src.agents.study.tools._open_browser"):
        result = save_study_file.invoke({
            "html": _valid_html(),
            "file_type": "fiche",
            "filename": "algo_tri",
        })

    p = Path(result["path"])
    assert p.suffix == ".html"
    assert "algo_tri" in p.name


def test_save_study_file_exo_type(tmp_path):
    from src.agents.study.tools import save_study_file

    with patch("src.agents.study.tools._output_dir", return_value=tmp_path), \
         patch("src.agents.study.tools._open_browser"):
        result = save_study_file.invoke({
            "html": _valid_html(),
            "file_type": "exo",
        })

    assert result["status"] == "ok"
    assert "exo" in Path(result["path"]).name


def test_save_study_file_empty_html():
    from src.agents.study.tools import save_study_file
    result = save_study_file.invoke({"html": "", "file_type": "fiche"})
    assert result["status"] == "error"
    assert "vide" in result["error"] or "court" in result["error"]


def test_save_study_file_too_short_html():
    from src.agents.study.tools import save_study_file
    result = save_study_file.invoke({"html": "<html><body>tiny</body></html>", "file_type": "fiche"})
    assert result["status"] == "error"


def test_save_study_file_opens_browser(tmp_path):
    from src.agents.study.tools import save_study_file

    with patch("src.agents.study.tools._output_dir", return_value=tmp_path), \
         patch("src.agents.study.tools._open_browser") as mock_open:
        save_study_file.invoke({"html": _valid_html(), "file_type": "fiche"})

    mock_open.assert_called_once()


def test_save_study_file_strips_markdown_fence(tmp_path):
    from src.agents.study.tools import save_study_file

    html_with_fence = f"```html\n{_valid_html()}\n```"
    with patch("src.agents.study.tools._output_dir", return_value=tmp_path), \
         patch("src.agents.study.tools._open_browser"):
        result = save_study_file.invoke({"html": html_with_fence, "file_type": "fiche"})

    assert result["status"] == "ok"
    content = Path(result["path"]).read_text()
    assert "```" not in content


def test_save_study_file_timestamp_in_filename(tmp_path):
    from src.agents.study.tools import save_study_file
    import re

    with patch("src.agents.study.tools._output_dir", return_value=tmp_path), \
         patch("src.agents.study.tools._open_browser"):
        result = save_study_file.invoke({"html": _valid_html(), "file_type": "fiche", "filename": "cours"})

    name = Path(result["path"]).name
    # Should contain YYYYMMDD_HHMM
    assert re.search(r"\d{8}_\d{4}", name)


def test_save_study_file_spaces_in_filename(tmp_path):
    from src.agents.study.tools import save_study_file

    with patch("src.agents.study.tools._output_dir", return_value=tmp_path), \
         patch("src.agents.study.tools._open_browser"):
        result = save_study_file.invoke({
            "html": _valid_html(),
            "file_type": "fiche",
            "filename": "audit securite",
        })

    assert " " not in Path(result["path"]).name


# ── save_study_file — pdf_path mode ──────────────────────────────────────────

def test_save_study_file_pdf_path_not_found():
    from src.agents.study.tools import save_study_file

    result = save_study_file.invoke({
        "pdf_path": "/nonexistent/file.pdf",
        "file_type": "fiche",
    })

    assert result["status"] == "error"
    assert "introuvable" in result["error"]


def _pdf_mode_patches(tmp_path, html_content, pdf_text="Course content"):
    """Return list of (target, kwargs) for ExitStack patching of pdf_path mode."""
    fake_llm = MagicMock()
    fake_response = MagicMock()
    fake_response.content = html_content
    fake_llm.invoke.return_value = fake_response

    mock_settings = MagicMock()
    mock_settings.llm_backend = "ollama_cloud"

    return [
        patch("src.ui.attachments._extract_pdf", return_value=pdf_text),
        patch("src.agents.study.tools._output_dir", return_value=tmp_path),
        patch("src.agents.study.tools._open_browser"),
        patch("src.llm.models.make_llm_ollama_cloud", return_value=fake_llm),
        patch("src.infra.settings.settings", mock_settings),
    ]


def test_save_study_file_pdf_path_generates_html(tmp_path):
    from src.agents.study.tools import save_study_file
    from contextlib import ExitStack

    fake_pdf = tmp_path / "cours.pdf"
    fake_pdf.write_bytes(b"%PDF-1.4 fake content")

    with ExitStack() as stack:
        for p in _pdf_mode_patches(tmp_path, _valid_html()):
            stack.enter_context(p)
        result = save_study_file.invoke({"pdf_path": str(fake_pdf), "file_type": "fiche"})

    assert result["status"] == "ok"


def test_save_study_file_pdf_path_uses_pdf_stem_as_filename(tmp_path):
    from src.agents.study.tools import save_study_file
    from contextlib import ExitStack

    fake_pdf = tmp_path / "algorithmes_tri.pdf"
    fake_pdf.write_bytes(b"%PDF-1.4 fake")

    with ExitStack() as stack:
        for p in _pdf_mode_patches(tmp_path, _valid_html()):
            stack.enter_context(p)
        result = save_study_file.invoke({"pdf_path": str(fake_pdf), "file_type": "fiche"})

    assert result["status"] == "ok"
    assert "algorithmes_tri" in Path(result["path"]).name


def test_save_study_file_pdf_extraction_error(tmp_path):
    from src.agents.study.tools import save_study_file

    fake_pdf = tmp_path / "bad.pdf"
    fake_pdf.write_bytes(b"%PDF-1.4 corrupted")

    # _extract_pdf is imported inside the function from src.ui.attachments
    with patch("src.ui.attachments._extract_pdf", side_effect=Exception("corrupt")):
        result = save_study_file.invoke({
            "pdf_path": str(fake_pdf),
            "file_type": "fiche",
        })

    assert result["status"] == "error"
    assert "PDF" in result["error"] or "lecture" in result["error"]


# ── _open_browser ─────────────────────────────────────────────────────────────

def test_open_browser_does_not_raise_on_missing_xdg(tmp_path):
    from src.agents.study.tools import _open_browser
    import subprocess

    with patch("subprocess.Popen", side_effect=FileNotFoundError):
        # Should not raise
        _open_browser(tmp_path / "test.html")
