"""Cold-start football : faut-il reporter la saison N-1 sur les premières journées ?

LE PROBLÈME, MESURÉ. Le modèle football ne regarde que la saison en cours. À la
première journée, aucune équipe n'a d'historique : les forces valent leur
initialisation, tirées vers la moyenne de la ligue, et `data_quality` tombe à
0,500. Constaté en production le 15 août 2026 — Rio Ave donné à 54,6 % contre le
FC Porto, coté 6,25. Le garde de qualité a fait son travail, mais le résultat est
que le football n'est évaluable qu'à partir d'octobre.

CE BANC NE TOUCHE À RIEN. Il ne modifie aucune probabilité live, aucun seuil,
aucune maturité, aucun store. Il consomme le MÊME constructeur de features, le
MÊME modèle et les MÊMES métriques que la production ; seule la POPULATION de
matchs servie à la gateway point-in-time change. C'est ce qui rend la comparaison
honnête : quatre candidats, un seul code.

LES QUATRE CANDIDATS

    A  saison N seule                 la baseline actuelle
    B  report brut N-1 + N            la gateway voit les deux saisons
    C  report à décroissance          même population, poids par ANCIENNETÉ
                                      calendaire au lieu du rang
    D  report shrinké vers la ligue   même population, `shrinkage_k` renforcé
                                      quand la preuve est vieille

A et B ne demandent AUCUN paramètre. C et D en demandent un chacun, et ce
paramètre est choisi sur une cohorte de VALIDATION antérieure — jamais sur le
holdout final.

LA SÉPARATION TEMPORELLE EST LA GARANTIE PRINCIPALE

    validation   ouverture de la saison 2024, avec 2023 comme N-1
    holdout      ouverture de la saison 2025, avec 2024 comme N-1

Un paramètre choisi sur 2024 et évalué sur 2025 ne peut pas avoir vu son propre
jeu d'évaluation. C'est la même discipline que le walk-forward : ce qui décide
précède toujours ce qui est mesuré.

PROMOTIONS. Un club promu n'a AUCUN match de saison N-1 dans le fichier de sa
nouvelle ligue — le report ne lui donne donc rien, et il retombe de lui-même sur
le comportement A. Aucun transfert inter-compétition n'est tenté : les échelles
de deux divisions ne sont pas les mêmes, et rien dans le corpus ne permet de
mesurer leur rapport. Le refus est structurel, pas déclaratif.
"""

from __future__ import annotations

import math
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Sequence

from src.agents.quant.betting_engine.calibration import metrics
from src.agents.quant.betting_engine.calibration.point_in_time_gateway import PointInTimeGateway
from src.agents.quant.betting_engine.core.canonical_event import (
    CanonicalEvent,
    CanonicalParticipant,
)
from src.agents.quant.betting_engine.core.market_model import DataReadiness
from src.agents.quant.betting_engine.sports.football.market_models.one_x_two import OneXTwoModel
from src.agents.quant.gateway.sports.football.canonical_facts import CanonicalMatch

_CLASSES = ("home", "draw", "away")

#: Les sept championnats onboardés, avec leur préfixe de fixture. Chaque paire de
#: saisons consécutives donne une ouverture de saison mesurable.
LIGUES: dict[str, str] = {
    "fl1": "competition:football:fra:ligue1",
    "sa": "competition:football:ita:serie_a",
    "pd": "competition:football:esp:laliga",
    "bl1": "competition:football:deu:bundesliga",
    "elc": "competition:football:eng:championship",
    "ded": "competition:football:nld:eredivisie",
    "ppl": "competition:football:prt:primeira_liga",
}

#: (saison évaluée, saison de report). La première sert à CHOISIR les paramètres
#: de C et D, la seconde à les MESURER — jamais l'inverse.
COHORTE_VALIDATION = ("2024", "2023")
COHORTE_HOLDOUT = ("2025", "2024")


def _issue(match: CanonicalMatch) -> str:
    if match.goals_home > match.goals_away:
        return "home"
    if match.goals_away > match.goals_home:
        return "away"
    return "draw"


# ── Candidats ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Candidat:
    """Une façon de construire les features. Rien d'autre ne change."""

    nom: str
    #: Le report de la saison précédente est-il servi à la gateway ?
    reporte: bool
    #: Pondération d'un match de la forme. `None` = celle de production, qui
    #: décroît avec le RANG. Une fonction reçoit `(rang, match, cutoff)`.
    poids: Callable[[int, dict, datetime], float] | None = None
    #: Force du prior ligue, en équivalent-matchs. `None` = valeur de production.
    #: Une fonction reçoit l'âge moyen de la preuve, en jours.
    shrinkage: Callable[[float], float] | None = None
    parametre: float | None = None
    description: str = ""


