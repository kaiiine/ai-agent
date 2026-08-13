"""Lecteur du jeu de données nflverse (`games.csv`, CC-BY-4.0).

Deuxième adapter, écrit APRÈS openfootball pour vérifier que le noyau
`HistoricalMatchEvidence` tient sur un autre sport et un autre format. Il ne
partage aucune ligne de code avec lui — c'est voulu : le noyau commun est le
CONTRAT, pas l'implémentation. Un adapter qui hériterait de l'autre finirait par
plier le baseball dans la sémantique du football.

CE QUI DIFFÈRE DU FOOTBALL, ET QUI COMPTE. Il n'y a pas de nul en NFL depuis
1974 — sauf qu'il y en a, rarement, quand la prolongation ne départage pas. Les
écraser en victoire domicile fausserait une issue réelle ; les ignorer ferait
disparaître des rencontres. Elles sortent donc en `draw`, comme au football, et
c'est au modèle de décider s'il sait les traiter.

LA PROLONGATION FAIT PARTIE DU RÉSULTAT ICI. Contraire au 1X2 football, où le
marché se règle à 90 minutes : un *moneyline* NFL se règle sur le score final,
prolongation comprise. Le champ `overtime` est conservé pour que ce choix reste
visible plutôt qu'implicite.

LES IDENTIFIANTS SONT DES ABRÉVIATIONS (`KC`, `SF`) — jamais des noms. Elles ne
se rapprochent d'aucun autre référentiel par ressemblance : le rapprochement
passe par `identity_bridge`, qui ne lit pas les libellés.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import datetime, time
from zoneinfo import ZoneInfo

from ..evidence import HistoricalMatchEvidence, utcnow

SOURCE = "nflverse"
LICENCE = "CC-BY-4.0"
ATTRIBUTION = "nflverse (https://github.com/nflverse/nflverse-data), CC-BY-4.0"
URL_GAMES = "https://github.com/nflverse/nflverse-data/releases/download/schedules/games.csv"

#: Les horaires NFL sont publiés en heure de l'Est. Déclaré, jamais supposé :
#: `verifier_fuseau` doit le confirmer avant tout ancrage temporel.
TZ_DEFAUT = "America/New_York"

_TYPES_SAISON = {"REG": "regular", "POST": "postseason", "WC": "postseason",
                 "DIV": "postseason", "CON": "postseason", "SB": "postseason"}


@dataclass(frozen=True)
class ParseResult:
    evidences: tuple[HistoricalMatchEvidence, ...]
    unparsed: tuple[str, ...]
    n_lignes: int

    @property
    def resume(self) -> dict:
        return {"lignes": self.n_lignes, "rencontres": len(self.evidences),
                "non_analysees": len(self.unparsed)}


def _entier(v):
    v = (v or "").strip()
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def parser(texte: str, *, competition_id: str, tz: str = TZ_DEFAUT,
           provenance: str = URL_GAMES, retrieved_at: datetime | None = None,
           saisons=None) -> ParseResult:
    """`games.csv` -> observations historiques.

    `saisons` restreint la lecture (itérable de chaînes). Sans filtre, les 28
    saisons entrent : c'est utile pour un backfill profond, coûteux pour un test.
    """
    zone = ZoneInfo(tz)
    lu_a = retrieved_at or utcnow()
    voulues = {str(s) for s in saisons} if saisons else None
    evidences: list[HistoricalMatchEvidence] = []
    unparsed: list[str] = []
    lignes = list(csv.DictReader(io.StringIO(texte)))

    for r in lignes:
        saison = (r.get("season") or "").strip()
        if voulues is not None and saison not in voulues:
            continue
        dom, ext = (r.get("home_team") or "").strip(), (r.get("away_team") or "").strip()
        jour = (r.get("gameday") or "").strip()
        if not dom or not ext or not jour:
            unparsed.append(str(r)[:160])
            continue
        try:
            j = datetime.strptime(jour, "%Y-%m-%d").date()
        except ValueError:
            unparsed.append(str(r)[:160])
            continue

        heure = (r.get("gametime") or "").strip()
        try:
            hh, mm = heure.split(":")[:2]
            h = time(int(hh), int(mm))
        except (ValueError, IndexError):
            # Horaire absent (rencontres anciennes) : la date seule reste
            # exploitable pour un historique, mais pas pour un ancrage à la
            # minute. On le marque au lieu de fabriquer « 00:00 » sans le dire.
            h = None
        quand = datetime.combine(j, h or time(0, 0), tzinfo=zone)

        sd, se = _entier(r.get("home_score")), _entier(r.get("away_score"))
        if sd is None or se is None:
            statut, issue, score = "SCHEDULED", None, None
        else:
            statut = "FINISHED"
            issue = "home" if sd > se else "away" if se > sd else "draw"
            score = f"{sd}-{se}"

        evidences.append(HistoricalMatchEvidence(
            sport="american_football", source=SOURCE,
            source_event_id=(r.get("game_id") or f"{saison}|{jour}|{dom}|{ext}").strip(),
            competition=competition_id, season=saison,
            participants=(dom, ext), scheduled_at=quand, status=statut,
            outcome=issue, score=score,
            provenance=provenance, license=LICENCE, retrieved_at=lu_a,
            timezone_verified=False,
            sport_specific={
                "week": _entier(r.get("week")),
                "game_type": _TYPES_SAISON.get((r.get("game_type") or "").strip(), "autre"),
                "overtime": (r.get("overtime") or "").strip() in ("1", "TRUE", "True"),
                "home_score": sd, "away_score": se,
                "heure_publiee": bool(h),
                "declared_timezone": tz}))

    return ParseResult(tuple(evidences), tuple(unparsed), len(lignes))
