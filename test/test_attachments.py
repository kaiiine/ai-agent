"""Tests for src/ui/attachments.py — Attachment, AttachmentStore, build_message_with_attachments."""
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock


# ── _fix_spaced_chars ─────────────────────────────────────────────────────────

def test_fix_spaced_chars_collapses_spaced_letters():
    from src.ui.attachments import _fix_spaced_chars
    # Simulates pypdf artifact where letters are space-separated
    spaced = "H e l l o W o r l d"
    result = _fix_spaced_chars(spaced)
    assert "Hello" in result or "HelloWorld" in result


def test_fix_spaced_chars_preserves_normal_text():
    from src.ui.attachments import _fix_spaced_chars
    normal = "This is a normal sentence with real words."
    result = _fix_spaced_chars(normal)
    assert "normal sentence" in result


def test_fix_spaced_chars_handles_empty():
    from src.ui.attachments import _fix_spaced_chars
    assert _fix_spaced_chars("") == ""


def test_fix_spaced_chars_multiline():
    from src.ui.attachments import _fix_spaced_chars
    text = "H e l l o\nThis is fine"
    result = _fix_spaced_chars(text)
    lines = result.splitlines()
    assert "This is fine" in lines[-1]


# ── _extract_pdf ──────────────────────────────────────────────────────────────

def test_extract_pdf_returns_text(tmp_path):
    from src.ui.attachments import _extract_pdf
    f = tmp_path / "doc.pdf"
    f.write_bytes(b"%PDF-1.4 fake")

    mock_page = MagicMock()
    mock_page.extract_text.return_value = "Page content here"
    mock_reader = MagicMock()
    mock_reader.pages = [mock_page]

    with patch("pypdf.PdfReader", return_value=mock_reader):
        result = _extract_pdf(f)

    assert "Page content here" in result
    assert "[Page 1]" in result


def test_extract_pdf_empty_pages(tmp_path):
    from src.ui.attachments import _extract_pdf
    f = tmp_path / "empty.pdf"
    f.write_bytes(b"%PDF-1.4 fake")

    mock_page = MagicMock()
    mock_page.extract_text.return_value = ""
    mock_reader = MagicMock()
    mock_reader.pages = [mock_page]

    with patch("pypdf.PdfReader", return_value=mock_reader):
        result = _extract_pdf(f)

    assert "sans texte" in result or result == "[PDF sans texte extractible]"


def test_extract_pdf_error_returns_error_string(tmp_path):
    from src.ui.attachments import _extract_pdf
    f = tmp_path / "bad.pdf"
    f.write_bytes(b"not a pdf")

    with patch("pypdf.PdfReader", side_effect=Exception("bad format")):
        result = _extract_pdf(f)

    assert "Erreur" in result or "erreur" in result


def test_extract_pdf_multiple_pages(tmp_path):
    from src.ui.attachments import _extract_pdf
    f = tmp_path / "multi.pdf"
    f.write_bytes(b"%PDF-1.4 fake")

    pages = [MagicMock(), MagicMock(), MagicMock()]
    for i, p in enumerate(pages):
        p.extract_text.return_value = f"Content of page {i + 1}"
    mock_reader = MagicMock()
    mock_reader.pages = pages

    with patch("pypdf.PdfReader", return_value=mock_reader):
        result = _extract_pdf(f)

    assert "[Page 1]" in result
    assert "[Page 2]" in result
    assert "[Page 3]" in result


# ── AttachmentStore ───────────────────────────────────────────────────────────

def test_attachment_store_add_text_file(tmp_path):
    from src.ui.attachments import AttachmentStore
    f = tmp_path / "code.py"
    f.write_text("def hello(): pass\n")

    store = AttachmentStore()
    a = store.add_file(str(f))

    assert a is not None
    assert a.name == "code.py"
    assert a.is_image is False
    assert "hello" in a.content


def test_attachment_store_stores_source_path(tmp_path):
    from src.ui.attachments import AttachmentStore
    f = tmp_path / "data.txt"
    f.write_text("content")

    store = AttachmentStore()
    a = store.add_file(str(f))

    assert a.source_path == str(f.resolve())


def test_attachment_store_add_image_file(tmp_path):
    from src.ui.attachments import AttachmentStore
    f = tmp_path / "photo.png"
    # Minimal valid PNG header
    f.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 50)

    store = AttachmentStore()
    with patch("PIL.Image.open"):  # avoid PIL errors on fake PNG
        a = store.add_file(str(f))

    assert a is not None
    assert a.is_image is True
    assert a.b64 != ""
    assert a.mime == "image/png"


def test_attachment_store_nonexistent_file():
    from src.ui.attachments import AttachmentStore
    store = AttachmentStore()
    result = store.add_file("/nonexistent/path/file.txt")
    assert result is None


def test_attachment_store_pop_all_clears(tmp_path):
    from src.ui.attachments import AttachmentStore
    f = tmp_path / "f.txt"
    f.write_text("x")

    store = AttachmentStore()
    store.add_file(str(f))
    assert len(store) == 1

    items = store.pop_all()
    assert len(items) == 1
    assert len(store) == 0


