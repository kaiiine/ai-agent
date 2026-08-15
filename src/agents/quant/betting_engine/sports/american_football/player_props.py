"""Props de JOUEUR NFL — la statistique comme DISTRIBUTION, jamais comme point.

Une prop se cote contre une LIGNE que le bookmaker déplace d'un match à l'autre :
274,5 yards à la passe cette semaine, 249,5 la suivante. Un modèle qui rendrait
une espérance ne répondrait donc à aucune question posée — comparer une moyenne
prédite à une cote est exactement le raccourci interdit. Ce module produit une
LOI de la statistique, et la ligne s'y lit après coup :

    passing_yards ~ loi(μ, σ)   puis   P(yards > 274,5)

UN MODÈLE PAR STATISTIQUE, PAS UN PAR LIGNE. C'est la même discipline que les
totaux de score : la ligne est un paramètre de lecture, pas une famille.

CORPUS : nflverse `player_stats`, 134 470 lignes joueur-semaine, saisons 1999 à
2024, licence CC-BY-4.0 (attribution obligatoire). Il porte exactement les
familles que le marché cote — passes, courses, réceptions — et, en prime, le
`target_share`, qui est une feature d'usage disponible AVANT le match.

SANS FUITE PAR CONSTRUCTION. L'état d'un joueur à la semaine W ne dépend que de
ses matchs strictement antérieurs, dans l'ordre du calendrier. Aucune moyenne de
saison, aucun agrégat calculé sur l'ensemble : ce sont les deux façons dont une
prop se met à prédire le passé.

LA POPULATION EST CONDITIONNELLE À LA PARTICIPATION, et il faut le dire. Le
corpus ne contient une ligne que si le joueur a joué. Les probabilités rendues
ici sont donc des P(stat > ligne | le joueur joue) — ce qui correspond au
règlement usuel du marché (pari annulé si le joueur ne participe pas), mais
n'est PAS la probabilité inconditionnelle, et un blessé de dernière minute ne
s'y lit pas.
"""

from __future__ import annotations

import csv
import gzip
import math
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

_FIXTURE = Path(__file__).resolve().parents[6] / "tests" / "fixtures" / "nfl_player_stats.csv.gz"

#: Familles de props, avec la colonne du corpus et la nature de la statistique.
#: `entier` distingue un COMPTAGE (réceptions, tentatives, touchdowns) d'une
#: quantité continue (yards) : les deux ne se modélisent pas par la même loi, et
#: les confondre donnerait des probabilités décalées d'un demi-point sur les
#: petites valeurs — précisément là où les lignes du marché se situent.
@dataclass(frozen=True)
class FamilleStat:
    nom: str
    colonne: str
    entier: bool
    positions: tuple[str, ...]
    #: Lignes de marché typiques, servant de grille d'évaluation. Ce ne sont pas
    #: des seuils de décision : ce sont les points où l'on regarde si la loi
    #: répond juste.
    lignes: tuple[float, ...]


FAMILLES: tuple[FamilleStat, ...] = (
    FamilleStat("PASSING_YARDS", "passing_yards", False, ("QB",),
                (149.5, 199.5, 249.5, 299.5)),
    FamilleStat("PASSING_ATTEMPTS", "attempts", True, ("QB",),
                (24.5, 29.5, 34.5, 39.5)),
    FamilleStat("PASSING_TDS", "passing_tds", True, ("QB",), (0.5, 1.5, 2.5)),
    FamilleStat("INTERCEPTIONS", "interceptions", True, ("QB",), (0.5, 1.5)),
    FamilleStat("RUSHING_YARDS", "rushing_yards", False, ("RB", "QB"),
                (29.5, 49.5, 69.5, 89.5)),
    FamilleStat("RUSHING_ATTEMPTS", "carries", True, ("RB",), (9.5, 14.5, 19.5)),
    FamilleStat("RUSHING_TDS", "rushing_tds", True, ("RB",), (0.5, 1.5)),
    FamilleStat("RECEIVING_YARDS", "receiving_yards", False, ("WR", "TE", "RB"),
                (29.5, 49.5, 69.5, 89.5)),
    FamilleStat("RECEPTIONS", "receptions", True, ("WR", "TE", "RB"),
                (2.5, 3.5, 4.5, 5.5, 6.5)),
    FamilleStat("RECEIVING_TDS", "receiving_tds", True, ("WR", "TE"), (0.5, 1.5)),
)

PAR_NOM = {f.nom: f for f in FAMILLES}


@dataclass(frozen=True)
class LigneJoueur:
    """Une performance de joueur sur une rencontre, telle que le corpus la donne."""

    player_id: str
    nom: str
    position: str
    equipe: str
    adversaire: str
    saison: int
    semaine: int
    type_saison: str
    stats: dict = field(default_factory=dict)

    @property
    def cle_temporelle(self) -> tuple[int, int]:
        """Ordre chronologique. La semaine de playoff suit la saison régulière —
        `season_type` sert donc de départage, jamais de filtre silencieux."""
        return (self.saison, self.semaine + (100 if self.type_saison == "POST" else 0))


def _nombre(valeur, entier: bool):
    if valeur in (None, "", "NA"):
        return None
    try:
        f = float(valeur)
    except (TypeError, ValueError):
        return None
    return int(round(f)) if entier else f


