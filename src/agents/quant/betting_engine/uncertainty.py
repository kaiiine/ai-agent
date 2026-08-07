"""Borne basse de probabilité — mesurée, jamais une marge forfaitaire.

`probability_low` valait `fair_probability` sur tous les modèles, avec
`uncertainty_status=NOT_ESTIMATED`. Le contrat était honnête, et la conséquence
ne l'était pas : cette valeur est celle que le sizing traite comme PRUDENTE, et
un point estimé n'a rien de prudent.

Mesuré sur les données réelles, en walk-forward strict, la fréquence à laquelle
l'issue observée atteint la borne annoncée :

    NOT_ESTIMATED     NBA   0 %      MLB  33 %     Tennis ATP  51 %
    borne mesurée     NBA 100 %      MLB  80 %     Tennis ATP  83 %

Zéro pour cent au basket : le modèle y est systématiquement plus optimiste que la
réalité, et l'appeler « borne basse » ajoutait une fausse prudence par-dessus.

MÉTHODE. La borne est le minorant de Wilson de la fréquence historique observée
dans le VOISINAGE de cette prédiction. Concrètement : quand ce modèle a annoncé
une probabilité proche de celle-ci, l'issue s'est produite dans k cas sur n ; la
borne est le minorant de confiance de k/n.

Ce que cela capte, et c'est voulu : l'erreur de calibration ET l'incertitude
d'échantillonnage, en une seule quantité observable. Un modèle qui dit 0,62 alors
qu'il réalise 0,55 voit sa borne descendre — sans qu'aucune constante n'ait été
choisie.

Ce que cela ne capte PAS, et qu'il faut savoir : deux prédictions de même valeur
reçoivent la même borne, même si l'une porte sur une équipe à cinq matchs
d'historique et l'autre à cinq cents. Une incertitude vraiment individuelle
demanderait un rééchantillonnage des paramètres du modèle — mesuré à plusieurs
ordres de grandeur plus cher, pour un gain non démontré ici.

La largeur reste néanmoins CONDITIONNÉE à la prédiction : mesurée, elle varie
d'un facteur 2,7 (NBA) à 9,6 (MLB) entre les tranches. Ce n'est donc pas une
pénalité globale déguisée.

ALTERNATIVES ÉCARTÉES, avec leur raison :

- `probability_low = fair_probability − constante` : interdit, et à juste titre —
  une marge fixe ne mesure rien ;
- intervalle de Jeffreys : bornes identiques à Wilson à 10⁻⁴ près sur les mêmes
  données, pour un coût 1000× supérieur (26 s contre 0,03 s sur 4 000
  prédictions) et une instabilité numérique aux grands échantillons ;
- bootstrap des paramètres Elo : réellement individuel, mais exige de réajuster
  le modèle par rééchantillon — hors budget d'une prédiction live, et non
  départageable sans une étude dédiée.
"""

from __future__ import annotations

import functools
import math
from dataclasses import dataclass
from typing import Sequence

#: Nombre de tranches de probabilité. Dix donne des effectifs exploitables sur
#: les jeux les plus petits ; vingt double la résolution et vide les tranches
#: extrêmes — mesuré, la couverture n'y gagne rien et les cas dégénérés doublent.
N_TRANCHES = 10

#: Effectif minimal d'une tranche pour que sa fréquence veuille dire quelque
#: chose. En dessous, on ne rend PAS une borne large : on rend « non estimée »,
#: ce qui est différent — une borne large est une mesure, une absence n'en est
#: pas une.
MIN_ECHANTILLON = 30


@dataclass(frozen=True)
class CalibrationBins:
    """Fréquences historiques par tranche de probabilité prédite.

    Construites sur des observations STRICTEMENT antérieures à la prédiction à
    borner. C'est ce qui rend la borne point-in-time : le modèle ne voit jamais
    l'issue qu'il essaie de borner, ni aucune issue postérieure.
    """

    succes: tuple[int, ...]
    total: tuple[int, ...]
    confiance: float

    def tranche(self, probabilite: float) -> int:
        return min(N_TRANCHES - 1, max(0, int(probabilite * N_TRANCHES)))

    def borne_basse(self, probabilite: float) -> float | None:
        """Minorant pour cette probabilité, ou `None` si non mesurable."""
        indice = self.tranche(probabilite)
        n = self.total[indice]
        if n < MIN_ECHANTILLON:
            return None
        borne = wilson_lower(self.succes[indice], n, self.confiance)
        # La borne ne peut pas dépasser l'estimation : elle la MINORE. Quand
        # l'historique est meilleur que la prédiction, c'est la prédiction qui
        # fait foi — la borne ne sert pas à rendre un modèle plus optimiste.
        return min(probabilite, borne)


def wilson_lower(succes: int, total: int, confiance: float = 0.95) -> float:
    """Minorant de Wilson d'une proportion binomiale, unilatéral.

    Choisi pour sa tenue aux petits effectifs et aux proportions extrêmes, là où
    l'approximation normale simple rend des bornes négatives.
    """
    if total <= 0:
        return 0.0
    z = _z(confiance)
    p = succes / total
    denominateur = 1 + z * z / total
    centre = p + z * z / (2 * total)
    demi = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total))
    return max(0.0, (centre - demi) / denominateur)


