"""Vérifier l'effet, pas le jugement.

Un fichier écrit n'est pas un fichier qui marche. Vécu : une réécriture de
`tri.py` a produit un source où tout le corps était sur une seule ligne, avec des
`\\n` littéraux — le fichier existait, le diff s'affichait, et le script était
mort. Personne ne l'a vu avant l'exécution.

Le contrôle est DÉTERMINISTE : on demande au langage lui-même si le fichier tient
debout. Aucun appel de modèle, donc aucun token, et aucun jugement — juste
« est-ce que ça parse ? ». Ce qu'on ne sait pas vérifier n'est pas signalé : un
faux positif ferait corriger du code correct.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

#: Ce qu'on sait contrôler sans exécuter. Exécuter serait un autre métier — et un
#: risque : un script écrit à l'instant peut effacer, envoyer, appeler.
_CONTROLES = (".py", ".json")


def sait_verifier(chemin: str) -> bool:
    """Ce fichier fait-il partie de ce qu'on sait contrôler ?

    Public parce que la trace de décision doit distinguer « vérifié, il tient »
    de « personne ne sait vérifier ça ». Confondre les deux ferait passer la
    couverture actuelle — deux extensions — pour une garantie générale, et le
    trou ne se compterait jamais.
    """
    return Path(chemin).suffix in _CONTROLES


def _erreur_python(source: str) -> str:
    try:
        ast.parse(source)
    except SyntaxError as erreur:
        return f"ligne {erreur.lineno} : {erreur.msg}"
    return ""


def _erreur_json(source: str) -> str:
    try:
        json.loads(source)
    except ValueError as erreur:
        return str(erreur)
    return ""


def verifier(chemins: list[str]) -> list[str]:
    """Les fichiers qui ne tiennent pas debout, un message par fichier."""
    fautifs: list[str] = []
    for chemin in chemins:
        fichier = Path(chemin)
        if fichier.suffix not in _CONTROLES or not fichier.is_file():
            continue
        try:
            source = fichier.read_text(encoding="utf-8")
        except Exception:
            continue
        erreur = (_erreur_python(source) if fichier.suffix == ".py"
                  else _erreur_json(source))
        if erreur:
            fautifs.append(f"{fichier.name} — {erreur}")
    return fautifs


def consigne(fautifs: list[str]) -> str:
    """Ce qu'on dit au modèle. Un ordre, pas une question.

    Il vient d'écrire le fichier : il a le contenu, et l'erreur dit où. Demander
    l'autorisation de réparer sa propre casse n'apporte rien à personne.
    """
    detail = " ; ".join(fautifs)
    return (f"ÉCRIT MAIS CASSÉ — {detail}. Corrige-le TOI-MÊME maintenant, sans "
            f"rien demander : repropose le fichier entier réparé. Ne considère pas "
            f"la tâche finie tant qu'il ne parse pas.")
