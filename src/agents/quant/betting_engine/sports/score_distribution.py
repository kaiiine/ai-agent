"""Distribution du SCORE — marge et total — pour les sports à points.

L'Elo moneyline répond à « qui gagne », et à rien d'autre. En dériver un écart de
points reviendrait à inventer la quantité qui manque : une probabilité de
victoire de 0,62 est compatible avec un favori qui gagne de deux points en
moyenne avec un grand écart-type, comme avec un favori qui gagne de dix points
avec un petit. Les deux donnent le même moneyline et des `SPREAD` opposés.

CE MODULE MODÉLISE DONC CE QUI EST DEMANDÉ, PAS CE QUI EST DISPONIBLE : des
notes d'ATTAQUE et de DÉFENSE en points, mises à jour séquentiellement, d'où
sortent une marge attendue et un total attendu. Le moneyline existant n'est ni
utilisé, ni modifié, ni concurrencé — il reste la référence de son propre marché.

SANS FUITE PAR CONSTRUCTION. Les notes d'une équipe au moment T ne dépendent que
de ses rencontres STRICTEMENT antérieures, et la dispersion résiduelle aussi.
C'est la même garantie que l'Elo pairwise, obtenue de la même façon : un seul
passage chronologique, prédire puis mettre à jour, jamais l'inverse.

TROIS LOIS CANDIDATES, PARCE QU'AUCUNE NE VA DE SOI. Le basket marque cent
points par équipe et par match, le baseball quatre. Supposer la même loi pour les
deux serait exactement l'hypothèse non vérifiée que ce chantier refuse :

    NORMAL          marge et total gaussiens autour de leur espérance
    POISSON         chaque camp compte des points indépendamment (marge = Skellam)
    NEGBIN          comptage SURDISPERSÉ — variance > moyenne, ce que Poisson
                    interdit et que les données peuvent démontrer

Aucune n'est privilégiée dans le code. Le benchmark tranche, sport par sport, et
sa réponse est parfois « aucune » — c'est un résultat, pas un échec.

CE MODULE NE DÉCIDE RIEN. Il ne promeut aucune maturité, n'écrit aucun seuil, ne
rend aucun verdict. Il produit des probabilités et laisse `build_target_metrics`
et `evaluate_maturity` — ceux du 1X2, inchangés — dire ce qu'elles valent.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import Sequence


@dataclass(frozen=True)
class ScoreParams:
    """Paramètres de MÉTHODE, propres à un sport. Fixes, documentés, jamais fités
    sur l'échantillon d'évaluation."""

    #: Points marqués par équipe et par match, a priori. Sert de point de départ
    #: aux notes ; il est immédiatement corrigé par les premières rencontres.
    baseline_points: float
    #: Pas d'apprentissage des notes attaque/défense, en points par match. Grand,
    #: le modèle suit le bruit ; petit, il oublie qu'une équipe a changé.
    k: float
    #: Avantage du terrain, EN POINTS de marge — jamais en points Elo. C'est la
    #: quantité que le marché du handicap cote, et elle s'observe directement.
    home_edge: float
    #: Sous ce nombre de rencontres antérieures, aucune prédiction. Les notes y
    #: sont dominées par leur valeur initiale : ce ne serait pas une prédiction
    #: faible, ce serait la valeur par défaut déguisée.
    min_prior_games: int
    #: Dispersion résiduelle minimale d'échantillon. En dessous, l'écart-type
    #: mesuré sur trop peu de matchs vaut n'importe quoi.
    min_prior_residuals: int = 30
    notes: str = ""


@dataclass(frozen=True)
class ScoreGame:
    """Une rencontre avec son SCORE — pas seulement son vainqueur."""

    game_id: str
    tipoff: datetime
    home_id: str
    away_id: str
    home_score: int
    away_score: int

    @property
    def margin(self) -> int:
        """Marge du point de vue DOMICILE. Le signe porte l'information : une
        marge en valeur absolue ne dit plus qui a gagné."""
        return self.home_score - self.away_score

    @property
    def total(self) -> int:
        return self.home_score + self.away_score


@dataclass(frozen=True)
class ScorePrediction:
    """Ce que le modèle annonce pour une rencontre, avant qu'elle soit jouée."""

    home_points: float
    away_points: float
    margin_mean: float
    margin_sigma: float
    total_mean: float
    total_sigma: float
    prior_games_home: int
    prior_games_away: int
    n_residuals: int


