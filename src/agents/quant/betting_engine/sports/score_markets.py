"""Validation des marchés de SCORE, sport par sport — reproductible.

Le benchmark qui a tranché entre les trois lois candidates vit ici, dans le
dépôt, et pas dans un carnet : un résultat qu'on ne peut pas rejouer n'est pas un
résultat, c'est un souvenir. Chaque sport déclare ses données et ses paramètres ;
la mécanique de mesure est commune, et c'est EXACTEMENT celle du multi-marché
football — `build_target_metrics` puis `evaluate_maturity`, sans une métrique
réécrite. Un basket validé par une porte que le football n'a pas franchie serait
une validation de complaisance.

CE QUI A ÉTÉ MESURÉ, ET CE QUE ÇA A DONNÉ (walk-forward strict, baselines
point-in-time) :

    NBA    4 149 rencontres, 3 944 évaluées
           NORMAL   24/24 cibles battent leur baseline · ECE moyen 0,0144
           POISSON  24/24 · ECE 0,0249      NEGBIN 22/24 · ECE 0,0281
           surdispersion du total mesurée : variance/moyenne = 1,88

    NFL    7 405 rencontres, 7 231 évaluées
           NORMAL   24/24 · ECE moyen 0,0176
           POISSON   2/24 · ECE 0,1188  — rejeté, la surdispersion vaut 4,52
           NEGBIN   24/24 · ECE 0,0181, mais sur 6 102 rencontres seulement

    MLB    8 495 rencontres, 8 169 évaluées
           NORMAL   10/22 · gains entre −0,010 et +0,006 — du bruit
           POISSON   0/22      NEGBIN 10/22 sur 1 914 rencontres
           VERDICT : aucune loi ne bat honnêtement sa baseline. STOP STATISTIQUE.

LA LOI RETENUE EST LA NORMALE POUR LES DEUX SPORTS VALIDÉS, et la raison est
mesurée, pas esthétique : Poisson impose variance = moyenne, ce que les données
démentent dans les trois sports (1,88 / 4,52 / 2,29). La binomiale négative
corrige la dispersion mais son support tronqué exclut une part importante des
rencontres, sans gagner en calibration.

CE MODULE NE PROMEUT AUCUNE MATURITÉ. Il mesure ; le ledger décide.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Callable, Sequence

from src.agents.quant.betting_engine.calibration.market_walk_forward import build_target_metrics

from .score_distribution import (
    ScoreGame,
    ScoreParams,
    cibles_marge,
    cibles_total,
    cibles_total_equipe,
    lignes_autour,
    run_score_walk_forward,
)

#: Lois confrontées. L'ordre est celui du rapport, pas une préférence.
LOIS_CANDIDATES = ("NORMAL", "POISSON", "NEGBIN")


@dataclass(frozen=True)
class ScoreMarketConfig:
    """Ce qu'un sport apporte : ses données, ses paramètres, son identité."""

    sport: str
    competition_id: str
    model_name: str
    model_version: str
    params: ScoreParams
    load: Callable[[], list[ScoreGame]]
    #: Loi retenue APRÈS benchmark. `None` tant qu'aucune ne l'a emporté — et
    #: c'est un état parfaitement valide, pas un oubli de configuration.
    law: str | None = None
    #: `canonical_id -> identifiant du corpus`. LA MÊME table que celle du
    #: moneyline du sport, jamais une seconde : deux annuaires d'équipes finissent
    #: par diverger, et le jour où ils divergent le modèle de score price une
    #: autre équipe que celle qu'on croit. `None` = pont non fourni, donc aucune
    #: rencontre reconnue — un refus visible plutôt qu'une identité devinée.
    team_id_of: Callable[[], dict] | None = None

    def corpus_id(self, canonical_id: str) -> str | None:
        table = self.team_id_of() if self.team_id_of is not None else {}
        return table.get(canonical_id)


