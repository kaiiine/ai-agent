"""Intégration Axon des tools MCP (src/mcp_client/registry.py).

Ce que ces tests protègent :
  - l'index reçoit le `retrieval_text` enrichi, PAS la description brute ;
  - le serveur est indexé séparément, sinon l'étage 1 du routing n'existe pas ;
  - le resync est INCRÉMENTAL et part du `ToolDiff` de `manager.refresh()` ;
  - un `ToolResult.failed` arrive au modèle comme une ERREUR d'outil — sinon il
    raisonne sur un message de panne comme sur une donnée métier ;
  - un tool MCP et un tool natif sont indiscernables pour le runtime de tools.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import BaseTool, tool as native_tool
from langgraph.graph import END, START, StateGraph, MessagesState
from langgraph.prebuilt import ToolNode

from src.mcp_client.adapter import adapt_schema
from src.mcp_client.models import MCPServerConfig, MCPToolRef, ToolDiff, ToolResult, ImageArtifact
from src.mcp_client.registry import (
    MCP_SERVER_SOURCE,
    MCP_SOURCE,
    ChromaToolIndex,
    build_mcp_tools,
    build_server_document,
    execute_mcp_tool,
    format_tool_result,
    make_mcp_tool,
    register_server_tools,
    resync_index,
    route,
    runtime_tool_name,
    tool_metadata,
    unregister_server_tools,
)

run = asyncio.run

_SCHEMA = {"type": "object", "properties": {"code": {"type": "string"}}, "required": ["code"]}


def _ref(server="alpha", name="get_status", *, description="Statut du backend", schema=None,
         hint="diagnostic, exécution"):
    return adapt_schema(
        server,
        SimpleNamespace(name=name, description=description, inputSchema=schema or {}),
        MCPServerConfig(name=server, capabilities_hint=hint),
    )


class _FakeIndex:
    """Index en mémoire : la logique d'enregistrement se teste sans embeddings."""

    def __init__(self, *, servers=(), tools=()):
        self.docs: dict[str, tuple[str, dict]] = {}
        self.deleted_where: list[dict] = []
        self.deleted_ids: list[str] = []
        self.queries: list[tuple] = []
        self._servers, self._tools = list(servers), list(tools)

    def upsert(self, id, document, metadata):
        self.docs[id] = (document, metadata)

    def delete(self, where):
        self.deleted_where.append(where)

    def delete_ids(self, ids):
        self.deleted_ids.extend(ids)

    def query_servers(self, query, n=3):
        self.queries.append(("servers", query, n))
        return list(self._servers)

    def query_tools(self, query, k=7, where=None):
        self.queries.append(("tools", query, k, where))
        return list(self._tools)


class _FakeManager:
    def __init__(self, refs, result: ToolResult | None = None):
        self._refs = list(refs)
        self.servers = {"alpha": MCPServerConfig(name="alpha", capabilities_hint="diagnostic")}
        self.calls: list[dict] = []
        self.result = result or ToolResult(text="ok")

    async def list_tools(self, server):
        return [r for r in self._refs if r.server == server]

    async def call_tool(self, server, tool, arguments):
        self.calls.append({"server": server, "tool": tool, "arguments": arguments})
        return self.result


# ── indexation ──────────────────────────────────────────────────────────────────
def test_le_document_indexe_est_le_retrieval_text_pas_la_description():
    """« Execute Python code » matche mal « fais-moi un logo 3D » : c'est le
    document enrichi qui est indexé."""
    refs = [_ref(name="execute_snippet", description="Execute code.", schema=_SCHEMA)]
    index = _FakeIndex()

    run(register_server_tools(_FakeManager(refs), "alpha", index))

    document, metadata = index.docs["alpha.execute_snippet"]
    assert document == refs[0].retrieval_text
    assert document != refs[0].description
    assert "Capabilities: diagnostic, exécution" in document
    assert "code: string" in document
    assert metadata == {"source": MCP_SOURCE, "server": "alpha", "tool": "execute_snippet",
                        "public_name": "alpha.execute_snippet", "risk_level": "execute"}


