"""Ce que l'utilisateur joint doit atteindre l'agent de code.

La frontière entre l'orchestrateur et le sous-graphe de code est une CHAÎNE :
`run_coding_agent(task: str)`. Le contenu d'un PDF joint, lui, vivait dans
l'historique de l'orchestrateur — du mauvais côté. Joindre un cahier des charges
puis demander « code ce qui est décrit dedans » ne transmettait que la phrase, et
l'agent partait inventer.

Les images ne traversent pas : aucun backend ne déclare ici s'il sait les lire, et
envoyer du base64 à un modèle qui ne le sait pas casse l'appel. On signale qu'elles
existent, ce qui laisse l'agent demander — au lieu de deviner sans savoir qu'il devine.
"""
from __future__ import annotations

import json

import pytest

from src.agents.coding import noeud
from src.ui.attachments import attachments


@pytest.fixture(autouse=True)
def _pile_propre():
    attachments.pop_all()
    attachments._derniers.clear()
    yield
    attachments.pop_all()
    attachments._derniers.clear()


@pytest.fixture
def joint(tmp_path):
    def _joindre(nom: str, contenu: str = "contenu"):
        fichier = tmp_path / nom
        fichier.write_text(contenu, encoding="utf-8")
        attachments.add_file(str(fichier))
        return fichier
    return _joindre


def _pieces_transmises(monkeypatch) -> str:
    """Ce que le sous-graphe reçoit vraiment, sans appeler de modèle."""
    from src.agents.coding import specialist

    vu: dict = {}
    graphe = type("G", (), {"invoke": lambda self, etat: vu.update(etat) or {}})()
    monkeypatch.setattr(specialist, "preparer", lambda tache: (graphe, lambda r: "ok"))
    monkeypatch.setattr(specialist, "_vram_swap_in", lambda: None)
    monkeypatch.setattr(specialist, "_vram_swap_out", lambda: None)

    from langchain_core.messages import ToolMessage

    noeud.coder({"messages": [ToolMessage(
        content=json.dumps({"status": noeud.MARQUEUR, "tache": "code ce qui est décrit"}),
        tool_call_id="c1", name="run_coding_agent")]})
    return vu.get("pieces", "")


def test_un_fichier_joint_traverse_jusqua_lagent_de_code(joint, monkeypatch):
    joint("cahier.md", "Le script doit trier par insertion.\n")
    attachments.pop_all()          # ce que l'UI fait en bâtissant le message

    assert "trier par insertion" in _pieces_transmises(monkeypatch)


def test_un_pdf_traverse_par_son_texte_extrait(tmp_path, monkeypatch):
    pypdf = pytest.importorskip("pypdf")
    pdf = tmp_path / "spec.pdf"
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.write(str(pdf))
    attachments.add_file(str(pdf))
    attachments.pop_all()

    assert "spec.pdf" in _pieces_transmises(monkeypatch)


def test_une_image_est_signalee_mais_pas_envoyee(tmp_path, monkeypatch):
    Image = pytest.importorskip("PIL.Image", reason="PIL absent")
    jpg = tmp_path / "maquette.jpg"
    Image.new("RGB", (10, 10)).save(jpg)
    attachments.add_file(str(jpg))
    attachments.pop_all()

    pieces = _pieces_transmises(monkeypatch)

    assert "maquette.jpg" in pieces
    assert "base64" not in pieces


def test_un_fichier_trop_long_passe_par_son_chemin(joint, monkeypatch):
    gros = joint("gros.txt", "x" * (noeud._PIECES_MAX + 1))
    attachments.pop_all()

    pieces = _pieces_transmises(monkeypatch)

    assert "local_read_file" in pieces
    assert str(gros) in pieces
    assert "x" * 500 not in pieces, "le contenu ne doit pas être recopié"


def test_sans_piece_jointe_rien_nest_ajoute(monkeypatch):
    assert _pieces_transmises(monkeypatch) == ""


def test_le_magasin_retient_le_tour_apres_avoir_ete_vide(joint):
    """`coder` tourne APRÈS que l'UI ait vidé la pile pour bâtir le message."""
    joint("note.txt")

    attachments.pop_all()

    assert not attachments.items
    assert [p.name for p in attachments.derniers] == ["note.txt"]
