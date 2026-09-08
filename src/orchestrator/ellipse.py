"""Reconnaître un tour qui n'a de sens que par le tour d'avant.

« reprend ou tu en étais sans rien oublier » ne dit rien d'un domaine. Le routeur
élit alors le groupe le moins improbable et le modèle appelle `shell_ls` — seul
échec SILENCIEUX qui survive à toutes les exécutions de `outils/mesure_filet.py`.

Le test qui existait était un proxy de LONGUEUR : moins de huit mots, on recollait
les trois derniers tours. Il échouait pile sur le cas qu'il devait attraper — la
phrase ci-dessus fait exactement huit mots.

Ce qui remplace le proxy, et pourquoi pas autre chose :

    aucun signal de domaine    le vocabulaire vient des `keywords` et
                               `soft_keywords` DÉJÀ mesurés des groupes, pas
                               d'une liste de marqueurs écrite pour l'occasion.
                               Une liste curée à la main est ce qui a produit
                               vingt points de surajustement sur les alias de
                               skills ; on n'en ajoute pas une deuxième.

    et la requête est courte   parce que la longueur, mesurée, sépare mieux que
                               tout le reste : médiane 3 mots contre 15.

Deux pistes essayées et ÉCARTÉES sur mesure, pas sur intuition :

    la marge `_MARGE_CLAUSE`   « aucun groupe ne se détache » ne sépare rien :
                               les distances se tassent, et 77 requêtes
                               autoportantes sur 80 sont elles aussi « non
                               séparées ».
    la distance au rang 1      distributions superposées — ellipses 0,76→0,99,
                               autoportantes 0,40→0,97.

Mesuré, jeu tenu à l'écart jamais vu pendant le réglage (`tests/corpus_ellipses.py`) :

                        rappel      faux positifs
    proxy < 8 mots      6/10          4/51
    ce test             9/10          9/51

Et un faux positif ne coûte RIEN : recoller des tours même SANS RAPPORT laisse le
routage à 14/17 requêtes servies, identique à la requête seule. On échange donc
trente points de rappel contre un coût mesuré nul.

RÉSERVE — ce zéro-coût tient sur DIX-SEPT cas. C'est assez pour écarter « le
recollage dégrade franchement », pas pour établir un taux. Le jour où le harnais
s'élargira pour viser un vrai taux sous 1 %, le coût du faux positif doit entrer
dans le lot au même titre que le rappel : ici il est écarté, pas clos.

Le choix des vocabulaires est expliqué sur `_vocabulaire`, celui du seuil sur
`_MOTS_MAX`.
"""
from __future__ import annotations

from functools import lru_cache

#: Au-delà, la requête se porte elle-même : la médiane des autoportantes est à 15
#: mots contre 3 pour les ellipses.
#:
#: PROVENANCE DU SEUIL — parce qu'un seuil dont on ignore l'origine ne se
#: distingue plus, six mois après, d'un seuil qui a fuité du jeu de validation.
#:
#: Choisi par balayage 6/8/10/12/14/18 sur `ELLIPSES_REGLAGE` et
#: `AUTONOMES_REGLAGE` SEULS, avant toute mesure sur le jeu tenu à l'écart. Le
#: critère de choix était de dominer la référence en place (`< 8 mots`) sur ce
#: même jeu : rappel 8/9 contre 7/9, faux positifs 19/80 contre 20/80.
#:
#: EXPOSITION DÉCLARÉE : en comparant ensuite les vocabulaires, `< 14` est apparu
#: à 10/10 sur le jeu tenu à l'écart, contre 9/10 pour 12. Le seuil n'a PAS été
#: déplacé — le corriger après coup sur ce jeu-là le brûlerait, et un gain d'un
#: cas ne vaut pas la perte de l'unique mesure honnête dont on dispose.
_MOTS_MAX = 12

#: Ce qui ancre une requête dans le monde sans passer par le vocabulaire des
#: groupes : une URL, un chemin, une adresse.
_ANCRES = ("http", "/", "@", ".com")


@lru_cache(maxsize=1)
def _vocabulaire() -> frozenset[str]:
    """Les termes que les groupes déclarent déjà couvrir.

    On ne réécrit pas ce vocabulaire : il est mesuré, discuté dans
    `tool_retriever`, et il bouge avec les groupes. Une liste parallèle
    divergerait au premier groupe ajouté.

    Il est MAIGRE — 128 termes — et ça se paie : « quels sont mes fichiers
    modifiés ? » n'y trouve rien et se déclenche à tort. Deux vocabulaires plus
    riches ont été essayés, tous deux REJETÉS sur le jeu de réglage seul, donc
    sans regarder le jeu de validation :

        tous les mots des documents de groupe    rappel 4/9 (contre 8/9)
        idem, filtrés par distinctivité          rappel 5/9

    Les documents portent du français ordinaire — « quels », « sont », « quel » —
    et la distinctivité ne l'élimine pas : ces mots-là n'apparaissent eux-mêmes
    que dans un ou deux documents. Élargir la source élargit le bruit avec elle.
    """
    from src.orchestrator.tool_retriever import TOOL_GROUPS

    termes: set[str] = set()
    for spec in TOOL_GROUPS.values():
        termes |= set(spec.keywords) | set(spec.soft_keywords)
    return frozenset(termes)


def porte_un_signal(requete: str) -> bool:
    """La requête nomme-t-elle un domaine, ou pointe-t-elle quelque chose ?"""
    from src.orchestrator.tool_retriever import _WORD

    if any(ancre in requete for ancre in _ANCRES):
        return True
    return bool({mot.lower() for mot in _WORD.findall(requete)} & _vocabulaire())


def est_une_ellipse(requete: str) -> bool:
    """Ce tour a-t-il besoin des précédents pour vouloir dire quelque chose ?"""
    from src.orchestrator.tool_retriever import _WORD

    if not requete or not requete.strip():
        return False
    return len(_WORD.findall(requete)) < _MOTS_MAX and not porte_un_signal(requete)
