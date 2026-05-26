"""Décompose une spec.md en phases d'exécution indépendantes."""
from __future__ import annotations
import json, re
from dataclasses import dataclass

@dataclass
class Phase:
    index: int
    title: str
    scope: str

_BACKEND_BUDGET = {
    "mistral":      "Backend Mistral — phases PETITES, max 12 tool calls. Préférer 5-6 phases.",
    "groq":         "Backend Groq — phases standard, max 20 tool calls. 4-5 phases.",
    "gemini":       "Backend Gemini — phases larges, max 25 tool calls. 4 phases.",
    "ollama_cloud": "Backend cloud — phases standard, max 20 tool calls. 4-5 phases.",
    "ollama":       "Backend local — phases TRÈS petites, max 10 tool calls. 6 phases.",
}

_DECOMPOSE_SYSTEM = """\
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
- scope = liste exhaustive de ce qui DOIT être livré dans cette phase, sous forme de tirets
- Ne jamais répéter le même travail dans 2 phases

Budget : {budget}
"""

_FALLBACK_PHASES = [
    Phase(1, "Setup & Scaffold",     "Initialiser le projet via CLI, configurer stack, structure de dossiers"),
    Phase(2, "Composants partagés",  "Layout, header, footer, design system (couleurs, typo, composants UI)"),
    Phase(3, "Pages principales",    "Implémenter les pages core définies dans la spec"),
    Phase(4, "Polish & finalisation","Vérification visuelle, corrections finales"),
]


def decompose(spec_text: str, backend: str) -> list[Phase]:
    """Appelle le LLM pour décomposer spec_text en phases. Fallback sur 4 phases génériques."""
    try:
        from src.llm.models import make_llm_ollama_cloud, make_llm_groq, make_llm_gemini, make_llm_mistral
        from langchain_core.messages import SystemMessage, HumanMessage
        _factories = {
            "groq": make_llm_groq, "ollama_cloud": make_llm_ollama_cloud,
            "gemini": make_llm_gemini, "mistral": make_llm_mistral,
        }
        llm = _factories.get(backend, make_llm_ollama_cloud)()
        budget = _BACKEND_BUDGET.get(backend, _BACKEND_BUDGET["ollama_cloud"])
        resp = llm.invoke([
            SystemMessage(content=_DECOMPOSE_SYSTEM.format(budget=budget)),
            HumanMessage(content=f"Spec du projet :\n\n{spec_text[:8000]}"),
        ])
        raw = resp.content if hasattr(resp, "content") else str(resp)
        cleaned = re.sub(r"```(?:json)?\s*", "", raw).replace("```", "").strip()
        m = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if not m:
            return _FALLBACK_PHASES
        data = json.loads(m.group())
        phases = [
            Phase(index=i, title=p.get("title", f"Phase {i}"), scope=p.get("scope", ""))
            for i, p in enumerate(data.get("phases", []), start=1)
        ]
        return phases if phases else _FALLBACK_PHASES
    except Exception:
        return _FALLBACK_PHASES
