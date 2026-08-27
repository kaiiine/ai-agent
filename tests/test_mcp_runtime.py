"""Pont entre le runtime de tools synchrone d'Axon et le client MCP (src/mcp_client/runtime.py).

Le point critique : les connexions MCP doivent SURVIVRE entre deux appels de tool.
Un `asyncio.run()` par invocation détruirait le sous-processus à chaque appel — d'où
la boucle dédiée dans un thread, dont ce fichier vérifie qu'elle tient la charge
d'un vrai serveur stdio de bout en bout.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys

import pytest

from src.mcp_client.registry import MCP_SOURCE
from src.mcp_client.runtime import MCPRuntime, default_config_path

_SERVER_SRC = """
import sys
sys.path[:0] = {paths!r}
from mcp.server.fastmcp import FastMCP

app = FastMCP("axon-runtime-server")

@app.tool()
def get_status(user_prompt: str) -> str:
    "Statut du backend (lecture seule)."
    return "backend unavailable: bridge not connected"

@app.tool()
def execute_snippet(code: str) -> str:
    "Exécute un extrait et renvoie le résultat."
    return "ok:" + code

app.run()
"""

_needs_server = pytest.mark.skipif(
    importlib.util.find_spec("mcp.server.fastmcp") is None,
    reason="serveur FastMCP indisponible",
)


class _FakeIndex:
    def __init__(self, *, servers=(), tools=()):
        self.docs, self._servers, self._tools = {}, list(servers), list(tools)

    def upsert(self, id, document, metadata):
        self.docs[id] = (document, metadata)

    def delete(self, where):
        pass

    def delete_ids(self, ids):
        pass

    def query_servers(self, query, n=3):
        return list(self._servers)

    def query_tools(self, query, k=7, where=None):
        return list(self._tools)


def _config_file(tmp_path, *, enabled=True):
    path = tmp_path / "mcp_servers.json"
    path.write_text(json.dumps({"servers": {"alpha": {
        "command": sys.executable,
        "args": ["-c", _SERVER_SRC.format(paths=[p for p in sys.path if p])],
        "enabled": enabled,
        "timeouts": {"connect_s": 30, "list_tools_s": 30, "call_s": 30},
        "health": {"probe_tool": "get_status",
                   "failure_patterns": ["backend unavailable"],
                   "consecutive_failures_to_degrade": 1},
        "capabilities_hint": "diagnostic, exécution de code",
    }}}), encoding="utf-8")
    return path


# ── coût nul sans serveur ───────────────────────────────────────────────────────
def test_aucune_configuration_ne_demarre_aucun_thread(tmp_path):
    runtime = MCPRuntime(tmp_path / "absent.json")
    runtime.start()

    assert runtime.tools == []
    assert runtime.select("crée un objet") == []
    assert runtime._thread is None          # Axon ne paie rien quand MCP n'est pas utilisé


def test_serveur_desactive_ne_lance_aucun_sous_processus_mais_reste_visible(tmp_path):
    """Un serveur désactivé ne coûte aucun sous-processus, mais doit rester
    listable et activable — sinon `/mcp list` et `/mcp enable` ne le voient pas."""
    runtime = MCPRuntime(_config_file(tmp_path, enabled=False), index=_FakeIndex())
    try:
        runtime.start()

        assert runtime.tools == []
        assert runtime.discovered("alpha") == []
        assert runtime.status()["alpha"].state.value == "disabled"
    finally:
        runtime.stop()


def test_chemin_de_config_surchargeable(monkeypatch, tmp_path):
    monkeypatch.setenv("AXON_MCP_CONFIG", str(tmp_path / "ailleurs.json"))
    assert default_config_path() == tmp_path / "ailleurs.json"
    monkeypatch.delenv("AXON_MCP_CONFIG")
    assert default_config_path().name == "mcp_servers.json"


def _expect_refusal(runtime, coro, match):
    try:
        with pytest.raises(RuntimeError, match=match):
            runtime.submit(coro)
    finally:
        coro.close()


def test_submit_avant_demarrage_est_explicite():
    _expect_refusal(MCPRuntime(), asyncio.sleep(0), "non démarré")


def test_le_graphe_branche_les_tools_mcp_a_cote_des_natifs():
    """Garde d'architecture : les tools MCP doivent être exécutables par le
    ToolNode ET sélectionnables, sans passer par l'index des tools natifs."""
    import pathlib

    src = pathlib.Path("src/orchestrator/graph.py").read_text(encoding="utf-8")
    assert "from src.mcp_client.runtime import mcp_runtime" in src
    assert "tools = tools + _mcp.tools" in src                  # exécutables
    # La forme exacte de l'appel a changé quand `select` a reçu les serveurs
    # actifs de la conversation ; ce qui est gardé ici, c'est que la sélection
    # native et la sélection MCP se composent, pas leur rédaction.
    assert "retriever.get(query) + _mcp.select(" in src         # sélectionnables
    # l'index natif est construit AVANT l'ajout des tools MCP : il ne les indexe pas
    assert src.index("retriever = ToolRetriever(tools)") < src.index("tools = tools + _mcp.tools")

    # La rédaction ne doit pas perdre l'artefact multimodal en reconstruisant le
    # message. Elle vit avec l'exécution des tools, dans `tool_node.py`.
    noeud = pathlib.Path("src/orchestrator/tool_node.py").read_text(encoding="utf-8")
    assert 'artifact=getattr(msg, "artifact", None)' in noeud


