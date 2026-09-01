"""Écrit n'est pas debout.

Vécu : une réécriture de `tri.py` a produit un source dont tout le corps tenait
sur une seule ligne, avec des `\\n` littéraux. Le fichier existait, le diff
s'affichait, la revue disait « 1 fichier écrit » — et le script était mort.
Personne ne l'a su avant de l'exécuter.

Le contrôle est déterministe : on demande au langage lui-même si le fichier
parse. Aucun appel de modèle, donc aucun token, et aucun jugement.
"""
from __future__ import annotations

import pytest

from src.agents.coding.pending import FileChange, pending_changes
from src.orchestrator import revision
from src.orchestrator.plan import EXECUTER  # noqa: F401 — garde l'import stable
from src.orchestrator.verification import consigne, verifier


@pytest.fixture(autouse=True)
def _pile_propre():
    pending_changes.clear()
    yield
    pending_changes.clear()


def test_un_python_casse_est_detecte(tmp_path):
    """Le cas réel : des `\\n` littéraux au lieu de vraies fins de ligne."""
    fichier = tmp_path / "tri.py"
    fichier.write_text("'''doc'''\\n\\n\\ndef tri(l):\\n    return sorted(l)\\n",
                       encoding="utf-8")

    fautifs = verifier([str(fichier)])

    assert len(fautifs) == 1
    assert "tri.py" in fautifs[0]


def test_un_python_correct_ne_declenche_rien(tmp_path):
    fichier = tmp_path / "ok.py"
    fichier.write_text("def tri(liste):\n    return sorted(liste)\n", encoding="utf-8")

    assert verifier([str(fichier)]) == []


def test_un_json_invalide_est_detecte(tmp_path):
    fichier = tmp_path / "cfg.json"
    fichier.write_text('{"a": 1,,}', encoding="utf-8")

    assert verifier([str(fichier)])


def test_ce_quon_ne_sait_pas_verifier_nest_pas_signale(tmp_path):
    """Un faux positif ferait corriger du code correct."""
    for nom, contenu in (("note.md", "# titre"), ("script.sh", "if then fi"),
                         ("data.csv", "a,b\n1,2")):
        fichier = tmp_path / nom
        fichier.write_text(contenu, encoding="utf-8")
        assert verifier([str(fichier)]) == [], nom


def test_un_fichier_absent_ne_casse_pas_la_verification(tmp_path):
    assert verifier([str(tmp_path / "jamais.py")]) == []


def test_la_consigne_ordonne_de_reparer_sans_demander():
    """Il vient d'écrire le fichier : il a le contenu, et l'erreur dit où.
    Demander l'autorisation de réparer sa propre casse n'apporte rien."""
    texte = consigne(["tri.py — ligne 1 : invalid syntax"])

    assert "TOI-MÊME" in texte
    assert "sans rien demander" in texte
    assert "tri.py" in texte


# ── intégration : la revue le dit au modèle ───────────────────────────────────
def test_la_revue_signale_un_fichier_casse(tmp_path, monkeypatch):
    cible = tmp_path / "tri.py"
    pending_changes.add(FileChange(path=str(cible), original="",
                                   proposed="def tri(:\n", description="création"))
    monkeypatch.setattr(revision, "demander", lambda demande: ["Appliquer", ""])

    note = revision.reviser({"messages": []})["messages"][-1].content

    assert cible.exists(), "le fichier est bien écrit — on ne l'annule pas"
    assert "CASSÉ" in note
    assert "Corrige-le" in note


def test_la_revue_ne_signale_rien_sur_un_fichier_sain(tmp_path, monkeypatch):
    cible = tmp_path / "tri.py"
    pending_changes.add(FileChange(path=str(cible), original="",
                                   proposed="def tri(liste):\n    return sorted(liste)\n",
                                   description="création"))
    monkeypatch.setattr(revision, "demander", lambda demande: ["Appliquer", ""])

    note = revision.reviser({"messages": []})["messages"][-1].content

    assert "CASSÉ" not in note


def test_appliquer_ninterdit_pas_une_suite_legitime(tmp_path, monkeypatch):
    """« N'écris pas ces fichiers une seconde fois » visait la reproposition à
    vide — déjà refusée par `propose_file_change`, qui rejette un contenu
    identique au disque. Interdire ici bloquait toute suite légitime : une étape
    suivante du plan, une correction, un ajout demandé après coup."""
    cible = tmp_path / "tri.py"
    pending_changes.add(FileChange(path=str(cible), original="",
                                   proposed="x = 1\n", description="création"))
    monkeypatch.setattr(revision, "demander", lambda demande: ["Appliquer", ""])

    note = revision.reviser({"messages": []})["messages"][-1].content

    assert "seconde fois" not in note
    assert "sur le disque" in note
