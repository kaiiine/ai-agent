"""Où AXON écrit doit être déclaré une fois, et déplaçable.

Dix-sept fichiers recalculaient chacun `Path.home() / ".axon"`. L'état était donc
cloué dans `$HOME` — le README annonce `AXON_INSTALL_DIR` pour le dépôt, rien
pour l'état — et aucun endroit ne listait ce qu'AXON écrit.

Ce que ces tests NE gardent pas : les constantes réglées (`_BUDGET_OUTILS`,
`_DOMAINES_MAX`, `_MARGE_CLAUSE`). Elles portent en commentaire le balayage qui
les a fixées ; les déplacer en configuration les couperait de leur
justification — le défaut même que le chantier harnais corrige.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

from src.infra import chemins

RACINE = Path(__file__).resolve().parent.parent

#: `Path.home() / ".axon"` écrit à la main, hors du module qui le déclare.
_EN_DUR = re.compile(r'Path\.home\(\)\s*/\s*["\']\.axon["\']')


def test_aucun_chemin_detat_en_dur():
    """Le seul test qui empêche la duplication de revenir."""
    fautifs = []
    for source in list(RACINE.glob("src/**/*.py")) + list(RACINE.glob("outils/*.py")):
        if source.name == "chemins.py":
            continue
        if _EN_DUR.search(source.read_text(encoding="utf-8", errors="replace")):
            fautifs.append(str(source.relative_to(RACINE)))

    assert fautifs == [], fautifs


def test_le_detecteur_mord():
    """Sans ça, « 0 faute » ne voudrait rien dire."""
    assert _EN_DUR.search('LOG = Path.home() / ".axon" / "x.json"')
    assert not _EN_DUR.search('LOG = chemins.etat("x.json")')


def test_la_racine_par_defaut_est_dans_le_home(monkeypatch):
    monkeypatch.delenv("AXON_STATE_DIR", raising=False)

    assert chemins.racine_etat() == Path.home() / ".axon"


def test_la_surcharge_est_entendue(monkeypatch, tmp_path):
    monkeypatch.setenv("AXON_STATE_DIR", str(tmp_path))

    assert chemins.racine_etat() == tmp_path
    assert chemins.mesures() == tmp_path / "mesures.jsonl"


def test_la_racine_est_lue_a_chaque_appel(monkeypatch, tmp_path):
    """Figée à l'import, la surcharge arriverait toujours trop tard."""
    monkeypatch.setenv("AXON_STATE_DIR", str(tmp_path / "un"))
    premier = chemins.racine_etat()
    monkeypatch.setenv("AXON_STATE_DIR", str(tmp_path / "deux"))

    assert chemins.racine_etat() != premier


def test_rien_nest_cree_a_la_lecture(monkeypatch, tmp_path):
    """Nommer un chemin ne doit pas écrire sur le disque."""
    cible = tmp_path / "jamais-cree"
    monkeypatch.setenv("AXON_STATE_DIR", str(cible))
    chemins.index_outils()
    chemins.base_memoire()

    assert not cible.exists()


@pytest.mark.parametrize("accesseur", [
    "base_memoire", "dernier_thread", "echecs_backend", "pool_de_cles",
    "index_outils", "pid_cron", "mesures", "crons", "journaux_cron",
    "historique_saisie", "memoire_projet",
])
def test_chaque_accesseur_reste_sous_la_racine(accesseur, monkeypatch, tmp_path):
    monkeypatch.setenv("AXON_STATE_DIR", str(tmp_path))
    chemin = getattr(chemins, accesseur)()

    assert tmp_path in chemin.parents or chemin.parent == tmp_path


def test_la_config_mcp_garde_sa_surcharge_propre(monkeypatch, tmp_path):
    """`AXON_MCP_CONFIG` existait avant : elle reste prioritaire."""
    monkeypatch.setenv("AXON_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("AXON_MCP_CONFIG", "/ailleurs/serveurs.json")

    assert chemins.serveurs_mcp() == Path("/ailleurs/serveurs.json")


def test_les_modules_migres_suivent_la_surcharge(tmp_path):
    """Les constantes de module sont calculées à l'import : la surcharge doit
    être posée AVANT. On le vérifie dans un processus neuf."""
    code = (
        "from src.infra.failure_log import LOG_PATH;"
        "from src.agents.cron.store import CRON_FILE;"
        "print(LOG_PATH); print(CRON_FILE)"
    )
    sortie = subprocess.run(
        [sys.executable, "-c", code], cwd=RACINE, capture_output=True, text=True,
        env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path),
             "PYTHONPATH": str(RACINE), "AXON_STATE_DIR": str(tmp_path / "ailleurs")},
    )

    assert str(tmp_path / "ailleurs") in sortie.stdout, sortie.stderr[-400:]
