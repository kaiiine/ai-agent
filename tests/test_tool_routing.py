"""Non-régression du routing à deux étages (src/orchestrator/tool_retriever.py).

Deux jeux, deux rôles distincts.

`REFERENCE` — 22 requêtes formulées comme un utilisateur les écrit. C'est le jeu
qui décide : chacune doit aboutir à l'outil attendu DANS LA SÉLECTION FINALE.

`CORPUS` — les 298 phrases qui servaient d'ancres d'indexation avant la refonte.
Elles ne sont plus indexées ; elles sont devenues des sondes. Deux précautions
sur leur lecture :

  - le score n'est PAS comparable à celui de l'ancien système, qui contenait ces
    phrases mêmes comme documents et les retrouvait donc par construction ;
  - beaucoup sont des fragments sans objet (« alerte si », « dessine moi ça »),
    écrits pour être matchés, pas pour être des requêtes. Vérifié : les compléter
    en phrases ne les rattrape presque pas (1/12 → 4/12), donc les échecs sont
    réels — mais le seuil reste un PLANCHER DE RÉGRESSION mesuré, pas une cible.

Le seuil global est doublé de seuils par groupe : une moyenne peut rester belle
pendant qu'un groupe s'effondre.
"""

from __future__ import annotations

import pytest

from src.orchestrator.registry import build_all_tools
from src.orchestrator.tool_retriever import TOOL_GROUPS, ToolRetriever, _TOP_GROUPS


# ── jeu de référence : requête → outil attendu dans la sélection ────────────────
REFERENCE = [
    ("corrige le bug dans mon application next.js",        "run_coding_agent"),
    ("cree une landing page pour ma startup",              "run_coding_agent"),
    ("modelise un igloo dans blender",                     "load_skill"),
    ("fais moi un rendu 3d de cette scene",                "load_skill"),
    ("cherche sur internet les nouveautes de python 3.13", "web_research_report"),
    ("quelles sont les actualites tech aujourd'hui",       "web_search_news"),
    ("fais moi un recap tous les jours a 14h",             "schedule_task"),
    ("rappelle moi dans 2 heures",                         "schedule_task"),
    ("quels sont mes fichiers modifies en ce moment",      "git_status"),
    ("montre moi le dernier commit",                       "git_log"),
    ("lis le fichier src/main.py",                         "local_read_file"),
    ("telecharge le contenu de cette page web",            "url_fetch"),
    ("envoie un message sur le canal test-cron",           "slack_send_message"),
    ("quels tickets jira me sont assignes",                "jira_get_my_issues"),
    ("y a-t-il de bons paris a faire ce soir",             "winamax_odds_fetch"),
    ("fais moi un schema de l'architecture",               "mermaid_diagram"),
    ("quel temps fait-il a paris",                         "get_weather_by_city"),
    ("resume mes derniers mails",                          "gmail_summarize"),
    ("mes rendez vous de demain",                          "calendar_list_events"),
    ("prends une capture d'ecran",                         "screenshot_take"),
    ("cherche un papier arxiv sur les transformers",       "arxiv_search"),
    ("note ca dans ta memoire projet",                     "axon_note"),
]

