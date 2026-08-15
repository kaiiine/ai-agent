"""Tennis — quels marchés de sets et de jeux tiennent, et lesquels ne tiennent pas.

Cinq marchés ont été confrontés à l'historique par la MÊME mécanique que le
football et les sports à points : walk-forward strict, baseline point-in-time,
`build_target_metrics`, seuils de `model_maturity_policy`. Deux passent, trois
échouent — et les trois échecs sont plus instructifs que les deux réussites.

MESURÉ (ATP 100 802 rencontres évaluées 1991-2018 · WTA 119 877 rencontres
1949-2021 · best-of-3) :

    marché           ATP Brier/baseline   WTA Brier/baseline   ECE ATP/WTA   verdict
    SET_WINNER       0,4747 / 0,5000      0,4153 / 0,5000      0,003 / 0,026  VALIDÉ
    MATCH_SET_SCORE  0,7167 / 0,7288      0,6298 / 0,7096      0,032 / 0,039  VALIDÉ
    TOTAL_SETS       0,4853 / 0,4575      0,4320 / 0,4191      0,119 / 0,095  REJETÉ
    TOTAL_GAMES      0,5305 / 0,4950      0,5459 / 0,4909      0,136 / 0,147  REJETÉ
    GAME_HANDICAP    voir ci-dessous — le verdict dépend de la LIGNE            REJETÉ

Le handicap de jeux mérite son détail, parce qu'il illustre les deux façons
d'échouer à la fois. Sur les cinq lignes ATP mesurées, trois ne battent pas leur
baseline (−0,0015 à −0,0023) et quatre dépassent le seuil de calibration. Sur la
WTA, les cinq battent leur baseline — jusqu'à +0,10 de Brier — et quatre sur cinq
sont mal calibrées, jusqu'à 0,107 pour un seuil à 0,05. Ne retenir que la ligne
ATP à 0,036 d'ECE aurait validé la famille sur son meilleur échantillon ; c'est
exactement la sélection que la règle par ligne du football interdit déjà.

CE QUE LES ÉCHECS DISENT, ET C'EST LE RÉSULTAT PRINCIPAL. Le modèle dérive tout
d'une probabilité par JEU, en supposant les jeux indépendants puis les sets
indépendants. Ces deux hypothèses sont assez bonnes pour dire QUI gagne un set —
c'est une question de force relative, et l'ordre des jeux y compte peu. Elles ne
le sont pas du tout pour dire COMBIEN de jeux se joueront : la durée d'un match
dépend de la manière dont le score évolue, exactement ce que l'indépendance
efface.

Mesure directe de ce point : en remplaçant le total attendu par la moyenne de
ligue du format — donc un modèle sans aucune information sur l'affiche — le
`TOTAL_GAMES` passe de 0,5459 à 0,4929 de Brier. Le modèle fait PIRE que de ne
rien savoir. Ce n'est pas un réglage à ajuster, c'est une hypothèse à remplacer.

`GAME_HANDICAP` bat ses baselines (jusqu'à +0,10 de Brier) mais son erreur de
calibration atteint 0,107 sur la WTA, pour un seuil de politique à 0,05. Battre
une baseline sans être calibré donne des probabilités ordonnées dans le bon sens
et fausses en niveau — soit exactement ce qu'il ne faut pas donner à un calcul
d'espérance.

LE VRAI BLOCAGE EST AILLEURS, ET IL EST DE DONNÉES. Les rencontres qu'AXON
ÉVALUE et celles qui portent un SCORE sont deux populations disjointes :

    ATP   70 688 rencontres à cotes (2000-2026), 0 avec score
          151 873 rencontres avec score, dont le circuit principal s'arrête en 1999
    WTA   46 769 rencontres à cotes (2006-2026), 0 avec score
          187 233 rencontres avec score, circuit principal jusqu'en 2021

Aucun de ces marchés ne peut donc être pricé en direct aujourd'hui : le corpus
qui les valide ne recouvre pas le corpus qui les jouerait. C'est un STOP DATA, et
il est indépendant de la qualité des modèles.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Marchés confrontés à l'historique, avec leur verdict MÉCANIQUE : bat-il sa
#: baseline point-in-time, et son erreur de calibration passe-t-elle le seuil de
#: `model_maturity_policy` (0,05) ?
FAMILLES = ("SET_WINNER", "MATCH_SET_SCORE", "TOTAL_SETS", "TOTAL_GAMES",
            "GAME_HANDICAP")

#: Ce qui bloque la mise en production, marché validé compris.
STOP_DONNEES = (
    "STOP DATA — les rencontres à cotes et les rencontres à score sont deux "
    "populations disjointes. ATP : 70 688 cibles (2000-2026) dont AUCUNE ne "
    "porte de score, et un corpus scoré de circuit principal qui s'arrête en "
    "1999. WTA : 46 769 cibles (2006-2026) sans score, corpus scoré jusqu'en "
    "2021. Un marché validé sur une population qu'on ne price jamais ne price "
    "rien."
)


@dataclass(frozen=True)
class MesureMarcheTennis:
    """Une ligne du benchmark, telle qu'elle a été mesurée."""

    marche: str
    circuit: str
    best_of: int
    n_eval: int
    brier: float
    baseline: float
    ece: float
    verdict: str

    @property
    def bat_la_baseline(self) -> bool:
        return self.brier < self.baseline

    @property
    def calibre(self) -> bool:
        """Seuil LU dans la politique de maturité, jamais choisi ici."""
        from ...maturity import load_maturity_policy
        return self.ece <= load_maturity_policy().criteria["max_calibration_error"]


