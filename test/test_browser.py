"""Tests for src/infra/browser.py — screenshot_url, _find_chromium, _AUDIT_JS."""
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

# sync_playwright is imported inside screenshot_url(), so we patch it at its source
_PW_PATCH = "playwright.sync_api.sync_playwright"


# ── _find_chromium ────────────────────────────────────────────────────────────

def test_find_chromium_returns_first_existing(tmp_path):
    from src.infra import browser as bmod
    fake = tmp_path / "chromium"
    fake.touch()
    with patch.object(bmod, "_CHROMIUM_CANDIDATES", (str(fake),)):
        result = bmod._find_chromium()
    assert result == str(fake)


def test_find_chromium_raises_when_none_found():
    from src.infra import browser as bmod
    with patch.object(bmod, "_CHROMIUM_CANDIDATES", ("/nonexistent/chromium",)):
        with pytest.raises(FileNotFoundError, match="Chromium"):
            bmod._find_chromium()


def test_find_chromium_skips_missing_picks_real(tmp_path):
    from src.infra import browser as bmod
    real = tmp_path / "chromium"
    real.touch()
    candidates = ("/nonexistent/one", str(real), "/nonexistent/two")
    with patch.object(bmod, "_CHROMIUM_CANDIDATES", candidates):
        result = bmod._find_chromium()
    assert result == str(real)


# ── screenshot_url — playwright missing ──────────────────────────────────────

def test_screenshot_url_returns_error_when_playwright_missing():
    from src.infra.browser import screenshot_url
    with patch("builtins.__import__", side_effect=lambda n, *a, **kw: (
        (_ for _ in ()).throw(ImportError("No module named 'playwright'"))
        if n == "playwright.sync_api" else __import__(n, *a, **kw)
    )):
        result = screenshot_url("http://localhost:3000")
    assert result["status"] == "error"
    assert "playwright" in result["error"].lower()


# ── screenshot_url — chromium not found ──────────────────────────────────────

def test_screenshot_url_returns_error_when_chromium_missing():
    from src.infra.browser import screenshot_url
    with patch("src.infra.browser._find_chromium", side_effect=FileNotFoundError("Aucun navigateur")):
        result = screenshot_url("http://localhost:3000")
    assert result["status"] == "error"


# ── helpers for mocking playwright ───────────────────────────────────────────

def _make_mock_pw(page_title="Test", page_text="Hello world", audit_result=None):
    """Build a complete mock playwright stack."""
    if audit_result is None:
        audit_result = {
            "title": page_title, "h1s": ["Hello"],
            "issueCount": 0, "issues": [],
            "viewport": {"width": 1280, "height": 900},
        }
    mock_page = MagicMock()
    mock_page.goto.return_value = None
    mock_page.wait_for_timeout.return_value = None
    mock_page.screenshot.return_value = None
    mock_page.evaluate.return_value = audit_result
    mock_page.inner_text.return_value = page_text

    mock_browser = MagicMock()
    mock_browser.new_page.return_value = mock_page

    mock_chromium_launcher = MagicMock()
    mock_chromium_launcher.launch.return_value = mock_browser

    mock_p = MagicMock()
    mock_p.chromium = mock_chromium_launcher

    mock_ctx = MagicMock()
    mock_ctx.__enter__ = MagicMock(return_value=mock_p)
    mock_ctx.__exit__ = MagicMock(return_value=False)

    return mock_ctx, mock_browser, mock_page


# ── screenshot_url — happy path ───────────────────────────────────────────────

def test_screenshot_url_ok_structure(tmp_path):
    from src.infra import browser as bmod
    fake_chromium = tmp_path / "chromium"
    fake_chromium.touch()
    mock_ctx, _, _ = _make_mock_pw()

    with patch.object(bmod, "_find_chromium", return_value=str(fake_chromium)), \
         patch(_PW_PATCH, return_value=mock_ctx), \
         patch.object(bmod, "_SCREENSHOT_DIR", tmp_path):
        result = bmod.screenshot_url("http://localhost:3000")

    assert result["status"] == "ok"
    assert "screenshot_path" in result
    assert "page_text" in result
    assert "audit" in result
    assert result["url"] == "http://localhost:3000"


def test_screenshot_url_viewport_passed_correctly(tmp_path):
    from src.infra import browser as bmod
    fake_chromium = tmp_path / "chromium"
    fake_chromium.touch()
    mock_ctx, mock_browser, _ = _make_mock_pw()

    with patch.object(bmod, "_find_chromium", return_value=str(fake_chromium)), \
         patch(_PW_PATCH, return_value=mock_ctx), \
         patch.object(bmod, "_SCREENSHOT_DIR", tmp_path):
        bmod.screenshot_url("http://localhost:3000", width=375, height=812)

    mock_browser.new_page.assert_called_once_with(viewport={"width": 375, "height": 812})


