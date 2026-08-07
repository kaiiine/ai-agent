"""Invariant VALUE (§6) + readiness (§16), hermétique.

§6 : une cote basse n'est PAS une « value ». Sans `fair_probability` valide (aucun
modèle), le chemin structuré ne calcule NI edge NI EV et n'affiche jamais une cote
brute comme « value » : un événement sans modèle est ISOLÉ (SkippedEvaluation), et le
rendu n'expose une EV que pour une ligne BET réellement misée (donc SUPPORTED).
"""

from __future__ import annotations

from datetime import datetime, timezone

from src.agents.quant.advisor.cli import render_human
from src.agents.quant.advisor.domain.enums import RecommendationOutcome
from src.agents.quant.advisor.domain.recommendations import RecommendationResponse
from src.agents.quant.betting_engine.readiness_cli import render as readiness_render
from src.agents.quant.betting_engine.assessment import assess_default_one_x_two

_T = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)


def _response(outcome, portfolios=()):
    return RecommendationResponse(
        request_id="r", generated_at=_T, outcome=outcome, portfolios=portfolios,
        review_candidates=(), rejection_summary={}, warnings=(), audit_id="audit:x")


def test_no_bet_no_value_or_ev_in_render():
    # Aucun portefeuille misé -> le rendu n'affiche NI BET NI EV NI value.
    for outcome in (RecommendationOutcome.NO_OPPORTUNITY,
                    RecommendationOutcome.NO_EVALUABLE_EVENTS):
        text = "\n".join(render_human(_response(outcome)))
        low = text.lower()
        assert "bet " not in low            # aucune ligne de mise
        assert "ev " not in low             # aucune espérance affichée
        assert "value" not in low           # jamais le mot value sur une cote brute


def test_render_never_labels_raw_odds_as_value():
    # Le rendu ne contient aucune notion de value/edge liée à une cote sans modèle.
    text = "\n".join(render_human(_response(RecommendationOutcome.NO_OPPORTUNITY)))
    assert "edge" not in text.lower()


def test_readiness_render_is_honest_experimental():
    lines = readiness_render(assess_default_one_x_two())
    text = "\n".join(lines)
    assert "-> EXPERIMENTAL" in text                       # verdict mécanique, jamais SUPPORTED
    # Un seul bloqueur depuis l'acquisition historique : la CLV, qui demande des
    # captures CLOSING réelles — pas plus de données passées.
    assert "bloqueurs vers SUPPORTED : positive_clv" in text
