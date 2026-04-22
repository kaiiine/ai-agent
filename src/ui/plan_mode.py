"""Plan mode — read-only planning state.

When active, all write-capable tools are stripped from the LLM's tool list.
The LLM analyses, reasons, and proposes — but cannot execute.
Toggle with Ctrl+T or /plan.
"""
from __future__ import annotations

_state = {"active": False}

# Tools that create, modify, delete or send anything — blocked in plan mode.
BLOCKED_TOOLS: frozenset[str] = frozenset({
    "shell_run", "process_kill", "clipboard_write", "notify",
    "git_add", "git_commit", "git_checkout", "git_stash",
    "run_coding_agent",
    "google_docs_create", "google_docs_update",
    "create_presentation", "add_slide",
    "gmail_send_email", "gmail_confirm_send", "gmail_edit_draft",
    "drive_delete_file",
    "calendar_create_event", "calendar_update_event", "calendar_delete_event",
    "slack_send_message",
    "jira_create_issue", "jira_create_issues_bulk", "jira_add_comment",
    "jira_transition_issue", "jira_assign_issue", "jira_update_issue",
    "jira_move_issue", "jira_delete_issue", "jira_link_to_epic",
})


def is_active() -> bool:
    return _state["active"]


def toggle() -> bool:
    _state["active"] = not _state["active"]
    return _state["active"]


def set_active(value: bool) -> None:
    _state["active"] = value