def test_le_serveur_est_indexe_pour_l_etage_1_du_routing():
    refs = [_ref(name="get_status"), _ref(name="execute_snippet", description="Exécute")]
    index = _FakeIndex()

    run(register_server_tools(_FakeManager(refs), "alpha", index))

    document, metadata = index.docs["server:alpha"]
    assert metadata == {"source": MCP_SERVER_SOURCE, "server": "alpha"}
    assert "Server: alpha" in document
    assert "get_status" in document and "execute_snippet" in document
    assert "Capabilities: diagnostic" in document   # capabilities_hint du serveur


def test_build_server_document_sans_config():
    assert "Capabilities: \n" in build_server_document("alpha", [_ref()], None)


def test_unregister_retire_les_tools_et_le_document_de_serveur():
    index = _FakeIndex()
    unregister_server_tools("alpha", index)

    assert index.deleted_where == [
        {"$and": [{"source": MCP_SOURCE}, {"server": "alpha"}]},
        {"$and": [{"source": MCP_SERVER_SOURCE}, {"server": "alpha"}]},
    ]


def test_tool_metadata_porte_le_risque():
    assert tool_metadata(_ref(name="delete_object"))["risk_level"] == "destructive"


# ── resync incrémental ──────────────────────────────────────────────────────────
def test_resync_reindexe_uniquement_ce_qui_a_bouge():
    added, changed, removed = _ref(name="nouveau"), _ref(name="modifie"), _ref(name="obsolete")
    index = _FakeIndex()
    tools = [added, changed]

    resync_index(ToolDiff(added=[added], changed=[changed], removed=[removed]),
                 "alpha", index, tools=tools, cfg=MCPServerConfig(name="alpha"))

    assert set(index.docs) == {"alpha.nouveau", "alpha.modifie", "server:alpha"}
    assert index.deleted_ids == ["alpha.obsolete"]


def test_resync_ne_fait_rien_sur_un_diff_vide():
    index = _FakeIndex()
    resync_index(ToolDiff(), "alpha", index, tools=[_ref()])
    assert index.docs == {} and index.deleted_ids == []


def test_resync_ne_regenere_pas_le_document_serveur_pour_un_simple_changement():
    """Le document de serveur liste les NOMS de tools : un schéma modifié ne le
    change pas, inutile de le réécrire."""
    index = _FakeIndex()
    resync_index(ToolDiff(changed=[_ref(name="modifie")]), "alpha", index, tools=[_ref()])
    assert "server:alpha" not in index.docs


# ── routing à deux étages ───────────────────────────────────────────────────────
def test_routing_filtre_l_etage_tools_sur_les_serveurs_retenus():
    index = _FakeIndex(servers=["alpha", "beta"], tools=["alpha.execute_snippet"])

    assert route("crée un objet", index, top_servers=2, k=5) == ["alpha.execute_snippet"]

    assert index.queries[0] == ("servers", "crée un objet", 2)
    kind, query, k, where = index.queries[1]
    assert (kind, k) == ("tools", 5)
    assert where == {"server": {"$in": ["alpha", "beta"]}}


def test_routing_sans_serveur_pertinent_ne_cherche_pas_de_tool():
    index = _FakeIndex(servers=[], tools=["alpha.get_status"])
    assert route("météo à Paris", index) == []
    assert len(index.queries) == 1                 # l'étage 2 n'a pas été interrogé


# ── index Chroma réel (embeddings déterministes, aucun réseau) ──────────────────
def _chroma_index():
    from langchain_core.embeddings import DeterministicFakeEmbedding

    return ChromaToolIndex(DeterministicFakeEmbedding(size=32),
                           collection_name=f"test_{uuid.uuid4().hex}")


def test_chroma_index_filtre_bien_serveurs_et_tools():
    index = _chroma_index()
    refs = [_ref(server="alpha", name="get_status"), _ref(server="beta", name="read_file")]
    run(register_server_tools(_FakeManager(refs), "alpha", index))
    run(register_server_tools(_FakeManager(refs), "beta", index))

    # étage 1 : ne remonte que des documents de serveur
    servers = index.query_servers("statut du backend", n=5)
    assert set(servers) == {"alpha", "beta"}

    # étage 2 : filtré sur un seul serveur
    tools = index.query_tools("statut", k=10, where={"server": {"$in": ["alpha"]}})
    assert tools == ["alpha.get_status"]


