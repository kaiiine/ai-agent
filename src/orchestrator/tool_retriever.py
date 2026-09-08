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

from src.infra import chemins as _chemins
from src.infra.pont_fr_en import pont_linguistique
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
    # Termes qui INDIQUENT le groupe sans le désigner. Ils le rendent joignable,
    # jamais certain — pas de rang 1.
    #
    # `prix` a fait la démonstration des deux côtés : sur les 112 requêtes réelles
    # il déclenchait 0 fois juste pour 2 faux (« si le prix change de plus de 1 % »
    # est une surveillance, pas un achat, et poser le rang 1 sur `search` volait la
    # place à `cron`) — mais « quel est le prix du Lenovo Legion 7i » a besoin de
    # la recherche web. Un mot peut être un bon indice et une mauvaise certitude ;
    # le supprimer comme le garder dur étaient tous deux faux.
    soft_keywords: frozenset[str] = frozenset()
    # Rang minimal exigé à l'étage 1 pour que le groupe entre dans la sélection.
    # `None` = aucun seuil, le cas normal : admettre `local_grep` au rang 5 ne
    # coûte qu'un outil de plus dans le prompt.
    #
    # Ce seuil existe pour les groupes dont l'outil AGIT — `run_coding_agent`
    # délègue et écrit des fichiers sur le disque. Le proposer parce qu'il est
    # cinquième, sur « lis le fichier src/main.py » ou « télécharge cette page »,
    # met à portée du modèle une action lourde que la requête ne demandait pas.
    # Un seuil de rang généralise à toutes les formulations, là où une liste de
    # phrases ne couvrirait que celles qu'on a pensé écrire.
    requires_top_rank: int | None = field(default=None, compare=False)
    # Outils qui MÈNENT le groupe : liés les premiers dès que le groupe l'est.
    #
    # Le budget coupe dans le classement du groupe, or ce classement est dense —
    # et l'embedding ne sépare pas les verbes d'une même famille : sur « crée un
    # événement », `calendar_delete_event` sort avant `calendar_create_event`.
    # Un invariant métier ne peut donc pas reposer dessus. `betting_recommend`
    # est l'UNIQUE chemin de recommandation : lier `parlay_analyze` sans lui rend
    # au modèle la configuration exacte qui lui faisait produire des paris
    # lui-même. Ce qui doit toujours être là se déclare, ne s'espère pas.
    tete: tuple[str, ...] = ()
    # Sous-familles d'INTENTION à l'intérieur du groupe. Un groupe peut être
    # cohésif au niveau 1 — tout y parle de paris — sans que ses outils soient
    # nécessaires ensemble : demander les cotes n'appelle pas l'analyse d'un
    # combiné. Quand elles sont déclarées, seule la famille visée est liée, ce
    # qui rend au budget les places que le reste du groupe occupait.
    #
    # Pas d'index dédié : une famille vaut le rang de son meilleur outil, déjà
    # calculé à l'étage 2. Un vecteur de plus par famille agirait comme un a
    # priori sur le groupe — mesuré ailleurs, le rang-1 global tombait de 41 à
    # 30 % quand un groupe portait cinq documents au lieu d'un.
    capabilities: dict[str, tuple[str, ...]] | None = field(default=None, compare=False)

    def document(self, name: str, *, max_chars: int = 2000) -> str:
        covers = self.covers
        if self.extend:
            extra = ", ".join(self.extend())
            if extra:
                covers = f"{covers} Domaines disponibles : {extra}."
        # La liste des noms d'outils RESTE dans le document, malgré l'intuition
        # que l'étage 1 score un domaine et non des outils. Retirée, le vecteur
        # seul gagnait deux points au rang 1 — mais le pipeline complet perdait
        # cinq points de rappel groupe (82 -> 77 %) et six à l'outil. Les noms
        # portent un signal que les clauses et la correspondance exacte
        # exploitent ; le rang isolé n'est pas le service rendu.
        return build_catalog_document(
            {"Groupe": name, "Couvre": covers}, "Outils", self.tools, max_chars=max_chars
        )


_WORD = re.compile(r"[\w-]+", re.UNICODE)


def _familles_visees(spec: "ToolGroup", classes: list[str]) -> list[str]:
    """Les outils des `_FAMILLES_MAX` familles les mieux placées, plus la tête.

    Une famille vaut le rang de son meilleur outil. Garder la tête quoi qu'il
    arrive n'est pas un confort : elle porte un invariant — `betting_recommend`
    est l'unique chemin de recommandation, et une demande de cotes reste une
    demande de pari.
    """
    rang = {nom: i for i, nom in enumerate(classes)}
    familles = sorted(spec.capabilities.items(),
                      key=lambda kv: min((rang.get(t, 999) for t in kv[1]), default=999))
    gardes = {t for _, outils in familles[:_FAMILLES_MAX] for t in outils}
    gardes.update(spec.tete)
    return [t for t in classes if t in gardes]


def _soft_keyword_groups(query: str) -> list[str]:
    """Groupes seulement INDIQUÉS. Mêmes mots entiers, sans le rang 1."""
    mots = {m.group(0).lower() for m in _WORD.finditer(query)}
    return [g for g, spec in TOOL_GROUPS.items() if spec.soft_keywords & mots]


def _keyword_groups(query: str) -> list[str]:
    """Groupes NOMMÉS littéralement dans la requête, dans l'ordre de déclaration.

    Comparaison sur des mots entiers, jamais sur des sous-chaînes : « paris » ne
    doit pas être trouvé dans « comparaison », et « ip » pas dans « équipe »."""
    mots = {m.group(0).lower() for m in _WORD.finditer(query)}
    return [g for g, spec in TOOL_GROUPS.items() if spec.keywords & mots]


