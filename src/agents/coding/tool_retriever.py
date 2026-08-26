"""Per-turn semantic tool selector for the coding specialist.

Instead of binding all 30+ tools to every LLM call, this retriever returns
only the tools relevant to the current step — always including the mandatory
workflow tools regardless of the query.
"""
from __future__ import annotations

from src.infra.pont_fr_en import pont_linguistique


from uuid import uuid4

from langchain_chroma import Chroma
from langchain_ollama import OllamaEmbeddings
from langchain_core.documents import Document
from langchain_core.messages import AIMessage

# ── Always in every turn — mandatory workflow tools ────────────────────────────
_ALWAYS_INCLUDED = frozenset({
    "dev_plan_create",
    "dev_plan_update",
    "dev_plan_step_done",
    "dev_explain",
    "ask_clarification",
    "propose_file_change",
    "edit_file",
    "load_skill",
})

# ── Group expansion ────────────────────────────────────────────────────────────
# If any tool in a group is retrieved, the whole group is included.
# Rationale: you never want git_status without git_add, or shell_run without shell_cd.
_TOOL_GROUPS: dict[str, list[str]] = {
    "filesystem": [
        "find_git_repos",
        "local_find_file", "local_list_directory", "local_glob",
        "local_read_file", "local_grep",
        "url_fetch",
    ],
    # `browser_screenshot` a été retiré d'ici. Le motif invoqué — la vérification
    # visuelle est couplée au shell, on lance le dev server puis on regarde — dit
    # la dépendance dans le MAUVAIS SENS, et la mesure l'a montré.
    #
    # Il n'arrivait pas en passager d'une tâche de build : il était la GRAINE. Ses
    # ancres françaises (« voir ce que donne le site ») sont si front-end qu'il
    # remontait sur « crée la page d'accueil » et « corrige l'erreur de typage
    # dans page.tsx », deux tâches sans aucun shell, et il traînait les cinq
    # outils du groupe derrière lui. Sur « installe framer-motion », qui a pourtant
    # un vrai besoin de shell, celui-ci arrivait quand même par accident.
    #
    # Un outil ne rejoint donc ce groupe que s'il EST une commande shell, pas
    # parce qu'on l'emploie souvent après une commande shell.
    "shell": [
        "shell_run", "shell_cd", "shell_pwd", "shell_ls", "shell_kill_bg",
    ],
    "git": [
        "git_status", "git_log", "git_diff", "git_suggest_commit",
        "git_add", "git_commit", "git_checkout", "git_stash",
    ],
    "web": [
        "web_research_report", "web_search_news",
    ],
    "memory": [
        "axon_note",
    ],
    # « visual » regroupait trois outils qui ne partageaient que de produire une
    # image. Rien ne justifie de tirer un diagramme parce qu'on télécharge un asset.
    "diagrams": [
        "mermaid_diagram",
    ],
    "assets": [
        "download_asset",
    ],
    "notebook": [
        "notebook_read", "notebook_edit_cell",
        "notebook_insert_cell", "notebook_run",
    ],
}

def _index_inverse(groupes: dict[str, list[str]]) -> dict[str, str]:
    """L'index outil → groupe, en refusant qu'un outil appartienne à deux groupes.

    Sans ce refus, la compréhension équivalente garde le DERNIER groupe vu et
    perd l'autre sans rien dire. Ce n'est pas une précaution théorique : c'est
    arrivé à `browser_screenshot`, déclaré à la fois dans « shell » et dans un
    groupe « visual », qui tirait donc mermaid et download_asset au lieu du
    shell. Le bug était invisible parce que le mauvais résultat était un
    résultat valide — un groupe existant, simplement pas celui qu'on croyait.

    Le garde-fou vaut plus que le cas qui l'a motivé : `browser_screenshot` a
    depuis été supprimé, et la règle tient toujours pour les cinq commandes shell
    qui lui survivent. Il échoue au démarrage plutôt qu'en routage silencieux.
    """
    index: dict[str, str] = {}
    for groupe, outils in groupes.items():
        for outil in outils:
            if (deja := index.get(outil)) and deja != groupe:
                raise ValueError(
                    f"« {outil} » est déclaré dans « {deja} » ET « {groupe} » : "
                    "l'index inverse en perdrait un silencieusement. "
                    "Un outil appartient à un seul groupe."
                )
            index[outil] = groupe
    return index


_TOOL_TO_GROUP: dict[str, str] = _index_inverse(_TOOL_GROUPS)