def test_chroma_index_supprime_par_filtre():
    index = _chroma_index()
    refs = [_ref(server="alpha", name="get_status")]
    run(register_server_tools(_FakeManager(refs), "alpha", index))
    assert index.query_tools("statut", k=5) == ["alpha.get_status"]

    unregister_server_tools("alpha", index)

    assert index.query_tools("statut", k=5) == []
    assert index.query_servers("statut", n=5) == []


# ── exécution ───────────────────────────────────────────────────────────────────
def test_execute_mcp_tool_passe_par_le_manager_sans_capturer_de_connexion():
    manager = _FakeManager([], ToolResult(text="fait"))
    ref = _ref(name="execute_snippet", schema=_SCHEMA)

    result = run(execute_mcp_tool(ref, {"code": "42"}, manager))

    assert result.text == "fait"
    assert manager.calls == [{"server": "alpha", "tool": "execute_snippet",
                              "arguments": {"code": "42"}}]
    # la référence reste inerte : aucune session, aucune connexion attachée
    assert not any(hasattr(ref, attr) for attr in ("session", "connection", "_conn"))


@pytest.mark.parametrize("public,expected", [
    ("alpha.get_status", "alpha__get_status"),
    ("alpha.execute-snippet", "alpha__execute-snippet"),
    ("alpha.tool with space", "alpha__tool_with_space"),
])
def test_runtime_tool_name_est_accepte_par_le_function_calling(public, expected):
    import re

    assert runtime_tool_name(public) == expected
    assert re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", runtime_tool_name(public))


# ── présentation du résultat au modèle ──────────────────────────────────────────
def test_un_echec_est_presente_comme_une_erreur_d_outil():
    """Invariant central : sans enveloppe, le modèle lirait « backend
    injoignable » comme s'il s'agissait de l'état réel du système."""
    failed = ToolResult(text="backend unavailable", is_error=False,
                        suspected_error=True, error_source="heuristic")

    payload = json.loads(format_tool_result(failed, _ref()))

    assert payload["status"] == "error"
    assert payload["error_source"] == "heuristic"
    assert payload["tool"] == "alpha.get_status"
    assert "backend unavailable" in payload["message"]
    assert "ne pas interpréter" in payload["note"].lower()


def test_un_succes_est_rendu_tel_quel():
    assert format_tool_result(ToolResult(text='{"objects": 3}'), _ref()) == '{"objects": 3}'
    assert format_tool_result(ToolResult(structured={"n": 1}), _ref()) == '{"n": 1}'


def test_un_resultat_non_textuel_est_decrit_sans_etre_aplati():
    result = ToolResult(images=[ImageArtifact(data="BASE64", mime_type="image/png")])

    content = format_tool_result(result, _ref(name="capture"))

    assert "1 image(s)" in content
    assert "BASE64" not in content          # l'image n'est jamais inlinée dans le texte
    assert result.images[0].data == "BASE64"  # elle reste intacte dans le ToolResult


# ── enveloppe LangChain ─────────────────────────────────────────────────────────
def _sync_submit(coro):
    return asyncio.run(coro)


def test_make_mcp_tool_produit_un_basetool_standard():
    manager = _FakeManager([], ToolResult(text="fait"))
    tool = make_mcp_tool(_ref(name="execute_snippet", schema=_SCHEMA), manager, submit=_sync_submit)

    assert isinstance(tool, BaseTool)
    assert tool.name == "alpha__execute_snippet"
    assert tool.description == "Statut du backend"
    assert "code" in tool.args


def test_l_artefact_transporte_le_toolresult_complet():
    """Les images ne doivent pas être perdues entre le tool et un backend vision."""
    result = ToolResult(text="scène capturée",
                        images=[ImageArtifact(data="BASE64", mime_type="image/png")])
    tool = make_mcp_tool(_ref(name="capture"), _FakeManager([], result), submit=_sync_submit)

    message = tool.invoke({"name": tool.name, "args": {}, "id": "c1", "type": "tool_call"})

    assert message.content == "scène capturée"
    assert message.artifact.images[0].data == "BASE64"
    assert message.artifact.failed is False


