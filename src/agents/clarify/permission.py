"""Demander une information, ce n'est pas demander la permission.

Vécu, sur « place-toi dans /tmp/axon-essai et supprime tout ce qu'il contient » :

    Confirmez-vous la suppression de tous les fichiers … ?
      ▶ Oui, supprime tout / Non, annule          ← ask_clarification
    …
    Commande DESTRUCTIVE : rm -rf /tmp/axon-essai/*
      ▶ Oui, exécuter / Non, annuler              ← la vraie barrière

Deux questions pour un seul geste. La première ne décidait rien : quelle que
soit la réponse, la seconde arrivait — c'est elle qui tient la porte. Le modèle
s'en servait comme d'une politesse, et la politesse coûtait un aller-retour.

AXON garde lui-même tout ce qui engage : une commande destructive, un envoi, un
fichier écrit (relu en diff), un plan. Aucune de ces portes n'a besoin qu'on
sonne avant. `ask_clarification` est là pour ce qu'AXON ne peut PAS deviner — une
bankroll, un choix de nom, une approche indécidable — pas pour un feu vert.

On le reconnaît à la FORME, pas au texte : un couple de réponses oui/non est une
demande d'autorisation, quelle qu'en soit la formulation. Le refus est
récupérable — le modèle agit, et la vraie barrière fait son office.
"""
from __future__ import annotations

import unicodedata

_OUI = ("oui", "yes", "ok", "d'accord", "daccord", "vas-y", "vasy", "confirme",
        "continue", "go", "valide")
_NON = ("non", "no", "nope", "annule", "annuler", "stop", "abandonne", "cancel")


def _sans_accent(texte: str) -> str:
    plie = unicodedata.normalize("NFD", texte.strip().lower())
    return "".join(c for c in plie if unicodedata.category(c) != "Mn")


def _commence_par(texte: str, prefixes: tuple[str, ...]) -> bool:
    nu = _sans_accent(texte)
    return any(nu == p or nu.startswith(p + " ") or nu.startswith(p + ",")
               for p in prefixes)


def demande_une_permission(choix) -> bool:
    """Ces réponses proposées forment-elles un oui/non ?

    Exactement deux : au-delà, c'est un vrai choix entre options. Zéro, c'est une
    question ouverte — donc une information.
    """
    if not isinstance(choix, (list, tuple)) or len(choix) != 2:
        return False
    textes = [str(c) for c in choix]
    return (any(_commence_par(t, _OUI) for t in textes)
            and any(_commence_par(t, _NON) for t in textes))


#: Ce qu'on répond quand la question demande un feu vert. Ce n'est PAS un refus :
#: un refus s'affiche en rouge, invite à réessayer, et donne à voir à
#: l'utilisateur une dispute interne dont il n'a que faire — vécu, deux fois de
#: suite sur un seul « supprime tout ». Le vrai travail est en amont, dans le
#: prompt : le modèle ne doit pas poser la question. Ceci n'est que le filet, et
#: un filet se traverse sans bruit.
SANS_OBJET = (
    "Accord acquis — continue. Cette question n'avait pas à être posée : AXON "
    "demande lui-même son accord à l'utilisateur au moment d'agir (commande "
    "destructive, envoi, fichier écrit montré en diff, plan). Poursuis "
    "maintenant ; la vraie confirmation lui sera présentée au bon moment, avec "
    "l'action sous les yeux. Réserve `ask_clarification` à ce qu'on ne peut pas "
    "deviner : une valeur, un nom, une approche indécidable."
)
