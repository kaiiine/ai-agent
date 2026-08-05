"""Non-régression math : le nouveau chemin (feature_engineering -> one_x_two)
reproduit EXACTEMENT l'implémentation gelée `quant/dixon_coles.py`.

Valeurs de référence FIGÉES (littéraux), produites par l'impl actuelle. Le noyau
étant réutilisé à l'identique par import, toute différence à 1e-9 est un bug de
câblage, pas un arrondi. Ces golden viennent EN PLUS des 17 tests gelés de
`test_quant_engine.py`, qu'ils ne remplacent pas.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.agents.quant.dixon_coles import DEFAULT_RHO, score_matrix
from src.agents.quant.betting_engine.core.canonical_event import CanonicalEvent, CanonicalParticipant
from src.agents.quant.betting_engine.sports.football.feature_engineering import build_event_feature_set
from src.agents.quant.betting_engine.sports.football.market_models.one_x_two import OneXTwoModel

TOL = 1e-9
_T = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
_H = "team:football:fra:psg"
_A = "team:football:fra:marseille"
_DATES = ["2026-07-28", "2026-07-25", "2026-07-21", "2026-07-18", "2026-07-14"]


def _form(pairs):  # pairs = [(is_home, goals_home, goals_away), ...] plus récent en premier
    return [
        {"is_home": h, "goals_home": gh, "goals_away": ga,
         "opponent_id": f"opp{i}", "date": _DATES[i]}
        for i, (h, gh, ga) in enumerate(pairs)
    ]


_HOME_STRONG = _form([(True, 4, 0), (False, 3, 1), (True, 3, 0), (False, 2, 1), (True, 4, 1)])
_AWAY_WEAK = _form([(True, 0, 2), (False, 0, 3), (True, 1, 2), (False, 0, 2), (True, 1, 1)])
_AVG = _form([(True, 2, 1), (False, 1, 1), (True, 1, 1), (False, 1, 2), (True, 2, 2)])
_LOW_HOME = _form([(True, 1, 0), (False, 0, 0), (True, 1, 1), (False, 0, 1), (True, 0, 0)])
_LOW_AWAY = _form([(False, 0, 1), (True, 1, 0), (False, 0, 0), (True, 0, 0), (False, 1, 1)])


def _sym(n=10):
    from src.agents.quant.dixon_coles import LEAGUE_AVG_GOALS, HOME_ADVANTAGE, AWAY_FACTOR
    form = []
    for i in range(n):
        is_home = i % 2 == 0
        scored = LEAGUE_AVG_GOALS * (HOME_ADVANTAGE if is_home else AWAY_FACTOR)
        conceded = LEAGUE_AVG_GOALS * (AWAY_FACTOR if is_home else HOME_ADVANTAGE)
        form.append({
            "goals_home": scored if is_home else conceded,
            "goals_away": conceded if is_home else scored,
            "is_home": is_home, "opponent_id": f"o{i}", "date": "2026-07-%02d" % (28 - i),
        })
    return form


class _FakeGateway:
    def __init__(self, home_form, away_form):
        self._forms = {_H: home_form, _A: away_form}

    def recent_form(self, canonical_team_id, *, competition_id, last, season):
        return self._forms[canonical_team_id][:last]

    def standings_strength(self, league_canonical_id, season):
        return {}                                   # -> opponent_ratings=None (fixtures sans ajustement)


def _new_path_1x2(home_form, away_form):
    event = CanonicalEvent(
        "e", "football", "competition:football:fra:ligue1",
        (CanonicalParticipant(_H, "home"), CanonicalParticipant(_A, "away")), _T,
    )
    features = build_event_feature_set(event, gateway=_FakeGateway(home_form, away_form), as_of=_T)
    preds = OneXTwoModel().predict_selections(event, features, point_in_time=_T)
    return preds, features


# (home, draw, away) FIGÉS depuis dixon_coles_probabilities de l'impl actuelle.
_GOLDEN_1X2 = {
    "home_fav":         (_HOME_STRONG, _AWAY_WEAK, (0.4948, 0.2646, 0.2407)),
    "balanced":         (_AVG, _AVG, (0.4266, 0.2841, 0.2893)),
    "away_fav":         (_AWAY_WEAK, _HOME_STRONG, (0.3727, 0.2802, 0.3471)),
    "low_intensity":    (_LOW_HOME, _LOW_AWAY, (0.3666, 0.3605, 0.2729)),
    "limit_symmetric":  (_sym(), _sym(), (0.4250, 0.2863, 0.2886)),
}


@pytest.mark.parametrize("name", list(_GOLDEN_1X2))
def test_1x2_matches_frozen_reference(name):
    home_form, away_form, (ref_h, ref_d, ref_a) = _GOLDEN_1X2[name]
    preds, _ = _new_path_1x2(home_form, away_form)
    assert abs(preds["home"].fair_probability - ref_h) < TOL
    assert abs(preds["draw"].fair_probability - ref_d) < TOL
    assert abs(preds["away"].fair_probability - ref_a) < TOL
    # somme ≈ 1 (troncature de grille + arrondi 4 décimales)
    total = sum(preds[s].fair_probability for s in ("home", "draw", "away"))
    assert abs(total - 1.0) < 5e-4


def test_strengths_feature_matches_frozen_reference():
    _, features = _new_path_1x2(_HOME_STRONG, _AWAY_WEAK)
    home = features.participant_features[_H]
    away = features.participant_features[_A]
    assert (home["attack_strength"], home["defense_strength"]) == (1.2066, 0.9519)
    assert (away["attack_strength"], away["defense_strength"]) == (1.0218, 0.966)


def test_dixon_coles_low_score_correction_is_active_and_frozen():
    # Sur faibles intensités, la correction tau modifie P(0-0) vs Poisson pur (rho=0).
    home_str = {"attack": 0.8572, "defense": 0.786}     # forces figées (low_home)
    away_str = {"attack": 0.8673, "defense": 0.7715}    # forces figées (low_away)
    with_rho = score_matrix(home_str, away_str, DEFAULT_RHO)[0][0]
    without = score_matrix(home_str, away_str, 0.0)[0][0]
    assert abs(with_rho - 0.180912) < 1e-6            # valeur figée AVEC correction DC
    assert abs(without - 0.163644) < 1e-6            # sans correction
    assert abs(with_rho - without) > 1e-3            # preuve que tau est bien actif
