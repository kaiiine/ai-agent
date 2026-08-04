"""Intégration Axon : indexation, routing et exécution des tools MCP (DESIGN §8).

Trois responsabilités, volontairement séparées de `manager.py` :

1. **Indexation** — les `MCPToolRef` découverts sont poussés dans un index
   vectoriel sur leur `retrieval_text` (nom + description + capacités + schéma),
   pas sur la description brute : « Execute Python code » matche mal une demande
   formulée en intention métier. Le serveur lui-même est indexé séparément pour
   l'étage 1 du routing.

2. **Routing à deux étages** — on score d'abord les serveurs, puis on ne cherche
   les tools que parmi ceux retenus (filtre `where`). Coût nul avec un seul
   serveur, et la structure absorbe la prolifération de tools ensuite.

3. **Exécution** — `execute_mcp_tool` ne détient JAMAIS de connexion : il passe
   par `manager.call_tool`, qui résout la connexion courante au moment de
   l'appel. Un tool indexé survit donc aux redémarrages du serveur.

Frontière avec LangGraph : `make_mcp_tool` produit un `BaseTool` standard. Le
graphe ne peut pas distinguer un tool MCP d'un tool natif — même appel, même
forme de résultat (`ToolMessage` à contenu textuel).

Le point délicat est l'échec : un `ToolResult.failed` doit arriver au modèle
comme une ERREUR D'OUTIL. Sans ça, le modèle raisonne sur un message de panne
(« backend injoignable ») comme s'il s'agissait de données métier.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Callable, Iterable, Protocol

from langchain_core.tools import BaseTool, StructuredTool

from src.infra.retrieval import build_catalog_document, unique as _unique
from src.mcp_client.models import MCPServerConfig, MCPToolRef, ToolDiff, ToolResult

logger = logging.getLogger("axon.mcp")

MCP_SOURCE = "mcp"
MCP_SERVER_SOURCE = "mcp_server"

_UNSAFE_NAME_CHARS = re.compile(r"[^a-zA-Z0-9_-]")
_MAX_RUNTIME_NAME = 64

# Plafond du document de l'étage 1. Défaut conservateur : très en dessous du
# contexte des embedders courants (`nomic-embed-text` : 2048 tokens), pour que le
# document reste indexable quel que soit le nombre de tools du serveur.
SERVER_DOC_MAX_CHARS = 4000
# Compromis pertinence / diversité de l'étage 2. 0.5 = équilibré ; plus haut
# revient à la similarité pure et ramène le problème des quasi-doublons.
_MMR_LAMBDA = 0.5


# ── index ───────────────────────────────────────────────────────────────────────
class ToolIndex(Protocol):
    """Surface minimale attendue de l'index. Un `Protocol` plutôt qu'une classe
    de base : les tests injectent un index en mémoire, la prod un Chroma."""

    def upsert(self, id: str, document: str, metadata: dict) -> None: ...
    def delete(self, where: dict) -> None: ...
    def delete_ids(self, ids: list[str]) -> None: ...
    def query_servers(self, query: str, n: int = 3) -> list[str]: ...
    def query_tools(self, query: str, k: int = 7, where: dict | None = None) -> list[str]: ...


def _and(*clauses: dict) -> dict:
    """Chroma exige `$and` explicite dès qu'un filtre porte sur deux clés."""
    kept = [c for c in clauses if c]
    if len(kept) == 1:
        return kept[0]
    return {"$and": kept}