def _clauses(query: str) -> list[str]:
    """Les clauses d'une requête composite, ou [] si elle n'en a qu'une.

    Retourner [] plutôt que [query] est délibéré : l'appelant distingue ainsi
    « une seule intention » de « plusieurs », et n'applique marge et plafond que
    dans le second cas.
    """
    morceaux = [m.strip() for m in _COUPE_CLAUSES.split(query or "")
                if len(m.strip()) >= _CLAUSE_MIN_CHARS]
    return morceaux if len(morceaux) > 1 else []


# ── Porte déterministe d'intention money ──────────────────────────────────────
# Le routing sémantique est un plus-proche-voisin : son résultat dépend du corpus
# d'embeddings, qui dérive. Mesuré sur douze intentions de pari, deux n'élisaient
# jamais le groupe `quant` — « que dois-je jouer ce soir » et « scanne tout ce qui
# est disponible aujourd'hui et demain », c'est-à-dire les formulations mêmes du
# dump. Sans `betting_recommend` dans la sélection, le modèle n'a plus que des
# outils de données et refait exactement ce qu'on vient de fermer.
#
# Une intention d'argent ne peut pas dépendre d'une distance vectorielle. Cette
# porte s'ajoute au routing sémantique sans le remplacer : elle ne fait
# qu'ADJOINDRE le groupe, jamais en retirer un autre. Un faux positif coûte un
# outil de plus dans le prompt ; un faux négatif rouvre le second moteur. Face à
# cette asymétrie, on inclut.
_MONEY_INTENT = re.compile(
    r"(?i)("
    r"\bparis?\b|\bparier\b|\bcotes?\b|\bbankroll\b|\bfreebets?\b"
    r"|\bmise[rz]?\b|\bmises\b|\bcombin[ée]s?\b|\bvalue\s*bets?\b"
    r"|\bbookmaker\b|\bwinamax\b|\bpronostics?\b"
    # « que dois-je jouer », « je joue quoi », « quoi jouer » — aucun de ces
    # tours ne contient de mot du lexique du pari.
    # Infinitif ET conjugué : « quoi jouer » comme « je joue quoi ». Seul le
    # second est spontané à l'oral, et c'est celui qui manquait.
    r"|\b(?:que|qu'est[- ]ce\s+que|quoi)\b[^.?!]{0,30}\bjoue[rs]?\b"
    r"|\bjoue[rs]?\b[^.?!]{0,15}\bquoi\b"
    # « scanne tout ce qui est disponible aujourd'hui et demain ».
    r"|\bscann?[ez]r?\b[^.?!]{0,60}\b(?:disponibles?|dispos?|matchs?|sports?|"
    r"comp[ée]titions?|aujourd'?hui|demain|ce\s+soir)\b"
    r")")


def _money_intent(query: str) -> bool:
    return bool(_MONEY_INTENT.search(query or ""))


# ── Porte déterministe d'intention « produire du code » ───────────────────────
# Le seuil de rang du groupe `coding` rate les demandes de production formulées
# sans vocabulaire technique — mesuré sur « finis le site », « crée un fichier ».
# Sans `run_coding_agent` dans la sélection, le modèle ne peut pas déléguer.
# La porte n'ouvre que sur un VERBE DE PRODUCTION suivi d'un ARTEFACT de code ;
# les verbes de lecture ne la franchissent jamais.
_CODING_INTENT = re.compile(
    r"(?i)"
    r"\b(?:cr[ée]{1,2}[erz]?|[ée]cri[stvez]+|fai[stre]+|termine[rz]?|finis?|finir"
    r"|d[ée]veloppe[rz]?|impl[ée]mente[rz]?|code[rz]?|corrige[rz]?|refactor\w*"
    r"|ajoute[rz]?|g[ée]n[èe]re[rz]?|scaffold\w*|build\w*|reprend?s?)\b"
    r"[^.?!]{0,60}"
    # Le vocabulaire d'artefacts était calqué sur les demandes de SITE. Mesuré sur
    # les 74 sondes `coding` du corpus : 17 échouaient à l'étage sémantique, et
    # toutes nommaient un artefact absent de cette liste — « des tests
    # unitaires », « un système d'authentification », « une dépendance
    # obsolète », « des variables, fonctions ou fichiers », « le thème, les
    # couleurs ou la typographie ». Le verbe était bon, l'objet manquait.
    r"\b(?:site|page|landing|app|application|projet|composants?|fichiers?|module"
    r"|script|api|next\.?js|react|vue|svelte|astro|front|back|spec"
    r"|tests?|bugs?|r[ée]gressions?|crash|d[ée]pendances?|migrations?"
    r"|fonctions?|classes?|variables?|m[ée]thodes?|endpoints?|routes?"
    r"|authentification|auth|login|formulaires?|d[ée]ploiement"
    r"|th[èe]me|couleurs?|typographie|style|css|responsive"
    r"|base\s+de\s+donn[ée]es|sch[ée]ma|mod[èe]les?|types?)\b"
)


def _coding_intent(query: str) -> bool:
    return bool(_CODING_INTENT.search(query or ""))


