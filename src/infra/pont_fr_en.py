"""Pont lexical français → anglais pour le routage d'outils.

Les descriptions d'outils MCP viennent de leurs serveurs, en anglais ; les
requêtes d'AXON sont en français. `pont_linguistique` ajoute la traduction des
intentions présentes, sans remplacer la requête.

Consommé à TROIS endroits — `orchestrator/tool_retriever`, `mcp_client/registry`
et `agents/coding/tool_retriever`. Neutre par nécessité : `src/mcp_client/` ne
peut pas dépendre de `src/agents/`.

CE QU'IL APPORTE, MESURÉ PAR ABLATION. Le pont a longtemps porté la réputation de
« n'apporter presque rien » — une phrase de `skills/retriever.py`, qui parle de
l'index des SKILLS, où il n'est pas utilisé. Elle ne disait donc rien de ses
usages réels. Mesuré en le remplaçant par l'identité :

    étage 2 de l'orchestrateur   rappel réel 92/98 AVEC comme SANS,
    (98 requêtes réelles)        largeur identique — aucun apport ici,
                                 alors qu'il modifie 12 % des requêtes

    suites de routage            4 échecs réels sans lui :
    (91 tests)                     · 3 sur le routage MCP — vérification
                                     visuelle, lecture d'état de scène,
                                     requêtes d'interrogation
                                   · 1 sur l'orchestrateur — « envoie le
                                     recap dans le salon »

Il est donc porteur pour le MCP, dont les descriptions sont en anglais, et inerte
sur le routage natif où les documents de groupe sont déjà en français. C'est
exactement ce que son intention annonçait, et personne ne l'avait vérifié.

Pour rejouer : remplacer le corps de `pont_linguistique` par `return query`, puis

    pytest tests/test_mcp_routing_specialist.py tests/test_tool_routing.py \\
           tests/test_routing_generalization.py
    python outils/mesure_routage.py --outils
"""
from __future__ import annotations

import re
from functools import lru_cache


@lru_cache(maxsize=256)
def _motif(cle: str) -> re.Pattern[str]:
    return re.compile(rf"(?<!\w){re.escape(cle)}(?!\w)")


def _present(cle: str, texte: str) -> bool:
    """La clé apparaît-elle comme un MOT, et non comme une sous-chaîne ?

    La comparaison était `cle in texte`. Elle a tenu tant que les clés étaient
    choisies pour ne rien contenir d'autre — l'auteur énumérait d'ailleurs déjà
    « clique » ET « cliquer » plutôt que de compter sur le préfixe. Étendre le
    pont aux verbes d'action a exposé le défaut, mesuré sur quatre tournures
    ordinaires du dépôt lui-même :

        « une étape suivante »  → type text into   ("tape" ⊂ "étape")
        « renvoie la liste »    → submit send      ("envoie" ⊂ "renvoie")
        « le champion »         → field input      ("champ" ⊂ "champion")
        « invalider le cache »  → submit confirm   ("valider" ⊂ "invalider")

    `renvoie` et `étape` sont omniprésents dans les tâches françaises d'AXON :
    le pont aurait injecté du vocabulaire de formulaire dans des requêtes qui
    n'ont rien à voir, à l'étage même où l'on choisit les outils.
    """
    return bool(_motif(cle).search(texte))



