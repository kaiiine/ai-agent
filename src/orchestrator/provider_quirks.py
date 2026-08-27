# src/orchestrator/provider_quirks.py
"""Contournements de comportements SPÉCIFIQUES à un fournisseur.

Isolés ici pour deux raisons : le flux principal reste lisible sans eux, et
chacun porte la trace de ce qu'il contourne — un contournement dont on a oublié
la cause ne s'enlève jamais.
"""
from __future__ import annotations

import re
from typing import List

from langchain_core.messages import AIMessage, ToolMessage

_MALFORMED_TOOL_CALL_RE = re.compile(r"\w+:tool_call\b.*?</\w+:tool_call>", re.DOTALL | re.IGNORECASE)

def _sanitize_messages_for_mistral(messages: List) -> List:
    """Mistral requires strict tool_call/tool_result pairing.
    Removes AIMessages with unanswered tool_calls AND ToolMessages
    that became orphaned (e.g. after context compression dropped their parent AIMessage)."""
    all_response_ids = {m.tool_call_id for m in messages if isinstance(m, ToolMessage)}

    valid_call_ids: set[str] = set()
    removed_ai: set[int] = set()
    for i, m in enumerate(messages):
        if isinstance(m, AIMessage) and getattr(m, "tool_calls", None):
            tc_ids = [tc["id"] for tc in m.tool_calls]
            if all(tid in all_response_ids for tid in tc_ids):
                valid_call_ids.update(tc_ids)
            else:
                removed_ai.add(i)

    return [
        m
        for i, m in enumerate(messages)
        if i not in removed_ai
        and not (isinstance(m, ToolMessage) and m.tool_call_id not in valid_call_ids)
    ]

def outil_ecrit_en_json(texte: str, outils: List) -> str | None:
    """Nom de l'outil dont les paramètres correspondent à un JSON écrit en texte.

    Autre forme du même défaut que `_MALFORMED_TOOL_CALL_RE`, sans balise pour la
    trahir : le modèle rend `{"definition": "...", "title": "...", "export_to": ""}`
    comme réponse finale. `tool_calls` est vide, rien ne s'exécute, et l'utilisateur
    reçoit les arguments au lieu du résultat. Vécu sur gpt-oss:120b avec
    `mermaid_diagram` pourtant lié : aucun diagramme produit.

    On n'accepte que si le JSON occupe l'essentiel de la réponse — sinon un exemple
    de configuration cité dans une explication déclencherait la correction.
    """
    import json

    depart = texte.find("{")
    fin = texte.rfind("}")
    if depart < 0 or fin <= depart:
        return None
    bloc = texte[depart:fin + 1]
    if len(bloc) < len(texte.strip()) * 0.8:
        return None
    try:
        objet = json.loads(bloc)
    except (ValueError, TypeError):
        return None
    if not isinstance(objet, dict) or not objet:
        return None

    cles = set(objet)
    for outil in outils:
        try:
            schema = outil.args_schema.model_json_schema()
        except Exception:
            continue
        parametres = set(schema.get("properties") or {})
        requis = set(schema.get("required") or {})
        if parametres and cles <= parametres and requis <= cles:
            return outil.name
    return None
