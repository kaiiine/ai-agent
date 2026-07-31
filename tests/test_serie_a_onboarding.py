"""Onboarding Serie A (§7/§9/§10) — données RÉELLES football-data.org, hermétique.

Prouve qu'une 2e compétition football devient data-capable SANS whitelist arbitraire
ni fabrication : identités réelles (IDs football_data_org vérifiés en direct), résolution
EXACTE (jamais floue), dataset historique réel, même modèle/walk-forward, verdict
MÉCANIQUE EXPERIMENTAL (jamais un faux SUPPORTED). Aucune donnée synthétique.
"""

from __future__ import annotations

from src.agents.quant.gateway.core.identity_data import TEAMS, LEAGUE_TEAMS
from src.agents.quant.gateway.core.identity_resolver import IdentityResolver
from src.agents.quant.betting_engine.assessment import assess_serie_a
from src.agents.quant.betting_engine.bookmakers.bookmaker_registry import BookmakerEventResolver
from src.agents.quant.betting_engine.bookmakers.winamax.competition_mapping import resolve_competition
from src.agents.quant.betting_engine.calibration.historical_dataset import (
    SA_LEAGUE_ID, SA_SEASON, DEFAULT_SA_FIXTURE, load_competition_season, load_sa_2025,
)

_RESOLVER = IdentityResolver(TEAMS)


def test_roster_is_twenty_teams_with_real_provider_ids():
    league = LEAGUE_TEAMS["competition:football:ita:serie_a"]
    assert len(league) == 20
    by_id = {e.canonical_id: e for e in TEAMS}
    for cid in league:
        e = by_id[cid]
        assert e.identities.get("football_data_org")          # ID provider RÉEL présent
        assert cid.startswith("team:football:ita:")


def test_winamax_names_resolve_exactly_no_fuzzy():
    ber = BookmakerEventResolver(_RESOLVER)
    cases = {"Milan AC": "team:football:ita:milan", "Inter Milan": "team:football:ita:inter",
             "Naples": "team:football:ita:napoli", "AS Rome": "team:football:ita:roma",
             "Côme": "team:football:ita:como", "Juventus Turin": "team:football:ita:juventus"}
    for wnm_name, expected in cases.items():
        matches, _ = ber._name_matches("football", wnm_name)
        assert [m.canonical_id for m in matches] == [expected]


def test_teams_absent_from_dataset_stay_unresolved():
    # Frosinone/Monza/Venise apparaissent chez Winamax mais PAS dans le dataset 2025 :
    # aucune identité -> UNRESOLVED (isolé, jamais mal résolu).
    ber = BookmakerEventResolver(_RESOLVER)
    for name in ("Frosinone", "Monza", "Venise"):
        matches, _ = ber._name_matches("football", name)
        assert matches == []


def test_competition_mapping_resolved():
    cid, status, _ = resolve_competition("33")
    assert cid == "competition:football:ita:serie_a" and status == "RESOLVED"


def test_historical_dataset_real_and_fully_resolved():
    matches, fingerprint, n_finished = load_sa_2025(_RESOLVER)
    assert n_finished == 380 and len(matches) == 380          # saison complète, 100 % résolue
    assert fingerprint.startswith("sha256:")                  # provenance/reproductibilité
    assert all(m.league_id == SA_LEAGUE_ID and m.season == SA_SEASON for m in matches)


def test_generic_loader_matches_wrapper():
    a, fa, na = load_competition_season(_RESOLVER, DEFAULT_SA_FIXTURE, SA_LEAGUE_ID, SA_SEASON)
    b, fb, nb = load_sa_2025(_RESOLVER)
    assert (len(a), fa, na) == (len(b), fb, nb)                # wrapper == chargeur générique


def test_walk_forward_is_experimental_never_fabricated_supported():
    a = assess_serie_a()
    o, d = a.observations, a.decision
    assert d.status == "EXPERIMENTAL"                          # verdict MÉCANIQUE, jamais SUPPORTED
    assert o.n_evaluated > 300 and o.n_temporal_folds >= 3     # hors échantillon réel
    assert o.model_brier < o.best_baseline_brier              # bat la baseline (mesuré)
    blockers = {c.name for c in d.criteria if c.required and c.verdict.value != "PASS"}
    assert "min_sample_size" in blockers                      # 370 < 500 : honnêtement bloqué


def test_walk_forward_is_deterministic():
    a1, a2 = assess_serie_a(), assess_serie_a()
    assert a1.decision.status == a2.decision.status
    assert a1.observations.n_evaluated == a2.observations.n_evaluated
    assert a1.observations.model_brier == a2.observations.model_brier
