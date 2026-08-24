"""Poser des questions à l'utilisateur — avec un schéma qui dit sa propre forme.

`questions` était déclaré `list[dict]`. Le schéma JSON envoyé au modèle disait
donc « un tableau d'objets quelconques », et la vraie structure ne vivait que
dans la prose de la docstring. Un modèle robuste s'en accommode ; un modèle
moyen n'a aucune contrainte sur quoi s'appuyer et écrit l'appel EN TEXTE :

    { "questions": [ { "question": "…", "choices": [] }, … ] }

affiché à l'utilisateur au lieu d'être exécuté, `tool_calls` resté vide. Observé
sur `gpt-oss:120b-cloud`, et non rattrapé par le garde-fou de `graph.py` — qui
ne reconnaît que le balisage `<xxx:tool_call>` de MiniMax, pas un JSON nu.

Le schéma décrit maintenant chaque question. La coercition d'entrée reste
tolérante pour autant : typer guide le modèle, elle rattrape ceux qui envoient
quand même autre chose. Durcir sans elle transformerait une erreur récupérable
en échec dur.
"""
from __future__ import annotations

import json

from langchain_core.tools import tool
from pydantic import BaseModel, Field, field_validator

#: Au-delà, ce n'est plus une clarification mais un formulaire.
MAX_QUESTIONS = 5


class Question(BaseModel):
    """Une question, et les réponses proposées s'il y en a."""

    question: str = Field(description="La question posée à l'utilisateur.")
    choices: list[str] = Field(
        default_factory=list,
        description="3 à 5 réponses proposées. Laisser vide pour une question "
                    "ouverte. Ne jamais ajouter « Autre » : l'interface le fait.",
    )


class ArgsClarification(BaseModel):
    """Ce que le modèle doit produire — visible par lui dans le schéma."""

    questions: list[Question] = Field(
        description=f"1 à {MAX_QUESTIONS} questions à poser d'un seul coup.",
    )

    @field_validator("questions", mode="before")
    @classmethod
    def _tolerer_les_formes_approchantes(cls, brut):
        """Ramène à une liste de questions ce que le modèle a bien voulu envoyer.

        UNE CHAÎNE N'EST PAS UNE LISTE DE QUESTIONS. Python itère volontiers sur
        une chaîne : passée telle quelle, elle produit une question par
        CARACTÈRE — mille et quelques, et un terminal bloqué. C'est à la
        frontière de valider, pas à l'affichage de deviner.
        """
        if isinstance(brut, str):
            texte = brut.strip()
            return [{"question": texte}] if texte else []
        if not isinstance(brut, (list, tuple)):
            return brut                      # laisse pydantic dire ce qui cloche
        propres: list[dict] = []
        for item in brut:
            if isinstance(item, str) and item.strip():
                propres.append({"question": item.strip()})
            elif isinstance(item, dict):
                libelle = str(item.get("question", "")).strip()
                if not libelle:
                    continue
                entree: dict = {"question": libelle}
                choix = item.get("choices")
                if isinstance(choix, (list, tuple)) and choix:
                    entree["choices"] = [str(c) for c in choix]
                propres.append(entree)
            else:
                propres.append(item)
        return propres[:MAX_QUESTIONS]


@tool("ask_clarification", args_schema=ArgsClarification)
def ask_clarification(questions: list[Question]) -> str:
    """Ask the user clarifying questions via an interactive questionnaire.
    Use this ALWAYS when you need more info — never ask in plain text.

    Provide 3-5 choices when options are clear; omit choices for open-ended
    questions. The UI automatically adds an "Autre (préciser)" option — do NOT
    include it yourself. Max 5 questions.
    """
    charge = [
        q.model_dump(exclude_defaults=False) if isinstance(q, Question) else dict(q)
        for q in questions
    ]
    # `choices` vide se retire : l'interface distingue une question ouverte d'une
    # question à choix par l'ABSENCE de la clé, pas par une liste vide.
    for q in charge:
        if not q.get("choices"):
            q.pop("choices", None)
    return json.dumps({"questions": charge, "awaiting_input": True})