# ── bout en bout : config -> sous-processus -> tool LangChain synchrone ─────────
@_needs_server
def test_bout_en_bout_un_tool_mcp_sexecute_depuis_un_appel_synchrone(tmp_path):
    index = _FakeIndex(servers=["alpha"], tools=["alpha.execute_snippet"])
    runtime = MCPRuntime(_config_file(tmp_path), index=index)
    try:
        runtime.start()

        # découverte -> indexation -> enveloppes LangChain
        assert {t.name for t in runtime.tools} == {"alpha__get_status", "alpha__execute_snippet"}
        assert index.docs["alpha.execute_snippet"][1]["source"] == MCP_SOURCE
        assert "server:alpha" in index.docs

        # routing à deux étages -> sélection
        selected = runtime.select("exécute ce bout de code")
        assert [t.name for t in selected] == ["alpha__execute_snippet"]

        # exécution SYNCHRONE, comme le ferait le ToolNode
        tool = selected[0]
        message = tool.invoke({"name": tool.name, "args": {"code": "42"},
                               "id": "c1", "type": "tool_call"})
        assert message.content == "ok:42"
        assert message.artifact.failed is False

        # la connexion SURVIT : un second appel réutilise le même sous-processus
        again = tool.invoke({"name": tool.name, "args": {"code": "43"},
                             "id": "c2", "type": "tool_call"})
        assert again.content == "ok:43"
        assert runtime.manager.connections["alpha"].runtime.state.value == "ready"
    finally:
        runtime.stop()


@_needs_server
def test_bout_en_bout_un_echec_backend_arrive_en_erreur_doutil(tmp_path):
    """`isError=False` côté protocole, échec réel côté backend : ce qui parvient
    au modèle doit être une erreur d'outil, pas le message de panne brut."""
    runtime = MCPRuntime(_config_file(tmp_path), index=_FakeIndex())
    try:
        runtime.start()
        tool = next(t for t in runtime.tools if t.name == "alpha__get_status")

        message = tool.invoke({"name": tool.name, "args": {"user_prompt": "sonde"},
                               "id": "c1", "type": "tool_call"})

        payload = json.loads(message.content)
        assert payload["status"] == "error"
        assert payload["error_source"] == "heuristic"
        assert message.artifact.failed is True
        # l'état du serveur reflète la panne backend, process MCP toujours vivant
        assert runtime.manager.connections["alpha"].runtime.state.value == "degraded"
    finally:
        runtime.stop()


@_needs_server
def test_submit_depuis_la_boucle_est_refuse(tmp_path):
    """Attendre son propre résultat depuis la boucle MCP serait un interblocage
    silencieux : on préfère une erreur immédiate."""
    runtime = MCPRuntime(_config_file(tmp_path), index=_FakeIndex())
    try:
        runtime.start()

        async def _reentrant():
            inner = asyncio.sleep(0)
            try:
                return runtime.submit(inner)
            finally:
                inner.close()

        _expect_refusal(runtime, _reentrant(), "depuis la boucle")
    finally:
        runtime.stop()


