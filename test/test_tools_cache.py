"""Tests for src/infra/tools_cache.py — SessionCache, CACHEABLE_TOOLS, _INVALIDATES."""
import time
import pytest

from src.infra.tools_cache import SessionCache, CACHEABLE_TOOLS, CACHE_TTLS, _INVALIDATES


# ── SessionCache.get / set ────────────────────────────────────────────────────

def test_get_missing_returns_none():
    cache = SessionCache()
    assert cache.get("local_read_file", {"path": "/tmp/x"}) is None


def test_set_then_get_roundtrip():
    cache = SessionCache()
    cache.set("local_read_file", {"path": "/tmp/x"}, "hello", ttl=60)
    assert cache.get("local_read_file", {"path": "/tmp/x"}) == "hello"


def test_different_args_different_entries():
    cache = SessionCache()
    cache.set("local_read_file", {"path": "/a"}, "A", ttl=60)
    cache.set("local_read_file", {"path": "/b"}, "B", ttl=60)
    assert cache.get("local_read_file", {"path": "/a"}) == "A"
    assert cache.get("local_read_file", {"path": "/b"}) == "B"


def test_expired_entry_returns_none(monkeypatch):
    cache = SessionCache()
    cache.set("git_status", {}, "stale", ttl=1)
    # Fast-forward time by patching time.time
    original = time.time
    monkeypatch.setattr(time, "time", lambda: original() + 10)
    assert cache.get("git_status", {}) is None


def test_not_expired_entry_returned(monkeypatch):
    cache = SessionCache()
    cache.set("git_status", {}, "fresh", ttl=300)
    original = time.time
    monkeypatch.setattr(time, "time", lambda: original() + 5)
    assert cache.get("git_status", {}) == "fresh"


def test_set_uses_cache_ttls_by_default():
    cache = SessionCache()
    cache.set("web_research_report", {"query": "test"}, "result")
    # Entry should be present (TTL = 300s by default)
    assert cache.get("web_research_report", {"query": "test"}) == "result"


def test_len():
    cache = SessionCache()
    assert len(cache) == 0
    cache.set("git_log", {}, "log", ttl=60)
    assert len(cache) == 1
    cache.set("git_status", {}, "status", ttl=60)
    assert len(cache) == 2


def test_clear():
    cache = SessionCache()
    cache.set("git_log", {}, "log", ttl=60)
    cache.clear()
    assert len(cache) == 0
    assert cache.get("git_log", {}) is None


# ── SessionCache.invalidate ───────────────────────────────────────────────────

def test_invalidate_removes_matching_tool():
    cache = SessionCache()
    cache.set("git_status", {}, "status", ttl=60)
    cache.set("git_log", {}, "log", ttl=60)
    cache.invalidate("git_status")
    assert cache.get("git_status", {}) is None
    assert cache.get("git_log", {}) == "log"  # unaffected


def test_invalidate_multiple():
    cache = SessionCache()
    cache.set("git_status", {}, "s", ttl=60)
    cache.set("git_diff", {}, "d", ttl=60)
    cache.set("git_log", {}, "l", ttl=60)
    cache.invalidate("git_status", "git_diff")
    assert cache.get("git_status", {}) is None
    assert cache.get("git_diff", {}) is None
    assert cache.get("git_log", {}) == "l"


def test_invalidate_nonexistent_is_noop():
    cache = SessionCache()
    cache.invalidate("nonexistent_tool")  # must not raise


# ── SessionCache.on_tool_executed ────────────────────────────────────────────

def test_git_add_invalidates_status_and_diff():
    cache = SessionCache()
    cache.set("git_status", {}, "s", ttl=60)
    cache.set("git_diff", {}, "d", ttl=60)
    cache.set("git_log", {}, "l", ttl=60)
    cache.on_tool_executed("git_add")
    assert cache.get("git_status", {}) is None
    assert cache.get("git_diff", {}) is None
    assert cache.get("git_log", {}) == "l"  # not in git_add invalidation


def test_git_commit_invalidates_status_log_diff():
    cache = SessionCache()
    cache.set("git_status", {}, "s", ttl=60)
    cache.set("git_log", {}, "l", ttl=60)
    cache.set("git_diff", {}, "d", ttl=60)
    cache.on_tool_executed("git_commit")
    assert cache.get("git_status", {}) is None
    assert cache.get("git_log", {}) is None
    assert cache.get("git_diff", {}) is None


def test_shell_run_invalidates_all_filesystem_caches():
    cache = SessionCache()
    for tool in ("git_status", "git_diff", "git_log",
                 "local_read_file", "local_list_directory", "local_find_file", "local_glob"):
        cache.set(tool, {}, "val", ttl=60)
    cache.on_tool_executed("shell_run")
    for tool in ("git_status", "git_diff", "git_log",
                 "local_read_file", "local_list_directory", "local_find_file", "local_glob"):
        assert cache.get(tool, {}) is None, f"{tool} should have been invalidated"


def test_propose_file_change_invalidates_filesystem():
    cache = SessionCache()
    cache.set("local_read_file", {"path": "/proj/app.py"}, "old content", ttl=60)
    cache.on_tool_executed("propose_file_change")
    assert cache.get("local_read_file", {"path": "/proj/app.py"}) is None


def test_unknown_tool_on_executed_is_noop():
    cache = SessionCache()
    cache.set("git_status", {}, "s", ttl=60)
    cache.on_tool_executed("some_random_tool")
    assert cache.get("git_status", {}) == "s"


# ── CACHEABLE_TOOLS contract ──────────────────────────────────────────────────

def test_cacheable_tools_is_frozenset():
    assert isinstance(CACHEABLE_TOOLS, frozenset)


def test_expected_tools_are_cacheable():
    for tool in ("local_read_file", "local_list_directory", "local_find_file",
                 "local_glob", "git_status", "git_log", "git_diff",
                 "web_research_report", "web_search_news"):
        assert tool in CACHEABLE_TOOLS, f"{tool} should be in CACHEABLE_TOOLS"


def test_browser_screenshot_not_cacheable():
    assert "browser_screenshot" not in CACHEABLE_TOOLS


def test_shell_run_not_cacheable():
    assert "shell_run" not in CACHEABLE_TOOLS


def test_propose_file_change_not_cacheable():
    assert "propose_file_change" not in CACHEABLE_TOOLS


def test_cacheable_tools_matches_cache_ttls():
    assert set(CACHEABLE_TOOLS) == set(CACHE_TTLS.keys())


# ── _INVALIDATES contract ────────────────────────────────────────────────────

def test_invalidates_has_shell_run():
    assert "shell_run" in _INVALIDATES


def test_invalidates_has_propose_file_change():
    assert "propose_file_change" in _INVALIDATES


def test_browser_screenshot_not_in_invalidates():
    assert "browser_screenshot" not in _INVALIDATES
