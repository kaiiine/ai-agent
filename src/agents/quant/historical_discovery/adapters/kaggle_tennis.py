"""Lecteur du dataset Kaggle `taylorbrownlow/atpwta-tennis-data` (CC BY-NC-SA 4.0).

LICENCE — VÉRIFIÉE, PAS SUPPOSÉE. `licenseName` rendu par l'API Kaggle vaut
`CC BY-NC-SA 4.0`, conforme à ce qui était annoncé. Mêmes trois obligations que
la base Sackmann dont ce jeu dérive : attribution, usage NON COMMERCIAL, et
partage à l'identique de toute base dérivée REDISTRIBUÉE.

CE QUE LE JEU CONTIENT VRAIMENT — mesuré, et différent de ce qu'on en lit :

    WTA   195 498 rencontres, 1949-2021, 13 249 joueuses
    ATP   177 938 rencontres, 1968-2021,  6 442 joueurs

Il n'y a NI qualification (un seul tour `Q4` sur 195 498), NI Challenger côté
ATP (niveaux A/G/M/D/F uniquement). Les affirmations d'un « archive ITF de
220 000 rencontres » ne concernent pas CE jeu : `C` et `CC` réunis n'en donnent
que 3 664. Son apport réel est ailleurs, et il est considérable pour le WTA :
tennis-data.co.uk ne remonte qu'à 2007, celui-ci à 1949.

L'IDENTIFIANT DE JOUEUR EST STABLE. `winner_id`/`loser_id` renvoient à
`KagglePlayers.csv`, qui porte aussi le GENRE. C'est ce qui permet d'interdire
structurellement une migration ATP↔WTA : deux personnes différentes peuvent
porter le même patronyme d'un circuit à l'autre, et seul un identifiant les
sépare à coup sûr.

La date reste celle du TOURNOI, comme chez Sackmann — d'où le même décalage
conservateur vers sa fin présumée.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from ..evidence import HistoricalMatchEvidence, utcnow
from .sackmann import DECALAGE_FIN_TOURNOI

SOURCE = "kaggle_atpwta"
LICENCE = "CC-BY-NC-SA-4.0"
DATASET = "taylorbrownlow/atpwta-tennis-data"
VERSION = "1"
DERNIERE_MAJ = "2021-03-08"
ATTRIBUTION = ("WTA/ATP Tennis Data, Taylor Brownlow (Kaggle, "
               "taylorbrownlow/atpwta-tennis-data, v1), CC BY-NC-SA 4.0 — "
               "dérivé des bases de Jeff Sackmann / Tennis Abstract")
PROVENANCE = f"https://www.kaggle.com/datasets/{DATASET}"

#: Regroupement des `tourney_level` en CATÉGORIES benchmarkables séparément.
#: Le détail brut reste dans `sport_specific["tourney_level"]` : regrouper sert
#: à décider, pas à effacer.
CATEGORIES: dict[str, str] = {
    # Circuit principal, tous systèmes de nommage confondus. `W` domine (110 597) :
    # c'est le niveau historique du tour féminin, PAS de l'ITF malgré la lettre.
    "W": "tour", "G": "tour", "P": "tour", "PM": "tour", "I": "tour",
    "T1": "tour", "T2": "tour", "T3": "tour", "T4": "tour", "T5": "tour",
    "F": "tour", "O": "tour",
    # Compétitions par ÉQUIPES : format et enjeu distincts du tableau individuel.
    "D": "equipes", "BR": "equipes",
    # ITF / satellites — le niveau le plus bas présent, et le plus rare ici.
    "C": "itf", "CC": "itf",
    # Exhibitions et juniors : jamais un résultat de circuit.
    "E": "exhibition", "J": "junior",
}


@dataclass(frozen=True)
class ParseResult:
    evidences: tuple[HistoricalMatchEvidence, ...]
    unparsed: tuple[str, ...]
    n_lignes: int
    genres_refuses: int = 0

    @property
    def resume(self) -> dict:
        return {"lignes": self.n_lignes, "rencontres": len(self.evidences),
                "non_analysees": len(self.unparsed),
                "genres_refuses": self.genres_refuses}


def lire_joueurs(texte: str) -> dict[str, dict]:
    """`player_id -> {nom, genre, pays}`. Le GENRE est la garde qui interdit une
    migration de circuit : sans lui, « Sanchez M. » du côté masculin et du côté
    féminin se confondraient sur le seul patronyme."""
    joueurs: dict[str, dict] = {}
    for r in csv.DictReader(io.StringIO(texte)):
        pid = (r.get("player_id") or "").strip()
        if not pid:
            continue
        prenom = (r.get("name_first") or "").strip()
        nom = (r.get("name_last") or "").strip()
        joueurs[pid] = {
            "nom": f"{prenom} {nom}".strip(),
            "genre": (r.get("gender") or "").strip().lower(),
            "pays": (r.get("country") or "").strip() or None}
    return joueurs


def _genre_attendu(tour: str) -> str:
    return "female" if tour.lower() == "wta" else "male"


def parser(texte: str, *, tour: str, competition_id: str, joueurs: dict,
           retrieved_at: datetime | None = None) -> ParseResult:
    """CSV Kaggle -> observations historiques, pour UN circuit.

    Une rencontre dont l'un des participants n'a pas le genre attendu est
    REFUSÉE, pas corrigée : c'est soit une erreur de la source, soit un
    rattachement que rien ne justifie, et les deux doivent se voir.
    """
    lu_a = retrieved_at or utcnow()
    attendu = _genre_attendu(tour)
    evidences: list[HistoricalMatchEvidence] = []
    unparsed: list[str] = []
    refuses = 0
    lignes = 0

    for r in csv.DictReader(io.StringIO(texte)):
        lignes += 1
        if (r.get("league") or "").strip().lower() != tour.lower():
            continue
        jour = (r.get("tourney_date") or "").strip()[:10]
        wid, lid = (r.get("winner_id") or "").strip(), (r.get("loser_id") or "").strip()
        gagnant = (r.get("winner_name") or "").strip()
        perdant = (r.get("loser_name") or "").strip()
        if not jour or not gagnant or not perdant:
            unparsed.append(str(r)[:140])
            continue
        try:
            debut = datetime.fromisoformat(jour).replace(tzinfo=timezone.utc)
        except ValueError:
            unparsed.append(str(r)[:140])
            continue

        genres = {(joueurs.get(p) or {}).get("genre") for p in (wid, lid) if p}
        if genres and genres != {attendu}:
            refuses += 1
            continue

        niveau = (r.get("tourney_level") or "").strip()
        evidences.append(HistoricalMatchEvidence(
            sport="tennis", source=SOURCE,
            source_event_id=f"{r.get('tourney_id','')}|{r.get('match_num','')}|{wid}|{lid}",
            competition=competition_id, season=jour[:4],
            participants=(gagnant, perdant),
            scheduled_at=debut + DECALAGE_FIN_TOURNOI,
            status="FINISHED", outcome="p1",
            score=(r.get("score") or "").strip() or None,
            provenance=PROVENANCE, license=LICENCE, retrieved_at=lu_a,
            timezone_verified=False,
            sport_specific={
                "tour": tour.lower(),
                "circuit": CATEGORIES.get(niveau, "inconnu"),
                "tourney_level": niveau or None,
                "tourney_id": (r.get("tourney_id") or "").strip() or None,
                "tourney_name": (r.get("tourney_name") or "").strip() or None,
                "surface": (r.get("surface") or "").strip() or None,
                "round": (r.get("round") or "").strip() or None,
                "best_of": (r.get("best_of") or "").strip() or None,
                "winner_id": wid or None, "loser_id": lid or None,
                "winner_rank": (r.get("winner_rank") or "").strip() or None,
                "loser_rank": (r.get("loser_rank") or "").strip() or None,
                "tourney_date": jour,
                "date_decalee_de_jours": DECALAGE_FIN_TOURNOI.days,
                "dataset": DATASET, "dataset_version": VERSION,
                "dataset_maj": DERNIERE_MAJ,
                "attribution": ATTRIBUTION}))

    return ParseResult(tuple(evidences), tuple(unparsed), lignes, refuses)
