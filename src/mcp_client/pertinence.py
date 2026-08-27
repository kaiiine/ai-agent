"""Un serveur MCP ne doit être lié que si la conversation le concerne.

L'étage 1 sémantique ne peut pas en décider : mesuré sur les documents de serveur,
« crée un cube dans blender » sort à 0.897 et « scanne les paris de foot » à 0.905
— huit millièmes d'écart. Au niveau outil c'est pire, les distributions se croisent.
Un plancher de distance est donc impossible ; le signal qui reste est lexical.

Deux soustractions le rendent utilisable, et ce sont les seules :
  · un jeton présent dans PLUSIEURS hints ne distingue aucun serveur ;
  · un jeton qui figure déjà dans les descriptions des outils natifs n'est pas
    un signal MCP — « python », « export », « fichier » en sont.

Reste la collance, sans laquelle rien ne marche : sur les 8 usages MCP réels du
corpus, 5 sont des tours de suivi — « voici l'uid: d76a… », « Extrude le plus ».
Aucun ne nomme Blender. Le signal n'est pas dans la phrase, il est dans le fait
qu'on est déjà dans une conversation Blender.

Mesuré sur 184 tours réels : lié sur 6 % d'entre eux au lieu de 100 %, pour 5/8
des besoins servis. Les 3 restants sont rattrapables — ils sont au catalogue, et
un modèle qui y lit un nom l'appelle directement.
"""
from __future__ import annotations

import re
import unicodedata

JETONS_MINIMUM = 2

_LONGUEUR_MIN = 4

_RACINE = 5


def _plier(texte: str) -> str:
    decompose = unicodedata.normalize("NFD", texte.lower())
    return "".join(c for c in decompose if unicodedata.category(c) != "Mn")


def jetons(texte: str) -> set[str]:
    return set(re.findall(rf"[a-z0-9]{{{_LONGUEUR_MIN},}}", _plier(texte)))


def _vocabulaire_natif() -> set[str]:
    """Import tardif : `registry` tire tous les agents, dont certains touchent MCP."""
    try:
        from src.orchestrator.registry import build_all_tools
    except Exception:
        return set()
    return set().union(*(jetons(f"{o.name} {o.description or ''}")
                         for o in build_all_tools())) or set()


def signatures(hints: dict[str, str]) -> dict[str, set[str]]:
    """Les jetons qui identifient CHAQUE serveur, et lui seul.

    Le hint n'est pas la seule matière : les NOMS et descriptions des outils en
    portent autant, et souvent la plus utile — un serveur dont le hint parle de
    « diagnostic » expose `execute_snippet`, et « exécute ce bout de code » ne
    trouvait rien. Ce que le serveur sait faire est écrit dans ce qu'il expose.
    """
    bruts = {nom: jetons(hint) for nom, hint in hints.items()}
    if not bruts:
        return {}
    partages = {mot for mot in set().union(*bruts.values())
                if sum(mot in v for v in bruts.values()) > 1}
    natif = _vocabulaire_natif()

    # La soustraction du natif est BORNÉE. Elle sert à écarter le vocabulaire qui
    # ne signale rien — « python », « export », « fichier » sont dans le hint de
    # Blender, et sans elle le bruit passait de 6 à 20 %. Mais appliquée sans
    # limite, elle retire à l'utilisateur le contrôle de son propre hint : un hint
    # « diagnostic, exécution de code » se réduisait à un seul jeton, et régler ce
    # texte ne changeait plus rien — exactement le défaut que le routage MCP a déjà
    # corrigé une fois. Quand il ne reste pas de quoi discriminer, on garde le mot
    # de l'utilisateur plutôt que le silence.
    signatures_nettes = {}
    for nom, brut in bruts.items():
        propre = brut - partages
        elague = propre - natif
        signatures_nettes[nom] = elague if len(elague) >= JETONS_MINIMUM else propre
    return signatures_nettes


def _accords(mots: set[str], signature: set[str]) -> int:
    """Compte les jetons de la signature reconnus, au préfixe près.

    « clique » et « cliquer » sont le même signal ; sans ça, « ouvre le navigateur
    et clique sur le bouton » ne reconnaissait qu'un jeton et passait sous le seuil.
    """
    trouves = 0
    for reference in signature:
        racine = reference[:_RACINE]
        if any(mot.startswith(racine) or reference.startswith(mot[:_RACINE])
               for mot in mots):
            trouves += 1
    return trouves


def serveurs_pertinents(query: str, sigs: dict[str, set[str]],
                        actifs: set[str] = frozenset()) -> list[str]:
    """Nommé dans la requête, reconnu par sa signature, ou déjà en conversation."""
    mots = jetons(query)
    return [nom for nom, signature in sigs.items()
            if nom in actifs
            # Sans signature — `capabilities_hint` vide, ou entièrement composé de
            # termes que les outils natifs emploient déjà — la porte n'a RIEN sur
            # quoi juger. La refermer rendrait le serveur muet à jamais, ce qui est
            # pire que bruyant : une capacité dégradée vaut mieux qu'une capacité
            # absente. On laisse alors l'étage sémantique décider seul.
            or not signature
            or _plier(nom) in mots
            # Exiger deux jetons d'une signature qui n'en a qu'un rend le serveur
            # inéligible à jamais : le seuil ne peut pas dépasser la matière.
            or _accords(mots, signature) >= min(JETONS_MINIMUM, len(signature))]
