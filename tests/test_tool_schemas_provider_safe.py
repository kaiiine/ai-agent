"""Les schémas d'outils doivent passer la validation du provider LE PLUS STRICT.

`ask_clarification` déclarait `questions: list` — sans type d'élément. Le schéma
produit portait `"items": {}`, un objet VIDE. OpenAI et Ollama l'acceptent,
Gemini le refuse :

    400 INVALID_ARGUMENT
    tools[0].function_declarations[19].parameters.properties[questions].items:
    missing field

Et comme `ask_clarification` est épinglé dans TOUTES les sélections, Gemini
échouait sur absolument chaque requête, en 0,1 s, avant d'avoir rien fait. Le
symptôme — « Gemini ne fait rien » — n'avait aucun rapport avec un quota.

Un schéma trop permissif ne se voit pas en test unitaire ni chez un provider
tolérant : il ne se manifeste que chez le plus strict, et sous la forme d'une
panne totale.
"""

from __future__ import annotations

import pytest

from src.orchestrator.registry import build_all_tools

TOOLS = build_all_tools()


def _schema(tool) -> dict:
    if isinstance(tool.args_schema, dict):
        return tool.args_schema
    return tool.args_schema.model_json_schema() if tool.args_schema else {}


def _arrays_sans_items(spec: dict, chemin: str) -> list[str]:
    """Parcourt le schéma en profondeur : un `array` fautif peut être imbriqué
    dans un `anyOf` ou dans les propriétés d'un objet."""
    fautes: list[str] = []
    if spec.get("type") == "array" and not spec.get("items"):
        fautes.append(chemin)
    for combinateur in ("anyOf", "oneOf", "allOf"):
        for i, sous in enumerate(spec.get(combinateur) or []):
            fautes += _arrays_sans_items(sous, f"{chemin}.{combinateur}[{i}]")
    for nom, sous in (spec.get("properties") or {}).items():
        fautes += _arrays_sans_items(sous, f"{chemin}.{nom}")
    return fautes


@pytest.mark.parametrize("tool", TOOLS, ids=[t.name for t in TOOLS])
def test_tout_tableau_declare_le_type_de_ses_elements(tool):
    """`list` nu produit `items: {}` — présent mais vide, donc invalide pour
    Gemini. Il faut `list[dict]`, `list[str]`, etc."""
    fautes = []
    for nom, spec in (_schema(tool).get("properties") or {}).items():
        fautes += _arrays_sans_items(spec, nom)
    assert not fautes, (
        f"{tool.name} : tableau sans type d'élément en {fautes} — "
        f"annoter `list[...]` plutôt que `list`")


def test_ask_clarification_reste_typé():
    """L'outil qui a causé la panne : épinglé partout, donc son schéma casse
    TOUTES les requêtes du provider strict, pas seulement celles qui l'appellent."""
    spec = _schema(next(t for t in TOOLS if t.name == "ask_clarification"))
    items = spec["properties"]["questions"].get("items")
    assert items and items.get("type") == "object"


def test_l_outil_fautif_etait_epingle_partout():
    """Rappel de l'ampleur : ce n'était pas un outil rare mal typé, c'était celui
    que chaque sélection embarque."""
    from src.orchestrator.tool_retriever import _PINNED_TOOLS

    assert "ask_clarification" in _PINNED_TOOLS
