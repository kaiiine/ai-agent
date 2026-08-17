"""Le sélecteur d'outils du specialist face aux serveurs MCP.

Ce jeu existe parce qu'un raisonnement architectural propre a failli casser le
routage. La décision « aligner `specialist.py` sur `graph.py`, coût quasi nul »
était une ESTIMATION ; mesurée, elle coûtait 9 cas sur 23. Sans ce fichier, la
prochaine personne qui touche à l'un des deux chemins refera le raisonnement,
pas la mesure.

MESURES, le 16 août 2026, 82 outils (39 natifs + 43 MCP : Blender et Motion) :

    architecture                POS_MCP   NÉG_MCP   POS_NATIF   total
    index unique (actuel)         6/7      10/10       6/6      22/23
    deux voies (graph.py)         7/7       0/10       6/6      13/23

`mcp_runtime().select()` rend SEPT outils sur chaque requête, sans exception —
« montre-moi les fichiers modifiés dans le dépôt » comprise. Il ne discrimine
pas. Dans l'orchestrateur, sept outils de plus se noient dans une sélection
conversationnelle large ; dans le specialist ils sont liés à CHAQUE tour de
CHAQUE phase, et redeviennent le bruit permanent que le routage par groupe
(commit `0c9a03b`) avait éliminé.

Les deux chemins divergent donc pour une raison mesurée, pas par négligence.

Protocole : labels écrits AVANT exécution, depuis le contrat déclaré par le
serveur (`tools/list`) et jamais depuis le comportement observé ; requêtes
formulées comme un utilisateur les écrit, jamais recopiées d'une ancre indexée.
Les cinq requêtes « ambiguës » portent un mot du vocabulaire 3D — rendu, scène,
modélise, génère, anime — avec un sens front-end : c'est là qu'un index où MCP
pèse 31 % de la cardinalité devrait déraper.
"""

from __future__ import annotations

import pytest

# ── Labels, écrits avant toute exécution ────────────────────────────────────
POSITIFS_MCP = [
    ("exécute ce script python bpy dans la scène blender", "blender__execute_blender_code"),
    ("prends une capture du viewport blender", "blender__get_viewport_screenshot"),
    ("télécharge un modèle 3d depuis sketchfab", "blender__download_sketchfab_model"),
    ("génère un modèle 3d à partir d'une description texte",
     "blender__generate_hyper3d_model_via_text"),
    ("applique une texture polyhaven sur cet objet", "blender__set_texture"),
    ("modélise un igloo en 3d et exporte-le en glb", None),   # tout outil 3D convient
]

#: Cas témoin. Défaillant à la mesure du 16 août (aucun outil MCP remonté),
#: passant depuis le pont linguistique. Gardé nommément parce que c'est lui qui
#: a révélé toute la catégorie « lecture d'état ».
POSITIF_MCP_CONNU_DEFAILLANT = (
    "dis-moi ce que contient la scène blender actuelle", "blender__get_scene_info")

NEGATIFS_MCP = [
    # Sans ambiguïté
    "crée les sections hero et footer de la landing page",
    "lance les tests et corrige les erreurs de compilation",
    "ajoute une transition au scroll avec framer-motion",
    "écris le composant react du formulaire de contact",
    "montre-moi les fichiers modifiés dans le dépôt",
    # Ambigus : vocabulaire partagé avec la 3D, sens front-end
    "optimise le rendu de la page produit",
    "modélise les données du formulaire de contact",
    "génère les icônes svg du site",
    "anime cette page avec des transitions css",
    "construis la scène d'accueil du site",
]

POSITIFS_NATIFS = [
    ("lis le fichier src/app/page.tsx", "local_read_file"),
    ("montre-moi le dernier commit", "git_log"),
    ("note cette décision dans la mémoire projet", "axon_note"),
    # Mixtes : natif attendu, vocabulaire partagé avec la 3D
    ("fais une capture de la page d'accueil dans le navigateur", "browser_screenshot"),
    ("lis le fichier qui décrit la scène du hero", "local_read_file"),
    ("note la décision sur le rendu des animations", "axon_note"),
]