def _age_jours(match: dict, cutoff: datetime) -> float:
    """Ancienneté d'un match de forme, en jours. `date` est une chaîne ISO."""
    try:
        jour = datetime.fromisoformat(str(match["date"])).date()
    except (TypeError, ValueError, KeyError):
        return 0.0
    return max(0.0, (cutoff.date() - jour).days)


def candidat_a() -> Candidat:
    return Candidat("A", reporte=False,
                    description="saison N seule — baseline actuelle")


def candidat_b() -> Candidat:
    return Candidat("B", reporte=True,
                    description="report brut N-1 + N, pondération de production")


def candidat_c(demi_vie_jours: float) -> Candidat:
    """Décroissance par ANCIENNETÉ CALENDAIRE.

    MOTIVATION, et elle est structurelle : la pondération de production décroît
    avec le RANG du match dans la forme. Tant qu'on ne lit qu'une saison, rang et
    ancienneté vont de pair. Dès qu'on reporte la saison précédente, ils
    divergent complètement — le dixième match de la forme peut dater de mai
    dernier ou de la semaine passée, et le rang ne fait pas la différence. Une
    demi-vie en jours est la forme minimale qui rétablit cette distinction.
    """
    lam = math.log(2.0) / demi_vie_jours
    return Candidat(
        "C", reporte=True, parametre=demi_vie_jours,
        poids=lambda i, m, cutoff: math.exp(-lam * _age_jours(m, cutoff)),
        description=f"report à décroissance calendaire, demi-vie {demi_vie_jours:.0f} j")


def candidat_d(k_max: float) -> Candidat:
    """Prior ligue renforcé quand la preuve est vieille.

    MOTIVATION : le shrinkage existe DÉJÀ dans l'architecture — il tire les
    forces vers 1,0 selon la taille d'échantillon. Ce candidat n'en invente donc
    pas un ; il rend sa force fonction de l'ÂGE de la preuve plutôt que du seul
    effectif. Une force bâtie sur des matchs vieux de dix mois mérite d'être plus
    proche de la moyenne de ligue qu'une force bâtie sur les cinq derniers.

    L'interpolation est linéaire entre la valeur de production (preuve fraîche) et
    `k_max` (preuve d'un an). Une forme plus riche ne se justifierait pas : on
    n'a que deux points d'ancrage mesurables.
    """
    from src.agents.quant.dixon_coles import DEFAULT_SHRINKAGE_K

    def shrinkage(age_moyen: float) -> float:
        part = min(1.0, max(0.0, age_moyen / 365.0))
        return DEFAULT_SHRINKAGE_K + part * (k_max - DEFAULT_SHRINKAGE_K)

    return Candidat("D", reporte=True, parametre=k_max, shrinkage=shrinkage,
                    description=f"report shrinké vers la ligue, k jusqu'à {k_max:.0f}")


# ── Construction des features, un seul chemin ────────────────────────────────

def _features_du_candidat(candidat: Candidat, event, gateway, cutoff: datetime):
    """Le MÊME `build_event_feature_set` que la production, avec la pondération
    du candidat. Aucune copie du constructeur de features."""
    from src.agents.quant.betting_engine.sports.football.feature_engineering import (
        event_features as fe,
    )

    if candidat.poids is None and candidat.shrinkage is None:
        return fe.build_event_feature_set(event, gateway=gateway, as_of=cutoff)

    # Le constructeur appelle `team_strengths` ; on lui substitue une version
    # partielle portant les réglages du candidat, le temps de l'appel. C'est le
    # même code de force, avec d'autres poids — jamais une seconde formule.
    import src.agents.quant.dixon_coles as dc

    original = fe.team_strengths

    def strengths(form, opponent_ratings=None, shrinkage_k=dc.DEFAULT_SHRINKAGE_K):
        poids = None
        if candidat.poids is not None:
            poids = lambda i, m: candidat.poids(i, m, cutoff)   # noqa: E731
        k = shrinkage_k
        if candidat.shrinkage is not None and form:
            age_moyen = statistics.mean(_age_jours(m, cutoff) for m in form)
            k = candidat.shrinkage(age_moyen)
        return original(form, opponent_ratings=opponent_ratings, shrinkage_k=k, poids=poids)

    fe.team_strengths = strengths
    try:
        return fe.build_event_feature_set(event, gateway=gateway, as_of=cutoff)
    finally:
        fe.team_strengths = original


