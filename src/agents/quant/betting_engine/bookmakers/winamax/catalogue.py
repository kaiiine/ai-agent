"""Service catalogue Winamax : scan complet (découverte) vs filtre supporté.

DÉCOUVERTE (`all_events`) : TOUS les événements 2-compétiteurs réellement exposés,
toutes compétitions confondues — jamais de perte silencieuse. Une compétition sans
modèle/données n'est PAS écartée au scan ; elle sera isolée à l'évaluation
(statut typé), ce qui rend la couverture observable et n'arrête jamais le run.

FILTRE ÉTROIT (`supported_events`) : ne garde que les compétitions dont le tournoi
Winamax résout vers une compétition canonique VÉRIFIÉE (RESOLVED). Conservé pour un
appelant qui veut délibérément se restreindre ; le chemin produit préfère
`all_events` + isolation (couverture réelle multisport/multi-compétition).
"""

from __future__ import annotations

from collections.abc import Sequence

from ..protocol import RawBookmakerEvent
from .competition_mapping import resolve_competition


def all_events(connector, sport: str = "football") -> Sequence[RawBookmakerEvent]:
    """DÉCOUVERTE : tous les événements scannés, aucune compétition écartée. La
    résolution/évaluation en aval isole les non-supportés (jamais de perte au scan)."""
    return connector.scan_catalog(sport)


def supported_events(connector, sport: str = "football") -> Sequence[RawBookmakerEvent]:
    """Filtre ÉTROIT (compétitions RESOLVED uniquement). Propage toute erreur de scan.
    NB : écarte silencieusement les compétitions non mappées — préférer `all_events`
    pour la découverte multisport observable (le run n'est jamais réduit au silence)."""
    events = connector.scan_catalog(sport)
    return [e for e in events if resolve_competition(e.raw_tournament_id)[1] == "RESOLVED"]
