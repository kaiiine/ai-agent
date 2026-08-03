"""Orchestration MCP (src/mcp_client/manager.py).

Invariants du PRD vérifiés ici :
  - un serveur injoignable ne bloque JAMAIS le démarrage des autres ;
  - `call_tool` résout la connexion COURANTE — aucune session n'est capturée, ce
    qui est ce qui rend un tool indexé survivant à un redémarrage du serveur ;
  - la provenance logue `success = not result.failed`, donc `false` sur un échec
    backend renvoyé avec `isError=False`.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import logging
import sys
from types import SimpleNamespace

import pytest

from src.mcp_client.adapter import adapt_schema
from src.mcp_client.config import load_config
from src.mcp_client.manager import MCPClientManager, diff_server_tools
from src.mcp_client.models import (
    MCPHealthPolicy,
    MCPServerConfig,
    MCPServerState,
    MCPTimeouts,
    MCPToolRef,
    ToolResult,
)

run = asyncio.run


class _StubConnection:
    """Même surface que `MCPConnection`, sans sous-processus."""

    def __init__(self, cfg: MCPServerConfig, result: ToolResult | None = None):
        self.config = cfg
        self.runtime = SimpleNamespace(
            state=MCPServerState.READY, last_error=None, tool_count=0,
            protocol_version="test", resolved_command="/bin/true",
        )
        self.result = result or ToolResult(text="ok")
        self.calls: list[tuple] = []
        self.closed = False
        self._tools: list[MCPToolRef] = []
        self.next_tools: list[MCPToolRef] | None = None  # ce que renverra le prochain list_tools

    @property
    def tools(self):
        return list(self._tools)

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        return self.result

    async def open(self):
        return None

    async def close(self):
        self.closed = True

    async def list_tools(self):
        if self.next_tools is not None:
            self._tools = list(self.next_tools)
        return list(self._tools)


def _manager(tmp_path, connections: dict[str, _StubConnection]) -> MCPClientManager:
    manager = MCPClientManager(tmp_path / "mcp_servers.json")
    manager.connections = dict(connections)
    manager.servers = {name: conn.config for name, conn in connections.items()}
    return manager


def _ref(server, name, *, schema=None, description="d"):
    return adapt_schema(
        server,
        SimpleNamespace(name=name, description=description, inputSchema=schema or {}),
        MCPServerConfig(name=server),
    )


# ── exécution ───────────────────────────────────────────────────────────────────
def test_serveur_inconnu_donne_un_resultat_en_echec_pas_une_exception(tmp_path):
    result = run(_manager(tmp_path, {}).call_tool("absent", "t", {}))
    assert result.failed is True and "absent" in result.text


def test_call_tool_resout_la_connexion_courante_et_ne_capture_rien(tmp_path):
    """Preuve de l'absence de closure : on remplace l'objet connexion entre deux
    appels, le second doit partir sur le NOUVEAU (comme après un restart)."""
    first = _StubConnection(MCPServerConfig(name="alpha"), ToolResult(text="ancienne"))
    manager = _manager(tmp_path, {"alpha": first})

    assert run(manager.call_tool("alpha", "t", {})).text == "ancienne"

    second = _StubConnection(MCPServerConfig(name="alpha"), ToolResult(text="nouvelle"))
    manager.connections["alpha"] = second

    assert run(manager.call_tool("alpha", "t", {})).text == "nouvelle"
    assert len(first.calls) == 1 and len(second.calls) == 1


# ── provenance ──────────────────────────────────────────────────────────────────
def _invocations(caplog):
    return [r for r in caplog.records if r.getMessage() == "mcp_tool_invocation"]


def test_provenance_succes(tmp_path, caplog):
    conn = _StubConnection(MCPServerConfig(name="alpha"), ToolResult(text="ok"))
    conn._tools = [_ref("alpha", "execute_snippet")]
    manager = _manager(tmp_path, {"alpha": conn})

    with caplog.at_level(logging.INFO, logger="axon.mcp"):
        run(manager.call_tool("alpha", "execute_snippet", {}))

    record = _invocations(caplog)[0]
    assert record.success is True
    assert record.tool == "alpha.execute_snippet"
    assert record.source == "mcp" and record.server == "alpha"
    assert record.risk_level == "execute"        # inféré depuis la référence indexée
    assert record.duration_ms >= 0


def test_provenance_ne_ment_pas_sur_un_echec_a_is_error_false(tmp_path, caplog):
    """Le correctif central de l'addendum : `not is_error` aurait logué `true`."""
    failed = ToolResult(text="backend unavailable", is_error=False,
                        suspected_error=True, error_source="heuristic")
    manager = _manager(tmp_path, {"alpha": _StubConnection(MCPServerConfig(name="alpha"), failed)})

    with caplog.at_level(logging.INFO, logger="axon.mcp"):
        run(manager.call_tool("alpha", "get_status", {}))

    record = _invocations(caplog)[0]
    assert record.success is False
    assert record.error_source == "heuristic"


