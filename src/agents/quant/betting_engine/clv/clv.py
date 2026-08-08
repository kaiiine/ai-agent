"""Closing-line value (CLV) POINT-IN-TIME — calcul réel si (et seulement si) une
paire décision/clôture existe pour le même marché ; sinon état explicite
`NOT_YET_MEASURABLE`. L'absence de CLV n'est JAMAIS convertie en 0 (consigne §9).

CLV = decision_odds / closing_odds − 1 :
  > 0  la cote prise à la décision était meilleure que la clôture (edge confirmé) ;
  = 0  identique ; < 0  la cote a monté en votre défaveur.

Contrainte point-in-time : `decision.observed_at < closing.observed_at` (STRICT) —
on ne « prouve » jamais une CLV avec une clôture antérieure à la décision.

UNITÉ D'OBSERVATION (§4 — anti-pseudo-réplication). Une CLV n'est PAS « une ligne
stockée ». Plusieurs lignes du MÊME match bougent ensemble (home/away/nul du même
marché, plusieurs snapshots, plusieurs bookmakers) : les compter comme indépendantes
gonflerait artificiellement l'échantillon. Définition retenue (V1, conservatrice) :

  1. Pour chaque `stable_market_key` (rencontre STABLE, market, selection, bookmaker),
     on ne forme qu'UNE paire : la DÉCISION la plus tardive STRICTEMENT antérieure à
     la DERNIÈRE clôture (les captures répétées d'un même marché sont fusionnées).
     L'identité de rencontre ignore l'horaire annoncé — un match repoussé reste le
     même match, et sa décision doit pouvoir s'apparier avec sa vraie clôture
     (cf. `identity.py`).
  2. L'ÉCHANTILLON EFFECTIF est le nombre d'ÉVÉNEMENTS indépendants (`n_events`) :
     toutes les paires d'un même événement sont agrégées en UNE valeur (moyenne
     intra-événement). C'est `n_events` — jamais le nombre brut de lignes ni de
     paires — qui gouverne la maturité CLV.

Le `status` reste une lecture de COLLECTE (MEASURABLE dès qu'une paire existe) ; la
règle de PROMOTION robuste (échantillon minimal + borne de confiance > 0) vit dans la
politique de maturité, pas ici.
"""

from __future__ import annotations

import random
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from .observation import ObservationPhase, OddsObservation

# Statuts explicites (repris tels quels par la politique de maturité).
MEASURABLE = "MEASURABLE"
NOT_YET_MEASURABLE = "NOT_YET_MEASURABLE"

# Bootstrap non-paramétrique (borne de confiance inférieure de la CLV moyenne).
# DÉTERMINISTE (graine fixe) pour que la maturité reste reproductible. Choix
# non-paramétrique (percentile) : aucune hypothèse de normalité — la distribution de
# CLV est asymétrique et à queues lourdes (rapport de cotes). Robuste aux outliers :
# un unique gain isolé ne suffit pas à relever la borne basse (§2/§3).
_BOOTSTRAP_RESAMPLES = 4000
_BOOTSTRAP_SEED = 20260801


@dataclass(frozen=True)
class ClvResult:
    #: Identité STABLE du marché — insensible aux reports d'horaire (identity.py).
    stable_market_key: tuple[str, str, str, str]
    decision_odds: Decimal
    closing_odds: Decimal
    decision_time: datetime
    closing_time: datetime
    clv: Decimal
    beat_close: bool


@dataclass(frozen=True)
class ClvReadiness:
    status: str                  # MEASURABLE | NOT_YET_MEASURABLE
    n_observations: int
    n_complete_pairs: int        # paires brutes (market_key apparié) — INFORMATIF, jamais l'échantillon
    n_events: int                # ÉCHANTILLON EFFECTIF : événements indépendants (§4)
    mean_clv: Decimal | None     # moyenne des CLV par événement — None si NOT_YET_MEASURABLE (jamais 0)
    clv_lower_bound: float | None  # borne de confiance inférieure (bootstrap) — None si aucune paire
    reason: str


def _pair_for_market(obs_list: list[OddsObservation]) -> ClvResult | None:
    """UNE paire par `stable_market_key` (§4) : la DERNIÈRE clôture disponible, et
    la DÉCISION la plus tardive strictement antérieure à elle.

    Fusionne les captures répétées d'un même marché — un scheduler qui rescanne
    DECISION ne crée pas N observations « indépendantes ».

    POURQUOI LA DERNIÈRE CLÔTURE, ET NON LA PREMIÈRE. Une ligne de clôture est par
    définition le DERNIER prix avant la fermeture du marché. Tant qu'un match
    partait à l'heure, les clôtures d'un même marché tenaient dans une fenêtre de
    trente minutes et le choix était indifférent. Il cesse de l'être dès qu'un
    match est repoussé : les clôtures d'une même rencontre peuvent alors s'étaler
    sur des heures, et retenir la première reviendrait à mesurer la dérive du
    marché plutôt que la valeur de clôture.

    Ce choix suffit à honorer la contrainte « clôture antérieure au coup d'envoi
    final » sans que ce module connaisse le moindre horaire : quand l'appelant a
    filtré par `eligibility`, toute clôture reçue est déjà prouvée dans la fenêtre
    du dernier coup d'envoi connu.
    """
    decisions = sorted((o for o in obs_list if o.phase is ObservationPhase.DECISION),
                       key=lambda o: o.observed_at)
    closings = sorted((o for o in obs_list if o.phase is ObservationPhase.CLOSING),
                      key=lambda o: o.observed_at)
    if not decisions or not closings:
        return None
    latest_closing = closings[-1]
    prior = [d for d in decisions if d.observed_at < latest_closing.observed_at]
    if not prior:
        return None
    return compute_clv(prior[-1], latest_closing)


