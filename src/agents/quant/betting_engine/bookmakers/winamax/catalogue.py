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
from dataclasses import dataclass, field

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


@dataclass(frozen=True)
class MultisportScan:
    """Ce que le scan a rapporté, sport par sport — succès ET pannes.

    `failures` est un statut TYPÉ par sport, pas un message perdu dans un log :
    c'est ce qui permet à l'aval de distinguer « ce sport n'a rien à proposer »
    de « ce sport n'a pas pu être interrogé », sans jamais les confondre.
    """

    events: tuple[RawBookmakerEvent, ...] = ()
    failures: dict[str, str] = field(default_factory=dict)   # sport -> "TypeErreur: message"
    scanned: tuple[str, ...] = ()                            # sports réellement rapportés
    #: L'exception ELLE-MÊME, par sport. `failures` porte un texte, bon pour la
    #: télémétrie et le rendu ; il ne suffit pas à un appelant strict, qui attrape
    #: un type précis (`ConnectionError` pour une coupure). Relever une exception
    #: de substitution lui ferait manquer sa propre panne.
    exceptions: dict[str, BaseException] = field(default_factory=dict, repr=False)

    @property
    def total_failure(self) -> bool:
        """Aucun sport n'a pu être interrogé — il n'y a pas de scan du tout."""
        return bool(self.failures) and not self.scanned


def _panne(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"


def multisport_scan(connector, sports: Sequence[str]) -> MultisportScan:
    """DÉCOUVERTE MULTISPORT (§3), avec ISOLATION PAR SPORT.

    Chaque `RawBookmakerEvent` porte son propre `sport` -> dispatch en aval via
    `SPORT_MODULES` (aucun `if sport ==`). L'isolation par ÉVÉNEMENT reste garantie par
    `evaluate_live_batch` : un événement non résolu (identité/compétition) devient un
    résultat typé, jamais un arrêt du run ni une perte au scan.

    Les scans partent ensemble : sept appels réseau enchaînés coûtaient leur
    somme (~0,9 s) alors qu'ils ne dépendent pas les uns des autres. L'ordre de
    sortie reste celui des sports DEMANDÉS et non celui des réponses — deux runs
    identiques doivent produire le même catalogue, dans le même ordre.

    UN ÉCHEC RESTE LOCAL AU SPORT QUI LE PROVOQUE. Une panne de source sur le
    tennis ne dit rien du football, et la propager coûtait le run entier : sept
    branches indépendantes s'arrêtaient pour une seule coupure. L'erreur n'est
    pour autant jamais avalée — elle devient un statut porté par le scan, et
    l'appelant qui ne le regarde pas ne peut pas conclure « rien aujourd'hui ».
    """
    demandes = list(sports)
    if not demandes:
        return MultisportScan()

    def _un_sport(sport: str):
        try:
            return sport, tuple(connector.scan_catalog(sport)), None
        except Exception as exc:   # noqa: BLE001 — la panne devient une donnée
            return sport, (), exc

    if len(demandes) == 1:
        resultats = [_un_sport(demandes[0])]
    else:
        with ThreadPoolExecutor(max_workers=min(_PARALLELISME_SCAN, len(demandes))) as pool:
            resultats = list(pool.map(_un_sport, demandes))

    events: list[RawBookmakerEvent] = []
    failures: dict[str, str] = {}
    exceptions: dict[str, BaseException] = {}
    scanned: list[str] = []
    for sport, lot, exc in resultats:
        if exc is not None:
            failures[sport] = _panne(exc)
            exceptions[sport] = exc
            continue
        scanned.append(sport)
        events.extend(lot)
    return MultisportScan(tuple(events), failures, tuple(scanned), exceptions)


def multisport_events(connector, sports: Sequence[str]) -> Sequence[RawBookmakerEvent]:
    """Variante STRICTE : rend les événements, propage la première panne.

    Conservée pour les appelants qui veulent tout ou rien — la collecte CLV, une
    capture, un banc de mesure. Le chemin produit, lui, passe par
    `multisport_scan` : là-bas, l'arrêt doit rester local à la branche qui le
    provoque.

    L'exception D'ORIGINE est relevée, jamais une de substitution : la collecte
    CLV attrape `ConnectionError` pour distinguer une coupure d'une panne de
    programme, et un `RuntimeError` enveloppant lui ferait manquer la sienne.
    """
    scan = multisport_scan(connector, sports)
    if scan.exceptions:
        raise next(iter(scan.exceptions.values()))
    return list(scan.events)


def supported_events(connector, sport: str) -> Sequence[RawBookmakerEvent]:
    """Filtre ÉTROIT (compétitions RESOLVED uniquement). Propage toute erreur de scan.
    NB : écarte silencieusement les compétitions non mappées — préférer `all_events`
    pour la découverte multisport observable (le run n'est jamais réduit au silence)."""
    events = connector.scan_catalog(sport)
    return [e for e in events if resolve_competition(e.raw_tournament_id)[1] == "RESOLVED"]
