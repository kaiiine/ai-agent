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
