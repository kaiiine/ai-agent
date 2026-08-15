"""Le verdict du benchmark cold-start, figé.

Ce module est un RÉSULTAT, pas une configuration : rien dans le chemin live ne le
lit. Le report BRUT (candidat B) a été branché dans `gateway.recent_form` après
décision explicite ; ce fichier garde la mesure qui l'a justifié, et l'écart avec
le candidat que le benchmark préférait.

CE QUI A ÉTÉ MESURÉ. Sept championnats, deux ouvertures de saison. Les
paramètres de C et D ont été choisis sur l'ouverture 2024 (report 2023) et
mesurés sur l'ouverture 2025 (report 2024) — 679 rencontres rejouées, journées 1
à 10, point-in-time strict.

LE FAIT PRINCIPAL TIENT EN UNE LIGNE : à la première journée, le candidat A —
la production d'aujourd'hui — n'évalue AUCUNE rencontre. Zéro sur quarante-sept.
Le report en évalue quarante-sept sur quarante-sept, avec une qualité de données
de 1,000 contre 0,500.

    fenêtre   A n_eval   B/C n_eval   A qualité   B/C qualité
    J1              0           47       0,500        1,000
    J1-J5         268          317       0,500        0,931
    J1-J10        610          659       0,778        0,967

L'ATTRIBUTION EST FAITE, et elle importe : le candidat C change DEUX choses par
rapport à A — le report ET la pondération. Une ablation les sépare, sur le
holdout, à paramètre fixé :

    A -> A+   pondération seule, sans report   +0,0012  [-0,0001, +0,0025]  J1-J5
    A -> B    report seul                      +0,0227  [+0,0113, +0,0346]  J1-J5
    A+ -> C   report, pondération constante    +0,0293  [+0,0143, +0,0440]  J1-J5
    B -> C    pondération seule, avec report   +0,0087  [+0,0049, +0,0127]  J1-J5

Le report porte l'essentiel. La pondération n'apporte quelque chose QU'EN
PRÉSENCE du report — ce qui se comprend : sans report, il n'y a presque rien à
pondérer.

LA DEMI-VIE RETENUE N'EST PAS IDENTIFIÉE, et il faut le dire. Sur la validation,
le Brier décroît de façon monotone quand la demi-vie s'allonge (0,6330 à 30 j
jusqu'à 0,6104 à 1 460 j) : l'optimum sort au bord de la grille. Concrètement,
« C » ne décrit pas une décroissance forte mais une pondération QUASI UNIFORME
sur les dix derniers matchs, là où la production décroît avec le RANG. Toute
demi-vie supérieure à un an donnerait le même modèle.

D EST EXACTEMENT B. Son paramètre optimal sur la validation est 12, c'est-à-dire
la valeur de production du shrinkage : le renforcement du prior avec l'âge de la
preuve DÉGRADE le Brier de façon monotone (0,6139 à k=12 jusqu'à 0,6214 à k=48).
Ses chiffres de holdout sont bit-identiques à ceux de B, ce qui vérifie au
passage que le banc ne fabrique rien.

LA CALIBRATION NE S'EFFONDRE PAS. C'était le risque : gagner de la couverture en
perdant la justesse des niveaux. Le calibrateur EXISTANT (histogram binning),
ajusté sur 2024 et appliqué à 2025 :

    candidat   ECE brut J1-J10   ECE calibré   Brier brut   Brier calibré
    A                   0,0149        0,0272       0,6309         0,6356
    B                   0,0236        0,0201       0,6179         0,6176
    C                   0,0223        0,0185       0,6111         0,6135

Brut, A affiche la meilleure ECE — mais pour une raison qui ne lui fait pas
honneur : ne disposant d'aucune information, il prédit près du taux de base, et
une prédiction qui ne discrimine pas peut difficilement être mal calibrée. Son
avantage sur la fréquence historique le montre : +0,0127 de Brier pour A contre
+0,0427 pour C. Après calibration, C domine sur les DEUX axes.

PROMUS. Un club promu n'a aucun match de saison N-1 dans le fichier de sa
nouvelle ligue : le report ne lui donne rien et il retombe sur le comportement A.
Aucun transfert inter-compétition n'est tenté, et aucun ne pourrait l'être — les
divisions inférieures dont viennent ces clubs ne sont pas dans le corpus, donc le
rapport d'échelle entre elles n'est pas mesurable. Le refus est structurel.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Conclusions admissibles. Le benchmark en choisit une ; l'architecture n'a pas
#: son mot à dire.
KEEP_CURRENT_SEASON_ONLY = "KEEP_CURRENT_SEASON_ONLY"
USE_RAW_CARRY_OVER = "USE_RAW_CARRY_OVER"
USE_DECAYED_CARRY_OVER = "USE_DECAYED_CARRY_OVER"
USE_TRANSITION_POLICY = "USE_TRANSITION_POLICY"
NO_METHOD_PROVEN = "NO_METHOD_PROVEN"

#: Ce que le BENCHMARK recommande, sur les seuls chiffres.
RECOMMANDATION_DU_BENCHMARK = USE_DECAYED_CARRY_OVER

#: Ce qui a été DÉCIDÉ, et branché. Les deux ne coïncident pas, et la raison
#: n'est pas que C serait moins bon — il est meilleur sur toutes les fenêtres.
#: C'est que sa demi-vie n'est PAS IDENTIFIÉE : le gain continue jusqu'au bord de
#: la grille, et toute valeur suffisamment grande produit le même comportement.
#: Inscrire une demi-vie précise dans le chemin argent donnerait l'apparence d'un
#: paramètre estimé alors qu'il ne l'est pas. B capture l'essentiel du gain sans
#: aucun paramètre : c'est la solution minimale démontrée.
DECISION = USE_RAW_CARRY_OVER
CONCLUSION = DECISION

#: Classement du candidat C — résultat de recherche, pas dette immédiate. Il se
#: rouvre le jour où plusieurs ouvertures de saison supplémentaires permettront
#: d'estimer réellement une décroissance plutôt que d'en constater l'absence.
STATUT_CANDIDAT_C = "STATISTICALLY PROMISING / PARAMETER NOT IDENTIFIED"

#: Ce que la DÉCISION laisse sur la table, mesuré : l'écart entre B et C.
COUT_DE_LA_DECISION = {
    "J1-J5": 0.0087,       # ΔBrier apparié B -> C, IC [+0,0049, +0,0127]
    "J6-J10": 0.0050,      # IC [+0,0004, +0,0095]
    "J1-J10": 0.0068,      # IC [+0,0038, +0,0098]
}

#: Pourquoi PAS `USE_TRANSITION_POLICY`. Un calendrier de transition supposerait
#: qu'à partir d'une certaine journée le report devient nuisible. Mesuré, il ne
#: le devient jamais : C bat A sur J1-J5 (+0,0293) ET sur J6-J10 (+0,0044), et
#: bat B sur les deux fenêtres. Rien dans les données ne justifie de basculer.
POURQUOI_PAS_DE_CALENDRIER = (
    "Aucune journée où le report dégrade. C bat A sur J1-J5 et sur J6-J10 ; "
    "un calendrier de bascule serait de la complexité sans preuve."
)


@dataclass(frozen=True)
class MesureFenetre:
    """Une ligne du holdout, telle qu'elle a été mesurée."""

    candidat: str
    fenetre: str
    n_eval: int
    couverture: float
    data_quality: float
    brier: float
    log_loss: float
    ece: float
    baseline_frequence: float
    #: Écart de Brier APPARIÉ contre A, sur les seuls matchs communs. `None`
    #: quand A n'évalue rien — et c'est alors l'information principale.
    delta_brier_vs_a: float | None = None
    ic_bas: float | None = None
    ic_haut: float | None = None
    n_communs: int = 0

    @property
    def significatif(self) -> bool:
        """L'intervalle de confiance exclut-il zéro ?"""
        return (self.ic_bas is not None and self.ic_haut is not None
                and (self.ic_bas > 0 or self.ic_haut < 0))


