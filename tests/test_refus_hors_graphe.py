"""Un refus d'outil hors du graphe est irrécupérable — il faut le dire.

Vécu, sur « crée un fichier x.py, puis supprime a.txt » routé vers l'agent de
code :

    $ mkdir -p /tmp/axon-essai && rm -f /tmp/axon-essai/a.txt && ls -la    ✓
    $ mkdir -p /tmp/axon-essai && rm -f /tmp/axon-essai/a.txt && ls -la    ✓
    $ mkdir -p /tmp/axon-essai && rm -f /tmp/axon-essai/a.txt && ls -la    ✓

Rien n'avait tourné. La confirmation passe par un `interrupt()` du graphe, que la
boucle du specialist n'a pas : `shell_run` rendait `requires_confirmation`, l'écran
peignait un ✓ — le statut n'a pas d'`exit_code`, et le défaut à 0 vaut succès — et
le modèle rejouait, puis demandait à l'utilisateur de valider un questionnaire qui
ne pouvait pas s'afficher.

Le démon cron avait déjà tiré la règle : `_STATUTS_DE_REFUS`.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.agents.coding.specialist import _STATUTS_DE_REFUS, _refus_definitif
from src.agents.shell.tools import shell_run


def test_une_commande_destructive_hors_graphe_ne_sexecute_pas(tmp_path):
    """Le garde tient sans le graphe — c'est bien l'affichage qui mentait."""
    cible = tmp_path / "cible.txt"
    cible.write_text("x", encoding="utf-8")

    reponse = shell_run.invoke({"command": f"rm -f {cible}"})

    assert reponse["status"] == "requires_confirmation"
    assert cible.exists()


@pytest.mark.parametrize("statut", _STATUTS_DE_REFUS)
def test_un_refus_devient_une_impasse_explicite(statut):
    resultat = _refus_definitif("shell_run", {"status": statut, "command": "rm -rf /tmp/x",
                                              "reason": "destructive"})
    assert resultat["status"] == "error"
    assert "Ne relance pas" in resultat["error"]
    assert "propose_file_change" in resultat["error"]


def test_un_resultat_normal_passe_intact():
    normal = {"status": "ok", "stdout": "hello", "exit_code": 0}
    assert _refus_definitif("shell_run", normal) is normal


def test_laffichage_ne_peint_pas_en_vert_une_commande_refusee():
    """`exit_code` est ABSENT d'un refus ; `result.get("exit_code", 0)` valait
    donc succès. Garde de comportement écrite sur le texte, faute de pouvoir
    piloter Rich ici."""
    src = Path("src/ui/streaming.py").read_text(encoding="utf-8")
    bloc = src[src.index('elif tool_name == "shell_run":'):]
    bloc = bloc[:bloc.index('exit_code = result.get("exit_code", 0)')]
    assert 'requires_confirmation' in bloc
    assert 'blocked' in bloc
