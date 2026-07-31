"""CLV maturity ROBUSTE (§1-§8, §18) — la promotion SUPPORTED ne peut JAMAIS être
déclenchée par une seule observation CLV chanceuse.

Prouve, avec des données CLV explicitement SYNTHÉTIQUES (jamais présentées comme
réelles) :
  1. Unité d'observation (§4) : home/away, snapshots répétés et bookmakers multiples du
     MÊME match ne sont PAS des observations indépendantes -> `n_events` (échantillon
     effectif) != nombre brut de paires.
  2. Statistique (§2/§3) : borne de confiance inférieure bootstrap (non-paramétrique),
     déterministe, robuste à un outlier isolé et à une forte variance.
  3. Gate maturité (§7) : 0 paire / 1 paire / échantillon < min / échantillon suffisant
     mais borne <= 0 -> jamais PASS ; échantillon suffisant + borne > 0 -> PASS.
  4. Promotion mécanique (§8/§18) : le VRAI modèle hockey reste EXPERIMENTAL sur données
     réelles ; il ne passe SUPPORTED qu'avec un échantillon CLV robuste (synthétique) ;
     la réévaluation avec un CLV dégradé redéclasse (contrat de ledger existant).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from src.agents.quant.betting_engine.clv import (
    MEASURABLE,
    NOT_YET_MEASURABLE,
    ObservationPhase,
    OddsObservation,
    clv_readiness,
)
from src.agents.quant.betting_engine.maturity import load_maturity_policy

_T0 = datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc)
_CONF = load_maturity_policy().criteria["clv_confidence_level"]
_MIN = load_maturity_policy().criteria["min_clv_events"]


def _pair(event: str, selection: str, clv: float, *, book: str = "winamax", snap: int = 0):
    """Une paire décision/clôture SYNTHÉTIQUE dont la CLV vaut ~`clv`.
    CLV = decision/closing - 1 -> closing = decision / (1 + clv)."""
    decision = Decimal("2.0000")
    closing = (decision / (Decimal("1") + Decimal(str(clv)))).quantize(Decimal("0.0001"))
    t_dec = _T0 + timedelta(minutes=snap)
    return [
        OddsObservation(event, "MATCH_WINNER", selection, book, decision, t_dec,
                        ObservationPhase.DECISION, "synthetic"),
        OddsObservation(event, "MATCH_WINNER", selection, book, closing,
                        t_dec + timedelta(hours=2), ObservationPhase.CLOSING, "synthetic"),
    ]


def _events(clvs, *, selection="home"):
    """Un événement indépendant par valeur de CLV fournie."""
    obs = []
    for i, c in enumerate(clvs):
        obs += _pair(f"event:test:{i}", selection, c)
    return obs


# ── §4 : unité d'observation = ÉVÉNEMENT, pas la ligne brute ─────────────────────
def test_home_and_away_of_same_event_count_as_one_event():
    obs = _pair("event:e1", "home", 0.05) + _pair("event:e1", "away", -0.03)
    r = clv_readiness(obs, confidence=_CONF)
    assert r.status == MEASURABLE
    assert r.n_complete_pairs == 2      # deux market_keys appariés (informatif)
    assert r.n_events == 1              # UN seul événement indépendant (§4)


def test_repeated_decision_snapshots_collapse_to_one_pair():
    # 3 captures DECISION du même marché + 1 CLOSING -> UNE paire (pas 3).
    obs = (_pair("event:e1", "home", 0.05, snap=0)[:1]
           + _pair("event:e1", "home", 0.05, snap=10)[:1]
           + _pair("event:e1", "home", 0.05, snap=20))     # 3e paire porte la clôture
    r = clv_readiness(obs, confidence=_CONF)
    assert r.n_complete_pairs == 1 and r.n_events == 1


def test_many_correlated_lines_same_event_stay_one_event():
    # 50 lignes (sélections/bookmakers) du même match -> 1 événement, jamais 50.
    obs = []
    for i in range(25):
        obs += _pair("event:e1", "home", 0.04, book=f"book{i}")
        obs += _pair("event:e1", "away", 0.04, book=f"book{i}")
    r = clv_readiness(obs, confidence=_CONF)
    assert r.n_complete_pairs == 50 and r.n_events == 1


def test_distinct_events_count_independently():
    r = clv_readiness(_events([0.02] * 40), confidence=_CONF)
    assert r.n_events == 40


# ── §2/§3 : borne de confiance bootstrap, déterministe et robuste ────────────────
def test_no_pairs_has_no_lower_bound():
    r = clv_readiness([], confidence=_CONF)
    assert r.status == NOT_YET_MEASURABLE and r.clv_lower_bound is None and r.n_events == 0


def test_bootstrap_is_deterministic():
    a = clv_readiness(_events([0.01, 0.02, 0.03, -0.01] * 12), confidence=_CONF)
    b = clv_readiness(_events([0.01, 0.02, 0.03, -0.01] * 12), confidence=_CONF)
    assert a.clv_lower_bound == b.clv_lower_bound


def test_single_positive_outlier_does_not_lift_lower_bound():
    # 39 événements ~ -0.005 + 1 outlier +0.5 : moyenne > 0 mais borne basse <= 0.
    r = clv_readiness(_events([-0.005] * 39 + [0.5]), confidence=_CONF)
    assert r.mean_clv > 0                       # tirée par l'outlier
    assert r.clv_lower_bound <= 0               # borne robuste : un gain isolé ne suffit pas


def test_high_variance_straddling_zero_has_nonpositive_lower_bound():
    r = clv_readiness(_events([0.1, -0.1] * 25), confidence=_CONF)   # moyenne ~ 0, forte variance
    assert r.clv_lower_bound <= 0


def test_consistent_positive_edge_has_positive_lower_bound():
    r = clv_readiness(_events([0.02] * 50), confidence=_CONF)
    assert r.mean_clv > 0 and r.clv_lower_bound is not None and r.clv_lower_bound > 0


# ── §7/§8 : gate de maturité de bout en bout via clv_readiness -> evaluate ────────
def _decide_with(obs):
    """Injecte un échantillon CLV synthétique dans le VRAI modèle hockey et renvoie sa
    décision de maturité (tous les autres critères déjà PASS, sauf CLV)."""
    from src.agents.quant.betting_engine.sports.hockey.regulation import assess_nhl
    return assess_nhl(odds_observations=obs).decision


def _clv_criterion(decision):
    return next(c for c in decision.criteria if c.name == "positive_clv")


def test_real_hockey_stays_experimental_without_clv():
    d = _decide_with([])
    assert d.status == "EXPERIMENTAL"
    assert _clv_criterion(d).detail.startswith("CLV NOT_MEASURABLE")


def test_real_hockey_insufficient_clv_sample_stays_experimental():
    # Quelques paires positives mais < minimum -> INSUFFICIENT_SAMPLE, jamais SUPPORTED (§8).
    d = _decide_with(_events([0.03] * 5))
    assert d.status == "EXPERIMENTAL"
    assert _clv_criterion(d).observed["state"] == "INSUFFICIENT_SAMPLE"


def test_real_hockey_promotes_with_robust_synthetic_clv():
    # Preuve de la mécanique de promotion (§8/§18 cas 2) : échantillon robuste -> SUPPORTED.
    d = _decide_with(_events([0.02] * 60))
    assert _clv_criterion(d).verdict.value == "PASS"
    assert d.status == "SUPPORTED"          # tous les critères requis PASS
    # …mais UNIQUEMENT parce que les cotes sont SYNTHÉTIQUES : rien n'est persisté au ledger.
    from src.agents.quant.betting_engine.support_status import resolve_market_status
    assert resolve_market_status(d.model_name, d.model_version).value == "EXPERIMENTAL"


# ── §18 cas 3 : réévaluation avec CLV dégradé -> redéclassement (contrat ledger) ──
def test_downgrade_on_reevaluation_follows_ledger_contract(tmp_path):
    from src.agents.quant.betting_engine.support_status import (
        append_support_decision,
        resolve_market_status,
    )
    ledger = tmp_path / "ledger.jsonl"
    supported = _decide_with(_events([0.02] * 60))
    append_support_decision(supported, ledger_path=ledger)
    assert resolve_market_status(supported.model_name, supported.model_version,
                                 ledger_path=ledger).value == "SUPPORTED"
    # Réévaluation ultérieure : la CLV repasse sous le seuil -> verdict EXPERIMENTAL.
    downgraded = _decide_with(_events([0.02] * 5))       # échantillon redevenu insuffisant
    assert downgraded.status == "EXPERIMENTAL"
    append_support_decision(downgraded, ledger_path=ledger)
    # Contrat existant : la DERNIÈRE décision gouverne -> redéclassement, sans policy neuve.
    assert resolve_market_status(downgraded.model_name, downgraded.model_version,
                                 ledger_path=ledger).value == "EXPERIMENTAL"
