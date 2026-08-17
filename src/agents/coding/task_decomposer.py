"""Décompose une spec.md en phases d'exécution indépendantes."""
from __future__ import annotations
import json, re
from dataclasses import dataclass

@dataclass
class Phase:
    index: int
    title: str
    scope: str

    def __post_init__(self) -> None:
        """Ramène le scope à une CHAÎNE, d'où qu'il vienne.

        Une dataclass annote mais n'impose rien, et deux producteurs alimentent ce
        champ : le modèle qui décompose la spec, et le rechargement de
        `build-state.json`. Le premier a rendu un TABLEAU JSON, ce que la consigne
        invitait à faire — l'exemple montrait une chaîne, la règle disait « scope =
        liste exhaustive ». La liste a été persistée telle quelle, et toute reprise
        de build plantait ensuite :

            TypeError: can only concatenate str (not "list") to str

        Normaliser ici plutôt qu'aux appelants : `_is_scaffold_phase` concatène,
        `_build_phase_task` interpole, et chacun aurait eu besoin du même correctif.
        Un état déjà écrit en liste se relit donc sans migration.
        """
        if isinstance(self.scope, (list, tuple)):
            self.scope = "\n".join(f"- {str(x).strip()}" for x in self.scope if str(x).strip())
        elif not isinstance(self.scope, str):
            self.scope = "" if self.scope is None else str(self.scope)

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
- scope = UNE SEULE CHAÎNE de caractères listant ce qui doit être livré, avec des
  tirets et des retours à la ligne DANS la chaîne. Jamais un tableau JSON.
- Ne jamais répéter le même travail dans 2 phases

Budget : {budget}
"""

_FALLBACK_PHASES = [
    Phase(1, "Setup & Scaffold",     "Initialiser le projet via CLI, configurer stack, structure de dossiers"),
    Phase(2, "Composants partagés",  "Layout, header, footer, design system (couleurs, typo, composants UI)"),
    Phase(3, "Pages principales",    "Implémenter les pages core définies dans la spec"),
    Phase(4, "Polish & finalisation","Vérification visuelle, corrections finales"),
]


def _phases_depuis(raw: str) -> list[Phase]:
    cleaned = re.sub(r"```(?:json)?\s*", "", raw).replace("```", "").strip()
    m = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not m:
        return []
    data = json.loads(m.group())
    return [Phase(index=i, title=p.get("title", f"Phase {i}"), scope=p.get("scope", ""))
            for i, p in enumerate(data.get("phases", []), start=1)]


def decompose(spec_text: str, backend: str) -> list[Phase]:
    """Décompose la spec en phases. Repli sur 4 phases génériques si tout échoue.

    Passe par la rotation de clés : sans elle, un simple 429 sur CE seul appel
    faisait retomber tout le `/build` sur les phases génériques — en silence, et
    quelles que soient les autres clés configurées.
    """
    from langchain_core.messages import HumanMessage, SystemMessage

    from src.llm import rotation
    from src.llm.models import make_coding_llm_with_key

    budget = _BACKEND_BUDGET.get(backend, _BACKEND_BUDGET["ollama_cloud"])
    messages = [SystemMessage(content=_DECOMPOSE_SYSTEM.format(budget=budget)),
                HumanMessage(content=f"Spec du projet :\n\n{spec_text[:8000]}")]

    for fournisseur, cle, llm in rotation.clients(backend, make_coding_llm_with_key):
        try:
            resp = llm.invoke(messages)
        except Exception as exc:   # noqa: BLE001
            if rotation.vaut_la_peine_de_reessayer(exc):
                rotation.marquer_echec(fournisseur, cle, exc)
                continue
            break
        try:
            phases = _phases_depuis(resp.content if hasattr(resp, "content") else str(resp))
        except Exception:   # noqa: BLE001 — JSON illisible : un autre modèle fera mieux
            continue
        if phases:
            return phases
    return _FALLBACK_PHASES
