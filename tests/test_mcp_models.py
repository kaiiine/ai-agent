"""Modèles du client MCP — invariants de données (src/mcp_client/models.py).

Le point sensible est `ToolResult.failed` : le spike de Phase 0 a montré qu'un
serveur peut renvoyer un échec applicatif avec `isError=False`. Confondre les deux
notions ferait mentir la provenance et donnerait un message d'erreur au modèle
comme s'il s'agissait d'une donnée métier.
"""

from __future__ import annotations

from src.mcp_client.models import (
    MCPHealthPolicy,
    MCPServerConfig,
    MCPServerState,
    MCPToolRef,
    ToolDiff,
    ToolResult,
)


def test_failed_couvre_les_deux_sources_d_echec():
    assert ToolResult().failed is False
    assert ToolResult(is_error=True).failed is True
    assert ToolResult(suspected_error=True).failed is True
    assert ToolResult(is_error=True, suspected_error=True).failed is True


def test_is_error_seul_ne_suffit_pas_a_qualifier_un_succes():
    # Cas réel : contenu d'erreur, isError=False -> succès protocolaire, échec métier.
    result = ToolResult(text="backend indisponible", is_error=False, suspected_error=True)
    assert result.is_error is False
    assert result.failed is True


def test_les_collections_ne_sont_pas_partagees_entre_instances():
    a, b = ToolResult(), ToolResult()
    a.images.append(object())
    a.metadata["x"] = 1
    assert b.images == [] and b.metadata == {}

    c, d = MCPServerConfig(name="c"), MCPServerConfig(name="d")
    c.args.append("--flag")
    c.health.failure_patterns.append("boom")
    assert d.args == [] and d.health.failure_patterns == []


def test_valeurs_par_defaut_prudentes():
    cfg = MCPServerConfig(name="s")
    assert cfg.transport == "stdio"          # v1 : stdio uniquement
    assert cfg.enabled is True
    assert cfg.timeouts.connect_s < cfg.timeouts.call_s   # timeouts différenciés
    assert MCPHealthPolicy().consecutive_failures_to_degrade == 3
    assert MCPHealthPolicy().probe_tool is None
    assert MCPToolRef("s", "t", "s.t", "", {}).risk_level == "write"  # défaut prudent


def test_tool_diff_vide():
    assert ToolDiff().is_empty is True
    assert ToolDiff(added=[MCPToolRef("s", "t", "s.t", "", {})]).is_empty is False


def test_etats_serveur_distincts():
    # DEGRADED existe parce que « process MCP vivant » != « backend opérationnel ».
    assert MCPServerState.DEGRADED is not MCPServerState.ERROR
    assert {s.value for s in MCPServerState} == {
        "disabled", "disconnected", "connecting", "ready", "degraded", "error",
    }
