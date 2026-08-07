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
    """Une équipe hors référentiel reste UNRESOLVED — isolée, jamais mal résolue.

    Frosinone, Monza et Venise servaient d'exemples : ils jouaient en Serie A
    2023-24 et sont désormais AU référentiel, puisque le corpus acquis les
    contient. L'invariant, lui, ne change pas — on l'éprouve donc sur un nom qui
    n'existe nulle part, ce qui le rend indépendant du roster du jour."""
    ber = BookmakerEventResolver(_RESOLVER)
    for name in ("Club Inexistant", "Equipe Fantome"):
        matches, _ = ber._name_matches("football", name)
        assert matches == []


def test_competition_mapping_resolved():
    cid, status, _ = resolve_competition("33")
    assert cid == "competition:football:ita:serie_a" and status == "RESOLVED"


def test_historical_dataset_real_and_fully_resolved():
    matches, fingerprint, n_finished = load_sa_2025(_RESOLVER)
    # Trois saisons acquises : c'est l'INVARIANT de résolution qui est vérifié,
    # pas la taille d'une saison — la figer ferait échouer le test à chaque
    # acquisition sans jamais détecter une équipe perdue.
    assert len(matches) == n_finished and n_finished >= 380   # 100 % résolu
    assert fingerprint.startswith("sha256:")                  # provenance/reproductibilité
    # La compétition reste la même sur tout le corpus ; la saison, elle, varie
    # désormais — chaque match porte la sienne, jamais celle de la plus récente.
    from src.agents.quant.betting_engine.calibration.historical_dataset import (
        HISTORICAL_SEASONS,
    )

    assert all(m.league_id == SA_LEAGUE_ID for m in matches)
    assert {m.season for m in matches} <= {*HISTORICAL_SEASONS, SA_SEASON}
    assert len({m.season for m in matches}) > 1               # l'historique est bien empilé


def test_generic_loader_matches_wrapper():
    """Le wrapper délègue au chargeur générique : mêmes matchs pour la MÊME
    saison. Le wrapper empile désormais l'historique, donc on compare à saison
    forcée — sinon on comparerait trois saisons à une."""
    a, fa, na = load_competition_season(_RESOLVER, DEFAULT_SA_FIXTURE, SA_LEAGUE_ID, SA_SEASON)
    b, fb, nb = load_sa_2025(_RESOLVER, path=DEFAULT_SA_FIXTURE)
    assert (len(a), fa, na) == (len(b), fb, nb)


def test_walk_forward_is_experimental_never_fabricated_supported():
    a = assess_serie_a()
    o, d = a.observations, a.decision
    assert d.status == "EXPERIMENTAL"                          # verdict MÉCANIQUE, jamais SUPPORTED
    assert o.n_evaluated > 300 and o.n_temporal_folds >= 3     # hors échantillon réel
    assert o.model_brier < o.best_baseline_brier              # bat la baseline (mesuré)
    blockers = {c.name for c in d.criteria if c.required and c.verdict.value != "PASS"}
    # `min_sample_size` est franchi depuis l'acquisition de 2023-24 et 2024-25 —
    # par les DONNÉES, aucun seuil n'ayant bougé. Le verdict reste EXPERIMENTAL
    # parce que la CLV, elle, n'est toujours pas mesurable.
    assert "min_sample_size" not in blockers
    assert "positive_clv" in blockers


def test_walk_forward_is_deterministic():
    a1, a2 = assess_serie_a(), assess_serie_a()
    assert a1.decision.status == a2.decision.status
    assert a1.observations.n_evaluated == a2.observations.n_evaluated
    assert a1.observations.model_brier == a2.observations.model_brier
