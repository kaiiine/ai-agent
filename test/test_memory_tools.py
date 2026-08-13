"""Mémoire persistante par projet — `axon_note` et le stockage qui la porte.

CE FICHIER A ÉTÉ RECIBLÉ. Il visait `src/agents/memory/tools._find_git_root` et
`._memory_path`, deux fonctions privées qui ont déménagé : la logique vit
désormais dans `memory/persistent.py`, et le stockage est passé d'un fichier
unique `.axon/memory.md` à un RÉPERTOIRE `.axon/memory/` avec un fichier par
nature de note.

Les CONTRATS testés n'ont pas changé — découvrir la racine git, écrire la note,
créer l'arborescence, poser un en-tête une seule fois, dater, retirer les espaces
superflus. Seule leur adresse a bougé. Un test qui importe une fonction disparue
ne prouve rien ; il ne signale même pas la régression qu'il était censé attraper.
"""
import re
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest


# ── Découverte de la racine git ───────────────────────────────────────────────

def test_find_git_root_finds_repo(tmp_path):
    from src.agents.memory.persistent import _find_git_root
    (tmp_path / ".git").mkdir()
    assert _find_git_root(tmp_path) == tmp_path


def test_find_git_root_finds_parent_repo(tmp_path):
    from src.agents.memory.persistent import _find_git_root
    (tmp_path / ".git").mkdir()
    nested = tmp_path / "src" / "module"
    nested.mkdir(parents=True)
    assert _find_git_root(nested) == tmp_path


def test_find_git_root_hors_repo_rend_none(tmp_path):
    """Rend `None`, pas le répertoire de départ.

    L'ancienne version rendait le point de départ, ce qui faisait écrire une
    mémoire de projet dans un dossier quelconque — hors de tout dépôt, donc sans
    projet auquel la rattacher. `_axon_dir` a besoin de la distinction pour
    renoncer proprement.
    """
    from src.agents.memory.persistent import _find_git_root
    assert _find_git_root(tmp_path) is None


# ── axon_note ─────────────────────────────────────────────────────────────────

@pytest.fixture
def memoire(tmp_path):
    """Redirige la mémoire vers un répertoire temporaire.

    On substitue `_memory_dir`, la frontière du stockage — pas `Path.cwd`, qui
    ferait dépendre le test de la découverte git ET de l'écriture à la fois.
    """
    cible = tmp_path / ".axon" / "memory"
    with patch("src.agents.memory.persistent._memory_dir", return_value=cible):
        yield cible


def _note(fact: str, kind: str = "learning") -> str:
    from src.agents.memory.tools import axon_note
    return axon_note.invoke({"fact": fact, "kind": kind})


def test_axon_note_cree_le_fichier_de_memoire(memoire):
    resultat = _note("Auth uses JWT RS256. See src/auth/tokens.py")

    fichier = memoire / "learnings.md"
    assert fichier.exists()
    assert "Auth uses JWT RS256" in fichier.read_text(encoding="utf-8")
    assert "Note enregistrée" in resultat


def test_axon_note_cree_l_arborescence(tmp_path):
    cible = tmp_path / "profond" / "imbrique" / ".axon" / "memory"
    with patch("src.agents.memory.persistent._memory_dir", return_value=cible):
        _note("fait de test")
    assert (cible / "learnings.md").exists()


def test_axon_note_pose_un_en_tete_au_premier_appel(memoire):
    _note("Première note")
    contenu = (memoire / "learnings.md").read_text(encoding="utf-8")
    assert contenu.startswith("# Learnings")


def test_axon_note_ne_duplique_pas_l_en_tete(memoire):
    _note("Première note")
    _note("Seconde note, différente de la première")
    contenu = (memoire / "learnings.md").read_text(encoding="utf-8")
    assert contenu.count("# Learnings") == 1


def test_axon_note_ajoute_les_notes_successives(memoire):
    _note("Note une, sur le système d'authentification")
    _note("Note deux, sur la base de données PostgreSQL")
    contenu = (memoire / "learnings.md").read_text(encoding="utf-8")
    assert "Note une" in contenu and "Note deux" in contenu


def test_axon_note_date_chaque_entree(memoire):
    """La date sépare les entrées et permet l'archivage — sans elle, le découpage
    par `## AAAA-MM-JJ` ne retrouverait plus les anciennes notes."""
    _note("Fait daté")
    contenu = (memoire / "learnings.md").read_text(encoding="utf-8")
    assert re.search(r"## \d{4}-\d{2}-\d{2}", contenu)


def test_axon_note_retire_les_espaces_superflus(memoire):
    _note("  fait avec des espaces  ")
    contenu = (memoire / "learnings.md").read_text(encoding="utf-8")
    assert "fait avec des espaces" in contenu
    assert "  fait avec des espaces  " not in contenu


def test_axon_note_range_selon_la_nature_de_la_note(memoire):
    """Cinq fichiers, pas un seul : une décision et un blocage ne se relisent pas
    dans le même contexte."""
    _note("Choix de PostgreSQL 15 plutôt que MySQL", kind="decision")
    _note("Le build casse sans NODE_OPTIONS", kind="blocker")
    assert (memoire / "decisions.md").exists()
    assert (memoire / "blockers.md").exists()


def test_axon_note_sans_repo_git_n_ecrit_rien(tmp_path):
    """Hors dépôt, il n'y a pas de projet auquel rattacher la note."""
    with patch("src.agents.memory.persistent._memory_dir", return_value=None):
        resultat = _note("fait orphelin")
    assert "Pas de repo git" in resultat


def test_axon_note_trouve_un_vrai_depot_git(tmp_path):
    """Intégration : la découverte de la racine et l'écriture, ensemble."""
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=False)

    with patch("src.agents.memory.persistent.Path.cwd", return_value=tmp_path), \
         patch("src.agents.shell.tools.get_cwd", return_value=tmp_path):
        _note("Fait de dépôt réel")

    fichier = tmp_path / ".axon" / "memory" / "learnings.md"
    assert fichier.exists()
    assert "Fait de dépôt réel" in fichier.read_text(encoding="utf-8")
