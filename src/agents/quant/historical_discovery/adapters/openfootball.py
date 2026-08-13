"""Lecteur du format Football.TXT (openfootball, CC0-1.0).

Le format est lisible par un humain, ce qui le rend piégeux à analyser : la date
et l'heure se REPORTENT d'une ligne à l'autre, et une ligne de rencontre peut
n'être qu'un nom, un « v », un nom et un score. Un lecteur laxiste rattacherait
silencieusement des rencontres au mauvais jour.

D'où deux règles. Toute ligne non reconnue est COMPTÉE et RENDUE (`unparsed`),
jamais ignorée : un corpus amputé de moitié doit se voir dans le rapport, pas se
déduire d'un benchmark décevant. Et l'analyse échoue plutôt que de deviner quand
un contexte manque — une rencontre avant toute ligne de date n'a pas de date.

LE SCORE DES 90 MINUTES, PAS LE SCORE FINAL. `1-4 pen. 0-1 a.e.t. (0-1, 0-1)`
contient quatre scores. Un modèle 1X2 apprend l'issue du temps réglementaire ;
prendre les tirs au but ferait apprendre « victoire » là où le marché cotait un
nul. C'est exactement la divergence qui produisait les conflits entre
football-data.org et api-sports — ici elle est levée par lecture, pas par
arbitrage.

LE FUSEAU N'EST PAS SUPPOSÉ. Les heures sont locales à la compétition, jamais
UTC. Le fuseau est donc un paramètre OBLIGATOIRE, et `timezone_verified` reste
faux tant qu'un recoupement ne l'a pas établi (cf. `verifier_fuseau`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from ..evidence import HistoricalMatchEvidence, utcnow

SOURCE = "openfootball"
LICENCE = "CC0-1.0"
BASE_RAW = "https://raw.githubusercontent.com/openfootball"

_MOIS = {m: i + 1 for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
     "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])}

_RE_ROUND = re.compile(r"^\s*▪\s*(?P<round>.+?)\s*$")
_RE_DATE = re.compile(
    r"^\s{1,4}(?P<jour>Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+"
    r"(?P<mois>[A-Z][a-z]{2})\s+(?P<num>\d{1,2})(?:\s+(?P<annee>\d{4}))?\s*$")
_RE_MATCH = re.compile(
    r"^\s+(?:(?P<h>\d{1,2}):(?P<mn>\d{2})\s+)?(?P<reste>\S.*\sv\s.*)$")

#: Les quatre scores possibles d'une même rencontre, dans l'ordre où le format
#: les écrit : tirs au but, prolongation, temps réglementaire, mi-temps.
_RE_SCORE = re.compile(
    r"^(?:(?P<pen>\d+-\d+)\s+pen\.\s+)?"
    r"(?:(?P<aet>\d+-\d+)\s+a\.e\.t\.\s*)?"
    r"(?P<ft>\d+-\d+)?\s*"
    r"(?:\((?P<paren>[^)]*)\))?\s*$")

_RE_PAYS = re.compile(r"\s*\([A-Z]{3}\)\s*$")

#: Rencontres NON JOUÉES, marquées entre crochets par le format. Un `[awarded]`
#: porte pourtant un score (3-0 sur tapis vert) : l'ingérer apprendrait au modèle
#: une victoire que personne n'a construite sur le terrain. Elles sont donc
#: reconnues et écartées de l'apprentissage — pas ignorées, ce qui les ferait
#: passer pour une anomalie de format.
_MARQUEURS_NON_JOUE = {
    "[awarded]": "WALKOVER",
    "[cancelled]": "CANCELLED",
    "[canceled]": "CANCELLED",
    "[abandoned]": "CANCELLED",
    "[postponed]": "POSTPONED",
}


@dataclass(frozen=True)
class ParseResult:
    evidences: tuple[HistoricalMatchEvidence, ...]
    unparsed: tuple[str, ...]
    n_lignes: int
    titre: str = ""

    @property
    def resume(self) -> dict:
        return {"titre": self.titre, "lignes": self.n_lignes,
                "rencontres": len(self.evidences), "non_analysees": len(self.unparsed)}


def _paire(txt: str) -> tuple[int, int] | None:
    m = re.match(r"^(\d+)-(\d+)$", txt.strip())
    return (int(m.group(1)), int(m.group(2))) if m else None


def _score_reglementaire(brut: str) -> tuple[tuple[int, int] | None, str]:
    """`(score 90 min, trace brute)`. `None` si la rencontre n'a pas de score."""
    brut = brut.strip()
    if not brut:
        return None, ""
    m = _RE_SCORE.match(brut)
    if not m:
        return None, brut
    paren = [p for p in (m.group("paren") or "").split(",") if p.strip()]
    if m.group("aet"):
        # Prolongation jouée : le temps réglementaire est le PREMIER couple entre
        # parenthèses. Sans lui, la rencontre est inexploitable pour un 1X2 —
        # et on préfère la perdre que lui prêter l'issue de la prolongation.
        return (_paire(paren[0]) if paren else None), brut
    if m.group("ft"):
        return _paire(m.group("ft")), brut
    return None, brut