# ── Notes séquentielles attaque/défense ──────────────────────────────────────

class SequentialScoreRatings:
    """Notes d'attaque et de défense, en POINTS, mises à jour match après match.

    L'écart d'une équipe à la moyenne de la ligue, à l'attaque et à la défense,
    est ce qui reste quand on a retiré le contexte : jouer contre une mauvaise
    défense gonfle les points marqués sans rien dire de l'attaque. La mise à jour
    répartit donc l'erreur de prédiction entre l'attaque de celui qui marque et la
    défense de celui qui encaisse — à parts égales, faute d'une raison mesurée
    d'en privilégier une.

    L'ÉTAT EST CHRONOLOGIQUE. Cette classe se consomme dans l'ordre du calendrier
    et ne sait pas revenir en arrière : c'est ce qui rend l'absence de fuite
    vérifiable à la lecture plutôt que par convention.
    """

    def __init__(self, params: ScoreParams):
        self.params = params
        self.attack: dict[str, float] = {}       # points marqués au-dessus de la moyenne
        self.defense: dict[str, float] = {}      # points encaissés au-dessus de la moyenne
        self.played: Counter = Counter()
        #: Moyenne de ligue COURANTE, réestimée en continu. La figer à une
        #: constante ferait porter aux notes d'équipe la dérive du sport lui-même
        #: — le rythme NBA a bougé de quinze points en dix ans.
        self._somme_points = 0.0
        self._n_scores = 0
        #: Résidus STRICTEMENT antérieurs, pour la dispersion.
        self._residus_marge: list[float] = []
        self._residus_total: list[float] = []

    @property
    def league_mean_points(self) -> float:
        if not self._n_scores:
            return self.params.baseline_points
        return self._somme_points / self._n_scores

    def _attendus(self, home_id: str, away_id: str) -> tuple[float, float]:
        moyenne = self.league_mean_points
        a_dom = self.attack.get(home_id, 0.0)
        d_dom = self.defense.get(home_id, 0.0)
        a_ext = self.attack.get(away_id, 0.0)
        d_ext = self.defense.get(away_id, 0.0)
        # L'avantage du terrain porte sur la MARGE : il en revient donc la moitié
        # à chaque camp, en sens opposé. L'ajouter entier au domicile gonflerait
        # le total autant que la marge, ce qui n'est pas ce qu'on observe.
        return (moyenne + a_dom + d_ext + self.params.home_edge / 2.0,
                moyenne + a_ext + d_dom - self.params.home_edge / 2.0)

    def _sigma(self, residus: list[float]) -> float | None:
        """Écart-type des résidus ANTÉRIEURS, ou rien.

        `None` plutôt qu'une valeur par défaut : sans dispersion mesurée, il n'y a
        pas de distribution — et une distribution supposée est exactement ce
        qu'on refuse de fabriquer.
        """
        if len(residus) < self.params.min_prior_residuals:
            return None
        moyenne = sum(residus) / len(residus)
        variance = sum((r - moyenne) ** 2 for r in residus) / (len(residus) - 1)
        return math.sqrt(variance) if variance > 0 else None

    def predict(self, home_id: str, away_id: str) -> ScorePrediction | None:
        """Prédiction pour cette affiche, ou `None` si l'état ne le permet pas."""
        n_dom, n_ext = self.played[home_id], self.played[away_id]
        if min(n_dom, n_ext) < self.params.min_prior_games:
            return None
        sigma_marge = self._sigma(self._residus_marge)
        sigma_total = self._sigma(self._residus_total)
        if sigma_marge is None or sigma_total is None:
            return None
        dom, ext = self._attendus(home_id, away_id)
        return ScorePrediction(
            home_points=dom, away_points=ext,
            margin_mean=dom - ext, margin_sigma=sigma_marge,
            total_mean=dom + ext, total_sigma=sigma_total,
            prior_games_home=n_dom, prior_games_away=n_ext,
            n_residuals=len(self._residus_marge))

    def update(self, game: ScoreGame) -> None:
        """Intègre une rencontre JOUÉE. Appelé après la prédiction, jamais avant."""
        dom, ext = self._attendus(game.home_id, game.away_id)
        erreur_dom = game.home_score - dom
        erreur_ext = game.away_score - ext

        self._residus_marge.append(game.margin - (dom - ext))
        self._residus_total.append(game.total - (dom + ext))

        k = self.params.k
        self.attack[game.home_id] = self.attack.get(game.home_id, 0.0) + k * erreur_dom / 2
        self.defense[game.away_id] = self.defense.get(game.away_id, 0.0) + k * erreur_dom / 2
        self.attack[game.away_id] = self.attack.get(game.away_id, 0.0) + k * erreur_ext / 2
        self.defense[game.home_id] = self.defense.get(game.home_id, 0.0) + k * erreur_ext / 2

        self.played[game.home_id] += 1
        self.played[game.away_id] += 1
        self._somme_points += game.home_score + game.away_score
        self._n_scores += 2


