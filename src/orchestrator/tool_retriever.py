# src/orchestrator/tool_retriever.py
"""Routing à deux étages : la requête élit des GROUPES, les groupes livrent leurs
outils.

L'étage 1 score la requête contre un document par groupe, jamais contre les
outils eux-mêmes. C'est ce qui rend la sélection insensible au nombre de
documents qu'un outil possède : l'ancien index mélangeait 90 descriptions et 298
phrases d'ancrage, si bien qu'un outil à 74 ancres occupait 19 % de l'espace de
recherche et remontait sur des requêtes qui ne le concernaient pas — mesuré sur
10 des 20 requêtes non-coding d'un jeu de référence. Le nombre d'ancres était
devenu un multiplicateur de probabilité d'être choisi, indépendamment de la
pertinence.

Même forme que le routing MCP (`src/mcp_client/registry.py`) : document de
contenant, puis contenu filtré. Les primitives communes sont dans
`src/infra/retrieval.py`.
"""
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from langchain_chroma import Chroma
from langchain_ollama import OllamaEmbeddings
from langchain_core.documents import Document

from src.infra.retrieval import build_catalog_document, unique


@dataclass(frozen=True)
class ToolGroup:
    """`covers` est le document de l'étage 1 : c'est LUI qui décide si le groupe
    est élu, pas les descriptions des outils. Un groupe mal décrit est un groupe
    injoignable — d'où le corpus de non-régression de tests/test_tool_routing.py.

    `extend` sert aux groupes dont le domaine n'est pas connu à l'écriture : les
    skills déclarent eux-mêmes ce qu'ils couvrent, la description les interroge
    au lieu de les recopier.
    """
    covers: str
    tools: tuple[str, ...]
    extend: Callable[[], list[str]] | None = field(default=None, compare=False)
    # Termes qui DÉSIGNENT ce groupe sans ambiguïté — noms de produits, pas de
    # vocabulaire courant. Leur présence littérale dans la requête élit le groupe
    # quel que soit son rang vectoriel. Mesuré : « envoie ça à Nicolas sur Slack »
    # classait `slack` 17e sur 22, derrière `news` et `quant`, alors que la
    # description commence par le mot « Slack ». L'embedder dilue un terme rare
    # dans une phrase courte et banale ; la correspondance exacte, elle, ne le
    # rate jamais. Un terme ambigu ici ferait élire un groupe à tort : n'y mettre
    # que ce qui ne désigne rien d'autre.
    keywords: frozenset[str] = frozenset()

    def document(self, name: str, *, max_chars: int = 2000) -> str:
        covers = self.covers
        if self.extend:
            extra = ", ".join(self.extend())
            if extra:
                covers = f"{covers} Domaines disponibles : {extra}."
        return build_catalog_document(
            {"Groupe": name, "Couvre": covers}, "Outils", self.tools, max_chars=max_chars
        )


_WORD = re.compile(r"[\w-]+", re.UNICODE)


def _keyword_groups(query: str) -> list[str]:
    """Groupes NOMMÉS littéralement dans la requête, dans l'ordre de déclaration.

    Comparaison sur des mots entiers, jamais sur des sous-chaînes : « paris » ne
    doit pas être trouvé dans « comparaison », et « ip » pas dans « équipe »."""
    mots = {m.group(0).lower() for m in _WORD.finditer(query)}
    return [g for g, spec in TOOL_GROUPS.items() if spec.keywords & mots]


def _skill_topics() -> list[str]:
    """Les skills visibles par l'orchestrateur décrivent eux-mêmes leur domaine."""
    try:
        from src.skills.tools import anchors_for
        return anchors_for("orchestrator")
    except Exception:
        return []