HOLDOUT: tuple[MesureFenetre, ...] = (
    MesureFenetre("A", "J1", 0, 0.0, 0.500, 0.0, 0.0, 0.0, 0.6316),
    MesureFenetre("A", "J2", 66, 0.9706, 0.500, 0.6349, 1.0534, 0.0267, 0.6403),
    MesureFenetre("A", "J3", 64, 1.0, 0.500, 0.6163, 1.0278, 0.0384, 0.6404),
    MesureFenetre("A", "J4", 69, 1.0, 0.500, 0.6658, 1.0991, 0.0787, 0.6575),
    MesureFenetre("A", "J5", 69, 1.0, 0.500, 0.6326, 1.0479, 0.0211, 0.6630),
    MesureFenetre("A", "J1-J5", 268, 0.8454, 0.500, 0.6379, 1.0576, 0.0118, 0.6506),
    MesureFenetre("A", "J6-J10", 342, 1.0, 0.996, 0.6255, 1.0401, 0.0229, 0.6594),
    MesureFenetre("A", "J1-J10", 610, 0.9256, 0.778, 0.6309, 1.0478, 0.0149, 0.6555),

    MesureFenetre("B", "J1", 47, 1.0, 1.000, 0.6123, 1.0231, 0.0610, 0.6316,
                  None, None, None, 0),
    MesureFenetre("B", "J2", 68, 1.0, 0.919, 0.5970, 1.0036, 0.0726, 0.6445,
                  0.0380, 0.0121, 0.0658, 66),
    MesureFenetre("B", "J3", 64, 1.0, 0.914, 0.5929, 0.9957, 0.0514, 0.6404,
                  0.0234, 0.0003, 0.0453, 64),
    MesureFenetre("B", "J4", 69, 1.0, 0.924, 0.6462, 1.0752, 0.0515, 0.6575,
                  0.0197, -0.0035, 0.0425, 69),
    MesureFenetre("B", "J5", 69, 1.0, 0.917, 0.6223, 1.0324, 0.0311, 0.6630,
                  0.0103, -0.0069, 0.0271, 69),
    MesureFenetre("B", "J1-J5", 317, 1.0, 0.931, 0.6147, 1.0268, 0.0385, 0.6486,
                  0.0227, 0.0113, 0.0346, 268),
    MesureFenetre("B", "J6-J10", 342, 1.0, 1.000, 0.6209, 1.0336, 0.0292, 0.6594,
                  0.0045, -0.0005, 0.0096, 342),
    MesureFenetre("B", "J1-J10", 659, 1.0, 0.967, 0.6179, 1.0303, 0.0236, 0.6542,
                  0.0125, 0.0069, 0.0185, 610),

    MesureFenetre("C", "J1", 47, 1.0, 1.000, 0.6000, 1.0053, 0.0629, 0.6316,
                  None, None, None, 0),
    MesureFenetre("C", "J2", 68, 1.0, 0.919, 0.5864, 0.9900, 0.0764, 0.6445,
                  0.0474, 0.0160, 0.0797, 66),
    MesureFenetre("C", "J3", 64, 1.0, 0.914, 0.5871, 0.9872, 0.0576, 0.6404,
                  0.0293, -0.0016, 0.0584, 64),
    MesureFenetre("C", "J4", 69, 1.0, 0.924, 0.6373, 1.0659, 0.0560, 0.6575,
                  0.0285, -0.0029, 0.0590, 69),
    MesureFenetre("C", "J5", 69, 1.0, 0.917, 0.6153, 1.0217, 0.0186, 0.6630,
                  0.0174, -0.0080, 0.0418, 69),
    MesureFenetre("C", "J1-J5", 317, 1.0, 0.931, 0.6059, 1.0151, 0.0358, 0.6486,
                  0.0305, 0.0155, 0.0453, 268),
    MesureFenetre("C", "J6-J10", 342, 1.0, 1.000, 0.6159, 1.0258, 0.0390, 0.6594,
                  0.0095, 0.0010, 0.0182, 342),
    MesureFenetre("C", "J1-J10", 659, 1.0, 0.967, 0.6111, 1.0207, 0.0223, 0.6542,
                  0.0187, 0.0107, 0.0274, 610),
)

