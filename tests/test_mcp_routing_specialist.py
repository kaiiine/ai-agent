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

État actuel de l'index, 87 outils / 138 documents : 38 natifs, et 49 outils MCP
soit 35 % de la cardinalité — Blender 25, Playwright 24. Motion a été supprimé
de la config, et avec lui trois labels de lecture d'état (cf. LECTURE_D_ETAT).

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
    #
    # « fais une capture de la page d'accueil dans le navigateur » attendait ici
    # `browser_screenshot`, supprimé. Le cas n'est pas perdu : il vit maintenant
    # dans POSITIFS_NAVIGATEUR, où l'attendu est un outil Playwright — c'est le
    # même besoin, routé vers son nouveau titulaire.
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
    # Repris de POSITIFS_NATIFS, où il attendait `browser_screenshot`.
    "fais une capture de la page d'accueil dans le navigateur",
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
    """Les outils navigateur — tous Playwright depuis la suppression du natif.

    Ce filtre a été écrit quand `browser_screenshot` existait encore, et c'est
    lui qui a rendu la bascule mesurable : il fuyait alors sur 5 des 6 tâches
    d'écriture front-end, et le confondre avec Playwright aurait attribué à la
    bascule une fuite qu'elle n'avait pas causée.

    La séparation a servi deux fois. Elle a montré que la fuite venait du
    GROUPEMENT et non du sens — `browser_screenshot` était la graine qui tirait
    le groupe `shell` — puis, ce défaut corrigé séparément, elle a permis de
    mesurer Playwright seul avant de supprimer son prédécesseur.
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

    Le seuil est à 4 sur 5, pas à 5 : « clique sur le menu hamburger et vérifie
    qu'il s'ouvre » ne remonte rien, « menu » et « s'ouvre » dominant le seul mot
    ponté. C'est une limite connue et unique, pas un test permissif — les quatre
    autres remontent les 24 outils du serveur.
    """
    reussis = sum(1 for r in POSITIFS_NAVIGATEUR if _outils_navigateur(selection(r)))
    assert reussis >= 4, (
        f"rappel navigateur insuffisant ({reussis}/{len(POSITIFS_NAVIGATEUR)})")


def test_ecrire_du_code_front_ne_tire_jamais_le_navigateur(selection):
    """Le garde le plus important de la bascule Playwright. Un composant
    s'écrit dans un fichier ; l'ouvrir dans un onglet ne le fait pas exister."""
    fuites = [(r, _outils_navigateur(selection(r))) for r in NEGATIFS_FRONT
              if _outils_navigateur(selection(r))]
    assert not fuites, f"fuite navigateur sur des tâches d'écriture : {fuites}"


#: Planchers de RÉGRESSION, pas des cibles. Mesurés le 16 août 2026.
_MIN_POSITIFS_MCP = 6      # sur 6 (hors cas connu défaillant)
_MIN_NEGATIFS_MCP = 10     # sur 10 — aucune fuite tolérée
_MIN_POSITIFS_NATIFS = 5   # sur 5 — un cas est parti vers POSITIFS_NAVIGATEUR


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
    ("est-ce que polyhaven est activé", "blender__get_polyhaven_status"),
    ("vérifie l'état de sketchfab", "blender__get_sketchfab_status"),
]

#: Trois requêtes ont été retirées avec le serveur Motion, supprimé de la config :
#: « combien de crédits motion me reste-t-il », « donne-moi mon solde motion »,
#: « quels plans motion sont disponibles ».
#:
#: Elles ne sont PAS remplacées par des équivalents Blender fabriqués pour tenir
#: le compte à huit. Conséquence à connaître : quatre entrées du pont ne sont plus
#: exercées par aucun label — « combien » → « how many count balance »,
#: « donne-moi », « quels sont », et « reste » → « remaining balance ». Aucun outil
#: des serveurs restants n'expose un solde ou une liste de plans, donc le cas
#: n'existe simplement plus ; ces entrées restent en place pour le jour où un
#: serveur à quotas reviendra, mais sans filet de mesure d'ici là.

#: Plancher mesuré APRÈS le pont : 0/8 avant, 7/8 après, sur les huit labels
#: d'alors. Ce n'était pas 8/8 et le seuil le disait — deux formulations résistent
#: encore (« montre-moi les objets présents dans la scène », « qu'est-ce que
#: contient le viewport »), et poser le maximum rendrait le test rouge sur un
#: progrès réel. Même écart conservé sur les cinq labels restants.
_MIN_LECTURE_D_ETAT = 4


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


def test_piloter_un_navigateur_donne_un_shell(selection):
    """Regarder une page qu'on n'a pas pu démarrer ne vérifie rien.

    Ce test a d'abord été posé en xfail, sur cette mesure :

        « vérifie que la page d'accueil s'affiche dans le navigateur »
              → 24 outils Playwright, shell_run ABSENT

    C'est le besoin qui justifiait de mettre `browser_screenshot` DANS le groupe
    `shell`. Le moyen était faux — il y devenait la graine et polluait des tâches
    d'écriture — mais le besoin lui a survécu, et son retrait l'a laissé à nu.

    Il est satisfait par une dépendance ORIENTÉE (`_DEPENDANCES_MCP`), pas par une
    appartenance de groupe : un groupe est symétrique, et c'est sa symétrie qui
    avait tout cassé. Piloter un navigateur exige un shell ; lancer une commande
    shell n'exige aucun navigateur, et le vérifier est l'objet de
    `test_le_shell_ne_convoque_jamais_le_navigateur`.
    """
    sans_shell = [q for q in POSITIFS_NAVIGATEUR
                  if _outils_navigateur(selection(q)) and "shell_run" not in selection(q)]

    assert not sans_shell, f"navigateur sans moyen de servir la page : {sans_shell}"