@_needs_server
def test_sans_index_les_tools_restent_executables(tmp_path):
    """Perdre le routing (Ollama indisponible) ne doit pas rendre MCP muet."""
    runtime = MCPRuntime(_config_file(tmp_path), index=None)
    runtime._index_provided = True          # simule un index indisponible
    try:
        runtime.start()
        assert len(runtime.tools) == 2
        assert len(runtime.select("peu importe la requête")) == 2
    finally:
        runtime.stop()


# ── synchronisation par delta, jamais de reconstruction ────────────────────────
class _RecordingIndex(_FakeIndex):
    """Compte précisément ce qui est écrit dans l'index."""

    def __init__(self):
        super().__init__()
        self.upserts: list[str] = []
        self.deleted_ids: list[str] = []
        self.deleted_where: list[dict] = []

    def upsert(self, id, document, metadata):
        self.upserts.append(id)
        super().upsert(id, document, metadata)

    def delete_ids(self, ids):
        self.deleted_ids.extend(ids)

    def delete(self, where):
        self.deleted_where.append(where)


def _refs(*names):
    from types import SimpleNamespace

    from src.mcp_client.adapter import adapt_schema
    from src.mcp_client.models import MCPServerConfig

    return [adapt_schema("alpha",
                         SimpleNamespace(name=n, description="d", inputSchema={}),
                         MCPServerConfig(name="alpha")) for n in names]


def test_lindex_est_synchronise_par_delta_pas_reconstruit(tmp_path):
    """Preuve chiffrée : ajouter UN tool n'écrit qu'UNE entrée de tool, pas N.
    Reconstruire l'index entier à chaque changement re-embedderait tout."""
    index = _RecordingIndex()
    runtime = MCPRuntime(tmp_path / "absent.json", index=index)

    runtime._apply("alpha", _refs("a", "b"))              # première indexation
    assert sorted(index.upserts) == ["alpha.a", "alpha.b", "server:alpha"]

    index.upserts.clear()
    runtime._apply("alpha", _refs("a", "b", "c"))         # un seul ajout

    tools_ecrits = [i for i in index.upserts if not i.startswith("server:")]
    assert tools_ecrits == ["alpha.c"]                    # ni "alpha.a" ni "alpha.b"
    assert "server:alpha" in index.upserts                # le doc serveur liste les noms


def test_le_retrait_dun_tool_ne_supprime_que_lui(tmp_path):
    index = _RecordingIndex()
    runtime = MCPRuntime(tmp_path / "absent.json", index=index)
    runtime._apply("alpha", _refs("a", "b", "c"))
    index.upserts.clear()

    runtime._apply("alpha", _refs("a", "b"))

    assert index.deleted_ids == ["alpha.c"]
    assert [i for i in index.upserts if not i.startswith("server:")] == []


def test_un_diff_vide_ne_touche_pas_a_lindex(tmp_path):
    index = _RecordingIndex()
    runtime = MCPRuntime(tmp_path / "absent.json", index=index)
    runtime._apply("alpha", _refs("a", "b"))
    index.upserts.clear()

    runtime._apply("alpha", _refs("a", "b"))

    assert index.upserts == [] and index.deleted_ids == []


def test_desindexer_retire_aussi_le_document_de_serveur(tmp_path):
    """Sinon un serveur désactivé continuerait de peser sur l'étage 1 du routing."""
    index = _RecordingIndex()
    runtime = MCPRuntime(tmp_path / "absent.json", index=index)
    runtime._apply("alpha", _refs("a"))

    runtime._apply("alpha", [])

    assert index.deleted_where                      # suppression filtrée par serveur
    assert any("mcp_server" in str(w) for w in index.deleted_where)
    assert runtime.tools == []


