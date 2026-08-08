"""Identité d'une rencontre, séparée de son horaire.

L'identité canonique d'AXON porte le coup d'envoi :
`event:tennis:tour:2026-08-08T18:30:00Z:player_a=…`. C'est commode — le temps
d'avance se reconstruit sans rien stocker — et c'était faux dès qu'un bookmaker
déplace un match.

MESURÉ SUR LE STORE RÉEL. Winamax republie sans cesse l'heure de départ en
tennis, où un match commence quand le précédent libère le court : une rencontre a
été annoncée sous DOUZE horaires différents, étalés sur 2 h 50. Chaque
republication créait une identité neuve, donc une rencontre neuve. 16 rencontres
tennis ont ainsi produit 43 identités fantômes — et une décision enregistrée sous
l'horaire de 18 h 00 ne pouvait plus jamais s'apparier avec sa clôture
enregistrée sous 18 h 50.

LA CLÉ RETENUE EST `source_event_id`, l'identifiant Winamax. Elle n'est pas
choisie par goût, elle est prouvée sur les 336 observations du store :

  - présente sur 336/336 ;
  - stable à travers les reports — 16 identifiants tennis portent plusieurs
    horaires, l'un d'eux en porte douze ;
  - jamais recyclée — AUCUN identifiant ne porte deux jeux de protagonistes ;
  - séparant les vrais matchs distincts — les 13 séries MLB (mêmes équipes deux
    soirs de suite) ont chacune leur identifiant, là où un rapprochement par
    participants les aurait fusionnées.

C'est ce dernier point qui interdit l'appariement par noms : deux rencontres
réellement distinctes ne doivent JAMAIS fusionner au prétexte que les
participants sont les mêmes.

DEUX CLÉS, ET C'EST VOULU. `OddsObservation.market_key` porte l'horaire et
répond à « ai-je déjà écrit cette observation ? » — le collecteur s'en sert pour
son idempotence, et il DOIT pouvoir capturer une nouvelle clôture après un
report. `stable_market_key` ignore l'horaire et répond à « ces deux observations
parlent-elles du même marché de la même rencontre ? ». Les confondre casserait
l'une des deux : une clé stable côté collecteur ferait passer la vraie clôture
d'après-report pour un doublon déjà connu.

Rien n'est migré ni réécrit : tout se reconstruit au-dessus du store append-only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

#: L'horodatage ISO à l'intérieur de l'identité d'événement. Extrait par MOTIF et
#: non par découpage sur « : » — l'identité vaut
#: `event:tennis:tour:2026-08-08T14:30:00Z:player_a=…`, et un `split(":")[3]`
#: rend « 2026-08-08T14 », soit une heure ronde plausible et fausse. L'erreur est
#: silencieuse : elle décale les temps d'avance de dizaines de minutes et
#: fabrique des clôtures « postérieures au coup d'envoi » qui n'existent pas.
_HORODATAGE = re.compile(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)")


def kickoff_de(event_id: str) -> datetime | None:
    """Coup d'envoi porté par une identité canonique, ou `None` si illisible."""
    trouve = _HORODATAGE.search(event_id or "")
    if trouve is None:
        return None
    return datetime.fromisoformat(trouve.group(1).replace("Z", "+00:00"))


def scheduled_kickoff_as_observed(observation) -> datetime | None:
    """Le coup d'envoi tel qu'il était ANNONCÉ au moment de cette observation.

    C'est la valeur point-in-time : elle vient de l'identité écrite dans le store
    à l'instant de la capture, et aucun report ultérieur ne la modifie.
    """
    return kickoff_de(observation.event_id)


def stable_event_id(observation) -> str:
    """Identité de rencontre insensible aux changements d'horaire.

    Repli sur l'identité canonique quand le bookmaker n'a pas fourni d'identifiant :
    sans preuve de stabilité, l'ancienne identité reste la moins mauvaise, et le
    comportement est alors strictement inchangé.
    """
    if not observation.source_event_id:
        return observation.event_id
    parties = (observation.event_id or "").split(":")
    sport = parties[1] if len(parties) > 1 else "?"
    competition = parties[2] if len(parties) > 2 else "?"
    # Le sport reste en 2e position : `clv-status` lit le sport sur cette identité.
    return f"event:{sport}:{competition}:{observation.bookmaker}#{observation.source_event_id}"


def stable_market_key(observation) -> tuple[str, str, str, str]:
    """« Même marché de la même rencontre », quel que soit l'horaire annoncé."""
    return (stable_event_id(observation), observation.market_type,
            observation.selection, observation.bookmaker)


@dataclass(frozen=True)
class HistoriqueHoraires:
    """Les coups d'envoi successivement annoncés pour chaque rencontre stable.

    Reconstruit à la lecture, jamais stocké : les anciennes valeurs restent
    exactement ce qu'elles étaient dans le store.

    L'ORDRE EST CELUI DE L'ANNONCE, PAS L'ORDRE CHRONOLOGIQUE DES HORAIRES. La
    distinction est invisible tant qu'un match n'est que repoussé — le dernier
    annoncé est alors aussi le plus tardif — et elle décide de tout dès qu'un
    match est AVANCÉ. Annoncé à 18 h 30 puis ramené à 18 h 00, sa meilleure
    approximation de départ réel est 18 h 00 ; prendre le maximum rendrait
    18 h 30, et une cote relevée à 18 h 13 passerait pour une clôture valable
    alors que le match avait déjà commencé.
    """

    #: identité stable -> couples (observed_at, kickoff annoncé), triés par annonce.
    _par_evenement: dict[str, tuple[tuple[datetime, datetime], ...]]

    def horaires(self, identite: str) -> tuple[datetime, ...]:
        """Horaires successivement annoncés, dans l'ordre d'ANNONCE, sans doublon."""
        vus: set[datetime] = set()
        sortie: list[datetime] = []
        for _, kickoff in self._par_evenement.get(identite, ()):
            if kickoff not in vus:
                vus.add(kickoff)
                sortie.append(kickoff)
        return tuple(sortie)

    def dernier(self, identite: str) -> datetime | None:
        """Le dernier coup d'envoi ANNONCÉ — meilleure approximation du départ réel."""
        annonces = self._par_evenement.get(identite, ())
        return annonces[-1][1] if annonces else None

    def replanifiee(self, identite: str) -> bool:
        return len(self.horaires(identite)) > 1


def historique_horaires(observations) -> HistoriqueHoraires:
    """Calendrier observé, reconstruit depuis les observations fournies.

    L'APPELANT choisit l'assiette, et ce choix compte : pour juger une clôture, il
    faut l'historique COMPLET de la rencontre. Ne fournir qu'un sous-ensemble déjà
    filtré ferait passer un horaire intermédiaire pour l'horaire final.
    """
    annonces: dict[str, list[tuple[datetime, datetime]]] = {}
    for observation in observations:
        kickoff = scheduled_kickoff_as_observed(observation)
        if kickoff is None:
            continue
        annonces.setdefault(stable_event_id(observation), []).append(
            (observation.observed_at, kickoff))
    # Tri sur (annonce, horaire) : le second terme ne départage que des annonces
    # simultanées, et garantit un résultat identique d'une exécution à l'autre.
    return HistoriqueHoraires({k: tuple(sorted(v)) for k, v in annonces.items()})
