"""Ce qui se passait APRÈS que le fichier soit écrit.

Vécu, sur « écris un script /tmp/axon-essai/tri.py qui trie une liste » : le
fichier est écrit, accepté, sur le disque — et l'agent tourne encore plusieurs
minutes. Il rejoue son plan deux fois sans rien y changer, le curseur revient à
l'étape 1 alors que la 2 est cochée, et il lance `echo done`, `true`,
`echo step1done`.

Rien de tout cela n'était du caprice de modèle. Chaque geste répondait à un refus
que le code lui opposait :

- `dev_plan_step_done(proof_type="file_written")` attendait le statut
  « accepted » ; `propose_file_change` rend « proposed », toujours. L'étape
  qu'il venait d'accomplir était donc incochable, et la seule preuve encore
  recevable était `shell_ran` — d'où les `echo`.
- `dev_plan_update` exigeait les étapes cochées EN TÊTE ; la sienne était au
  milieu, l'appel était refusé, il le refaisait.
- une suppression relue puis acceptée écrivait un fichier VIDE au lieu
  d'effacer : le fichier revenait, il le reproposait, indéfiniment.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.agents.coding import tools as outils
from src.agents.coding.pending import (FileChange, dev_plan, pending_changes,
                                       recent_tools)
from src.orchestrator import revision


@pytest.fixture(autouse=True)
def _etat_propre():
    for magasin in (dev_plan, recent_tools, pending_changes):
        magasin.clear()
    dev_plan._tache = ""
    dev_plan.exige_un_plan = True
    yield
    for magasin in (dev_plan, recent_tools, pending_changes):
        magasin.clear()
    dev_plan.exige_un_plan = False


@pytest.fixture
def accepte(monkeypatch):
    monkeypatch.setattr(revision, "demander", lambda demande: ["Appliquer", ""])


# ── cocher ce qu'on vient d'écrire ────────────────────────────────────────────
def test_une_etape_est_cochable_apres_une_ecriture_acceptee(tmp_path, accepte):
    cible = tmp_path / "tri.py"
    dev_plan.create(["Créer tri.py"])
    outils.propose_file_change.invoke(
        {"path": str(cible), "content": "def tri(l):\n    return sorted(l)\n"})
    revision.reviser({"messages": []})

    resultat = outils.dev_plan_step_done.invoke(
        {"step_index": 0, "proof_type": "file_written", "proof_path": str(cible)})

    assert resultat["status"] == "ok", resultat.get("error")


def test_aucune_preuve_shell_nest_necessaire_pour_une_ecriture(tmp_path, accepte):
    """La preuve fabriquée : `echo done` passait là où l'écriture réelle échouait."""
    cible = tmp_path / "tri.py"
    dev_plan.create(["Créer tri.py"])
    outils.propose_file_change.invoke({"path": str(cible), "content": "x = 1\n"})
    revision.reviser({"messages": []})

    assert recent_tools.file_was_written(str(cible))
    assert not recent_tools.shell_succeeded()


def test_une_etape_de_suppression_se_coche_par_labsence(tmp_path, accepte):
    cible = tmp_path / "inutile.txt"
    cible.write_text("du contenu\n", encoding="utf-8")
    dev_plan.create(["Supprimer inutile.txt"])
    outils.propose_file_delete.invoke({"path": str(cible)})
    revision.reviser({"messages": []})

    resultat = outils.dev_plan_step_done.invoke(
        {"step_index": 0, "proof_type": "file_written", "proof_path": str(cible)})

    assert resultat["status"] == "ok", resultat.get("error")


# ── supprimer, c'est effacer ──────────────────────────────────────────────────
def test_une_suppression_acceptee_efface_vraiment(tmp_path, accepte):
    cible = tmp_path / "inutile.txt"
    cible.write_text("du contenu\n", encoding="utf-8")
    pending_changes.add(FileChange(path=str(cible), original="du contenu\n",
                                   proposed="", description="Supprimer",
                                   supprime=True))

    revision.reviser({"messages": []})

    assert not cible.exists(), "le fichier était recréé vide au lieu d'être effacé"


def test_la_revue_annonce_une_suppression_comme_telle(tmp_path):
    cible = tmp_path / "inutile.txt"
    changement = FileChange(path=str(cible), original="du contenu\n", proposed="",
                            description="Supprimer", supprime=True)

    apercu = revision._apercu([changement])

    assert "supprimé" in apercu
    assert "nouveau" not in apercu


# ── vider n'est pas supprimer ─────────────────────────────────────────────────
def test_vider_un_fichier_existant_est_refuse(tmp_path):
    """Le geste qui a créé `fragments-???.txt` 0B : le même chemin, contenu vide."""
    cible = tmp_path / "fragments.txt"
    cible.write_text("du contenu\n", encoding="utf-8")

    resultat = outils.propose_file_change.invoke({"path": str(cible), "content": ""})

    assert resultat["status"] == "error"
    assert "propose_file_delete" in resultat["error"]
    assert cible.read_text(encoding="utf-8") == "du contenu\n"


