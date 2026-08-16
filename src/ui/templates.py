"""Templates de prompt vivant dans `skills/`, mais qui ne sont PAS des skills.

Un skill est un guide qu'un modèle choisit de charger. Ceux-ci sont des gabarits
consommés par le code : les exposer au catalogue ferait charger 277 lignes de
HTML à un modèle croyant lire des consignes. D'où `scope: [template]`, qu'aucun
agent ne lit.

Les jetons sont `%%NOM%%` et non `{nom}` : le HTML embarque du CSS, et `.format()`
imposait de doubler chaque accolade — un piège silencieux dès qu'on éditait le
fichier.
"""

from __future__ import annotations

SCOPE = "template"


def charger(nom: str, **jetons: str) -> str:
    """Rend le template `nom` avec ses jetons substitués.

    Le nom est vérifié AVANT la lecture : le retriever fait une recherche
    sémantique et rendrait le gabarit le plus proche pour un nom inconnu — donc
    le mauvais prompt, sans que rien ne le signale.
    """
    from src.skills import get_skill, list_skills

    if nom not in list_skills(SCOPE):
        raise LookupError(f"template introuvable : skills/{nom}.md")
    texte = get_skill(nom, scope=SCOPE)
    for cle, valeur in jetons.items():
        texte = texte.replace(f"%%{cle.upper()}%%", valeur)
    return texte