@functools.lru_cache(maxsize=16)
def _z(confiance: float) -> float:
    """Quantile normal unilatéral. Table explicite : les niveaux utilisés sont
    connus, et une inversion numérique ajouterait une dépendance pour rien."""
    table = {0.80: 0.8416, 0.90: 1.2816, 0.95: 1.6449, 0.975: 1.9600, 0.99: 2.3263}
    if confiance in table:
        return table[confiance]
    proche = min(table, key=lambda niveau: abs(niveau - confiance))
    return table[proche]


def build_bins(paires: Sequence[tuple[float, float]], *,
               confiance: float = 0.95) -> CalibrationBins:
    """Table de calibration depuis des couples (probabilité prédite, issue).

    `issue` vaut 1 si l'événement prédit s'est produit, 0 sinon. L'ordre des
    couples n'entre pas dans le calcul — c'est à l'APPELANT de ne fournir que des
    observations antérieures à ce qu'il veut borner.
    """
    succes = [0] * N_TRANCHES
    total = [0] * N_TRANCHES
    for probabilite, issue in paires:
        indice = min(N_TRANCHES - 1, max(0, int(probabilite * N_TRANCHES)))
        succes[indice] += int(round(issue))
        total[indice] += 1
    return CalibrationBins(tuple(succes), tuple(total), confiance)


# ── Tables par modèle, construites une fois ───────────────────────────────────
#: Fabrique de couples (probabilité, issue) par version de modèle. Chaque entrée
#: rejoue le walk-forward du dataset EMBARQUÉ du modèle — donc des observations
#: toutes antérieures aux rencontres live qu'on bornera ensuite.
_SOURCES: dict[str, str] = {
    "basketball.moneyline.elo.v0": "nba",
    "baseball.moneyline.elo.v0": "mlb",
    "american_football.moneyline.elo.v0": "nfl",
    "volleyball.moneyline.elo.v0": "volley",
    "hockey.regulation.davidson.v0": "nhl",
    "tennis.moneyline.elo.v0": "atp",
}


@functools.lru_cache(maxsize=16)
def bins_for_model(model_version: str, confiance: float = 0.95) -> CalibrationBins | None:
    """Table de calibration d'un modèle, ou `None` s'il n'en a pas.

    Mémorisée : le walk-forward coûte de l'ordre de la seconde, et son résultat
    ne change pas tant que le dataset embarqué ne change pas.

    Une panne de construction rend `None` plutôt qu'une table vide : sans
    mesure, le modèle doit continuer d'annoncer `NOT_ESTIMATED` — pas une borne
    fabriquée à partir de rien.
    """
    cle = _SOURCES.get(model_version)
    if cle is None:
        return None
    try:
        paires = _paires_historiques(cle)
    except Exception:   # noqa: BLE001 — l'incertitude ne casse jamais une prédiction
        return None
    return build_bins(paires, confiance=confiance) if paires else None


def _paires_historiques(cle: str) -> list[tuple[float, float]]:
    """Couples (probabilité prédite, issue) du walk-forward embarqué."""
    if cle == "atp":
        from .sports.tennis.elo_model import (
            ATP_PARAMS, load_tennis_data, run_tennis_walk_forward,
        )
        run = run_tennis_walk_forward(load_tennis_data("atp").matches, ATP_PARAMS)
        return list(run.model_pairs)

    if cle == "nba":
        from .sports.basketball.moneyline import load_nba_games, run_elo_walk_forward
        run = run_elo_walk_forward(load_nba_games()[0])
        return [(p["home"], 1.0 if o == "home" else 0.0) for p, o in run.model_predictions]

    from .sports.pairwise_elo import run_pairwise_elo
    chargeurs = {
        "mlb": ("baseball.moneyline", "load_mlb_games", "MLB_PARAMS"),
        "nfl": ("american_football.moneyline", "load_nfl_games", "NFL_PARAMS"),
        "volley": ("volleyball.moneyline", "load_volleyball_games", "VOLLEY_PARAMS"),
        "nhl": ("hockey.regulation", "load_nhl_regulation", "NHL_PARAMS"),
    }
    module_nom, chargeur_nom, params_nom = chargeurs[cle]
    import importlib
    module = importlib.import_module(f".sports.{module_nom}", package=__package__)
    charge = getattr(module, chargeur_nom)()
    jeux = charge[0] if isinstance(charge, tuple) else charge
    params = getattr(module, params_nom)
    if cle == "nhl":                     # 3-way : la borne porte sur l'issue home
        from .sports.threeway_davidson import run_threeway_davidson
        run = run_threeway_davidson(jeux, params)
        return [(p["home"], 1.0 if o == "home" else 0.0) for p, o in run.model_predictions]
    run = run_pairwise_elo(jeux, params)
    return [(p["home"], 1.0 if o == "home" else 0.0) for p, o in run.model_predictions]


def bound_for(model_version: str, probabilite: float,
              confiance: float = 0.95) -> tuple[float, bool]:
    """(borne basse, mesurée ?) pour une probabilité de ce modèle.

    Rend `(probabilite, False)` quand aucune mesure n'est disponible — le modèle
    annonce alors `NOT_ESTIMATED`, ce qui reste la seule description honnête.
    """
    bins = bins_for_model(model_version, confiance)
    if bins is None:
        return probabilite, False
    borne = bins.borne_basse(probabilite)
    if borne is None:
        return probabilite, False
    return borne, True
