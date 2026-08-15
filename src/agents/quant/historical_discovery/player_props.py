"""Props de JOUEUR : ce que le bookmaker propose, et ce qu'on pourrait modéliser.

Les props représentent la plus grande part du catalogue non modélisée — mesuré,
67,9 % des marchés d'une rencontre de basket. Avant d'écrire le moindre modèle,
il faut savoir si les données existent ET si on a le droit de s'en servir : un
modèle sans corpus ne price rien, et un corpus sans licence ne se garde pas.

CETTE MATRICE NE MODÉLISE RIEN. Elle dit, famille par famille, ce que le marché
expose, ce qu'il faudrait comme données, quelle source est candidate, sous quelle
licence, et où ça bloque. Une case honnête vaut mieux qu'un modèle rapide.

MESURES DU CATALOGUE (scan réel, 3 événements par sport, 2026-08-15) :

    basket             803 marchés · 545 props de joueur (67,9 %)
    football           691 marchés · 144 props par clé `player`, plus 121 marchés
                       « Nombre de passes décisives » dont le joueur est encodé
                       dans un `variant=pre:playerprops:…` opaque, et des marqueurs
                       en ListOdd dont le joueur n'existe QUE dans le libellé
    football américain 194 marchés · 0 prop (présaison : marché très mince)
    hockey              12 marchés · 0 prop (présaison)

LE JOUEUR N'EST PAS TOUJOURS IDENTIFIABLE, et c'est un blocage distinct de la
licence. Quatre formes coexistent, et une seule est inutilisable :

    player=sr:player:1152420          structuré, identifiant SportRadar
    players=sr:ID-sr:ID               structuré, multi-joueurs
    player1=…|player2=…               structuré, face-à-face
    variant=pre:playerprops:X:Y       OPAQUE — aucun identifiant de joueur lisible
    ListOdd, joueur dans le libellé   NON structuré — le nom seul, à résoudre

VÉRIFICATIONS DATÉES DU 2026-08-15, par sondage réel.
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: Statut d'utilisabilité d'une source, du point de vue d'un usage PERSONNEL non
#: commercial. L'ordre va du plus ouvert au plus fermé.
FREE_USABLE = "FREE_USABLE"
AUTH_REQUIRED_FREE = "AUTH_REQUIRED_FREE"
PERSONAL_NON_COMMERCIAL_ONLY = "PERSONAL_NON_COMMERCIAL_ONLY"
PAID = "PAID"
LICENSE_UNKNOWN = "LICENSE_UNKNOWN"
FORBIDDEN = "FORBIDDEN"
NO_CANDIDATE = "NO_CANDIDATE"

STATUTS = frozenset({FREE_USABLE, AUTH_REQUIRED_FREE, PERSONAL_NON_COMMERCIAL_ONLY,
                     PAID, LICENSE_UNKNOWN, FORBIDDEN, NO_CANDIDATE})


@dataclass(frozen=True)
class FamilleProp:
    """Une famille de props, de ce que le marché en propose à ce qui la bloque."""

    sport: str
    famille: str
    #: Marchés observés pour cette famille dans le scan réel. `None` = famille
    #: attendue mais NON observée — ce qui n'est pas la même chose que zéro.
    marches_observes: int | None
    #: Le joueur est-il identifiable STRUCTURELLEMENT dans le payload ?
    sujet_identifiable: bool
    donnees_requises: tuple[str, ...]
    source_candidate: str | None
    licence: str | None
    statut: str
    preuve: str = ""
    blocage: str = ""
    bet_types: tuple[int, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.statut not in STATUTS:
            raise ValueError(f"statut inconnu : {self.statut!r}")

    @property
    def exploitable(self) -> bool:
        """Une source utilisable NE SUFFIT PAS : encore faut-il pouvoir dire de
        quel joueur parle le marché."""
        return self.statut == FREE_USABLE and self.sujet_identifiable


MATRICE: tuple[FamilleProp, ...] = (
    # ── football américain : le seul cas entièrement débloqué côté données ────
    FamilleProp(
        sport="american_football", famille="passing (yards, TD, tentatives)",
        marches_observes=0, sujet_identifiable=True,
        donnees_requises=("statistiques de joueur par match",),
        source_candidate="nflverse/nflverse-data release `player_stats`",
        licence="CC-BY-4.0", statut=FREE_USABLE,
        preuve="HTTP 200, player_stats.csv 33 447 747 octets ; colonnes "
               "completions/attempts/passing_yards/passing_tds/interceptions ; "
               "LICENSE.md lu = Attribution 4.0 International",
        blocage="STOP EXTERNAL — aucune prop NFL au catalogue : 16 événements, "
                "moreBets 63-65 par rencontre, 514 marchés lus sur 8 rencontres, "
                "ZÉRO prop (2026-08-15). Winamax ouvre ces marchés à l'approche de "
                "la saison, le 10 septembre. Les données existent AVANT le marché — "
                "situation inverse exacte du basket."),
    FamilleProp(
        sport="american_football", famille="rushing (yards, TD, courses)",
        marches_observes=0, sujet_identifiable=True,
        donnees_requises=("statistiques de joueur par match",),
        source_candidate="nflverse/nflverse-data release `player_stats`",
        licence="CC-BY-4.0", statut=FREE_USABLE,
        preuve="mêmes colonnes : carries/rushing_yards/rushing_tds/rushing_fumbles",
        blocage="marché non observé au catalogue (présaison)"),
    FamilleProp(
        sport="american_football", famille="receiving (réceptions, yards, TD)",
        marches_observes=0, sujet_identifiable=True,
        donnees_requises=("statistiques de joueur par match",),
        source_candidate="nflverse/nflverse-data release `player_stats`",
        licence="CC-BY-4.0", statut=FREE_USABLE,
        preuve="colonnes receptions/targets/receiving_yards/receiving_tds",
        blocage="marché non observé au catalogue (présaison)"),

    # ── basket : le marché le plus riche, aucune source libre ────────────────
    FamilleProp(
        sport="basketball", famille="points du joueur",
        marches_observes=60, sujet_identifiable=True, bet_types=(3722, 5598),
        donnees_requises=("box score par joueur et par match",),
        source_candidate="api.balldontlie.io", licence="tier ALL-STAR, 9,99 $/mois",
        statut=PAID,
        preuve="HTTP 401 sans clé ; tableau des tiers de la documentation lu le "
               "2026-08-15 : Teams/Players/Games = « Yes » en gratuit, "
               "« Game Player Stats » = « No ». Gratuit limité à 5 req/min.",
        blocage="Le tier gratuit expose tout SAUF ce dont un modèle de prop a "
                "besoin. Une clé gratuite ne débloque rien — il n'y a pas de "
                "credential à demander, il y a un abonnement à refuser."),
    FamilleProp(
        sport="basketball", famille="rebonds du joueur",
        marches_observes=35, sujet_identifiable=True, bet_types=(2661, 5620),
        donnees_requises=("box score par joueur et par match",),
        source_candidate="api.balldontlie.io", licence="tier ALL-STAR, 9,99 $/mois",
        statut=PAID, preuve="idem points", blocage="idem points"),
    FamilleProp(
        sport="basketball", famille="passes décisives du joueur",
        marches_observes=20, sujet_identifiable=True, bet_types=(3764, 5619),
        donnees_requises=("box score par joueur et par match",),
        source_candidate="api.balldontlie.io", licence="tier ALL-STAR, 9,99 $/mois",
        statut=PAID, preuve="idem points", blocage="idem points"),
    FamilleProp(
        sport="basketball", famille="paniers à 3 points du joueur",
        marches_observes=22, sujet_identifiable=True, bet_types=(3373, 5622),
        donnees_requises=("box score par joueur et par match",),
        source_candidate="api.balldontlie.io", licence="tier ALL-STAR, 9,99 $/mois",
        statut=PAID, preuve="idem points", blocage="idem points"),
    FamilleProp(
        sport="basketball", famille="combinés joueur (points+rebonds+passes)",
        marches_observes=135, sujet_identifiable=True,
        bet_types=(5590, 5591, 5592, 5593, 6044, 6045, 6046, 6047),
        donnees_requises=("box score par joueur et par match",),
        source_candidate="api.balldontlie.io", licence="tier ALL-STAR, 9,99 $/mois",
        statut=PAID,
        preuve="8 betTypes distincts, 135 marchés sur 3 rencontres",
        blocage="idem points ; s'y ajoute que la corrélation entre composantes "
                "d'un combiné ne se dérive pas de leurs lois marginales"),
    FamilleProp(
        sport="basketball", famille="duos / trios de marqueurs",
        marches_observes=220, sujet_identifiable=True, bet_types=(5594, 5595, 5596),
        donnees_requises=("box score par joueur", "corrélation entre coéquipiers"),
        source_candidate="api.balldontlie.io", licence="tier ALL-STAR, 9,99 $/mois",
        statut=PAID,
        preuve="220 marchés — la plus grosse famille du catalogue basket",
        blocage="Deux joueurs de la MÊME équipe se partagent un volume de tirs "
                "fini : traiter leurs totaux comme indépendants surestimerait "
                "systématiquement la probabilité conjointe."),

    # ── football : le sujet lui-même n'est pas toujours lisible ──────────────
    FamilleProp(
        sport="football", famille="duo / trio de buteurs",
        marches_observes=144, sujet_identifiable=True, bet_types=(5702, 5703),
        donnees_requises=("buteurs par match", "minutes jouées"),
        source_candidate=None, licence=None, statut=NO_CANDIDATE,
        preuve="openfootball sondé : HTTP 200 mais le format Football.TXT est "
               "STRICTEMENT au niveau match (« Manchester United FC v Fulham FC "
               "1-0 (0-0) ») — aucun buteur, aucune minute, aucun carton",
        blocage="Aucune archive libre de buteurs identifiée pour les championnats "
                "couverts."),
    FamilleProp(
        sport="football", famille="passes décisives du joueur",
        marches_observes=121, sujet_identifiable=False, bet_types=(3361,),
        donnees_requises=("passes décisives par joueur et par match",),
        source_candidate=None, licence=None, statut=NO_CANDIDATE,
        preuve="le joueur est encodé dans `variant=pre:playerprops:66299338:2601927` "
               "— une paire d'identifiants opaques, sans référentiel connu",
        blocage="DOUBLE blocage : ni source de données, ni identification "
                "structurée du joueur. Le second est le plus dur — un modèle "
                "parfait resterait inutilisable faute de savoir de qui on parle."),
    FamilleProp(
        sport="football", famille="buteur (marché en liste)",
        marches_observes=18, sujet_identifiable=False, bet_types=(5659, 5660),
        donnees_requises=("buteurs par match",),
        source_candidate=None, licence=None, statut=NO_CANDIDATE,
        preuve="template ListOdd, joueurs présents UNIQUEMENT comme libellés "
               "d'issue (« A. Kovac », « Cayman Togashi »)",
        blocage="Le nom abrégé est la seule identification disponible, et le "
                "chantier a déjà mesuré ce que valent les libellés : « L.A. "
                "Sparks » pour « Los Angeles Sparks »."),
    FamilleProp(
        sport="football", famille="minutes, tirs, tirs cadrés, cartons",
        marches_observes=None, sujet_identifiable=False,
        donnees_requises=("événements de match par joueur",),
        source_candidate=None, licence=None, statut=NO_CANDIDATE,
        preuve="familles NON observées dans le scan des trois rencontres MLS",
        blocage="ni marché observé, ni source — rien à conclure pour l'instant"),

    # ── hockey : fermé contractuellement ─────────────────────────────────────
    FamilleProp(
        sport="hockey", famille="temps de glace, buts, passes, tirs",
        marches_observes=0, sujet_identifiable=False,
        donnees_requises=("box score par joueur et par match",),
        source_candidate="api-web.nhle.com", licence="NHL Terms of Service",
        statut=FORBIDDEN,
        preuve="CGU §2 : « unauthorized spidering, scraping, or harvesting » "
               "prohibé ; §7 : usage personnel et non commercial uniquement",
        blocage="Techniquement ouverte, contractuellement fermée. "
                "L'accessibilité n'est pas une permission."),
)


def par_sport(sport: str) -> tuple[FamilleProp, ...]:
    return tuple(f for f in MATRICE if f.sport == sport)


def exploitables() -> tuple[FamilleProp, ...]:
    """Les familles qu'on POURRAIT modéliser : source libre ET joueur lisible."""
    return tuple(f for f in MATRICE if f.exploitable)


def resume() -> dict:
    """Compte par statut. Aucune famille n'est omise — l'absence de candidat est
    un statut, pas un trou dans le tableau."""
    from collections import Counter
    return dict(Counter(f.statut for f in MATRICE).most_common())