# ── Lois candidates ──────────────────────────────────────────────────────────

def _phi(x: float) -> float:
    """Fonction de répartition normale centrée réduite."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _poisson_pmf(k: int, lam: float) -> float:
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return math.exp(-lam + k * math.log(lam) - math.lgamma(k + 1))


def _negbin_pmf(k: int, moyenne: float, variance: float) -> float:
    """Loi binomiale négative paramétrée par sa moyenne et sa variance.

    Quand la variance ne dépasse pas la moyenne, la surdispersion n'existe pas et
    la loi dégénère en Poisson — on y retombe explicitement plutôt que de forcer
    un paramètre hors de son domaine.
    """
    if variance <= moyenne:
        return _poisson_pmf(k, moyenne)
    r = moyenne * moyenne / (variance - moyenne)
    p = r / (r + moyenne)
    return math.exp(math.lgamma(k + r) - math.lgamma(r) - math.lgamma(k + 1)
                    + r * math.log(p) + k * math.log(1 - p))


#: Fenêtre de support d'un comptage, en écarts-types autour de son espérance.
#: Six sigmas laissent moins de 10⁻⁸ de masse dehors — sous la précision de tout
#: ce qui suit — et bornent le coût : une convolution sur [0, 4λ+40] coûtait
#: 160 000 produits par rencontre en NBA, soit 660 millions sur le corpus. La
#: masse réellement laissée dehors est MESURÉE et rendue, jamais supposée.
_FENETRE_SIGMAS = 6.0

#: Masse tolérée hors du support retenu. Ce n'est PAS un seuil de décision : c'est
#: la limite de validité numérique de la troncature, comme la masse hors grille du
#: football. Au-delà, on s'abstient plutôt que de pricer une loi renormalisée.
_MASSE_HORS_SUPPORT_MAX = 1e-4


def _fenetre(moyenne: float, variance: float, *, plancher: int = 0) -> range:
    ecart = math.sqrt(max(variance, 1e-9))
    bas = max(plancher, int(math.floor(moyenne - _FENETRE_SIGMAS * ecart)))
    haut = int(math.ceil(moyenne + _FENETRE_SIGMAS * ecart))
    return range(bas, haut + 1)


class _Distribution:
    """La loi d'UNE rencontre, calculée UNE fois et lue autant de fois qu'il y a
    de lignes.

    C'est le même invariant que le football : une rencontre, une distribution, N
    projections. Le recalculer par ligne coûterait autant de convolutions qu'il y
    a de marchés, et — plus grave — ne garantirait plus que le `SPREAD -5,5` et le
    `SPREAD +5,5` de la même rencontre sortent de la même loi.
    """

    def __init__(self, prediction: ScorePrediction):
        self.prediction = prediction
        self.masse_hors_support = 0.0

    def p_marge_superieure(self, ligne: float) -> float:   # pragma: no cover - contrat
        raise NotImplementedError

    def p_total_superieur(self, ligne: float) -> float:    # pragma: no cover - contrat
        raise NotImplementedError

    def p_camp_superieur(self, ligne: float, camp: str) -> float:   # pragma: no cover
        raise NotImplementedError


class _DistributionNormale(_Distribution):
    """Marge et total gaussiens. Aucun support à borner : la forme est analytique."""

    def p_marge_superieure(self, ligne: float) -> float:
        p = self.prediction
        return 1.0 - _phi((ligne - p.margin_mean) / p.margin_sigma)

    def p_total_superieur(self, ligne: float) -> float:
        p = self.prediction
        return 1.0 - _phi((ligne - p.total_mean) / p.total_sigma)

    def p_camp_superieur(self, ligne: float, camp: str) -> float:
        """Total d'UN camp. Sa dispersion n'est pas celle de la somme : deux
        scores indépendants de variance v donnent un total de variance 2v, donc
        l'écart-type d'un camp vaut celui du total divisé par racine de deux.
        L'hypothèse d'indépendance est DÉCLARÉE ici — le benchmark dira si elle
        tient, et sur `TEAM_TOTALS` c'est elle qui est réellement testée."""
        p = self.prediction
        moyenne = p.home_points if camp == "home" else p.away_points
        return 1.0 - _phi((ligne - moyenne) / (p.total_sigma / math.sqrt(2.0)))


