"""Loader tennis-data.co.uk (source RÉCUPÉRÉE automatiquement — Unité B).

Lit les fixtures compactées `tests/fixtures/tennis/tennis_data_{atp,wta}_2000_2026.csv.gz`
(provenance + checksums dans docs/implementation/PROVENANCE-tennis-data.md). Produit des
`TennisMatch` (même contrat que le loader Sackmann) enrichis des cotes de CLÔTURE.

Point-in-time (Notes.txt vérifié) : classements/points au DÉBUT du tournoi et cotes « most
recent before play starts » sont PRÉ-MATCH ; `Winner/Loser`/`Comment` sont l'ISSUE
(POST-MATCH). Les non-matchs (`Walkover`) sont exclus ; les abandons (`Retired`) gardés
(le résultat au moment de l'abandon est un vrai résultat de pari « vainqueur »).
"""

from __future__ import annotations

import csv
import gzip
import hashlib
from datetime import date
from pathlib import Path

from .dataset_loader import DatasetFile, TennisDataset, TennisMatch

_FIXTURES = Path(__file__).resolve().parents[6] / "tests" / "fixtures" / "tennis"


def _int(v: str) -> int | None:
    v = (v or "").strip()
    if not v or v.upper() in ("NR", "N/A"):
        return None
    try:
        return int(float(v))
    except ValueError:
        return None


def _float(v: str) -> float | None:
    v = (v or "").strip()
    if not v:
        return None
    try:
        return float(v)
    except ValueError:
        return None


def _date(v: str) -> date | None:
    v = (v or "").strip()[:10]
    try:
        return date.fromisoformat(v)
    except ValueError:
        return None


def _row_to_match(row: dict) -> TennisMatch | None:
    d = _date(row.get("Date", ""))
    if d is None or not row.get("Winner") or not row.get("Loser"):
        return None
    if (row.get("Comment") or "").strip().lower() == "walkover":
        return None                              # non-match : jamais un résultat de jeu
    return TennisMatch(
        tourney_id="", tourney_name=(row.get("Level") or ""), tourney_date=d,
        surface=(row.get("Surface") or None), tourney_level=(row.get("Level") or None),
        best_of=_int(row.get("BestOf", "")), round=(row.get("Round") or None),
        p1_id=(row.get("Winner") or ""), p1_name=(row.get("Winner") or ""),
        p1_rank=_int(row.get("WRank", "")), p1_rank_points=_int(row.get("WPts", "")),
        p2_id=(row.get("Loser") or ""), p2_name=(row.get("Loser") or ""),
        p2_rank=_int(row.get("LRank", "")), p2_rank_points=_int(row.get("LPts", "")),
        outcome="p1", score=None, minutes=None, comment=(row.get("Comment") or None),
        p1_close_odds=_float(row.get("AvgW", "")) or _float(row.get("B365W", "")),
        p2_close_odds=_float(row.get("AvgL", "")) or _float(row.get("B365L", "")))


def load_tennis_data(tour: str, path: Path | None = None) -> TennisDataset:
    """Charge le dataset tennis-data.co.uk d'un tour ('atp'|'wta') depuis la fixture
    embarquée (ou un chemin explicite). Trie chronologiquement (walk-forward sans fuite)."""
    tour = tour.lower()
    if tour not in ("atp", "wta"):
        raise ValueError(f"tour invalide : {tour!r}")
    p = Path(path) if path is not None else _FIXTURES / f"tennis_data_{tour}_2000_2026.csv.gz"
    raw = p.read_bytes()
    checksum = "sha256:" + hashlib.sha256(raw).hexdigest()
    text = gzip.decompress(raw).decode("utf-8")
    rows = list(csv.DictReader(text.splitlines()))
    matches = [m for m in (_row_to_match(r) for r in rows) if m is not None]
    matches.sort(key=lambda m: m.tourney_date)
    period = (matches[0].tourney_date, matches[-1].tourney_date) if matches else None
    return TennisDataset(
        tour=tour, matches=tuple(matches),
        files=(DatasetFile(path=str(p), checksum=checksum, rows=len(matches)),), period=period)
