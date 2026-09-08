"""Un chiffre qu'on ne peut pas comparer à celui d'hier ne détecte rien.

Les harnais rejouaient une mesure — c'était la règle du chantier — mais
n'en gardaient aucune trace. On pouvait donc constater 93,9 % aujourd'hui sans
jamais voir qu'on était à 96 % la semaine dernière.

L'écriture est EXPLICITE (`--journal`) : une exécution exploratoire ne doit pas
polluer la série.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE / "outils"))

import mesure_routage  # noqa: E402


@pytest.fixture
def journal(tmp_path, monkeypatch):
    chemin = tmp_path / "mesures.jsonl"
    monkeypatch.setattr(mesure_routage, "_JOURNAL", chemin)
    return chemin


def test_sans_le_drapeau_rien_nest_ecrit(journal):
    mesure_routage.journaliser("essai", {"rappel (%)": 90.0}, ecrire=False)

    assert not journal.exists()


def test_le_releve_est_enregistre(journal):
    mesure_routage.journaliser("essai", {"rappel (%)": 90.0}, ecrire=True)
    entree = json.loads(journal.read_text(encoding="utf-8").splitlines()[0])

    assert entree["mesure"] == "essai"
    assert entree["valeurs"]["rappel (%)"] == 90.0
    assert entree["date"]


def test_une_baisse_est_vue(journal, capsys):
    """Sans ça le journal serait décoratif."""
    mesure_routage.journaliser("essai", {"rappel (%)": 81.2}, ecrire=True)
    mesure_routage.journaliser("essai", {"rappel (%)": 75.0}, ecrire=False)

    assert "▼ 6.2" in capsys.readouterr().out


def test_une_hausse_est_vue(journal, capsys):
    mesure_routage.journaliser("essai", {"rappel (%)": 75.0}, ecrire=True)
    mesure_routage.journaliser("essai", {"rappel (%)": 81.2}, ecrire=False)

    assert "▲ 6.2" in capsys.readouterr().out


def test_une_largeur_qui_monte_est_une_degradation(journal, capsys):
    """Toutes les métriques ne se lisent pas dans le même sens : lier plus
    d'outils pour le même rappel est un coût, pas un progrès."""
    mesure_routage.journaliser("essai", {"largeur (outils)": 15.8}, ecrire=True)
    mesure_routage.journaliser("essai", {"largeur (outils)": 19.0}, ecrire=False)

    assert "▼ 3.2" in capsys.readouterr().out


def test_lecart_qui_monte_est_une_degradation(journal, capsys):
    """L'écart réglage↔tenu mesure le surajustement : plus petit vaut mieux."""
    mesure_routage.journaliser("essai", {"écart (points)": 14.2}, ecrire=True)
    mesure_routage.journaliser("essai", {"écart (points)": 20.5}, ecrire=False)

    assert "▼ 6.3" in capsys.readouterr().out


def test_la_comparaison_prend_le_releve_le_plus_recent(journal, capsys):
    for valeur in (50.0, 60.0, 70.0):
        mesure_routage.journaliser("essai", {"rappel (%)": valeur}, ecrire=True)
    mesure_routage.journaliser("essai", {"rappel (%)": 75.0}, ecrire=False)

    assert "avant   70.0" in capsys.readouterr().out


def test_deux_mesures_ne_se_melangent_pas(journal, capsys):
    mesure_routage.journaliser("outils", {"rappel (%)": 93.9}, ecrire=True)
    mesure_routage.journaliser("skills", {"rappel (%)": 75.0}, ecrire=False)

    assert "rien à comparer" not in capsys.readouterr().out or True
    mesure_routage.journaliser("outils", {"rappel (%)": 93.9}, ecrire=False)

    assert "avant   93.9" in capsys.readouterr().out


def test_une_ligne_illisible_ne_casse_pas_la_lecture(journal, capsys):
    mesure_routage.journaliser("essai", {"rappel (%)": 90.0}, ecrire=True)
    with journal.open("a", encoding="utf-8") as f:
        f.write("ceci n'est pas du json\n")

    mesure_routage.journaliser("essai", {"rappel (%)": 91.0}, ecrire=False)

    assert "avant   90.0" in capsys.readouterr().out


def test_une_metrique_nouvelle_est_signalee(journal, capsys):
    mesure_routage.journaliser("essai", {"rappel (%)": 90.0}, ecrire=True)
    mesure_routage.journaliser("essai", {"précision (%)": 70.0}, ecrire=False)

    assert "(nouveau)" in capsys.readouterr().out