@dataclass(frozen=True)
class ScoreMarketAssessment:
    sport: str
    law: str
    n_games: int
    n_predicted: int
    mae_margin: float | None
    mae_total: float | None
    #: clé de cible -> métriques complètes de `build_target_metrics`
    targets: dict = field(default_factory=dict)
    dispersion_ratio: float | None = None

    @property
    def familles_battant_leur_baseline(self) -> dict:
        """Par famille : combien de ses lignes battent la fréquence historique.

        La granularité est la LIGNE, jamais la famille : rejeter une famille pour
        une de ses lignes coûterait les autres, et en garder une invalidée
        coûterait la confiance. C'est la règle déjà appliquée au football, où le
        total 0.5 est rejeté et les cinq autres validées.
        """
        par_famille: dict[str, list[str]] = {}
        for cle, m in self.targets.items():
            if m.get("n_eval"):
                par_famille.setdefault(m["family"], []).append(cle)
        return {famille: [c for c in cles
                          if self.targets[c].get("beats_frequency_baseline")]
                for famille, cles in par_famille.items()}

    def lignes_validees(self, famille: str) -> list[float]:
        """Les lignes d'une famille qui battent leur baseline, triées."""
        return sorted(
            self.targets[c]["parameters"]["line"]
            for c in self.familles_battant_leur_baseline.get(famille, [])
            if "line" in self.targets[c].get("parameters", {}))


def cibles_du_corpus(jeux: Sequence[ScoreGame], *, combien: int = 3) -> list:
    """Les cibles à évaluer, CENTRÉES SUR LES DONNÉES.

    Le centre et le pas viennent de la moyenne et de l'écart-type observés, pas
    d'un chiffre rond choisi à la main : une grille arbitraire testerait la loi
    là où le marché ne propose rien, et la laisserait invérifiée là où il
    propose tout.
    """
    totaux = [g.total for g in jeux]
    centre = statistics.mean(totaux)
    pas = max(0.5, round(statistics.pstdev(totaux) / 3, 1))
    return (cibles_marge(lignes_autour(0, pas=max(1.0, pas), combien=combien))
            + cibles_total(lignes_autour(centre, pas=pas, combien=combien))
            + cibles_total_equipe(lignes_autour(centre / 2, pas=max(0.5, pas / 2),
                                                combien=combien - 1)))


def evaluer(config: ScoreMarketConfig, *, law: str | None = None,
            targets=None) -> ScoreMarketAssessment:
    """Un passage walk-forward complet et ses métriques, pour une loi."""
    jeux = config.load()
    cibles = list(targets) if targets is not None else cibles_du_corpus(jeux)
    loi = law or config.law or "NORMAL"
    run = run_score_walk_forward(jeux, params=config.params, targets=cibles,
                                 law=loi, competition_id=config.competition_id)
    totaux = [g.total for g in jeux]
    dispersion = (statistics.pvariance(totaux) / statistics.mean(totaux)
                  if totaux and statistics.mean(totaux) else None)
    return ScoreMarketAssessment(
        sport=config.sport, law=loi, n_games=run.n_games, n_predicted=run.n_predicted,
        mae_margin=run.mae_margin, mae_total=run.mae_total,
        targets={c.key: build_target_metrics(run.runs[c.key]) for c in cibles},
        dispersion_ratio=round(dispersion, 3) if dispersion else None)


def comparer_les_lois(config: ScoreMarketConfig, *,
                      lois: Sequence[str] = LOIS_CANDIDATES) -> dict:
    """Le benchmark : chaque loi candidate, sur les MÊMES cibles et le MÊME corpus.

    Comparer des lois sur des cibles différentes ne comparerait rien. Les cibles
    sont donc construites une fois et partagées.
    """
    jeux = config.load()
    cibles = cibles_du_corpus(jeux)
    resultats = {}
    for loi in lois:
        mesure = evaluer(config, law=loi, targets=cibles)
        evaluees = [m for m in mesure.targets.values() if m.get("n_eval")]
        eces = [m["ece"] for m in evaluees if m.get("ece") is not None]
        resultats[loi] = {
            "n_predicted": mesure.n_predicted,
            "cibles_evaluees": len(evaluees),
            "cibles_battant_la_baseline": sum(
                1 for m in evaluees if m.get("beats_frequency_baseline")),
            "ece_moyen": round(statistics.mean(eces), 4) if eces else None,
            "ece_max": round(max(eces), 4) if eces else None,
            "assessment": mesure,
        }
    return resultats
