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
from concurrent.futures import ThreadPoolExecutor

from ..protocol import RawBookmakerEvent
from .competition_mapping import resolve_competition


def all_events(connector, sport: str) -> Sequence[RawBookmakerEvent]:
    """DÉCOUVERTE : tous les événements scannés, aucune compétition écartée. La
    résolution/évaluation en aval isole les non-supportés (jamais de perte au scan)."""
    return connector.scan_catalog(sport)


#: Scans menés de front. Un scan est un appel réseau indépendant par sport ;
#: borné pour ne pas ouvrir sept connexions simultanées sur un bookmaker qui
#: n'a rien demandé.
_PARALLELISME_SCAN = 4


def multisport_events(connector, sports: Sequence[str]) -> Sequence[RawBookmakerEvent]:
    """DÉCOUVERTE MULTISPORT (§3) : agrège les événements de CHAQUE sport demandé.
    Chaque `RawBookmakerEvent` porte son propre `sport` -> dispatch en aval via
    `SPORT_MODULES` (aucun `if sport ==`). L'isolation par ÉVÉNEMENT reste garantie par
    `evaluate_live_batch` : un événement non résolu (identité/compétition) devient un
    résultat typé, jamais un arrêt du run ni une perte au scan.

    Les scans partent ensemble : sept appels réseau enchaînés coûtaient leur
    somme (~0,9 s) alors qu'ils ne dépendent pas les uns des autres. L'ordre de
    sortie reste celui des sports DEMANDÉS et non celui des réponses — deux runs
    identiques doivent produire le même catalogue, dans le même ordre.

    Une erreur reste propagée : un scan qui échoue est une panne de source, pas
    un sport vide, et la confondre avec l'absence d'événements ferait répondre
    « rien aujourd'hui » à une coupure réseau.
    """
    demandes = list(sports)
    if len(demandes) <= 1:
        return [e for sport in demandes for e in connector.scan_catalog(sport)]

    with ThreadPoolExecutor(max_workers=min(_PARALLELISME_SCAN, len(demandes))) as pool:
        par_sport = list(pool.map(connector.scan_catalog, demandes))
    return [event for lot in par_sport for event in lot]


def supported_events(connector, sport: str) -> Sequence[RawBookmakerEvent]:
    """Filtre ÉTROIT (compétitions RESOLVED uniquement). Propage toute erreur de scan.
    NB : écarte silencieusement les compétitions non mappées — préférer `all_events`
    pour la découverte multisport observable (le run n'est jamais réduit au silence)."""
    events = connector.scan_catalog(sport)
    return [e for e in events if resolve_competition(e.raw_tournament_id)[1] == "RESOLVED"]