# ── démarrage tolérant aux pannes ───────────────────────────────────────────────
def test_un_serveur_injoignable_ne_bloque_pas_les_autres(tmp_path):
    path = tmp_path / "mcp_servers.json"
    path.write_text(json.dumps({"servers": {
        "casse": {"command": "axon-binaire-inexistant-xyz",
                  "reconnect": {"max_retries": 1, "backoff_s": 0}},
        "eteint": {"command": "/bin/true", "enabled": False},
    }}), encoding="utf-8")

    manager = MCPClientManager(path)
    run(manager.start())          # ne doit pas lever
    status = manager.status()

    assert status["casse"].state is MCPServerState.ERROR
    assert "introuvable" in (status["casse"].last_error or "")
    # un serveur désactivé reste visible dans /mcp list, sans process lancé
    assert status["eteint"].state is MCPServerState.DISABLED
    run(manager.stop())


# ── config gérée par le manager ─────────────────────────────────────────────────
def test_add_puis_remove_server_persistent_la_config(tmp_path):
    path = tmp_path / "mcp_servers.json"
    manager = MCPClientManager(path)
    cfg = MCPServerConfig(name="alpha", command="/bin/true", enabled=False,
                          capabilities_hint="diagnostic")

    run(manager.add_server(cfg))
    assert load_config(path)["alpha"].capabilities_hint == "diagnostic"

    run(manager.remove_server("alpha"))
    assert load_config(path) == {}


def test_disable_ferme_la_connexion_et_persiste(tmp_path):
    conn = _StubConnection(MCPServerConfig(name="alpha", command="/bin/true"))
    manager = _manager(tmp_path, {"alpha": conn})

    run(manager.disable("alpha"))

    assert conn.closed is True
    assert conn.runtime.state is MCPServerState.DISABLED
    assert load_config(tmp_path / "mcp_servers.json")["alpha"].enabled is False


def test_serveur_inconnu_pour_les_operations_de_gestion(tmp_path):
    with pytest.raises(KeyError):
        run(_manager(tmp_path, {}).disable("absent"))


# ── diff de tools ───────────────────────────────────────────────────────────────
def test_diff_server_tools():
    schema_v1 = {"properties": {"code": {"type": "string"}}}
    schema_v2 = {"properties": {"code": {"type": "string"}, "timeout": {"type": "integer"}}}

    old = [_ref("alpha", "get_status"), _ref("alpha", "execute_snippet", schema=schema_v1),
           _ref("alpha", "obsolete")]
    new = [_ref("alpha", "get_status"), _ref("alpha", "execute_snippet", schema=schema_v2),
           _ref("alpha", "nouveau")]

    diff = diff_server_tools(old, new)

    assert [r.remote_name for r in diff.added] == ["nouveau"]
    assert [r.remote_name for r in diff.removed] == ["obsolete"]
    assert [r.remote_name for r in diff.changed] == ["execute_snippet"]
    assert diff.changed[0].input_schema == schema_v2      # on garde la version NOUVELLE
    assert diff.is_empty is False


def test_diff_vide_quand_rien_ne_bouge():
    tools = [_ref("alpha", "get_status")]
    assert diff_server_tools(tools, list(tools)).is_empty is True