def test_une_collision_entre_serveurs_est_vue(tmp_path):
    """La partition des noms runtime est GLOBALE : un traitement serveur par
    serveur masquerait une collision inter-serveurs."""
    from types import SimpleNamespace

    from src.mcp_client.adapter import adapt_schema
    from src.mcp_client.models import MCPServerConfig

    def ref(server, name):
        return adapt_schema(server, SimpleNamespace(name=name, description="d", inputSchema={}),
                            MCPServerConfig(name=server))

    runtime = MCPRuntime(tmp_path / "absent.json", index=_FakeIndex())
    runtime._apply("a", [ref("a", "b__c")])         # -> a__b__c
    runtime._apply("a__b", [ref("a__b", "c")])      # -> a__b__c aussi

    assert len(runtime.tools) == 1
    assert runtime.collisions("a__b")               # le second est signalé, pas écrasé


# ── non-régression n°13 (ADDENDUM v2.5) ────────────────────────────────────────
class _ExplodingEmbeddings:
    """Embedder qui échoue systématiquement, comme `nomic-embed-text` quand le
    document dépasse son contexte."""

    def embed_documents(self, texts):
        raise RuntimeError("the input length exceeds the context length")

    def embed_query(self, text):
        raise RuntimeError("the input length exceeds the context length")


class _ExplodingIndex(_FakeIndex):
    def upsert(self, id, document, metadata):
        raise RuntimeError("index indisponible")


def test_13_une_panne_dindexation_ne_fait_jamais_tomber_les_tools_a_zero(tmp_path):
    """Le défaut corrigé était d'être à la fois AVALÉ et FATAL : l'exception
    remontait de `_apply` jusqu'à `start()`, où un `except` la réduisait à une
    ligne de log — Axon démarrait alors sans aucun tool MCP, en silence."""
    import uuid

    from src.mcp_client.registry import ChromaToolIndex

    index = ChromaToolIndex(_ExplodingEmbeddings(), collection_name=f"t_{uuid.uuid4().hex}")
    runtime = MCPRuntime(tmp_path / "absent.json", index=index)

    runtime._apply("alpha", _refs("a", "b", "c"))     # ne doit pas lever

    assert len(runtime.tools) == 3                    # les tools survivent
    assert "context length" in (runtime.index_state("alpha") or "")


def test_13_variante_index_qui_leve_a_lupsert(tmp_path):
    runtime = MCPRuntime(tmp_path / "absent.json", index=_ExplodingIndex())

    runtime._apply("alpha", _refs("a", "b"))

    assert len(runtime.tools) == 2
    assert runtime.index_state("alpha") == "index indisponible"


def test_un_serveur_sans_etage_1_reste_joignable_par_letage_2(tmp_path):
    """L'étage 1 perdu ne doit pas rendre le serveur inatteignable : on le joint
    d'office au filtre de l'étage 2."""

    class _Stage1Broken(_FakeIndex):
        def upsert(self, id, document, metadata):
            if id.startswith("server:"):
                raise RuntimeError("contexte de l'embedder dépassé")
            super().upsert(id, document, metadata)

        def query_servers(self, query, n=3):
            return []                               # le document serveur manque

        def query_tools(self, query, k=7, where=None):
            return [i for i in self.docs if not i.startswith("server:")]

    runtime = MCPRuntime(tmp_path / "absent.json", index=_Stage1Broken())
    runtime._apply("alpha", _refs("a", "b"))

    assert len(runtime.tools) == 2
    assert "contexte" in (runtime.index_state("alpha") or "")
    assert len(runtime.select("peu importe")) == 2   # repli sur l'étage 2 seul


def test_letat_dindexation_redevient_sain_apres_un_succes(tmp_path):
    class _FlakyIndex(_FakeIndex):
        fail = True

        def upsert(self, id, document, metadata):
            if self.fail:
                raise RuntimeError("boom")
            super().upsert(id, document, metadata)

    index = _FlakyIndex()
    runtime = MCPRuntime(tmp_path / "absent.json", index=index)
    runtime._apply("alpha", _refs("a"))
    assert runtime.index_state("alpha") is not None

    index.fail = False
    runtime._apply("alpha", _refs("a", "b"))

    assert runtime.index_state("alpha") is None
    assert len(runtime.tools) == 2
