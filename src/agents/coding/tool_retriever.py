"""Per-turn semantic tool selector for the coding specialist.

Instead of binding all 30+ tools to every LLM call, this retriever returns
only the tools relevant to the current step — always including the mandatory
workflow tools regardless of the query.
"""
from __future__ import annotations

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

    Le garde-fou vaut plus que le cas qui l'a motivé : il reste vrai quand
    `browser_screenshot` aura disparu, et il échoue au démarrage plutôt qu'en
    routage silencieux.
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
        # Une seule ancre, pas deux : « ajouter une dépendance au projet » a été
        # essayée et retirée. « au projet » est assez générique pour remonter sur
        # « explique-moi ce que fait cette fonction », qui passait alors de zéro
        # à cinq outils shell. Le gain d'une requête d'install ne payait pas cette
        # fuite.
        "installer une librairie ou un paquet par son nom",
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
    "browser_screenshot": [
        "vérifier le rendu visuel de l'application",
        "voir ce que donne le site dans le navigateur",
        "contrôler l'affichage de la page après le build",
        "vérifier que la page n'est pas blanche",
        "tester visuellement le résultat UI",
        "screenshot du dev server localhost",
    ],
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
_PONT_FR_EN: dict[str, str] = {
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
}


def _pont_linguistique(query: str) -> str:
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
    ajouts = [en for fr, en in _PONT_FR_EN.items() if fr in bas]
    if not ajouts:
        return query
    return f"{query} | {' '.join(dict.fromkeys(' '.join(ajouts).split()))}"


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
            self._store = Chroma.from_documents(docs, embeddings)
        except Exception:
            pass  # fallback to all tools

    def get(self, query: str) -> list:
        if self._store is None:
            return self._fallback

        # 1. Semantic retrieval
        results = self._store.as_retriever(
            search_kwargs={"k": self._k}
        ).invoke(_pont_linguistique(query))
        seed_names = {r.metadata["tool_name"] for r in results if "tool_name" in r.metadata}

        # 2. Group expansion
        selected: set[str] = set(_ALWAYS_INCLUDED)
        for name in seed_names:
            group = _TOOL_TO_GROUP.get(name)
            if group:
                selected.update(_TOOL_GROUPS[group])
                continue
            serveur, _, _ = name.partition("__")
            selected.update(self._serveurs_mcp.get(serveur, [name]))

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