class _DistributionComptage(_Distribution):
    """Deux comptages indépendants, convolués une fois pour donner la marge.

    Sous-classée par Poisson et binomiale négative : seules leurs masses
    ponctuelles diffèrent, pas la mécanique.
    """

    def _pmf(self, k: int, moyenne: float, variance: float) -> float:  # pragma: no cover
        raise NotImplementedError

    def _variance_camp(self) -> float:
        return self.prediction.total_sigma ** 2 / 2.0

    def __init__(self, prediction: ScorePrediction):
        super().__init__(prediction)
        v = self._variance_camp()
        self._support_dom = _fenetre(prediction.home_points, v)
        self._support_ext = _fenetre(prediction.away_points, v)
        self._pd = [self._pmf(k, prediction.home_points, v) for k in self._support_dom]
        self._pe = [self._pmf(k, prediction.away_points, v) for k in self._support_ext]
        self.masse_hors_support = max(0.0, 1.0 - min(sum(self._pd), sum(self._pe)))

        # Marge : une seule convolution, dont on garde la fonction de répartition.
        marges: dict[int, float] = {}
        for i, a in enumerate(self._pd):
            x = self._support_dom.start + i
            for j, b in enumerate(self._pe):
                marges[x - (self._support_ext.start + j)] = (
                    marges.get(x - (self._support_ext.start + j), 0.0) + a * b)
        self._marges = sorted(marges.items())

    def p_marge_superieure(self, ligne: float) -> float:
        return sum(p for m, p in self._marges if m > ligne)

    def p_total_superieur(self, ligne: float) -> float:
        p = self.prediction
        variance = p.total_sigma ** 2
        support = _fenetre(p.total_mean, variance)
        return sum(self._pmf(k, p.total_mean, variance) for k in support if k > ligne)

    def p_camp_superieur(self, ligne: float, camp: str) -> float:
        support = self._support_dom if camp == "home" else self._support_ext
        masses = self._pd if camp == "home" else self._pe
        return sum(p for k, p in zip(support, masses) if k > ligne)


class _DistributionPoisson(_DistributionComptage):
    def _pmf(self, k: int, moyenne: float, variance: float) -> float:
        return _poisson_pmf(k, max(moyenne, 0.01))


class _DistributionNegBin(_DistributionComptage):
    def _pmf(self, k: int, moyenne: float, variance: float) -> float:
        return _negbin_pmf(k, max(moyenne, 0.01), variance)


LOIS = {"NORMAL": _DistributionNormale, "POISSON": _DistributionPoisson,
        "NEGBIN": _DistributionNegBin}


# ── Cibles de marché ─────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ScoreTarget:
    """Un marché à évaluer : comment le pricer, comment le régler.

    Les lignes sont des DEMI-LIGNES. Sur une ligne entière, un total ou une marge
    exactement égale à la ligne a un règlement — remboursement — que ce harness
    ne cherche pas à deviner : c'est la même règle que le football, pour la même
    raison, et elle n'est pas ré-argumentée sport par sport.
    """

    key: str
    family: str
    classes: tuple[str, ...]
    parameters: dict = field(default_factory=dict)
    probabilities: object = None          # (distribution) -> dict[str, float]
    settle: object = None                 # (ScoreGame) -> str