# ── Rejeu ────────────────────────────────────────────────────────────────────

@dataclass
class Observation:
    """Un match évalué par UN candidat. Appariable par `cle`."""

    cle: str
    ligue: str
    journee: int
    probabilites: dict
    issue: str
    data_quality: float
    promu_implique: bool
    forme_reportee: bool


@dataclass
class RunCandidat:
    candidat: str
    observations: list = field(default_factory=list)
    abstentions: Counter = field(default_factory=Counter)
    n_matchs: int = 0

    @property
    def par_cle(self) -> dict:
        return {o.cle: o for o in self.observations}

    def fenetre(self, journees: Sequence[int]) -> list:
        return [o for o in self.observations if o.journee in journees]


def _journee_de(match: CanonicalMatch, joues: dict) -> int:
    """Journée du match, définie par ce que le MODÈLE a vu : une de plus que le
    nombre de rencontres déjà disputées par l'équipe la plus avancée.

    `CanonicalMatch` ne porte aucun numéro de journée — et c'est tant mieux : ce
    qui compte pour un cold-start n'est pas le calendrier officiel mais la
    quantité d'information disponible.
    """
    return 1 + max(joues.get(match.home_team_id, 0), joues.get(match.away_team_id, 0))


def rejouer(candidat: Candidat, *, matchs_saison: Sequence[CanonicalMatch],
            matchs_precedents: Sequence[CanonicalMatch], league_id: str,
            season: str, journee_max: int = 10) -> RunCandidat:
    """Un passage chronologique sur l'ouverture d'une saison, pour un candidat."""
    modele = OneXTwoModel()
    ordonnes = sorted(matchs_saison, key=lambda m: m.kickoff)
    pool_report = list(matchs_precedents) if candidat.reporte else []
    equipes_precedentes = {m.home_team_id for m in matchs_precedents} | {
        m.away_team_id for m in matchs_precedents}

    run = RunCandidat(candidat.nom)
    joues: dict[str, int] = defaultdict(int)

    for match in ordonnes:
        journee = _journee_de(match, joues)
        if journee > journee_max:
            break
        run.n_matchs += 1
        cutoff = match.kickoff
        # La gateway voit le pool de report ET la saison en cours ; son filtre
        # `kickoff < cutoff` fait le reste. Aucune règle de report n'est écrite
        # ici : c'est la population servie qui change, rien d'autre.
        pit = PointInTimeGateway(list(pool_report) + list(matchs_saison),
                                 cutoff=cutoff, league_id=league_id, season=season)
        event = CanonicalEvent(
            event_id=match.canonical_match_id, sport="football", competition_id=league_id,
            participants=(CanonicalParticipant(match.home_team_id, "home"),
                          CanonicalParticipant(match.away_team_id, "away")),
            scheduled_at=cutoff)
        features = _features_du_candidat(candidat, event, pit, cutoff)

        if modele.assess_data_readiness(event, features) == DataReadiness.INSUFFICIENT_DATA:
            run.abstentions["INSUFFICIENT_DATA"] += 1
        else:
            predictions = modele.predict_selections(event, features, cutoff)
            promu = not {match.home_team_id, match.away_team_id} <= equipes_precedentes
            reportee = any(
                _age_jours(f, cutoff) > 45
                for tid in (match.home_team_id, match.away_team_id)
                for f in pit.recent_form(tid, competition_id=league_id, last=10,
                                         season=season))
            run.observations.append(Observation(
                cle=match.canonical_match_id, ligue=league_id, journee=journee,
                probabilites={c: predictions[c].fair_probability for c in _CLASSES},
                issue=_issue(match),
                data_quality=modele._data_quality(event, features),
                promu_implique=promu, forme_reportee=reportee))

        joues[match.home_team_id] += 1
        joues[match.away_team_id] += 1

    return run


# ── Mesures ──────────────────────────────────────────────────────────────────

