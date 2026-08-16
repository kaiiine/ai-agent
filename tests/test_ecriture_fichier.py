"""Un contenu que son extension rend manifestement faux n'est pas écrit.

Relevé sur un vrai build : `public/config.json` a reçu
`<demoUrl>https://demo.axon.ai/run</demoUrl><license>MIT</license>` — du XML
sous un nom `.json`. Le backend avait sérialisé la structure en balises au lieu
de rendre la chaîne.

Le coût n'a pas été l'écriture ratée. L'agent a ensuite brûlé une dizaine
d'étapes en `xxd`, `cat -A` et `node -e JSON.parse` à chercher un problème
d'encodage, avant de renoncer et de déplacer la config dans un module
TypeScript. Un refus immédiat qui NOMME la cause épargne cette enquête.

Ce que ces tests protègent surtout, c'est la RETENUE du garde : on ne valide que
ce qui se valide sans ambiguïté. Un vérificateur qui refuse du travail correct
est un vérificateur qu'on contourne.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.agents.coding.tools import _contenu_invalide


# ── Ce qui doit être refusé ─────────────────────────────────────────────────
def test_du_xml_sous_une_extension_json_est_refuse():
    """Le cas mesuré, verbatim."""
    refus = _contenu_invalide(
        Path("public/config.json"),
        "<demoUrl>https://demo.axon.ai/run</demoUrl><license>MIT</license>")

    assert refus
    assert "n'est pas du JSON" in refus
    assert "Rien n'a été écrit" in refus


def test_le_refus_nomme_la_cause_probable():
    """Sans la cause, l'agent cherche un problème d'encodage pendant dix étapes."""
    refus = _contenu_invalide(Path("c.json"), "<a>1</a>")

    assert "sérialisé la structure en XML" in refus
    assert "CHAÎNE" in refus


def test_un_json_syntaxiquement_faux_est_refuse():
    assert _contenu_invalide(Path("c.json"), "{demoUrl: cassé,,}")


@pytest.mark.parametrize("nom", ["config.ts", "main.py", "app.css", "conf.yaml"])
def test_une_balise_en_tete_d_un_fichier_de_code_est_refusee(nom):
    refus = _contenu_invalide(Path(nom), "<config>x</config>")

    assert refus
    assert "balise XML" in refus


# ── Ce qui doit passer — la retenue du garde ────────────────────────────────
def test_un_json_valide_passe():
    assert _contenu_invalide(
        Path("c.json"), '{"demoUrl": "https://x", "license": "MIT"}') == ""


def test_du_jsx_en_tete_d_un_tsx_passe():
    """Un composant React commence légitimement par une balise. Le refuser
    bloquerait le cas le plus courant du build front."""
    assert _contenu_invalide(Path("src/app/page.tsx"), "<div>Hello</div>") == ""


def test_du_html_en_tete_d_un_markdown_passe():
    """Le README d'AXON commence par `<div align="center">`."""
    assert _contenu_invalide(Path("README.md"), '<div align="center">') == ""


def test_un_fichier_de_code_normal_passe():
    assert _contenu_invalide(Path("config.ts"), "export const cfg = { a: 1 }") == ""


def test_une_extension_inconnue_n_est_jamais_jugee():
    """On ne valide que ce qui se valide. Inventer une règle pour une extension
    qu'on ne connaît pas refuserait du travail correct."""
    assert _contenu_invalide(Path("truc.xyz"), "<n_importe>quoi</n_importe>") == ""


# ── Le garde est branché sur l'outil, pas seulement disponible ──────────────
def test_l_outil_refuse_reellement_d_ecrire(monkeypatch):
    """Un garde écrit mais non câblé ne protège rien — c'est le défaut qu'on
    vient de trouver deux fois ailleurs dans ce dépôt."""
    from src.agents.coding import tools

    tools.dev_plan.create(["une étape"])          # le plan est un prérequis de l'outil
    resultat = tools.propose_file_change.func(
        path="/tmp/axon_test_config.json",
        content="<demoUrl>x</demoUrl>",
        description="test")

    assert resultat["status"] == "error"
    assert "JSON" in resultat["error"]
    assert not Path("/tmp/axon_test_config.json").exists()
