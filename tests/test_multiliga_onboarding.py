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
from src.agents.quant.betting_engine.assessment import (
    assess_bundesliga, assess_championship, assess_eredivisie, assess_laliga, assess_primeira_liga,
)
from src.agents.quant.betting_engine.bookmakers.bookmaker_registry import BookmakerEventResolver
from src.agents.quant.betting_engine.bookmakers.winamax.competition_mapping import resolve_competition
from src.agents.quant.betting_engine.calibration.historical_dataset import (
    DEFAULT_BL1_FIXTURE, DEFAULT_PD_FIXTURE, load_bl1_2025, load_ded_2025, load_elc_2025,
    load_pd_2025, load_ppl_2025,
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
    ("championship", "2", load_elc_2025, "competition:football:eng:championship", 557,
     {"Norwich": "team:football:eng:norwich", "Sheffield United": "team:football:eng:sheffield_utd",
      "Stoke City": "team:football:eng:stoke", "West Bromwich": "team:football:eng:west_brom"}),
    ("eredivisie", "39", load_ded_2025, "competition:football:nld:eredivisie", 306,
     {"Ajax Amsterdam": "team:football:nld:ajax", "PSV Eindhoven": "team:football:nld:psv",
      "Feyenoord": "team:football:nld:feyenoord", "Groningue": "team:football:nld:groningen"}),
    ("primeira_liga", "52", load_ppl_2025, "competition:football:prt:primeira_liga", 306,
     {"Benfica": "team:football:prt:benfica", "FC Porto": "team:football:prt:porto",
      "Sporting Portugal": "team:football:prt:sporting", "Braga": "team:football:prt:braga"}),
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
    """100 % résolu : tout match FINISHED doit atteindre un canonical_id.

    Le nombre attendu n'est plus figé sur une saison — le corpus en compte
    désormais trois. Ce qui compte est l'INVARIANT (aucune perte à la résolution)
    et un plancher (le corpus ne rétrécit jamais), pas la taille d'une saison
    donnée : figer celle-ci ferait échouer le test à chaque acquisition, sans
    jamais détecter une équipe perdue.
    """
    matches, fingerprint, n_finished = loader(_RESOLVER)
    assert len(matches) == n_finished, (
        f"{n_finished - len(matches)} match(s) écarté(s) à la résolution")
    assert n_finished >= n_fin                                # jamais de régression
    assert fingerprint.startswith("sha256:")


@pytest.mark.parametrize("slug,assessor", [
    ("laliga", assess_laliga), ("bundesliga", assess_bundesliga),
    ("championship", assess_championship), ("eredivisie", assess_eredivisie),
    ("primeira_liga", assess_primeira_liga)])
def test_walk_forward_experimental_beats_baseline(slug, assessor):
    a = assessor()
    o, d = a.observations, a.decision
    assert d.status == "EXPERIMENTAL"                         # mécanique, jamais SUPPORTED
    assert o.n_evaluated > 250 and o.n_temporal_folds >= 3
    assert o.model_brier < o.best_baseline_brier             # bat la baseline (mesuré)
    # positive_clv bloque TOUTES les compétitions (aucune paire décision/clôture collectée) ;
    # le modèle réel reste donc EXPERIMENTAL même quand min_sample_size passe (Championship).
    blockers = {c.name for c in d.criteria if c.required and c.verdict.value != "PASS"}
    assert "positive_clv" in blockers


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
