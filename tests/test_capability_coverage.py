"""Model Capability Registry (§4) + couverture (§16), hermétique. Découverte
multi-compétition : une compétition supportée (Ligue 1) est évaluable EXPERIMENTAL,
une non mappée (MLS) est isolée COMPETITION_NOT_RESOLVED — jamais évaluée, jamais
arrêtant le scan. Aucune donnée fabriquée.
"""

from __future__ import annotations

from src.agents.quant.betting_engine.bookmakers.winamax.connector import parse_catalog
from src.agents.quant.betting_engine.bookmakers.winamax.record_replay import (
    save_capture,
    synthetic_capture,
)
from src.agents.quant.betting_engine.capability import (
    COMPETITION_NOT_RESOLVED,
    DATA_UNAVAILABLE,
    SPORT_NOT_SUPPORTED,
    SPORT_UNAVAILABLE,
    coverage_matrix,
    market_capability,
)
from src.agents.quant.betting_engine.coverage_cli import main as coverage_cli, render


def _match(mid, comp_a, comp_b, tid, oid_base):
    return {
        "sportId": 1, "tournamentId": tid, "isOutright": False,
        "competitor1Id": oid_base, "competitor1Name": comp_a,
        "competitor2Id": oid_base + 1, "competitor2Name": comp_b,
        "matchStart": 1772359200, "status": "PREMATCH"}


def _state():
    """Ligue 1 (tid 4, RESOLVED) + MLS (tid 18, non mappé)."""
    return {
        "matches": {"1": _match("1", "Paris Saint-Germain", "Marseille", 4, 1301),
                    "2": _match("2", "Inter Miami", "LA Galaxy", 18, 1401)},
        "bets": {"9001": {"matchId": 1, "betType": 1, "betTypeName": "Résultat", "template": "3way",
                          "betTypeIsLive": False, "outcomes": [501, 502, 503]},
                 "9002": {"matchId": 2, "betType": 1, "betTypeName": "Résultat", "template": "3way",
                          "betTypeIsLive": False, "outcomes": [601, 602, 603]}},
        "outcomes": {"501": {"code": "1", "label": "PSG"}, "502": {"code": "x", "label": "Nul"},
                     "503": {"code": "2", "label": "OM"}, "601": {"code": "1", "label": "MIA"},
                     "602": {"code": "x", "label": "Nul"}, "603": {"code": "2", "label": "LAG"}},
        "odds": {"501": 1.55, "502": 4.30, "503": 6.10, "601": 2.00, "602": 3.50, "603": 3.80},
        "tournaments": {"4": {"tournamentName": "Ligue 1 McDonald's®"},
                        "18": {"tournamentName": "Major League Soccer"}}}


def _events():
    return parse_catalog(_state(), "football", 1)


# --- Capability registry -------------------------------------------------------
def test_market_capability_derived_from_modules_and_ledger():
    available, maturity = market_capability("football", "MATCH_WINNER")
    assert available is True and maturity == "EXPERIMENTAL"    # dérivé du ledger, jamais SUPPORTED
    assert market_capability("football", "OVER_UNDER_2_5") == (False, "UNAVAILABLE")
    assert market_capability("handball", "MATCH_WINNER") == (False, "UNAVAILABLE")  # pas de module


# --- Couverture : découverte vs évaluable --------------------------------------
def test_coverage_isolates_unsupported_competition():
    m = coverage_matrix(_events(), "football")
    assert m.competitions_discovered == 2 and m.events_discovered == 2
    assert m.competitions_evaluable == 1 and m.events_evaluable == 1     # Ligue 1 seule
    by_name = {c.competition_name: c for c in m.capabilities}
    l1 = by_name["Ligue 1 McDonald's®"]
    assert l1.evaluable is True and l1.maturity == "EXPERIMENTAL"
    assert l1.canonical_competition == "competition:football:fra:ligue1"
    mls = by_name["Major League Soccer"]
    assert mls.evaluable is False and mls.reason_unavailable == COMPETITION_NOT_RESOLVED
    assert m.by_reason.get(COMPETITION_NOT_RESOLVED) == 1


def test_capability_lattice_distinguishes_data_gap_from_model_gap():
    # Le treillis en couches (§5) doit rendre observable catalogue ≠ data ≠ model.
    m = coverage_matrix(_events(), "football")
    by_name = {c.competition_name: c for c in m.capabilities}

    l1 = by_name["Ligue 1 McDonald's®"]
    assert l1.model_capable is True and l1.data_capable is True
    assert l1.capability_state == "EXPERIMENTAL"           # modèle + données + maturité

    # MLS : un modèle football MATCH_WINNER EXISTERAIT (model_capable) — c'est la
    # DONNÉE (identité/historique) qui manque. Donc DATA_UNAVAILABLE, PAS un manque
    # de modèle. C'est le cœur de l'honnêteté multisport.
    mls = by_name["Major League Soccer"]
    assert mls.model_capable is True                        # le modèle s'appliquerait
    assert mls.data_capable is False                        # mais aucune donnée ne résout
    assert mls.capability_state == DATA_UNAVAILABLE
    assert mls.reason_unavailable == COMPETITION_NOT_RESOLVED   # rétro-compat

    # Colonnes de couverture DISTINCTES (§19).
    assert m.competitions_model_capable == 2               # les deux ont un modèle applicable
    assert m.competitions_data_capable == 1                # seule Ligue 1 a les données
    assert m.competitions_evaluable == 1
    assert m.by_state.get(DATA_UNAVAILABLE) == 1


def test_capability_state_sport_unavailable_when_no_module():
    # Vu comme du "handball" (aucun module) : ni modèle ni données -> SPORT_UNAVAILABLE.
    m = coverage_matrix(_events(), "handball")
    for c in m.capabilities:
        assert c.model_capable is False and c.data_capable is False
        assert c.capability_state == SPORT_UNAVAILABLE
        assert c.reason_unavailable == SPORT_NOT_SUPPORTED
    assert m.competitions_model_capable == 0 and m.competitions_data_capable == 0
    assert m.competitions_evaluable == 0


def test_render_shows_both_evaluable_and_unavailable():
    lines = render(coverage_matrix(_events(), "football"), "replay:synthetic")
    text = "\n".join(lines)
    assert "ÉVALUABLES : 1" in text
    assert "model-capable : 2" in text and "data-capable : 1" in text   # couches distinctes
    assert "Ligue 1" in text and "EXPERIMENTAL" in text
    assert "Major League Soccer" in text and COMPETITION_NOT_RESOLVED in text
    assert DATA_UNAVAILABLE in text                                     # état de couche visible


def test_coverage_cli_from_capture_offline(tmp_path):
    cap = tmp_path / "cap.json"
    save_capture(synthetic_capture(_state(), "football"), cap)
    assert coverage_cli(["--sport", "football", "--capture", str(cap)]) == 0