def _bootstrap_lower_bound(values: list[float], confidence: float) -> float | None:
    """Borne de confiance inférieure UNILATÉRALE de la CLV moyenne, par bootstrap
    percentile (non-paramétrique, déterministe). `None` si aucun échantillon."""
    n = len(values)
    if n == 0:
        return None
    rng = random.Random(_BOOTSTRAP_SEED)
    means: list[float] = []
    for _ in range(_BOOTSTRAP_RESAMPLES):
        acc = 0.0
        for _ in range(n):
            acc += values[rng.randrange(n)]
        means.append(acc / n)
    means.sort()
    alpha = 1.0 - confidence
    return means[int(alpha * (_BOOTSTRAP_RESAMPLES - 1))]


def compute_clv(decision: OddsObservation, closing: OddsObservation) -> ClvResult:
    if decision.stable_market_key != closing.stable_market_key:
        raise ValueError("CLV : décision et clôture doivent viser le même marché")
    if decision.phase is not ObservationPhase.DECISION:
        raise ValueError("CLV : la première observation doit être de phase DECISION")
    if closing.phase is not ObservationPhase.CLOSING:
        raise ValueError("CLV : la seconde observation doit être de phase CLOSING")
    if not decision.observed_at < closing.observed_at:
        raise ValueError(
            "CLV : violation point-in-time — la clôture doit être STRICTEMENT postérieure "
            "à la décision"
        )
    clv = decision.decimal_odds / closing.decimal_odds - Decimal("1")
    return ClvResult(
        stable_market_key=decision.stable_market_key,
        decision_odds=decision.decimal_odds,
        closing_odds=closing.decimal_odds,
        decision_time=decision.observed_at,
        closing_time=closing.observed_at,
        clv=clv,
        beat_close=clv > 0,
    )


def clv_readiness(
    observations: Sequence[OddsObservation], *, confidence: float = 0.95
) -> ClvReadiness:
    """Détermine si la CLV est mesurable à partir des observations collectées, et
    produit l'échantillon EFFECTIF (par événement) + la borne de confiance inférieure.

    MEASURABLE dès qu'il existe au moins une paire décision/clôture appariable (lecture
    de COLLECTE). L'échantillon `n_events` agrège les lignes corrélées d'un même
    événement en UNE observation (§4). `confidence` gouverne la borne basse bootstrap
    (paramètre de méthode fourni par la politique de maturité). Aucune valeur fabriquée :
    absence de paire -> NOT_YET_MEASURABLE, mean_clv=None (jamais 0).
    """
    # Appariement sur l'identité STABLE : une décision prise sous l'horaire de
    # 18 h 00 et sa clôture prise sous 18 h 50 appartiennent à la même rencontre.
    by_market: dict[tuple, list[OddsObservation]] = defaultdict(list)
    for obs in observations:
        by_market[obs.stable_market_key].append(obs)

    per_event: dict[str, list[Decimal]] = defaultdict(list)   # rencontre -> CLV des paires
    n_pairs = 0
    for market_key, obs_list in by_market.items():
        result = _pair_for_market(obs_list)
        if result is None:
            continue
        n_pairs += 1
        per_event[market_key[0]].append(result.clv)           # market_key[0] == rencontre stable

    if n_pairs == 0:
        return ClvReadiness(
            status=NOT_YET_MEASURABLE,
            n_observations=len(observations),
            n_complete_pairs=0,
            n_events=0,
            mean_clv=None,                    # jamais 0 pour « non mesuré »
            clv_lower_bound=None,
            reason="aucune paire décision/clôture appariable (odds_history en collecte)",
        )
    # Une observation CLV indépendante = un ÉVÉNEMENT (moyenne intra-événement).
    event_values = [sum(v, Decimal("0")) / Decimal(len(v)) for v in per_event.values()]
    n_events = len(event_values)
    mean_clv = sum(event_values, Decimal("0")) / Decimal(n_events)
    lower_bound = _bootstrap_lower_bound([float(v) for v in event_values], confidence)
    return ClvReadiness(
        status=MEASURABLE,
        n_observations=len(observations),
        n_complete_pairs=n_pairs,
        n_events=n_events,
        mean_clv=mean_clv,
        clv_lower_bound=lower_bound,
        reason=f"{n_pairs} paire(s) sur {n_events} événement(s) indépendant(s) "
               f"(borne basse {confidence:.0%})",
    )