# ── Semantic anchors ───────────────────────────────────────────────────────────
# Extra indexing phrases for tools whose description isn't enough to match
# natural-language queries reliably.
_TOOL_ANCHORS: dict[str, list[str]] = {
    "find_git_repos": [
        "trouver le projet local sur le disque",
        "identifier quel repo modifier",
        "localiser le dossier du projet git",
        "scanner les repos disponibles",
    ],
    "shell_run": [
        "exécuter une commande bash ou shell",
        "lancer le serveur de développement",
        "installer les dépendances npm pip cargo pnpm",
        # Sans ces deux-là, `shell_run` sort 1er sur « installe les dépendances »,
        # « installe framer-motion avec pnpm » et « lance npm install », mais est
        # ABSENT de « installe framer-motion » et « ajoute la librairie
        # framer-motion au projet » : l'ancre ci-dessus exige un mot d'écosystème,
        # et l'embedding ne sait pas que framer-motion est un paquet npm.
        #
        # Le trou existait avant, masqué : `browser_screenshot` était alors dans
        # le groupe shell et l'y tirait par accident. Le retirer a découvert un
        # agent à qui l'on demande d'installer une lib sans lui donner de shell.
        "installer une librairie ou un paquet par son nom",
        # Ces deux-là ont d'abord été REJETÉES, sur un jeu de quatre négatifs :
        # « ajouter une dépendance au projet » faisait remonter le shell sur
        # « explique-moi ce que fait cette fonction », et le gain d'une requête
        # d'install ne semblait pas payer cette fuite.
        #
        # Mesuré plus largement — 120 requêtes bâties sur les dépendances RÉELLES
        # du dépôt croisées avec cinq gabarits, contre 15 négatifs de lecture,
        # d'écriture et de note — le verdict s'inverse :
        #
        #     sans elles ....  101/120 paquets ont un shell   5/15 négatifs, 22 outils
        #     avec elles ....  114/120                        8/15 négatifs, 23 outils
        #
        # Treize tâches de plus peuvent lancer une commande, pour trois négatifs
        # de plus et UN outil de plus en moyenne. L'asymétrie décide : sans shell,
        # « retire langchain des dépendances » est une tâche bloquée — l'agent
        # éditerait requirements.txt sans jamais désinstaller ; avec un shell en
        # trop, « explique-moi cette fonction » reçoit un outil qu'il ignore.
        #
        # Le premier jeu était trop petit pour voir ça, et son verdict tenait à
        # une seule requête.
        "ajouter ou retirer une dépendance du projet",
        "configurer un outil ou une librairie installée",
        "builder le projet tsc next build",
        "lancer les tests jest pytest",
        "compiler le code",
        "créer un dossier ou initialiser git",
        "démarrer l'application en arrière-plan",
    ],
    "local_read_file": [
        "lire le contenu d'un fichier source",
        "voir le code d'un fichier",
        "analyser le fichier existant",
        "consulter le contenu de",
        "ouvrir le fichier pour comprendre",
    ],
    "local_grep": [
        "chercher du texte dans les fichiers du projet",
        "trouver où est définie une fonction ou variable",
        "rechercher dans le code source",
        "trouver toutes les occurrences de",
    ],
    # Les six ancres de `browser_screenshot` ont été SUPPRIMÉES avec lui, et
    # délibérément pas transférées à Playwright — c'est le geste évident, et il
    # est mesuré comme faux.
    #
    # Elles sont françaises, courtes, mono-intention : tout ce qui devrait bien
    # router. Mais ce sont exactement celles dont la mesure a montré la fuite —
    # « voir ce que donne le site dans le navigateur » sortait PREMIÈRE sur
    # « crée la page d'accueil du site », et « contrôler l'affichage de la page
    # après le build » sur « installe framer-motion ». Les recoller sur un outil
    # Playwright rejouerait cette fuite, désormais multipliée par 24 par
    # l'expansion de serveur.
    #
    # Ce qui route le navigateur est le pont lexical, pas des ancres françaises.

    "notebook_read": [
        "lire un notebook jupyter ipynb",
        "voir les cellules du notebook",
        "analyser le contenu d'un fichier ipynb",
        "notebook python data science",
    ],
    "notebook_edit_cell": [
        "modifier une cellule du notebook",
        "éditer le code d'une cellule",
        "compléter le TODO dans le notebook",
        "écrire du code dans une cellule jupyter",
    ],
    "web_research_report": [
        "chercher dans la documentation officielle",
        "trouver comment utiliser une API ou librairie",
        "quelle est la bonne syntaxe pour",
        "trouver un exemple de code en ligne",
        "vérifier la doc avant d'implémenter",
    ],
    "axon_note": [
        "mémoriser une information sur ce projet",
        "noter pour les prochaines sessions",
        "sauvegarder dans la mémoire projet axon",
        "mettre à jour AXON.md",
    ],
    "mermaid_diagram": [
        "générer un diagramme de l'architecture",
        "schéma de flux ou de séquence",
        "représenter visuellement le système",
        "créer un diagramme entité-relation",
    ],
    "git_add": [
        "committer les changements git",
        "sauvegarder dans l'historique git",
        "créer un commit avec les fichiers modifiés",
        "git add et git commit",
    ],
    "download_asset": [
        "télécharger une image ou une ressource",
        "récupérer un asset pour le projet",
        "image pour la page d'accueil ou le hero",
        "fichier GLB ou modèle 3D à télécharger",
    ],
}