def _nom_propre(nom: str) -> str:
    """Retire le suffixe pays `(ESP)` des compétitions européennes.

    Le suffixe n'est pas du bruit — c'est un signal d'identité ancré au pays,
    conservé à part dans `sport_specific` parce qu'il sert au rapprochement
    inter-provider, où il vaut mieux qu'une ressemblance de nom.
    """
    return _RE_PAYS.sub("", nom).strip()


def _pays(nom: str) -> str | None:
    m = re.search(r"\(([A-Z]{3})\)\s*$", nom.strip())
    return m.group(1) if m else None


def parser(texte: str, *, competition_id: str, season: str, tz: str,
           provenance: str, retrieved_at: datetime | None = None) -> ParseResult:
    """Analyse un fichier Football.TXT en observations historiques.

    `tz` est obligatoire : une heure locale interprétée comme UTC décalerait
    toutes les rencontres d'une à deux heures, ce qui suffit à faire basculer une
    rencontre de l'autre côté d'un `cutoff` point-in-time.
    """
    zone = ZoneInfo(tz)
    lu_a = retrieved_at or utcnow()
    evidences: list[HistoricalMatchEvidence] = []
    unparsed: list[str] = []
    titre = ""
    jour_courant: datetime | None = None
    annee_courante: int | None = None
    heure_courante: time | None = None
    round_courant = ""
    lignes = texte.splitlines()

    for ligne in lignes:
        if not ligne.strip():
            continue
        if ligne.startswith("="):
            titre = ligne.lstrip("= ").strip()
            continue
        if ligne.lstrip().startswith("#"):
            continue

        m = _RE_ROUND.match(ligne)
        if m:
            round_courant = m.group("round")
            continue

        m = _RE_DATE.match(ligne)
        if m:
            if m.group("annee"):
                annee_courante = int(m.group("annee"))
            if annee_courante is None:
                unparsed.append(ligne)
                continue
            jour_courant = datetime(annee_courante, _MOIS[m.group("mois")],
                                    int(m.group("num")))
            heure_courante = None      # une nouvelle journée ne garde pas l'heure
            continue

        m = _RE_MATCH.match(ligne)
        if not m:
            unparsed.append(ligne)
            continue
        if jour_courant is None:
            # Une rencontre sans jour connu : refusée, jamais rattachée au hasard.
            unparsed.append(ligne)
            continue

        if m.group("h"):
            heure_courante = time(int(m.group("h")), int(m.group("mn")))

        #: Une rencontre NON JOUÉE n'a pas d'heure de coup d'envoi, et le format
        #: n'en écrit pas. Reconnaître le marqueur AVANT d'exiger une heure : dans
        #: l'ordre inverse, un forfait passait pour une ligne mal formée.
        marqueur = next((v for k, v in _MARQUEURS_NON_JOUE.items()
                         if k in ligne.lower()), None)
        if heure_courante is None and marqueur is None:
            unparsed.append(ligne)
            continue

        parties = re.split(r"\s+v\s+", m.group("reste"), maxsplit=1)
        if len(parties) != 2:
            unparsed.append(ligne)
            continue
        domicile = parties[0].strip()
        reste = parties[1]

        # Le score est séparé du nom par DEUX espaces au moins ; c'est la seule
        # frontière que le format garantit.
        coupe = re.split(r"\s{2,}", reste.strip(), maxsplit=1)
        exterieur = coupe[0].strip()
        score_brut = coupe[1].strip() if len(coupe) > 1 else ""

        statut_force = marqueur
        if marqueur is not None:
            for cle in _MARQUEURS_NON_JOUE:
                score_brut = re.sub(re.escape(cle), "", score_brut,
                                    flags=re.IGNORECASE).strip()
        score, trace = _score_reglementaire(score_brut)

        quand = datetime.combine(jour_courant.date(),
                                 heure_courante or time(0, 0), tzinfo=zone)
        pays = (_pays(domicile), _pays(exterieur))
        dom, ext = _nom_propre(domicile), _nom_propre(exterieur)

        if statut_force is not None:
            # Rencontre non jouée : le score éventuel est administratif, jamais
            # une issue apprenable. On le garde en trace, sans `outcome`.
            statut, issue = statut_force, None
        elif score is None:
            if score_brut:
                # Score présent mais illisible : c'est une anomalie de format, pas
                # une rencontre à venir. On la signale au lieu de l'inventer.
                unparsed.append(ligne)
                continue
            statut, issue = "SCHEDULED", None
        else:
            statut = "FINISHED"
            issue = ("home" if score[0] > score[1]
                     else "away" if score[1] > score[0] else "draw")

        evidences.append(HistoricalMatchEvidence(
            sport="football", source=SOURCE,
            source_event_id=f"{competition_id}|{season}|{quand.date()}|{dom}|{ext}",
            competition=competition_id, season=season,
            participants=(dom, ext), scheduled_at=quand, status=statut,
            outcome=issue, score=trace or None,
            provenance=provenance, license=LICENCE, retrieved_at=lu_a,
            timezone_verified=False,
            sport_specific={"round": round_courant,
                            "goals_home": score[0] if score else None,
                            "goals_away": score[1] if score else None,
                            "country_home": pays[0], "country_away": pays[1],
                            "declared_timezone": tz}))

    return ParseResult(tuple(evidences), tuple(unparsed), len(lignes), titre)


