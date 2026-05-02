"""Tests for src/agents/filesystem/tools.py — local_find_file, local_list_directory,
local_read_file, local_grep, local_glob."""
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path


# ── local_read_file ───────────────────────────────────────────────────────────

def test_read_file_ok(tmp_path):
    from src.agents.filesystem.tools import local_read_file
    f = tmp_path / "hello.txt"
    f.write_text("line1\nline2\nline3\n")

    result = local_read_file.invoke({"path": str(f)})

    assert result["status"] == "ok"
    assert "line1" in result["content"]
    assert result["lines"] == 4  # 3 lines + trailing newline = 4 \n + 1


def test_read_file_not_found():
    from src.agents.filesystem.tools import local_read_file
    result = local_read_file.invoke({"path": "/nonexistent/path/xyz.txt"})
    assert result["status"] == "not_found"


def test_read_file_path_is_directory(tmp_path):
    from src.agents.filesystem.tools import local_read_file
    result = local_read_file.invoke({"path": str(tmp_path)})
    assert result["status"] == "error"


def test_read_file_too_large(tmp_path):
    from src.agents.filesystem.tools import local_read_file
    f = tmp_path / "large.txt"
    f.write_bytes(b"x" * (200_001))

    result = local_read_file.invoke({"path": str(f)})
    assert result["status"] == "too_large"
    assert "hint" in result


def test_read_file_with_offset_and_limit(tmp_path):
    from src.agents.filesystem.tools import local_read_file
    f = tmp_path / "lines.txt"
    content = "\n".join(f"line{i}" for i in range(1, 21))
    f.write_text(content)

    result = local_read_file.invoke({"path": str(f), "offset": 5, "limit": 3})

    assert result["status"] == "ok"
    assert result["lines_returned"] == 3
    assert "line5" in result["content"]
    assert "line7" in result["content"]
    assert "line8" not in result["content"]


def test_read_file_offset_only(tmp_path):
    from src.agents.filesystem.tools import local_read_file
    f = tmp_path / "lines.txt"
    f.write_text("a\nb\nc\nd\ne\n")

    result = local_read_file.invoke({"path": str(f), "offset": 3, "limit": 0})
    assert result["status"] == "ok"
    assert "c" in result["content"]


def test_read_file_pdf_no_text(tmp_path):
    from src.agents.filesystem.tools import local_read_file
    f = tmp_path / "scanned.pdf"
    f.write_bytes(b"%PDF-1.4 fake")

    mock_reader = type("R", (), {"pages": []})()
    with patch("pypdf.PdfReader", return_value=mock_reader):
        result = local_read_file.invoke({"path": str(f)})

    assert result["status"] == "error"
    assert "scanné" in result["error"] or "extractible" in result["error"]


def test_read_file_pdf_with_text(tmp_path):
    from src.agents.filesystem.tools import local_read_file
    f = tmp_path / "doc.pdf"
    f.write_bytes(b"%PDF-1.4 fake")

    mock_page = MagicMock()
    mock_page.extract_text.return_value = "Hello PDF content"
    mock_reader = MagicMock()
    mock_reader.pages = [mock_page]

    with patch("pypdf.PdfReader", return_value=mock_reader):
        result = local_read_file.invoke({"path": str(f)})

    assert result["status"] == "ok"
    assert "Hello PDF content" in result["content"]


# ── local_list_directory ──────────────────────────────────────────────────────

def test_list_directory_by_path(tmp_path):
    from src.agents.filesystem.tools import local_list_directory
    (tmp_path / "file.py").write_text("code")
    (tmp_path / "subdir").mkdir()

    result = local_list_directory.invoke({"path": str(tmp_path)})

    assert result["status"] == "ok"
    names = [e["name"] for e in result["entries"]]
    assert "file.py" in names
    assert "subdir" in names


def test_list_directory_dirs_before_files(tmp_path):
    from src.agents.filesystem.tools import local_list_directory
    (tmp_path / "aaa.txt").write_text("x")
    (tmp_path / "zzz_dir").mkdir()

    result = local_list_directory.invoke({"path": str(tmp_path)})
    entries = result["entries"]
    dirs = [e for e in entries if e["type"] == "dossier"]
    files = [e for e in entries if e["type"] == "fichier"]
    # Dirs should come before files (sorted by is_file ascending)
    if dirs and files:
        last_dir_idx = max(i for i, e in enumerate(entries) if e["type"] == "dossier")
        first_file_idx = min(i for i, e in enumerate(entries) if e["type"] == "fichier")
        assert last_dir_idx < first_file_idx


def test_list_directory_not_found(tmp_path):
    from src.agents.filesystem.tools import local_list_directory
    # Provide both path (nonexistent) and no name — tool returns not_found only when target is None
    result = local_list_directory.invoke({"path": str(tmp_path / "does_not_exist"), "name": ""})
    # The path doesn't exist as a dir, and no name search → not_found
    assert result["status"] in ("not_found", "error")


def test_list_directory_file_has_size(tmp_path):
    from src.agents.filesystem.tools import local_list_directory
    f = tmp_path / "data.csv"
    f.write_text("a,b,c\n1,2,3\n")

    result = local_list_directory.invoke({"path": str(tmp_path)})
    file_entry = next(e for e in result["entries"] if e["name"] == "data.csv")
    assert "size" in file_entry
    assert "path" in file_entry


