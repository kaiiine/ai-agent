"""Ce que les props NFL valent, ligne par ligne — et pourquoi aucune ne price.

Dix familles ont été confrontées à l'historique par la MÊME mécanique que tout le
reste : walk-forward strict, baseline point-in-time, `build_target_metrics`,
seuils de `model_maturity_policy`. Corpus nflverse `player_stats`, 134 470 lignes
joueur-semaine, 1999-2024, CC-BY-4.0.

LA VALIDATION EST PAR LIGNE, comme pour les Plus/Moins football. Ce n'est pas un
choix de commodité : les lignes échouent RÉELLEMENT de façon différente, et le
motif est régulier — la calibration se dégrade PRÈS DE LA MÉDIANE et s'améliore
dans les queues.

    PASSING_YARDS   ECE 0,040 à 149,5 · 0,069 à 199,5 · 0,064 à 249,5 · 0,034 à 299,5
                    médiane observée : 208 yards

L'explication tient à la forme du problème : autour de la médiane, la loi est à
son plus raide, et une petite erreur sur la moyenne s'y traduit par une grande
erreur de probabilité. Loin de la médiane, la même erreur de moyenne ne déplace
presque rien. Ce n'est donc pas le modèle qui « marche mieux » aux extrêmes : ce
sont les extrêmes qui pardonnent. Et c'est précisément la région médiane que le
bookmaker cote.

TROIS FAMILLES NE BATTENT PAS LEUR BASELINE, et toutes trois comptent des
TOUCHDOWNS ou des INTERCEPTIONS :

    INTERCEPTIONS   −0,027 et −0,020 de Brier — le modèle fait pire que la
                    fréquence historique
    RUSHING_TDS     +0,016 à 0,5 mais −0,0002 à 1,5
    RECEIVING_TDS   −0,008 et −0,003

Rien d'étonnant : un touchdown est un événement rare dont le taux dépend de la
position sur le terrain et de la séquence de jeu, pas du volume récent du joueur.
Une moyenne exponentielle de touchdowns mesure surtout du bruit. Les VOLUMES
(yards, tentatives, réceptions), eux, sont fortement auto-corrélés — d'où des
gains de Brier jusqu'à +0,216.

AUCUNE DE CES LIGNES NE PRICE AUJOURD'HUI, et c'est le résultat principal.
Mesuré le 2026-08-15 sur le catalogue Winamax : 16 événements NFL, `moreBets`
entre 63 et 65, 514 marchés lus sur 8 rencontres — et ZÉRO prop de joueur. La
saison ouvre le 10 septembre ; le bookmaker n'a pas encore ouvert ces marchés.
Un modèle validé pour un marché qui n'existe pas ne couvre rien.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Instant de la mesure. Le marché NFL est saisonnier : « zéro prop » est une
#: observation DATÉE, pas une propriété du bookmaker.
MESURE_LE = "2026-08-15"

#: Ce que le catalogue offrait au moment de la mesure.
MARCHE_OBSERVE = {
    "evenements_nfl": 16,
    "evenements_detailles": 8,
    "marches_lus": 514,
    "props_observees": 0,
    "more_bets_declare": "63 à 65 par rencontre",
    "ouverture_saison": "2026-09-10",
}


@dataclass(frozen=True)
class MesureProp:
    """Une ligne de prop, telle que le walk-forward l'a rendue."""

    famille: str
    ligne: float
    loi: str
    n_eval: int
    brier: float
    baseline: float
    ece: float

    @property
    def bat_la_baseline(self) -> bool:
        return self.brier < self.baseline

    @property
    def calibre(self) -> bool:
        """Seuil LU dans la politique de maturité — jamais choisi ici."""
        from ...maturity import load_maturity_policy
        return self.ece <= load_maturity_policy().criteria["max_calibration_error"]

    @property
    def validee(self) -> bool:
        return self.bat_la_baseline and self.calibre


