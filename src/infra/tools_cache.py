# src/infra/tools_cache.py
from __future__ import annotations

import json
import time

# TTL en secondes par outil — None = pas de cache pour cet outil
CACHE_TTLS: dict[str, int] = {
    "local_read_file":      30,
    "local_list_directory": 30,
    "local_find_file":      60,
    "local_glob":           30,
    "git_status":           15,
    "git_log":              30,
    "git_diff":             20,
    "web_research_report":  300,
    "web_search_news":      120,
}

CACHEABLE_TOOLS: frozenset[str] = frozenset(CACHE_TTLS)

# Caches filesystem + git invalidés ensemble après toute écriture de fichier
_FILESYSTEM_CACHES = (
    "git_status", "git_diff", "git_log",
    "local_read_file", "local_list_directory", "local_find_file", "local_glob",
)

# Quand ces outils s'exécutent, invalider les groupes de cache correspondants
_INVALIDATES: dict[str, tuple[str, ...]] = {
    "git_add":            ("git_status", "git_diff"),
    "git_commit":         ("git_status", "git_log", "git_diff"),
    "git_stash":          ("git_status", "git_diff"),
    "shell_run":          _FILESYSTEM_CACHES,
    # Writing a file via the coding specialist must bust the read cache immediately
    "propose_file_change": _FILESYSTEM_CACHES,
}


class SessionCache:
    def __init__(self) -> None:
        self._data: dict[str, tuple[float, object, int]] = {}

    def _key(self, name: str, args: dict) -> str:
        return f"{name}:{json.dumps(args, sort_keys=True, default=str)}"

    def get(self, name: str, args: dict) -> object | None:
        entry = self._data.get(self._key(name, args))
        if entry is None:
            return None
        ts, value, ttl = entry
        if time.time() - ts > ttl:
            del self._data[self._key(name, args)]
            return None
        return value

    def set(self, name: str, args: dict, value: object, ttl: int | None = None) -> None:
        t = ttl if ttl is not None else CACHE_TTLS.get(name, 60)
        self._data[self._key(name, args)] = (time.time(), value, t)

    def invalidate(self, *names: str) -> None:
        prefix_set = {n + ":" for n in names}
        for key in list(self._data):
            if any(key.startswith(p) for p in prefix_set):
                del self._data[key]

    def on_tool_executed(self, tool_name: str) -> None:
        targets = _INVALIDATES.get(tool_name)
        if targets:
            self.invalidate(*targets)

    def invalidate_filesystem(self) -> None:
        """Vide tous les caches filesystem + git. À appeler après toute écriture de fichier externe."""
        self.invalidate(*_FILESYSTEM_CACHES)

    def clear(self) -> None:
        self._data.clear()

    def __len__(self) -> int:
        return len(self._data)


session_cache = SessionCache()
