"""Surface CLI `/mcp` (src/mcp_client/commands.py).

Ce que ces tests protègent, au-delà du rendu :
  - un tool découvert mais NON exposé (collision de nom runtime) est visible dans
    `/mcp list` et nommé dans `/mcp tools` — sinon il disparaît sans trace ;
  - les trois niveaux de nommage sont affichés côte à côte ;
  - `--deep` n'est JAMAIS implicite : `tools/call` peut avoir des effets de bord ;
  - `add` écrit la config PUIS teste, au lieu de laisser découvrir la panne au
    premier appel de tool.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from types import SimpleNamespace

import pytest

from src.mcp_client.adapter import adapt_schema
from src.mcp_client.commands import (
    handle_mcp,
    render_diagnostic,
    render_diff,
    render_status_table,
    render_tools,
)
from src.mcp_client.models import (
    DiagnosticReport,
    DiagnosticStep,
    MCPServerConfig,
    MCPServerRuntime,
    MCPServerState,
    ToolDiff,
)
from src.mcp_client.runtime import MCPRuntime


def _ref(server="alpha", name="get_status", *, description="Statut du backend", schema=None):
    return adapt_schema(
        server,
        SimpleNamespace(name=name, description=description, inputSchema=schema or {}),
        MCPServerConfig(name=server, capabilities_hint="diagnostic"),
    )


class _FakeRuntime:
    """Surface CLI de `MCPRuntime`, sans boucle ni sous-processus."""

    def __init__(self, status=None, discovered=None, exposed=None, collisions=None,
                 index_state=None):
        self.config_path = "/tmp/mcp_servers.json"
        self._status = status or {}
        self._discovered = discovered or {}
        self._exposed = exposed or {}
        self._collisions = collisions or {}
        self._index_state = index_state or {}
        self.calls: list[tuple] = []
        self.diff = ToolDiff()
        self.report = DiagnosticReport(server="alpha", steps=[
            DiagnosticStep("command resolved", True, "/usr/bin/alpha-server"),
        ])

    def status(self):
        return dict(self._status)

    def discovered(self, server):
        if server not in self._status:
            raise KeyError(server)
        return list(self._discovered.get(server, []))

    def exposed(self, server):
        return list(self._exposed.get(server, []))

    def collisions(self, server):
        return list(self._collisions.get(server, []))

    def index_state(self, server):
        return self._index_state.get(server)

    def _record(self, name, *a):
        self.calls.append((name, *a))
        return self.diff

    def add(self, cfg):
        return self._record("add", cfg)

    def remove(self, s):
        return self._record("remove", s)

    def enable(self, s):
        return self._record("enable", s)

    def disable(self, s):
        return self._record("disable", s)

    def refresh(self, s):
        return self._record("refresh", s)

    def restart(self, s):
        return self._record("restart", s)

    def diagnose(self, server, deep=False):
        self.calls.append(("diagnose", server, deep))
        return self.report


def _runtime_state(state=MCPServerState.READY, error=None):
    return MCPServerRuntime(state=state, last_error=error)


# ── /mcp list ───────────────────────────────────────────────────────────────────
def test_list_sans_serveur():
    assert "Aucun serveur MCP déclaré" in handle_mcp(["list"], _FakeRuntime())


def test_list_affiche_etat_et_derniere_erreur():
    refs = [_ref(name=f"t{i}") for i in range(3)]
    rt = _FakeRuntime(
        status={"alpha": _runtime_state(),
                "beta": _runtime_state(MCPServerState.DEGRADED, "connection reset"),
                "gamma": _runtime_state(MCPServerState.DISABLED)},
        discovered={"alpha": refs, "beta": refs[:2]},
        exposed={"alpha": refs, "beta": refs[:2]},
    )

    out = handle_mcp(["list"], rt)

    assert "NAME" in out and "STATE" in out and "TOOLS" in out and "LAST ERROR" in out
    assert "alpha" in out and "ready" in out
    assert "connection reset" in out
    assert "gamma" in out and "disabled" in out
    lines = out.splitlines()
    assert lines[1].split()[0] == "alpha"       # les serveurs sains en premier
    assert "-" in lines[-1]                     # gamma : aucun tool


def test_list_distingue_tools_exposes_et_decouverts():
    """Un tool découvert mais non exposé est inatteignable : l'écart doit se voir."""
    refs = [_ref(name=f"t{i}") for i in range(3)]
    rt = _FakeRuntime(status={"alpha": _runtime_state()},
                      discovered={"alpha": refs}, exposed={"alpha": refs[:2]},
                      collisions={"alpha": [(refs[2], refs[0].public_name)]})

    out = handle_mcp(["list"], rt)

    assert "2/3" in out
    assert "exposés/découverts" in out
    assert "Collision de nom runtime sur alpha" in out