class ChromaToolIndex:
    """Index vectoriel des tools MCP, séparé de l'index des tools natifs.

    Collection éphémère par défaut : les tools MCP sont DÉCOUVERTS à chaque
    démarrage (`tools/list`). Les persister exposerait au cas où l'index propose
    un tool que le serveur n'expose plus — un tool fantôme est pire qu'une
    réindexation de quelques centaines de millisecondes.
    """

    def __init__(self, embeddings=None, *, collection_name: str = "axon_mcp_tools",
                 persist_directory: str | None = None):
        from langchain_chroma import Chroma

        if embeddings is None:  # pragma: no cover - dépend d'Ollama, non testé hors ligne
            from langchain_ollama import OllamaEmbeddings

            embeddings = OllamaEmbeddings(model="nomic-embed-text")
        self._store = Chroma(
            collection_name=collection_name,
            embedding_function=embeddings,
            persist_directory=persist_directory,
        )

    def upsert(self, id: str, document: str, metadata: dict) -> None:
        self._store.add_texts([document], metadatas=[metadata], ids=[id])

    def delete(self, where: dict) -> None:
        found = self._store.get(where=where)
        ids = found.get("ids") or []
        if ids:
            self._store.delete(ids=ids)

    def delete_ids(self, ids: list[str]) -> None:
        if ids:
            self._store.delete(ids=list(ids))

    def query_servers(self, query: str, n: int = 3) -> list[str]:
        docs = self._store.similarity_search(query, k=n, filter={"source": MCP_SERVER_SOURCE})
        return _unique(d.metadata.get("server") for d in docs)

    def query_tools(self, query: str, k: int = 7, where: dict | None = None) -> list[str]:
        """Sélection DIVERSIFIÉE (MMR), pas les k plus proches.

        Les tools d'un serveur se ressemblent beaucoup entre eux : une requête qui
        matche une famille (« importe ce modèle ») remplit le top-k de quasi-doublons
        et évince le tool générique dont on a besoin pour la suite de la tâche.
        Mesuré : sur une requête à identifiant, le tool d'exécution passait 18e et
        disparaissait du top-7 ; avec MMR il y revient, sans déloger les autres."""
        flt = _and({"source": MCP_SOURCE}, where or {})
        try:
            docs = self._store.max_marginal_relevance_search(
                query, k=k, fetch_k=max(k * 4, 20), lambda_mult=_MMR_LAMBDA, filter=flt)
        except Exception:
            docs = self._store.similarity_search(query, k=k, filter=flt)
        return _unique(d.metadata.get("public_name") for d in docs)


# ── documents indexés ───────────────────────────────────────────────────────────
def build_server_document(server: str, tools: list[MCPToolRef],
                          cfg: MCPServerConfig | None = None,
                          *, max_chars: int = SERVER_DOC_MAX_CHARS) -> str:
    """Document de l'étage 1 : ce que le SERVEUR sait faire, pour que la requête
    sélectionne le bon serveur avant même de regarder ses tools.

    Borné par construction (cf. `build_catalog_document`) : le document ne
    grandit pas avec le nombre de tools, donc un serveur de 100 tools n'échoue
    pas à l'indexation là où un serveur de 20 passait.
    """
    return build_catalog_document(
        {"Server": server, "Capabilities": cfg.capabilities_hint if cfg else ""},
        "Tools",
        [t.remote_name for t in tools],
        max_chars=max_chars,
    )


def tool_metadata(ref: MCPToolRef) -> dict:
    return {
        "source": MCP_SOURCE,
        "server": ref.server,
        "tool": ref.remote_name,
        "public_name": ref.public_name,
        "risk_level": ref.risk_level,
    }


# ── enregistrement / désenregistrement ──────────────────────────────────────────
def _upsert_tools(refs: Iterable[MCPToolRef], tool_index: ToolIndex) -> None:
    for ref in refs:
        tool_index.upsert(
            id=ref.public_name,
            document=ref.retrieval_text or ref.description or ref.public_name,
            metadata=tool_metadata(ref),
        )


def _upsert_server(server: str, refs: list[MCPToolRef], tool_index: ToolIndex,
                   cfg: MCPServerConfig | None) -> None:
    tool_index.upsert(
        id=f"server:{server}",
        document=build_server_document(server, refs, cfg),
        metadata={"source": MCP_SERVER_SOURCE, "server": server},
    )