# ── Navigateur — labels écrits AVANT de brancher Playwright MCP ─────────────
#
# Playwright partage le vocabulaire front-end de l'agent code, ce que Blender ne
# faisait pas : « vérifie que la page s'affiche » et « écris le composant
# Header » se ressemblent bien plus que « rendu 3D » et « landing page ». Les
# NÉGATIFS de cette section sont donc la partie la plus susceptible de casser —
# c'est exactement ce type de pollution qui a fait chuter le score de 22/23 à
# 13/23 quand on avait tenté de router les MCP séparément.
POSITIFS_NAVIGATEUR = [
    "vérifie que la page d'accueil s'affiche dans le navigateur",
    "clique sur le menu hamburger et vérifie qu'il s'ouvre",
    "y a-t-il des erreurs dans la console du navigateur",
    "remplis le formulaire de contact et soumets-le",
]

#: Ceux-là ne doivent JAMAIS tirer d'outil navigateur : ils s'écrivent dans des
#: fichiers, ils ne se regardent pas dans un onglet. Le recouvrement lexical est
#: maximal — « page », « bouton », « formulaire » appartiennent aux deux mondes.
NEGATIFS_FRONT = [
    "écris le composant Header en react",
    "ajoute une classe tailwind à ce bouton",
    "crée la page d'accueil du site",
    "corrige l'erreur de typage dans page.tsx",
    "installe framer-motion et configure-le",
    "renomme le fichier du formulaire de contact",
]


def _outils_navigateur(noms: list[str]) -> list[str]:
    """Les outils PLAYWRIGHT, pas l'outil natif `browser_screenshot`.

    La distinction est essentielle et mesurée. `browser_screenshot` fuit déjà sur
    5 des 6 tâches d'écriture front-end — non par proximité sémantique, mais
    parce qu'il est déclaré dans le groupe `shell` : toute tâche qui installe,
    build ou lance quelque chose tire le groupe entier, lui compris.

    C'est un artefact de GROUPEMENT, antérieur à Playwright, et Playwright ne
    l'héritera pas : ses outils arrivent par le chemin MCP, routés par leur
    description, hors de tout groupe natif. Confondre les deux ferait attribuer
    à la bascule une fuite qu'elle n'a pas causée.
    """
    return [n for n in noms if n.startswith("playwright__")]


def test_les_requetes_de_verification_visuelle_atteignent_le_navigateur(selection):
    """Ce qui route le navigateur est le PONT LEXICAL, pas l'index.

    Playwright était joignable et exécutable, mais inatteignable en français :
    ses outils se décrivent en trois à cinq mots d'anglais (« Navigate to a
    URL »), donc 0/4 en français contre 5-8/8 en anglais.

    Indexer le `capabilities_hint` du serveur corrigeait ces 4 positifs et
    cassait les négatifs, dans les trois formes essayées — document composite
    (~10/16 pollués), découpé en capacités (~13/16), chaque capacité nommant
    « navigateur » (14/16, la pire : 9 ancres quasi-identiques, soit l'erreur du
    commit 0c9a03b refaite). Aucun seuil ne triait, les distributions se
    recouvrant : positifs [1, 1, 2, 2] graines contre négatifs [0, 0, 0, 1×9,
    2, 2, 2, 3].

    Le seuil est à 3 et non à 4 : « clique sur le menu hamburger » ne remonte
    rien, « menu » et « s'ouvre » dominant le seul mot ponté. C'est une limite
    connue, pas un test permissif.
    """
    reussis = sum(1 for r in POSITIFS_NAVIGATEUR if _outils_navigateur(selection(r)))
    assert reussis >= 3, f"rappel navigateur insuffisant ({reussis}/4)"


def test_ecrire_du_code_front_ne_tire_jamais_le_navigateur(selection):
    """Le garde le plus important de la bascule Playwright. Un composant
    s'écrit dans un fichier ; l'ouvrir dans un onglet ne le fait pas exister."""
    fuites = [(r, _outils_navigateur(selection(r))) for r in NEGATIFS_FRONT
              if _outils_navigateur(selection(r))]
    assert not fuites, f"fuite navigateur sur des tâches d'écriture : {fuites}"


#: Planchers de RÉGRESSION, pas des cibles. Mesurés le 16 août 2026.
_MIN_POSITIFS_MCP = 6      # sur 6 (hors cas connu défaillant)
_MIN_NEGATIFS_MCP = 10     # sur 10 — aucune fuite tolérée
_MIN_POSITIFS_NATIFS = 6   # sur 6


