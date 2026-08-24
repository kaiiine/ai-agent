"""Découpage d'une spec de projet en phases séquentielles — le premier appel de `/build`.

Vivait au milieu de `src/agents/coding/task_decomposer.py`, entre la dataclasse
`Phase` et la fonction qui l'utilise.

La table de budget l'accompagne : elle n'existe que pour remplir le champ
`{budget}` du prompt, et n'est lue nulle part ailleurs. Les séparer aurait laissé
la moitié d'une consigne dans chaque fichier.
"""
from __future__ import annotations

BUDGET_PAR_BACKEND: dict[str, str] = {
    "mistral":      "Backend Mistral — phases PETITES, max 12 tool calls. Préférer 5-6 phases.",
    "groq":         "Backend Groq — phases standard, max 20 tool calls. 4-5 phases.",
    "gemini":       "Backend Gemini — phases larges, max 25 tool calls. 4 phases.",
    "ollama_cloud": "Backend cloud — phases standard, max 20 tool calls. 4-5 phases.",
    "ollama":       "Backend local — phases TRÈS petites, max 10 tool calls. 6 phases.",
}

BUDGET_DEFAUT = "ollama_cloud"

SYSTEME = """\
Tu décomposes une spec de projet web en phases d'exécution séquentielles et indépendantes.
Réponds UNIQUEMENT avec du JSON (pas de markdown, pas d'explication).

{{
  "phases": [
    {{"title": "Setup & Scaffold", "scope": "Description précise..."}},
    ...
  ]
}}

Règles :
- Phase 1 = scaffold CLI + config stack (JAMAIS de contenu métier)
- Phase 2 = composants partagés (layout, header, footer, design system)
- Phases intermédiaires = pages/sections métier groupées logiquement
- Phase finale = polish, tests visuels, corrections finales
- scope = UNE SEULE CHAÎNE de caractères listant ce qui doit être livré, avec des
  tirets et des retours à la ligne DANS la chaîne. Jamais un tableau JSON.
- Ne jamais répéter le même travail dans 2 phases

Budget : {budget}
"""


def systeme_pour(backend: str) -> str:
    """Le prompt prêt à l'emploi, budget du backend inclus."""
    return SYSTEME.format(
        budget=BUDGET_PAR_BACKEND.get(backend, BUDGET_PAR_BACKEND[BUDGET_DEFAUT]))