#: Au-delà de cette distance, une graine MCP est écartée : le voisin le plus
#: proche est si loin que la requête n'a rien matché du tout, et l'expansion de
#: serveur ferait de ce bruit vingt-cinq outils.
#:
#: Le seuil existe parce que le TOKEN n'était pas la cause. « installe
#: framer-motion » remontait les huit outils du serveur Motion — collision
#: apparente sur « motion » — puis, Motion retiré, les vingt-cinq de Blender. Une
#: requête courte nommant un nom propre inconnu n'a aucun bon voisin natif, et le
#: serveur MCP le plus proche remplit les huit places, quel qu'il soit.
#:
#: Mesuré sur les jeux de labels de tests/test_mcp_routing_specialist.py, en
#: distance de la MEILLEURE graine MCP :
#:
#:     légitimes (MCP attendu) ...  11 requêtes,  0.548 → 0.765
#:     parasites (aucun MCP) .....  18 requêtes,  une seule en a une : 0.960
#:
#: Aucun chevauchement, 0.195 d'écart. C'est le discriminant que le COMPTAGE de
#: graines ne donnait pas — il se recouvrait entièrement — parce que le nombre dit
#: combien de documents ont matché, la distance dit si l'un d'eux a vraiment
#: matché.
#:
#: Le seuil ne s'applique qu'aux outils MCP. Les natifs sont le repli : les
#: écarter pourrait ne rien laisser, alors qu'une graine MCP écartée coûte au pire
#: un serveur non proposé, avec `tool_map` qui le garde appelable.
#:
#: Il dépend de l'embedder (`nomic-embed-text`) et de la distance de Chroma. En
#: changer invaliderait ces nombres, d'où un test qui REMESURE la marge au lieu de
#: figer la valeur — il tombe si le classement se déplace.
_DISTANCE_MAX_MCP = 0.85

#: Dépendances ORIENTÉES : serveur MCP → groupe natif dont il a besoin.
#:
#: À ne pas confondre avec l'appartenance à un groupe, qui est symétrique et dont
#: le mauvais usage a coûté un commit entier. `browser_screenshot` avait été mis
#: DANS le groupe `shell` au motif qu'on lance le dev server avant de regarder la
#: page ; il y devenait la graine et polluait des tâches d'écriture qui n'avaient
#: rien à voir. Le motif était juste, le moyen faux.
#:
#: Ici le sens compte : piloter un navigateur sur une page servie localement exige
#: de pouvoir la SERVIR, tandis que lancer une commande shell n'exige aucun
#: navigateur. Mesuré avant :
#:
#:     « vérifie que la page d'accueil s'affiche dans le navigateur »
#:           → 24 outils Playwright, shell_run ABSENT
#:
#: L'inverse n'est délibérément PAS déclaré. Un `shell` → `playwright` ramènerait
#: le navigateur sur chaque build, install et lancement de tests : c'est
#: exactement la fuite mesurée à 13 négatifs sur 16.
#:
#: Conséquence assumée : une requête composite comme « démarre le serveur de
#: développement puis vérifie la page dans le navigateur » n'obtient que la moitié
#: shell, les huit places étant prises par le vocabulaire de commande. Elle se
#: résout au tour suivant, quand la requête ne porte plus que la vérification.
_DEPENDANCES_MCP: dict[str, str] = {
    "playwright": "shell",
}


def _groupes_mcp(tools: list) -> dict[str, list[str]]:
    """Un groupe par serveur MCP, d'après le préfixe `serveur__outil`.

    Même raison que les groupes natifs — on ne veut jamais `git_status` sans
    `git_add` — et elle est plus forte encore ici. Router correctement ne suffit
    pas : le pont lexical amenait UN outil par requête de navigateur, par exemple
    `browser_navigate` sans `browser_snapshot`. Naviguer sans pouvoir regarder ne
    vérifie rien.

    Le groupe n'était pas sûr avant le pont : il multipliait par 24 la moindre
    graine parasite, et les négatifs en avaient sur 13 requêtes sur 16. Il l'est
    maintenant qu'ils sont à zéro — l'amplification n'a plus rien à amplifier.
    C'est cet ordre qui compte, pas les deux mécanismes pris ensemble.
    """
    groupes: dict[str, list[str]] = {}
    for t in tools:
        serveur, _, _ = t.name.partition("__")
        if _:
            groupes.setdefault(serveur, []).append(t.name)
    return groupes