def test_list_directory_empty_dir(tmp_path):
    from src.agents.filesystem.tools import local_list_directory
    result = local_list_directory.invoke({"path": str(tmp_path)})
    assert result["status"] == "ok"
    assert result["entries"] == []
    assert result["count"] == 0


# ── local_grep ────────────────────────────────────────────────────────────────

def test_local_grep_finds_pattern(tmp_path):
    from src.agents.filesystem.tools import local_grep
    (tmp_path / "code.py").write_text("def hello():\n    pass\ndef world():\n    pass\n")

    with patch("src.agents.filesystem.tools._rg_available", return_value=False):
        result = local_grep.invoke({"pattern": "def hello", "path": str(tmp_path)})

    assert result["status"] == "ok"
    assert "def hello" in result["matches"]


def test_local_grep_no_match(tmp_path):
    from src.agents.filesystem.tools import local_grep
    (tmp_path / "code.py").write_text("nothing here\n")

    with patch("src.agents.filesystem.tools._rg_available", return_value=False):
        result = local_grep.invoke({"pattern": "XYZNOTFOUND999", "path": str(tmp_path)})

    assert result["status"] == "no_match"


def test_local_grep_case_insensitive(tmp_path):
    from src.agents.filesystem.tools import local_grep
    (tmp_path / "readme.md").write_text("Hello World\n")

    with patch("src.agents.filesystem.tools._rg_available", return_value=False):
        result = local_grep.invoke({
            "pattern": "hello world",
            "path": str(tmp_path),
            "case_insensitive": True,
        })

    assert result["status"] == "ok"


def test_local_grep_files_mode(tmp_path):
    from src.agents.filesystem.tools import local_grep
    (tmp_path / "a.py").write_text("import os\n")
    (tmp_path / "b.py").write_text("import sys\n")

    with patch("src.agents.filesystem.tools._rg_available", return_value=False):
        result = local_grep.invoke({
            "pattern": "import os",
            "path": str(tmp_path),
            "output_mode": "files",
        })

    assert result["status"] == "ok"
    assert "a.py" in result["matches"]
    assert "b.py" not in result["matches"]


def test_local_grep_invalid_path():
    from src.agents.filesystem.tools import local_grep
    result = local_grep.invoke({"pattern": "anything", "path": "/nonexistent/xyz"})
    assert result["status"] == "error"


def test_local_grep_glob_filter(tmp_path):
    from src.agents.filesystem.tools import local_grep
    (tmp_path / "code.py").write_text("TARGET\n")
    (tmp_path / "code.js").write_text("TARGET\n")

    with patch("src.agents.filesystem.tools._rg_available", return_value=False):
        result = local_grep.invoke({
            "pattern": "TARGET",
            "path": str(tmp_path),
            "glob": "*.py",
        })

    assert result["status"] == "ok"
    assert "code.py" in result["matches"]
    # JS file should not appear since glob is *.py
    assert "code.js" not in result["matches"]


# ── local_glob ────────────────────────────────────────────────────────────────

def test_local_glob_finds_files(tmp_path):
    from src.agents.filesystem.tools import local_glob
    (tmp_path / "a.py").write_text("x")
    (tmp_path / "b.py").write_text("x")
    (tmp_path / "c.js").write_text("x")

    result = local_glob.invoke({"pattern": "*.py", "path": str(tmp_path)})

    assert result["status"] == "ok"
    names = [m["name"] for m in result["matches"]]
    assert "a.py" in names
    assert "b.py" in names
    assert "c.js" not in names


def test_local_glob_recursive(tmp_path):
    from src.agents.filesystem.tools import local_glob
    sub = tmp_path / "src"
    sub.mkdir()
    (sub / "module.py").write_text("x")
    (tmp_path / "main.py").write_text("x")

    result = local_glob.invoke({"pattern": "**/*.py", "path": str(tmp_path)})

    assert result["status"] == "ok"
    paths = [m["path"] for m in result["matches"]]
    assert any("module.py" in p for p in paths)
    assert any("main.py" in p for p in paths)


def test_local_glob_no_match(tmp_path):
    from src.agents.filesystem.tools import local_glob
    (tmp_path / "file.txt").write_text("x")

    result = local_glob.invoke({"pattern": "*.rs", "path": str(tmp_path)})

    assert result["status"] == "no_match"
    assert result["matches"] == []


def test_local_glob_invalid_base():
    from src.agents.filesystem.tools import local_glob
    result = local_glob.invoke({"pattern": "*.py", "path": "/nonexistent/xyz"})
    assert result["status"] == "error"


def test_local_glob_excludes_dirs(tmp_path):
    from src.agents.filesystem.tools import local_glob
    (tmp_path / "file.py").write_text("x")
    (tmp_path / "subdir").mkdir()

    result = local_glob.invoke({"pattern": "*.py", "path": str(tmp_path)})

    # Only files, not directories
    for m in result["matches"]:
        assert Path(m["path"]).is_file()


def test_local_glob_match_has_required_fields(tmp_path):
    from src.agents.filesystem.tools import local_glob
    (tmp_path / "app.py").write_text("hello")

    result = local_glob.invoke({"pattern": "*.py", "path": str(tmp_path)})

    m = result["matches"][0]
    assert "path" in m
    assert "name" in m
    assert "ext" in m
    assert "size" in m
    assert "modified" in m
