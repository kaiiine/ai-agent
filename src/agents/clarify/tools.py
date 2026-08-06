import json
from langchain_core.tools import tool


@tool
def ask_clarification(questions: list[dict]) -> str:
    """Ask the user clarifying questions via an interactive questionnaire.
    Use this ALWAYS when you need more info — never ask in plain text.

    Each question: {"question": "...", "choices": ["opt1", "opt2", "opt3"]}
    Provide 3-5 choices when options are clear. Omit choices for open-ended questions.
    The UI automatically adds an "Autre (préciser)" option — do NOT include it yourself.
    Max 5 questions."""
    return json.dumps({"questions": questions, "awaiting_input": True})