def test_collision_de_nom_signalee_et_non_ecrasee(caplog):
    import logging

    refs = [_ref(name="a.b"), _ref(name="a__b")]    # les deux -> alpha__a__b
    with caplog.at_level(logging.WARNING, logger="axon.mcp"):
        tools = build_mcp_tools(refs, _FakeManager([]), submit=_sync_submit)

    assert len(tools) == 1
    assert any(r.getMessage() == "mcp_tool_name_collision" for r in caplog.records)


# ── LE test demandé : MCP et natif indiscernables ───────────────────────────────
@native_tool("native_echo")
def native_echo(value: str) -> str:
    """Renvoie la valeur telle quelle."""
    return f"echo:{value}"


def _tool_node_graph(tools):
    g = StateGraph(MessagesState)
    g.add_node("tools", ToolNode(tools=tools))
    g.add_edge(START, "tools")
    g.add_edge("tools", END)
    return g.compile()


def _call(app, name, args):
    ai = AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": "call_1"}])
    return app.invoke({"messages": [ai]})["messages"][-1]


def test_un_tool_mcp_et_un_tool_natif_sont_indiscernables_du_runtime():
    """Même liste de tools, même nœud, même appel, même forme de résultat.
    Si cette propriété tombe, LangGraph « sait » qu'un tool vient de MCP et
    l'objectif architectural du PRD §3 est perdu."""
    mcp = make_mcp_tool(_ref(name="execute_snippet", schema=_SCHEMA),
                        _FakeManager([], ToolResult(text="echo:x")), submit=_sync_submit)
    app = _tool_node_graph([native_echo, mcp])

    from_native = _call(app, "native_echo", {"value": "x"})
    from_mcp = _call(app, "alpha__execute_snippet", {"code": "x"})

    # même type d'objet, même statut, contenu textuel dans les deux cas
    assert type(from_native) is type(from_mcp) is ToolMessage
    assert from_native.status == from_mcp.status == "success"
    assert isinstance(from_native.content, str) and isinstance(from_mcp.content, str)
    assert from_native.content == from_mcp.content == "echo:x"
    # et les deux tools présentent la même interface au runtime
    for attribute in ("name", "description", "args", "invoke"):
        assert hasattr(native_echo, attribute) and hasattr(mcp, attribute)
    assert isinstance(mcp, BaseTool) and isinstance(native_echo, BaseTool)


# ── non-régression n°11 (ADDENDUM v2.3, Correction H) ──────────────────────────
def test_11_artefact_preserve_sur_tout_le_pipeline_de_messages(monkeypatch):
    """Un `ToolResult` porteur d'image traverse le pipeline COMPLET — nœud de
    tools, cache, redaction — sans perdre son artefact.

    Mode d'échec visé : tout traitement qui RECONSTRUIT un `ToolMessage` le prive
    de son artefact sans rien signaler. C'est déjà arrivé sur le chemin de
    redaction ; le test force ce chemin plutôt que de supposer qu'il est inerte.
    """
    from src.infra import redactor
    from src.infra.tools_cache import CACHEABLE_TOOLS
    from src.orchestrator.graph import CachedToolNode

    result = ToolResult(
        text="scène capturée, clé sk-ABCDEFGHIJKLMNOP dans les logs",
        images=[ImageArtifact(data="BASE64PNG", mime_type="image/png")],
    )
    mcp = make_mcp_tool(_ref(name="capture"), _FakeManager([], result), submit=_sync_submit)

    # backend cloud simulé : le chemin de redaction DOIT s'exécuter
    monkeypatch.setattr(redactor, "should_redact", lambda _backend: True)

    graph = StateGraph(MessagesState)
    graph.add_node("tools", CachedToolNode([mcp]))
    graph.add_edge(START, "tools")
    graph.add_edge("tools", END)
    ai = AIMessage(content="", tool_calls=[{"name": mcp.name, "args": {}, "id": "call_1"}])

    message = graph.compile().invoke({"messages": [ai]})["messages"][-1]

    assert "sk-ABCDEFGHIJKLMNOP" not in message.content   # la redaction a bien tourné
    assert message.artifact is not None, "artefact perdu en traversant le pipeline"
    assert message.artifact.images[0].data == "BASE64PNG"
    assert message.artifact.images[0].mime_type == "image/png"

    # Le chemin de cache rejoue un ToolMessage à partir d'une CHAÎNE : un tool MCP
    # mis en cache perdrait son artefact au replay. Aucun ne doit y figurer.
    assert mcp.name not in CACHEABLE_TOOLS
    assert not any(name.startswith("alpha__") for name in CACHEABLE_TOOLS)