# ── Porte déterministe d'intention « modifier un fichier existant » ───────────
# `filesystem` mêle cinq outils de lecture et deux d'écriture, et la similarité
# dense range TOUJOURS les lectures devant : `edit_file` sortait 7e sur 7, sur
# « commente ces deux lignes », « change la valeur de timeout » comme sur « lis
# le fichier ». Tant qu'on prenait le groupe entier ça ne se voyait pas ; depuis
# le budget, l'écriture est coupée à chaque fois.
#
# Le pont FR→EN a été essayé d'abord : il remonte `edit_file` du rang 7 au rang 5
# sur deux des trois cas, et ne bouge pas « commente ». Insuffisant — les
# descriptions des outils de lecture dominent quoi qu'on ajoute à la requête.
#
# Un verbe de modification suivi de ce qu'on modifie : le même patron que les
# trois autres portes, et pour la même raison — ce que le sémantique ne sait pas
# voir, le lexical ne le rate pas.
_ECRITURE_INTENT = re.compile(
    r"(?i)"
    r"\b(?:commente[rz]?|d[ée]commente[rz]?|modifie[rz]?|change[rz]?|remplace[rz]?"
    r"|ajoute[rz]?|retire[rz]?|renomme[rz]?|corrige[rz]?|[ée]dite?[rz]?"
    r"|rajoute[rz]?|insere[rz]?|ins[èe]re[rz]?)\b"
    r"[^.?!]{0,50}"
    r"\b(?:ligne|lignes|fichier|fichiers|config|configuration|conf|valeur|valeurs"
    r"|param[èe]tre|param[èe]tres|option|options|\S+\.(?:conf|cfg|ini|ya?ml|toml"
    r"|json|env|sh|zshrc|bashrc|py|js|ts|md))\b"
)


def _ecriture_intent(query: str) -> bool:
    return bool(_ECRITURE_INTENT.search(query or ""))


# ── Porte déterministe d'intention « récurrence » ─────────────────────────────
# `cron` était le groupe le plus mal routé du registre : 64,5 % de rappel sur ses
# 31 sondes, contre 85,9 % de moyenne. Ses onze échecs étaient tous de la même
# nature — « tous les jours », « quotidiennement », « chaque jour », « à la même
# heure », « périodiquement ». Des adverbes de RÉCURRENCE, que l'embedder envoie
# vers `time` parce qu'ils parlent d'heures et de jours.
#
# Or dire une heure et REVENIR à cette heure sont deux actes différents, et le
# second se reconnaît à des marqueurs lexicaux fermés. Contrairement au domaine
# d'un groupe, la récurrence est un trait de surface : c'est exactement le
# terrain où le lexical bat le vectoriel, comme pour `_MONEY_INTENT`.
#
# Mesuré : 31/31 sondes `cron` attrapées, 0 faux positif sur les 267 sondes des
# autres groupes. Comme les deux autres portes, celle-ci ADJOINT le groupe sans
# jamais en retirer un autre — « préviens-moi chaque matin sur Slack » doit
# garder `slack`.
_RECURRENCE_INTENT = re.compile(
    r"(?i)("
    r"\bchaque\s+(?:jour|matin|soir|semaine|mois|lundi|mardi|mercredi|jeudi"
    r"|vendredi|samedi|dimanche|heure|minute)"
    r"|\btous\s+les\s+(?:jours|matins|soirs|lundis|mardis|mercredis|jeudis"
    r"|vendredis|samedis|dimanches|\d+\s*\w+)"
    r"|\btoutes\s+les\s+(?:heures|semaines|minutes|\d+\s*\w+)"
    r"|\bquotidien\w*|\bhebdomadaire\w*|\bmensuel\w*|\bp[ée]riodique\w*"
    r"|\br[ée]curren\w*|\brecurring\b"
    r"|\bevery\s+(?:day|morning|week|hour|monday|tuesday)"
    r"|\bdaily\b|\bweekly\b|\bhourly\b"
    r"|\brappelle[- ]moi\b|\bplanifie[rz]?\b|\bschedule\w*"
    # Pas \bcron\b : le tiret est une frontière de mot, et « le canal test-cron »
    # est un nom de canal Slack, pas une demande de planification. Mesuré sur le
    # jeu de référence — c'était le seul faux positif qui restait.
    r"|(?<![\w-])cron\b"
    r"|\b[àa]\s+(?:la\s+m[êe]me\s+)?heure(?:\s+fixe)?\b"
    r"(?=[^.?!]*\b(?:tous|chaque|fixe|automatiquement)\b)"
    r"|\bautomatiquement\b[^.?!]{0,20}\bheure\b|\b[àa]\s+heure\s+fixe\b"
    # « notifie-moi si », « alerte si », « préviens-moi quand » : une condition à
    # surveiller suppose de repasser la vérifier.
    r"|\b(?:notifie|alerte|pr[ée]viens)[- ]?(?:moi)?\s*(?:si|quand|d[èe]s)\b"
    r"|\bsurveille\b|\bv[ée]rifie\b[^.?!]{0,15}\bp[ée]riodiquement\b"
    r")")