# ── corpus : phrase → groupe attendu à l'étage 1 ────────────────────────────────
CORPUS: dict[str, list[str]] = {
    "coding": [
        "modifier du code dans un projet local",
        "corriger un bug dans mon application",
        "corriger une erreur ou un comportement inattendu",
        "fixer un problème dans mon code",
        "déboguer un crash ou une exception",
        "trouver pourquoi mon code ne fonctionne pas",
        "réparer une régression introduite récemment",
        "résoudre un conflit de dépendances dans le projet",
        "ajouter une nouvelle fonctionnalité à un projet",
        "implémenter une nouvelle route dans mon API",
        "créer un nouveau composant, fichier ou page",
        "ajouter un bouton, un formulaire ou un élément UI",
        "intégrer une librairie externe dans le projet",
        "brancher une API tierce dans mon application",
        "mettre en place un système d'authentification",
        "ajouter des tests unitaires ou d'intégration",
        "écrire des tests pour couvrir mon code",
        "refactoriser un module, une classe ou une fonction",
        "réorganiser la structure des fichiers du projet",
        "découper un fichier trop long en plusieurs modules",
        "renommer des variables, fonctions ou fichiers",
        "supprimer du code mort ou des imports inutilisés",
        "migrer vers une nouvelle version d'un framework",
        "convertir du code JavaScript en TypeScript",
        "remplacer une dépendance obsolète par une alternative",
        "refaire l'interface utilisateur d'une application web",
        "améliorer le design ou le style d'un projet",
        "rendre l'application responsive ou mobile-friendly",
        "changer le thème, les couleurs ou la typographie",
        "corriger un problème d'affichage ou de layout",
        "animer un composant ou ajouter des transitions",
        "améliorer l'accessibilité de l'interface",
        "expliquer comment fonctionne le code d'un repo",
        "analyser la structure du code et proposer des améliorations",
        "faire un code review d'un projet et dire ce qui peut être amélioré",
        "lire les fichiers du projet et résumer l'architecture",
        "identifier les parties les plus complexes du code",
        "comprendre ce que fait un fichier ou une fonction",
        "documenter le code avec des commentaires ou un README",
        "générer la documentation d'une fonction ou d'une classe",
        "optimiser les performances d'un projet existant",
        "réduire le temps de chargement ou la consommation mémoire",
        "identifier et corriger des fuites mémoire",
        "améliorer la sécurité du code",
        "mettre en place du linting ou du formatage automatique",
        "configurer ESLint, Prettier, Black ou un autre linter",
        "améliorer le score Lighthouse d'une application web",
        "modifier la configuration du projet",
        "mettre à jour le fichier de configuration webpack, vite ou autre",
        "configurer les variables d'environnement",
        "créer ou modifier un Dockerfile ou docker-compose",
        "mettre en place une CI/CD pipeline",
        "configurer les scripts npm, yarn ou makefile",
        "initialiser un nouveau projet from scratch",
        "aller dans mon repo et faire des changements",
        "lire et modifier les fichiers d'un projet",
        "parcourir les fichiers d'un dossier et m'en expliquer le contenu",
        "chercher où est définie une fonction ou une classe dans le projet",
        "trouver tous les endroits où une variable est utilisée",
        "lister les dépendances du projet",
        "créer une landing page ou un site vitrine",
        "construire une application web de zéro",
        "initialiser un projet Next.js, React, Vue ou Svelte",
        "créer une app Next.js from scratch",
        "bootstrapper un nouveau projet front-end",
        "créer un site web pour un client ou un projet",
        "mettre en place un projet front-end",
        "créer un dossier et initialiser un projet",
        "créer un nouveau dossier et installer une app",
        "init git et créer une application",
        "site vitrine pour une startup ou un produit",
        "landing page d'un SaaS ou d'un produit",
        "page d'accueil d'une application web",
        "créer un site web moderne et épuré",
    ],
    "cron": [
        "surveille toutes les X minutes",
        "rappelle-moi dans",
        "chaque matin / soir",
        "notifie-moi si",
        "vérifie périodiquement",
        "alerte si",
        "tâche planifiée cron",
        "fais-le tous les jours",
        "tous les jours à la même heure",
        "chaque jour à 14h",
        "tous les jours à 9h du matin",
        "quotidiennement",
        "un récapitulatif quotidien",
        "un rapport tous les jours",
        "envoie-moi ça chaque jour",
        "en commençant par aujourd'hui puis chaque jour",
        "toutes les semaines",
        "chaque lundi",
        "de façon récurrente",
        "automatiquement à heure fixe",
        "programme une tâche récurrente",
        "planifie cette tâche",
        "mets ça en place tous les jours",
        "suivi quotidien automatique",
        "surveille en continu et préviens-moi",
        "every day at 2pm",
        "daily report",
        "schedule this task",
        "run this every day",
        "recurring task",
        "remind me every morning",
    ],
    "diagrams": [
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
    "jira": [
        "quels tickets jira me sont assignés",
        "voir mes tâches jira",
        "ce que j'ai à faire sur jira",
        "mon backlog jira",
        "mes issues en cours",
        "tickets assignés à moi",
        "qu'est-ce que j'ai à faire cette semaine sur jira",
        "avancement du projet sur jira",
        "état d'un projet jira",
        "progression du projet",
        "combien de tickets sont terminés dans le projet",
        "résumé du projet jira",
        "bilan du projet en cours",
        "vue d'ensemble du projet",
        "tickets du sprint actif",
        "ce qui est dans le sprint courant",
        "sprint en cours sur jira",
        "tâches du sprint actuel",
        "tickets en cours dans le sprint",
        "qui fait quoi dans l'équipe",
        "charge de travail par développeur",
        "répartition des tickets dans l'équipe",
        "qui a le plus de tickets assignés",
        "workload de l'équipe sur jira",
        "marquer un ticket jira comme terminé",
        "passer un ticket en cours",
        "changer le statut d'un ticket jira",
        "fermer un ticket jira",
        "mettre un ticket en done",
        "créer un ticket jira",
        "ouvrir une nouvelle tâche sur jira",
        "ajouter un ticket dans le projet",
        "créer un bug, une story ou une tâche jira",
        "nouveau ticket jira",
        "ajoute ce ticket dans mon projet jira",
        "mets ça dans jira",
        "créer plusieurs tickets jira en une fois",
        "importer une liste de tickets dans jira",
        "ajouter plusieurs user stories dans le projet",
        "mettre en place le backlog jira",
        "créer tous ces tickets dans mon projet",
        "mets moi tous ces tickets dans jira",
        "importer des tâches en masse dans jira",
        "créer un backlog complet dans jira",
    ],
    "news": [
        "qu'est-ce qui s'est passé aujourd'hui",
        "actualité du jour",
        "dernières nouvelles sur un sujet",
        "news récentes",
        "événements de cette semaine",
        "ce qui s'est passé hier",
        "quoi de neuf sur ce sujet",
        "dernières infos",
        "résultats des matchs hier",
        "score du match de foot",
        "résultat sportif récent",
        "qui a gagné le match",
        "classement actuel",
        "résultats championnat",
        "dernière annonce d'une entreprise",
        "news sur Apple Google Microsoft OpenAI",
        "sortie d'un nouveau produit",
        "mise à jour récente d'une application",
        "levée de fonds annoncée",
        "actualité politique récente",
        "élections résultats",
        "discours d'un dirigeant",
        "crise ou conflit en cours",
        "décision gouvernementale récente",
    ],
    "quant": [
        "il y a un coup à jouer sur ce match",
        "quelles sont les cotes du match",
        "analyse ce pari sportif",
        "ça vaut le coup de parier sur",
        "prono pour le match de ce soir",
        "value bet sur ce match",
        "compare ces combinés",
        "le pari est-il intéressant",
        "cote winamax",
        "y a-t-il de bons paris à faire en ce moment",
        "y a-t-il de bons paris sportifs à faire",
        "des paris intéressants aujourd'hui",
        "qu'est-ce qui se joue en ce moment côté paris",
        "des matchs à parier ce soir",
        "quelle est la probabilité que cette équipe gagne",
        "calcule les chances de victoire",
        "estime la probabilité du match",
        "qui va gagner selon les stats",
        "quelle est la forme récente de cette équipe",
        "historique des confrontations entre ces deux équipes",
        "comment se porte cette équipe en ce moment",
        "est-ce que ce pari a de la valeur",
        "calcule l'espérance de gain de ce pari",
        "combien miser sur ce pari",
        "ce pari est-il rentable sur le long terme",
        "analyse mon combiné de paris",
        "est-ce que ce combiné vaut le coup",
        "compare ces paris combinés entre eux",
        "combiné sur le même match",
        "victoire et plus de 2.5 buts dans le même match",
        "double pari sur un seul match",
    ],
    "search": [
        "cherche sur internet",
        "fais une recherche sur ce sujet",
        "recherche des informations sur le web",
        "trouve des infos en ligne sur",
        "cherche la documentation de",
        "recherche web approfondie",
        "renseigne-toi sur",
        "trouve la réponse sur internet",
        "vérifie sur le web",
        "cherche des sources sur",
        "donne-moi des informations sur ce sujet",
        "fais une veille sur",
        "cherche ce terme sur internet",
        "qu'est-ce que dit internet sur",
        "googler ce sujet",
        "que sait-on sur ce sujet en ligne",
        "search the web for",
        "look it up online",
        "find information about",
        "research this topic",
        "web search",
        "search online",
    ],
    "shell": [
        "lance cette commande pour moi",
        "exécute cette commande",
        "fais tourner ce script",
        "lance les commandes nécessaires",
        "fais le toi même via le terminal",
        "run this command",
        "execute this",
        "run it yourself",
        "regarde toi-même sur mon système",
        "vérifie par toi-même",
        "inspecte ma machine",
        "dis-moi ce que tu vois",
        "explore mon système",
        "fais les vérifications nécessaires",
        "qu'est-ce qui se passe sur mon système",
        "analyse ma machine par toi-même",
        "regarde sur mon ordinateur",
        "dis-moi ce qui se passe chez moi",
        "regarde toi même tu peux faire les commandes",
        "look at my system yourself",
        "check what's happening on my machine",
        "analyze my system",
        "investigate on my computer",
        "tell me what you find on my system",
        "go look yourself",
    ],
    "skills": [
        "crée une scène 3D dans blender",
        "modélise un objet en 3D",
        "fais-moi une scène qui bouge pour mon site",
        "ajoute une lumière et une caméra à la scène",
        "exporte la scène en GLB",
        "anime un objet dans blender",
        "fais un rendu 3D",
        "mets ce logo en 3D",
    ],
    "slack": [
        "envoie un message sur le canal",
        "poste ça sur le canal",
        "écris sur le canal",
        "envoie-moi ça sur le channel",
        "publie le rapport sur le canal",
        "fais un retour sur le canal",
        "préviens l'équipe sur le canal",
        "envoie le récap dans le salon",
        "poste le résultat dans la conversation",
        "envoie un message à cette personne",
        "send a message to the channel",
        "post this in the channel",
        "notify the team on slack",
    ],}

# Planchers mesurés le 2026-08-04 (_TOP_GROUPS = 5) : 241/298 au global, et le
# détail par groupe ci-dessous. Ils descendent d'un ou deux crans sous la mesure
# pour absorber le bruit d'un ré-embedding, pas pour tolérer une dérive.
_MIN_GLOBAL = 0.78
_MIN_PER_GROUP = {
    "coding": 0.65, "cron": 0.60, "diagrams": 0.55, "jira": 0.85,
    "news": 0.90, "quant": 0.85, "search": 0.85, "shell": 0.80,
    "skills": 0.85, "slack": 1.0,
}


@pytest.fixture(scope="module")
def retriever(tmp_path_factory):
    """Index ISOLÉ : un test qui écrit dans ~/.axon/tool_store écraserait le cache
    de l'utilisateur et ferait dépendre son démarrage du dernier test lancé."""
    from src.orchestrator import tool_retriever as module

    store = tmp_path_factory.mktemp("tool_store") / "store"
    module._CACHE_DIR, module._CACHE_HASH = store, store / "fingerprint.txt"
    return ToolRetriever(build_all_tools())


# ── ce qui décide ───────────────────────────────────────────────────────────────
def test_jeu_de_reference_complet(retriever):
    """L'outil attendu doit être dans la sélection — pas « bien classé »: un outil
    non sélectionné n'est pas lié au modèle, donc il n'existe pas."""
    manquants = [(q, tool) for q, tool in REFERENCE
                 if tool not in {t.name for t in retriever.get(q)}]
    assert not manquants, "requêtes sans leur outil : " + "; ".join(
        f'"{q}" → {t}' for q, t in manquants)


def test_aucune_domination_par_cardinalite(retriever):
    """LE défaut qui a motivé la refonte : `run_coding_agent` portait 74 des 388
    documents indexés et remontait sur 10 des 20 requêtes non-coding. Le routing
    par groupe le rend structurellement impossible — un groupe pèse un document,
    quel que soit le nombre d'outils ou de formulations derrière lui."""
    intrus = [q for q, tool in REFERENCE
              if tool != "run_coding_agent"
              and "run_coding_agent" in {t.name for t in retriever.get(q)}]
    assert len(intrus) <= 2, f"coding s'invite dans {len(intrus)} requêtes : {intrus}"


@pytest.mark.parametrize("query,tool", [
    ("quels sont mes fichiers modifies en ce moment", "git_status"),
    ("lis le fichier src/main.py",                    "local_read_file"),
    ("telecharge le contenu de cette page web",       "url_fetch"),
    ("note ca dans ta memoire projet",                "axon_note"),
])
def test_les_outils_sans_ancre_sont_retrouvables(retriever, query, tool):
    """Ces quatre-là échouaient avant la refonte, chacun pour une raison distincte :
    aucun n'avait d'ancre et ils affrontaient des outils qui en avaient 74."""
    assert tool in {t.name for t in retriever.get(query)}


def test_le_strip_coding_ne_se_declenche_qu_au_rang_1(retriever):
    """« lis le fichier src/main.py » élit `filesystem` en tête et `coding` plus
    bas : l'outil de lecture doit survivre. C'est le faux positif qui faisait
    perdre un outil retrouvé au rang 3."""
    assert "local_read_file" in {t.name for t in retriever.get("lis le fichier src/main.py")}
    codant = {t.name for t in retriever.get("refactorise entierement mon projet react")}
    assert "run_coding_agent" in codant
    assert not (codant & set(TOOL_GROUPS["filesystem"].tools)), \
        "quand coding gagne, le specialist gère les fichiers lui-même"


# ── corpus : plancher de régression, échecs nommés ──────────────────────────────
def test_corpus_par_groupe(retriever):
    """Un groupe qui s'effondre est masqué par une moyenne globale : on mesure
    groupe par groupe, et les phrases perdues sont listées, pas comptées."""
    rapport, sous_seuil = [], []
    total = reussis = 0
    for groupe, phrases in CORPUS.items():
        echecs = [p for p in phrases if groupe not in retriever._rank_groups(p)]
        ok = len(phrases) - len(echecs)
        total += len(phrases)
        reussis += ok
        taux = ok / len(phrases)
        if taux < _MIN_PER_GROUP[groupe]:
            sous_seuil.append(f"{groupe} {ok}/{len(phrases)} ({taux:.0%} < "
                              f"{_MIN_PER_GROUP[groupe]:.0%}) — perdues : {echecs[:5]}")
        rapport.append(f"{groupe} {ok}/{len(phrases)}")

    assert not sous_seuil, "groupes sous leur plancher :\n" + "\n".join(sous_seuil)
    assert reussis / total >= _MIN_GLOBAL, (
        f"corpus global {reussis}/{total} ({reussis/total:.1%}) < {_MIN_GLOBAL:.0%} — "
        + ", ".join(rapport))


def test_le_corpus_couvre_les_groupes_a_risque():
    """Le corpus ne vaut que par ce qu'il couvre : si un groupe historiquement
    fragile en sort, sa régression redevient invisible."""
    for groupe in ("coding", "cron", "diagrams", "news", "search", "quant"):
        assert len(CORPUS.get(groupe, [])) >= 8, f"couverture trop mince : {groupe}"
    assert set(CORPUS) <= set(TOOL_GROUPS), \
        f"corpus sur des groupes disparus : {sorted(set(CORPUS) - set(TOOL_GROUPS))}"


def test_top_groups_reste_le_reglage_mesure():
    """Le nombre de groupes retenus est un compromis mesuré (cf. le tableau dans
    tool_retriever.py). Le changer sans refaire la mesure casse les planchers
    ci-dessus — ce test rend le lien explicite plutôt qu'implicite."""
    assert _TOP_GROUPS == 5


# ── retriever du specialist : même classe de défaut, autre population ───────────
def test_aucun_outil_du_specialist_dans_deux_groupes():
    """`browser_screenshot` était déclaré dans `shell` ET dans `visual` : l'index
    inverse n'en garde qu'un, silencieusement. Il tirait donc mermaid et
    download_asset alors qu'une vérification visuelle a besoin du shell — on lance
    le dev server avant de regarder la page."""
    from src.agents.coding.tool_retriever import _TOOL_GROUPS

    declares = [n for names in _TOOL_GROUPS.values() for n in names]
    doublons = {n for n in declares if declares.count(n) > 1}
    assert not doublons, f"outils dans plusieurs groupes : {sorted(doublons)}"


def test_le_groupe_shell_ne_recrute_pas_par_voisinage_d_usage():
    """Ce test affirmait l'inverse — que `browser_screenshot` DEVAIT être dans le
    groupe `shell` — au motif que « screenshot sans shell_run, c'est regarder une
    page que l'on n'a pas pu démarrer ». Le besoin est réel ; le moyen était faux,
    et la mesure a montré le couplage dans le mauvais sens.

    `browser_screenshot` n'arrivait pas en passager d'une tâche de build : il en
    était la GRAINE. Ses ancres françaises (« voir ce que donne le site ») le
    faisaient remonter sur « crée la page d'accueil du site » et « corrige
    l'erreur de typage dans page.tsx » — deux tâches sans aucun shell — et il
    tirait les cinq outils du groupe derrière lui. Sur « installe framer-motion »,
    qui a pourtant un vrai besoin de shell, celui-ci arrivait par le même
    accident, masquant que `shell_run` n'y remontait pas de lui-même.

    Le besoin d'origine — piloter un navigateur exige de pouvoir démarrer le
    serveur — reste entier et n'est PAS satisfait aujourd'hui. Il est mesuré et
    suivi par `test_piloter_un_navigateur_devrait_donner_un_shell` dans
    tests/test_mcp_routing_specialist.py, qui appartient au couplage dev-server.
    """
    from src.agents.coding.tool_retriever import _TOOL_GROUPS

    intrus = [o for o in _TOOL_GROUPS["shell"] if not o.startswith("shell_")]
    assert not intrus, f"recrutés par voisinage d'usage, pas par nature : {intrus}"


# ── étage 1 hybride : un groupe NOMMÉ ne dépend pas d'un rang vectoriel ─────────
@pytest.mark.parametrize("query,groupe", [
    ("envoie ça à Nicolas sur Slack",                    "slack"),
    ("peux tu envoyer tout ça à Nicolas sur Slack stp",  "slack"),
    ("ajoute ce ticket dans jira",                       "jira"),
    ("quelle est la météo demain",                       "weather"),
    ("fais moi un diagramme mermaid",                    "diagrams"),
    ("quelles sont les cotes winamax",                   "quant"),
])
def test_un_groupe_nomme_litteralement_est_toujours_elu(retriever, query, groupe):
    """Régression vécue : « envoie ça à Nicolas sur Slack » classait `slack` 17e sur
    22 — derrière `news` et `quant` — alors que la description du groupe commence
    par le mot « Slack ». L'agent répondait « je ne dispose pas d'une intégration
    Slack », ce qui est faux, et proposait un copier-coller.

    L'embedder dilue un terme rare dans une phrase courte et banale. La
    correspondance exacte ne le rate jamais : c'est le cas le plus certain qui
    soit, et c'était le seul à échouer."""
    assert groupe in retriever._rank_groups(query)


def test_le_lexical_n_ecrase_pas_le_semantique(retriever):
    """Le lexical AJOUTE, il ne remplace pas : une demande sans terme propre doit
    continuer de passer par la similarité."""
    from src.orchestrator.tool_retriever import _keyword_groups

    query = "quels sont mes rendez vous de demain"
    assert not _keyword_groups(query), "aucun terme propre attendu ici"
    assert "calendar" in retriever._rank_groups(query)


def test_les_mots_cles_matchent_des_mots_entiers(retriever):
    """« paris » ne doit pas être trouvé dans « comparaison », ni « ip » dans
    « équipe » : une sous-chaîne élirait un groupe sans rapport, et le lexical
    deviendrait une source de bruit au lieu d'une garantie."""
    from src.orchestrator.tool_retriever import _keyword_groups

    assert "quant" not in _keyword_groups("fais une comparaison des options")
    assert "network" not in _keyword_groups("la composition de l'équipe")
    assert "quant" in _keyword_groups("des paris intéressants ce soir")


def test_aucun_mot_cle_n_est_revendique_par_deux_groupes():
    """Un terme ambigu élirait deux groupes à chaque fois qu'il apparaît, et la
    garantie deviendrait du bruit."""
    from collections import Counter

    from src.orchestrator.tool_retriever import TOOL_GROUPS

    compte = Counter(k for spec in TOOL_GROUPS.values() for k in spec.keywords)
    doublons = {k: n for k, n in compte.items() if n > 1}
    assert not doublons, f"mots-clés revendiqués par plusieurs groupes : {doublons}"


# ── Pont linguistique FR → EN ───────────────────────────────────────────────
#
# Les descriptions d'outils MCP viennent de leurs serveurs, en anglais ; les
# tâches de phase d'AXON sont en français. Mesuré sur sept requêtes de lecture
# d'état : français 2/7, anglais 7/7. Les verbes d'action ont leur cognat
# (execute/exécute, generate/génère) ; les tournures interrogatives n'en ont pas.
def test_le_pont_traduit_les_intentions_pas_les_outils():
    """Mettre un nom de serveur ou d'outil dans le pont le rendrait dépendant
    de ce qui est installé, et il faudrait le rouvrir à chaque nouveau MCP."""
    from src.agents.coding.tool_retriever import _PONT_FR_EN

    interdits = ("blender", "motion", "scene_info", "polyhaven", "sketchfab")
    contenu = " ".join(_PONT_FR_EN.keys()) + " " + " ".join(_PONT_FR_EN.values())
    for mot in interdits:
        assert mot not in contenu.lower(), f"« {mot} » lie le pont à un serveur"


def test_le_pont_ajoute_sans_remplacer():
    """La requête française porte les noms propres et le vocabulaire technique
    (« blender », « framer-motion », « GLB ») que traduire perdrait."""
    from src.agents.coding.tool_retriever import _pont_linguistique

    enrichie = _pont_linguistique("dis-moi ce que contient la scène blender")

    assert "blender" in enrichie
    assert "dis-moi" in enrichie
    assert "get information" in enrichie


def test_une_requete_sans_intention_connue_reste_intacte():
    from src.agents.coding.tool_retriever import _pont_linguistique

    assert _pont_linguistique("crée le composant Header") == "crée le composant Header"


def test_le_pont_ne_duplique_pas_les_termes():
    from src.agents.coding.tool_retriever import _pont_linguistique

    enrichie = _pont_linguistique("dis-moi quel est le statut et donne-moi l'état")
    apres = enrichie.split("|", 1)[1].split()

    assert len(apres) == len(set(apres))