class CodingToolRetriever:
    """Semantic tool selector initialised once per _run() call.

    Each turn, .get(query) returns the tools most relevant to the current
    step plus the mandatory workflow tools — typically 10-18 tools instead
    of all 30+.

    Falls back gracefully to all tools if the embedding model is unavailable.
    """

    def __init__(self, tools: list, k: int = 6):
        self._tools_by_name = {t.name: t for t in tools}
        self._fallback = list(tools)
        self._store = None
        self._k = k
        self._serveurs_mcp = _groupes_mcp(tools)

        try:
            embeddings = OllamaEmbeddings(model="nomic-embed-text")
            docs: list[Document] = []
            for t in tools:
                docs.append(Document(
                    page_content=f"{t.name}: {t.description}",
                    metadata={"tool_name": t.name},
                ))
                for anchor in _TOOL_ANCHORS.get(t.name, []):
                    docs.append(Document(
                        page_content=anchor,
                        metadata={"tool_name": t.name},
                    ))
            # Une collection PROPRE à cette instance. Sans `collection_name`,
            # `from_documents` écrit dans la collection « langchain » par défaut,
            # partagée par tout le processus : chaque construction AJOUTAIT ses
            # documents aux précédents. Mesuré, 138 → 276 → 414 → 552.
            #
            # Ce n'est pas théorique. `specialist.py` garde le retriever en cache
            # mais le reconstruit dès que l'ensemble d'outils change — un serveur
            # MCP qui tombe ou revient suffit. Les doublons mangent alors le
            # budget des k=8 places, et la sélection perd en largeur ce qu'elle
            # gagne en redondance :
            #
            #     138 docs   navigateur 4/5   blender 6/6   état 5/5   22 outils
            #     276 docs   navigateur 3/5   blender 5/6   état 4/5   16 outils
            #
            # Aucun test ne pouvait le voir : chacun ne construit qu'un retriever.
            self._store = Chroma.from_documents(
                docs, embeddings,
                collection_name=f"axon_outils_{uuid4().hex[:12]}",
            )
        except Exception:
            pass  # fallback to all tools

    def get(self, query: str) -> list:
        if self._store is None:
            return self._fallback

        # 1. Semantic retrieval — avec les distances, pour pouvoir écarter une
        #    graine MCP qui n'a en réalité rien matché (cf. _DISTANCE_MAX_MCP).
        resultats = self._store.similarity_search_with_score(
            pont_linguistique(query), k=self._k)
        seed_names = {
            doc.metadata["tool_name"]
            for doc, distance in resultats
            if "tool_name" in doc.metadata
            and (distance <= _DISTANCE_MAX_MCP or "__" not in doc.metadata["tool_name"])
        }

        # 2. Group expansion
        selected: set[str] = set(_ALWAYS_INCLUDED)
        for name in seed_names:
            group = _TOOL_TO_GROUP.get(name)
            if group:
                selected.update(_TOOL_GROUPS[group])
                continue
            serveur, _, _ = name.partition("__")
            selected.update(self._serveurs_mcp.get(serveur, [name]))
            if (requis := _DEPENDANCES_MCP.get(serveur)):
                selected.update(_TOOL_GROUPS[requis])

        # 3. Return in original order, only tools we have
        return [t for name, t in self._tools_by_name.items() if name in selected]


def retrieval_query(messages: list, task: str) -> str:
    """Build a retrieval query from the last AI message in the conversation.

    On the first turn (no AI message yet) falls back to the task text,
    which seeds the retriever with what the task is about.
    """
    for msg in reversed(messages):
        if not isinstance(msg, AIMessage):
            continue
        parts: list[str] = []
        if isinstance(msg.content, str) and msg.content.strip():
            parts.append(msg.content[:300])
        for tc in (getattr(msg, "tool_calls", None) or []):
            parts.append(tc.get("name", "").replace("_", " "))
            for key in ("command", "path", "task", "stack", "message", "query"):
                val = (tc.get("args") or {}).get(key, "")
                if isinstance(val, str) and val:
                    parts.append(val[:100])
        if parts:
            return " ".join(parts)[:500]

    return task[:400]
