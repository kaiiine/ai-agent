"""Lifecycle d'une connexion MCP (src/mcp_client/connection.py).

Points vérifiés, tous issus d'une panne réelle ou attendue :
  - `call_tool` ne propage jamais d'exception (une exception tue le tour de
    conversation au lieu de laisser le modèle réagir à l'erreur) ;
  - le `asyncio.Lock` empêche N échecs simultanés de déclencher N redémarrages ;
  - la machine READY / DEGRADED / ERROR distingue « process MCP mort » de
    « process vivant mais backend cassé » ;
  - les timeouts sont bien différenciés (override par tool).

Le dernier test est une intégration stdio réelle contre un serveur MCP minimal
lancé en sous-processus : il valide le transport, pas seulement la logique.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from types import SimpleNamespace

import pytest

from src.mcp_client.connection import MCPConnection
from src.mcp_client.models import (
    MCPHealthPolicy,
    MCPReconnectPolicy,
    MCPServerConfig,
    MCPServerState,
    MCPTimeouts,
)

run = asyncio.run


class _FakeSession:
    """Substitut de `ClientSession` : on teste la couche de lifecycle, pas le SDK."""

    def __init__(self, *, result=None, exc=None, delay=0.0, ping_ok=True, tools=()):
        self.result, self.exc, self.delay, self.ping_ok = result, exc, delay, ping_ok
        self.tools = list(tools)
        self.calls: list[tuple] = []

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.exc:
            raise self.exc
        return self.result

    async def send_ping(self):
        if not self.ping_ok:
            raise RuntimeError("process muet")

    async def list_tools(self):
        return SimpleNamespace(tools=self.tools)


def _text_result(text, *, is_error=False):
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        isError=is_error,
        structuredContent=None,
    )


def _connected(cfg, session):
    """Connexion déjà établie : évite de lancer un sous-processus pour tester la logique."""
    conn = MCPConnection(cfg)
    conn._session = session
    conn.runtime.state = MCPServerState.READY
    return conn


def _cfg(**kw):
    kw.setdefault("name", "alpha")
    return MCPServerConfig(**kw)


# ── call_tool ne fuit jamais ────────────────────────────────────────────────────
def test_exception_de_session_devient_un_tool_result():
    conn = _connected(_cfg(), _FakeSession(exc=RuntimeError("flux rompu")))
    result = run(conn.call_tool("get_status", {}))

    assert result.failed is True
    assert result.error_source == "transport"
    assert "flux rompu" in result.text


def test_timeout_par_tool_prioritaire_sur_le_timeout_global():
    cfg = _cfg(timeouts=MCPTimeouts(call_s=30.0), tool_timeouts={"lent": 0.01})
    conn = _connected(cfg, _FakeSession(delay=5.0, result=_text_result("jamais")))

    result = run(conn.call_tool("lent", {}))

    assert result.error_source == "timeout"
    assert result.failed is True


def test_serveur_injoignable_ne_leve_pas():
    cfg = _cfg(
        command="axon-binaire-inexistant-xyz",
        reconnect=MCPReconnectPolicy(max_retries=1, backoff_s=0.0),
    )
    conn = MCPConnection(cfg)

    result = run(conn.call_tool("get_status", {}))

    assert result.failed is True and result.error_source == "transport"
    assert conn.runtime.state is MCPServerState.ERROR
    assert "introuvable" in (conn.runtime.last_error or "")


# ── santé backend : READY / DEGRADED / ERROR ────────────────────────────────────
def _degrade_cfg(n=3, ping_ok=True):
    cfg = _cfg(health=MCPHealthPolicy(
        failure_patterns=["backend unavailable"], consecutive_failures_to_degrade=n))
    session = _FakeSession(result=_text_result("Backend unavailable"), ping_ok=ping_ok)
    return _connected(cfg, session), session


def test_degraded_apres_n_echecs_consecutifs_quand_le_ping_repond():
    conn, _ = _degrade_cfg(n=3)

    async def scenario():
        states = []
        for _ in range(3):
            result = await conn.call_tool("get_status", {})
            assert result.failed is True and result.error_source == "heuristic"
            states.append(conn.runtime.state)
        return states

    states = run(scenario())
    # process MCP vivant + backend cassé : DEGRADED, pas ERROR, et pas avant le seuil
    assert states == [MCPServerState.READY, MCPServerState.READY, MCPServerState.DEGRADED]


def test_error_quand_le_process_ne_repond_plus_au_ping():
    conn, _ = _degrade_cfg(n=1, ping_ok=False)
    run(conn.call_tool("get_status", {}))
    assert conn.runtime.state is MCPServerState.ERROR


def test_un_succes_reinitialise_le_compteur_et_restaure_ready():
    conn, session = _degrade_cfg(n=1)
    run(conn.call_tool("get_status", {}))
    assert conn.runtime.state is MCPServerState.DEGRADED

    session.result = _text_result('{"objects": 3}')
    result = run(conn.call_tool("get_status", {}))

    assert result.failed is False
    assert conn.runtime.state is MCPServerState.READY
    assert conn._consecutive_failures == 0


def test_le_seuil_est_bien_consecutif():
    conn, session = _degrade_cfg(n=2)

    async def scenario():
        await conn.call_tool("t", {})                       # échec 1
        session.result = _text_result("ok")
        await conn.call_tool("t", {})                       # succès -> reset
        session.result = _text_result("Backend unavailable")
        await conn.call_tool("t", {})                       # échec 1 à nouveau
        return conn.runtime.state

    assert run(scenario()) is MCPServerState.READY


# ── le lock de connexion ────────────────────────────────────────────────────────
def test_le_lock_empeche_les_redemarrages_concurrents():
    """Sans lock, trois tools qui échouent en même temps lancent trois
    sous-processus concurrents et laissent des PID orphelins."""
    conn = MCPConnection(_cfg())
    session = _FakeSession(result=_text_result("ok"))
    restarts: list[int] = []

    async def fake_restart():
        restarts.append(1)
        await asyncio.sleep(0.05)          # fenêtre pendant laquelle les autres attendent
        conn._session = session
        conn.runtime.state = MCPServerState.READY

    conn.restart = fake_restart

    async def scenario():
        await asyncio.gather(*(conn.ensure_connected() for _ in range(3)))

    run(scenario())
    assert len(restarts) == 1


def test_close_est_idempotent():
    conn = _connected(_cfg(), _FakeSession())

    async def scenario():
        await conn.close()
        await conn.close()

    run(scenario())
    assert conn.runtime.state is MCPServerState.DISCONNECTED


def test_open_refuse_un_serveur_desactive():
    conn = MCPConnection(_cfg(enabled=False, command="/bin/sh"))
    assert conn.runtime.state is MCPServerState.DISABLED
    with pytest.raises(Exception, match="désactivé"):
        run(conn.open())


# ── découverte ──────────────────────────────────────────────────────────────────
def test_list_tools_produit_des_references_stables():
    cfg = _cfg(capabilities_hint="diagnostic")
    session = _FakeSession(tools=[
        SimpleNamespace(name="get_status", description="Statut", inputSchema={"properties": {}}),
        SimpleNamespace(name="execute_snippet", description="Exécute",
                        inputSchema={"properties": {"code": {"type": "string"}}}),
    ])
    conn = _connected(cfg, session)

    refs = run(conn.list_tools())

    assert [r.public_name for r in refs] == ["alpha.get_status", "alpha.execute_snippet"]
    assert [r.risk_level for r in refs] == ["read", "execute"]
    assert conn.runtime.tool_count == 2
    # une référence ne porte aucune session : c'est ce qui la rend réutilisable
    assert not any(hasattr(r, "session") or hasattr(r, "connection") for r in refs)


# ── intégration stdio réelle ────────────────────────────────────────────────────
_SERVER_SRC = """
import sys
sys.path[:0] = {paths!r}
from mcp.server.fastmcp import FastMCP

