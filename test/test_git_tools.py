"""Tests for src/agents/git/tools.py — all git tools and url_fetch."""
import subprocess
import time
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def git_repo(tmp_path):
    """Create a real minimal git repo for testing."""
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, capture_output=True)
    # Initial commit
    (tmp_path / "README.md").write_text("# Test repo\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "commit", "-m", "initial commit"], cwd=tmp_path, capture_output=True)
    return tmp_path


# ── git_status ────────────────────────────────────────────────────────────────

def test_git_status_clean_repo(git_repo):
    from src.agents.git.tools import git_status
    result = git_status.invoke({"repo_path": str(git_repo)})
    assert result["status"] == "ok"
    assert "output" in result
    assert "repo" in result


def test_git_status_detects_modified_file(git_repo):
    from src.agents.git.tools import git_status
    (git_repo / "README.md").write_text("modified content")
    result = git_status.invoke({"repo_path": str(git_repo)})
    assert result["status"] == "ok"
    assert "README" in result["output"] or "M" in result["output"]


def test_git_status_not_a_repo(tmp_path):
    from src.agents.git.tools import git_status
    result = git_status.invoke({"repo_path": str(tmp_path)})
    # Not a repo → error
    assert result["status"] == "error"


# ── git_log ───────────────────────────────────────────────────────────────────

def test_git_log_returns_commits(git_repo):
    from src.agents.git.tools import git_log
    result = git_log.invoke({"repo_path": str(git_repo)})
    assert result["status"] == "ok"
    assert "initial commit" in result["log"]


def test_git_log_respects_n(git_repo):
    from src.agents.git.tools import git_log
    # Add a second commit
    (git_repo / "file.txt").write_text("x")
    subprocess.run(["git", "add", "."], cwd=git_repo, capture_output=True)
    subprocess.run(["git", "commit", "-m", "second commit"], cwd=git_repo, capture_output=True)

    result = git_log.invoke({"repo_path": str(git_repo), "n": 1})
    assert result["status"] == "ok"
    # Only 1 commit shown — initial should not appear
    lines = [l for l in result["log"].splitlines() if l.strip()]
    assert len(lines) == 1


def test_git_log_caps_at_50(git_repo):
    from src.agents.git.tools import git_log
    # n=200 should be capped to 50 in the command
    with patch("src.agents.git.tools._git") as mock_git:
        mock_git.return_value = (0, "* abc123 initial\n", "")
        git_log.invoke({"repo_path": str(git_repo), "n": 200})
        args = mock_git.call_args[0][0]
        assert "-50" in args


# ── git_diff ──────────────────────────────────────────────────────────────────

def test_git_diff_unstaged(git_repo):
    from src.agents.git.tools import git_diff
    (git_repo / "README.md").write_text("changed content")
    result = git_diff.invoke({"repo_path": str(git_repo)})
    assert result["status"] == "ok"
    assert result["staged"] is False
    assert "README" in result["stat"] or "README" in result["diff"]


def test_git_diff_staged_empty(git_repo):
    from src.agents.git.tools import git_diff
    result = git_diff.invoke({"repo_path": str(git_repo), "staged": True})
    assert result["status"] == "ok"
    assert result["diff"] == ""


def test_git_diff_staged_with_file(git_repo):
    from src.agents.git.tools import git_diff
    (git_repo / "new.py").write_text("print('hello')")
    subprocess.run(["git", "add", "new.py"], cwd=git_repo, capture_output=True)
    result = git_diff.invoke({"repo_path": str(git_repo), "staged": True})
    assert result["status"] == "ok"
    assert "new.py" in result["stat"] or "new.py" in result["diff"]


# ── git_suggest_commit ────────────────────────────────────────────────────────

def test_git_suggest_commit_empty_stage(git_repo):
    from src.agents.git.tools import git_suggest_commit
    result = git_suggest_commit.invoke({"repo_path": str(git_repo)})
    assert result["status"] == "empty"
    assert "staged" in result["message"].lower() or "git add" in result["message"]


def test_git_suggest_commit_with_staged(git_repo):
    from src.agents.git.tools import git_suggest_commit
    (git_repo / "feature.py").write_text("def new_func(): pass")
    subprocess.run(["git", "add", "feature.py"], cwd=git_repo, capture_output=True)
    result = git_suggest_commit.invoke({"repo_path": str(git_repo)})
    assert result["status"] == "ok"
    assert "diff_summary" in result
    assert "instruction" in result
    assert "diff" in result


# ── git_add ───────────────────────────────────────────────────────────────────

def test_git_add_single_file(git_repo):
    from src.agents.git.tools import git_add
    (git_repo / "new_file.py").write_text("x = 1")
    result = git_add.invoke({"paths": ["new_file.py"], "repo_path": str(git_repo)})
    assert result["status"] == "ok"
    assert "new_file.py" in result["paths"]


def test_git_add_multiple_files(git_repo):
    from src.agents.git.tools import git_add
    (git_repo / "a.py").write_text("a")
    (git_repo / "b.py").write_text("b")
    result = git_add.invoke({"paths": ["a.py", "b.py"], "repo_path": str(git_repo)})
    assert result["status"] == "ok"


def test_git_add_nonexistent_file(git_repo):
    from src.agents.git.tools import git_add
    result = git_add.invoke({"paths": ["does_not_exist.py"], "repo_path": str(git_repo)})
    assert result["status"] == "error"


# ── git_commit ────────────────────────────────────────────────────────────────

def test_git_commit_ok(git_repo):
    from src.agents.git.tools import git_commit
    (git_repo / "feature.py").write_text("code")
    subprocess.run(["git", "add", "."], cwd=git_repo, capture_output=True)
    result = git_commit.invoke({"message": "feat: add feature", "repo_path": str(git_repo)})
    assert result["status"] == "ok"
    assert result["commit"]
    assert result["message"] == "feat: add feature"


def test_git_commit_empty_message(git_repo):
    from src.agents.git.tools import git_commit
    result = git_commit.invoke({"message": "", "repo_path": str(git_repo)})
    assert result["status"] == "error"


def test_git_commit_nothing_staged(git_repo):
    from src.agents.git.tools import git_commit
    result = git_commit.invoke({"message": "fix: nothing", "repo_path": str(git_repo)})
    assert result["status"] == "error"


# ── git_checkout ──────────────────────────────────────────────────────────────

def test_git_checkout_create_branch(git_repo):
    from src.agents.git.tools import git_checkout
    result = git_checkout.invoke({
        "branch": "feat/test-branch",
        "create": True,
        "repo_path": str(git_repo),
    })
    assert result["status"] == "ok"
    assert result["created"] is True
    assert result["branch"] == "feat/test-branch"


def test_git_checkout_switch_branch(git_repo):
    from src.agents.git.tools import git_checkout
    subprocess.run(["git", "checkout", "-b", "other"], cwd=git_repo, capture_output=True)
    subprocess.run(["git", "checkout", "master"], cwd=git_repo, capture_output=True)

    result = git_checkout.invoke({
        "branch": "other",
        "create": False,
        "repo_path": str(git_repo),
    })
    assert result["status"] == "ok"
    assert result["created"] is False


def test_git_checkout_empty_branch_name(git_repo):
    from src.agents.git.tools import git_checkout
    result = git_checkout.invoke({"branch": "", "repo_path": str(git_repo)})
    assert result["status"] == "error"


def test_git_checkout_nonexistent_branch(git_repo):
    from src.agents.git.tools import git_checkout
    result = git_checkout.invoke({"branch": "nonexistent-branch", "create": False, "repo_path": str(git_repo)})
    assert result["status"] == "error"


# ── git_stash ─────────────────────────────────────────────────────────────────

def test_git_stash_list_empty(git_repo):
    from src.agents.git.tools import git_stash
    result = git_stash.invoke({"action": "list", "repo_path": str(git_repo)})
    assert result["status"] == "ok"


def test_git_stash_push_no_changes(git_repo):
    from src.agents.git.tools import git_stash
    result = git_stash.invoke({"action": "push", "repo_path": str(git_repo)})
    # No changes → git stash push may succeed with empty message or error depending on git version
    assert result["status"] in ("ok", "error")


def test_git_stash_push_with_changes(git_repo):
    from src.agents.git.tools import git_stash
    (git_repo / "README.md").write_text("uncommitted change")
    result = git_stash.invoke({"action": "push", "message": "WIP", "repo_path": str(git_repo)})
    assert result["status"] == "ok"


def test_git_stash_pop_after_push(git_repo):
    from src.agents.git.tools import git_stash
    (git_repo / "README.md").write_text("change to stash")
    git_stash.invoke({"action": "push", "repo_path": str(git_repo)})

    result = git_stash.invoke({"action": "pop", "repo_path": str(git_repo)})
    assert result["status"] == "ok"


def test_git_stash_invalid_action(git_repo):
    from src.agents.git.tools import git_stash
    result = git_stash.invoke({"action": "delete", "repo_path": str(git_repo)})
    assert result["status"] == "error"
    assert "invalide" in result["error"]


# ── url_fetch ─────────────────────────────────────────────────────────────────

def test_url_fetch_html_content():
    from src.agents.git.tools import url_fetch, _FETCH_CACHE
    _FETCH_CACHE.clear()

    mock_resp = MagicMock()
    mock_resp.read.return_value = b"<html><body><p>Hello world</p></body></html>"
    mock_resp.headers.get.return_value = "text/html; charset=utf-8"
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch("urllib.request.urlopen", return_value=mock_resp):
        result = url_fetch.invoke({"url": "http://example.com"})

    assert result["status"] == "ok"
    assert "Hello world" in result["content"]
    assert result["cached"] is False


def test_url_fetch_cached_on_second_call():
    from src.agents.git.tools import url_fetch, _FETCH_CACHE
    _FETCH_CACHE.clear()

    mock_resp = MagicMock()
    mock_resp.read.return_value = b"<p>Content</p>"
    mock_resp.headers.get.return_value = "text/html"
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch("urllib.request.urlopen", return_value=mock_resp):
        url_fetch.invoke({"url": "http://cached.example.com"})

    # Second call should use cache (no urlopen)
    with patch("urllib.request.urlopen", side_effect=Exception("Should not be called")) as mock_open:
        result = url_fetch.invoke({"url": "http://cached.example.com"})

    assert result["cached"] is True


def test_url_fetch_plain_text():
    from src.agents.git.tools import url_fetch, _FETCH_CACHE
    _FETCH_CACHE.clear()

    mock_resp = MagicMock()
    mock_resp.read.return_value = b"# README\nsome content"
    mock_resp.headers.get.return_value = "text/plain"
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch("urllib.request.urlopen", return_value=mock_resp):
        result = url_fetch.invoke({"url": "http://example.com/readme.md"})

    assert result["status"] == "ok"
    assert "README" in result["content"]


def test_url_fetch_truncates_at_max_chars():
    from src.agents.git.tools import url_fetch, _FETCH_CACHE
    _FETCH_CACHE.clear()

    long_content = b"x" * 100_000
    mock_resp = MagicMock()
    mock_resp.read.return_value = long_content
    mock_resp.headers.get.return_value = "text/plain"
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch("urllib.request.urlopen", return_value=mock_resp):
        result = url_fetch.invoke({"url": "http://example.com/long", "max_chars": 1000})

    assert len(result["content"]) <= 1100  # some slack for the truncation marker


def test_url_fetch_network_error():
    from src.agents.git.tools import url_fetch, _FETCH_CACHE
    _FETCH_CACHE.clear()

    with patch("urllib.request.urlopen", side_effect=Exception("Connection refused")):
        result = url_fetch.invoke({"url": "http://unreachable.invalid"})

    assert result["status"] == "error"
    assert "Connection refused" in result["error"]


def test_url_fetch_cache_ttl_expired():
    from src.agents.git.tools import url_fetch, _FETCH_CACHE, _cache_get, _cache_set
    _FETCH_CACHE.clear()

    # Manually insert an expired cache entry
    _FETCH_CACHE["http://old.example.com"] = (time.time() - 1000, {
        "status": "ok", "url": "http://old.example.com", "content": "old", "chars": 3, "cached": False,
    })

    mock_resp = MagicMock()
    mock_resp.read.return_value = b"fresh content"
    mock_resp.headers.get.return_value = "text/plain"
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch("urllib.request.urlopen", return_value=mock_resp):
        result = url_fetch.invoke({"url": "http://old.example.com"})

    assert result["cached"] is False
    assert "fresh content" in result["content"]


# ── _html_to_markdown ─────────────────────────────────────────────────────────

def test_html_to_markdown_basic():
    from src.agents.git.tools import _html_to_markdown
    html = b"<html><body><h1>Title</h1><p>Hello world</p></body></html>"
    result = _html_to_markdown(html)
    assert "Title" in result
    assert "Hello world" in result


def test_html_to_markdown_strips_script():
    from src.agents.git.tools import _html_to_markdown
    html = b"<html><body><script>evil()</script><p>Good</p></body></html>"
    result = _html_to_markdown(html)
    assert "evil" not in result
    assert "Good" in result


def test_html_to_markdown_strips_style():
    from src.agents.git.tools import _html_to_markdown
    html = b"<html><body><style>.css{color:red}</style><p>Content</p></body></html>"
    result = _html_to_markdown(html)
    assert "color" not in result
    assert "Content" in result
