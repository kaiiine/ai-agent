"""Un serveur MCP lié sur chaque requête est un serveur qu'on finit par débrancher.

Vécu : « schématise un RAG en prod » remontait cinq outils Blender et deux
Playwright. `top_servers=3` retenait les deux serveurs installés — il y en a moins
que trois — et `k=7` rendait toujours sept outils. Rien dans ce chemin ne pouvait
dire « aucun serveur ne concerne cette requête ».

Le seuil sémantique est impossible : « crée un cube dans blender » sort à 0.897 et
« scanne les paris de foot » à 0.905. Ces tests fixent donc ce qui marche —
signature lexicale distinctive, et mémoire de la conversation.
"""
from __future__ import annotations

import pytest

from src.mcp_client.pertinence import jetons, serveurs_pertinents, signatures

HINTS = {
    "blender": "Blender, 3D modeling, mesh manipulation, materials, geometry, "
               "animation, camera, lighting, rendering, scene editing, Python bpy",
    "playwright": "Piloter un navigateur web : ouvrir une URL, cliquer sur un "
                  "bouton ou un lien, saisir du texte dans un champ, remplir un "
                  "formulaire, faire une capture",
}


@pytest.fixture(scope="module")
def sigs():
    return signatures(HINTS)


def test_une_requete_sans_rapport_nelit_aucun_serveur(sigs):
    for question in ("quels sont mes rendez-vous de demain",
                     "envoie un mail à Nicolas pour décaler la réunion",
                     "commit mes changements avec un message clair",
                     "Tu peux me schématiser comment fonctionne un rag en prod"):
        assert serveurs_pertinents(question, sigs) == [], question


def test_le_nom_du_serveur_suffit(sigs):
    assert serveurs_pertinents("crée un cube dans blender", sigs) == ["blender"]


def test_la_signature_reconnait_sans_le_nom(sigs):
    assert serveurs_pertinents("rends la scène en 4k avec la caméra", sigs) == ["blender"]


def test_le_prefixe_rattrape_la_conjugaison(sigs):
    """« clique » et « cliquer » sont le même signal ; sans le préfixe, un seul
    jeton était reconnu et la requête passait sous le seuil."""
    assert serveurs_pertinents(
        "ouvre le navigateur et clique sur le bouton accepter", sigs) == ["playwright"]


def test_un_tour_de_suivi_reste_servi_par_la_conversation(sigs):
    """5 des 8 usages MCP réels du corpus ne nomment rien : « voici l'uid: … »."""
    suivi = "voici l'uid: d76a1407c0cd4d36a68d379a89863c07"
    assert serveurs_pertinents(suivi, sigs) == []
    assert serveurs_pertinents(suivi, sigs, actifs={"blender"}) == ["blender"]


def test_un_jeton_partage_ne_distingue_rien():
    """`python` et `export` figurent dans les descriptions des outils natifs :
    « écris un script python » ne doit pas réveiller Blender."""
    sigs = signatures(HINTS)
    assert "python" not in sigs["blender"]
    assert serveurs_pertinents("écris un script python qui trie un csv", sigs) == []


def test_les_signatures_sont_disjointes():
    sigs = signatures(HINTS)
    assert not (sigs["blender"] & sigs["playwright"])


def test_les_accents_ne_comptent_pas():
    assert jetons("Caméra") == jetons("camera")


def test_un_hint_maigre_garde_les_mots_de_lutilisateur():
    """La soustraction du vocabulaire natif est bornée.

    Un hint « diagnostic, exécution de code » se réduisait à `diagnostic` seul —
    `exécution` et `code` figurent dans les descriptions natives. Régler le hint ne
    changeait alors plus rien, ce qui est le défaut que le routage MCP a déjà
    corrigé une fois. Quand l'élagage ne laisse pas de quoi discriminer, on garde
    ce que l'utilisateur a écrit."""
    sigs = signatures({"alpha": "diagnostic, exécution de code"})
    assert len(sigs["alpha"]) >= 2
    assert serveurs_pertinents("exécute ce bout de code", sigs) == ["alpha"]


def test_un_hint_riche_reste_elague():
    """L'inverse doit rester vrai : sans élagage, le bruit passait de 6 à 20 %."""
    sigs = signatures(HINTS)
    assert "python" not in sigs["blender"]
    assert len(sigs["blender"]) >= 2


def test_un_serveur_sans_hint_reste_joignable():
    """L'absence de matière n'est pas une preuve de non-pertinence : le filtrer
    le rendrait injoignable pour toujours."""
    sigs = signatures({"muet": ""})
    assert serveurs_pertinents("n'importe quoi", sigs) == ["muet"]


def test_lindexation_attend_que_le_serveur_soit_elu(tmp_path, monkeypatch):
    """Elle coûtait 2,2 s à CHAQUE démarrage — 80 % du temps de lancement — pour
    52 outils, sur une collection éphémère dont le delta partait toujours d'un
    état vide. L'étage 1 lit le `capabilities_hint` de la config, pas l'index :
    un serveur peut donc être élu sans être indexé, et ne l'être qu'alors."""
    import inspect

    from src.mcp_client.runtime import MCPRuntime

    demarrage = inspect.getsource(MCPRuntime.start)
    assert "indexer=False" in demarrage, "le démarrage ne doit pas indexer"

    choix = inspect.getsource(MCPRuntime.select)
    assert choix.index("serveurs_pertinents") < choix.index("_indexer_si_besoin"), \
        "la porte décide AVANT qu'on paie une indexation"


def test_les_enveloppes_ne_dependent_pas_de_lindex():
    """Un outil non enveloppé n'est pas exécutable, quel que soit l'état de
    l'index — les deux structures sont donc distinctes."""
    import inspect

    from src.mcp_client.runtime import MCPRuntime

    source = inspect.getsource(MCPRuntime._rebuild_wrappers)
    assert "_connus" in source
    assert "_indexed" not in source
