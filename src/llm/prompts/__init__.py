"""Tous les prompts système d'Axon — un fichier par agent.

Ils vivaient dans cinq fichiers différents, chacun collé au code qui l'appelait :
`prompts.py` pour l'orchestrateur, mais aussi une constante au milieu de
`cron_daemon.py`, une autre dans `spec/review.py`, une troisième dans
`task_decomposer.py`. Pour relire ou corriger un prompt, il fallait d'abord
savoir lequel des cinq le contenait.

    orchestrateur.py   les 19 sections conditionnelles + `build_system_prompt`
    revue_spec.py      la relecture de spécification avant exécution
    cron.py            l'agent de monitoring autonome
    decomposeur.py     le découpage d'une spec en phases de `/build`

Le prompt du SPECIALIST reste dans `src/agents/coding/prompts/` : il est le seul
à porter un paquet dédié depuis longtemps, et les guides par stack qui
l'accompagnaient s'y référaient.

Ce module ré-exporte ce que les appelants importaient déjà de `src.llm.prompts`.
Le passage de module à paquet est donc invisible : `from src.llm.prompts import
build_system_prompt` continue de fonctionner, aux douze sites d'import existants
comme aux suivants.
"""
from __future__ import annotations

from src.llm.prompts.orchestrateur import (
    _CODING,
    _CORE,
    _CRON,
    _EMAIL,
    _FILES,
    _GEMINI_FORMAT,
    _GOOGLE,
    _JIRA,
    _LANG_INSTRUCTIONS,
    _MCP,
    _MEMORY,
    _MERMAID,
    _PLAN_MODE,
    _QUANT,
    _SHELL,
    _SKILLS,
    _SLACK,
    _STUDY,
    _WEB,
    build_system_prompt,
)

__all__ = [
    "build_system_prompt",
    "_CORE", "_WEB", "_FILES", "_SHELL", "_CODING", "_SLACK", "_GOOGLE",
    "_JIRA", "_EMAIL", "_MERMAID", "_MCP", "_SKILLS", "_MEMORY", "_QUANT",
    "_CRON", "_STUDY", "_PLAN_MODE", "_GEMINI_FORMAT", "_LANG_INSTRUCTIONS",
]