@pytest.fixture(scope="module")
def selection():
    """La sélection réelle du specialist, ou un skip si l'outillage manque.

    Les embeddings (`nomic-embed-text` via Ollama) et les serveurs MCP peuvent
    être absents d'une machine de CI. Un skip franc vaut mieux qu'un test vert
    qui n'a rien mesuré.
    """
    from src.agents.coding.specialist import _get_coding_tools
    from src.agents.coding.tool_retriever import CodingToolRetriever

    outils = _get_coding_tools()
    if not any("__" in t.name for t in outils):
        pytest.skip("aucun serveur MCP joignable — rien à mesurer")
    retriever = CodingToolRetriever(outils, k=8)
    if retriever._store is None:
        pytest.skip("embeddings indisponibles — sélection non mesurable")
    return lambda q: [t.name for t in retriever.get(q)]


def _outils_mcp(noms: list[str]) -> list[str]:
    return [n for n in noms if "__" in n]


# ── Ce qui doit remonter ────────────────────────────────────────────────────
def test_les_requetes_3d_atteignent_les_outils_mcp(selection):
    reussis = 0
    manques = []
    for requete, attendu in POSITIFS_MCP:
        noms = selection(requete)
        ok = (attendu in noms) if attendu else bool(_outils_mcp(noms))
        reussis += int(ok)
        if not ok:
            manques.append(requete)
    assert reussis >= _MIN_POSITIFS_MCP, f"rappel MCP en baisse — manqués : {manques}"


def test_la_lecture_d_etat_de_scene_remonte_l_outil(selection):
    """Défaillant jusqu'au pont linguistique, passant depuis. Voir
    `_PONT_FR_EN` dans tool_retriever.py : les descriptions MCP sont en anglais,
    les tâches de phase en français, et les tournures interrogatives n'ont
    aucun cognat."""
    requete, attendu = POSITIF_MCP_CONNU_DEFAILLANT
    assert attendu in selection(requete)


# ── Lecture d'état — le chantier qui était ouvert ───────────────────────────
#
# Mesuré le 16/08 : les requêtes d'ACTION passaient à 6/7, celles qui
# INTERROGENT à 2/8. Départage par la même question posée en anglais :
#
#     français 2/7   ·   anglais 7/7
#
# H1 (écart de langue) confirmée, H2 (concurrence entre outils voisins) réfutée.
# L'indice qu'on croyait pencher vers H2 — « combien de crédits » rendant UN
# mauvais outil plutôt que zéro — ne discriminait rien : ce cas passe en anglais.
LECTURE_D_ETAT = [
    ("dis-moi ce que contient la scène blender actuelle", "blender__get_scene_info"),
    ("quelles sont les propriétés de cet objet 3d", "blender__get_object_info"),
    ("où en est le job de génération 3d", "blender__poll_rodin_job_status"),
    ("combien de crédits motion me reste-t-il", "motion__get_credit_balance"),
    ("est-ce que polyhaven est activé", "blender__get_polyhaven_status"),
    ("donne-moi mon solde motion", "motion__get_credit_balance"),
    ("quels plans motion sont disponibles", "motion__list_plans"),
    ("vérifie l'état de sketchfab", "blender__get_sketchfab_status"),
]

#: Plancher mesuré APRÈS le pont : 0/8 avant, 7/8 après. Ce n'est pas 8/8 et le
#: seuil le dit — deux formulations résistent encore (« montre-moi les objets
#: présents dans la scène », « qu'est-ce que contient le viewport »), et poser
#: 8/8 rendrait le test rouge sur un progrès réel.
_MIN_LECTURE_D_ETAT = 6


def test_les_requetes_d_interrogation_atteignent_leurs_outils(selection):
    reussis, manques = 0, []
    for requete, attendu in LECTURE_D_ETAT:
        if attendu in selection(requete):
            reussis += 1
        else:
            manques.append(requete)
    assert reussis >= _MIN_LECTURE_D_ETAT, (
        f"régression de la lecture d'état ({reussis}/{len(LECTURE_D_ETAT)}) — "
        f"manqués : {manques}")