#: Intentions de requête, français → anglais. Le pont existe pour une raison
#: MESURÉE : les descriptions d'outils MCP viennent de leurs serveurs, en
#: anglais, et les tâches de phase d'AXON sont en français.
#:
#: Sur sept requêtes de lecture d'état, la MÊME question donne :
#:
#:     français : 2/7        anglais : 7/7
#:
#: L'écart n'est pas uniforme : les verbes d'ACTION ont leur cognat
#: (execute/exécute, generate/génère, download/télécharge) et passent à 6/7,
#: tandis que les tournures INTERROGATIVES — « dis-moi », « où en est »,
#: « combien » — n'ont aucun voisin lexical dans une description anglaise.
#:
#: Ce sont donc des intentions qu'on traduit, jamais des noms d'outils : mettre
#: « blender » ou « scene_info » ici rendrait le pont dépendant des serveurs
#: installés, et il faudrait le rouvrir à chaque nouveau MCP.
PONT_FR_EN: dict[str, str] = {
    # Interroger
    "dis-moi": "get information about",
    "donne-moi": "get information about",
    "montre-moi": "show get list",
    "quel est": "get status",
    "quelle est": "get status",
    "quelles sont": "get list properties",
    "quels sont": "get list properties",
    "qu'est-ce que": "get information about",
    "combien": "how many count balance",
    "où en est": "check status poll progress",
    "est-ce que": "check whether",
    "vérifie": "check verify",
    "liste": "list",
    "contient": "contains information",
    "état": "status state",
    "statut": "status",
    "infos": "information details",
    "informations": "information details",
    "propriétés": "properties information",
    "reste": "remaining balance",
    # Agir — déjà bien couverts par les cognats, présents pour la symétrie
    "supprime": "delete remove",
    "téléverse": "upload",
    "enregistre": "save record",
    # Piloter un navigateur. Ces entrées ont l'air de vocabulaire de domaine, et
    # la règle ci-dessus l'interdit — mais ce sont des mots français ORDINAIRES
    # du web, pas des noms de serveurs ni d'outils : tout MCP de navigateur en
    # profite, aucun n'est nommé.
    #
    # Elles existent parce que rien d'autre n'a marché. Les outils Playwright se
    # décrivent en trois à cinq mots d'anglais (« Navigate to a URL »), donc
    # 0/4 en français contre 5-8/8 en anglais. Indexer le `capabilities_hint` du
    # serveur corrigeait bien ces 4 positifs, mais polluait 10 à 14 des 16
    # négatifs dans les TROIS formes essayées — document composite, découpé en
    # capacités, ou chaque capacité nommant « navigateur » (la pire : 9 ancres
    # quasi-identiques, l'erreur du commit 0c9a03b refaite).
    #
    # Aucun seuil ne triait, car les distributions se recouvraient :
    #     graines Playwright   positifs [1, 1, 2, 2]
    #                          négatifs [0, 0, 0, 1×9, 2, 2, 2, 3]
    # L'embedding ne sépare pas « regarder une page » de « écrire une page » en
    # français : « page », « formulaire », « rendu » appartiennent aux deux, et
    # seul le VERBE discrimine.
    #
    # Le pont réussit là où l'index échoue parce qu'il n'ajoute AUCUN document —
    # il ne peut donc pas inonder les 8 places — et parce qu'il ne se déclenche
    # que sur des mots que les négatifs n'emploient jamais. Mesuré : positifs
    # 3/4, négatifs 0/16.
    "navigateur": "browser page tab",
    "onglet": "browser tab",
    "clique": "click element",
    "cliquer": "click element",
    "console": "console messages log",
    "remplis": "fill form type",
    "s'affiche": "renders is displayed snapshot",
    "formulaire": "form",
    # Ajoutées quand le pont a été étendu à l'orchestrateur : les cinq requêtes
    # d'action qui échouaient encore n'avaient aucun de leurs verbes ici.
    "bouton": "button",
    "appuie": "press click",
    "saisis": "type text into",
    "saisir": "type text into",
    "tape": "type text into",
    "champ": "field input",
    "valider": "submit confirm",
    "envoie": "submit send",
    "panier": "cart add to basket",
    "sélectionne": "select option",
    "selectionne": "select option",
    "coche": "check checkbox click",
}


def pont_linguistique(query: str) -> str:
    """Ajoute la traduction anglaise des intentions présentes dans la requête.

    AJOUTE, ne remplace pas : la requête française reste en tête, et les termes
    anglais sont appendus. Traduire à la place perdrait les noms propres et le
    vocabulaire technique que le français porte déjà correctement (« blender »,
    « framer-motion », « GLB »).

    Déterministe et sans appel réseau — un pont qui dépendrait d'un modèle
    coûterait un appel par tour, pour un gain qu'un dictionnaire de vingt
    entrées obtient déjà.
    """
    bas = query.lower()
    ajouts = [en for fr, en in PONT_FR_EN.items() if _present(fr, bas)]
    if not ajouts:
        return query
    return f"{query} | {' '.join(dict.fromkeys(' '.join(ajouts).split()))}"