# ── Groupes de tools ──────────────────────────────────────────
TOOL_GROUPS: dict[str, ToolGroup] = {
    "coding": ToolGroup(
        covers="Déléguer un travail de développement sur un projet de code à un agent "
               "spécialisé qui écrit les fichiers lui-même. Corriger un bug, déboguer un "
               "crash, ajouter une fonctionnalité, une route d'API, un composant ou une "
               "page, refactoriser un module, migrer un framework, écrire des tests, "
               "configurer le build ou le linting. Aussi : créer une application ou un "
               "site web à partir de rien — landing page, site vitrine, page d'accueil, "
               "projet Next.js, React, Vue ou Svelte. Le livrable est du code source "
               "sur le disque.",
        tools=("run_coding_agent",),
    ),
    "git": ToolGroup(
        covers="Dépôt git : voir les fichiers modifiés et l'état de la copie de travail, "
               "lire l'historique des commits, comparer les différences, ajouter des "
               "fichiers à l'index, committer, changer de branche, remiser.",
        tools=("git_status", "git_log", "git_diff", "git_suggest_commit",
               "git_add", "git_commit", "git_checkout", "git_stash"),
        keywords=frozenset({"git", "commit", "commits", "branche", "branch"}),
    ),
    "filesystem": ToolGroup(
        covers="Fichiers locaux du disque : retrouver un fichier par son nom ou un motif, "
               "lister le contenu d'un dossier, lire le contenu d'un fichier, chercher un "
               "texte ou une définition à l'intérieur des fichiers.",
        tools=("local_find_file", "local_read_file", "local_list_directory",
               "local_grep", "local_glob"),
    ),
    "shell": ToolGroup(
        covers="Terminal de la machine : exécuter une commande ou un script, lancer un "
               "build, une installation de dépendances ou une suite de tests, naviguer "
               "entre les dossiers, savoir où l'on se trouve, lister rapidement un "
               "répertoire.",
        tools=("shell_run", "shell_cd", "shell_pwd", "shell_ls"),
        keywords=frozenset({"terminal", "shell", "bash", "commande"}),
    ),
    "desktop": ToolGroup(
        covers="Bureau graphique : capturer l'écran pour voir ou analyser ce qui y est "
               "affiché, lire le presse-papiers, y écrire du texte à coller ailleurs.",
        tools=("screenshot_take", "clipboard_read", "clipboard_write"),
        keywords=frozenset({"presse-papier", "presse-papiers", "clipboard", "capture"}),
    ),
    "process": ToolGroup(
        covers="Processus de la machine : lister ce qui tourne et ce qui consomme du CPU "
               "ou de la mémoire, arrêter un programme par son identifiant.",
        tools=("process_list", "process_kill"),
        keywords=frozenset({"processus", "process"}),
    ),
    "network": ToolGroup(
        covers="Réseau local de la machine : nom du Wi-Fi, adresse IP, force du signal, "
               "latence de la connexion.",
        tools=("wifi_info",),
        keywords=frozenset({"wifi", "reseau", "réseau", "ip"}),
    ),
    "gmail": ToolGroup(
        covers="Boîte mail Gmail : chercher des messages, résumer les mails reçus, "
               "rédiger et envoyer un email, modifier un brouillon avant envoi.",
        tools=("gmail_search", "gmail_summarize", "gmail_send_email",
               "gmail_edit_draft", "gmail_confirm_send"),
        keywords=frozenset({"gmail", "mail", "mails", "email", "emails", "e-mail"}),
    ),
    "calendar": ToolGroup(
        covers="Agenda Google Calendar : consulter les rendez-vous et événements à venir "
               "d'une journée ou d'une période, en créer, les déplacer, les supprimer, "
               "chercher un événement, lister les agendas.",
        tools=("calendar_list_events", "calendar_create_event", "calendar_update_event",
               "calendar_delete_event", "calendar_list_calendars", "calendar_search_events"),
        keywords=frozenset({"calendar", "agenda"}),
    ),
    "drive": ToolGroup(
        covers="Documents Google en ligne. Drive : parcourir et lister les fichiers, "
               "retrouver l'identifiant d'un document par son nom, lire son contenu, "
               "consulter ses métadonnées, le supprimer. Docs : créer un nouveau document, "
               "y ajouter du texte, lire son contenu.",
        tools=("drive_list_files", "drive_find_file_id", "drive_read_file",
               "drive_delete_file", "drive_get_file_metadata",
               "google_docs_create", "google_docs_update", "google_docs_read"),
        keywords=frozenset({"drive", "gdoc", "gdocs"}),
    ),
    "slack": ToolGroup(
        covers="Slack : poster un message dans un canal, un salon ou une conversation "
               "privée, prévenir l'équipe, lire ce qui se dit dans un canal, chercher "
               "dans les messages, voir ses mentions, lister les canaux et retrouver une "
               "personne.",
        tools=("slack_find_user", "slack_list_channels", "slack_read_channel",
               "slack_get_mentions", "slack_list_dms", "slack_send_message",
               "slack_search_messages"),
        keywords=frozenset({"slack"}),
    ),
    "jira": ToolGroup(
        covers="Jira : tickets, issues, sprints, epics et projets. Voir les tickets qui "
               "me sont assignés et ce que j'ai à faire, chercher des issues, créer un "
               "ticket ou tout un backlog, modifier ou assigner un ticket, changer son "
               "statut, commenter, suivre l'avancement d'un projet et la charge de "
               "travail de l'équipe.",
        tools=("jira_get_my_issues", "jira_get_issue", "jira_search_issues",
               "jira_get_project_summary", "jira_get_sprint_issues",
               "jira_list_projects", "jira_add_comment", "jira_transition_issue",
               "jira_get_workload", "jira_create_issue", "jira_create_issues_bulk",
               "jira_assign_issue", "jira_update_issue", "jira_get_issue_comments",
               "jira_search_users", "jira_move_issue", "jira_delete_issue",
               "jira_link_to_epic"),
        keywords=frozenset({"jira", "sprint", "backlog"}),
    ),
    # `news` est séparé de `search` alors que les deux interrogent le web. Mesuré :
    # dans un document unique couvrant les deux, les formulations d'actualité ne
    # retrouvaient plus leur groupe que 6 fois sur 24 — contre 20 une fois séparées,
    # sans rien coûter aux formulations de recherche (19/22 dans les deux cas).
    # L'embedding d'un document multi-sujets est la moyenne de ses sujets : le sujet
    # minoritaire y devient indistinct. Un groupe doit donc porter UNE intention, pas
    # un fournisseur commun.
    "search": ToolGroup(
        covers="Chercher de l'information sur le web : recherche approfondie avec "
               "sources et citations, se renseigner sur un sujet, trouver la "
               "documentation d'une librairie, récupérer le contenu d'une page ou "
               "d'une URL. Aussi les articles et papers de recherche scientifique "
               "sur arXiv.",
        tools=("web_research_report", "url_fetch", "arxiv_search", "arxiv_get_paper"),
        keywords=frozenset({"arxiv", "internet", "web"}),
    ),
    "news": ToolGroup(
        covers="Actualités et événements récents : ce qui s'est passé aujourd'hui ou "
               "hier, les dernières nouvelles sur un sujet, résultats sportifs, scores "
               "de matchs et classements, annonces d'entreprises et sorties de produits, "
               "politique, élections et crises en cours.",
        tools=("web_search_news",),
        keywords=frozenset({"actualite", "actualité", "actualites", "actualités", "news"}),
    ),
    "time": ToolGroup(
        covers="Date et heure courantes : quelle heure il est, quel jour on est, la date "
               "d'aujourd'hui, le jour de la semaine.",
        tools=("get_current_time",),
    ),
    "weather": ToolGroup(
        covers="Météo d'une ville : le temps qu'il fait, la température, les conditions "
               "actuelles et à venir.",
        tools=("get_weather_by_city",),
        keywords=frozenset({"meteo", "météo"}),
    ),
    "diagrams": ToolGroup(
        covers="Produire un schéma ou un diagramme visuel : architecture d'un système, "
               "flowchart, diagramme de séquence, entité-relation, organigramme, mind "
               "map, pipeline, flux de données. Représenter, illustrer ou dessiner "
               "visuellement un fonctionnement.",
        tools=("mermaid_diagram",),
        keywords=frozenset({"mermaid", "diagramme", "schema", "schéma", "organigramme", "flowchart"}),
    ),
    "memory": ToolGroup(
        covers="Mémoire persistante du projet : retenir un fait pour les prochaines "
               "sessions, noter une information non évidente, mettre à jour AXON.md.",
        tools=("axon_note",),
        keywords=frozenset({"axon.md"}),
    ),
    "study": ToolGroup(
        covers="Fiches de révision et exercices : produire depuis un cours ou un PDF une "
               "fiche de synthèse ou un quiz interactif en HTML, puis l'ouvrir dans le "
               "navigateur.",
        tools=("save_study_file",),
        keywords=frozenset({"fiche", "revision", "révision", "exercices", "quiz"}),
    ),
    "skills": ToolGroup(
        covers="Charger la procédure écrite d'avance pour un savoir-faire particulier, "
               "avant d'agir dans ce domaine.",
        tools=("load_skill",),
        extend=_skill_topics,
    ),
    "cron": ToolGroup(
        covers="Tâches planifiées et récurrentes : faire quelque chose tous les jours, "
               "chaque matin, chaque semaine ou à intervalle régulier, à heure fixe, "
               "surveiller en continu et alerter, rappeler plus tard, produire un "
               "récapitulatif quotidien automatique, lister ou arrêter les tâches "
               "programmées.",
        tools=("schedule_task", "list_cron_tasks", "stop_cron_task"),
        keywords=frozenset({"cron", "planifie", "planifier", "recurrent", "récurrent"}),
    ),
    "quant": ToolGroup(
        covers="Paris sportifs et analyse quantitative : scanner les matchs disponibles "
               "aujourd'hui ou demain et proposer quoi jouer avec une bankroll, cotes d'un "
               "match chez le bookmaker, y a-t-il un bon pari à jouer ce soir, value bet, "
               "statistiques et forme d'une équipe, probabilité de victoire, espérance de "
               "gain, rentabilité d'un pari, mise à engager, freebets, combinés.",
        tools=("betting_recommend", "winamax_odds_fetch", "sports_stats_fetch",
               "probability_compute", "ev_analyze", "parlay_analyze",
               "same_match_combo_analyze"),
        keywords=frozenset({"winamax", "pari", "paris", "parier", "cote", "cotes",
                            "combine", "combiné", "bankroll", "freebet", "freebets",
                            "miser", "mise"}),
    ),
}