# ── Ce qui ne doit PAS remonter ─────────────────────────────────────────────
def test_aucun_outil_mcp_ne_fuit_sur_une_requete_front(selection):
    """Le garde central. Sept outils MCP liés à chaque tour d'une phase de code
    sont le bruit permanent que le routage par groupe avait supprimé."""
    fuites = []
    for requete in NEGATIFS_MCP:
        mcp = _outils_mcp(selection(requete))
        if mcp:
            fuites.append((requete, mcp[:3]))
    assert not fuites, f"fuite MCP sur des requêtes non-3D : {fuites}"


def test_le_vocabulaire_partage_ne_declenche_pas_la_3d(selection):
    """« rendu », « scène », « modélise », « génère », « anime » appartiennent
    aux deux mondes. C'est là qu'un index déséquilibré déraperait."""
    ambigus = NEGATIFS_MCP[5:]
    fuites = [r for r in ambigus if _outils_mcp(selection(r))]
    assert not fuites, f"le sens front-end n'a pas primé : {fuites}"


# ── Non-régression du routage natif ─────────────────────────────────────────
def test_les_outils_natifs_restent_atteignables(selection):
    reussis = sum(1 for requete, attendu in POSITIFS_NATIFS
                  if attendu in selection(requete))
    assert reussis >= _MIN_POSITIFS_NATIFS, "régression du routage natif"


# ── L'invariant d'architecture, vérifié sans réseau ─────────────────────────
def test_les_outils_mcp_restent_executables_meme_non_selectionnes():
    """`tool_map` est construit sur TOUS les outils : un outil hors sélection
    reste appelable. Retirer MCP de l'index ne doit jamais retirer ce filet —
    c'est la régression qu'un fix d'indexation trop rapide introduirait."""
    import inspect

    from src.agents.coding import specialist

    source = inspect.getsource(specialist)
    assert "tool_map = {t.name: t for t in all_tools}" in source
    assert "_get_coding_tools()" in source


def test_la_divergence_avec_l_orchestrateur_est_documentee():
    """Sans trace du POURQUOI, quelqu'un « corrigera » cette divergence en
    croyant réparer un oubli — et refera perdre 9 cas sur 23."""
    import inspect

    from src.agents.coding import specialist

    source = inspect.getsource(specialist)
    assert "graph.py" in source, "la divergence doit citer le chemin dont elle diverge"
    assert "test_mcp_routing_specialist" in source, "et le test qui la justifie"


# ── Le groupement est-il sain en lui-même ? ────────────────────────────────
#
# Question posée AVANT de supprimer `browser_screenshot`, et pour cette raison
# précise : si on retire le coupable d'abord, son symptôme le plus visible — il
# fuyait sur 5 tâches d'écriture front-end sur 6 — s'éteint mécaniquement avec
# lui, et l'on n'aura jamais vérifié le mécanisme. Le groupe `shell` garde cinq
# outils qui survivront à cette suppression.
#
# Mesuré alors, et l'inverse de ce qui était écrit dans le code : il n'arrivait
# pas en passager d'une tâche de build, il en était la GRAINE.
_COMMANDES_SHELL = "shell_"


def test_le_groupe_shell_ne_contient_que_des_commandes_shell():
    """L'appartenance se juge sur ce qu'un outil EST, pas sur ce qu'on fait
    juste après lui. « on lance le dev server puis on regarde la page » est une
    séquence d'usage, pas une parenté — et c'est ce raccourci qui avait mis
    `browser_screenshot` ici, d'où il tirait cinq outils sans rapport."""
    from src.agents.coding.tool_retriever import _TOOL_GROUPS

    intrus = [o for o in _TOOL_GROUPS["shell"] if not o.startswith(_COMMANDES_SHELL)]

    assert not intrus, f"pas des commandes shell : {intrus}"


def test_un_outil_dans_deux_groupes_echoue_au_demarrage():
    """Le bug qui a réellement eu lieu : `browser_screenshot` était déclaré à la
    fois dans « shell » et dans un groupe « visual ». L'index inverse gardait le
    dernier vu et perdait l'autre SANS RIEN DIRE — il tirait donc mermaid et
    download_asset au lieu du shell. Invisible, parce que le mauvais résultat
    était un groupe valide, simplement pas celui qu'on croyait."""
    from src.agents.coding.tool_retriever import _index_inverse

    with pytest.raises(ValueError, match="un seul groupe"):
        _index_inverse({"a": ["outil_x"], "b": ["outil_x"]})