def test_creer_un_fichier_vide_reste_permis(tmp_path):
    """`__init__.py` et `.gitkeep` en vivent."""
    resultat = outils.propose_file_change.invoke(
        {"path": str(tmp_path / "__init__.py"), "content": ""})

    assert resultat["status"] == "proposed"


# ── réviser un plan dont les cochées ne se suivent pas ────────────────────────
def test_le_plan_se_revise_meme_si_une_etape_du_milieu_est_cochee():
    dev_plan.create(["Créer le répertoire", "Supprimer le résidu", "Créer tri.py"])
    dev_plan.check(1)

    resultat = outils.dev_plan_update.invoke({
        "steps": ["Créer le répertoire", "Supprimer le résidu", "Créer tri.py",
                  "Lancer le script"],
        "reason": "il faut aussi vérifier que le script tourne"})

    assert resultat["status"] == "ok", resultat.get("error")
    assert [e.done for e in dev_plan.steps] == [False, True, False, False]


def test_une_etape_faite_ne_peut_pas_disparaitre_du_plan():
    dev_plan.create(["Créer le répertoire", "Créer tri.py"])
    dev_plan.check(0)

    resultat = outils.dev_plan_update.invoke(
        {"steps": ["Créer tri.py"], "reason": "simplification"})

    assert resultat["status"] == "error"
    assert "Créer le répertoire" in resultat["error"]


# ── une demande, un plan — mais un plan qui survit aux reprises ───────────────
def test_une_nouvelle_demande_repart_dun_plan_vide():
    """Singleton de module : seul `/build` le réinitialisait. Une deuxième demande
    dans la même session héritait du plan de la première."""
    dev_plan._tache = "une demande d'avant"
    dev_plan.create(["Une tâche d'avant"])

    with dev_plan.run_specialist("une autre demande"):
        assert dev_plan.steps == []
        resultat = outils.dev_plan_create.invoke({"steps": ["Créer tri.py"]})

    assert resultat["status"] == "ok"


def test_le_plan_survit_a_une_reprise_apres_interruption():
    """`coder` ré-entre dans `run_specialist` après CHAQUE interruption — un plan
    soumis, un diff relu. Effacer à l'entrée vidait le plan en plein travail : le
    modèle le retrouvait disparu, le recréait, et le plan neuf rouvrait le
    questionnaire de validation. Mesuré : trois validations pour une demande."""
    tache = "écris un script tri.py"

    with dev_plan.run_specialist(tache):
        dev_plan.create(["Créer tri.py"])

    with dev_plan.run_specialist(tache):        # la reprise
        assert [e.label for e in dev_plan.steps] == ["Créer tri.py"]


def test_une_reprise_ne_perd_pas_les_preuves_deja_acquises():
    """`recent_tools` était vidé au même endroit : l'écriture acceptée avant
    l'interruption devenait improuvable au retour."""
    tache = "écris un script tri.py"

    with dev_plan.run_specialist(tache):
        recent_tools.note_ecriture("/tmp/tri.py")

    with dev_plan.run_specialist(tache):
        assert recent_tools.file_was_written("/tmp/tri.py")


def test_la_description_de_loutil_ninvente_pas_detapes():
    """« 3–8 items » faisait rembourrer : d'où « Marquer le fichier comme écrit »,
    une étape qu'aucune preuve ne peut satisfaire."""
    description = outils.dev_plan_create.description

    assert "3–8" not in description and "3-8" not in description
    assert "bookkeeping" in description


# ── /undo ─────────────────────────────────────────────────────────────────────
# Le mode `ask` — celui qu'on utilise — écrivait sans sauver de snapshot : seuls
# `auto` et `/build` en gardaient un. `/undo` après une édition normale répondait
# donc « rien à annuler ». Le passage par `pending.appliquer` referme ça pour les
# trois chemins d'un coup.
def test_undo_rend_son_contenu_a_un_fichier_modifie(tmp_path, accepte):
    from src.agents.coding.pending import snapshots

    snapshots.clear()
    cible = tmp_path / "a.py"
    cible.write_text("original\n", encoding="utf-8")
    pending_changes.add(FileChange(path=str(cible), original="original\n",
                                   proposed="modifie\n", description="edit"))
    revision.reviser({"messages": []})

    assert snapshots, "/undo n'avait rien à annuler après une écriture en mode ask"
    snapshots.restore_all()

    assert cible.read_text(encoding="utf-8") == "original\n"