# Index inverse : tool_name → group_name
_TOOL_TO_GROUP: dict[str, str] = {
    tool: group
    for group, spec in TOOL_GROUPS.items()
    for tool in spec.tools
}

# ── Épinglage ─────────────────────────────────────────────────
# Override VOLONTAIRE, pas une béquille de retrieval : ces outils sont là parce
# qu'on veut qu'ils soient toujours disponibles, pas parce que la recherche
# n'arrive pas à les retrouver. `notify` et `ask_clarification` sont des canaux
# vers l'utilisateur ; `shell` est l'échappatoire qui permet d'agir sur la
# machine à n'importe quel moment d'un raisonnement.
_PINNED_TOOLS = {"get_current_time", "ask_clarification", "notify"}
_PINNED_GROUPS = ("shell",)

# ── Réglages du routing ───────────────────────────────────────
# Mesuré sur les deux jeux de tests/test_tool_routing.py :
#            requêtes de référence     corpus d'ancres     outils sélectionnés
#   3 groupes      20/22                    —                    15,3
#   4 groupes      21/22                  77,9 %                 18,2
#   5 groupes      22/22                  80,9 %                 21,0
# 5 tient sous les 21,6 outils de l'ancien index tout en le dépassant partout
# ailleurs. Les cas qui exigent ce 5e rang sont des collisions lexicales de
# l'embedder, pas des descriptions fautives : « bons paris ce soir » élit
# `weather` (Paris, la ville) et « cherche un papier » élit `desktop`
# (presse-papiers). Un homographe ne se corrige pas en réécrivant la description
# — essayé, mesuré : la variante qui gagne cette requête perd sur le corpus.
_TOP_GROUPS = 5
# Au-delà, on sous-classe dans le groupe au lieu de le prendre entier : seul
# `jira` dépasse. En deçà, la cohésion prime — on ne veut jamais `git_status`
# sans `git_add`.
_GROUP_FANOUT_MAX = 12
_GROUP_SOURCE, _TOOL_SOURCE = "group", "tool"


