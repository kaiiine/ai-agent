"""L'agent modifiait un fichier en le réécrivant en entier.

Un fichier de 800 lignes changé sur 3 coûtait 800 lignes de tokens de sortie, et
tout le prompt système passait son temps à interdire les `// ... reste inchangé`
que cette contrainte provoquait. `edit_file` fait porter le coût sur le
changement ; `propose_file_change` ne sert plus qu'à créer.
"""
from __future__ import annotations

import pytest

from src.agents.coding.pending import dev_plan, pending_changes
from src.agents.coding.tools import edit_file, propose_file_change


@pytest.fixture(autouse=True)
def _pile_propre():
    pending_changes.clear()
    yield
    pending_changes.clear()


@pytest.fixture
def fichier(tmp_path):
    f = tmp_path / "app.py"
    f.write_text("def a():\n    return 1\n\ndef b():\n    return 1\n", encoding="utf-8")
    return f


def _editer(fichier, ancien, nouveau, **extra):
    return edit_file.invoke({"path": str(fichier), "old_string": ancien,
                             "new_string": nouveau, **extra})


def test_un_fragment_unique_est_remplace(fichier):
    resultat = _editer(fichier, "def a():\n    return 1", "def a():\n    return 42")

    assert resultat["status"] == "proposed"
    assert pending_changes.items[0].proposed.startswith("def a():\n    return 42")


def test_le_fichier_non_touche_survit_au_changement(fichier):
    """L'intérêt de l'outil : ce qu'on ne retape pas ne peut pas être perdu."""
    _editer(fichier, "def a():\n    return 1", "def a():\n    return 42")

    assert "def b():\n    return 1" in pending_changes.items[0].proposed


def test_un_fragment_ambigu_est_refuse_avec_son_compte(fichier):
    """Remplacer la première occurrence au hasard modifierait le mauvais endroit."""
    resultat = _editer(fichier, "return 1", "return 2")

    assert resultat["status"] == "error"
    assert "2 fois" in resultat["error"]
    assert len(pending_changes) == 0


def test_replace_all_assume_les_occurrences_multiples(fichier):
    resultat = _editer(fichier, "return 1", "return 2", replace_all=True)

    assert resultat["status"] == "proposed"
    assert resultat["replacements"] == 2
    assert "return 1" not in pending_changes.items[0].proposed


def test_un_fragment_absent_renvoie_a_la_relecture(fichier):
    resultat = _editer(fichier, "def zzz():", "x")

    assert resultat["status"] == "error"
    assert "local_read_file" in resultat["error"]


def test_editer_un_fichier_inexistant_renvoie_a_la_creation(tmp_path):
    resultat = _editer(tmp_path / "nulle-part.py", "a", "b")

    assert resultat["status"] == "error"
    assert "propose_file_change" in resultat["error"]


def test_un_remplacement_sans_effet_est_refuse(fichier):
    assert _editer(fichier, "return 1", "return 1")["status"] == "error"


def test_deux_editions_du_meme_fichier_se_composent(fichier):
    """`PendingStore.add` remplace par chemin : sans lire la proposition en
    attente, la seconde édition effacerait la première avant même la revue."""
    _editer(fichier, "def a()", "def alpha()")
    _editer(fichier, "def b()", "def beta()")

    propose = pending_changes.items[0].proposed
    assert len(pending_changes) == 1
    assert "def alpha()" in propose and "def beta()" in propose


def test_le_diff_reste_calcule_face_au_disque(fichier):
    """`original` doit rester le vrai contenu du disque, sinon la revue montre
    un diff partiel et l'utilisateur approuve autre chose que ce qu'il croit."""
    _editer(fichier, "def a()", "def alpha()")
    _editer(fichier, "def b()", "def beta()")

    assert pending_changes.items[0].original == fichier.read_text(encoding="utf-8")


def test_une_edition_ne_reclame_pas_de_plan(fichier):
    """Le chemin court du prompt interdit dev_plan_create pour un seul fichier ;
    exiger un plan ici le rendrait impraticable."""
    dev_plan.clear()

    assert _editer(fichier, "return 1", "return 3", replace_all=True)["status"] == "proposed"


def test_creer_un_fichier_reclame_toujours_un_plan(tmp_path):
    """Le garde de propose_file_change reste : c'est lui qui a évité qu'une pile
    vide soit lue comme un refus utilisateur."""
    dev_plan.clear()

    resultat = propose_file_change.invoke(
        {"path": str(tmp_path / "neuf.py"), "content": "x", "description": "d"})

    assert resultat["status"] == "error"


# ── Câblage : un outil d'écriture ignoré quelque part est un outil inutilisable ──

@pytest.mark.parametrize("collection,chemin", [
    ("_ALWAYS_INCLUDED", "src.agents.coding.tool_retriever"),
    ("_REPETITION_EXEMPT", "src.agents.coding.specialist"),
    ("_PROGRESS_TOOLS", "src.agents.coding.specialist"),
    ("_WRITE_TOOLS", "src.agents.coding.pending"),
    ("BLOCKED_TOOLS", "src.ui.plan_mode"),
])
def test_edit_file_est_connu_partout(collection, chemin):
    import importlib

    assert "edit_file" in getattr(importlib.import_module(chemin), collection)


def test_une_edition_acceptee_vaut_preuve_d_ecriture():
    """Sans ça, dev_plan_step_done(proof_type="file_written") refuserait une
    étape pourtant réellement faite."""
    from src.agents.coding.pending import RecentToolsStore

    store = RecentToolsStore()
    store.record("edit_file", {"path": "/p/x.ts"}, {"status": "accepted", "path": "/p/x.ts"})

    assert store.file_was_written("/p/x.ts")


def test_les_deux_ui_ecrivent_les_editions_comme_les_creations():
    """/build et le mode auto passaient par data['content'] — absent d'edit_file."""
    import inspect

    from src.agents.coding import build_runner
    from src.ui import streaming

    assert '"propose_file_change", "edit_file"' in inspect.getsource(build_runner)
    assert 'elif tool_name in ("propose_file_change", "edit_file")' in inspect.getsource(streaming)


def test_build_ecrit_depuis_la_pile_pas_depuis_les_arguments():
    """`edit_file` ne passe qu'un fragment : reconstruire le fichier depuis les
    arguments écrirait le fragment à la place du fichier."""
    import inspect

    source = inspect.getsource(__import__("src.agents.coding.build_runner",
                                          fromlist=["_make_build_callback"])._make_build_callback)

    assert "pop_latest()" in source
    assert 'data.get("content"' not in source
    # Un appel en erreur n'a rien déposé : dépiler écrirait la proposition
    # précédente sous le chemin d'une autre.
    assert source.index('"status") == "error"') < source.index("pop_latest()")