def test_un_ecart_sans_collision_nest_pas_attribue_a_une_collision():
    """Le message ne doit jamais affirmer une cause non vérifiée : c'est ce
    diagnostic faux qui avait envoyé le debug dans la mauvaise direction."""
    refs = [_ref(name=f"t{i}") for i in range(3)]
    rt = _FakeRuntime(status={"alpha": _runtime_state()},
                      discovered={"alpha": refs}, exposed={"alpha": []})   # 0/3, 0 collision

    out = handle_mcp(["list"], rt)

    assert "0/3" in out
    assert "sans cause identifiée" in out
    assert "ollision" not in out


def test_list_sans_ecart_naffiche_pas_la_legende():
    refs = [_ref(name="t0")]
    rt = _FakeRuntime(status={"alpha": _runtime_state()},
                      discovered={"alpha": refs}, exposed={"alpha": refs})
    out = handle_mcp(["list"], rt)
    assert "exposés/découverts" not in out and " 1 " in out + " "


def test_list_montre_un_routing_etage_1_degrade():
    refs = [_ref(name="t0")]
    rt = _FakeRuntime(status={"alpha": _runtime_state()},
                      discovered={"alpha": refs}, exposed={"alpha": refs},
                      index_state={"alpha": "the input length exceeds the context length"})

    out = handle_mcp(["list"], rt)

    assert "ROUTING" in out and "étage 2" in out
    assert "étage 1 indisponible" in out
    assert "the input length exceeds the context length" in out
    assert "restent exposés et exécutables" in out


def test_list_routing_ok_quand_les_deux_etages_sont_indexes():
    refs = [_ref(name="t0")]
    rt = _FakeRuntime(status={"alpha": _runtime_state()},
                      discovered={"alpha": refs}, exposed={"alpha": refs})
    out = handle_mcp(["list"], rt)
    assert " ok " in out + " " and "étage 1 indisponible" not in out


# ── /mcp tools ──────────────────────────────────────────────────────────────────
def test_tools_affiche_les_trois_noms():
    ref = _ref(name="execute_snippet", description="Exécute un extrait.")
    rt = _FakeRuntime(status={"alpha": _runtime_state()},
                      discovered={"alpha": [ref]}, exposed={"alpha": [ref]})

    out = handle_mcp(["tools", "alpha"], rt)

    assert "REMOTE" in out and "PUBLIC (identité)" in out and "RUNTIME (modèle)" in out
    assert "execute_snippet" in out                 # remote_name
    assert "alpha.execute_snippet" in out           # public_name
    assert "alpha__execute_snippet" in out          # nom runtime
    assert "execute" in out                         # risk_level


def test_tools_signale_les_tools_ignores_pour_collision():
    visible, ignored = _ref(name="a__b"), _ref(name="a.b")
    rt = _FakeRuntime(
        status={"alpha": _runtime_state()},
        discovered={"alpha": [visible, ignored]},
        exposed={"alpha": [visible]},
        collisions={"alpha": [(ignored, visible.public_name)]},
    )

    out = handle_mcp(["tools", "alpha"], rt)

    assert "2 tools découverts, 1 exposés" in out
    assert "1 tool(s) ignoré(s)" in out
    assert "alpha.a.b → alpha__a__b" in out
    assert "déjà pris par alpha.a__b" in out
    assert "PAS atteignables" in out
    # le tool ignoré n'a pas de nom runtime utilisable
    ligne = next(l for l in out.splitlines() if l.startswith("a.b"))
    assert "—" in ligne


def test_tools_serveur_sans_tool():
    rt = _FakeRuntime(status={"alpha": _runtime_state(MCPServerState.ERROR)})
    assert "aucun tool découvert" in handle_mcp(["tools", "alpha"], rt)


def test_serveur_inconnu_message_explicite():
    out = handle_mcp(["tools", "absent"], _FakeRuntime())
    assert "Serveur MCP inconnu : absent" in out


# ── /mcp test ───────────────────────────────────────────────────────────────────
def _full_report():
    return DiagnosticReport(server="alpha", steps=[
        DiagnosticStep("command resolved", True, "/usr/bin/alpha-server"),
        DiagnosticStep("subprocess started", True,
                       "transport stdio ouvert (pid non exposé par le SDK)"),
        DiagnosticStep("MCP initialize", True, "ok", 312.0),
        DiagnosticStep("protocol version", True, "2025-11-25"),
        DiagnosticStep("tools/list", True, "22 tools", 188.0),
        DiagnosticStep("ping", True, "ok", 11.0),
        DiagnosticStep("backend health", None, "non exposé explicitement par ce serveur"),
    ])