_INTENTIONS_SHELL_PURES = [
    "build le projet",
    "installe les dépendances",
    "lance les tests",
    "démarre le serveur de développement",
]


def test_le_shell_ne_convoque_jamais_le_navigateur(selection):
    """La moitié qui manque à la dépendance, et qui doit manquer. Déclarer
    `shell` → `playwright` ramènerait le navigateur sur chaque build, install et
    lancement de tests : c'est la fuite mesurée à 13 négatifs sur 16 quand
    l'expansion de serveur tournait sans le pont lexical.

    « démarre le serveur de développement » est dans cette liste exprès : c'est
    le cas le plus tentant, puisque démarrer un serveur PRÉCÈDE souvent une
    vérification. Précéder n'est pas exiger.
    """
    fuites = [(q, _outils_navigateur(selection(q))) for q in _INTENTIONS_SHELL_PURES
              if _outils_navigateur(selection(q))]

    assert not fuites, f"le shell a convoqué le navigateur : {fuites}"


# ── Une graine MCP trop lointaine n'a rien matché ──────────────────────────
#
# `installe framer-motion` remontait les huit outils du serveur Motion. La cause
# semblait être le token « motion » — une lib d'animation npm contre un service
# de génération vidéo. Motion retiré, la même requête a remonté les vingt-cinq
# outils de Blender : ce n'était donc pas le token. Une requête courte nommant un
# nom propre inconnu n'a aucun bon voisin natif, et le serveur MCP le plus proche
# remplit les huit places, quel qu'il soit.
_FALLTHROUGH = [
    "installe framer-motion",
    "ajoute la librairie framer-motion au projet",
]


def _distance_mcp_min(retriever, query: str) -> float | None:
    from src.agents.coding.tool_retriever import _pont_linguistique

    resultats = retriever._store.similarity_search_with_score(
        _pont_linguistique(query), k=8)
    distances = [d for doc, d in resultats
                 if "__" in doc.metadata.get("tool_name", "")]
    return min(distances) if distances else None


@pytest.fixture(scope="module")
def retriever_brut():
    """Le retriever lui-même, pas seulement sa sélection : la marge se mesure sur
    des distances, que `selection` n'expose pas."""
    from src.agents.coding.specialist import _get_coding_tools
    from src.agents.coding.tool_retriever import CodingToolRetriever

    outils = _get_coding_tools()
    if not any("__" in t.name for t in outils):
        pytest.skip("aucun serveur MCP joignable — rien à mesurer")
    r = CodingToolRetriever(outils, k=8)
    if r._store is None:
        pytest.skip("embeddings indisponibles — distances non mesurables")
    return r


def test_la_marge_du_seuil_de_distance_tient_toujours(retriever_brut):
    """Ce test REMESURE la marge au lieu de figer 0.85.

    Le seuil dépend de l'embedder (`nomic-embed-text`) et de la distance de
    Chroma ; en changer invaliderait les nombres mesurés. Figer la valeur dans un
    test la rendrait vraie par construction et muette au moment où elle cesserait
    d'être juste. Vérifier la MARGE échoue au contraire dès que le classement se
    déplace, ce qui est précisément le signal qu'on veut.

    Mesuré : légitimes 0.548 → 0.765, parasites une seule graine à 0.960.
    """
    from src.agents.coding.tool_retriever import _DISTANCE_MAX_MCP

    legitimes = [q for q, _ in POSITIFS_MCP] + [POSITIF_MCP_CONNU_DEFAILLANT[0]] \
        + POSITIFS_NAVIGATEUR
    trop_loin = [(q, d) for q in legitimes
                 if (d := _distance_mcp_min(retriever_brut, q)) is not None
                 and d > _DISTANCE_MAX_MCP]
    assert not trop_loin, f"le seuil écarte des intentions MCP RÉELLES : {trop_loin}"

    trop_proche = [(q, d) for q in _FALLTHROUGH
                   if (d := _distance_mcp_min(retriever_brut, q)) is not None
                   and d <= _DISTANCE_MAX_MCP]
    assert not trop_proche, f"le seuil laisse passer du bruit : {trop_proche}"


def test_installer_une_lib_ne_convoque_aucun_serveur_mcp(selection):
    """Le symptôme, mesuré du côté de la sélection et non des distances : ni les
    vingt-cinq outils de Blender, ni ceux d'un autre serveur."""
    fuites = [(q, _outils_mcp(selection(q))) for q in _FALLTHROUGH
              if _outils_mcp(selection(q))]

    assert not fuites, f"un serveur MCP convoqué pour installer une lib : {fuites}"


def test_installer_une_lib_donne_quand_meme_le_shell(selection):
    """Le garde-fou du garde-fou : écarter le bruit ne doit pas laisser l'agent
    sans moyen d'installer quoi que ce soit.

    « installe framer-motion » nu est EXCLU de cette assertion, et le mesuré dit
    pourquoi : sur cette requête, toutes les distances sont ≥ 0.902 — git_status
    0.902, shell_run 0.970, blender 0.960. Rien ne matche. `shell_run` flotte au
    rang 7 d'un k=8 où les écarts se jouent à trois millièmes, donc sa présence
    varie d'une exécution à l'autre. L'asserter serait asserter sur du bruit.

    C'est précisément pour ce régime que le seuil de distance existe : quand rien
    ne matche, le tirage ne doit au moins pas convoquer un serveur entier — ce que
    `test_installer_une_lib_ne_convoque_aucun_serveur_mcp` vérifie sur les deux.
    """
    reel = "ajoute la librairie framer-motion au projet"   # meilleure graine 0.643
    assert "shell_run" in selection(reel), "aucun shell pour installer une lib"
