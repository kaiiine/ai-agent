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

from src.agents.shell.ecriture import analyser_ecriture


def _is_file_write(commande: str) -> bool:
    """Le chemin de PRODUCTION, et non plus une liste de motifs parallèle.

    `_is_file_write` comparait des chaînes littérales (« sed -i », « cat > »)
    pendant que `shell_run` décidait, lui, sur `analyser_ecriture`. Deux
    détections pour une seule question : le test pouvait passer alors que le
    garde réel laissait filer."""
    return analyser_ecriture(commande) is not None


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


@pytest.mark.parametrize("commande", [
    # Refus : commande composée.
    "echo x > /tmp/zzz_axon_msg.txt && echo suite",
    # Proposition : contenu lisible en local.
    "echo x > /tmp/zzz_axon_msg.txt",
    # Confirmation : contenu illisible en local.
    "mycommand > /tmp/zzz_axon_msg.log",
    # Confirmation : cible distante.
    'ssh vps "cat > /etc/motd"',
])
def test_aucune_reponse_du_garde_ne_nomme_un_outil_fantome(commande, outils_orchestrateur):
    """Chaque issue proposée doit exister. Le garde a maintenant quatre sorties,
    chacune avec sa consigne ; renvoyer vers un outil absent laisserait l'agent
    tourner en rond, ce qui est précisément ce qu'on lui reprochait.

    Vérifié sur ce que le tool RÉPOND, plus sur le texte du module : la version
    précédente lisait le source à partir d'une chaîne littérale, et n'a donc
    couvert qu'une seule des sorties — jusqu'à ce que cette chaîne disparaisse."""
    import re

    from src.agents.coding.pending import pending_changes
    from src.agents.shell.tools import shell_run

    pending_changes.clear()
    message = shell_run.invoke({"command": commande}).get("message", "")
    pending_changes.clear()

    cites = set(re.findall(r"\b(edit_file|propose_file_change|shell_run)\b", message))
    assert cites <= outils_orchestrateur, (
        f"« {commande} » renvoie vers des outils absents : "
        f"{cites - outils_orchestrateur}")


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