def test_test_rend_les_etapes_du_design():
    rt = _FakeRuntime(status={"alpha": _runtime_state()})
    rt.report = _full_report()

    out = handle_mcp(["test", "alpha"], rt)

    # 6 étapes vertes du §9.1, `backend health` indécidable sans --deep,
    # puis l'état d'indexation ajouté par la CLI (v2.5).
    symboles = [l[0] for l in out.splitlines() if l[:1] in ("✓", "✗", "⚠")]
    assert symboles == ["✓"] * 6 + ["⚠", "✓"]
    assert "(312 ms)" in out and "(188 ms)" in out
    assert "22 tools" in out


def test_test_montre_letat_dindexation():
    rt = _FakeRuntime(status={"alpha": _runtime_state()},
                      index_state={"alpha": "contexte de l'embedder dépassé"})
    rt.report = _full_report()

    ligne = next(l for l in handle_mcp(["test", "alpha"], rt).splitlines()
                 if "routing index" in l)

    assert ligne.startswith("✗")
    assert "étage 1 indisponible" in ligne and "repli sur l'étage 2" in ligne
    assert "exposés et exécutables" in ligne


def test_test_ne_fait_pas_grossir_le_rapport_a_chaque_appel():
    """Le rapport du runtime ne doit pas être muté par le rendu."""
    rt = _FakeRuntime(status={"alpha": _runtime_state()})
    rt.report = _full_report()

    premier = handle_mcp(["test", "alpha"], rt)
    second = handle_mcp(["test", "alpha"], rt)

    assert premier == second


def test_la_ligne_subprocess_naffiche_pas_de_pid():
    """Corrigé en v2.2 : le SDK n'expose pas le processus, on ne l'invente pas."""
    rt = _FakeRuntime(status={"alpha": _runtime_state()})
    rt.report = _full_report()

    ligne = next(l for l in handle_mcp(["test", "alpha"], rt).splitlines()
                 if "subprocess started" in l)

    assert "pid non exposé" in ligne
    assert not any(part.isdigit() for part in ligne.split())


def test_deep_nest_jamais_implicite():
    rt = _FakeRuntime(status={"alpha": _runtime_state()})

    handle_mcp(["test", "alpha"], rt)
    handle_mcp(["test", "alpha", "--deep"], rt)

    assert [c for c in rt.calls if c[0] == "diagnose"] == [
        ("diagnose", "alpha", False), ("diagnose", "alpha", True)]


def test_flag_inconnu_renvoie_l_usage():
    rt = _FakeRuntime(status={"alpha": _runtime_state()})
    assert "/mcp list" in handle_mcp(["test", "alpha", "--force"], rt)
    assert not rt.calls


def test_symboles_du_diagnostic():
    report = DiagnosticReport(server="alpha", steps=[
        DiagnosticStep("command resolved", False, "introuvable dans le PATH: alpha"),
    ])
    assert render_diagnostic(report).splitlines()[2].startswith("✗")


# ── cycle de vie ────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("sub", ["enable", "disable", "remove", "refresh", "restart"])
def test_les_operations_de_cycle_de_vie_resynchronisent_l_index(sub):
    rt = _FakeRuntime(status={"alpha": _runtime_state()})
    rt.diff = ToolDiff(added=[_ref(name="nouveau")], removed=[_ref(name="obsolete")])

    out = handle_mcp([sub, "alpha"], rt)

    assert rt.calls[0][:2] == (sub, "alpha")
    assert "index resynchronisé" in out
    assert "nouveau" in out and "obsolete" in out


def test_diff_vide_le_dit():
    rt = _FakeRuntime(status={"alpha": _runtime_state()})
    assert "déjà à jour" in handle_mcp(["refresh", "alpha"], rt)


# ── /mcp add ────────────────────────────────────────────────────────────────────
def test_add_forme_directe_puis_test():
    rt = _FakeRuntime(status={"alpha": _runtime_state()})
    rt.report = _full_report()

    out = handle_mcp(["add", "alpha", "uvx", "--python", "3.11", "alpha-server"], rt)

    kinds = [c[0] for c in rt.calls]
    assert kinds == ["add", "diagnose"]           # config écrite PUIS testée
    cfg = rt.calls[0][1]
    assert cfg.name == "alpha" and cfg.command == "uvx"
    assert cfg.args == ["--python", "3.11", "alpha-server"]
    assert "ajouté" in out and "command resolved" in out


def test_add_assistant_interactif():
    reponses = iter(["uvx", "--python 3.11 alpha-server", "diagnostic, exécution", "get_status"])
    rt = _FakeRuntime(status={"alpha": _runtime_state()})

    handle_mcp(["add", "alpha"], rt, prompt=lambda _q: next(reponses))

    cfg = rt.calls[0][1]
    assert cfg.command == "uvx" and cfg.args == ["--python", "3.11", "alpha-server"]
    assert cfg.capabilities_hint == "diagnostic, exécution"
    assert cfg.health.probe_tool == "get_status"