#: Le benchmark, figé — TOUTES les lignes mesurées, pas les plus flatteuses.
#: N'en garder qu'une par famille laissait passer un `GAME_HANDICAP` ATP à
#: 0,036 d'ECE alors que quatre de ses cinq lignes dépassent 0,08 : une famille
#: se juge sur l'ensemble de son support, exactement comme les Plus/Moins
#: football dont une ligne sur six est rejetée.
MESURES: tuple[MesureMarcheTennis, ...] = (
    # ── validés ──────────────────────────────────────────────────────────────
    MesureMarcheTennis("SET_WINNER", "atp", 3, 100802, 0.4747, 0.5000, 0.0027, "VALIDATED"),
    MesureMarcheTennis("SET_WINNER", "atp", 5, 2949, 0.4645, 0.5017, 0.0149, "VALIDATED"),
    MesureMarcheTennis("SET_WINNER", "wta", 3, 119877, 0.4153, 0.5000, 0.0262, "VALIDATED"),
    MesureMarcheTennis("MATCH_SET_SCORE", "atp", 3, 100802, 0.7167, 0.7288, 0.0316, "VALIDATED"),
    MesureMarcheTennis("MATCH_SET_SCORE", "atp", 5, 2949, 0.8083, 0.8166, 0.0198, "VALIDATED"),
    MesureMarcheTennis("MATCH_SET_SCORE", "wta", 3, 119877, 0.6298, 0.7096, 0.0388, "VALIDATED"),
    # ── aucune compétence : le modèle fait moins bien que la fréquence ───────
    MesureMarcheTennis("TOTAL_SETS(2.5)", "atp", 3, 100802, 0.4853, 0.4575, 0.1192,
                       "REJECTED_NO_SKILL"),
    MesureMarcheTennis("TOTAL_SETS(2.5)", "wta", 3, 119877, 0.4320, 0.4191, 0.0949,
                       "REJECTED_NO_SKILL"),
    MesureMarcheTennis("TOTAL_SETS(3.5)", "atp", 5, 2949, 0.5631, 0.5006, 0.1782,
                       "REJECTED_NO_SKILL"),
    MesureMarcheTennis("TOTAL_SETS(4.5)", "atp", 5, 2949, 0.3550, 0.3200, 0.1334,
                       "REJECTED_NO_SKILL"),
    # ── pire que la moyenne de ligue : l'hypothèse est à remplacer ──────────
    MesureMarcheTennis("TOTAL_GAMES(18.5)", "atp", 3, 100802, 0.4196, 0.4104, 0.0727,
                       "REJECTED_WORSE_THAN_LEAGUE_MEAN"),
    MesureMarcheTennis("TOTAL_GAMES(20.5)", "atp", 3, 100802, 0.5305, 0.4950, 0.1359,
                       "REJECTED_WORSE_THAN_LEAGUE_MEAN"),
    MesureMarcheTennis("TOTAL_GAMES(22.5)", "atp", 3, 100802, 0.5312, 0.4896, 0.1351,
                       "REJECTED_WORSE_THAN_LEAGUE_MEAN"),
    MesureMarcheTennis("TOTAL_GAMES(18.5)", "wta", 3, 119877, 0.5205, 0.4908, 0.1391,
                       "REJECTED_WORSE_THAN_LEAGUE_MEAN"),
    MesureMarcheTennis("TOTAL_GAMES(20.5)", "wta", 3, 119877, 0.5459, 0.4909, 0.1467,
                       "REJECTED_WORSE_THAN_LEAGUE_MEAN"),
    MesureMarcheTennis("TOTAL_GAMES(22.5)", "wta", 3, 119877, 0.4904, 0.4485, 0.0985,
                       "REJECTED_WORSE_THAN_LEAGUE_MEAN"),
    # ── ordonné dans le bon sens, faux en niveau ─────────────────────────────
    MesureMarcheTennis("GAME_HANDICAP(-5.5)", "atp", 3, 100802, 0.3093, 0.3078, 0.0831,
                       "REJECTED_MISCALIBRATED"),
    MesureMarcheTennis("GAME_HANDICAP(-2.5)", "atp", 3, 100802, 0.4824, 0.4847, 0.1133,
                       "REJECTED_MISCALIBRATED"),
    MesureMarcheTennis("GAME_HANDICAP(0.5)", "atp", 3, 100802, 0.4656, 0.4999, 0.0360,
                       "REJECTED_MISCALIBRATED"),
    MesureMarcheTennis("GAME_HANDICAP(2.5)", "atp", 3, 100802, 0.4887, 0.4878, 0.1182,
                       "REJECTED_MISCALIBRATED"),
    MesureMarcheTennis("GAME_HANDICAP(5.5)", "atp", 3, 100802, 0.3181, 0.3157, 0.0871,
                       "REJECTED_MISCALIBRATED"),
    MesureMarcheTennis("GAME_HANDICAP(-5.5)", "wta", 3, 119877, 0.3607, 0.3995, 0.1060,
                       "REJECTED_MISCALIBRATED"),
    MesureMarcheTennis("GAME_HANDICAP(-2.5)", "wta", 3, 119877, 0.4189, 0.4942, 0.1034,
                       "REJECTED_MISCALIBRATED"),
    MesureMarcheTennis("GAME_HANDICAP(0.5)", "wta", 3, 119877, 0.3969, 0.4998, 0.0760,
                       "REJECTED_MISCALIBRATED"),
    MesureMarcheTennis("GAME_HANDICAP(2.5)", "wta", 3, 119877, 0.4176, 0.4932, 0.1074,
                       "REJECTED_MISCALIBRATED"),
    MesureMarcheTennis("GAME_HANDICAP(5.5)", "wta", 3, 119877, 0.3554, 0.3983, 0.1069,
                       "REJECTED_MISCALIBRATED"),
)