_CACHE_DIR  = Path.home() / ".axon" / "tool_store"
_CACHE_HASH = _CACHE_DIR / "fingerprint.txt"


def _build_documents(tools: list) -> list[Document]:
    """Deux étages, deux familles de documents dans le même store.

    Étage 1 : un document par groupe. Étage 2 : un document par outil, sa vraie
    description, rien d'autre — aucune phrase d'ancrage. Un outil pèse donc
    exactement un document, comme tous les autres.
    """
    docs = [
        Document(page_content=spec.document(name),
                 metadata={"source": _GROUP_SOURCE, "group": name})
        for name, spec in TOOL_GROUPS.items()
    ]
    docs += [
        Document(page_content=f"{t.name}: {t.description}",
                 metadata={"source": _TOOL_SOURCE, "tool_name": t.name,
                           "group": _TOOL_TO_GROUP.get(t.name, "")})
        for t in tools
    ]
    return docs


def _fingerprint(docs: list[Document]) -> str:
    """Hash de CE QUI EST INDEXÉ, pas de ses ingrédients.

    Les documents dépendent des outils, des descriptions de groupe et — via
    `extend` — des skills installés. Hasher les entrées obligerait à penser à
    chaque nouvelle source ; en hashant le résultat, un cache périmé devient
    impossible par construction plutôt que par vigilance.
    """
    import hashlib, json
    payload = sorted((d.page_content, sorted(d.metadata.items())) for d in docs)
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]