def charger(chemin: Path = _FIXTURE) -> list[LigneJoueur]:
    """Le corpus, dans l'ordre du calendrier. Une seule lecture, une seule fois."""
    colonnes = {f.colonne: f.entier for f in FAMILLES}
    colonnes["targets"] = True
    colonnes["target_share"] = False
    lignes: list[LigneJoueur] = []
    with gzip.open(chemin, "rt", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            saison = _nombre(row.get("season"), True)
            semaine = _nombre(row.get("week"), True)
            if saison is None or semaine is None:
                continue
            lignes.append(LigneJoueur(
                player_id=row["player_id"], nom=row["player_display_name"],
                position=row.get("position") or "", equipe=row.get("recent_team") or "",
                adversaire=row.get("opponent_team") or "",
                saison=saison, semaine=semaine,
                type_saison=row.get("season_type") or "REG",
                stats={c: _nombre(row.get(c), e) for c, e in colonnes.items()}))
    lignes.sort(key=lambda l: (l.cle_temporelle, l.player_id))
    return lignes


# ── État séquentiel par joueur ───────────────────────────────────────────────

@dataclass(frozen=True)
class ParamsProp:
    """Paramètres de méthode, fixes et documentés — jamais fités sur l'évaluation."""

    #: Poids du match le plus récent dans la moyenne exponentielle. 0,25 donne
    #: une demi-vie d'environ 2,4 matchs : assez court pour suivre un changement
    #: de rôle, assez long pour ne pas suivre le bruit d'un seul match.
    alpha: float = 0.25
    #: Matchs antérieurs requis. En dessous, la moyenne est dominée par sa valeur
    #: initiale et la variance n'existe pas — ce ne serait pas une prédiction
    #: faible, ce serait la valeur par défaut déguisée.
    min_matchs: int = 6
    #: Écart-type plancher, pour éviter une loi dégénérée sur un joueur dont les
    #: dernières sorties ont été identiques. Exprimé en FRACTION de la moyenne :
    #: une constante absolue n'aurait pas de sens commun entre « 3 réceptions »
    #: et « 280 yards ».
    sigma_min_relatif: float = 0.15
    notes: str = ""


@dataclass(frozen=True)
class PredictionProp:
    """La loi annoncée pour une statistique, avant la rencontre."""

    moyenne: float
    ecart_type: float
    matchs_anterieurs: int
    #: Usage récent, quand la famille en dépend. Purement descriptif ici — il
    #: entre déjà dans la moyenne, et l'exposer permet de voir pourquoi elle bouge.
    usage_recent: float | None = None


class EtatJoueur:
    """Moyenne et dispersion exponentielles d'une statistique, par joueur.

    Se consomme dans l'ordre du calendrier et ne sait pas revenir en arrière :
    l'absence de fuite se lit dans la structure plutôt que par convention.
    """

    def __init__(self, params: ParamsProp):
        self.params = params
        self._moyenne: dict[tuple[str, str], float] = {}
        self._variance: dict[tuple[str, str], float] = {}
        self._n: dict[tuple[str, str], int] = defaultdict(int)

    def predict(self, player_id: str, colonne: str) -> PredictionProp | None:
        cle = (player_id, colonne)
        n = self._n[cle]
        if n < self.params.min_matchs:
            return None
        moyenne = self._moyenne[cle]
        variance = self._variance.get(cle, 0.0)
        plancher = self.params.sigma_min_relatif * max(moyenne, 1e-6)
        return PredictionProp(moyenne=moyenne,
                              ecart_type=max(math.sqrt(max(variance, 0.0)), plancher),
                              matchs_anterieurs=n)

    def update(self, player_id: str, colonne: str, valeur: float) -> None:
        cle = (player_id, colonne)
        a = self.params.alpha
        if self._n[cle] == 0:
            self._moyenne[cle] = float(valeur)
            self._variance[cle] = 0.0
        else:
            ecart = float(valeur) - self._moyenne[cle]
            self._moyenne[cle] += a * ecart
            # Variance exponentielle (Finch, 2009) : la mémoire de la dispersion
            # suit celle de la moyenne, donc un joueur qui change de rôle voit
            # les deux bouger ensemble.
            self._variance[cle] = (1 - a) * (self._variance.get(cle, 0.0) + a * ecart * ecart)
        self._n[cle] += 1


# ── Lois candidates ──────────────────────────────────────────────────────────

def _phi(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def p_depasse_normale(prediction: PredictionProp, ligne: float) -> float:
    """P(stat > ligne) sous une loi normale. Pour les quantités CONTINUES."""
    return 1.0 - _phi((ligne - prediction.moyenne) / prediction.ecart_type)


def p_depasse_negbin(prediction: PredictionProp, ligne: float) -> float:
    """P(stat > ligne) sous une binomiale négative, paramétrée par sa moyenne et
    sa variance. Pour les COMPTAGES, où la normale place de la masse sur des
    valeurs négatives — un joueur ne peut pas capter −1 ballon.

    Quand la variance ne dépasse pas la moyenne, la surdispersion n'existe pas et
    la loi dégénère en Poisson : on y retombe explicitement plutôt que de forcer
    un paramètre hors de son domaine.
    """
    moyenne = max(prediction.moyenne, 1e-6)
    variance = max(prediction.ecart_type ** 2, moyenne * 1.000001)
    r = moyenne * moyenne / (variance - moyenne)
    p = r / (r + moyenne)
    seuil = int(math.floor(ligne))
    cumul = 0.0
    for k in range(seuil + 1):
        cumul += math.exp(math.lgamma(k + r) - math.lgamma(r) - math.lgamma(k + 1)
                          + r * math.log(p) + k * math.log(1 - p))
    return max(0.0, min(1.0, 1.0 - cumul))


LOIS_PROP = {"NORMAL": p_depasse_normale, "NEGBIN": p_depasse_negbin}


def loi_par_defaut(famille: FamilleStat) -> str:
    """La loi qu'impose la NATURE de la statistique. Le benchmark la confirme ou
    l'infirme ; ce n'est pas un choix esthétique."""
    return "NEGBIN" if famille.entier else "NORMAL"