def test_un_echec_mcp_ne_casse_pas_le_tour_et_arrive_en_erreur():
    """Une exception ici tuerait le tour de conversation : l'échec doit VOYAGER
    dans le contenu, pas remonter en exception."""
    failed = ToolResult(text="backend unavailable", suspected_error=True, error_source="heuristic")
    mcp = make_mcp_tool(_ref(), _FakeManager([], failed), submit=_sync_submit)
    app = _tool_node_graph([native_echo, mcp])

    message = _call(app, "alpha__get_status", {})

    assert isinstance(message, ToolMessage)
    assert json.loads(message.content)["status"] == "error"
    assert message.artifact.failed is True


# ── document de l'étage 1 : borné par construction ─────────────────────────────
def test_le_document_serveur_reste_borne_avec_100_tools():
    """Le bug de la v2.5 : 22 tools passaient de justesse, 100 auraient explosé.
    La taille doit être une propriété du document, pas un coup de chance."""
    from src.mcp_client.registry import SERVER_DOC_MAX_CHARS

    refs = [_ref(name=f"tool_numero_{i}", description="description très longue " * 40)
            for i in range(100)]

    doc = build_server_document(
        "alpha", refs, MCPServerConfig(name="alpha", capabilities_hint="3D, mesh, export"))

    assert len(doc) <= SERVER_DOC_MAX_CHARS
    assert "Descriptions:" not in doc          # les descriptions vivent à l'étage 2
    assert "description très longue" not in doc
    assert "Server: alpha" in doc and "3D, mesh, export" in doc
    # les 100 noms tiennent : c'est la suppression des descriptions qui borne
    assert "tool_numero_99" in doc


def test_la_troncature_est_annoncee_et_jamais_muette():
    refs = [_ref(name=f"tool_au_nom_particulierement_long_numero_{i}") for i in range(500)]

    doc = build_server_document("alpha", refs, MCPServerConfig(name="alpha"))

    from src.mcp_client.registry import SERVER_DOC_MAX_CHARS
    assert len(doc) <= SERVER_DOC_MAX_CHARS
    assert "autres)" in doc                    # le nombre d'omis est dit, pas caché


def test_le_document_serveur_nomit_rien_quand_ca_tient():
    refs = [_ref(name=f"t{i}") for i in range(5)]
    doc = build_server_document("alpha", refs, MCPServerConfig(name="alpha"))
    assert all(f"t{i}" in doc for i in range(5))
    assert "autres)" not in doc


def test_le_plafond_est_configurable_et_dur():
    refs = [_ref(name=f"tool_numero_{i}") for i in range(200)]
    for plafond in (200, 500, 4000):
        doc = build_server_document("alpha", refs, MCPServerConfig(name="alpha"),
                                    max_chars=plafond)
        assert len(doc) <= plafond


def test_un_hint_geant_ne_fait_pas_deborder_le_document():
    doc = build_server_document("alpha", [_ref()],
                                MCPServerConfig(name="alpha", capabilities_hint="x" * 50_000),
                                max_chars=1000)
    assert len(doc) <= 1000


def test_routing_joint_les_serveurs_sans_etage_1(tmp_path):
    """Un serveur dont le document d'étage 1 manque ne peut pas être élu par
    l'étage 1 : il doit être joint d'office au filtre de l'étage 2."""
    index = _FakeIndex(servers=[], tools=["alpha.get_status"])

    assert route("statut", index, unrouted_servers=("alpha",)) == ["alpha.get_status"]

    _, _, _, where = index.queries[1]
    assert where == {"server": {"$in": ["alpha"]}}