#: Ablation sur le holdout, à paramètre fixé. `A+` = saison N seule avec la
#: pondération de C : il isole l'effet de la pondération de celui du report.
ABLATION: dict[str, dict] = {
    "A->A+": {"J1-J5": (0.0012, -0.0001, 0.0025),
              "J6-J10": (0.0052, 0.0017, 0.0084),
              "J1-J10": (0.0034, 0.0015, 0.0054)},
    "A->B": {"J1-J5": (0.0227, 0.0113, 0.0346),
             "J6-J10": (0.0045, -0.0005, 0.0096),
             "J1-J10": (0.0125, 0.0069, 0.0185)},
    "A+->C": {"J1-J5": (0.0293, 0.0143, 0.0440),
              "J6-J10": (0.0044, -0.0033, 0.0123),
              "J1-J10": (0.0153, 0.0075, 0.0232)},
    "B->C": {"J1-J5": (0.0087, 0.0049, 0.0127),
             "J6-J10": (0.0050, 0.0004, 0.0095),
             "J1-J10": (0.0068, 0.0038, 0.0098)},
}

#: Calibrateur EXISTANT ajusté sur 2024, appliqué à 2025. (ECE brut, ECE calibré,
#: Brier brut, Brier calibré) sur J1-J10.
CALIBRATION: dict[str, tuple[float, float, float, float]] = {
    "A": (0.0149, 0.0272, 0.6309, 0.6356),
    "B": (0.0236, 0.0201, 0.6179, 0.6176),
    "C": (0.0223, 0.0185, 0.6111, 0.6135),
}