def test_add_sans_commande_est_refuse():
    rt = _FakeRuntime()
    out = handle_mcp(["add", "alpha"], rt, prompt=lambda _q: "")
    assert "commande vide" in out
    assert not rt.calls                    # rien n'a été écrit en config


# ── usage ───────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("args", [[], ["help"], ["nawak"], ["list", "trop", "d", "args"]])
def test_usage(args):
    out = handle_mcp(args, _FakeRuntime())
    assert "/mcp list" in out and "/mcp test <nom> [--deep]" in out


def test_rendus_purs_sans_runtime():
    """Les fonctions de rendu sont pures : testables sans serveur ni terminal."""
    assert render_diff("alpha", ToolDiff()).startswith("alpha : index déjà à jour")
    assert render_tools("alpha", [], [], []).startswith("alpha : aucun tool")


# ── bout en bout contre un vrai serveur stdio ───────────────────────────────────
_SERVER_SRC = """
import sys
sys.path[:0] = {paths!r}
from mcp.server.fastmcp import FastMCP

app = FastMCP("axon-cli-server")

@app.tool()
def get_status(user_prompt: str) -> str:
    "Statut du backend (lecture seule)."
    return "backend unavailable: bridge not connected"

@app.tool()
def execute_snippet(code: str) -> str:
    "Exécute un extrait."
    return "ok:" + code

app.run()
"""


class _FakeIndex:
    def __init__(self):
        self.docs = {}

    def upsert(self, id, document, metadata):
        self.docs[id] = (document, metadata)

    def delete(self, where):
        pass

    def delete_ids(self, ids):
        for i in ids:
            self.docs.pop(i, None)

    def query_servers(self, query, n=3):
        return ["alpha"]

    def query_tools(self, query, k=7, where=None):
        return [i for i in self.docs if not i.startswith("server:")]


@pytest.mark.skipif(
    importlib.util.find_spec("mcp.server.fastmcp") is None,
    reason="serveur FastMCP indisponible",
)
def test_bout_en_bout_list_tools_et_test_deep(tmp_path):
    path = tmp_path / "mcp_servers.json"
    path.write_text(json.dumps({"servers": {"alpha": {
        "command": sys.executable,
        "args": ["-c", _SERVER_SRC.format(paths=[p for p in sys.path if p])],
        "timeouts": {"connect_s": 30, "list_tools_s": 30, "call_s": 30},
        "health": {"probe_tool": "get_status",
                   "failure_patterns": ["backend unavailable"],
                   "consecutive_failures_to_degrade": 1},
        "capabilities_hint": "diagnostic",
    }}}), encoding="utf-8")

    runtime = MCPRuntime(path, index=_FakeIndex())
    try:
        runtime.start()

        listing = handle_mcp(["list"], runtime)
        assert "alpha" in listing and "ready" in listing and " 2 " in listing + " "

        tools = handle_mcp(["tools", "alpha"], runtime)
        assert "get_status" in tools and "alpha.get_status" in tools
        assert "alpha__get_status" in tools
        assert "read" in tools and "execute" in tools

        # --deep : arguments dérivés du schéma, sonde un tool read-only
        deep = handle_mcp(["test", "alpha", "--deep"], runtime)
        assert "command resolved" in deep and "tools/list" in deep
        assert "pid non exposé" in deep
        assert "backend health" in deep
        assert "✗ backend health" in deep      # le backend est cassé, --deep le voit

        # sans --deep : aucune sonde, étape indécidable
        shallow = handle_mcp(["test", "alpha"], runtime)
        assert "⚠ backend health" in shallow

        assert "index déjà à jour" in handle_mcp(["refresh", "alpha"], runtime)

        assert "désactivé" in handle_mcp(["disable", "alpha"], runtime)
        assert runtime.tools == []
    finally:
        runtime.stop()


def test_le_dispatcher_axon_route_bien_slash_mcp(monkeypatch, tmp_path):
    """Câblage réel : `/mcp` doit atteindre ce module depuis le REPL. Sans config
    déclarée, `mcp_runtime()` est inerte — la commande répond quand même.

    Le test pointe `AXON_MCP_CONFIG` sur un chemin vide : il ne doit jamais lire
    la configuration réelle de la machine ni lancer de sous-processus."""
    from src.mcp_client.runtime import reset_runtime
    from src.ui.commands import SessionConfig, handle_slash

    monkeypatch.setenv("AXON_MCP_CONFIG", str(tmp_path / "absent.json"))
    reset_runtime()
    try:
        panel = handle_slash("/mcp help", {"messages": []}, SessionConfig())
        assert "/mcp list" in panel.renderable.plain

        listing = handle_slash("/mcp list", {"messages": []}, SessionConfig())
        assert "Aucun serveur MCP déclaré" in listing.renderable.plain
    finally:
        reset_runtime()
