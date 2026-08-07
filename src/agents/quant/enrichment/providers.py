"""Catalogue des providers candidats — sondés, jamais intégrés automatiquement.

Chaque entrée vient d'une sonde réelle (code HTTP, corps de réponse) et d'une
recherche de tarif, pas d'un souvenir. Quand un événement est bloqué faute de
provider, l'utilisateur voit ce qui existe et ce que ça coûte, et décide.

Rien ici ne s'intègre tout seul : un provider payant engage de l'argent, et un
provider gratuit engage une licence. Les deux sont des décisions humaines.
"""

from __future__ import annotations

from dataclasses import dataclass

FREE = "FREE"
AUTH_REQUIRED = "AUTH_REQUIRED"
PAID_REQUIRED = "PAID_REQUIRED"
UNREACHABLE = "UNREACHABLE"


@dataclass(frozen=True)
class ProviderOption:
    name: str
    url: str
    access: str
    #: Ce que la sonde a réellement observé — pas ce que le marketing annonce.
    probe: str
    covers: tuple[str, ...] = ()
    point_in_time: bool = False
    price_hint: str = ""
    note: str = ""


#: Sondés le 2026-08-07. `probe` cite le constat brut : un 403 est un 403, et
#: « couvre le Challenger » reste ce que le provider ANNONCE tant qu'on n'a pas
#: de clé pour le vérifier.
TENNIS_PROVIDERS: tuple[ProviderOption, ...] = (
    ProviderOption(
        "api-tennis.com", "https://api.api-tennis.com/", PAID_REQUIRED,
        probe='HTTP 200, JSON {"error":"Wrong login credentials"} — API vivante',
        covers=("ATP", "WTA", "Challenger (annoncé)", "ITF (annoncé)", "historique"),
        point_in_time=True, price_hint="~40 $/mois, essai 14 jours",
        note="Le moins cher annonçant Challenger + ITF."),
    ProviderOption(
        "Sportradar", "https://developer.sportradar.com/", PAID_REQUIRED,
        probe="HTTP 403 sur l'endpoint trial — authentification exigée",
        covers=("ATP", "WTA", "ITF", "Challenger", "qualifications", "historique", "live"),
        point_in_time=True, price_hint="contrat commercial, tarif non public",
        note="Couverture la plus large ; engagement contractuel."),
    ProviderOption(
        "Goalserve", "https://www.goalserve.com/en/sport-data-feeds/tennis-api/",
        PAID_REQUIRED,
        probe="HTTP 200, page tarifaire mentionnant un essai gratuit",
        covers=("ATP", "WTA", "ITF", "Challenger", "historique", "live"),
        point_in_time=True, price_hint="~150 $/mois"),
    ProviderOption(
        "Enetpulse", "https://www.enetpulse.com/tennis-data-api/", PAID_REQUIRED,
        probe="HTTP 200, offre commerciale",
        covers=("ATP", "WTA", "classements", "live"), point_in_time=True),
    ProviderOption(
        "Tennis Abstract", "https://www.tennisabstract.com/", FREE,
        probe="HTTP 200, pages HTML sans API structurée",
        covers=("ATP", "WTA", "Challenger", "historique"),
        point_in_time=False,
        note="Riche mais non structuré : scraping HTML, pas un flux exploitable."),
    ProviderOption(
        "tennis-data.co.uk", "http://www.tennis-data.co.uk/alldata.php", FREE,
        probe="HTTP 200 — source ACTUELLEMENT utilisée par AXON",
        covers=("ATP", "WTA", "tableau final 2000-2026"),
        point_in_time=True,
        note="Ne couvre PAS Challenger/ITF/qualifications — c'est précisément "
             "ce manque qui plafonne le coverage à 0,77."),
    ProviderOption(
        "JeffSackmann/tennis_atp", "https://github.com/JeffSackmann/tennis_atp",
        UNREACHABLE,
        probe="HTTP 404 ; un seul dépôt public reste chez cet auteur",
        covers=("ATP", "WTA", "qual/Challenger — historiquement"),
        note="Retiré du public. Le Match Charting Project subsiste mais contient "
             "du point-par-point, pas une archive de résultats."),
    ProviderOption(
        "UTR Sports", "https://app.utrsports.net/", AUTH_REQUIRED,
        probe="HTTP 200, compte requis",
        covers=("classement propriétaire tous niveaux",),
        note="Classement universel intéressant en feature, mais propriétaire."),
)


def providers_for(sport: str) -> tuple[ProviderOption, ...]:
    """Options connues pour un sport. Vide plutôt qu'approximatif : proposer une
    piste non sondée ferait perdre du temps à celui qui la suit."""
    return TENNIS_PROVIDERS if sport == "tennis" else ()