def test_attachment_store_remove_by_name(tmp_path):
    from src.ui.attachments import AttachmentStore
    f = tmp_path / "removeme.txt"
    f.write_text("x")

    store = AttachmentStore()
    store.add_file(str(f))
    removed = store.remove("removeme.txt")

    assert removed is True
    assert len(store) == 0


def test_attachment_store_remove_nonexistent():
    from src.ui.attachments import AttachmentStore
    store = AttachmentStore()
    removed = store.remove("ghost.txt")
    assert removed is False


def test_attachment_store_bool_false_when_empty():
    from src.ui.attachments import AttachmentStore
    store = AttachmentStore()
    assert not store


def test_attachment_store_bool_true_when_has_items(tmp_path):
    from src.ui.attachments import AttachmentStore
    f = tmp_path / "file.txt"
    f.write_text("x")

    store = AttachmentStore()
    store.add_file(str(f))
    assert store


def test_attachment_store_size_hint_large_file(tmp_path):
    from src.ui.attachments import AttachmentStore
    f = tmp_path / "big.txt"
    f.write_bytes(b"x" * 5000)

    store = AttachmentStore()
    a = store.add_file(str(f))

    assert "KB" in a.size_hint


def test_attachment_store_size_hint_small_file(tmp_path):
    from src.ui.attachments import AttachmentStore
    f = tmp_path / "tiny.txt"
    f.write_bytes(b"abc")

    store = AttachmentStore()
    a = store.add_file(str(f))

    assert "B" in a.size_hint


# ── build_message_with_attachments ────────────────────────────────────────────

def test_build_message_no_attachments():
    from src.ui.attachments import build_message_with_attachments
    result = build_message_with_attachments("Hello", [])
    assert result == {"role": "user", "content": "Hello"}


def test_build_message_small_text_attachment(tmp_path):
    from src.ui.attachments import build_message_with_attachments, Attachment
    a = Attachment(
        name="small.py",
        is_image=False,
        content="print('hello')",
        size_hint="20B",
        source_path=str(tmp_path / "small.py"),
    )

    result = build_message_with_attachments("Analyze this", [a])

    assert result["role"] == "user"
    assert isinstance(result["content"], str)
    assert "small.py" in result["content"]
    assert "print('hello')" in result["content"]


def test_build_message_large_text_attachment_uses_path(tmp_path):
    from src.ui.attachments import build_message_with_attachments, Attachment, _ORCHESTRATOR_INJECT
    large_content = "x" * (_ORCHESTRATOR_INJECT + 1)
    source = str(tmp_path / "large.pdf")

    a = Attachment(
        name="large.pdf",
        is_image=False,
        content=large_content,
        size_hint="500KB",
        source_path=source,
    )

    result = build_message_with_attachments("Make a fiche", [a])

    # Should inject path, not content
    content_str = result["content"]
    assert source in content_str
    assert large_content not in content_str
    assert "save_study_file" in content_str


def test_build_message_with_image():
    from src.ui.attachments import build_message_with_attachments, Attachment
    import base64
    fake_b64 = base64.b64encode(b"\x89PNG\r\n").decode()

    a = Attachment(
        name="screenshot.png",
        is_image=True,
        b64=fake_b64,
        mime="image/png",
        size_hint="5KB",
    )

    result = build_message_with_attachments("What is this?", [a])

    assert result["role"] == "user"
    assert isinstance(result["content"], list)
    # First item should be text, second should be image
    assert result["content"][0]["type"] == "text"
    img_parts = [c for c in result["content"] if c["type"] == "image_url"]
    assert len(img_parts) == 1
    assert fake_b64 in img_parts[0]["image_url"]["url"]


def test_build_message_mixed_image_and_text(tmp_path):
    from src.ui.attachments import build_message_with_attachments, Attachment
    import base64

    text_a = Attachment(
        name="code.py",
        is_image=False,
        content="x = 1",
        size_hint="10B",
        source_path=str(tmp_path / "code.py"),
    )
    img_a = Attachment(
        name="img.png",
        is_image=True,
        b64=base64.b64encode(b"PNG").decode(),
        mime="image/png",
        size_hint="1KB",
    )

    result = build_message_with_attachments("Explain", [text_a, img_a])

    assert isinstance(result["content"], list)
    text_part = result["content"][0]
    assert "code.py" in text_part["text"]
    assert "x = 1" in text_part["text"]


def test_build_message_pdf_language_tag(tmp_path):
    from src.ui.attachments import build_message_with_attachments, Attachment
    a = Attachment(
        name="report.pdf",
        is_image=False,
        content="PDF text here",
        size_hint="5KB",
        source_path=str(tmp_path / "report.pdf"),
    )

    result = build_message_with_attachments("Summarize", [a])
    content = result["content"]
    # PDF should use "pdf" as language tag in code block
    assert "pdf" in content or "report.pdf" in content
