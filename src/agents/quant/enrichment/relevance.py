"""Ce fait parle-t-il de CETTE rencontre ?

Le filtre d'extraction ne retenait qu'une condition : la phrase nomme un
participant. C'est nécessaire et très insuffisant. « Borges in run to Phoenix
Challenger last week » est une phrase vraie, officielle, sur le bon joueur — et
sans le moindre rapport avec son match de demain. Affichée sous « contexte
vérifié », elle emprunte l'autorité de sa source pour un contenu qui n'éclaire
rien, et pousse à croire qu'on en sait plus qu'on n'en sait.

Le problème est plus difficile qu'il n'y paraît, et il faut être honnête sur ce
qui est décidable. Une page web ne dit presque jamais explicitement « ceci
concerne le match du 8 août ». On dispose de trois signaux, et d'aucun oracle :

- **le sujet** : le fait nomme-t-il un participant de la rencontre ?
- **le temps** : quand le fait a-t-il été établi, par rapport au coup d'envoi ?
- **la nature du fait** : certaines catégories vieillissent en heures, d'autres
  sont des états qui durent.

C'est ce dernier point qui rend la règle défendable plutôt qu'arbitraire. Une
composition d'équipe annoncée il y a trois jours ne dit rien du match de ce soir ;
un classement ATP publié lundi vaut encore jeudi ; une surface de court ne change
pas. La durée de validité n'est donc pas un réglage global mais une propriété du
TYPE de fait — et elle se justifie fait par fait, ce qu'un seuil unique ne
permettrait jamais.

Ce module ne modifie AUCUN calcul : ni probabilité, ni EV, ni classement, ni
mise. Il décide seulement ce qui s'affiche. Un fait écarté l'est comme
`NOT_EVENT_RELEVANT` et porte sa raison — il n'a pas été jugé faux, il a été jugé
hors sujet, et confondre les deux rendrait le filtre inaudible.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Sequence

#: Verdicts. `RELEVANT` est le seul qui s'affiche à l'utilisateur.
RELEVANT = "RELEVANT"
NOT_EVENT_RELEVANT = "NOT_EVENT_RELEVANT"

#: Durée de validité par TYPE de fait, comptée AVANT le coup d'envoi.
#:
#: Ces durées ne sont pas des seuils statistiques : ce sont des propriétés du
#: monde, et chacune se défend séparément.
#:
#: - une composition ou un rapport de blessure décrit un état du jour même : la
#:   veille, il a déjà pu changer ;
#: - un forfait, une suspension ou un report sont des DÉCISIONS qui restent
#:   vraies jusqu'à annulation — leur fenêtre est large ;
#: - un classement officiel est hebdomadaire au tennis ;
#: - une surface, un lieu ou un tableau appartiennent au tournoi et ne bougent
#:   pas pendant sa durée.
#:
#: Un type absent de cette table est traité comme non datable, donc écarté :
#: mieux vaut ne rien montrer que montrer sans savoir dater.
VALIDITE: dict[str, timedelta] = {
    "LINEUP": timedelta(hours=12),
    "REST_STATUS": timedelta(hours=24),
    "INJURY": timedelta(days=3),
    "WEATHER": timedelta(hours=24),
    "WITHDRAWAL": timedelta(days=7),
    "SUSPENSION": timedelta(days=14),
    "POSTPONEMENT": timedelta(days=14),
    "SCHEDULE_CHANGE": timedelta(days=7),
    "VENUE_CHANGE": timedelta(days=14),
    "OFFICIAL_RANKING": timedelta(days=7),
    "DRAW": timedelta(days=14),
    "SURFACE": timedelta(days=30),
    "H2H": timedelta(days=365),          # un historique n'expire pas
}

#: Marqueurs d'un fait explicitement PASSÉ. Une phrase au passé qui raconte une
#: autre semaine est le cas exact que ce module existe pour écarter, et aucune
#: date ne la trahit — seule sa formulation le fait.
_PASSE = re.compile(
    r"(?i)\b("
    r"last (?:week|month|year|season|time)|previous (?:week|round|season)"
    r"|in \d{4}\b|back in \d{4}"
    r"|la semaine (?:dernière|passée)|le mois dernier|l'an dernier|en \d{4}\b"
    r"|défendait|avait remporté|s'était"
    r")\b")

#: Ce que chaque TYPE de fait doit AFFIRMER pour mériter d'être montré.
#:
#: Ce filtre est positif, et c'est délibéré. Énumérer ce qu'il faut rejeter est
#: sans fin : après « last week » viennent les citations de conférence de presse,
#: les palmarès, les notes de match d'un autre tournoi, les statistiques
#: historiques. Chaque ajout corrige un symptôme et en laisse dix.
#:
#: Énumérer ce qu'il faut AFFIRMER est au contraire borné et défendable. Un fait
#: de type INJURY n'a d'intérêt que s'il dit quelque chose de la DISPONIBILITÉ
#: d'un joueur ; un OFFICIAL_RANKING que s'il énonce un classement. Une phrase
#: qui ne fait pas l'affirmation promise par son type ne dit rien d'utile, quelle
#: que soit sa source — et la charge de la preuve appartient à ce qu'on affiche
#: sous « contexte vérifié ».
_AFFIRMATIONS: dict[str, "re.Pattern"] = {
    "INJURY": re.compile(
        r"(?i)\b(injur\w+|blessur\w+|blessé\w*|doubtful|questionable|fitness "
        r"(?:test|concern)|out (?:for|of)|sidelined|forfait|indisponible|"
        r"withdrew|withdrawn|withdraws|retired|walkover)\b"),
    "WITHDRAWAL": re.compile(
        r"(?i)\b(withdrew|withdrawn|withdraws|withdrawal|retired|retires|"
        r"walkover|pulled out|forfait|déclare forfait|abandon\w*)\b"),
    "SUSPENSION": re.compile(
        r"(?i)\b(suspend\w+|ban(?:ned|s)?|ineligible|suspension)\b"),
    "LINEUP": re.compile(
        r"(?i)\b(line ?-?up|starting|starters?|will start|expected to start|"
        r"named in|squad|composition|titulaire\w*|absent\w*)\b"),
    "REST_STATUS": re.compile(
        r"(?i)\b(rest(?:ed|ing)?|load management|back-to-back|days? off|"
        r"repos|rotation)\b"),
    "WEATHER": re.compile(
        r"(?i)\b(rain|wind|temperature|forecast|storm|snow|humid\w*|"
        r"pluie|vent|météo|orage)\b"),
    "OFFICIAL_RANKING": re.compile(
        r"(?i)\b(rank(?:ed|ing)?|seed(?:ed)?|no\.\s*\d+|world number|"
        r"classement|tête de série)\b"),
    "SURFACE": re.compile(
        r"(?i)\b(hard ?court|clay|grass|indoor|outdoor|surface|"
        r"terre battue|gazon|dur)\b"),
    "DRAW": re.compile(
        r"(?i)\b(draw|bracket|order of play|seeds?|tableau|programme)\b"),
    "POSTPONEMENT": re.compile(
        r"(?i)\b(postpon\w+|delayed|rescheduled|reporté\w*|décalé\w*)\b"),
    "SCHEDULE_CHANGE": re.compile(
        r"(?i)\b(reschedul\w+|new (?:date|time)|moved to|horaire|décalé\w*)\b"),
    "VENUE_CHANGE": re.compile(
        r"(?i)\b(venue|relocat\w+|moved to|stadium change|lieu)\b"),
    "H2H": re.compile(r"(?i)\b(head[- ]to[- ]head|h2h|face[- ]à[- ]face)\b"),
}

#: NARRATION DE RÉSULTAT. Distinct du marqueur temporel, et plus puissant : un
#: résultat porte sur un match DÉJÀ JOUÉ, par définition. « Borges reached the
#: final of the Phoenix Challenger » ne contient aucun marqueur de date et ne dit
#: pourtant rien du match de demain.
#:
#: Ce signal est volontairement séparé : il ne dépend d'aucune connaissance du
#: calendrier, seulement de la grammaire de la phrase.
_RESULTAT = re.compile(
    r"(?i)\b("
    r"reached|advanced to|beat|beaten|defeated|won (?:the|his|her|against)"
    r"|lost (?:to|against)|eliminated|knocked out|upset"
    r"|a battu|a remporté|s'est imposé|a perdu|éliminé"
    r")\b")

#: Un fait qui nomme un AUTRE tournoi que celui de la rencontre est suspect : il
#: parle probablement d'une autre semaine. On ne peut pas énumérer les tournois
#: du monde, mais on peut repérer qu'un nom de compétition apparaît et qu'il ne
#: correspond pas — via les mots significatifs de la compétition courante.
_MOTS_VIDES = frozenset({
    "the", "de", "du", "des", "la", "le", "les", "open", "cup", "tour", "atp",
    "wta", "masters", "championship", "championships", "trophy", "classic",
})


@dataclass(frozen=True)
class Verdict:
    """Pourquoi ce fait est retenu ou écarté. La raison est portée, pas déduite."""

    statut: str
    raison: str

    @property
    def retenu(self) -> bool:
        return self.statut == RELEVANT


def _mots_significatifs(texte: str) -> set[str]:
    mots = re.findall(r"[^\W\d_]{3,}", (texte or "").lower())
    return {m for m in mots if m not in _MOTS_VIDES}


def _nomme_un_participant(valeur: str, participants: Sequence[str]) -> bool:
    minuscule = (valeur or "").lower()
    for nom in participants:
        # Le nom canonique peut valoir « Borges N. » : on cherche le patronyme,
        # qui est la partie stable entre le référentiel et une page web.
        for morceau in re.split(r"[\s.,–—-]+", nom):
            if len(morceau) >= 4 and morceau.lower() in minuscule:
                return True
    return False


def evaluate(
    feature: Any, *, kickoff: datetime, participants: Sequence[str],
    competition_label: str = "", maintenant: datetime | None = None,
) -> Verdict:
    """Ce fait peut-il être rattaché à CETTE rencontre ?

    Aucune des trois vérifications ne suffit seule, et leur ordre est celui du
    coût : le sujet d'abord, puis la formulation, puis la datation.
    """
    if not _nomme_un_participant(feature.value, participants):
        return Verdict(NOT_EVENT_RELEVANT, "ne nomme aucun participant de la rencontre")

    if _PASSE.search(feature.value):
        return Verdict(NOT_EVENT_RELEVANT, "relate un fait explicitement passé")

    if _RESULTAT.search(feature.value):
        return Verdict(NOT_EVENT_RELEVANT,
                       "raconte un résultat, donc un match déjà joué")

    # Le fait tient-il la promesse de son type ? C'est la charge de la preuve du
    # camp qui affiche, et non l'inverse.
    affirmation = _AFFIRMATIONS.get(feature.feature_type)
    if affirmation is not None and not affirmation.search(feature.value):
        return Verdict(NOT_EVENT_RELEVANT,
                       f"n'affirme rien qui relève d'un fait « {feature.feature_type} »")

    # Un tournoi NOMMÉ dans le texte, absent du libellé de la compétition : le
    # fait parle vraisemblablement d'une autre semaine du calendrier.
    #
    # Au tennis, la compétition canonique est le CIRCUIT (« ATP tour ») et non le
    # tournoi : on ne connaît donc jamais le nom de l'épreuve du jour. Une
    # première version comparait les mots de la compétition et se désactivait
    # silencieusement dans ce cas — « atp » et « tour » étant tous deux des mots
    # vides, la comparaison portait sur un ensemble VIDE et laissait tout passer.
    # Quand la compétition ne porte aucun nom distinctif, un tournoi nommé reste
    # donc suspect par lui-même.
    tournois = [t.strip() for t in _AUTRES_TOURNOIS.findall(feature.value)]
    if tournois:
        mots_competition = _mots_significatifs(competition_label)
        cite = _mots_significatifs(" ".join(tournois))
        if not (mots_competition & cite):
            return Verdict(NOT_EVENT_RELEVANT,
                           f"paraît concerner un autre tournoi ({tournois[0]})")

    validite = VALIDITE.get(feature.feature_type)
    if validite is None:
        return Verdict(NOT_EVENT_RELEVANT,
                       f"type de fait non datable ({feature.feature_type})")

    # La date du fait est celle de sa RÉCUPÉRATION : c'est la seule dont on
    # dispose réellement. La page, elle, n'expose pas toujours sa date de
    # publication — et l'inventer serait pire que de s'en passer.
    reference = maintenant or feature.retrieved_at
    age = kickoff - reference
    if age > validite:
        return Verdict(NOT_EVENT_RELEVANT,
                       f"établi {age.days} jour(s) avant le coup d'envoi, au-delà "
                       f"de la validité d'un fait « {feature.feature_type} »")
    if reference > kickoff:
        return Verdict(NOT_EVENT_RELEVANT, "postérieur au coup d'envoi")

    return Verdict(RELEVANT, "sujet, formulation et datation compatibles")


#: Un nom de tournoi dans le texte : deux mots capitalisés suivis d'un marqueur
#: de compétition. Volontairement étroit — mieux vaut rater un cas que d'écarter
#: un fait pertinent parce qu'une majuscule traînait.
_AUTRES_TOURNOIS = re.compile(
    r"\b((?:[A-Z][a-z]+\s+){1,3}(?:Open|Masters|Challenger|Cup|Classic|Championships))\b")


def filter_relevant(
    features: Sequence[Any], *, kickoff: datetime, participants: Sequence[str],
    competition_label: str = "", maintenant: datetime | None = None,
) -> tuple[tuple[Any, ...], tuple[tuple[Any, str], ...]]:
    """(faits retenus, faits écartés avec leur raison).

    Les écartés sont RENDUS, pas jetés : ils restent visibles en debug, où l'on
    veut savoir ce que la recherche a trouvé et pourquoi on ne l'a pas montré.
    """
    retenus, ecartes = [], []
    for feature in features:
        verdict = evaluate(feature, kickoff=kickoff, participants=participants,
                           competition_label=competition_label, maintenant=maintenant)
        if verdict.retenu:
            retenus.append(feature)
        else:
            ecartes.append((feature, verdict.raison))
    return tuple(retenus), tuple(ecartes)
