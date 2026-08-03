"""Config du client MCP (src/mcp_client/config.py).

Trois propriétés valent d'être verrouillées :
  - une variable `${VAR}` absente lève une erreur explicite (jamais de secret vide) ;
  - `build_subprocess_env` part de `get_default_environment()` et ne déverse donc
    pas l'environnement complet d'Axon — tokens compris — dans un serveur tiers ;
  - le chemin résolu est normalisé, parce que c'est la ligne de diagnostic qui sert
    à comprendre un PATH divergent.
"""

from __future__ import annotations

import json
import os

import pytest

from src.mcp_client.config import (
    build_subprocess_env,
    load_config,
    resolve_command,
    resolve_env,
    save_config,
    server_from_dict,
)
from src.mcp_client.models import MCPServerConfig

_RAW = {
    "servers": {
        "alpha": {
            "transport": "stdio",
            "command": "alpha-server",
            "args": ["--python", "3.11", "alpha"],
            "env": {"ALPHA_PORT": "1234"},
            "enabled": True,
            "timeouts": {"connect_s": 15, "list_tools_s": 15, "call_s": 90},
            "tool_timeouts": {"execute_snippet": 180},
            "health": {
                "probe_tool": "get_status",
                "failure_patterns": ["backend unavailable"],
                "consecutive_failures_to_degrade": 2,
            },
            "capabilities_hint": "modélisation, matériaux, export",
            "risk_overrides": {"execute_snippet": "execute"},
        }
    }
}


def test_load_config_fichier_absent_nest_pas_une_erreur(tmp_path):
    assert load_config(tmp_path / "absent.json") == {}


def test_load_config_lit_toutes_les_sections(tmp_path):
    path = tmp_path / "mcp_servers.json"
    path.write_text(json.dumps(_RAW), encoding="utf-8")

    cfg = load_config(path)["alpha"]
    assert cfg.command == "alpha-server"
    assert cfg.timeouts.call_s == 90 and cfg.timeouts.connect_s == 15
    assert cfg.tool_timeouts == {"execute_snippet": 180.0}
    assert cfg.health.probe_tool == "get_status"
    assert cfg.health.failure_patterns == ["backend unavailable"]
    assert cfg.health.consecutive_failures_to_degrade == 2
    assert cfg.risk_overrides == {"execute_snippet": "execute"}


def test_roundtrip_save_load(tmp_path):
    path = tmp_path / "sub" / "mcp_servers.json"
    servers = load_config_from_raw()
    save_config(path, servers)
    assert load_config(path) == servers


def load_config_from_raw() -> dict[str, MCPServerConfig]:
    return {name: server_from_dict(name, raw) for name, raw in _RAW["servers"].items()}


def test_save_config_est_atomique_et_ne_laisse_pas_de_tmp(tmp_path):
    path = tmp_path / "mcp_servers.json"
    save_config(path, load_config_from_raw())
    assert path.exists()
    assert [p.name for p in tmp_path.iterdir()] == ["mcp_servers.json"]
    assert oct(path.stat().st_mode)[-3:] == "600"


def test_cle_inconnue_rejetee_plutot_qu_ignoree():
    # Une faute de frappe qui désactiverait silencieusement un réglage doit se voir.
    with pytest.raises(ValueError, match="capabilities_hnit"):
        server_from_dict("alpha", {"command": "x", "capabilities_hnit": "oops"})
    with pytest.raises(ValueError, match="max_retires"):
        server_from_dict("alpha", {"command": "x", "reconnect": {"max_retires": 3}})


def test_transport_non_supporte_rejete():
    with pytest.raises(ValueError, match="non supporté"):
        server_from_dict("alpha", {"transport": "sse", "command": "x"})


def test_resolve_env_substitue(monkeypatch):
    monkeypatch.setenv("ALPHA_TOKEN", "s3cret")
    assert resolve_env({"TOKEN": "${ALPHA_TOKEN}"}) == {"TOKEN": "s3cret"}
    assert resolve_env({"URL": "http://x/${ALPHA_TOKEN}/y"}) == {"URL": "http://x/s3cret/y"}


def test_resolve_env_variable_absente_leve_une_erreur_explicite(monkeypatch):
    monkeypatch.delenv("ALPHA_TOKEN", raising=False)
    with pytest.raises(KeyError) as err:
        resolve_env({"TOKEN": "${ALPHA_TOKEN}"})
    assert "ALPHA_TOKEN" in str(err.value) and "TOKEN" in str(err.value)


def test_build_subprocess_env_ne_propage_pas_les_secrets_non_declares(monkeypatch):
    monkeypatch.setenv("AXON_UNRELATED_TOKEN", "ne-doit-pas-fuiter")
    env = build_subprocess_env(MCPServerConfig(name="alpha", env={"ALPHA_PORT": "1234"}))

    assert env["ALPHA_PORT"] == "1234"
    assert "AXON_UNRELATED_TOKEN" not in env
    assert "PATH" in env  # un env vide priverait le sous-processus de son PATH


def test_build_subprocess_env_declaration_explicite_autorisee(monkeypatch):
    monkeypatch.setenv("AXON_NEEDED", "ok")
    env = build_subprocess_env(MCPServerConfig(name="a", env={"AXON_NEEDED": "${AXON_NEEDED}"}))
    assert env["AXON_NEEDED"] == "ok"


def test_resolve_command_normalise_le_chemin(monkeypatch, tmp_path):
    real = tmp_path / "bin"
    real.mkdir()
    (real / "tool").write_text("#!/bin/sh\n")
    monkeypatch.setattr("shutil.which", lambda _c: str(tmp_path / "bin" / ".." / "bin" / "tool"))

    resolved = resolve_command("tool")
    assert resolved == os.path.realpath(str(real / "tool"))
    assert ".." not in resolved


def test_resolve_command_introuvable(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _c: None)
    assert resolve_command("nexiste-pas") is None
    assert resolve_command("") is None