async def register_server_tools(manager, server: str, tool_index: ToolIndex) -> list[MCPToolRef]:
    """Indexe les tools d'un serveur + le serveur lui-même (étage 1 du routing)."""
    refs = await manager.list_tools(server)
    _upsert_tools(refs, tool_index)
    _upsert_server(server, refs, tool_index, manager.servers.get(server))
    return refs


def unregister_server_tools(server: str, tool_index: ToolIndex) -> None:
    """Retire les tools ET le document de serveur : un serveur désactivé ne doit
    plus peser sur l'étage 1 du routing."""
    tool_index.delete(where=_and({"source": MCP_SOURCE}, {"server": server}))
    tool_index.delete(where=_and({"source": MCP_SERVER_SOURCE}, {"server": server}))


def resync_index(diff: ToolDiff, server: str, tool_index: ToolIndex, *,
                 tools: list[MCPToolRef] | None = None,
                 cfg: MCPServerConfig | None = None) -> None:
    """Resync INCRÉMENTAL depuis le `ToolDiff` de `manager.refresh()` : on ne
    réindexe que ce qui a bougé. Le document de serveur est régénéré dès qu'un
    tool est ajouté ou retiré, puisqu'il en liste les noms."""
    if diff.is_empty:
        return
    _upsert_tools(list(diff.added) + list(diff.changed), tool_index)
    if diff.removed:
        tool_index.delete_ids([ref.public_name for ref in diff.removed])
    if (diff.added or diff.removed) and tools is not None:
        _upsert_server(server, tools, tool_index, cfg)


# ── routing à deux étages ───────────────────────────────────────────────────────
def route(query: str, tool_index: ToolIndex, *, top_servers: int = 3, k: int = 7,
          unrouted_servers: Iterable[str] = ()) -> list[str]:
    """Étage 1 : quels serveurs sont pertinents. Étage 2 : tools filtrés sur eux.

    Renvoie des `public_name`. Le filtrage évite qu'une requête destinée à un
    serveur remonte les tools d'un autre quand leurs descriptions se ressemblent.

    `unrouted_servers` : serveurs dont le document d'étage 1 n'a pas pu être
    indexé. Ils ne peuvent pas être élus par l'étage 1 — on les joint donc
    d'office au filtre, ce qui les laisse joignables par le seul étage 2.
    """
    servers = list(tool_index.query_servers(query, n=top_servers))
    servers += [s for s in unrouted_servers if s not in servers]
    if not servers:
        return []
    return tool_index.query_tools(query, k=k, where={"server": {"$in": servers}})


# ── exécution ───────────────────────────────────────────────────────────────────
async def execute_mcp_tool(tool_ref: MCPToolRef, args: dict, manager) -> ToolResult:
    """Point d'exécution unique. Référence STABLE en entrée, connexion résolue
    au moment de l'appel : rien ici ne capture de session."""
    return await manager.call_tool(
        server=tool_ref.server, tool=tool_ref.remote_name, arguments=args
    )


def runtime_tool_name(public_name: str) -> str:
    """`alpha.get_status` -> `alpha__get_status`.

    Le point est refusé par le schéma de function-calling de plusieurs
    fournisseurs (`^[a-zA-Z0-9_-]+$`). `public_name` reste l'identité stable
    — index, provenance —, ce nom-ci n'est que la surface exposée au modèle,
    indiscernable d'un tool natif."""
    return _UNSAFE_NAME_CHARS.sub("_", public_name.replace(".", "__"))[:_MAX_RUNTIME_NAME]