def verdicts() -> dict[str, str]:
    """Le verdict de chaque famille, RECALCULÉ depuis les lignes mesurées.

    Une table de verdicts écrite à côté des mesures finit par ne plus les
    décrire : c'est arrivé ici même, où « GAME_HANDICAP rejeté » cohabitait avec
    la seule de ses lignes qui passait.
    """
    return {nom: verdict_de_famille(nom) for nom in FAMILLES}


def famille(cle: str) -> str:
    """« GAME_HANDICAP(-5.5) » -> « GAME_HANDICAP ». La ligne est un paramètre,
    pas une famille."""
    return cle.split("(", 1)[0]


def verdict_de_famille(nom: str) -> str:
    """Le verdict d'une famille, DÉDUIT de ses lignes — jamais déclaré à côté.

    Une famille n'est validée que si TOUTES ses lignes mesurées battent leur
    baseline et passent le seuil de calibration. C'est la règle qui a rattrapé
    une sélection : le `GAME_HANDICAP` ATP à 0,036 d'ECE existe, mais quatre de
    ses cinq lignes dépassent 0,08.
    """
    lignes = [m for m in MESURES if famille(m.marche) == nom]
    if not lignes:
        return "NOT_MEASURED"
    if all(m.bat_la_baseline and m.calibre for m in lignes):
        return "VALIDATED"
    if all(m.bat_la_baseline for m in lignes):
        return "REJECTED_MISCALIBRATED"
    if any(not m.bat_la_baseline for m in lignes):
        return "REJECTED_NO_SKILL"
    return "REJECTED"
