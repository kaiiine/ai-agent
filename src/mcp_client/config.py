"""Chargement / écriture de `.axon/mcp_servers.json` (DESIGN §4, ADDENDUM v2.1 §3, §5).

Deux règles de sécurité portées par ce module :

1. Aucun secret en clair en config. La syntaxe `"${VAR}"` est résolue au lancement,
   et une variable absente lève une erreur explicite plutôt que de démarrer le
   serveur avec un secret vide.
2. L'environnement transmis au sous-processus part de `get_default_environment()`
   (sous-ensemble assaini par le SDK) et NON de `os.environ` : déverser tout
   l'environnement d'Axon — tokens compris — dans chaque serveur tiers est une
   fuite gratuite. Une variable hors de ce set se déclare explicitement en config.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

from mcp.client.stdio import get_default_environment

from src.mcp_client.models import (
    MCPHealthPolicy,
    MCPReconnectPolicy,
    MCPServerConfig,
    MCPTimeouts,
)

_VAR_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")

_SERVER_KEYS = {
    "transport", "command", "args", "env", "enabled", "timeouts", "tool_timeouts",
    "reconnect", "health", "capabilities_hint", "risk_overrides",
}
_SUPPORTED_TRANSPORTS = ("stdio",)


def _section(raw: dict[str, Any], key: str, cls):
    """Instancie une dataclass de politique en refusant les clés inconnues :
    une faute de frappe dans la config doit se voir immédiatement, pas se traduire
    par un réglage silencieusement ignoré."""
    section = raw.get(key) or {}
    if not isinstance(section, dict):
        raise ValueError(f"'{key}' doit être un objet JSON")
    allowed = {f for f in cls.__dataclass_fields__}
    unknown = set(section) - allowed
    if unknown:
        raise ValueError(f"clés inconnues dans '{key}': {sorted(unknown)}")
    return cls(**section)


def server_from_dict(name: str, raw: dict[str, Any]) -> MCPServerConfig:
    unknown = set(raw) - _SERVER_KEYS
    if unknown:
        raise ValueError(f"serveur '{name}': clés inconnues {sorted(unknown)}")

    transport = raw.get("transport", "stdio")
    if transport not in _SUPPORTED_TRANSPORTS:
        raise ValueError(
            f"serveur '{name}': transport '{transport}' non supporté en v1 "
            f"(supportés: {', '.join(_SUPPORTED_TRANSPORTS)})"
        )

    return MCPServerConfig(
        name=name,
        transport=transport,
        command=raw.get("command", ""),
        args=list(raw.get("args", [])),
        env=dict(raw.get("env", {})),
        enabled=bool(raw.get("enabled", True)),
        timeouts=_section(raw, "timeouts", MCPTimeouts),
        tool_timeouts={k: float(v) for k, v in (raw.get("tool_timeouts") or {}).items()},
        reconnect=_section(raw, "reconnect", MCPReconnectPolicy),
        health=_section(raw, "health", MCPHealthPolicy),
        capabilities_hint=raw.get("capabilities_hint", ""),
        risk_overrides=dict(raw.get("risk_overrides", {})),
    )


def server_to_dict(cfg: MCPServerConfig) -> dict[str, Any]:
    return {
        "transport": cfg.transport,
        "command": cfg.command,
        "args": list(cfg.args),
        "env": dict(cfg.env),
        "enabled": cfg.enabled,
        "timeouts": vars(cfg.timeouts).copy(),
        "tool_timeouts": dict(cfg.tool_timeouts),
        "reconnect": vars(cfg.reconnect).copy(),
        "health": vars(cfg.health).copy(),
        "capabilities_hint": cfg.capabilities_hint,
        "risk_overrides": dict(cfg.risk_overrides),
    }


def load_config(path: Path) -> dict[str, MCPServerConfig]:
    """Fichier absent = aucun serveur déclaré, pas une erreur."""
    path = Path(path)
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    servers = raw.get("servers", {})
    if not isinstance(servers, dict):
        raise ValueError("'servers' doit être un objet JSON")
    return {name: server_from_dict(name, cfg) for name, cfg in servers.items()}


def save_config(path: Path, servers: dict[str, MCPServerConfig]) -> None:
    """Écriture atomique (tmp + rename) : une écriture interrompue ne doit jamais
    laisser une config tronquée. Permissions restreintes par précaution."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"servers": {name: server_to_dict(cfg) for name, cfg in servers.items()}}
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def resolve_env(env: dict[str, str]) -> dict[str, str]:
    """Résout `"${VAR}"` depuis `os.environ`. Lève une erreur explicite si une
    variable référencée est absente, plutôt que de lancer le serveur avec un
    secret vide — un serveur qui démarre avec un token vide échoue plus tard et
    beaucoup moins clairement."""
    out: dict[str, str] = {}
    for key, value in env.items():
        def _sub(match: re.Match) -> str:
            name = match.group(1)
            if name not in os.environ:
                raise KeyError(f"Variable d'environnement manquante: {name} (requise par {key})")
            return os.environ[name]

        out[key] = _VAR_PATTERN.sub(_sub, str(value))
    return out


def build_subprocess_env(cfg: MCPServerConfig) -> dict[str, str]:
    """`get_default_environment()` plutôt que `os.environ` : sous-ensemble assaini
    par le SDK, qui évite de propager à un serveur tiers des secrets sans rapport
    avec lui. Le merge reste indispensable — un env de config seul priverait le
    sous-processus de son PATH."""
    return {**get_default_environment(), **resolve_env(cfg.env)}


def resolve_command(command: str) -> str | None:
    """Chemin absolu NORMALISÉ de la commande. Affiché par `/mcp test` : c'est la
    ligne qui fait gagner le plus de temps quand le PATH d'Axon diffère de celui
    du terminal, donc elle doit être lisible (`shutil.which` peut renvoyer un
    chemin contenant des `..`)."""
    if not command:
        return None
    found = shutil.which(command)
    return os.path.realpath(found) if found else None
