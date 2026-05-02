"""Tests for src/agents/coding/tools.py — coding agent tools."""
import pytest
from unittest.mock import patch, MagicMock


# ── dev_plan_create ───────────────────────────────────────────────────────────

def test_dev_plan_create_ok():
    from src.agents.coding.tools import dev_plan_create
    result = dev_plan_create.invoke({"steps": ["Lire app.py", "Modifier route", "Tester"]})
    assert result["status"] == "ok"
    assert result["count"] == 3


def test_dev_plan_create_empty_steps():
    from src.agents.coding.tools import dev_plan_create
    result = dev_plan_create.invoke({"steps": []})
    assert result["status"] == "error"


def test_dev_plan_create_single_step():
    from src.agents.coding.tools import dev_plan_create
    result = dev_plan_create.invoke({"steps": ["Unique step"]})
    assert result["status"] == "ok"
    assert result["count"] == 1


# ── dev_plan_step_done ────────────────────────────────────────────────────────

def test_dev_plan_step_done_ok():
    from src.agents.coding.tools import dev_plan_create, dev_plan_step_done
    dev_plan_create.invoke({"steps": ["A", "B", "C"]})
    result = dev_plan_step_done.invoke({"step_index": 0})
    assert result["status"] == "ok"
    assert result["step"] == "A"
    assert "remaining" in result
    assert result["remaining"] == 2


def test_dev_plan_step_done_already_done():
    from src.agents.coding.tools import dev_plan_create, dev_plan_step_done
    dev_plan_create.invoke({"steps": ["A"]})
    dev_plan_step_done.invoke({"step_index": 0})
    result = dev_plan_step_done.invoke({"step_index": 0})
    assert result["status"] == "already_done"


def test_dev_plan_step_done_out_of_range():
    from src.agents.coding.tools import dev_plan_create, dev_plan_step_done
    dev_plan_create.invoke({"steps": ["A", "B"]})
    result = dev_plan_step_done.invoke({"step_index": 99})
    assert result["status"] == "error"


def test_dev_plan_step_done_no_plan():
    from src.agents.coding.tools import dev_plan_step_done
    result = dev_plan_step_done.invoke({"step_index": 0})
    assert result["status"] == "error"


def test_dev_plan_step_done_remaining_reaches_zero():
    from src.agents.coding.tools import dev_plan_create, dev_plan_step_done
    dev_plan_create.invoke({"steps": ["A", "B"]})
    dev_plan_step_done.invoke({"step_index": 0})
    result = dev_plan_step_done.invoke({"step_index": 1})
    assert result["remaining"] == 0


# ── dev_explain ───────────────────────────────────────────────────────────────

def test_dev_explain_ok():
    from src.agents.coding.tools import dev_explain
    result = dev_explain.invoke({"message": "Voici ce que j'ai trouvé."})
    assert result["status"] == "ok"
    assert result["message"] == "Voici ce que j'ai trouvé."


def test_dev_explain_empty_message():
    from src.agents.coding.tools import dev_explain
    result = dev_explain.invoke({"message": ""})
    assert result["status"] == "ok"


# ── propose_file_change ───────────────────────────────────────────────────────

def test_propose_file_change_without_plan():
    from src.agents.coding.tools import propose_file_change
    result = propose_file_change.invoke({
        "path": "/proj/app.py",
        "content": "print('hello')",
        "description": "Init app",
    })
    assert result["status"] == "error"


def test_propose_file_change_new_file(tmp_path):
    from src.agents.coding.tools import dev_plan_create, propose_file_change
    dev_plan_create.invoke({"steps": ["Créer app.py"]})
    new_file = str(tmp_path / "app.py")
    result = propose_file_change.invoke({
        "path": new_file,
        "content": "print('hello')",
        "description": "Créer app.py",
    })
    assert result["status"] == "proposed"
    assert result["is_new_file"] is True
    assert result["awaiting_confirmation"] is True
    assert result["path"] == new_file


def test_propose_file_change_existing_file(tmp_path):
    from src.agents.coding.tools import dev_plan_create, propose_file_change
    dev_plan_create.invoke({"steps": ["Modifier app.py"]})
    f = tmp_path / "app.py"
    f.write_text("original")
    result = propose_file_change.invoke({
        "path": str(f),
        "content": "modified",
        "description": "Fix bug",
    })
    assert result["status"] == "proposed"
    assert result["is_new_file"] is False


def test_propose_file_change_adds_to_pending(tmp_path):
    from src.agents.coding.tools import dev_plan_create, propose_file_change
    from src.agents.coding.pending import pending_changes
    dev_plan_create.invoke({"steps": ["Step"]})
    propose_file_change.invoke({
        "path": str(tmp_path / "a.py"),
        "content": "a",
        "description": "desc",
    })
    propose_file_change.invoke({
        "path": str(tmp_path / "b.py"),
        "content": "b",
        "description": "desc",
    })
    assert len(pending_changes) == 2


def test_propose_file_change_replaces_same_path(tmp_path):
    from src.agents.coding.tools import dev_plan_create, propose_file_change
    from src.agents.coding.pending import pending_changes
    dev_plan_create.invoke({"steps": ["Step"]})
    path = str(tmp_path / "app.py")
    propose_file_change.invoke({"path": path, "content": "v1", "description": "v1"})
    propose_file_change.invoke({"path": path, "content": "v2", "description": "v2"})
    assert len(pending_changes) == 1
    assert pending_changes.items[0].proposed == "v2"


# ── browser_screenshot ────────────────────────────────────────────────────────

def test_browser_screenshot_delegates_to_screenshot_url():
    from src.agents.coding.tools import browser_screenshot
    mock_result = {
        "status": "ok",
        "screenshot_path": "/tmp/axon_screenshot_123.png",
        "url": "http://localhost:3000",
        "page_text": "Hello world",
        "audit": {"issues": [], "issueCount": 0},
    }
    with patch("src.infra.browser.screenshot_url", return_value=mock_result) as mock_fn:
        result = browser_screenshot.invoke({
            "url": "http://localhost:3000",
            "width": 1280,
            "height": 900,
            "wait_ms": 2500,
        })
    mock_fn.assert_called_once_with(
        "http://localhost:3000", width=1280, height=900, wait_ms=2500
    )
    assert result["status"] == "ok"
    assert "audit" in result


def test_browser_screenshot_propagates_error():
    from src.agents.coding.tools import browser_screenshot
    with patch("src.infra.browser.screenshot_url", return_value={"status": "error", "error": "timeout"}):
        result = browser_screenshot.invoke({"url": "http://localhost:9999"})
    assert result["status"] == "error"
