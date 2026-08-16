"""Règlement des prédictions depuis les résultats réellement observés.

Source pour le tennis : le MÊME jeu de données qui entraîne le modèle. Aucun
provider nouveau, aucune clé supplémentaire — et surtout aucune divergence
possible entre ce sur quoi le modèle apprend et ce sur quoi il est jugé.

Discipline de ce moteur : jamais de valeur fabriquée. Une rencontre introuvable,
ambiguë, ou postérieure à la fin du jeu de données reste NON RÉGLÉE — avec la
raison. Deviner un résultat corromprait la seule mesure de justesse qu'on ait.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from enum import Enum

from .record import Issue, PredictionRecord

# Le jeu de données porte une DATE de tournoi, la prédiction un instant de coup
# d'envoi : fuseaux et conventions de tournoi peuvent décaler d'un jour.
TOLERANCE_JOURS = 2


class RaisonNonReglee(str, Enum):
    HORS_PERIMETRE = "HORS_PERIMETRE"          # sport non couvert par cette source
    PAS_ENCORE_JOUE = "PAS_ENCORE_JOUE"        # coup d'envoi postérieur aux données
    INTROUVABLE = "INTROUVABLE"                # aucune rencontre appariable
    AMBIGUE = "AMBIGUE"                        # plusieurs rencontres appariables
    SELECTION_INCONNUE = "SELECTION_INCONNUE"  # sélection non rattachable à un joueur


@dataclass(frozen=True)
class Reglement:
    reglees: tuple[PredictionRecord, ...]
    non_reglees: tuple[tuple[PredictionRecord, RaisonNonReglee], ...]

    @property
    def resume(self) -> dict:
        par_raison: dict[str, int] = defaultdict(int)
        for _, raison in self.non_reglees:
            par_raison[raison.value] += 1
        return {"reglees": len(self.reglees), "non_reglees": len(self.non_reglees),
                "par_raison": dict(par_raison)}


def _cle_paire(a: str, b: str) -> tuple[str, str]:
    """Paire non ordonnée : l'appariement ne doit pas dépendre de qui a gagné."""
    return (a, b) if a <= b else (b, a)


def index_resultats_tennis(tour: str) -> tuple[dict, date | None]:
    """(paire, date) -> nom du vainqueur, plus la dernière date couverte.

    La dernière date est rendue avec l'index : sans elle, une rencontre non encore
    disputée serait déclarée INTROUVABLE, ce qui la retirerait définitivement de
    la file d'attente au lieu de la laisser en attente.
    """
    from src.agents.quant.betting_engine.sports.tennis.tennis_data_loader import (
        load_tennis_data,
    )

    index: dict[tuple[tuple[str, str], date], list[str]] = defaultdict(list)
    derniere: date | None = None
    for m in load_tennis_data(tour).matches:
        index[(_cle_paire(m.p1_name, m.p2_name), m.tourney_date)].append(m.p1_name)
        derniere = m.tourney_date if derniere is None else max(derniere, m.tourney_date)
    return dict(index), derniere


def _noms_du_tour(tour: str) -> dict[str, str]:
    from src.agents.quant.betting_engine.sports.tennis.identity import tennis_players

    _entites, dataset_of = tennis_players(tour)
    return dict(dataset_of)


def regler_tennis(records, tour: str, *, now: datetime | None = None) -> Reglement:
    """Règle les prédictions tennis d'un circuit à partir du jeu de données.

    `records` : prédictions NON réglées. Les prédictions déjà réglées sont
    renvoyées inchangées en `non_reglees` — jamais re-réglées (append-only).
    """
    now = now or datetime.now(timezone.utc)
    index, derniere = index_resultats_tennis(tour)
    dataset_of = _noms_du_tour(tour)

    reglees: list[PredictionRecord] = []
    restantes: list[tuple[PredictionRecord, RaisonNonReglee]] = []

    for r in records:
        if r.est_reglee:
            continue
        noms = [dataset_of.get(pid) for pid in r.participant_ids]
        if len(noms) != 2 or any(n is None for n in noms):
            restantes.append((r, RaisonNonReglee.HORS_PERIMETRE))
            continue
        jour = r.scheduled_at.date()
        if derniere is not None and jour > derniere:
            restantes.append((r, RaisonNonReglee.PAS_ENCORE_JOUE))
            continue

        paire = _cle_paire(noms[0], noms[1])
        trouves = [v for delta in range(-TOLERANCE_JOURS, TOLERANCE_JOURS + 1)
                   for v in index.get((paire, jour + timedelta(days=delta)), [])]
        if not trouves:
            restantes.append((r, RaisonNonReglee.INTROUVABLE))
            continue
        if len(set(trouves)) > 1:
            # Deux rencontres de la même paire dans la fenêtre, vainqueurs
            # différents : deviner reviendrait à tirer à pile ou face.
            restantes.append((r, RaisonNonReglee.AMBIGUE))
            continue

        nom_selectionne = _nom_de_la_selection(r, noms)
        if nom_selectionne is None:
            restantes.append((r, RaisonNonReglee.SELECTION_INCONNUE))
            continue

        issue = Issue.GAGNEE if trouves[0] == nom_selectionne else Issue.PERDUE
        reglees.append(r.regler(issue, at=now, source=f"tennis-data:{tour}"))

    return Reglement(tuple(reglees), tuple(restantes))


def _nom_de_la_selection(r: PredictionRecord, noms: list[str]) -> str | None:
    """Nom du joueur porté par la sélection enregistrée.

    Les sélections sont des rôles neutres (`player_a`/`player_b`, cf. le modèle
    live tennis) alignés sur l'ordre de `participant_ids`. Toute autre forme est
    refusée plutôt qu'interprétée.
    """
    roles = {"player_a": 0, "player_b": 1, "slot_1": 0, "slot_2": 1}
    position = roles.get(r.selection)
    if position is not None:
        return noms[position]
    # Sélection déjà nommée : acceptée seulement si elle désigne un participant.
    return r.selection if r.selection in noms else None