def test_le_garde_fou_laisse_passer_un_groupement_correct():
    from src.agents.coding.tool_retriever import _TOOL_GROUPS, _index_inverse

    assert _index_inverse(_TOOL_GROUPS)["shell_run"] == "shell"


_INTENTIONS_SHELL = [
    "installe les dépendances",
    "installe framer-motion et configure-le",
    "ajoute la librairie framer-motion au projet",
    "lance npm install",
    "build le projet",
    "démarre le serveur de développement",
    "lance les tests",
]


def test_installer_ou_builder_donne_toujours_un_shell(selection):
    """Le trou que le retrait de `browser_screenshot` a DÉCOUVERT, et qu'il n'a
    pas créé : il tirait le groupe shell par accident sur « installe
    framer-motion et configure-le », masquant que `shell_run` n'y remontait pas.

    Mesuré : `shell_run` sortait 1er dès que la requête nommait l'écosystème
    (« dépendances », « pnpm », « npm install », « build ») et était ABSENT quand
    elle ne nommait qu'un paquet — l'embedding ne sait pas que framer-motion est
    un paquet npm. D'où l'ancre « installer une librairie ou un paquet par son
    nom ». Un agent sommé d'installer une lib sans shell ne peut rien faire.
    """
    manquants = [q for q in _INTENTIONS_SHELL if "shell_run" not in selection(q)]

    assert not manquants, f"aucun shell pour : {manquants}"


_SANS_SHELL = [
    "explique-moi ce que fait cette fonction",
    "renomme le fichier du formulaire de contact",
    "lis le contenu de page.tsx",
]


def test_lire_ou_expliquer_ne_tire_pas_le_shell(selection):
    """Le contrepoids de l'ancre ci-dessus. Une seconde ancre avait été essayée,
    « ajouter une dépendance au projet », et retirée : « au projet » remontait
    sur « explique-moi ce que fait cette fonction », qui passait de zéro à cinq
    outils shell. Une requête d'install gagnée ne payait pas cette fuite.

    « écris le composant Header en react » n'est PAS dans cette liste : il tire
    les cinq outils via `shell_cd`/`shell_pwd`, et c'est assumé — écrire un
    composant précède presque toujours un build, et resserrer davantage
    demanderait des signaux négatifs dont le coût dépasse la pollution.
    """
    from src.agents.coding.tool_retriever import _TOOL_GROUPS

    shell = set(_TOOL_GROUPS["shell"])
    fuites = [(q, sorted(set(selection(q)) & shell)) for q in _SANS_SHELL
              if set(selection(q)) & shell]

    assert not fuites, f"shell tiré sans raison : {fuites}"


@pytest.mark.xfail(strict=True, reason=(
    "Le couplage dev-server n'est pas fait. Mesuré :\n\n"
    "  « vérifie que la page d'accueil s'affiche dans le navigateur »\n"
    "        → 24 outils Playwright, shell_run ABSENT\n"
    "  « y a-t-il des erreurs dans la console du navigateur »\n"
    "        → 24 outils Playwright, shell_run ABSENT\n"
    "  « démarre le serveur de développement puis vérifie la page »\n"
    "        → shell_run présent, ZÉRO outil Playwright\n\n"
    "Chaque moitié de l'intention, jamais les deux : l'agent peut piloter un "
    "navigateur sans pouvoir démarrer le serveur vers lequel le pointer, ou "
    "l'inverse.\n\n"
    "Ce besoin justifiait de mettre `browser_screenshot` dans le groupe `shell`. "
    "Le moyen était faux — il y devenait la GRAINE et polluait des tâches "
    "d'écriture — mais le besoin lui survit, et le retrait le laisse à nu plutôt "
    "qu'il ne le crée."
))
def test_piloter_un_navigateur_devrait_donner_un_shell(selection):
    """Regarder une page qu'on n'a pas pu démarrer ne vérifie rien."""
    sans_shell = [q for q in POSITIFS_NAVIGATEUR
                  if _outils_navigateur(selection(q)) and "shell_run" not in selection(q)]

    assert not sans_shell, f"navigateur sans moyen de servir la page : {sans_shell}"
