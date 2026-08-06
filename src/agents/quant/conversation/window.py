"""Fenêtre temporelle stricte, résolue en ABSOLU et timezone-aware (§9, §10).

Une expression comme « demain matin » n'est pas une donnée : c'est une fonction
de l'instant courant et d'un fuseau. Tant qu'elle reste du texte, elle est
réinterprétée à chaque tour, et un match d'après-demain finit par être présenté
comme « demain ». On la résout donc UNE fois, en `datetime` aware, et c'est la
paire d'instants qui voyage — jamais la phrase.

Le fuseau produit est `Europe/Paris` : le catalogue Winamax est français, la
bankroll est en euros, et l'utilisateur lit ses horaires en heure locale. UTC
reste la représentation interne de comparaison (les `start_time` du connecteur
sont aware), mais aucun affichage n'est fait en UTC seul.

Convention de fin : `end` est INCLUSIF à la microseconde près
(23:59:59.999999), et non minuit du jour suivant — pour qu'« aujourd'hui » ne
capture jamais un match du lendemain à 00:00.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

PARIS = ZoneInfo("Europe/Paris")

# Bornes de journée locales. « matin » s'arrête à midi, « soir » commence à 18 h :
# ces deux valeurs sont un choix produit, elles sont donc nommées et testées, pas
# dispersées dans le code.
MORNING_END = time(12, 0)
EVENING_START = time(18, 0)
_DAY_END = time(23, 59, 59, 999999)


@dataclass(frozen=True)
class TimeWindow:
    """Fenêtre absolue. `start`/`end` sont aware ; `label` documente l'origine."""

    start: datetime
    end: datetime
    label: str

    def __post_init__(self) -> None:
        if self.start.tzinfo is None or self.end.tzinfo is None:
            raise ValueError("TimeWindow exige des instants timezone-aware")
        if self.end < self.start:
            raise ValueError(f"fenêtre inversée : {self.start} > {self.end}")

    @property
    def is_empty(self) -> bool:
        """« ce matin » demandé à 15 h : la fenêtre est derrière nous. Elle reste
        vide et le dit, plutôt que d'être élargie en silence jusqu'à ce qu'elle
        contienne quelque chose à montrer."""
        return self.end == self.start

    def contains(self, moment: datetime | None) -> bool:
        """Un `start_time` absent n'est JAMAIS supposé dans la fenêtre : sans
        horaire, rien ne permet d'affirmer que le match est encore à venir."""
        if moment is None or self.is_empty:
            return False
        if moment.tzinfo is None:
            raise ValueError("start_time naïf : la comparaison serait ambiguë")
        return self.start <= moment <= self.end

    def describe(self) -> str:
        return (f"{_fr(self.start)} → {_fr(self.end)} (Europe/Paris)")


def to_paris(moment: datetime) -> datetime:
    """Conversion vers l'heure locale. Refuse un instant naïf : convertir un
    naïf revient à inventer un fuseau, et l'erreur ne se voit qu'en été."""
    if moment.tzinfo is None:
        raise ValueError("instant naïf : aucun fuseau à convertir")
    return moment.astimezone(PARIS)


_MOIS = ("janvier", "février", "mars", "avril", "mai", "juin", "juillet",
         "août", "septembre", "octobre", "novembre", "décembre")


def _fr(moment: datetime) -> str:
    """Rendu lisible en heure locale — l'unique format d'horaire du produit."""
    local = to_paris(moment)
    return f"{local.day} {_MOIS[local.month - 1]} {local.year}, {local:%H:%M}"


def render_kickoff(moment: datetime) -> str:
    """Horaire d'un match tel qu'affiché : local explicite, UTC en secondaire.

    Le décalage change deux fois par an ; afficher « 19:10 » sans fuseau produit
    une erreur d'une heure invisible pendant six mois."""
    return f"{_fr(moment)} (UTC {moment.astimezone(ZoneInfo('UTC')):%H:%M})"


# ── Résolution des expressions ────────────────────────────────────────────────
def _start_of(day: date) -> datetime:
    return datetime.combine(day, time(0, 0), tzinfo=PARIS)


def _end_of(day: date) -> datetime:
    return datetime.combine(day, _DAY_END, tzinfo=PARIS)


def _at(day: date, moment: time) -> datetime:
    return datetime.combine(day, moment, tzinfo=PARIS)


def _normalise(text: str) -> str:
    """Sans accents, minuscules — « aujourd'hui » s'écrit de trop de façons."""
    sans_accent = "".join(
        c for c in unicodedata.normalize("NFD", text.lower())
        if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", sans_accent)


# Chaque motif rend une fenêtre (start, end) à partir du jour local courant.
# L'ordre compte : « demain matin » doit être testé avant « demain ».
_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\bdemain matin\b", "demain_matin"),
    (r"\bdemain soir\b", "demain_soir"),
    (r"\bdemain\b", "demain"),
    (r"\bce soir\b|\bcesoir\b", "ce_soir"),
    (r"\bce matin\b", "ce_matin"),
    (r"\baujourd hui\b|\baujourdhui\b", "aujourdhui"),
    (r"\bmaintenant\b|\btout de suite\b|\bla tout de suite\b", "maintenant"),
)


def _span(key: str, now: datetime) -> tuple[datetime, datetime]:
    today = now.date()
    tomorrow = today + timedelta(days=1)
    spans = {
        "aujourdhui": (now, _end_of(today)),
        "ce_matin": (now, _at(today, MORNING_END)),
        "ce_soir": (max(now, _at(today, EVENING_START)), _end_of(today)),
        "maintenant": (now, _end_of(tomorrow)),
        "demain": (_start_of(tomorrow), _end_of(tomorrow)),
        "demain_matin": (_start_of(tomorrow), _at(tomorrow, MORNING_END)),
        "demain_soir": (_at(tomorrow, EVENING_START), _end_of(tomorrow)),
    }
    return spans[key]


def resolve_window(text: str, now: datetime) -> TimeWindow:
    """Résout les expressions temporelles d'une demande en fenêtre ABSOLUE.

    Défaut produit — aucune expression reconnue : de maintenant à la fin du jour
    civil SUIVANT. C'est ce que « des paris maintenant » veut dire pour un
    utilisateur : le pari se place aujourd'hui ou demain, pas dans trois
    semaines.

    Plusieurs expressions -> enveloppe (min des débuts, max des fins). C'est la
    seule lecture qui satisfait « aujourd'hui ou demain matin » : de maintenant à
    demain 12:00. Une intersection rendrait la fenêtre vide, et prendre la
    dernière expression citée ignorerait la première.
    """
    if now.tzinfo is None:
        raise ValueError("resolve_window exige un instant courant timezone-aware")
    now = to_paris(now)

    # Les motifs sont CONSOMMÉS dans l'ordre : « demain matin » retire « demain »
    # du texte restant. Sans cela les deux se déclenchent, et l'enveloppe des
    # deux rend la journée entière — « demain matin » cesse de vouloir dire matin.
    restant = _normalise(text or "")
    trouves: list[str] = []
    for motif, key in _PATTERNS:
        nouveau, remplaces = re.subn(motif, " ", restant)
        if remplaces:
            trouves.append(key)
            restant = nouveau

    if not trouves:
        start, end = _span("maintenant", now)
        return TimeWindow(start, end, "defaut:maintenant_a_fin_de_demain")

    spans = [_span(key, now) for key in trouves]
    start = min(s for s, _ in spans)
    end = max(e for _, e in spans)
    return TimeWindow(start, max(end, start), "+".join(trouves))
