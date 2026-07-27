"""Service catalogue Winamax : scan + filtre vers les compétitions supportées.

Le filtrage FL1/PL vit ICI (pas dans le CLI) et s'appuie sur le champ STRUCTURÉ
`raw_tournament_id` + la table vérifiée `WinamaxCompetitionMapping` — jamais sur
une inspection artisanale du payload. Un événement est retenu si son tournoi
Winamax résout vers une compétition canonique VÉRIFIÉE (RESOLVED).
"""

from __future__ import annotations

from collections.abc import Sequence

from ..protocol import RawBookmakerEvent
from .competition_mapping import resolve_competition


def supported_events(connector, sport: str = "football") -> Sequence[RawBookmakerEvent]:
    """Scanne le catalogue et ne garde que les événements des compétitions
    supportées (résolution vérifiée). Propage toute erreur de scan (réseau /
    structure) — la gestion du code de sortie est au CLI."""
    events = connector.scan_catalog(sport)
    return [e for e in events if resolve_competition(e.raw_tournament_id)[1] == "RESOLVED"]