def mesurer(observations: Sequence[Observation], *, n_total: int) -> dict:
    """Les métriques d'un ensemble d'observations. Aucune n'est réécrite ici."""
    if not observations:
        return {"n_eval": 0, "coverage": 0.0 if n_total else None}
    paires = [(o.probabilites, o.issue) for o in observations]
    agrege = metrics.evaluate(paires, classes=_CLASSES)
    ece = metrics.expected_calibration_error(paires, classes=_CLASSES)
    return {
        "n_eval": len(observations),
        "coverage": round(len(observations) / n_total, 4) if n_total else None,
        "data_quality": round(statistics.mean(o.data_quality for o in observations), 4),
        "brier": agrege["brier"]["value"],
        "log_loss": agrege["log_loss"]["value"],
        "ece": ece["ece"],
        "baseline_uniforme": metrics.uniform_baseline(
            [o.issue for o in observations], classes=_CLASSES)["brier"]["value"],
    }


def baseline_frequence(observations: Sequence[Observation],
                       historique: Sequence[str]) -> float | None:
    """Brier de la fréquence historique des issues, mesurée AVANT la fenêtre.

    C'est la baseline qui compte : battre une uniforme ne prouve rien sur un
    marché où le domicile gagne 45 % du temps.
    """
    if not observations or not historique:
        return None
    compte = Counter(historique)
    freq = {c: compte.get(c, 0) / len(historique) for c in _CLASSES}
    return metrics.evaluate([(freq, o.issue) for o in observations],
                            classes=_CLASSES)["brier"]["value"]


@dataclass(frozen=True)
class ComparaisonAppariee:
    """Deux candidats, sur EXACTEMENT les mêmes matchs."""

    n_communs: int
    delta_brier: float | None
    delta_log_loss: float | None
    gagnes: int
    perdus: int
    egalites: int
    ic_bas: float | None = None
    ic_haut: float | None = None
    n_uniquement_a: int = 0
    n_uniquement_b: int = 0


def comparer(a: RunCandidat, b: RunCandidat, *, journees: Sequence[int],
             confiance: float = 0.95, tirages: int = 2000) -> ComparaisonAppariee:
    """Comparaison APPARIÉE. Comparer des métriques absolues sur des populations
    différentes mesurerait surtout la différence de population."""
    pa = {o.cle: o for o in a.fenetre(journees)}
    pb = {o.cle: o for o in b.fenetre(journees)}
    communs = sorted(set(pa) & set(pb))
    if not communs:
        return ComparaisonAppariee(0, None, None, 0, 0, 0,
                                   n_uniquement_a=len(set(pa) - set(pb)),
                                   n_uniquement_b=len(set(pb) - set(pa)))

    ecarts_brier, ecarts_ll = [], []
    gagnes = perdus = egalites = 0
    for cle in communs:
        oa, ob = pa[cle], pb[cle]
        ba = metrics.brier_score(oa.probabilites, oa.issue, _CLASSES)
        bb = metrics.brier_score(ob.probabilites, ob.issue, _CLASSES)
        ecarts_brier.append(ba - bb)          # > 0 : b est meilleur
        ecarts_ll.append(metrics.log_loss(oa.probabilites, oa.issue, classes=_CLASSES)
                         - metrics.log_loss(ob.probabilites, ob.issue, classes=_CLASSES))
        if bb < ba - 1e-12:
            gagnes += 1
        elif ba < bb - 1e-12:
            perdus += 1
        else:
            egalites += 1

    bas, haut = _bootstrap(ecarts_brier, confiance, tirages)
    return ComparaisonAppariee(
        n_communs=len(communs),
        delta_brier=round(statistics.mean(ecarts_brier), 6),
        delta_log_loss=round(statistics.mean(ecarts_ll), 6),
        gagnes=gagnes, perdus=perdus, egalites=egalites,
        ic_bas=bas, ic_haut=haut,
        n_uniquement_a=len(set(pa) - set(pb)), n_uniquement_b=len(set(pb) - set(pa)))


def _bootstrap(ecarts: Sequence[float], confiance: float, tirages: int):
    """Intervalle percentile non paramétrique, DÉTERMINISTE.

    Même méthode que la borne CLV : aucune hypothèse de normalité, et une graine
    fixe pour que deux exécutions du banc rendent le même intervalle.
    """
    import random

    if len(ecarts) < 2:
        return None, None
    alea = random.Random(20260815)
    n = len(ecarts)
    moyennes = []
    for _ in range(tirages):
        moyennes.append(sum(ecarts[alea.randrange(n)] for _ in range(n)) / n)
    moyennes.sort()
    marge = (1.0 - confiance) / 2.0
    return (round(moyennes[int(marge * tirages)], 6),
            round(moyennes[min(tirages - 1, int((1 - marge) * tirages))], 6))