MESURES: tuple[MesureProp, ...] = (
    MesureProp("PASSING_YARDS", 149.5, "NORMAL", 14696, 0.3039, 0.3798, 0.0395),
    MesureProp("PASSING_YARDS", 199.5, "NORMAL", 14696, 0.4223, 0.4912, 0.0686),
    MesureProp("PASSING_YARDS", 249.5, "NORMAL", 14696, 0.4133, 0.4547, 0.0638),
    MesureProp("PASSING_YARDS", 299.5, "NORMAL", 14696, 0.2742, 0.2857, 0.0335),
    MesureProp("PASSING_ATTEMPTS", 24.5, "NEGBIN", 14696, 0.3428, 0.4024, 0.0484),
    MesureProp("PASSING_ATTEMPTS", 29.5, "NEGBIN", 14696, 0.4501, 0.4941, 0.0807),
    MesureProp("PASSING_ATTEMPTS", 34.5, "NEGBIN", 14696, 0.4335, 0.4599, 0.0727),
    MesureProp("PASSING_ATTEMPTS", 39.5, "NEGBIN", 14696, 0.2996, 0.3075, 0.0298),
    MesureProp("PASSING_TDS", 0.5, "NEGBIN", 14696, 0.3882, 0.4278, 0.0236),
    MesureProp("PASSING_TDS", 1.5, "NEGBIN", 14696, 0.4385, 0.4696, 0.0552),
    MesureProp("PASSING_TDS", 2.5, "NEGBIN", 14696, 0.2433, 0.2512, 0.0299),
    MesureProp("INTERCEPTIONS", 0.5, "NEGBIN", 14696, 0.5269, 0.5003, 0.1133),
    MesureProp("INTERCEPTIONS", 1.5, "NEGBIN", 14696, 0.3352, 0.3149, 0.0744),
    MesureProp("RUSHING_YARDS", 29.5, "NORMAL", 44461, 0.2861, 0.4663, 0.0390),
    MesureProp("RUSHING_YARDS", 49.5, "NORMAL", 44461, 0.2410, 0.3614, 0.0327),
    MesureProp("RUSHING_YARDS", 69.5, "NORMAL", 44461, 0.1894, 0.2464, 0.0263),
    MesureProp("RUSHING_YARDS", 89.5, "NORMAL", 44461, 0.1350, 0.1566, 0.0188),
    MesureProp("RUSHING_ATTEMPTS", 9.5, "NEGBIN", 29765, 0.2777, 0.4939, 0.0336),
    MesureProp("RUSHING_ATTEMPTS", 14.5, "NEGBIN", 29765, 0.2625, 0.3918, 0.0363),
    MesureProp("RUSHING_ATTEMPTS", 19.5, "NEGBIN", 29765, 0.1835, 0.2308, 0.0231),
    MesureProp("RUSHING_TDS", 0.5, "NEGBIN", 29765, 0.3364, 0.3528, 0.0427),
    MesureProp("RUSHING_TDS", 1.5, "NEGBIN", 29765, 0.0917, 0.0915, 0.0221),
    MesureProp("RECEIVING_YARDS", 29.5, "NORMAL", 95802, 0.3673, 0.4768, 0.0553),
    MesureProp("RECEIVING_YARDS", 49.5, "NORMAL", 95802, 0.2805, 0.3508, 0.0409),
    MesureProp("RECEIVING_YARDS", 69.5, "NORMAL", 95802, 0.1908, 0.2221, 0.0286),
    MesureProp("RECEIVING_YARDS", 89.5, "NORMAL", 95802, 0.1169, 0.1271, 0.0202),
    MesureProp("RECEPTIONS", 2.5, "NEGBIN", 95802, 0.3722, 0.4927, 0.0337),
    MesureProp("RECEPTIONS", 3.5, "NEGBIN", 95802, 0.3212, 0.4209, 0.0263),
    MesureProp("RECEPTIONS", 4.5, "NEGBIN", 95802, 0.2531, 0.3172, 0.0193),
    MesureProp("RECEPTIONS", 5.5, "NEGBIN", 95802, 0.1823, 0.2167, 0.0110),
    MesureProp("RECEPTIONS", 6.5, "NEGBIN", 95802, 0.1223, 0.1387, 0.0106),
    MesureProp("RECEIVING_TDS", 0.5, "NEGBIN", 66031, 0.3448, 0.3372, 0.0612),
    MesureProp("RECEIVING_TDS", 1.5, "NEGBIN", 66031, 0.0582, 0.0556, 0.0126),
)

#: Ce qui bloque la mise en production. Le modèle n'y est pour rien.
STOP_MARCHE = (
    "STOP EXTERNAL — le marché n'existe pas encore. 16 événements NFL au "
    f"catalogue le {MESURE_LE}, 514 marchés lus sur 8 rencontres, ZÉRO prop de "
    "joueur. Winamax ouvre ces marchés à l'approche de la saison "
    f"({MARCHE_OBSERVE['ouverture_saison']}). Les modèles sont validés et "
    "attendent leur marché — l'inverse exact du basket, qui a 545 props par "
    "rencontre et aucune donnée."
)


def lignes_validees(famille: str | None = None) -> tuple[MesureProp, ...]:
    """Les lignes qui battent leur baseline ET passent le seuil de calibration."""
    return tuple(m for m in MESURES if m.validee
                 and (famille is None or m.famille == famille))


def familles() -> tuple[str, ...]:
    vues: list[str] = []
    for m in MESURES:
        if m.famille not in vues:
            vues.append(m.famille)
    return tuple(vues)


def resume_par_famille() -> dict:
    """Par famille : lignes mesurées, lignes validées, et le motif dominant."""
    sortie = {}
    for nom in familles():
        lignes = [m for m in MESURES if m.famille == nom]
        validees = [m for m in lignes if m.validee]
        sans_competence = [m for m in lignes if not m.bat_la_baseline]
        mal_calibrees = [m for m in lignes if m.bat_la_baseline and not m.calibre]
        sortie[nom] = {
            "lignes_mesurees": len(lignes),
            "lignes_validees": len(validees),
            "sans_competence": len(sans_competence),
            "mal_calibrees": len(mal_calibrees),
            "loi": lignes[0].loi,
            "n_eval": lignes[0].n_eval,
        }
    return sortie