def format_tool_result(result: ToolResult, tool_ref: MCPToolRef) -> str:
    """Contenu textuel remis au modèle.

    Un échec est présenté comme une ERREUR D'OUTIL explicite, jamais comme un
    résultat : c'est l'impact direct du fait qu'un serveur peut renvoyer sa panne
    avec `isError=False`. Sans cette enveloppe, « backend injoignable » arriverait
    au modèle sous la même forme qu'un vrai contenu métier, et il raisonnerait
    dessus comme sur une donnée."""
    if result.failed:
        return json.dumps({
            "status": "error",
            "tool": tool_ref.public_name,
            "error_source": result.error_source,
            "message": result.text or "échec sans message",
            "note": "Échec d'exécution de l'outil : ne pas interpréter ce contenu "
                    "comme un résultat, et ne pas le présenter comme tel.",
        }, ensure_ascii=False)

    if result.text is not None:
        return result.text
    if result.structured is not None:
        return json.dumps(result.structured, ensure_ascii=False)

    # Contenu non textuel : le texte le décrit, les artefacts restent intacts
    # dans `ToolResult` (jamais aplatis dans la chaîne).
    parts = []
    if result.images:
        parts.append(f"{len(result.images)} image(s)")
    if result.resources:
        parts.append(f"{len(result.resources)} ressource(s)")
    return f"[{tool_ref.public_name}: {', '.join(parts)}]" if parts else ""


def make_mcp_tool(tool_ref: MCPToolRef, manager, *,
                  submit: Callable[[Any], ToolResult]) -> BaseTool:
    """Enveloppe un `MCPToolRef` en `BaseTool` LangChain standard.

    `submit` exécute la coroutine et rend son résultat : le pont sync/async est
    injecté (cf. `runtime.py`), ce module reste sans thread ni boucle.

    `response_format="content_and_artifact"` : le modèle reçoit du texte, et le
    `ToolResult` complet — images et ressources comprises — voyage dans
    `ToolMessage.artifact` sans être aplati en chaîne.
    """
    schema = tool_ref.input_schema or {"type": "object", "properties": {}}

    def _run(**arguments) -> tuple[str, ToolResult]:
        result = submit(execute_mcp_tool(tool_ref, arguments, manager))
        return format_tool_result(result, tool_ref), result

    return StructuredTool.from_function(
        func=_run,
        name=runtime_tool_name(tool_ref.public_name),
        description=tool_ref.description or tool_ref.public_name,
        args_schema=schema,
        response_format="content_and_artifact",
    )


def partition_by_runtime_name(
    refs: Iterable[MCPToolRef],
) -> tuple[list[MCPToolRef], list[tuple[MCPToolRef, str]]]:
    """Sépare les tools exposables de ceux dont le nom runtime est déjà pris.

    Renvoie `(gardés, [(ignoré, public_name en conflit)])`. Un tool ignoré est un
    tool INVISIBLE pour le modèle : la liste des ignorés est renvoyée pour que la
    CLI puisse le dire, plutôt que de laisser la disparition sans trace."""
    kept: list[MCPToolRef] = []
    ignored: list[tuple[MCPToolRef, str]] = []
    taken: dict[str, str] = {}
    for ref in refs:
        name = runtime_tool_name(ref.public_name)
        if name in taken:
            ignored.append((ref, taken[name]))
            continue
        taken[name] = ref.public_name
        kept.append(ref)
    return kept, ignored


def build_mcp_tools(refs: Iterable[MCPToolRef], manager, *,
                    submit: Callable[[Any], ToolResult]) -> dict[str, BaseTool]:
    """`public_name -> BaseTool`. Une collision de nom d'exécution (deux
    `public_name` distincts réduits au même nom) est signalée et ignorée plutôt
    que d'écraser silencieusement un tool."""
    kept, ignored = partition_by_runtime_name(refs)
    for ref, conflict in ignored:
        logger.warning(
            "mcp_tool_name_collision",
            extra={"tool": ref.public_name, "conflicts_with": conflict,
                   "runtime_name": runtime_tool_name(ref.public_name)},
        )
    return {ref.public_name: make_mcp_tool(ref, manager, submit=submit) for ref in kept}
