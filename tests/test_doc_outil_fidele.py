"""La description d'un outil ne doit pas mentir sur ses paramètres.

Le catalogue donne au modèle le NOM des 105 outils, jamais leur schéma — il coûte
~446 tokens l'unité. Un outil non lié est donc appelé à l'aveugle, sur la foi de
sa description. Mesuré sur `gpt-oss:120b` : appelé ainsi, il invente une
convention plausible — `projectKey` pour `project_key` — et l'appel est refusé.

Une description qui cite un paramètre INEXISTANT transforme cette devinette en
erreur garantie. Vécu : `schedule_task` documentait `interval_seconds` quand le
paramètre s'appelle `interval_sec`.

Le refus de l'outil rattrape le cas — le message pydantic nomme le champ
manquant, et le modèle corrige au tour suivant, mesuré. Mais c'est un tour perdu
pour une faute qui se voit sans modèle.
"""
from __future__ import annotations

import re

import pytest

from src.orchestrator.registry import build_all_tools

#: Une ligne « nom: description » indentée, la forme des blocs Args des docstrings.
_CITE = re.compile(r"^\s{4,8}([a-z][a-z0-9_]*)\s*:", re.M)


@pytest.fixture(scope="module")
def outils() -> list:
    return build_all_tools()


def test_le_detecteur_voit_un_parametre_invente(outils):
    """Sans ça, un « 0 faute » ne voudrait rien dire."""
    faux = _CITE.findall("    interval_seconds: fréquence\n    prompt: quoi faire\n")

    assert faux == ["interval_seconds", "prompt"]


def test_aucune_description_ne_cite_un_parametre_inexistant(outils):
    fautifs: list[tuple[str, list[str]]] = []
    for outil in outils:
        try:
            reels = set(outil.args_schema.model_json_schema()["properties"])
        except Exception:                                    # noqa: BLE001
            continue
        if not reels:
            continue
        inventes = sorted(set(_CITE.findall(outil.description or "")) - reels)
        if inventes:
            fautifs.append((outil.name, inventes))

    assert fautifs == []