def cibles_marge(lignes: Sequence[float]) -> list[ScoreTarget]:
    """`SPREAD(line=L)` : le domicile l'emporte-t-il de PLUS de L points ?

    La convention de signe est celle du marché : une ligne négative est un
    handicap donné au domicile (« -5,5 » = il doit gagner de six points ou plus),
    une ligne positive un handicap reçu.
    """
    cibles = []
    for ligne in lignes:
        cibles.append(ScoreTarget(
            key=f"SPREAD(line={ligne})", family="SPREAD", classes=("home", "away"),
            parameters={"line": ligne},
            probabilities=lambda d, l=ligne: {
                "home": d.p_marge_superieure(l),
                "away": 1.0 - d.p_marge_superieure(l)},
            settle=lambda g, l=ligne: "home" if g.margin > l else "away"))
    return cibles


def cibles_total(lignes: Sequence[float]) -> list[ScoreTarget]:
    cibles = []
    for ligne in lignes:
        cibles.append(ScoreTarget(
            key=f"TOTALS(line={ligne})", family="TOTALS", classes=("over", "under"),
            parameters={"line": ligne},
            probabilities=lambda d, l=ligne: {
                "over": d.p_total_superieur(l),
                "under": 1.0 - d.p_total_superieur(l)},
            settle=lambda g, l=ligne: "over" if g.total > l else "under"))
    return cibles


def cibles_total_equipe(lignes: Sequence[float]) -> list[ScoreTarget]:
    """`TEAM_TOTALS` : le total d'UN camp. Le sujet est le rôle, jamais le nom —
    un total d'équipe attribué au mauvais camp est une prédiction inversée."""
    cibles = []
    for camp in ("home", "away"):
        for ligne in lignes:
            cibles.append(ScoreTarget(
                key=f"TEAM_TOTALS({camp},line={ligne})", family="TEAM_TOTALS",
                classes=("over", "under"), parameters={"line": ligne, "side": camp},
                probabilities=lambda d, l=ligne, c=camp: {
                    "over": d.p_camp_superieur(l, c),
                    "under": 1.0 - d.p_camp_superieur(l, c)},
                settle=lambda g, l=ligne, c=camp: (
                    "over" if (g.home_score if c == "home" else g.away_score) > l else "under")))
    return cibles


# ── Rejeu chronologique ──────────────────────────────────────────────────────

@dataclass
class ScoreTargetRun:
    """Compatible avec `build_target_metrics` du harness multi-marché football :
    mêmes champs, donc mêmes métriques et même verdict de maturité. Réécrire des
    métriques ici autoriserait un jour un basket validé par une porte que le
    football n'a pas franchie."""

    target: ScoreTarget
    predictions: list = field(default_factory=list)
    baseline: list = field(default_factory=list)
    kickoffs: list = field(default_factory=list)
    competitions: list = field(default_factory=list)
    n_void: int = 0


@dataclass(frozen=True)
class ScoreWalkForward:
    runs: dict
    law: str
    n_games: int
    n_predicted: int
    exclusions: dict
    evaluation_start: str
    evaluation_end: str
    #: Erreurs absolues moyennes de la PRÉDICTION PONCTUELLE, avant toute
    #: probabilité. Une loi peut être bien calibrée sur un mauvais centre ; ces
    #: deux nombres disent si le centre lui-même tient.
    mae_margin: float | None = None
    mae_total: float | None = None
    mean_margin_sigma: float | None = None
    mean_total_sigma: float | None = None


