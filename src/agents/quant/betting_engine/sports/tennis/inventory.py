"""Inventaire/validation d'un dataset tennis chargé (Unité B §2).

Sur les VRAIS fichiers fournis : taux de valeurs manquantes par champ, période réellement
couverte, distributions (surface, best_of, niveau), complétude point-in-time. Aucune
statistique de modèle ici — pure caractérisation de données (le fork méthodologique reste
ouvert, §4).
"""

from __future__ import annotations

from collections import Counter

from .dataset_loader import POST_MATCH_FIELDS, PRE_MATCH_FIELDS, TennisDataset

_FIELDS = {
    "surface": lambda m: m.surface,
    "tourney_level": lambda m: m.tourney_level,
    "best_of": lambda m: m.best_of,
    "round": lambda m: m.round,
    "p1_rank": lambda m: m.p1_rank,
    "p2_rank": lambda m: m.p2_rank,
    "p1_rank_points": lambda m: m.p1_rank_points,
    "p2_rank_points": lambda m: m.p2_rank_points,
    "score": lambda m: m.score,
    "minutes": lambda m: m.minutes,
}


def inventory(ds: TennisDataset) -> dict:
    n = ds.n
    def missing_rate(getter):
        return round(sum(1 for m in ds.matches if getter(m) in (None, "")) / n, 4) if n else None
    return {
        "tour": ds.tour,
        "n_matches": n,
        "period": None if ds.period is None else (ds.period[0].isoformat(), ds.period[1].isoformat()),
        "files": [{"path": f.path, "checksum": f.checksum, "rows": f.rows} for f in ds.files],
        "missing_rate": {name: missing_rate(g) for name, g in _FIELDS.items()},
        "surface_dist": dict(Counter(m.surface for m in ds.matches)),
        "best_of_dist": dict(Counter(m.best_of for m in ds.matches)),
        "level_dist": dict(Counter(m.tourney_level for m in ds.matches)),
        "pre_match_complete_rate": (
            round(sum(1 for m in ds.matches if m.is_pre_match_complete) / n, 4) if n else None),
        "pre_match_fields": list(PRE_MATCH_FIELDS),
        "post_match_fields_excluded_from_features": list(POST_MATCH_FIELDS),
    }


def render(ds: TennisDataset) -> list[str]:
    inv = ds and inventory(ds)
    lines = [
        f"Tennis dataset [{inv['tour'].upper()}] — {inv['n_matches']} match(s)",
        f"  période        : {inv['period']}",
        f"  fichiers       : {len(inv['files'])} (provenance + checksum sha256)",
    ]
    for f in inv["files"]:
        lines.append(f"    {f['path']} | {f['checksum'][:19]}… | {f['rows']} lignes")
    lines.append(f"  surface        : {inv['surface_dist']}")
    lines.append(f"  best_of        : {inv['best_of_dist']}")
    lines.append(f"  niveau         : {inv['level_dist']}")
    lines.append("  taux manquants :")
    for name, rate in inv["missing_rate"].items():
        lines.append(f"    {name:16} {rate}")
    lines.append(f"  complétude pré-match (surface+2 classements) : {inv['pre_match_complete_rate']}")
    lines.append(f"  features PRE-MATCH admissibles : {', '.join(inv['pre_match_fields'])}")
    lines.append(f"  EXCLUS des features (post-match/fuite) : {', '.join(inv['post_match_fields_excluded_from_features'])}")
    return lines
