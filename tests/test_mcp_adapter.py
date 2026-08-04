"""Adaptation MCP <-> Axon (src/mcp_client/adapter.py).

Deux exigences y sont vérifiées explicitement :

  - `normalize_result` n'aplatit JAMAIS un `CallToolResult` en `str` — une image
    concaténée dans du texte est une image perdue, et le test « passe » à tort ;
  - un résultat `isError=False` contenant un `failure_pattern` déclaré en config
    donne `result.failed is True`. C'est le correctif central de l'addendum : le
    prédicat est générique, les patterns viennent de la config du serveur.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.mcp_client.adapter import (
    adapt_schema,
    apply_health_policy,
    build_retrieval_text,
    derive_probe_arguments,
    infer_risk,
    normalize_result,
    summarize_schema,
)
from src.mcp_client.models import MCPHealthPolicy, MCPServerConfig, ToolResult


def _tool(name, description="", schema=None):
    return SimpleNamespace(name=name, description=description, inputSchema=schema or {})


def _result(content=None, *, is_error=False, structured=None):
    return SimpleNamespace(content=content or [], isError=is_error, structuredContent=structured)


# ── risk ────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("name,expected", [
    ("delete_object", "destructive"),
    ("remove_entry", "destructive"),
    ("drop_table", "destructive"),
    ("execute_snippet", "execute"),
    ("run_query", "execute"),
    ("eval_expression", "execute"),
    ("get_status", "read"),
    ("list_items", "read"),
    ("search_assets", "read"),
    ("upload_file", "write"),
    ("unknown_thing", "write"),
])
def test_infer_risk(name, expected):
    assert infer_risk(name) == expected


def test_risk_override_de_config_prioritaire():
    cfg = MCPServerConfig(name="alpha", risk_overrides={"get_status": "execute"})
    assert adapt_schema("alpha", _tool("get_status"), cfg).risk_level == "execute"


# ── retrieval ───────────────────────────────────────────────────────────────────
def test_retrieval_text_enrichi():
    cfg = MCPServerConfig(name="alpha", capabilities_hint="modélisation, matériaux, export")
    text = build_retrieval_text("alpha", _tool(
        "execute_snippet", "Run code.", {"properties": {"code": {"type": "string"}}}), cfg)

    assert "Tool: execute_snippet" in text
    assert "Run code." in text
    assert "code: string" in text                      # le schéma est de l'information
    # Ni le serveur ni son hint : identiques sur tous les documents du serveur, ils
    # ne discriminent rien et noient la description. Mesuré sur 22 tools, rang moyen
    # du tool générique : 9,7 avec, 2,0 sans. L'étage 2 est déjà filtré par serveur.
    assert "Server: alpha" not in text
    assert "modélisation, matériaux, export" not in text


def test_summarize_schema():
    schema = {"properties": {"code": {"type": "string"}, "location": {"type": "array"}}}
    assert summarize_schema(schema) == "code: string, location: array"
    assert summarize_schema({}) == "" and summarize_schema(None) == ""


def test_adapt_schema_prefixe_le_nom_public():
    ref = adapt_schema("alpha", _tool("get_status", "d", {"properties": {}}), MCPServerConfig(name="alpha"))
    assert (ref.public_name, ref.server, ref.remote_name) == ("alpha.get_status", "alpha", "get_status")


# ── normalisation multimodale ───────────────────────────────────────────────────
def test_normalize_result_range_les_blocs_par_type_sans_aplatir():
    raw = _result([
        SimpleNamespace(type="text", text="ligne 1"),
        SimpleNamespace(type="image", data="BASE64", mimeType="image/png"),
        SimpleNamespace(type="text", text="ligne 2"),
        SimpleNamespace(type="resource", resource=SimpleNamespace(
            uri="file:///x.glb", mimeType="model/gltf-binary", text=None)),
        SimpleNamespace(type="resource_link", uri="file:///y.glb", mimeType="model/gltf-binary"),
    ], structured={"count": 3})

    out = normalize_result(raw, source_tool="alpha.capture")

    assert out.text == "ligne 1\nligne 2"
    assert len(out.images) == 1 and out.images[0].mime_type == "image/png"
    assert out.images[0].source_tool == "alpha.capture"
    assert [r.uri for r in out.resources] == ["file:///x.glb", "file:///y.glb"]
    assert out.structured == {"count": 3}
    # l'image ne doit apparaître nulle part dans le texte
    assert "BASE64" not in (out.text or "")


def test_normalize_result_trace_les_blocs_non_geres_au_lieu_de_les_jeter():
    out = normalize_result(_result([SimpleNamespace(type="audio", data="x", mimeType="audio/wav")]))
    assert out.metadata["unhandled_block_types"] == ["audio"]


def test_normalize_result_sans_texte():
    out = normalize_result(_result([]))
    assert out.text is None and out.images == [] and out.failed is False


def test_normalize_result_is_error_protocolaire():
    out = normalize_result(_result([SimpleNamespace(type="text", text="boom")], is_error=True))
    assert out.is_error is True and out.error_source == "protocol" and out.failed is True


# ── prédicat de santé déclaratif ────────────────────────────────────────────────
def test_echec_backend_avec_is_error_false_est_detecte():
    """LE cas du spike : succès protocolaire, échec applicatif."""
    policy = MCPHealthPolicy(failure_patterns=["backend unavailable", "not connected"])
    raw = _result([SimpleNamespace(type="text", text="Backend unavailable, check the bridge")])

    out = apply_health_policy(normalize_result(raw), policy)

    assert out.is_error is False          # le protocole dit « succès »
    assert out.suspected_error is True    # le prédicat dit « échec »
    assert out.error_source == "heuristic"
    assert out.failed is True             # seul verdict qui fasse foi


def test_health_policy_insensible_a_la_casse():
    policy = MCPHealthPolicy(failure_patterns=["Backend Unavailable"])
    out = apply_health_policy(ToolResult(text="backend unavailable"), policy)
    assert out.failed is True


def test_health_policy_sans_pattern_ne_touche_a_rien():
    out = apply_health_policy(ToolResult(text="backend unavailable"), MCPHealthPolicy())
    assert out.failed is False and out.error_source is None


def test_health_policy_ne_requalifie_pas_une_erreur_protocolaire():
    out = apply_health_policy(
        ToolResult(text="boom", is_error=True), MCPHealthPolicy(failure_patterns=["boom"]))
    assert out.error_source == "protocol" and out.suspected_error is False


def test_health_policy_laisse_passer_un_vrai_resultat():
    policy = MCPHealthPolicy(failure_patterns=["backend unavailable"])
    out = apply_health_policy(ToolResult(text='{"objects": 3}'), policy)
    assert out.failed is False and out.error_source is None


# ── arguments de sonde ──────────────────────────────────────────────────────────
def test_derive_probe_arguments_remplit_les_champs_requis():
    schema = {
        "properties": {
            "user_prompt": {"type": "string"},
            "count": {"type": "integer"},
            "ratio": {"type": "number"},
            "flag": {"type": "boolean"},
            "items": {"type": "array"},
            "opts": {"type": "object"},
            "optionnel": {"type": "string"},
        },
        "required": ["user_prompt", "count", "ratio", "flag", "items", "opts"],
    }
    args = derive_probe_arguments(schema)

    assert args == {
        "user_prompt": "axon health probe", "count": 0, "ratio": 0,
        "flag": False, "items": [], "opts": {},
    }
    assert "optionnel" not in args       # on ne remplit que le requis


def test_derive_probe_arguments_respecte_default_et_enum():
    schema = {
        "properties": {"mode": {"type": "string", "enum": ["fast", "slow"]},
                       "size": {"type": "integer", "default": 800}},
        "required": ["mode", "size"],
    }
    assert derive_probe_arguments(schema) == {"mode": "fast", "size": 800}


def test_derive_probe_arguments_schema_vide():
    assert derive_probe_arguments({}) == {} and derive_probe_arguments(None) == {}


def test_le_document_de_tool_ne_porte_ni_le_serveur_ni_son_hint():
    """Ces deux-là sont identiques sur tous les documents d'un serveur : ils ne
    discriminent rien à l'étage 2, déjà filtré par serveur, et diluent la
    description. Le hint reste au document de serveur, pour l'étage 1."""
    cfg = MCPServerConfig(name="alpha", capabilities_hint="3D mesh matériaux export")

    doc = build_retrieval_text("alpha", _tool("execute_code", "Exécute du code"), cfg)

    assert "alpha" not in doc
    assert "3D mesh matériaux export" not in doc
    assert "execute_code" in doc and "Exécute du code" in doc
