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


#: Backfill sous licence CC BY-NC-SA 4.0 (Jeff Sackmann / Tennis Abstract) —
#: Challenger, qualifications et Futures, que tennis-data.co.uk ne couvre PAS.
#: Ces rencontres construisent la force des joueurs sans jamais servir de cible :
#: c'est `TennisMatch.circuit` qui porte la distinction.
_BACKFILL = {"atp": "tennis_sackmann_atp_backfill.csv.gz",
             "wta": "tennis_kaggle_wta_backfill.csv.gz"}

#: Circuits RETENUS comme contexte. Les Futures (ITF) sont dans la fixture mais
#: écartés ici — la décision reste donc lisible et remesurable, au lieu d'être
#: gravée dans un fichier amputé.
#:
#: MESURÉ sur le corpus ATP réel, écart de Brier apparié sur les 54 708
#: rencontres évaluables dans tous les cas :
#:
#:     challenger + qualifs + tour   couverture 0.9366   ΔBrier +0.000539
#:     …et Futures en plus           couverture 0.9586   ΔBrier +0.003083
#:
#: Deux points de couverture de plus coûtent six fois plus de précision. La
#: raison est de domaine, pas de réglage : un tableau ITF se joue à un niveau si
#: éloigné du circuit principal qu'y faire évoluer la note d'un joueur la rend
#: moins comparable à celle de ses futurs adversaires. Le Brier ABSOLU du corpus
#: retenu (0.212428) est d'ailleurs meilleur que sans aucun backfill (0.212959).
#: MESURÉ côté WTA (dataset Kaggle, écart apparié sur les 34 954 rencontres
#: évaluables dans tous les cas) :
#:
#:     tour seul               couverture 0.8393   ΔBrier +0.000869
#:     + équipes (Fed Cup)     couverture 0.8503   ΔBrier +0.000840
#:     + ITF / satellites      couverture 0.8545   ΔBrier +0.000855
#:     + exhibitions, juniors  couverture 0.8545   ΔBrier identique
#:
#: Les trois premiers niveaux se valent à la troisième décimale et apportent
#: chacun de la couverture : on les garde. Les exhibitions et les tableaux
#: juniors n'apportent AUCUNE évaluation supplémentaire — un match d'exhibition
#: n'est pas un résultat de compétition, et le corpus n'a pas à porter ce qui ne
#: change rien.
CIRCUITS_RETENUS = frozenset({
    "challenger_qualifying", "tour",    # ATP (Sackmann)
    "equipes", "itf",                   # WTA (Kaggle)
})


def _backfill_rows(tour: str):
    """Rencontres de backfill, ou rien si la fixture est absente.

    L'absence n'est pas une erreur : le WTA n'a aucun miroir sous licence
    identifiable, et le modèle doit fonctionner sans — dégradé, pas cassé.
    """
    nom = _BACKFILL.get(tour)
    if not nom:
        return [], None
    p = _FIXTURES / nom
    if not p.exists():
        return [], None
    raw = p.read_bytes()
    texte = gzip.decompress(raw).decode("utf-8")
    matches = []
    for r in csv.DictReader(texte.splitlines()):
        if (r.get("circuit") or "") not in CIRCUITS_RETENUS:
            continue
        try:
            jour = date.fromisoformat(r["date"])
        except (KeyError, ValueError):
            continue
        matches.append(TennisMatch(
            tourney_id=r.get("tourney_id", ""), tourney_name=r.get("tourney_name", ""),
            tourney_date=jour, surface=(r.get("surface") or None),
            tourney_level=(r.get("level") or None), best_of=_int(r.get("best_of", "")),
            round=(r.get("round") or None),
            p1_id="", p1_name=r["p1"], p1_rank=_int(r.get("p1_rank", "")),
            p1_rank_points=None,
            p2_id="", p2_name=r["p2"], p2_rank=_int(r.get("p2_rank", "")),
            p2_rank_points=None,
            outcome="p1", score=(r.get("score") or None), minutes=None,
            circuit=r.get("circuit") or "challenger_qualifying"))
    return matches, DatasetFile(
        path=str(p), checksum="sha256:" + hashlib.sha256(raw).hexdigest(),
        rows=len(matches))


def load_tennis_data(tour: str, path: Path | None = None, *,
                     avec_backfill: bool = True) -> TennisDataset:
    """Charge le dataset tennis d'un tour ('atp'|'wta'), backfill compris.

    Trie chronologiquement — le walk-forward suppose que les rencontres arrivent
    dans le temps, et un corpus mal ordonné fuiterait.

    `avec_backfill=False` restitue le corpus D'ORIGINE : c'est la seule façon de
    remesurer l'écart sans refaire le pipeline, et un chemin explicite vaut mieux
    qu'une fixture qu'on renomme.
    """
    tour = tour.lower()
    if tour not in ("atp", "wta"):
        raise ValueError(f"tour invalide : {tour!r}")
    p = Path(path) if path is not None else _FIXTURES / f"tennis_data_{tour}_2000_2026.csv.gz"
    raw = p.read_bytes()
    checksum = "sha256:" + hashlib.sha256(raw).hexdigest()
    text = gzip.decompress(raw).decode("utf-8")
    rows = list(csv.DictReader(text.splitlines()))
    matches = [m for m in (_row_to_match(r) for r in rows) if m is not None]
    fichiers = [DatasetFile(path=str(p), checksum=checksum, rows=len(matches))]

    if avec_backfill and path is None:
        complement, fichier = _backfill_rows(tour)
        if complement:
            matches.extend(complement)
            fichiers.append(fichier)

    # Tri STABLE sur la date seule : à date égale, l'ordre d'insertion place le
    # circuit principal avant le backfill. Peu importe lequel passe en premier —
    # aucun des deux ne peut informer l'autre, la comparaison restant stricte.
    matches.sort(key=lambda m: m.tourney_date)
    period = (matches[0].tourney_date, matches[-1].tourney_date) if matches else None
    return TennisDataset(tour=tour, matches=tuple(matches),
                         files=tuple(fichiers), period=period)