def test_screenshot_url_page_text_truncated(tmp_path):
    from src.infra import browser as bmod
    fake_chromium = tmp_path / "chromium"
    fake_chromium.touch()
    long_text = "A" * 10_000
    audit = {"title": "T", "h1s": [], "issueCount": 0, "issues": [], "viewport": {"width": 1280, "height": 900}}
    mock_ctx, _, mock_page = _make_mock_pw(page_text=long_text, audit_result=audit)
    mock_page.inner_text.return_value = long_text

    with patch.object(bmod, "_find_chromium", return_value=str(fake_chromium)), \
         patch(_PW_PATCH, return_value=mock_ctx), \
         patch.object(bmod, "_SCREENSHOT_DIR", tmp_path):
        result = bmod.screenshot_url("http://localhost:3000")

    assert len(result["page_text"]) <= 6020
    assert "tronqué" in result["page_text"]


# ── screenshot_url — resource cleanup (bug fixes) ────────────────────────────

def test_browser_always_closed_on_goto_error(tmp_path):
    """Regression: browser.close() must be called even when goto() raises."""
    from src.infra import browser as bmod
    fake_chromium = tmp_path / "chromium"
    fake_chromium.touch()

    mock_page = MagicMock()
    mock_page.goto.side_effect = Exception("Connection refused")
    mock_browser = MagicMock()
    mock_browser.new_page.return_value = mock_page
    mock_p = MagicMock()
    mock_p.chromium.launch.return_value = mock_browser
    mock_ctx = MagicMock()
    mock_ctx.__enter__ = MagicMock(return_value=mock_p)
    mock_ctx.__exit__ = MagicMock(return_value=False)

    with patch.object(bmod, "_find_chromium", return_value=str(fake_chromium)), \
         patch(_PW_PATCH, return_value=mock_ctx):
        result = bmod.screenshot_url("http://localhost:9999")

    assert result["status"] == "error"
    mock_browser.close.assert_called_once()


def test_browser_always_closed_on_screenshot_error(tmp_path):
    """Regression: browser.close() must be called even when page.screenshot() raises."""
    from src.infra import browser as bmod
    fake_chromium = tmp_path / "chromium"
    fake_chromium.touch()

    mock_page = MagicMock()
    mock_page.goto.return_value = None
    mock_page.wait_for_timeout.return_value = None
    mock_page.screenshot.side_effect = OSError("disk full")
    mock_browser = MagicMock()
    mock_browser.new_page.return_value = mock_page
    mock_p = MagicMock()
    mock_p.chromium.launch.return_value = mock_browser
    mock_ctx = MagicMock()
    mock_ctx.__enter__ = MagicMock(return_value=mock_p)
    mock_ctx.__exit__ = MagicMock(return_value=False)

    with patch.object(bmod, "_find_chromium", return_value=str(fake_chromium)), \
         patch(_PW_PATCH, return_value=mock_ctx):
        result = bmod.screenshot_url("http://localhost:3000")

    assert result["status"] == "error"
    mock_browser.close.assert_called_once()


def test_audit_error_degrades_gracefully(tmp_path):
    """If page.evaluate() raises, screenshot_url must still return status=ok."""
    from src.infra import browser as bmod
    fake_chromium = tmp_path / "chromium"
    fake_chromium.touch()

    mock_ctx, mock_browser, mock_page = _make_mock_pw()
    mock_page.evaluate.side_effect = Exception("JS eval error")

    with patch.object(bmod, "_find_chromium", return_value=str(fake_chromium)), \
         patch(_PW_PATCH, return_value=mock_ctx), \
         patch.object(bmod, "_SCREENSHOT_DIR", tmp_path):
        result = bmod.screenshot_url("http://localhost:3000")

    assert result["status"] == "ok"
    assert result["audit"]["issueCount"] == 0
    assert "error" in result["audit"]


def test_page_text_error_degrades_gracefully(tmp_path):
    """If inner_text() raises, screenshot_url must still return status=ok."""
    from src.infra import browser as bmod
    fake_chromium = tmp_path / "chromium"
    fake_chromium.touch()

    mock_ctx, _, mock_page = _make_mock_pw()
    mock_page.inner_text.side_effect = Exception("DOM error")

    with patch.object(bmod, "_find_chromium", return_value=str(fake_chromium)), \
         patch(_PW_PATCH, return_value=mock_ctx), \
         patch.object(bmod, "_SCREENSHOT_DIR", tmp_path):
        result = bmod.screenshot_url("http://localhost:3000")

    assert result["status"] == "ok"
    assert result["page_text"] == "(texte non disponible)"


# ── _AUDIT_JS structure ───────────────────────────────────────────────────────

def test_audit_js_is_nonempty_string():
    from src.infra.browser import _AUDIT_JS
    assert isinstance(_AUDIT_JS, str)
    assert len(_AUDIT_JS) > 100


def test_audit_js_is_arrow_function():
    from src.infra.browser import _AUDIT_JS
    assert _AUDIT_JS.strip().startswith("() => {")


def test_audit_js_detects_all_issue_types():
    from src.infra.browser import _AUDIT_JS
    for issue_type in ("text_cropped", "outside_viewport_right", "not_centered",
                       "empty_section", "broken_image"):
        assert issue_type in _AUDIT_JS, f"_AUDIT_JS should detect '{issue_type}'"


def test_audit_js_returns_expected_keys():
    from src.infra.browser import _AUDIT_JS
    for key in ("title", "h1s", "viewport", "issueCount", "issues"):
        assert key in _AUDIT_JS
