# src/orchestrator/tool_retriever.py
from langchain_community.vectorstores import Chroma
from langchain_ollama import OllamaEmbeddings
from langchain_core.documents import Document

# ── Groupes de tools ──────────────────────────────────────────
TOOL_GROUPS: dict[str, list[str]] = {
    "coding": [
        "run_coding_agent",
    ],
    "git": [
        "git_status", "git_log", "git_diff", "git_suggest_commit",
        "git_add", "git_commit", "git_checkout", "git_stash",
        "url_fetch",
    ],
    "filesystem": [
        "local_find_file", "local_read_file", "local_list_directory",
        "local_grep", "local_glob",
    ],
    "shell": [
        "shell_run", "shell_cd", "shell_pwd", "shell_ls",
        "notify", "clipboard_read", "clipboard_write",
    ],
    "system": [
        "screenshot_take", "process_list", "process_kill", "wifi_info",
    ],
    "gmail": [
        "gmail_search", "gmail_summarize", "gmail_send_email",
        "gmail_edit_draft", "gmail_confirm_send",
    ],
    "calendar": [
        "calendar_list_events", "calendar_create_event", "calendar_update_event",
        "calendar_delete_event", "calendar_list_calendars", "calendar_search_events",
    ],
    "drive": [
        "drive_list_files", "drive_find_file_id", "drive_read_file",
        "drive_delete_file", "drive_get_file_metadata",
    ],
    "docs": [
        "google_docs_create", "google_docs_update", "google_docs_read",
    ],
    "slides": [
        "create_presentation", "add_slide",
    ],
    "slack": [
        "slack_find_user", "slack_list_channels", "slack_read_channel",
        "slack_get_mentions", "slack_list_dms", "slack_send_message",
        "slack_search_messages",
    ],
    "jira": [
        "jira_get_my_issues", "jira_get_issue", "jira_search_issues",
        "jira_get_project_summary", "jira_get_sprint_issues",
        "jira_list_projects", "jira_add_comment", "jira_transition_issue",
        "jira_get_workload", "jira_create_issue", "jira_create_issues_bulk",
        "jira_assign_issue", "jira_update_issue", "jira_get_issue_comments",
        "jira_search_users", "jira_move_issue", "jira_delete_issue", "jira_link_to_epic",
    ],
    "search": [
        "web_research_report",
        "web_search_news",
    ],
    "arxiv": [
        "arxiv_search", "arxiv_get_paper",
    ],
    "time": [
        "get_current_time",
    ],
    "weather": [
        "get_weather_by_city",
    ],
    "diagrams": [
        "excalidraw_create",
    ],
    "memory": [
        "axon_note",
    ],
}

# Index inverse : tool_name → group_name
_TOOL_TO_GROUP: dict[str, str] = {
    tool: group
    for group, tools in TOOL_GROUPS.items()
    for tool in tools
}

# Tools toujours inclus
_ALWAYS_INCLUDED = {"get_current_time"}

