"""Loader dataset tennis HISTORIQUE — source LOCALE explicite (Unité B §1).

Charge des CSV Jeff Sackmann (`atp_matches_*.csv` / `wta_matches_*.csv`) depuis un
RÉPERTOIRE fourni par l'utilisateur. AUCUN téléchargement (ni silencieux, ni de secours) :
si le répertoire est absent/vide, on lève — jamais un repli inventé. Chaque fichier est
tracé (provenance + checksum sha256) ; le manifeste porte la période réelle et le tour.

SÉPARATION POINT-IN-TIME (§3) stricte, exposée comme donnée de premier ordre :
- `PRE_MATCH_FIELDS`  : connus AVANT le match (surface, niveau, best_of, round, identités
  des 2 joueurs, classements + points de classement pré-tournoi) -> features admissibles ;
- `POST_MATCH_FIELDS` : produits par/après le match (désignation winner/loser = l'ISSUE,
  score, durée, stats de service) -> JAMAIS des features (fuite). Le loader les conserve
  pour l'audit mais les marque post-match.

Le nommage Sackmann encode l'issue dans les colonnes (`winner_*`/`loser_*`) : la
désignation winner/loser EST l'issue (post-match). Les CLASSEMENTS `winner_rank`/
`loser_rank` sont eux pré-tournoi (publiés avant) donc pré-match — mais toute feature
doit rester SYMÉTRIQUE (ne jamais lire « qui est le winner »).
"""

from __future__ import annotations

import csv
import hashlib
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

# Colonnes disponibles AVANT le match (features admissibles).
PRE_MATCH_FIELDS = (
    "tourney_date", "surface", "tourney_level", "best_of", "round",
    "p1_id", "p1_name", "p1_rank", "p1_rank_points",
    "p2_id", "p2_name", "p2_rank", "p2_rank_points",
)
# Colonnes produites PAR/APRÈS le match — jamais des features (fuite).
POST_MATCH_FIELDS = ("outcome", "score", "minutes", "serve_stats")

_SURFACES = {"Hard", "Clay", "Grass", "Carpet"}


@dataclass(frozen=True)
class TennisMatch:
    tourney_id: str
    tourney_name: str
    tourney_date: date               # début du tournoi (Sackmann : granularité tournoi)
    surface: str | None
    tourney_level: str | None
    best_of: int | None
    round: str | None
    # Deux joueurs — p1 = vainqueur, p2 = perdant. `outcome="p1"` EST l'issue (post-match).
    p1_id: str; p1_name: str; p1_rank: int | None; p1_rank_points: int | None
    p2_id: str; p2_name: str; p2_rank: int | None; p2_rank_points: int | None
    outcome: str                     # "p1" (le vainqueur) — POST-MATCH
    score: str | None                # POST-MATCH
    minutes: int | None              # POST-MATCH
    # Optionnels (source tennis-data.co.uk). `comment` = statut (Completed/Retired/Walkover)
    # — POST-MATCH mais utile pour filtrer les non-matchs. Les cotes de CLÔTURE sont
    # PRÉ-MATCH (« most recent before play starts ») : admissibles en baseline/CLV, mais
    # étiquetées p1/p2 (vainqueur/perdant) → à ne lire que SYMÉTRIQUEMENT.
    comment: str | None = None
    p1_close_odds: float | None = None
    p2_close_odds: float | None = None

    @property
    def is_pre_match_complete(self) -> bool:
        """Toutes les features PRE-MATCH minimales présentes (surface + 2 classements)."""
        return (self.surface in _SURFACES and self.p1_rank is not None
                and self.p2_rank is not None)


@dataclass(frozen=True)
class DatasetFile:
    path: str
    checksum: str                    # sha256 du contenu brut
    rows: int


@dataclass(frozen=True)
class TennisDataset:
    tour: str                        # "atp" | "wta"
    matches: tuple[TennisMatch, ...]
    files: tuple[DatasetFile, ...]   # provenance + checksum par fichier
    period: tuple[date, date] | None # (première, dernière) date de tournoi réellement couverte

    @property
    def n(self) -> int:
        return len(self.matches)


def _int(v: str | None) -> int | None:
    v = (v or "").strip()
    if not v:
        return None
    try:
        return int(float(v))
    except ValueError:
        return None


def _date(v: str | None) -> date | None:
    v = (v or "").strip()
    if len(v) != 8 or not v.isdigit():          # Sackmann : YYYYMMDD
        return None
    try:
        return datetime.strptime(v, "%Y%m%d").date()
    except ValueError:
        return None


def _row_to_match(row: dict) -> TennisMatch | None:
    d = _date(row.get("tourney_date"))
    if d is None or not row.get("winner_name") or not row.get("loser_name"):
        return None                              # ligne inexploitable -> ignorée (jamais fabriquée)
    return TennisMatch(
        tourney_id=str(row.get("tourney_id", "")), tourney_name=str(row.get("tourney_name", "")),
        tourney_date=d, surface=(row.get("surface") or None),
        tourney_level=(row.get("tourney_level") or None), best_of=_int(row.get("best_of")),
        round=(row.get("round") or None),
        p1_id=str(row.get("winner_id", "")), p1_name=str(row.get("winner_name")),
        p1_rank=_int(row.get("winner_rank")), p1_rank_points=_int(row.get("winner_rank_points")),
        p2_id=str(row.get("loser_id", "")), p2_name=str(row.get("loser_name")),
        p2_rank=_int(row.get("loser_rank")), p2_rank_points=_int(row.get("loser_rank_points")),
        outcome="p1", score=(row.get("score") or None), minutes=_int(row.get("minutes")))


def load_sackmann_dir(directory: str | Path, tour: str) -> TennisDataset:
    """Charge tous les `{tour}_matches_*.csv` d'un répertoire LOCAL explicite.

    Lève `FileNotFoundError` si le répertoire n'existe pas et `ValueError` s'il ne contient
    aucun fichier du tour demandé — jamais un téléchargement de secours."""
    tour = tour.lower()
    if tour not in ("atp", "wta"):
        raise ValueError(f"tour invalide : {tour!r} (attendu 'atp' ou 'wta')")
    d = Path(directory)
    if not d.is_dir():
        raise FileNotFoundError(f"répertoire dataset introuvable : {d} (fournir les CSV Sackmann)")
    paths = sorted(d.glob(f"{tour}_matches_*.csv"))
    if not paths:
        raise ValueError(
            f"aucun fichier {tour}_matches_*.csv dans {d} — placez-y les CSV Jeff Sackmann "
            f"({tour}) ; aucun téléchargement automatique.")
    matches: list[TennisMatch] = []
    files: list[DatasetFile] = []
    for p in paths:
        raw = p.read_bytes()
        checksum = "sha256:" + hashlib.sha256(raw).hexdigest()
        text = raw.decode("utf-8-sig")
        rows = list(csv.DictReader(text.splitlines()))
        parsed = [m for m in (_row_to_match(r) for r in rows) if m is not None]
        matches.extend(parsed)
        files.append(DatasetFile(path=str(p), checksum=checksum, rows=len(parsed)))
    matches.sort(key=lambda m: m.tourney_date)
    period = (matches[0].tourney_date, matches[-1].tourney_date) if matches else None
    return TennisDataset(tour=tour, matches=tuple(matches), files=tuple(files), period=period)
