"""Comparaison d'une veille : la valeur relevée a-t-elle bougé assez pour alerter ?

Déterministe. Seule l'extraction de la valeur passe par le modèle.
"""
from __future__ import annotations

import re
from typing import Literal, TypedDict

Condition = Literal["change", "baisse", "hausse", "sous", "sur"]
CONDITIONS: tuple[str, ...] = ("change", "baisse", "hausse", "sous", "sur")


class Surveillance(TypedDict):
    quoi: str                    # « le prix en euros »
    condition: Condition
    seuil: float | None          # pour « sous » et « sur »
    derniere: str | None         # None au premier passage


#: La ligne que la tâche doit produire pour être comparable.
BALISE = "VALEUR"
_LIGNE = re.compile(rf"{BALISE}\s*:\s*(.+?)\s*$", re.MULTILINE)
_NOMBRE = re.compile(r"-?\d+(?:[.,]\d+)?")
_VIDES = ("inconnue", "inconnu", "none", "n/a", "")


def consigne(quoi: str) -> str:
    """Ce qu'on ajoute au prompt pour que la réponse soit comparable."""
    return (f"\n\nRelève {quoi}. Termine ta réponse par une ligne, et une seule, "
            f"de la forme :\n{BALISE}: <la valeur relevée>\n"
            f"Si tu ne parviens pas à la relever, écris `{BALISE}: inconnue`.")


def extraire(reponse: str) -> str | None:
    trouve = _LIGNE.search(reponse or "")
    if not trouve:
        return None
    valeur = trouve.group(1).strip().strip("`*_ ")
    return None if valeur.lower() in _VIDES else valeur


def _nombre(valeur: str | None) -> float | None:
    if valeur is None:
        return None
    trouve = _NOMBRE.search(valeur.replace(" ", "").replace(" ", ""))
    return float(trouve.group(0).replace(",", ".")) if trouve else None


def doit_alerter(veille: Surveillance, valeur: str | None) -> tuple[bool, str]:
    """(faut-il prévenir, pourquoi)."""
    # Un relevé impossible n'alerte jamais : une page en panne sonnerait à chaque
    # passage, et on apprendrait à ignorer l'alerte.
    if valeur is None:
        return False, "valeur non relevée"

    ancienne = veille.get("derniere")
    if ancienne is None:
        return False, "premier relevé"

    condition = veille.get("condition") or "change"
    if condition == "change":
        if valeur.strip() == ancienne.strip():
            return False, "inchangé"
        return True, f"{ancienne} → {valeur}"

    neuf, vieux = _nombre(valeur), _nombre(ancienne)
    if neuf is None:
        return False, "valeur non numérique"

    if condition == "baisse":
        monte = vieux is not None and neuf < vieux
        return (True, f"baisse : {vieux} → {neuf}") if monte else (False, "pas de baisse")
    if condition == "hausse":
        monte = vieux is not None and neuf > vieux
        return (True, f"hausse : {vieux} → {neuf}") if monte else (False, "pas de hausse")

    seuil = veille.get("seuil")
    if seuil is None:
        return False, "seuil absent"

    # Alerte au FRANCHISSEMENT seulement : un prix durablement bas sonnerait
    # sinon à chaque passage.
    dedans = neuf <= seuil if condition == "sous" else neuf >= seuil
    etait = vieux is not None and (vieux <= seuil if condition == "sous" else vieux >= seuil)
    if dedans and not etait:
        return True, f"passé {'sous' if condition == 'sous' else 'au-dessus de'} {seuil} : {neuf}"
    return (False, f"déjà du bon côté de {seuil}") if dedans else \
           (False, f"seuil {seuil} non franchi : {neuf}")


def decrire(veille: Surveillance) -> str:
    seuil = veille.get("seuil")
    quand = {
        "change": "à chaque changement",
        "baisse": "quand ça baisse",
        "hausse": "quand ça monte",
        "sous": f"quand ça passe sous {seuil}",
        "sur": f"quand ça dépasse {seuil}",
    }.get(veille.get("condition") or "change", "")
    releve = veille.get("derniere")
    etat = f"dernier relevé : {releve}" if releve else "jamais relevé"
    return f"{veille.get('quoi', '?')} — alerte {quand} ({etat})"