# ── Multi-vector anchors ───────────────────────────────────────
# Pour les méta-outils dont la description parle de "déléguer" plutôt
# que du travail concret, on indexe N phrases sémantiques supplémentaires
# couvrant les différentes façons dont un utilisateur peut formuler sa demande.
# Chaque anchor est un document séparé dans Chroma → N chances d'être trouvé.
_TOOL_ANCHORS: dict[str, list[str]] = {
    "run_coding_agent": [
        # ── Modifications & corrections ───────────────────────
        "modifier du code dans un projet local",
        "corriger un bug dans mon application",
        "corriger une erreur ou un comportement inattendu",
        "fixer un problème dans mon code",
        "déboguer un crash ou une exception",
        "trouver pourquoi mon code ne fonctionne pas",
        "réparer une régression introduite récemment",
        "résoudre un conflit de dépendances dans le projet",

        # ── Nouvelles fonctionnalités ─────────────────────────
        "ajouter une nouvelle fonctionnalité à un projet",
        "implémenter une nouvelle route dans mon API",
        "créer un nouveau composant, fichier ou page",
        "ajouter un bouton, un formulaire ou un élément UI",
        "intégrer une librairie externe dans le projet",
        "brancher une API tierce dans mon application",
        "mettre en place un système d'authentification",
        "ajouter des tests unitaires ou d'intégration",
        "écrire des tests pour couvrir mon code",

        # ── Refactoring & architecture ────────────────────────
        "refactoriser un module, une classe ou une fonction",
        "réorganiser la structure des fichiers du projet",
        "découper un fichier trop long en plusieurs modules",
        "renommer des variables, fonctions ou fichiers",
        "supprimer du code mort ou des imports inutilisés",
        "migrer vers une nouvelle version d'un framework",
        "convertir du code JavaScript en TypeScript",
        "remplacer une dépendance obsolète par une alternative",

        # ── UI / Frontend ─────────────────────────────────────
        "refaire l'interface utilisateur d'une application web",
        "améliorer le design ou le style d'un projet",
        "rendre l'application responsive ou mobile-friendly",
        "changer le thème, les couleurs ou la typographie",
        "corriger un problème d'affichage ou de layout",
        "animer un composant ou ajouter des transitions",
        "améliorer l'accessibilité de l'interface",

        # ── Analyse & compréhension ───────────────────────────
        "expliquer comment fonctionne le code d'un repo",
        "analyser la structure du code et proposer des améliorations",
        "faire un code review d'un projet et dire ce qui peut être amélioré",
        "lire les fichiers du projet et résumer l'architecture",
        "identifier les parties les plus complexes du code",
        "comprendre ce que fait un fichier ou une fonction",
        "documenter le code avec des commentaires ou un README",
        "générer la documentation d'une fonction ou d'une classe",

        # ── Performance & qualité ─────────────────────────────
        "optimiser les performances d'un projet existant",
        "réduire le temps de chargement ou la consommation mémoire",
        "identifier et corriger des fuites mémoire",
        "améliorer la sécurité du code",
        "mettre en place du linting ou du formatage automatique",
        "configurer ESLint, Prettier, Black ou un autre linter",
        "améliorer le score Lighthouse d'une application web",

        # ── DevOps / config ───────────────────────────────────
        "modifier la configuration du projet",
        "mettre à jour le fichier de configuration webpack, vite ou autre",
        "configurer les variables d'environnement",
        "créer ou modifier un Dockerfile ou docker-compose",
        "mettre en place une CI/CD pipeline",
        "configurer les scripts npm, yarn ou makefile",
        "initialiser un nouveau projet from scratch",

        # ── Navigation dans le repo ───────────────────────────
        "aller dans mon repo et faire des changements",
        "lire et modifier les fichiers d'un projet",
        "parcourir les fichiers d'un dossier et m'en expliquer le contenu",
        "chercher où est définie une fonction ou une classe dans le projet",
        "trouver tous les endroits où une variable est utilisée",
        "lister les dépendances du projet",
    ],

    "jira_get_my_issues": [
        "quels tickets jira me sont assignés",
        "voir mes tâches jira",
        "ce que j'ai à faire sur jira",
        "mon backlog jira",
        "mes issues en cours",
        "tickets assignés à moi",
        "qu'est-ce que j'ai à faire cette semaine sur jira",
    ],
    "jira_get_project_summary": [
        "avancement du projet sur jira",
        "état d'un projet jira",
        "progression du projet",
        "combien de tickets sont terminés dans le projet",
        "résumé du projet jira",
        "bilan du projet en cours",
        "vue d'ensemble du projet",
    ],
    "jira_get_sprint_issues": [
        "tickets du sprint actif",
        "ce qui est dans le sprint courant",
        "sprint en cours sur jira",
        "tâches du sprint actuel",
        "tickets en cours dans le sprint",
    ],
    "jira_get_workload": [
        "qui fait quoi dans l'équipe",
        "charge de travail par développeur",
        "répartition des tickets dans l'équipe",
        "qui a le plus de tickets assignés",
        "workload de l'équipe sur jira",
    ],
    "jira_transition_issue": [
        "marquer un ticket jira comme terminé",
        "passer un ticket en cours",
        "changer le statut d'un ticket jira",
        "fermer un ticket jira",
        "mettre un ticket en done",
    ],
    "jira_create_issue": [
        "créer un ticket jira",
        "ouvrir une nouvelle tâche sur jira",
        "ajouter un ticket dans le projet",
        "créer un bug, une story ou une tâche jira",
        "nouveau ticket jira",
        "ajoute ce ticket dans mon projet jira",
        "mets ça dans jira",
    ],
    "jira_create_issues_bulk": [
        "créer plusieurs tickets jira en une fois",
        "importer une liste de tickets dans jira",
        "ajouter plusieurs user stories dans le projet",
        "mettre en place le backlog jira",
        "créer tous ces tickets dans mon projet",
        "mets moi tous ces tickets dans jira",
        "importer des tâches en masse dans jira",
        "créer un backlog complet dans jira",
    ],
    "excalidraw_create": [
        "schématise moi quelque chose",
        "fais moi un schéma de ce concept",
        "crée un diagramme de l'architecture",
        "dessine un flowchart",
        "génère un diagramme de flux",
        "représente visuellement ce système",
        "fais un mind map",
        "crée un schéma d'architecture",
        "représente l'architecture en schéma",
        "diagramme de séquence",
        "schéma de la base de données",
        "visualise le pipeline",
        "dessine le flux de données",
        "fais un organigramme",
        "schéma de l'infrastructure",
        "diagramme de composants",
        "représentation visuelle de ce processus",
        "fais un diagramme entité-relation",
        "illustre comment fonctionne ce système",
        "montre moi l'architecture en schéma",
        "fais un schéma du RAG",
        "schématise le fonctionnement",
        "dessine moi ça",
        "crée un visuel pour expliquer",
        "diagram this architecture",
        "draw a flowchart",
    ],
    "web_search_news": [
        # ── Événements récents ────────────────────────────────────
        "qu'est-ce qui s'est passé aujourd'hui",
        "actualité du jour",
        "dernières nouvelles sur un sujet",
        "news récentes",
        "événements de cette semaine",
        "ce qui s'est passé hier",
        "quoi de neuf sur ce sujet",
        "dernières infos",
        # ── Sport ─────────────────────────────────────────────────
        "résultats des matchs hier",
        "score du match de foot",
        "résultat sportif récent",
        "qui a gagné le match",
        "classement actuel",
        "résultats championnat",
        # ── Tech & business ───────────────────────────────────────
        "dernière annonce d'une entreprise",
        "news sur Apple Google Microsoft OpenAI",
        "sortie d'un nouveau produit",
        "mise à jour récente d'une application",
        "levée de fonds annoncée",
        # ── Politique & monde ─────────────────────────────────────
        "actualité politique récente",
        "élections résultats",
        "discours d'un dirigeant",
        "crise ou conflit en cours",
        "décision gouvernementale récente",
    ],
}