app = FastMCP("axon-test-server")

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


@pytest.mark.skipif(
    importlib.util.find_spec("mcp.server.fastmcp") is None,
    reason="serveur FastMCP indisponible",
)
def test_integration_stdio_bout_en_bout(tmp_path):
    """Vraie chaîne : sous-processus stdio -> initialize -> tools/list -> call_tool.

    Le serveur renvoie volontairement un échec applicatif avec `isError=False`,
    comme le serveur observé au spike : le prédicat de santé doit le rattraper.
    """
    cfg = MCPServerConfig(
        name="alpha",
        command=sys.executable,
        args=["-c", _SERVER_SRC.format(paths=[p for p in sys.path if p])],
        timeouts=MCPTimeouts(connect_s=30.0, list_tools_s=30.0, call_s=30.0),
        health=MCPHealthPolicy(
            probe_tool="get_status",
            failure_patterns=["backend unavailable"],
            consecutive_failures_to_degrade=1,
        ),
        capabilities_hint="diagnostic, exécution",
    )
    conn = MCPConnection(cfg)

    async def scenario():
        await conn.open()
        assert conn.runtime.state is MCPServerState.READY
        assert conn.runtime.protocol_version                    # version négociée
        assert conn.runtime.resolved_command.startswith("/")    # chemin normalisé

        refs = await conn.list_tools()
        names = {r.remote_name: r for r in refs}
        assert {"get_status", "execute_snippet"} <= set(names)
        assert names["get_status"].risk_level == "read"
        assert names["execute_snippet"].risk_level == "execute"

        ok = await conn.call_tool("execute_snippet", {"code": "42"})
        assert ok.failed is False and ok.text == "ok:42"
        assert conn.runtime.state is MCPServerState.READY

        # succès protocolaire, échec applicatif
        ko = await conn.call_tool("get_status", {"user_prompt": "sonde"})
        assert ko.is_error is False
        assert ko.suspected_error is True and ko.error_source == "heuristic"
        assert conn.runtime.state is MCPServerState.DEGRADED   # ping OK -> pas ERROR

        assert await conn.ping() is True
        await conn.close()
        assert conn.runtime.state is MCPServerState.DISCONNECTED

    run(scenario())
