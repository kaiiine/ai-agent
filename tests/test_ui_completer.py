"""Autocomplétion des slash-commands, volet `/mcp` (src/ui/completer.py).

La complétion s'exécute à CHAQUE frappe : elle ne doit jamais démarrer le runtime
MCP, lire une configuration ni lancer de sous-processus. Le test le vérifie
explicitement, parce que le coût d'un tel effet de bord ne se voit pas dans une
sortie — il se voit dans un terminal qui se fige.
"""

from __future__ import annotations

import pytest
from prompt_toolkit.document import Document

from src.ui.completer import SlashCompleter


def _complete(text: str) -> list[str]:
    return [c.text for c in SlashCompleter().get_completions(Document(text), None)]


def test_mcp_est_propose_au_premier_niveau():
    assert "/mcp" in _complete("/mc")
    assert "/mcp" in _complete("/")


def test_les_neuf_sous_commandes_sont_proposees():
    assert set(_complete("/mcp ")) == {
        "list", "add", "remove", "enable", "disable", "test", "tools", "refresh", "restart",
    }


@pytest.mark.parametrize("prefixe,attendu", [
    ("/mcp te", ["test"]),
    ("/mcp re", ["remove", "refresh", "restart"]),
    ("/mcp li", ["list"]),
    ("/mcp dis", ["disable"]),
])
def test_filtrage_par_prefixe(prefixe, attendu):
    assert sorted(_complete(prefixe)) == sorted(attendu)


def test_chaque_sous_commande_porte_une_description():
    completions = list(SlashCompleter().get_completions(Document("/mcp "), None))
    assert all(c.display_meta_text for c in completions)


# ── second niveau : noms de serveurs ────────────────────────────────────────────
class _FakeRuntime:
    def status(self):
        from src.mcp_client.models import MCPServerRuntime, MCPServerState

        return {
            "blender": MCPServerRuntime(state=MCPServerState.READY),
            "filesystem": MCPServerRuntime(state=MCPServerState.DISABLED),
        }


@pytest.fixture
def runtime_connu(monkeypatch):
    from src.mcp_client import runtime as runtime_module

    monkeypatch.setattr(runtime_module, "_runtime", _FakeRuntime())


def test_le_nom_du_serveur_est_complete(runtime_connu):
    assert _complete("/mcp test ") == ["blender", "filesystem"]
    assert _complete("/mcp restart ble") == ["blender"]


def test_letat_du_serveur_est_affiche_en_meta(runtime_connu):
    metas = {c.text: c.display_meta_text
             for c in SlashCompleter().get_completions(Document("/mcp tools "), None)}
    assert metas == {"blender": "ready", "filesystem": "disabled"}


@pytest.mark.parametrize("cmd", ["/mcp list ", "/mcp add "])
def test_pas_de_serveur_propose_quand_la_commande_nen_attend_pas(cmd, runtime_connu):
    assert _complete(cmd) == []


def test_deep_propose_apres_le_nom_du_serveur(runtime_connu):
    assert _complete("/mcp test blender ") == ["--deep"]
    assert _complete("/mcp test blender --d") == ["--deep"]
    # --deep n'a de sens que pour `test`
    assert _complete("/mcp tools blender ") == []


# ── la complétion ne doit avoir aucun effet de bord ────────────────────────────
def test_la_completion_ne_demarre_jamais_le_runtime(monkeypatch):
    """Sans runtime déjà construit, aucune proposition — et surtout aucun appel à
    `mcp_runtime()`, qui lirait la config et lancerait des sous-processus."""
    from src.mcp_client import runtime as runtime_module

    monkeypatch.setattr(runtime_module, "_runtime", None)
    monkeypatch.setattr(
        runtime_module, "mcp_runtime",
        lambda: pytest.fail("la complétion ne doit pas démarrer le runtime MCP"),
    )

    assert _complete("/mcp test ") == []
    assert set(_complete("/mcp ")) != set()      # le premier niveau reste disponible
    assert runtime_module._runtime is None


def test_un_runtime_en_erreur_ne_casse_pas_la_completion(monkeypatch):
    class _Broken:
        def status(self):
            raise RuntimeError("boom")

    from src.mcp_client import runtime as runtime_module

    monkeypatch.setattr(runtime_module, "_runtime", _Broken())
    assert _complete("/mcp test ") == []


# ── cohérence avec la surface réellement dispatchée ────────────────────────────
def test_les_sous_commandes_completees_existent_toutes_dans_le_dispatcher():
    """Une complétion qui propose une commande inexistante est un mensonge."""
    from src.mcp_client.commands import _USAGE
    from src.ui.completer import _MCP_SUBCOMMANDS

    for sub in _MCP_SUBCOMMANDS:
        assert f"/mcp {sub}" in _USAGE