def run_score_walk_forward(
    games: Sequence[ScoreGame], *, params: ScoreParams, targets: Sequence[ScoreTarget],
    law: str = "NORMAL", competition_id: str = "",
) -> ScoreWalkForward:
    """Un seul passage chronologique : prédire, puis apprendre. Jamais l'inverse."""
    fabrique = LOIS[law]
    ordonnes = sorted(games, key=lambda g: g.tipoff)
    notes = SequentialScoreRatings(params)
    runs = {c.key: ScoreTargetRun(c) for c in targets}
    exclusions: Counter = Counter()
    erreurs_marge: list[float] = []
    erreurs_total: list[float] = []
    sigmas_marge: list[float] = []
    sigmas_total: list[float] = []
    n_predit = 0
    #: Fréquence des issues ANTÉRIEURES, par cible, tenue à jour au fil de l'eau.
    #: La recalculer sur tout l'historique à chaque match coûterait un temps
    #: quadratique — 172 millions de règlements sur la NBA — pour exactement le
    #: même nombre.
    vues: dict[str, Counter] = {c.key: Counter() for c in targets}
    n_vues = 0

    for game in ordonnes:
        prediction = notes.predict(game.home_id, game.away_id)
        if prediction is None:
            exclusions["INSUFFICIENT_PRIOR_no_ratings_or_dispersion"] += 1
            notes.update(game)
            for cible in targets:
                vues[cible.key][cible.settle(game)] += 1
            n_vues += 1
            continue

        distribution = fabrique(prediction)
        if distribution.masse_hors_support > _MASSE_HORS_SUPPORT_MAX:
            # Une loi dont le support tronqué ne représente plus la masse ne
            # price pas : la renormaliser à l'aveugle fabriquerait des
            # probabilités trop hautes, exactement comme la grille de scores
            # football hors de son domaine.
            exclusions["OUT_OF_SUPPORT_truncation_mass"] += 1
            notes.update(game)
            for cible in targets:
                vues[cible.key][cible.settle(game)] += 1
            n_vues += 1
            continue

        n_predit += 1
        erreurs_marge.append(abs(game.margin - prediction.margin_mean))
        erreurs_total.append(abs(game.total - prediction.total_mean))
        sigmas_marge.append(prediction.margin_sigma)
        sigmas_total.append(prediction.total_sigma)

        for cible in targets:
            reel = cible.settle(game)
            run = runs[cible.key]
            probs = cible.probabilities(distribution)
            run.predictions.append(({c: probs[c] for c in cible.classes}, reel))
            run.kickoffs.append(game.tipoff.isoformat())
            run.competitions.append(competition_id)

            # Baseline POINT-IN-TIME : la fréquence observée avant ce match, pour
            # CETTE cible. Battre une uniforme ne prouve rien sur un marché
            # déséquilibré ; battre la fréquence historique, si.
            if n_vues:
                compte = vues[cible.key]
                run.baseline.append(
                    ({c: compte.get(c, 0) / n_vues for c in cible.classes}, reel))

        notes.update(game)
        for cible in targets:
            vues[cible.key][cible.settle(game)] += 1
        n_vues += 1

    def _moyenne(valeurs):
        return round(sum(valeurs) / len(valeurs), 4) if valeurs else None

    return ScoreWalkForward(
        runs=runs, law=law, n_games=len(ordonnes), n_predicted=n_predit,
        exclusions=dict(exclusions),
        evaluation_start=ordonnes[0].tipoff.isoformat() if ordonnes else "",
        evaluation_end=ordonnes[-1].tipoff.isoformat() if ordonnes else "",
        mae_margin=_moyenne(erreurs_marge), mae_total=_moyenne(erreurs_total),
        mean_margin_sigma=_moyenne(sigmas_marge), mean_total_sigma=_moyenne(sigmas_total))


def lignes_autour(valeur: float, *, pas: float, combien: int) -> list[float]:
    """Demi-lignes réparties autour d'une valeur centrale.

    Évaluer une seule ligne ne dit rien de la forme de la loi : c'est en balayant
    le support qu'on voit si la distribution est trop étroite ou trop large. Le
    centrage vient des DONNÉES (moyenne observée), jamais d'un chiffre rond
    choisi à la main.

    TOUTES LES VALEURS RENDUES SONT DES DEMI-LIGNES, et pas seulement le centre.
    Une ligne entière a un règlement — remboursement sur égalité exacte — que ce
    harness ne cherche pas à deviner ; en valider une reviendrait à mesurer un
    marché dont la règle n'est pas celle qu'on croit.
    """
    def _demi(x: float) -> float:
        return math.floor(x) + 0.5

    centre = _demi(valeur)
    # DÉDOUBLONNÉES : un pas inférieur à un point fait retomber deux échelons sur
    # la même demi-ligne. Deux cibles de même clé écrasaient alors leur run
    # commun, et la population évaluée doublait — un `n` de 16 338 sur un corpus
    # de 8 169 rencontres, avec une baseline à 1,0010 pour le signaler.
    return sorted({_demi(centre + i * pas) for i in range(-combien, combien + 1)})
