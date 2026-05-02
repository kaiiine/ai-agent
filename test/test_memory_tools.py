"""Tests for src/agents/memory/tools.py — axon_note, _find_git_root, _memory_path."""
import subprocess
import pytest
from pathlib import Path
from unittest.mock import patch


# ── _find_git_root ────────────────────────────────────────────────────────────

def test_find_git_root_finds_repo(tmp_path):
    from src.agents.memory.tools import _find_git_root
    (tmp_path / ".git").mkdir()
    assert _find_git_root(tmp_path) == tmp_path


def test_find_git_root_finds_parent_repo(tmp_path):
    from src.agents.memory.tools import _find_git_root
    (tmp_path / ".git").mkdir()
    nested = tmp_path / "src" / "module"
    nested.mkdir(parents=True)
    assert _find_git_root(nested) == tmp_path


def test_find_git_root_no_repo_returns_start(tmp_path):
    from src.agents.memory.tools import _find_git_root
    # No .git anywhere — should return the start directory
    result = _find_git_root(tmp_path)
    assert result == tmp_path


# ── axon_note ─────────────────────────────────────────────────────────────────

def test_axon_note_creates_memory_file(tmp_path):
    from src.agents.memory.tools import axon_note
    (tmp_path / ".git").mkdir()

    with patch("src.agents.memory.tools._memory_path", return_value=tmp_path / ".axon" / "memory.md"):
        result = axon_note.invoke({"fact": "Auth uses JWT RS256. See src/auth/tokens.py"})

    mem = tmp_path / ".axon" / "memory.md"
    assert mem.exists()
    assert "Auth uses JWT RS256" in mem.read_text()
    assert "Note enregistrée" in result


def test_axon_note_creates_parent_dirs(tmp_path):
    from src.agents.memory.tools import axon_note
    memory_path = tmp_path / "deep" / "nested" / ".axon" / "memory.md"

    with patch("src.agents.memory.tools._memory_path", return_value=memory_path):
        axon_note.invoke({"fact": "test fact"})

    assert memory_path.exists()


def test_axon_note_writes_header_on_first_call(tmp_path):
    from src.agents.memory.tools import axon_note
    memory_path = tmp_path / ".axon" / "memory.md"

    with patch("src.agents.memory.tools._memory_path", return_value=memory_path):
        axon_note.invoke({"fact": "First note ever"})

    content = memory_path.read_text()
    assert "# Axon Memory" in content
    assert "Généré automatiquement" in content


def test_axon_note_no_duplicate_header(tmp_path):
    from src.agents.memory.tools import axon_note
    memory_path = tmp_path / ".axon" / "memory.md"

    with patch("src.agents.memory.tools._memory_path", return_value=memory_path):
        axon_note.invoke({"fact": "First note"})
        axon_note.invoke({"fact": "Second note"})

    content = memory_path.read_text()
    assert content.count("# Axon Memory") == 1


def test_axon_note_appends_multiple_notes(tmp_path):
    from src.agents.memory.tools import axon_note
    memory_path = tmp_path / ".axon" / "memory.md"

    with patch("src.agents.memory.tools._memory_path", return_value=memory_path):
        axon_note.invoke({"fact": "Note one"})
        axon_note.invoke({"fact": "Note two"})

    content = memory_path.read_text()
    assert "Note one" in content
    assert "Note two" in content


def test_axon_note_includes_timestamp(tmp_path):
    from src.agents.memory.tools import axon_note
    import re
    memory_path = tmp_path / ".axon" / "memory.md"

    with patch("src.agents.memory.tools._memory_path", return_value=memory_path):
        axon_note.invoke({"fact": "Timestamped fact"})

    content = memory_path.read_text()
    # Should contain a date like ## 2024-03-15 14:30
    assert re.search(r"## \d{4}-\d{2}-\d{2} \d{2}:\d{2}", content)


def test_axon_note_strips_whitespace(tmp_path):
    from src.agents.memory.tools import axon_note
    memory_path = tmp_path / ".axon" / "memory.md"

    with patch("src.agents.memory.tools._memory_path", return_value=memory_path):
        axon_note.invoke({"fact": "  fact with spaces  "})

    content = memory_path.read_text()
    assert "fact with spaces" in content
    # Leading/trailing spaces should be stripped
    assert "  fact with spaces  " not in content


def test_axon_note_real_git_repo(tmp_path):
    """Integration test: axon_note discovers real git repo from cwd."""
    from src.agents.memory.tools import axon_note
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)

    with patch("pathlib.Path.cwd", return_value=tmp_path):
        result = axon_note.invoke({"fact": "Real repo fact"})

    mem = tmp_path / ".axon" / "memory.md"
    assert mem.exists()
    assert "Real repo fact" in mem.read_text()
