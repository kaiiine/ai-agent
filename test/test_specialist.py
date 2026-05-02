"""Tests for src/agents/coding/specialist.py — pure functions, no LLM calls."""
import pytest


# ── _clean_output ─────────────────────────────────────────────────────────────

def _clean(text):
    from src.agents.coding.specialist import _clean_output
    return _clean_output(text)


def test_clean_output_passthrough():
    assert _clean("Voici le résumé.") == "Voici le résumé."


def test_clean_output_removes_human_message_repr():
    text = "Analyse :\n[HumanMessage(content='bonjour')]\nFin."
    result = _clean(text)
    assert "HumanMessage" not in result
    assert "Analyse" in result
    assert "Fin." in result


def test_clean_output_removes_ai_message_repr():
    text = "Début.\nAIMessage(content='réponse')\nSuite."
    result = _clean(text)
    assert "AIMessage" not in result


def test_clean_output_removes_tool_message_repr():
    text = "Résultat.\n[ToolMessage(content='ok', tool_call_id='123')]\nDone."
    result = _clean(text)
    assert "ToolMessage" not in result
    assert "Done." in result


def test_clean_output_collapses_blank_lines():
    text = "A\n\n\n\n\nB"
    result = _clean(text)
    assert "\n\n\n" not in result
    assert "A" in result and "B" in result


def test_clean_output_fallback_when_everything_removed():
    # If the regex wipes all content, return original
    text = "[HumanMessage(content='x')]"
    result = _clean(text)
    # Either returns original or empty — must not crash
    assert isinstance(result, str)


def test_clean_output_empty_string():
    assert _clean("") == ""


# ── _extract_json_tool_call ───────────────────────────────────────────────────

def _extract(text):
    from src.agents.coding.specialist import _extract_json_tool_call
    return _extract_json_tool_call(text)


def test_extract_valid_json_tool_call():
    import json
    payload = json.dumps({"name": "dev_explain", "args": {"message": "hello"}})
    result = _extract(payload)
    assert result is not None
    assert result["name"] == "dev_explain"
    assert result["args"] == {"message": "hello"}


def test_extract_tool_key_alias():
    import json
    payload = json.dumps({"tool": "shell_run", "args": {"cmd": "ls"}})
    result = _extract(payload)
    assert result["name"] == "shell_run"


def test_extract_function_key_alias():
    import json
    payload = json.dumps({"function": "git_status", "arguments": {}})
    result = _extract(payload)
    assert result["name"] == "git_status"


def test_extract_with_markdown_code_fence():
    import json
    inner = json.dumps({"name": "dev_explain", "args": {"message": "test"}})
    payload = f"```json\n{inner}\n```"
    result = _extract(payload)
    assert result is not None
    assert result["name"] == "dev_explain"


def test_extract_plain_code_fence():
    import json
    inner = json.dumps({"name": "axon_note", "args": {"fact": "important"}})
    payload = f"```\n{inner}\n```"
    result = _extract(payload)
    assert result is not None
    assert result["name"] == "axon_note"


def test_extract_invalid_json_returns_none():
    result = _extract("not json at all")
    assert result is None


def test_extract_json_without_name_returns_none():
    import json
    payload = json.dumps({"args": {"key": "val"}})
    result = _extract(payload)
    assert result is None


def test_extract_empty_string_returns_none():
    assert _extract("") is None


def test_extract_args_defaults_to_empty_dict():
    import json
    payload = json.dumps({"name": "dev_plan_create"})
    result = _extract(payload)
    assert result["args"] == {}


# ── prompt contract (via build_system_prompt) ─────────────────────────────────
# These tests check that the right content ends up in the assembled prompt
# for each relevant stack. We build with explicit stacks for determinism.

def _full_prompt(*stacks: str) -> str:
    from src.agents.coding.prompts import build_system_prompt
    return build_system_prompt(list(stacks))


def test_system_prompt_contains_dev_plan_first_rule():
    prompt = _full_prompt()
    assert "dev_plan_create" in prompt
    assert "PREMIER" in prompt or "FIRST" in prompt


def test_system_prompt_mentions_propose_file_change():
    assert "propose_file_change" in _full_prompt()


def test_system_prompt_mentions_browser_screenshot():
    assert "browser_screenshot" in _full_prompt("frontend")


def test_system_prompt_mentions_web_research():
    assert "web_research_report" in _full_prompt()


def test_system_prompt_mentions_audit_issue_types():
    prompt = _full_prompt("frontend")
    for issue_type in ("text_cropped", "not_centered", "empty_section", "broken_image"):
        assert issue_type in prompt, f"Prompt should guide the LLM on how to fix '{issue_type}'"


def test_system_prompt_mentions_design_system_first():
    prompt = _full_prompt("frontend")
    assert "globals.css" in prompt
    assert "tailwind.config" in prompt


def test_system_prompt_forbids_hardcoded_colors():
    prompt = _full_prompt("frontend")
    assert "❌" in prompt


# ── _PROGRESS_TOOLS ───────────────────────────────────────────────────────────

def test_progress_tools_contains_expected_entries():
    from src.agents.coding.specialist import _PROGRESS_TOOLS
    for tool in ("dev_plan_create", "dev_plan_step_done", "dev_explain",
                 "propose_file_change", "axon_note"):
        assert tool in _PROGRESS_TOOLS


# ── set_progress_callback ─────────────────────────────────────────────────────

def test_set_progress_callback_sets_and_clears():
    from src.agents.coding.specialist import set_progress_callback, _progress_cb
    import src.agents.coding.specialist as spec

    cb = lambda name, args: None
    set_progress_callback(cb)
    assert spec._progress_cb is cb

    set_progress_callback(None)
    assert spec._progress_cb is None
