"""Un nom de fichier ne doit pas être un morceau de code.

Vécu à l'écran : l'agent devait lire un `.xls` et a écrit 1,3 Ko de Python
valide dans un fichier nommé `max_rows:` — le nom vient de son propre script,
`def df_to_markdown(df, max_rows=20):`. Le fichier n'a ni extension ni nom
utilisable : il ne se lance pas, ne se relit pas, et l'agent a continué comme si
de rien n'était.

Le chemin n'était validé NULLE PART. Seul le contenu l'était, contre son
extension (`_contenu_invalide`). Ces gardes sont le symétrique.

Les deux règles ont été mesurées sur le disque réel de l'utilisateur avant
d'être écrites — c'est ce qui les distingue d'une intuition :

    92 445 fichiers · « finit par : »        1 accroché — le fautif
    92 445 fichiers · « contient (…=…) »     0 accroché
     1 280 sans extension · Python structuré 1 accroché — le même

Une règle plus large — toute ponctuation de code dans le nom — en aurait rejeté
1 845 : les crochets de Next.js et les hachages base64 des caches Android sont
de vrais noms de fichiers.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.agents.coding.tools import _chemin_invalide

_PYTHON = "import os\n\ndef traite(df, max_rows=20):\n    return df.head(max_rows)\n"


# ── le cas vécu ───────────────────────────────────────────────────────────────
def test_le_nom_issu_dune_signature_est_refuse():
    refus = _chemin_invalide(Path("max_rows:"), _PYTHON)

    assert refus and "morceau de code" in refus


def test_du_python_sans_extension_est_refuse():
    refus = _chemin_invalide(Path("/tmp/monscript"), _PYTHON)

    assert refus and ".py" in refus


# ── ce qui doit passer — mesuré sur 92 445 fichiers réels ─────────────────────
@pytest.mark.parametrize("chemin", [
    "/tmp/x.py",
    "/tmp/Makefile",
    "/tmp/LICENSE",
    "/tmp/Dockerfile",
    "/tmp/a/[turbopack]_runtime.js",
    "/tmp/a/[root-of-the-server]__974941ed._.js",
    "/tmp/cache/6Z0WEAtce5JcsAUIxn1jhr5IU28=",
    "/tmp/mon fichier, version 2.txt",
])
def test_un_vrai_nom_de_fichier_passe(chemin):
    assert _chemin_invalide(Path(chemin), _PYTHON if chemin.endswith(".py") else "x") == ""


def test_un_fichier_sans_extension_sans_python_passe():
    """`Makefile`, `LICENSE`, `Dockerfile` vivent sans extension."""
    assert _chemin_invalide(Path("/tmp/Makefile"), "all:\n\tgcc -o x x.c\n") == ""


def test_un_texte_court_sans_extension_passe():
    """`.gitkeep`, un marqueur, une note : rien à refuser."""
    assert _chemin_invalide(Path("/tmp/VERSION"), "1.2.3") == ""


def test_du_python_avec_son_extension_passe():
    assert _chemin_invalide(Path("/tmp/script.py"), _PYTHON) == ""


# ── la garde ne doit pas être vide ────────────────────────────────────────────
def test_le_detecteur_de_signature_mord():
    """Sans ça, « aucun faux positif » ne voudrait rien dire."""
    for nom in ("f(x=1)", "def truc(a, b=2):", "resultat:"):
        assert _chemin_invalide(Path(nom), "x"), nom


def test_le_refus_dit_quoi_faire():
    """Un refus qui ne nomme pas la correction coûte une enquête à l'agent —
    c'est la leçon de `_contenu_invalide`, dix étapes brûlées en `xxd`."""
    refus = _chemin_invalide(Path("max_rows:"), _PYTHON)

    assert "extension" in refus and "Rien n'a été écrit" in refus


# ── le chemin réel de l'outil ─────────────────────────────────────────────────
def test_propose_file_change_refuse_le_chemin(tmp_path):
    from src.agents.coding.pending import dev_plan, pending_changes
    from src.agents.coding.tools import propose_file_change

    dev_plan.clear()
    pending_changes.clear()
    sortie = propose_file_change.invoke(
        {"path": str(tmp_path / "max_rows:"), "content": _PYTHON})

    assert sortie["status"] == "error"
    assert not (tmp_path / "max_rows:").exists()