class ToolRetriever:
    def __init__(self, tools: list, k: int = 7):
        from src.ui.boot import report_step
        report_step("index sémantique…")
        embeddings = OllamaEmbeddings(model="nomic-embed-text")
        docs = _build_documents(tools)
        current_hash = _fingerprint(docs)
        cache_valid = (
            _CACHE_DIR.exists()
            and _CACHE_HASH.exists()
            and _CACHE_HASH.read_text().strip() == current_hash
        )

        if cache_valid:
            self._store = Chroma(persist_directory=str(_CACHE_DIR), embedding_function=embeddings)
        else:
            # Repart de zéro à chaque reconstruction — sinon les anciennes générations
            # de documents (précédentes listes de tools) s'accumulent indéfiniment dans
            # Chroma et diluent la recherche par similarité avec des doublons obsolètes.
            if _CACHE_DIR.exists():
                import shutil
                shutil.rmtree(_CACHE_DIR)
            _CACHE_DIR.mkdir(parents=True, exist_ok=True)
            self._store = Chroma.from_documents(docs, embeddings, persist_directory=str(_CACHE_DIR))
            _CACHE_HASH.write_text(current_hash)

        self._tools = tools
        self._k = k

    def _rank_groups(self, query: str) -> list[str]:
        """Étage 1, HYBRIDE : correspondance exacte d'abord, puis similarité.

        La recherche dense seule rate les termes rares dans les phrases courtes —
        « envoie ça à Nicolas sur Slack » classait `slack` 17e sur 22. Un terme
        qui NOMME un groupe ne doit jamais dépendre d'un rang vectoriel : c'est le
        cas le plus certain qui soit, et c'était le seul à échouer.

        Le lexical COMPLÈTE le vectoriel, il ne le remplace pas : il n'ajoute que
        des groupes explicitement nommés, et la similarité continue de fournir
        tout ce qui est demandé sans être nommé. L'ordre compte — le rang 1 décide
        de l'étape 4 — donc un groupe nommé littéralement passe devant.
        """
        nommes = _keyword_groups(query)
        docs = self._store.similarity_search(
            query, k=_TOP_GROUPS, filter={"source": _GROUP_SOURCE})
        return unique(nommes + [d.metadata.get("group") for d in docs])

    def _tools_of(self, group: str, query: str) -> list[str]:
        """Étage 2. Un groupe cohésif est pris entier ; un gros groupe est
        sous-classé en MMR, qui diversifie au lieu de ramener une famille de
        quasi-doublons (18 tools Jira se ressemblent beaucoup entre eux)."""
        spec = TOOL_GROUPS[group]
        if len(spec.tools) <= _GROUP_FANOUT_MAX:
            return list(spec.tools)
        flt = {"$and": [{"source": _TOOL_SOURCE}, {"group": group}]}
        try:
            docs = self._store.max_marginal_relevance_search(
                query, k=self._k, fetch_k=max(self._k * 4, 20), lambda_mult=0.5, filter=flt)
        except Exception:
            docs = self._store.similarity_search(query, k=self._k, filter=flt)
        return unique(d.metadata.get("tool_name") for d in docs)

    def get(self, query: str) -> list:
        ranked = self._rank_groups(query)
        groups = ranked + [g for g in _PINNED_GROUPS if g not in ranked]

        selected: set[str] = set(_PINNED_TOOLS)
        for group in groups:
            selected.update(self._tools_of(group, query))

        # Le specialist gère lui-même les fichiers et git : les lui laisser évite
        # que l'orchestrateur commence le travail au lieu de déléguer. Seulement
        # quand `coding` gagne l'étage 1, pas dès qu'il apparaît — « lis le fichier
        # src/main.py » élit `filesystem` en tête et `coding` en second, et perdait
        # alors l'outil de lecture qu'il venait de trouver.
        if ranked and ranked[0] == "coding":
            for group in ("git", "filesystem"):
                selected -= set(TOOL_GROUPS[group].tools)

        return [t for t in self._tools if t.name in selected]
