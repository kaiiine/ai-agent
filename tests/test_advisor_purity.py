"""Garde-fou architectural : le cœur Advisor n'importe AUCUN framework/couche
d'interface. Test contraignant — inspecte l'AST de chaque module du package
Advisor et échoue sur tout import interdit (§Q2 du Lot 0)."""

from __future__ import annotations

import ast
import pathlib

_ADVISOR = pathlib.Path(__file__).resolve().parents[1] / "src" / "agents" / "quant" / "advisor"

# Namespaces interdits dans le cœur : frameworks + orchestration + couches d'interface.
_FORBIDDEN = (
    "langgraph", "langchain", "click", "fastapi",
    "src.orchestrator", "src.ui", "src.api",
    "src.agents.quant.tools",
)


def _imported_modules(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name
        elif isinstance(node, ast.ImportFrom):
            yield node.module or ""


def test_advisor_core_imports_no_forbidden_namespace():
    py_files = list(_ADVISOR.rglob("*.py"))
    assert py_files, "package advisor introuvable"

    violations: list[str] = []
    for path in py_files:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for module in _imported_modules(tree):
            if any(module == f or module.startswith(f + ".") for f in _FORBIDDEN):
                violations.append(f"{path.name} importe « {module} »")

    assert not violations, (
        "cœur Advisor doit rester pur domaine (aucun framework/interface) : "
        + "; ".join(violations)
    )
