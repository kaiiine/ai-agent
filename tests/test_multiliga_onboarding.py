"""Onboarding batch multiligue — LaLiga + Bundesliga (§1-4, §10). Données RÉELLES
football-data.org, hermétique. Même recette prouvée que Serie A : identités réelles
(IDs vérifiés en direct), résolution EXACTE, désambiguïsation par roster (homonyme
Bundesliga), historique 100 % résolu, walk-forward -> EXPERIMENTAL mécanique.
"""

from __future__ import annotations

import json

import pytest

from src.agents.quant.gateway.core.identity_data import TEAMS, LEAGUE_TEAMS
from src.agents.quant.gateway.core.identity_resolver import IdentityResolver
from src.agents.quant.betting_engine.assessment import assess_laliga, assess_bundesliga
from src.agents.quant.betting_engine.bookmakers.bookmaker_registry import BookmakerEventResolver
from src.agents.quant.betting_engine.bookmakers.winamax.competition_mapping import resolve_competition
from src.agents.quant.betting_engine.calibration.historical_dataset import (
    DEFAULT_BL1_FIXTURE, DEFAULT_PD_FIXTURE, load_bl1_2025, load_pd_2025,
)
from src.agents.quant.betting_engine.competition_identity import (
    COMPETITION_IDENTITY_RESOLVED, disambiguate,
)

_RESOLVER = IdentityResolver(TEAMS)

# (slug compétition, tid Winamax, loader, competition_id, n_finished attendu, exemples nom Winamax -> canonical)
_LEAGUES = [
    ("laliga", "36", load_pd_2025, "competition:football:esp:laliga", 380,
     {"Real Madrid": "team:football:esp:real_madrid", "FC Barcelone": "team:football:esp:barcelona",
      "Atletico Madrid": "team:football:esp:atletico_madrid", "Betis Séville": "team:football:esp:real_betis"}),
    ("bundesliga", "42", load_bl1_2025, "competition:football:deu:bundesliga", 306,
     {"Bayern Munich": "team:football:deu:bayern", "Borussia Dortmund": "team:football:deu:dortmund",
      "FC Cologne": "team:football:deu:koln", "Mayence": "team:football:deu:mainz"}),
]


@pytest.mark.parametrize("slug,tid,loader,comp_id,n_fin,samples", _LEAGUES)
def test_roster_and_identity(slug, tid, loader, comp_id, n_fin, samples):
    league = LEAGUE_TEAMS[comp_id]
    by_id = {e.canonical_id: e for e in TEAMS}
    for cid in league:                                        # IDs provider RÉELS présents
        assert by_id[cid].identities.get("football_data_org")
    ber = BookmakerEventResolver(_RESOLVER)
    for wnm_name, expected in samples.items():                # résolution EXACTE (jamais floue)
        matches, _ = ber._name_matches("football", wnm_name)
        assert [m.canonical_id for m in matches] == [expected]


@pytest.mark.parametrize("slug,tid,loader,comp_id,n_fin,samples", _LEAGUES)
def test_competition_mapping_resolved(slug, tid, loader, comp_id, n_fin, samples):
    cid, status, _ = resolve_competition(tid)
    assert cid == comp_id and status == "RESOLVED"


@pytest.mark.parametrize("slug,tid,loader,comp_id,n_fin,samples", _LEAGUES)
def test_historical_fully_resolved(slug, tid, loader, comp_id, n_fin, samples):
    matches, fingerprint, n_finished = loader(_RESOLVER)
    assert n_finished == n_fin and len(matches) == n_fin      # 100 % résolu
    assert fingerprint.startswith("sha256:")


@pytest.mark.parametrize("slug,assessor", [("laliga", assess_laliga), ("bundesliga", assess_bundesliga)])
def test_walk_forward_experimental_beats_baseline(slug, assessor):
    a = assessor()
    o, d = a.observations, a.decision
    assert d.status == "EXPERIMENTAL"                         # mécanique, jamais SUPPORTED
    assert o.n_evaluated > 250 and o.n_temporal_folds >= 3
    assert o.model_brier < o.best_baseline_brier
    assert "min_sample_size" in {c.name for c in d.criteria if c.required and c.verdict.value != "PASS"}


def test_bundesliga_homonym_resolved_by_real_roster_not_name():
    # Preuve sur données RÉELLES : le roster BL1 (fixture) désambiguïse le vrai
    # Bundesliga allemand d'un roster autrichien. Jamais par le nom (§2).
    payload = json.loads(DEFAULT_BL1_FIXTURE.read_text(encoding="utf-8"))
    bl1_names = sorted({m[s]["name"] for m in payload["matches"] for s in ("homeTeam", "awayTeam")})
    austrian = ["FC Red Bull Salzburg", "SK Rapid Wien", "SK Sturm Graz", "LASK", "Austria Wien"]
    res = disambiguate(bl1_names, {
        "competition:football:deu:bundesliga": bl1_names,
        "competition:football:aut:bundesliga": austrian,
    })
    assert res.status == COMPETITION_IDENTITY_RESOLVED
    assert res.competition_id == "competition:football:deu:bundesliga"


def test_unknown_team_stays_unresolved():
    ber = BookmakerEventResolver(_RESOLVER)
    for name in ("Paderborn", "Schalke 04", "Deportivo La Corogne"):   # hors dataset -> isolé
        matches, _ = ber._name_matches("football", name)
        assert matches == []