def test_changement_de_description_est_un_changement():
    old = [_ref("alpha", "get_status", description="ancienne")]
    new = [_ref("alpha", "get_status", description="nouvelle")]
    assert [r.remote_name for r in diff_server_tools(old, new).changed] == ["get_status"]


def test_refresh_renvoie_le_diff_sans_redemarrer(tmp_path):
    conn = _StubConnection(MCPServerConfig(name="alpha"))
    conn._tools = [_ref("alpha", "get_status")]
    manager = _manager(tmp_path, {"alpha": conn})

    conn.next_tools = [_ref("alpha", "get_status"), _ref("alpha", "nouveau")]
    diff = run(manager.refresh("alpha"))

    assert [r.remote_name for r in diff.added] == ["nouveau"]
    assert conn.closed is False        # aucun redémarrage de process


# ── diagnostic ──────────────────────────────────────────────────────────────────
_DIAG_SERVER = """
import sys
sys.path[:0] = {paths!r}
from mcp.server.fastmcp import FastMCP

app = FastMCP("axon-diag-server")

@app.tool()
def get_status(user_prompt: str) -> str:
    "Statut du backend (lecture seule)."
    return "backend unavailable: bridge not connected"

app.run()
"""

_EXPECTED_STEPS = [
    "command resolved", "subprocess started", "MCP initialize",
    "protocol version", "tools/list", "ping", "backend health",
]


def _diag_config(**overrides) -> MCPServerConfig:
    cfg = MCPServerConfig(
        name="alpha",
        command=sys.executable,
        args=["-c", _DIAG_SERVER.format(paths=[p for p in sys.path if p])],
        timeouts=MCPTimeouts(connect_s=30.0, list_tools_s=30.0, call_s=30.0),
        health=MCPHealthPolicy(
            probe_tool="get_status", failure_patterns=["backend unavailable"],
            consecutive_failures_to_degrade=1),
    )
    for key, value in overrides.items():
        setattr(cfg, key, value)
    return cfg


def test_diagnose_commande_introuvable_sarrete_a_la_premiere_etape(tmp_path):
    manager = MCPClientManager(tmp_path / "mcp_servers.json")
    run(manager.add_server(MCPServerConfig(name="alpha", command="axon-binaire-inexistant-xyz",
                                           enabled=False)))
    report = run(manager.diagnose("alpha"))

    assert [s.label for s in report.steps] == ["command resolved"]
    assert report.steps[0].ok is False and report.ok is False


@pytest.mark.skipif(
    importlib.util.find_spec("mcp.server.fastmcp") is None,
    reason="serveur FastMCP indisponible",
)
def test_diagnose_deep_detecte_un_backend_casse(tmp_path):
    """`--deep` sonde un tool read-only avec des arguments dérivés du schéma.
    Le serveur répond `isError=False` : sans prédicat de santé, l'étape passerait."""
    manager = MCPClientManager(tmp_path / "mcp_servers.json")
    run(manager.add_server(_diag_config()))

    report = run(manager.diagnose("alpha", deep=True))
    run(manager.stop())

    assert [s.label for s in report.steps] == _EXPECTED_STEPS
    assert report.steps[0].detail.startswith("/")          # chemin normalisé
    assert report.steps[3].detail                          # version de protocole négociée
    assert report.steps[4].detail == "1 tools"
    assert report.steps[5].ok is True                      # le process MCP répond au ping
    assert report.steps[6].ok is False                     # mais son backend est cassé
    assert report.ok is False


@pytest.mark.skipif(
    importlib.util.find_spec("mcp.server.fastmcp") is None,
    reason="serveur FastMCP indisponible",
)
def test_diagnose_sans_deep_ne_declenche_aucun_appel_de_tool(tmp_path):
    """`tools/call` peut avoir des effets de bord : jamais automatique."""
    manager = MCPClientManager(tmp_path / "mcp_servers.json")
    run(manager.add_server(_diag_config()))

    report = run(manager.diagnose("alpha"))
    run(manager.stop())

    health = report.steps[-1]
    assert health.label == "backend health"
    assert health.ok is None                               # non déterminable, pas « ok »
    assert report.ok is True                               # une étape indécidable n'échoue pas