def _recurrence_intent(query: str) -> bool:
    return bool(_RECURRENCE_INTENT.search(query or ""))


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
        # Le document le plus long du registre (510 caractères) et le plus large :
        # il énumérait tant de vocabulaire technique général qu'il remontait sur
        # cinq requêtes non-coding — un schéma d'architecture, une lecture de
        # fichier, un téléchargement de page. La largeur d'un document agit comme
        # la cardinalité d'un index : elle achète de la proximité avec tout.
        #
        # On mène donc par l'ACTE — écrire du code dans des fichiers — et on
        # nomme explicitement ce qui n'en relève pas.
        covers="Déléguer un travail de développement sur un projet de code à un agent "
               "spécialisé qui écrit les fichiers lui-même. Corriger un bug, déboguer un "
               "crash, ajouter une fonctionnalité, une route d'API, un composant ou une "
               "page, refactoriser un module, migrer un framework, écrire des tests, "
               "configurer le build ou le linting. Aussi : créer une application ou un "
               "site web à partir de rien — landing page, site vitrine, page d'accueil, "
               "projet Next.js, React, Vue ou Svelte. Le livrable est du code source "
               "sur le disque. Écris une fonction, une classe, un script, un composant. "
               "Crée un site vitrine, une boutique en ligne, un portfolio, un tableau "
               "de bord, une API.",
        tools=("run_coding_agent",),
        requires_top_rank=3,
    ),
    "git": ToolGroup(
        # La description menait par le jargon (« Dépôt git », index, remisage) et
        # l'embedding s'en trouvait tiré loin d'une question posée en français
        # courant : « quels sont mes fichiers modifiés » ne remontait même pas
        # `git` dans les cinq premiers, alors que la phrase « voir les fichiers
        # modifiés » y figurait mot pour mot. On mène donc par l'INTENTION, et le
        # vocabulaire technique vient après.
        covers="Savoir quels fichiers j'ai modifiés, changés ou touchés dans mon projet, "
               "et ce qui a changé depuis la dernière fois : état de la copie de travail, "
               "modifications en cours non encore validées, différences ligne à ligne. "
               "Aussi l'historique des commits, ajouter des fichiers à l'index, committer, "
               "changer de branche, remiser. Dépôt git. Ne lit pas le contenu d'un "
               "fichier et ne cherche pas un fichier par son nom.",
        tools=("git_status", "git_log", "git_diff", "git_suggest_commit",
               "git_add", "git_commit", "git_checkout", "git_stash"),
        keywords=frozenset({"git", "commit", "commits", "branche", "branch",
                            "depot", "dépôt", "staged", "diff"}),
    ),
    "filesystem": ToolGroup(
        covers="Fichiers locaux du disque : retrouver un fichier par son nom ou un motif, "
               "lister le contenu d'un dossier, lire le contenu d'un fichier, chercher un "
               "texte ou une définition à l'intérieur des fichiers. Aussi MODIFIER un "
               "fichier existant — commenter ou décommenter une ligne, changer une "
               "valeur, corriger une entrée de configuration — et en créer un.",
        tools=("local_find_file", "local_read_file", "local_list_directory",
               "local_grep", "local_glob",
               # Lire sans pouvoir écrire enfermait l'orchestrateur : `shell_run`
               # bloque l'écriture et renvoie vers ces deux-là, qu'il n'avait pas.
               "edit_file", "propose_file_change", "propose_file_delete"),
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
               "rédiger et envoyer un email avec pièces jointes et copie, répondre "
               "dans un fil de discussion, modifier un brouillon avant envoi.",
        tools=("gmail_search", "gmail_summarize", "gmail_send_email",
               "gmail_edit_draft", "gmail_confirm_send", "gmail_reply"),
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
               "google_docs_create", "google_docs_write", "google_docs_read"),
        keywords=frozenset({"drive", "gdoc", "gdocs"}),
    ),
    "sheets": ToolGroup(
        covers="Tableur Google Sheets : créer une feuille de calcul, y ajouter des "
               "lignes de données, lire les valeurs d'une plage, tenir un budget ou "
               "un suivi chiffré.",
        tools=("sheets_create", "sheets_append_rows", "sheets_read"),
        keywords=frozenset({"sheets", "sheet", "tableur", "gsheet", "spreadsheet"}),
    ),
    # Deux groupes, parce que ce sont deux ACTES différents : produire un deck,
    # et le déposer chez Google. Les réunir laissait le modèle arbitrer entre
    # `create_slides` et `slides_create` sur la seule foi de leurs descriptions —
    # et il prenait le second, qui construit une diapositive PAR APPEL et épuise
    # le budget de tours avant la fin du deck.
    "translate": ToolGroup(
        covers="Traduire un mot, une phrase ou un texte d'une langue vers une "
               "autre : comment dit-on ceci en anglais, en espagnol, en allemand, "
               "traduis ce paragraphe, donne-moi l'équivalent dans une autre langue.",
        tools=("translator",),
        keywords=frozenset({"traduis", "traduire", "traduction", "translate"}),
    ),
    "slides": ToolGroup(
        covers="Faire une présentation, un diaporama, un deck, un PowerPoint : "
               "synthétiser un sujet en diapositives avec titre, puces, chiffres, "
               "tableaux, citations et sommaire, pour une réunion, un cours ou un "
               "exposé. Produit le fichier et l'ouvre.",
        tools=("create_slides",),
        keywords=frozenset({"slides", "slide", "diapo", "diapositive", "diaporama",
                            "presentation", "présentation", "deck", "powerpoint",
                            "pptx"}),
    ),
    "google_slides": ToolGroup(
        covers="Déposer ou modifier une présentation DANS GOOGLE SLIDES, le "
               "service en ligne de Google : créer le document chez Google, y "
               "ajouter des diapositives, le rendre partageable depuis Drive.",
        tools=("slides_create", "slides_add_slide", "slides_from_markdown"),
        keywords=frozenset({"gslides"}),
        # Google Slides est une DESTINATION, pas une façon de faire un deck.
        # Sans ce seuil, il remontait sur toute demande de présentation et
        # redevenait le chemin par défaut.
        requires_top_rank=2,
    ),
    "slack": ToolGroup(
        covers="Slack : envoyer, poster ou publier un message, un récap ou un compte "
               "rendu dans un salon, un canal, un channel ou une conversation privée, "
               "prévenir l'équipe, lire ce qui se dit dans un salon, chercher dans les "
               "messages, voir ses mentions, lister les salons et retrouver une personne.",
        tools=("slack_find_user", "slack_list_channels", "slack_read_channel",
               "slack_get_mentions", "slack_list_dms", "slack_send_message",
               "slack_search_messages"),
        # « salon », « canal » et « channel » ne désignent rien d'autre dans ce
        # produit. La description contenait déjà le mot « salon » et le groupe
        # sortait quand même hors du top 5 : l'embedder dilue un terme rare dans
        # une phrase courte et banale, la correspondance exacte ne le rate jamais.
        # `canal`/`canaux` passés en indice : 0 déclenchement juste pour 2 faux —
        # « surveille le cours d'actions » n'a rien de Slack. `salon` reste dur,
        # contrairement à ce que l'intuition dit : c'est la mesure qui départage,
        # pas l'air ambigu d'un mot.
        keywords=frozenset({"slack", "salon", "salons", "channel", "channels"}),
        soft_keywords=frozenset({"canal", "canaux"}),
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
               "sur arXiv, et les recherches APPROFONDIES : dossier complet, état "
               "de l'art, comparatif argumenté, faire le tour d'un sujet.",
        tools=("web_research_report", "deep_research", "url_fetch",
               "arxiv_search", "arxiv_get_paper"),
        # Le vocabulaire commercial est passé en INDICE. Mesuré sur les 112
        # requêtes réelles, `prix` déclenchait 0 fois juste pour 2 faux — mais le
        # corpus de référence commercial en a besoin (« quel est le prix du Lenovo
        # Legion 7i »). Un mot qui a raison une fois sur deux ne peut pas poser le
        # rang 1 ; il peut rendre le groupe joignable.
        keywords=frozenset({"arxiv", "web"}),
        soft_keywords=frozenset({"internet",
                                 "promo", "promos", "reduction", "réduction",
                                 "prix", "tarif", "tarifs", "solde", "soldes",
                                 "remise", "remises"}),
    ),
    "news": ToolGroup(
        covers="Actualités et événements récents : ce qui s'est passé aujourd'hui ou "
               "hier, les dernières nouvelles sur un sujet, résultats sportifs, scores "
               "de matchs et classements, communiqués et annonces d'entreprises, "
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
        covers="Météo d'une ville : le temps qu'il fait et celui qu'il fera. Température, "
               "pluie, neige, vent, orage. Aujourd'hui, demain, après-demain, ce week-end, "
               "cette semaine. Prévisions à plusieurs jours.",
        tools=("get_weather_by_city",),
        keywords=frozenset({"meteo", "météo", "previsions", "prévisions"}),
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
        # Document court et générique : il se logeait près du centroïde de
        # l'espace, donc proche de tout. Il sortait au rang 1 sur « quels sont mes
        # fichiers modifiés » comme sur « envoie le récap dans le salon », deux
        # requêtes qui ne le concernent en rien. On restreint aux intentions de
        # mémoire EXPLICITES et on dit ce qu'il ne fait pas.
        covers="Se souvenir explicitement de quelque chose pour les prochaines sessions : "
               "mémorise ceci, retiens cette préférence, note-le dans ta mémoire, "
               "qu'est-ce que tu sais de moi, rappelle-toi de ce que je t'ai dit, "
               "mettre à jour AXON.md. Uniquement la mémoire de l'assistant : ne "
               "cherche rien, n'envoie rien, ne lit aucun fichier, ne consulte ni le "
               "dépôt, ni les messages, ni le web.",
        tools=("axon_note",),
        keywords=frozenset({"axon.md", "memorise", "mémorise", "souviens", "retiens"}),
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
        tools=("schedule_task", "surveiller", "list_cron_tasks", "stop_cron_task"),
        # « rappelle moi dans 2 heures » classait `schedule_task` DERNIER de son
        # propre groupe, derrière `stop_cron_task` : les quatre outils parlent de
        # tâches planifiées, et seul le verbe les sépare. Planifier est l'action
        # première du groupe ; lire et arrêter supposent qu'une tâche existe.
        tete=("schedule_task",),
        # `surveiller` vit ici faute de mieux. Un groupe dédié donnait 5/5 en
        # réglage ET en held-out, contre 4/5 et 1/5 ici — mais l'étage 1 ne
        # discrimine pas les requêtes courtes : sur « mes rendez-vous de demain »,
        # sept groupes tiennent dans un écart de 0.04 et `calendar` sort 5e.
        # Toute intention ajoutée éjecte donc un groupe qui ne tenait que par la
        # largeur de la coupure. À rebasculer quand l'étage 1 saura trancher.
        keywords=frozenset({"cron", "planifie", "planifier", "recurrent", "récurrent",
                            "surveille", "surveiller", "veille", "alerte-moi",
                            "previens-moi", "préviens-moi", "avertis-moi"}),
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
        # Les deux PORTES D'ENTRÉE du domaine : recommander, et aller chercher les
        # cotes. `probability_compute` et `ev_analyze` sont des étages en aval —
        # ils sortaient pourtant devant `winamax_odds_fetch` sur « y a-t-il de bons
        # paris ce soir », parce que la similarité dense classe des outils d'une
        # même famille sans distinguer ce qui commence de ce qui poursuit.
        tete=("betting_recommend", "winamax_odds_fetch"),
        # Quatre actes distincts, pas sept outils interchangeables. Demander les
        # cotes d'un match n'appelle ni le calcul de probabilité ni l'analyse
        # d'un combiné — et ce groupe est le plus lourd du registre : sur « donne
        # moi les cotes du match PSG Marseille » il liait six outils pour 5 436
        # tokens, soit un tiers de l'entrée du tour.
        capabilities={
            "recommander": ("betting_recommend",),
            "cotes": ("winamax_odds_fetch",),
            "analyser": ("sports_stats_fetch", "probability_compute", "ev_analyze"),
            "combine": ("parlay_analyze", "same_match_combo_analyze"),
        },
        keywords=frozenset({"winamax", "pari", "paris", "parier",
                            "combine", "combiné", "bankroll", "freebet", "freebets",
                            "miser", "mise"}),
        # `cote`/`cotes` en indice : 2 déclenchements justes pour 4 faux, dont
        # « les entreprises cotées en bourse ». Et comme ce groupe exige le rang 3,
        # un simple indice ne l'ouvre pas — c'est voulu : on n'entre pas dans le
        # groupe le plus lourd du registre sur un mot qui a tort deux fois sur
        # trois. `winamax` et `paris` restent durs, et la porte `_money_intent`
        # rattrape le vocabulaire de pari.
        soft_keywords=frozenset({"cote", "cotes"}),
        # Le groupe le plus LOURD du registre : sept outils, ~5 000 tokens de
        # schémas, dont 1 984 pour `betting_recommend` seul. Le proposer parce
        # qu'il est arrivé quatrième coûte 45 % de l'entrée d'un tour.
        #
        # Vécu : « il me reste combien de stockage ? » le classait 4e — la
        # tournure « il me reste combien » ressemble à « combien il me reste à
        # miser », et « espérance de gain » ou « bankroll » sont dans sa
        # description. Sur une RTX 3070 Ti (8 Go), ces 5 957 tokens en trop
        # valaient 48 secondes d'ingestion pour un `df -h`.
        #
        # Le seuil est à 3, pas 2. Première tentative à 2 : un test de
        # non-régression l'a refusée, à raison. Les demandes qui POURSUIVENT une
        # conversation de paris n'ont ni le vocabulaire ni le rang 1 —
        # « uniquement l'ATP aujourd'hui » sort au rang 3 et sans intention
        # lexicale, et un seuil à 2 la coupait du domaine.
        #
        # Les rangs mesurés séparent proprement à 3 :
        #     rang 1   six demandes explicites de paris
        #     rang 2   « tous les sports et toutes les compétitions »
        #     rang 3   « uniquement l'ATP aujourd'hui »
        #     rang 4   « il me reste combien de stockage ? »   ← à exclure
        #
        # Même valeur que `coding`, et pour la même raison : ne pas mettre une
        # action lourde à portée d'une requête qui ne la demande pas.
        requires_top_rank=3,
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
#: Groupe élu par la porte déterministe d'intention money (`_money_intent`).
_MONEY_GROUP = "quant"
#: Groupe élu par la porte déterministe d'intention code (`_coding_intent`).
_CODING_GROUP = "coding"
#: Groupe élu par la porte déterministe de récurrence (`_recurrence_intent`).
_CRON_GROUP = "cron"

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
# Balayé : 3 coûte 1,8 point de rappel, 7 n'en rend aucun.
#     python outils/mesure_routage.py --constantes
_TOP_GROUPS = 5

# ── Requêtes composites ───────────────────────────────────────
# Une requête est encodée en UN vecteur. « lis le README et poste un résumé sur
# slack » produit donc un point unique où la moitié « slack » écrase la moitié
# « fichier » : `filesystem` n'apparaît dans AUCUN des huit premiers groupes,
# et élargir la sélection ne le rattrape pas — vérifié jusqu'à huit groupes.
# Ce n'est pas un défaut de seuil, c'est la limite du vecteur unique.
#
# Router chaque clause séparément puis unir lève exactement cette limite.
# Mesuré sur les 298 sondes du corpus :
#                                 global    multi-clauses   groupes/req
#   vecteur unique (avant)         85,9 %       73,9 %          5,00
#   par clause                     86,6 %       82,6 %          5,23
#
# Le découpage ne s'applique QUE s'il trouve plusieurs clauses : les 275 sondes
# mono-clause suivent le chemin d'avant, à l'identique, sans marge ni cap. Un
# gain de 8,7 points sur les composites ne vaudrait pas de payer une régression,
# même petite, sur le cas courant.
_COUPE_CLAUSES = re.compile(r"\s+(?:et|puis|ensuite|then)\s+|\s*[;,]\s*", re.I)
# En deçà, ce n'est pas une clause mais un fragment (« et toi », « puis ça ») :
# l'embedder n'en tire rien et le bruit coûterait un groupe.
_CLAUSE_MIN_CHARS = 7
# Marge de distance RELATIVE au meilleur groupe de la clause. Les distances se
# tassent entre 0,67 et 0,90 sur ce corpus : un seuil absolu ne sépare rien,
# une marge relative si.
# INERTE sur le corpus réel : balayée de 0,10 à 0,30, le rappel ne bouge pas
# (93,0 %) et la largeur non plus. Elle ne discrimine que sur les requêtes
# multi-clauses, trop peu nombreuses ici pour peser. Gardée faute d'une raison de
# la changer, pas parce qu'un chiffre la défend.
#     python outils/mesure_routage.py --constantes
_MARGE_CLAUSE = 0.20
# Plafond de l'union. Une requête à deux intentions a besoin de deux domaines,
# donc de plus de cinq groupes ; 8 est le point où le rappel multi-clauses cesse
# de progresser franchement (82,6 % à 8, 87,0 % à 10 pour deux groupes de plus).
# Balayé : 5 et 6 coûtent 3,5 et 1,8 point ; 10 et 12 ne rendent rien.
#     python outils/mesure_routage.py --constantes
_MAX_GROUPES_UNION = 8

# Plafond d'outils liés, épinglés compris. OpenAI recommande moins de 20 au
# début d'un tour ; au-delà, la capacité du modèle à choisir se dégrade.
#
# RESTE À 16, et c'est un résultat, pas un statu quo. Balayé le 6 septembre 2026
# sur le corpus réel — 98 requêtes, séparées en réglage et tenu à l'écart —
# 12 y est indiscernable de 16 :
#
#     budget   rappel réglage   rappel TENU   outils liés
#         10          89,5 %         92,7 %          10,0
#         12          93,0 %         95,1 %          12,0
#         16          93,0 %         95,1 %          15,8   ← en place
#
# Descendu à 12, TROIS tests de non-régression tombent — dont deux formulations
# que le corpus réel ne contient pas : « ou en est ma copie de travail » pour
# `git_status`, « balance ca dans le channel dev » pour Slack. Le corpus de
# `tests/test_tool_routing.py` est plus large que celui de `CORPUS-ROUTAGE.md`
# sur ces tournures.
#
# Les quatre outils supplémentaires achètent donc une assurance que le corpus
# réel ne mesure pas. Un balayage sur un seul corpus aurait fait expédier la
# baisse comme gratuite : c'est la même leçon que les deux jeux, à l'échelle des
# corpus au lieu des requêtes.
#
#     python outils/mesure_routage.py --constantes
_BUDGET_OUTILS = 16

# Familles retenues dans un groupe qui en déclare. Deux, pas une : une
# demande porte souvent sur un acte et sa donnée — les cotes ET le pari.
# Balayé : 2 et 3 ne rendent aucun rappel et élargissent la sélection.
#     python outils/mesure_routage.py --constantes
_FAMILLES_MAX = 1

# Ce que la porte d'écriture met à portée. `propose_file_change` accompagne
# `edit_file` : le second refuse un fichier absent en renvoyant vers le premier.
_OUTILS_ECRITURE = ("edit_file", "propose_file_change", "propose_file_delete")

# Rang attribué à un groupe seulement INDIQUÉ par un mot souple. Assez bas
# pour passer les seuils `requires_top_rank` les plus courants, assez haut
# pour ne jamais primer sur ce que le sémantique a élu.
_RANG_INDICE = 4
_GROUP_SOURCE, _TOOL_SOURCE = "group", "tool"


_CACHE_DIR  = _chemins.index_outils()
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
        return self._rank_groups_detaille(query)[0]

    def _rank_groups_detaille(self, query: str) -> tuple[list[str], dict[str, int]]:
        """Le classement, plus le RANG retenu pour chaque groupe.

        Le rang est celui de la meilleure clause où le groupe apparaît, jamais sa
        position dans l'union. C'est ce qui garde `requires_top_rank` fidèle à son
        sens sous le découpage : le seuil dit « ce groupe doit être fortement
        impliqué », et l'être dans la seconde moitié de la phrase compte autant
        que dans la première. Sans cela, « lis le README et corrige le bug »
        placerait `coding` au rang 4 de l'union et son seuil de 3 l'écarterait,
        alors que la seconde clause l'élit en tête.
        """
        nommes = _keyword_groups(query)
        ordre: list[str] = list(nommes)
        rangs: dict[str, int] = {g: 1 for g in nommes}

        # Les indices n'entrent qu'APRÈS ce que le sémantique aura élu : ils
        # rendent le groupe joignable sans lui donner la priorité. Placés ici en
        # tête, ils reproduiraient le défaut qu'ils corrigent.
        indices = [g for g in _soft_keyword_groups(query) if g not in rangs]

        morceaux = _clauses(query)
        compose = bool(morceaux)

        # Ce que chaque clause élit, gardé SÉPARÉMENT avant d'être fusionné.
        par_clause: list[list[str]] = []
        for clause in (morceaux or [query]):
            docs = self._store.similarity_search_with_score(
                clause, k=_TOP_GROUPS, filter={"source": _GROUP_SOURCE})
            if not docs:
                continue
            seuil = docs[0][1] + _MARGE_CLAUSE
            elus: list[str] = []
            for rang, (doc, score) in enumerate(docs, start=1):
                if compose and score > seuil:
                    break
                groupe = doc.metadata.get("group")
                if not groupe:
                    continue
                rangs[groupe] = min(rangs.get(groupe, rang), rang)
                elus.append(groupe)
            par_clause.append(elus)

        # Fusion À TOUR DE RÔLE : le premier choix de CHAQUE clause, puis le
        # deuxième de chacune, et ainsi de suite.
        #
        # Concaténer clause par clause donnait tout le budget aux premières.
        # Vécu : « …le rag en détail, pas en dev en prod, ce qui change du dev
        # et me schématiser tout ça » — les deux premières clauses remplissaient
        # les 8 places, et `diagrams`, pourtant élu au rang 2 par la dernière,
        # était coupé. Le modèle n'avait tout simplement pas l'outil de schéma.
        #
        # Une clause est une intention : aucune ne doit se servir deux fois
        # avant que les autres se soient servies une fois.
        for tour in range(_TOP_GROUPS):
            for elus in par_clause:
                if tour < len(elus) and elus[tour] not in ordre:
                    ordre.append(elus[tour])

        for groupe in indices:
            if groupe not in ordre:
                ordre.append(groupe)
                rangs[groupe] = _RANG_INDICE

        if morceaux:
            ordre = ordre[:_MAX_GROUPES_UNION]
        return ordre, rangs

    def _tools_of(self, group: str, query: str) -> list[str]:
        """Étage 2 : les outils du groupe, CLASSÉS. Le budget coupe dans cette
        liste, donc l'ordre décide de ce qui est lié — plus seulement de ce qui
        entre dans un top-k.

        Similarité et non MMR : le MMR diversifie, ce qui est exactement l'inverse
        du besoin quand on ne garde que les premiers. Vérifié — les deux donnaient
        le même ordre sur les cas testés, et la diversité n'a plus de rôle depuis
        que le budget répartit entre groupes."""
        spec = TOOL_GROUPS[group]
        flt = {"$and": [{"source": _TOOL_SOURCE}, {"group": group}]}
        vise = len(spec.tools)
        # Le pont FR→EN, ici comme sur le chemin MCP. Le groupe est déjà trouvé ;
        # ce qui reste à trancher est le VERBE, et c'est là que le français et
        # l'anglais divergent : « envoie le recap dans le salon » classait
        # `slack_send_message` 6e de son propre groupe, derrière trois outils de
        # lecture. Avec le pont : 1er. L'embedding dense ne sépare pas les verbes
        # d'une même famille — `calendar_delete_event` sort avant
        # `calendar_create_event` sur « crée un événement ».
        texte = pont_linguistique(query)
        try:
            docs = self._store.similarity_search(texte, k=vise, filter=flt)
        except Exception:
            docs = []
        classes = unique(d.metadata.get("tool_name") for d in docs)
        # Un outil absent de l'index (fraîchement ajouté) ne doit pas disparaître :
        # il passe en queue plutôt que d'être perdu.
        classes = classes + [t for t in spec.tools if t not in classes]
        # Les familles se choisissent sur le classement BRUT. La tête est
        # appliquée après : posée avant, elle mettait ses propres outils au rang 1
        # et 2, donc leurs familles gagnaient toujours — les huit demandes de
        # paris testées rendaient les deux mêmes outils, « analyse la forme de
        # Liverpool » comprise. Une tête déclare ce qu'on garde, pas ce qui est
        # pertinent.
        if spec.capabilities:
            classes = _familles_visees(spec, classes)
        return ([t for t in spec.tete if t in classes]
                + [t for t in classes if t not in spec.tete])

    #: Le groupe élu au rang 1 du dernier `get()`. Exposé parce que l'appelant en
    #: a besoin et que le recalculer coûterait une recherche vectorielle de plus
    #: par tour. Même forme que `graph._last_selected_tools`.
    groupe_de_tete: str | None = None

    def get(self, query: str) -> list:
        ranked, rangs = self._rank_groups_detaille(query)
        self.groupe_de_tete = ranked[0] if ranked else None
        groups = ranked + [g for g in _PINNED_GROUPS if g not in ranked]

        # Les trois portes déterministes, au même endroit et au même titre :
        # `quant`, `coding`, `cron`. Chacune rattrape ce que le sémantique rate
        # sur son domaine, et aucune ne retire quoi que ce soit.
        #
        # Une porte qui s'ouvre POSE le rang 1 au lieu de préfixer la liste.
        # Préfixer suffisait tant que le rang ÉTAIT la position dans la liste :
        # une porte qui ajoutait son groupe en queue le plaçait au rang 6 ou
        # plus, et `requires_top_rank` l'écartait aussitôt — le filet devenait
        # silencieusement inopérant. Maintenant que le rang vient de la clause
        # d'origine, l'écrire est le seul geste qui dise « fortement impliqué ».
        for ouverte, groupe in ((_money_intent(query), _MONEY_GROUP),
                                (_coding_intent(query), _CODING_GROUP),
                                (_recurrence_intent(query), _CRON_GROUP)):
            if not ouverte:
                continue
            rangs[groupe] = 1
            if groupe not in groups:
                groups = [groupe] + groups

        selected: set[str] = set(_PINNED_TOOLS)
        # Posés AVANT le budget, comme les épinglés : ils doivent tenir leur place,
        # pas la disputer à cinq outils de lecture qui les devancent toujours.
        # Le retrait qui suit, quand `coding` gagne l'étage 1, les reprend — c'est
        # voulu : le specialist gère lui-même ses fichiers.
        if _ecriture_intent(query):
            selected.update(_OUTILS_ECRITURE)
        files: list[list[str]] = []
        for position, group in enumerate(groups, start=1):
            seuil = TOOL_GROUPS[group].requires_top_rank
            if seuil is not None and rangs.get(group, position) > seuil:
                continue
            files.append(self._tools_of(group, query))

        # Le BUDGET, et non l'union. Unir les groupes entiers liait 26,6 outils en
        # moyenne, jusqu'à 47 — au-dessus des 20 recommandés par OpenAI et très
        # au-dessus des 3-5 d'Anthropic. Ce n'est pas qu'une question de tokens :
        # différer les outils AMÉLIORE la précision du choix (49 -> 74 % mesuré
        # par Anthropic sur Opus 4). Un outil manquant, lui, reste réclamable au
        # catalogue — c'est ce filet qui rend le resserrement acceptable.
        #
        # Tourniquet et non concaténation : sans lui, le premier groupe mange tout
        # le budget et les intentions suivantes n'ont plus rien, exactement comme
        # les clauses avant leur propre tourniquet.
        for tour in range(max((len(f) for f in files), default=0)):
            for elus in files:
                if len(selected) >= _BUDGET_OUTILS:
                    break
                if tour < len(elus):
                    selected.add(elus[tour])
            if len(selected) >= _BUDGET_OUTILS:
                break

        # Le specialist gère lui-même les fichiers et git : les lui laisser évite
        # que l'orchestrateur commence le travail au lieu de déléguer. Seulement
        # quand `coding` gagne l'étage 1, pas dès qu'il apparaît — « lis le fichier
        # src/main.py » élit `filesystem` en tête et `coding` en second, et perdait
        # alors l'outil de lecture qu'il venait de trouver.
        #
        # C'est un INDICE, pas une barrière, et il faut le savoir avant de s'y
        # fier : le `ToolNode` est construit sur les 105 outils, pas sur la
        # sélection du tour, et le catalogue montre au modèle tous les noms.
        # Mesuré sur gpt-oss:120b — demande claire, outil retiré de la liaison :
        # il l'appelle DIRECTEMENT depuis le catalogue et l'appel s'exécute.
        # Pour interdire vraiment, il faut retirer du CATALOGUE, comme le font
        # `BLOCKED_TOOLS` en mode plan et `_EXPLORATION` en délégation.
        if ranked and ranked[0] == "coding":
            for group in ("git", "filesystem"):
                selected -= set(TOOL_GROUPS[group].tools)

        return [t for t in self._tools if t.name in selected]