#: Promus contre équipes stables, fenêtre J1-J5 du holdout.
#: (n, Brier, ECE, data_quality)
PROMUS: dict[str, dict[str, tuple[int, float, float, float]]] = {
    "A": {"stables": (189, 0.6369, 0.0116, 0.500),
          "promu_implique": (79, 0.6403, 0.0209, 0.500)},
    "B": {"stables": (238, 0.6102, 0.0407, 1.000),
          "promu_implique": (79, 0.6280, 0.0342, 0.722)},
    "C": {"stables": (238, 0.5997, 0.0392, 1.000),
          "promu_implique": (79, 0.6247, 0.0354, 0.722)},
}

#: Verdict de transférabilité demandé au §6.
VERDICT_PROMUS = "INSUFFICIENT_EVIDENCE"
MOTIF_PROMUS = (
    "Aucun club promu ne reçoit de force reportée : ses rencontres de saison N-1 "
    "se sont jouées dans une division absente du corpus. Mesurer un rapport "
    "d'échelle inter-division demanderait les deux côtés de la promotion, et "
    "AXON n'a que le côté supérieur. Le report leur est donc structurellement "
    "impossible, pas refusé par précaution — et les rencontres qui les "
    "impliquent restent évaluées, parce que leur ADVERSAIRE, lui, est reporté "
    "(Brier 0,6403 en A contre 0,6247 en C)."
)

#: Ce que le report ne mesure PAS, et qu'on ne prétend pas mesurer.
RISQUES_RESTANTS = (
    "Le renouvellement d'effectif n'est pas modélisé : le corpus ne contient "
    "aucune donnée joueur pour les championnats concernés. Le report suppose "
    "donc qu'une équipe reste comparable à elle-même d'une saison à l'autre, ce "
    "qui est FAUX pour celles qui changent beaucoup — et rien ici ne permet de "
    "les distinguer.",
    "La demi-vie retenue n'est pas identifiée : toute valeur supérieure à un an "
    "donne le même modèle. Le paramètre est donc à considérer comme « pondération "
    "quasi uniforme », pas comme une constante estimée.",
    "Deux ouvertures de saison seulement, 679 rencontres. Les écarts par journée "
    "reposent sur ~65 matchs et leurs intervalles se chevauchent largement ; "
    "seules les fenêtres agrégées tranchent.",
    "Le classement servant de proxy d'adversaire est reconstruit sur le pool "
    "reporté : au début de la saison N, c'est le classement final de N-1. C'est "
    "un choix défendable et il n'a pas été comparé à une alternative.",
)


def mesure(candidat: str, fenetre: str) -> MesureFenetre | None:
    return next((m for m in HOLDOUT
                 if m.candidat == candidat and m.fenetre == fenetre), None)


def gain_de_couverture(fenetre: str) -> int:
    """Rencontres rendues évaluables par le report, sur cette fenêtre."""
    a, c = mesure("A", fenetre), mesure("C", fenetre)
    return (c.n_eval - a.n_eval) if a and c else 0
