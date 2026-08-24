"""L'orchestrateur doit pouvoir MODIFIER un fichier, pas seulement le lire.

Vécu, sur « commente ces deux lignes dans ~/.config/hypr/keybindings.conf » :

  1. `shell_run` refuse `sed -i` et renvoie le modèle vers `edit_file` /
     `propose_file_change` ;
  2. ces deux outils n'étaient enregistrés QUE pour le specialist de code ;
  3. le modèle a donc tenté `run_coding_agent` — dont la description ne parle
     que de projets de code — s'est trompé d'argument, et a fini par rendre un
     mode d'emploi à l'utilisateur.

Un message d'erreur qui nomme une porte inexistante est pire qu'un refus sec :
il fait tourner le modèle en rond avant qu'il n'abandonne.

Ce n'est pas une couche de plus. Les changements proposés étaient DÉJÀ drainés
après chaque tour par `ui/streaming.py`. L'outil existait, son consommateur
existait ; seul le fil entre les deux manquait.
"""
from __future__ import annotations

import pytest

from src.agents.shell.tools import _is_file_write


@pytest.fixture(scope="module")
def outils_orchestrateur() -> set[str]:
    from src.orchestrator.registry import build_all_tools
    return {t.name for t in build_all_tools()}


def test_le_shell_refuse_toujours_d_ecrire(outils_orchestrateur):
    """La garde reste : une écriture passe par un diff relu, jamais par `sed -i`."""
    assert _is_file_write("sed -i 's/a/b/' ~/.config/hypr/keybindings.conf")
    assert _is_file_write("cat > ~/.ssh/config")
    assert not _is_file_write("cat ~/.ssh/config")


def test_la_porte_que_le_refus_designe_existe_vraiment(outils_orchestrateur):
    """Le cœur du bug : le message d'erreur nomme `edit_file` et
    `propose_file_change`. Ils doivent être là."""
    assert "edit_file" in outils_orchestrateur
    assert "propose_file_change" in outils_orchestrateur


def test_le_message_de_refus_ne_nomme_que_des_outils_disponibles(outils_orchestrateur):
    """Si le libellé change un jour, il ne doit pas renvoyer vers un fantôme."""
    import re
    from pathlib import Path

    # Le module, pas la fonction : `shell_run` est un `StructuredTool` une fois
    # décoré, et `inspect.getsource` ne sait pas le lire.
    source = (Path(__file__).resolve().parents[1]
              / "src" / "agents" / "shell" / "tools.py").read_text(encoding="utf-8")
    debut = source.index("Écriture de fichier via shell bloquée")
    message = source[debut:debut + 400]
    cites = set(re.findall(r"\b(edit_file|propose_file_change|shell_run)\b", message))
    assert cites, "le message ne nomme plus aucune issue"
    assert cites <= outils_orchestrateur, (
        f"le refus renvoie vers des outils absents : {cites - outils_orchestrateur}")


def test_modifier_un_fichier_de_config_route_les_outils_d_ecriture():
    """Un fichier de configuration n'est pas « un projet de code » : la demande
    ne doit pas dépendre de `run_coding_agent` pour aboutir."""
    from src.orchestrator.registry import build_all_tools
    from src.orchestrator.tool_retriever import ToolRetriever

    retriever = ToolRetriever(build_all_tools())
    for requete in (
        "commente ces deux lignes dans ~/.config/hypr/keybindings.conf",
        "change la valeur de timeout dans mon fichier de config",
        "ajoute une ligne à mon .zshrc",
    ):
        outils = {t.name for t in retriever.get(requete)}
        assert "edit_file" in outils, f"pas d'outil d'édition pour « {requete} »"


def test_le_specialist_garde_la_main_sur_un_projet_de_code():
    """L'orchestrateur ne doit pas se mettre à éditer du code lui-même : quand
    `coding` gagne l'étage 1, les outils de fichier lui sont retirés."""
    from src.orchestrator.registry import build_all_tools
    from src.orchestrator.tool_retriever import ToolRetriever

    retriever = ToolRetriever(build_all_tools())
    outils = {t.name for t in retriever.get("corrige le bug dans mon application next.js")}
    assert "run_coding_agent" in outils
    assert "edit_file" not in outils


def test_les_changements_proposes_sont_bien_consommes():
    """Sans ce drain, `edit_file` empilerait des propositions que personne
    n'applique — un cul-de-sac différent, mais un cul-de-sac."""
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1]
              / "src" / "ui" / "streaming.py").read_text(encoding="utf-8")
    assert "pending_changes" in source
    assert "auto_write_all" in source and "review_pending" in source
