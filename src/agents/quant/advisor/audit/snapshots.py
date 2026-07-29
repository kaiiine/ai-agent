"""Snapshots COMPLETS des configurations consommées (Lot 10 §7). Le payload
archive le CONTENU EXACT (pas seulement nom/version/checksum) : le replay
historique ne dépend jamais de l'existence future de `configs/advisor/*.json`.

Le checksum du snapshot garantit l'intégrité du contenu archivé ; il n'est PAS un
pointeur vers l'état courant du disque (drift = hors scope V1)."""

from __future__ import annotations

import json
import pathlib

from ..combos.policy import _CONFIG_PATH as _COMBO_PATH, load_combo_policy
from ..policy.eligibility import _CONFIG_PATH as _POLICY_PATH, load_policy_config
from ..portfolio.constraints import _CONFIG_PATH as _PORTFOLIO_PATH, load_portfolio_caps
from ..ranking.profiles import _CONFIG_PATH as _RANKING_PATH, load_ranking_profiles
from ..recommendation.simple import _CONFIG_PATH as _SIZING_PATH, load_sizing_profiles
from . import canonical
from .errors import ConfigSnapshotCorrupt
from .schema import ConfigSnapshot

# config_name -> (chemin par défaut, kwarg de run_pipeline, loader)
_CONFIGS = {
    "eligibility_policy": (_POLICY_PATH, "policy_config", load_policy_config),
    "ranking_profiles": (_RANKING_PATH, "ranking_profiles", load_ranking_profiles),
    "sizing_policy": (_SIZING_PATH, "sizing_profiles", load_sizing_profiles),
    "portfolio_policy": (_PORTFOLIO_PATH, "portfolio_caps", load_portfolio_caps),
    "combo_policy": (_COMBO_PATH, "combo_policy", load_combo_policy),
}


def _snapshot(config_name: str, path: pathlib.Path) -> ConfigSnapshot:
    content = json.loads(path.read_text(encoding="utf-8"))
    version = content.get("config_version") or content.get("version") or "?"
    return ConfigSnapshot(config_name, version, canonical.checksum(content), content)


def build_config_snapshots(*, allow_combos: bool) -> tuple[ConfigSnapshot, ...]:
    """Snapshots des configs RÉELLEMENT consommées : combo uniquement si demandé."""
    names = ["eligibility_policy", "ranking_profiles", "sizing_policy", "portfolio_policy"]
    if allow_combos:
        names.append("combo_policy")
    return tuple(_snapshot(n, _CONFIGS[n][0]) for n in names)


def verify_snapshot(config_name: str, content, expected_checksum: str) -> None:
    if canonical.checksum(content) != expected_checksum:
        raise ConfigSnapshotCorrupt(f"snapshot de config corrompu : {config_name}")


def reconstruct_configs(snapshot_dicts, tmp_dir: pathlib.Path) -> dict:
    """Reconstruit les configs depuis les snapshots ARCHIVÉS (jamais le disque
    courant) : écrit le contenu dans un fichier temporaire et réutilise le loader
    réel. Vérifie le checksum du snapshot AVANT usage."""
    kwargs: dict = {}
    for snap in snapshot_dicts:
        name, content, chk = snap["config_name"], snap["content"], snap["checksum"]
        verify_snapshot(name, content, chk)
        _, kwarg, loader = _CONFIGS[name]
        path = tmp_dir / f"{name}.json"
        path.write_text(json.dumps(content, ensure_ascii=False), encoding="utf-8")
        kwargs[kwarg] = loader(path)
    return kwargs
