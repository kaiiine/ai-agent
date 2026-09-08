"""Journal des échecs par backend — pour remplacer une impression par une mesure.

« gemini foire tout le temps », « mistral n'est pas stable » : ces phrases sont
probablement vraies, mais on ne peut ni les vérifier ni savoir ce qui a été
corrigé sans compter. Ce module enregistre chaque échec avec son backend, son
type et la stratégie qui a permis (ou non) de s'en sortir.

Volontairement minimal : un fichier JSONL en append, aucune dépendance, aucune
I/O à l'import. Un journal qui coûte cher ou qui casse est un journal qu'on
finit par désactiver.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from src.infra import chemins as _chemins

LOG_PATH = _chemins.echecs_backend()

# Au-delà, on repart d'un fichier neuf : un journal de diagnostic ne doit pas
# grandir sans fin sur la machine de quelqu'un.
_MAX_BYTES = 2_000_000


def record(*, backend: str, error_type: str, message: str,
           strategy: str, recovered: bool, path: Path | None = None) -> None:
    """Consigne un échec. Ne lève JAMAIS : un journal qui casse le tour qu'il
    observe serait exactement le défaut qu'on cherche à corriger."""
    target = path or LOG_PATH
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and target.stat().st_size > _MAX_BYTES:
            target.unlink()
        entry = {
            "at": datetime.now(timezone.utc).isoformat(),
            "backend": backend,
            "error_type": error_type,
            "message": message[:300],
            "strategy": strategy,          # retry | provider_switch | no_tools | none
            "recovered": recovered,
        }
        with target.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


def summary(path: Path | None = None) -> dict:
    """Agrégat par backend : combien d'échecs, de quels types, et quelle part a
    été rattrapée. C'est ce chiffre-là qui doit décider d'un correctif, pas une
    impression laissée par les deux dernières sessions."""
    target = path or LOG_PATH
    stats: dict[str, dict] = {}
    if not target.exists():
        return stats

    try:
        lignes = target.read_text(encoding="utf-8").splitlines()
    except Exception:
        return stats

    for ligne in lignes:
        try:
            e = json.loads(ligne)
        except Exception:
            continue                      # une ligne corrompue n'invalide pas le reste
        s = stats.setdefault(e.get("backend", "?"), {
            "total": 0, "recovered": 0, "types": {}, "strategies": {}})
        s["total"] += 1
        s["recovered"] += bool(e.get("recovered"))
        s["types"][e.get("error_type", "?")] = s["types"].get(e.get("error_type", "?"), 0) + 1
        strat = e.get("strategy", "none")
        s["strategies"][strat] = s["strategies"].get(strat, 0) + 1

    for s in stats.values():
        s["recovery_rate"] = round(s["recovered"] / s["total"], 3) if s["total"] else 0.0
    return stats


def render(path: Path | None = None) -> list[str]:
    """Rendu texte du résumé, pour une commande de diagnostic."""
    stats = summary(path)
    if not stats:
        return ["Aucun échec enregistré."]

    out = ["Échecs par backend :", ""]
    for backend, s in sorted(stats.items(), key=lambda kv: -kv[1]["total"]):
        out.append(f"  {backend:14s} {s['total']:4d} échecs   "
                   f"{s['recovery_rate']:.0%} rattrapés")
        for t, n in sorted(s["types"].items(), key=lambda kv: -kv[1])[:4]:
            out.append(f"       {n:4d}  {t}")
    return out