def test_undo_efface_un_fichier_qui_vient_detre_cree(tmp_path, accepte):
    """Un snapshot vide disait à la fois « n'existait pas » et « existait, vide » :
    annuler une création réécrivait le fichier à vide au lieu de le retirer."""
    from src.agents.coding.pending import snapshots

    snapshots.clear()
    cible = tmp_path / "neuf.py"
    pending_changes.add(FileChange(path=str(cible), original="", proposed="x = 1\n",
                                   description="create"))
    revision.reviser({"messages": []})
    snapshots.restore_all()

    assert not cible.exists()


def test_undo_ressuscite_un_fichier_supprime(tmp_path, accepte):
    from src.agents.coding.pending import snapshots

    snapshots.clear()
    cible = tmp_path / "c.py"
    cible.write_text("a garder\n", encoding="utf-8")
    pending_changes.add(FileChange(path=str(cible), original="a garder\n",
                                   proposed="", description="del", supprime=True))
    revision.reviser({"messages": []})
    assert not cible.exists()

    snapshots.restore_all()

    assert cible.read_text(encoding="utf-8") == "a garder\n"


def test_undo_distingue_un_fichier_vide_dun_fichier_absent(tmp_path, accepte):
    """`__init__.py` vide, modifié puis annulé : il doit revenir vide, pas disparaître."""
    from src.agents.coding.pending import snapshots

    snapshots.clear()
    cible = tmp_path / "__init__.py"
    cible.write_text("", encoding="utf-8")
    pending_changes.add(FileChange(path=str(cible), original="",
                                   proposed="from .a import b\n", description="edit"))
    revision.reviser({"messages": []})
    snapshots.restore_all()

    assert cible.exists() and cible.read_text(encoding="utf-8") == ""


# ── /undo défait la dernière revue, pas la session ────────────────────────────
# Il restaurait TOUT ce que la session avait touché. Vécu en mesure : deux
# demandes sans rapport, un `/undo`, et un travail de vingt minutes revenait avec
# la coquille qu'on voulait annuler. Les chemins s'affichaient bien avant
# restauration, mais rien ne disait qu'ils venaient de tours différents.
def _revue(chemin, contenu, accepte_fixture=None):
    from src.agents.coding.pending import FileChange, pending_changes

    pending_changes.add(FileChange(path=str(chemin), original=chemin.read_text(),
                                   proposed=contenu, description=""))
    revision.reviser({"messages": []})


def test_undo_ne_defait_que_la_derniere_revue(tmp_path, accepte):
    from src.agents.coding.pending import snapshots

    snapshots.clear()
    vieux, recent = tmp_path / "vieux.py", tmp_path / "recent.py"
    vieux.write_text("travail de 20 minutes\n", encoding="utf-8")
    recent.write_text("coquille\n", encoding="utf-8")

    _revue(vieux, "vieux modifié\n")          # tour 1
    _revue(recent, "recent modifié\n")        # tour 2
    snapshots.restore_last()

    assert vieux.read_text(encoding="utf-8") == "vieux modifié\n", "le tour 1 a été défait"
    assert recent.read_text(encoding="utf-8") == "coquille\n"


def test_ce_que_undo_va_defaire_est_annoncable(tmp_path, accepte):
    from src.agents.coding.pending import snapshots

    snapshots.clear()
    a, b = tmp_path / "a.py", tmp_path / "b.py"
    a.write_text("a\n", encoding="utf-8")
    b.write_text("b\n", encoding="utf-8")
    _revue(a, "a2\n")
    _revue(b, "b2\n")

    assert [Path(p).name for p in snapshots.dernier_lot] == ["b.py"]


def test_undo_all_defait_encore_tout(tmp_path, accepte):
    from src.agents.coding.pending import snapshots

    snapshots.clear()
    a, b = tmp_path / "a.py", tmp_path / "b.py"
    a.write_text("a\n", encoding="utf-8")
    b.write_text("b\n", encoding="utf-8")
    _revue(a, "a2\n")
    _revue(b, "b2\n")
    snapshots.restore_all()

    assert a.read_text(encoding="utf-8") == "a\n"
    assert b.read_text(encoding="utf-8") == "b\n"


def test_deux_undo_de_suite_remontent_le_temps(tmp_path, accepte):
    from src.agents.coding.pending import snapshots

    snapshots.clear()
    a, b = tmp_path / "a.py", tmp_path / "b.py"
    a.write_text("a\n", encoding="utf-8")
    b.write_text("b\n", encoding="utf-8")
    _revue(a, "a2\n")
    _revue(b, "b2\n")
    snapshots.restore_last()
    snapshots.restore_last()

    assert a.read_text(encoding="utf-8") == "a\n"


def test_plus_rien_a_defaire_rend_une_liste_vide(tmp_path, accepte):
    from src.agents.coding.pending import snapshots

    snapshots.clear()
    a = tmp_path / "a.py"
    a.write_text("a\n", encoding="utf-8")
    _revue(a, "a2\n")
    snapshots.restore_last()

    assert snapshots.restore_last() == []
    assert snapshots.dernier_lot == []
