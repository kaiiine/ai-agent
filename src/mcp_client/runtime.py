"""Pont entre le runtime de tools d'Axon (synchrone) et le client MCP (asyncio).

`ToolNode` exécute les tools de façon synchrone, alors que le SDK MCP est
entièrement asynchrone et que les connexions doivent SURVIVRE entre deux appels.
Un `asyncio.run()` par invocation détruirait le sous-processus à chaque appel —
d'où une **boucle asyncio dédiée dans un thread démon**, propriétaire du
`MCPClientManager` et de toutes les tâches porteuses de transport. C'est ce qui
rend compatibles la contrainte de la Correction C (entrée/sortie de scope dans la
même tâche) et l'exécution synchrone du graphe.

Toutes les opérations de cycle de vie passent par `_apply()`, qui applique au seul
index le DELTA entre ce qui y est enregistré et ce que le serveur expose
maintenant. L'index n'est jamais reconstruit dans son ensemble.

Coût nul quand aucun serveur n'est déclaré : aucun thread n'est démarré.
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
from pathlib import Path
from typing import Any

from langchain_core.tools import BaseTool

from src.mcp_client.config import load_config
from src.mcp_client.pertinence import serveurs_pertinents, signatures
from src.mcp_client.manager import MCPClientManager, diff_server_tools
from src.mcp_client.models import (
    DiagnosticReport,
    MCPServerConfig,
    MCPServerRuntime,
    MCPToolRef,
    ToolDiff,
)
from src.mcp_client.registry import (
    ChromaToolIndex,
    ToolIndex,
    build_mcp_tools,
    partition_by_runtime_name,
    resync_index,
    route,
    unregister_server_tools,
)

logger = logging.getLogger("axon.mcp")

_START_TIMEOUT_S = 120.0
_CALL_TIMEOUT_S = 900.0  # garde-fou : les vrais délais sont ceux de la config serveur
_MAX_UNROUTED_TOOLS = 12  # routing indisponible : on expose sans noyer le contexte


def default_config_path() -> Path:
    return Path(os.getenv("AXON_MCP_CONFIG") or (Path.home() / ".axon" / "mcp_servers.json"))


class MCPRuntime:
    """Propriétaire de la boucle MCP, de l'index et des enveloppes LangChain."""

    def __init__(self, config_path: Path | None = None, *, index: ToolIndex | None = None):
        self.config_path = Path(config_path) if config_path else default_config_path()
        self.manager: MCPClientManager | None = None
        self._index = index
        self._index_provided = index is not None
        self._indexed: dict[str, list[MCPToolRef]] = {}          # ce qui est DANS l'index
        # Ce que chaque serveur EXPOSE. Distinct de l'index : les enveloppes
        # doivent exister dès le démarrage — sinon un outil n'est pas exécutable —
        # alors que l'indexation peut attendre que le serveur soit élu.
        self._connus: dict[str, list[MCPToolRef]] = {}
        self._signatures_cache: dict[str, set[str]] | None = None
        self._index_state: dict[str, str] = {}                   # serveur -> raison de l'échec
        self._collisions: dict[str, list[tuple[MCPToolRef, str]]] = {}
        self._tools: dict[str, BaseTool] = {}                    # public_name -> BaseTool
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._started = False

    # ---------- boucle dédiée ----------

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def submit(self, coro, timeout: float | None = _CALL_TIMEOUT_S) -> Any:
        """Dépose une coroutine sur la boucle MCP et attend son résultat."""
        if self._loop is None:
            raise RuntimeError("runtime MCP non démarré")
        if threading.current_thread() is self._thread:
            # Attendre son propre résultat depuis la boucle serait un interblocage.
            raise RuntimeError("submit() appelé depuis la boucle MCP elle-même")
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result(timeout)

    def _boot(self) -> None:
        """Démarre la boucle et charge la config. Idempotent."""
        if self._loop is not None:
            return
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, name="axon-mcp", daemon=True)
        self._thread.start()
        self.manager = MCPClientManager(self.config_path)
        self.submit(self.manager.start(), timeout=_START_TIMEOUT_S)

    # ---------- démarrage ----------

    def start(self) -> None:
        """Non bloquant pour Axon : la panne d'un serveur reste locale à ce
        serveur, et l'absence de déclaration ne coûte strictement rien."""
        if self._started:
            return
        self._started = True
        if not load_config(self.config_path):
            return
        self._boot()
        for name, conn in self.manager.connections.items():
            # Un serveur injoignable n'est pas relisté ici : cela déclencherait sa
            # séquence de backoff et retarderait le démarrage d'Axon.
            if not (conn.config.enabled and conn.is_healthy):
                continue
            try:
                self._apply(name, conn.tools, indexer=False)
            except Exception as exc:
                # Filet : un serveur ne peut pas empêcher les autres de s'indexer.
                logger.warning("mcp_server_index_failed",
                               extra={"server": name, "error": str(exc)})

    # ---------- synchronisation d'index (toujours par delta) ----------

    def _apply(self, server: str, new_refs: list[MCPToolRef],
               *, indexer: bool = True) -> ToolDiff:
        """Applique le DELTA entre l'état indexé et `new_refs`. Seules les entrées
        qui changent sont touchées — l'index n'est jamais reconstruit.

        **Une panne d'indexation ne fait jamais disparaître de tools.** L'exception
        est capturée ICI, au niveau du serveur : les enveloppes LangChain sont
        construites quoi qu'il arrive, seul le routing du serveur concerné est
        dégradé. Laisser l'exception remonter la rendait à la fois avalée plus haut
        et fatale — Axon démarrait alors sans aucun tool MCP, en silence."""
        # Les enveloppes d'abord, et toujours : un outil non enveloppé n'est pas
        # exécutable, quel que soit l'état de l'index.
        if new_refs:
            self._connus[server] = list(new_refs)
        else:
            self._connus.pop(server, None)

        previous = self._indexed.get(server, [])
        diff = diff_server_tools(previous, list(new_refs))
        if not indexer:
            # Indexation DIFFÉRÉE. Elle coûtait 2,2 s à chaque démarrage pour 52
            # outils, et la collection est éphémère : le delta partait toujours
            # d'un état vide. L'étage 1 du routage lit le `capabilities_hint` de la
            # config, pas l'index — un serveur peut donc être élu sans être indexé,
            # et ne l'être qu'à ce moment-là.
            self._rebuild_wrappers()
            return diff

        index = self._ensure_index()
        if index is not None:
            try:
                if new_refs:
                    resync_index(diff, server, index, tools=list(new_refs),
                                 cfg=self.manager.servers.get(server) if self.manager else None)
                elif previous:
                    # Plus aucun tool : retirer aussi le document de serveur, sinon
                    # il continuerait de peser sur l'étage 1 du routing.
                    unregister_server_tools(server, index)
                self._index_state.pop(server, None)
            except Exception as exc:
                self._index_state[server] = str(exc)
                logger.warning("mcp_index_sync_failed",
                               extra={"server": server, "error": str(exc)})
        if new_refs:
            self._indexed[server] = list(new_refs)
        else:
            self._indexed.pop(server, None)
        self._rebuild_wrappers()
        return diff

    def _indexer_si_besoin(self, serveurs: set[str]) -> None:
        """Indexe à la demande les serveurs élus qui ne le sont pas encore."""
        for nom in serveurs:
            if nom in self._indexed or nom not in self._connus:
                continue
            try:
                self._apply(nom, self._connus[nom])
            except Exception as exc:
                self._index_state[nom] = str(exc)
                logger.warning("mcp_index_lazy_failed",
                               extra={"server": nom, "error": str(exc)})

    def _rebuild_wrappers(self) -> None:
        """Reconstruit les enveloppes LangChain (objets mémoire, pas l'index).
        La partition est GLOBALE : une collision entre deux serveurs doit être vue,
        pas masquée par un traitement serveur par serveur."""
        all_refs = [ref for refs in self._connus.values() for ref in refs]
        kept, ignored = partition_by_runtime_name(all_refs)
        self._tools = build_mcp_tools(kept, self.manager, submit=self.submit)
        self._collisions = {}
        for ref, conflict in ignored:
            self._collisions.setdefault(ref.server, []).append((ref, conflict))

    def _ensure_index(self) -> ToolIndex | None:
        if self._index is not None or self._index_provided:
            return self._index
        try:
            self._index = ChromaToolIndex()
        except Exception as exc:
            # Sans index : pas de routing, mais les tools restent exécutables.
            logger.warning("mcp_index_unavailable", extra={"error": str(exc)})
            self._index = None
            self._index_provided = True
        return self._index

    # ---------- surface consommée par le graphe ----------

    @property
    def tools(self) -> list[BaseTool]:
        """Tools MCP exécutables, à passer au `ToolNode` aux côtés des natifs."""
        return list(self._tools.values())

    def _ensure_index(self) -> ToolIndex | None:
        if self._index is not None or self._index_provided:
            return self._index
        try:
            self._index = ChromaToolIndex()
        except Exception as exc:
            # Sans index : pas de routing, mais les tools restent exécutables.
            logger.warning("mcp_index_unavailable", extra={"error": str(exc)})
            self._index = None
            self._index_provided = True
        return self._index

    # ---------- surface consommée par le graphe ----------

    @property
    def tools(self) -> list[BaseTool]:
        """Tools MCP exécutables, à passer au `ToolNode` aux côtés des natifs."""
        return list(self._tools.values())

    def _signatures(self) -> dict[str, set[str]]:
        if self._signatures_cache is None:
            from src.mcp_client.config import load_config
            cfgs = load_config(self.config_path) or {}
            # Le hint SEUL. Enrichir la signature avec le vocabulaire des outils a
            # été mesuré : bruit de 6 à 10 %, et pas un cas servi de plus.
            self._signatures_cache = signatures(
                {nom: getattr(c, "capabilities_hint", "") or ""
                 for nom, c in cfgs.items()})
        return self._signatures_cache

    def select(self, query: str, actifs: set[str] = frozenset()) -> list[BaseTool]:
        """Routing à deux étages, précédé d'une PORTE.

        Sans elle, `top_servers=3` retenait les deux serveurs installés et `k=7`
        rendait sept outils — sur chaque requête, quelle qu'elle soit. Mesuré :
        Blender et Playwright liés sur 100 % des tours, 644 tokens par tour, pour
        des outils hors sujet partout sauf sur 8 tours de 184.

        Un serveur dont l'étage 1 n'a pas pu être indexé reste joignable par
        l'étage 2 seul ; sans index du tout, on expose un sous-ensemble borné.
        Une capacité dégradée vaut mieux qu'une capacité muette — mais jamais au
        prix d'un mensonge sur son état (cf. `/mcp list`).
        """
        if not self._tools:
            return []
        # Index DÉFINITIVEMENT indisponible (Ollama absent) : la porte suppose un
        # routage derrière elle pour trier ce qu'elle laisse passer. L'appliquer
        # seule ne filtrerait pas, ça tairait — et une capacité muette est pire
        # qu'une capacité large. À distinguer de « pas encore indexé ».
        if self._index is None and self._index_provided:
            return self.tools[:_MAX_UNROUTED_TOOLS]

        # La PORTE d'abord : elle lit le `capabilities_hint` de la config, pas
        # l'index. Aucune requête sans rapport ne doit payer une indexation.
        retenus = set(serveurs_pertinents(query, self._signatures(), actifs))
        retenus |= set(self._index_state)      # jamais indexés : joignables ou muets
        if not retenus:
            return []

        # L'index n'existe qu'à partir d'ici, et seulement pour les serveurs élus.
        self._indexer_si_besoin(retenus)

        # L'indexation a échoué à l'instant : on rend les outils des serveurs élus.
        if self._index is None:
            return [t for t in self.tools
                    if t.name.split("__")[0] in retenus][:_MAX_UNROUTED_TOOLS]
        try:
            names = route(query, self._index, servers=tuple(retenus),
                          unrouted_servers=tuple(self._index_state))
        except Exception as exc:
            logger.warning("mcp_routing_failed", extra={"error": str(exc)})
            return [t for t in self.tools
                    if t.name.split("__")[0] in retenus][:_MAX_UNROUTED_TOOLS]
        return [self._tools[n] for n in names if n in self._tools]

    # ---------- surface consommée par la CLI ----------

    def status(self) -> dict[str, MCPServerRuntime]:
        return self.manager.status() if self.manager else {}

    def servers(self) -> dict[str, MCPServerConfig]:
        return dict(self.manager.servers) if self.manager else {}

    def discovered(self, server: str) -> list[MCPToolRef]:
        """Ce que le serveur expose (dernier `tools/list`)."""
        conn = self.manager.connections.get(server) if self.manager else None
        return conn.tools if conn else []

    def exposed(self, server: str) -> list[MCPToolRef]:
        """Ce qui est réellement atteignable par le modèle : les découverts moins
        ceux qu'une collision de nom runtime a rendus invisibles."""
        return [ref for ref in self._connus.get(server, []) if ref.public_name in self._tools]

    def collisions(self, server: str) -> list[tuple[MCPToolRef, str]]:
        return list(self._collisions.get(server, []))

    def index_state(self, server: str) -> str | None:
        """`None` si les deux étages du routing sont indexés ; sinon la raison
        pour laquelle l'étage 1 manque. Les tools restent exposés dans les deux cas."""
        if self._index is None and self._tools:
            return "aucun index disponible (embeddings indisponibles)"
        return self._index_state.get(server)

    def add(self, cfg: MCPServerConfig) -> ToolDiff:
        self._boot()
        self.submit(self.manager.add_server(cfg), timeout=_START_TIMEOUT_S)
        return self._apply(cfg.name, self.discovered(cfg.name))

    def remove(self, server: str) -> ToolDiff:
        self._boot()
        diff = self._apply(server, [])          # désindexer AVANT de perdre la connexion
        self.submit(self.manager.remove_server(server))
        return diff

    def enable(self, server: str) -> ToolDiff:
        self._boot()
        self.submit(self.manager.enable(server), timeout=_START_TIMEOUT_S)
        return self._apply(server, self.discovered(server))

    def disable(self, server: str) -> ToolDiff:
        self._boot()
        self.submit(self.manager.disable(server))
        return self._apply(server, [])

    def refresh(self, server: str) -> ToolDiff:
        """Re-`tools/list` sans redémarrer le sous-processus."""
        self._boot()
        self.submit(self.manager.refresh(server), timeout=_START_TIMEOUT_S)
        return self._apply(server, self.discovered(server))

    def restart(self, server: str) -> ToolDiff:
        self._boot()
        self.submit(self.manager.restart(server), timeout=_START_TIMEOUT_S)
        return self._apply(server, self.discovered(server))

    def diagnose(self, server: str, deep: bool = False) -> DiagnosticReport:
        self._boot()
        return self.submit(self.manager.diagnose(server, deep), timeout=_START_TIMEOUT_S)

    def forget_server(self, server: str) -> None:
        self._apply(server, [])

    def stop(self) -> None:
        if self.manager is not None and self._loop is not None:
            try:
                self.submit(self.manager.stop(), timeout=30.0)
            except Exception:
                pass
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._loop.stop)
        self._tools.clear()
        self._indexed.clear()
        self._connus.clear()
        self._index_state.clear()
        self._signatures_cache = None
        self._collisions.clear()
        self._started = False


_runtime: MCPRuntime | None = None


def mcp_runtime() -> MCPRuntime:
    """Singleton. Toute panne est absorbée : le client MCP ne doit jamais
    empêcher Axon de démarrer."""
    global _runtime
    if _runtime is None:
        _runtime = MCPRuntime()
        try:
            _runtime.start()
        except Exception as exc:
            logger.warning("mcp_runtime_start_failed", extra={"error": str(exc)})
    return _runtime


def reset_runtime() -> None:
    """Utilisé par les tests : repart d'un runtime vierge."""
    global _runtime
    if _runtime is not None:
        _runtime.stop()
    _runtime = None