class ToolRetriever:
    def __init__(self, tools: list, k: int = 7):
        """
        k : nombre de documents récupérés par similarité.
        Les méta-outils sont indexés avec plusieurs vecteurs sémantiques
        (multi-vector anchors) pour améliorer leur rappel sans les forcer.
        """
        embeddings = OllamaEmbeddings(model="nomic-embed-text")

        docs = []
        for t in tools:
            # Document principal
            docs.append(Document(
                page_content=f"{t.name}: {t.description}",
                metadata={"tool_name": t.name},
            ))
            # Ancres sémantiques supplémentaires (un doc par intention)
            for anchor in _TOOL_ANCHORS.get(t.name, []):
                docs.append(Document(
                    page_content=anchor,
                    metadata={"tool_name": t.name},
                ))

        self._tools = tools
        self._store = Chroma.from_documents(docs, embeddings)
        self._k = k

    def get(self, query: str) -> list:
        # 1. Récupère les k documents les plus similaires (dédupliqués par tool_name)
        results = self._store.as_retriever(search_kwargs={"k": self._k}).invoke(query)
        seed_names = {r.metadata["tool_name"] for r in results}

        # 2. Étend aux groupes complets
        groups_needed: set[str] = set()
        for name in seed_names:
            group = _TOOL_TO_GROUP.get(name)
            if group:
                groups_needed.add(group)

        # 3. Construit la liste finale
        selected_names: set[str] = set(_ALWAYS_INCLUDED)
        for group in groups_needed:
            selected_names.update(TOOL_GROUPS[group])

        # 4. Si coding détecté → retirer git/filesystem de l'orchestrateur
        #    Le specialist gère lui-même les fichiers et git.
        #    Shell (shell_run, etc.) reste disponible pour les tâches système
        #    pures (audit disque, monitoring…) qui ne nécessitent pas le specialist.
        if "coding" in groups_needed:
            for group in ("git", "filesystem"):
                for tool_name in TOOL_GROUPS.get(group, []):
                    selected_names.discard(tool_name)

        # 5. Retourner les objets tools dans l'ordre original
        return [t for t in self._tools if t.name in selected_names]