# ── Vérification du fuseau, par recoupement ─────────────────────────────────

@dataclass(frozen=True)
class VerificationFuseau:
    """Le fuseau déclaré résiste-t-il à une source horodatée en UTC ?"""

    apparies: int
    concordants: int
    ecart_max_minutes: int
    verdict: str            # VERIFIED | INCONSISTENT | INSUFFICIENT_OVERLAP

    @property
    def est_verifie(self) -> bool:
        return self.verdict == "VERIFIED"


def verifier_fuseau(evidences, references, *, tolerance_minutes: int = 15,
                    minimum: int = 20) -> VerificationFuseau:
    """Recoupe des observations openfootball avec des rencontres horodatées UTC.

    `references` : itérable de `(date_utc, nom_domicile_libre, nom_exterieur_libre)`.
    L'appariement se fait sur le JOUR et l'ordre des participants uniquement — pas
    sur les noms, qui diffèrent d'une source à l'autre — puis on compare les heures.
    Un fuseau juste donne un écart nul sur presque tout ; un fuseau faux donne un
    décalage CONSTANT, ce qui se voit immédiatement.
    """
    par_jour: dict = {}
    for quand, _dom, _ext in references:
        par_jour.setdefault(quand.date(), []).append(quand)

    apparies = concordants = 0
    ecart_max = 0
    for e in evidences:
        utc = e.scheduled_at.astimezone(ZoneInfo("UTC"))
        candidats = par_jour.get(utc.date(), [])
        if not candidats:
            continue
        apparies += 1
        ecart = min(abs((utc - c).total_seconds()) for c in candidats) / 60
        ecart_max = max(ecart_max, int(ecart))
        if ecart <= tolerance_minutes:
            concordants += 1

    if apparies < minimum:
        return VerificationFuseau(apparies, concordants, ecart_max,
                                  "INSUFFICIENT_OVERLAP")
    # Exiger la quasi-totalité : quelques rencontres décalées sont des reports,
    # mais un fuseau faux décale TOUT.
    verdict = "VERIFIED" if concordants >= apparies * 0.9 else "INCONSISTENT"
    return VerificationFuseau(apparies, concordants, ecart_max, verdict)


def url_saison(depot: str, saison: str, fichier: str) -> str:
    return f"{BASE_RAW}/{depot}/master/{saison}/{fichier}"
