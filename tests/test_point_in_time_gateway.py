"""GATE de non-fuite temporelle — condition BLOQUANTE avant toute métrique.

Prouve que la reconstruction à un cutoff T n'utilise QUE des matchs strictement
antérieurs (`kickoff < T`), à la seconde près, jamais par matchday. Données
synthétiques (autorisé pour les tests du framework, jamais pour un ExperimentResult).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.agents.quant.gateway.sports.football.canonical_facts import CanonicalMatch
from src.agents.quant.betting_engine.core.canonical_event import CanonicalEvent, CanonicalParticipant
from src.agents.quant.betting_engine.sports.football.feature_engineering import build_event_feature_set
from src.agents.quant.betting_engine.calibration.point_in_time_gateway import PointInTimeGateway

_LEAGUE = "competition:football:fra:ligue1"
_A = "team:football:fra:psg"
_B = "team:football:fra:marseille"
_C = "team:football:fra:lyon"
_D = "team:football:fra:lille"

# Match évalué : coup d'envoi T (4 octobre 2025, 17:00 UTC).
_T = datetime(2025, 10, 4, 17, 0, tzinfo=timezone.utc)


def _m(hid, aid, gh, ga, kickoff):
    return CanonicalMatch(f"m-{hid}-{aid}-{kickoff.isoformat()}", _LEAGUE, "2025",
                          hid, aid, kickoff, "FINISHED", gh, ga)


def _utc(month, day, hour=17):
    return datetime(2025, month, day, hour, tzinfo=timezone.utc)


# Antérieurs à T : 3 journées, 4 équipes, venues variées.
_PRIOR = [
    _m(_A, _B, 2, 0, _utc(8, 15)), _m(_C, _D, 1, 1, _utc(8, 16)),
    _m(_C, _A, 0, 1, _utc(8, 22)), _m(_D, _B, 2, 0, _utc(8, 23)),
    _m(_A, _D, 3, 1, _utc(8, 29)), _m(_B, _C, 1, 1, _utc(8, 30)),
]


def _reconstruct(matches):
    gw = PointInTimeGateway(matches, cutoff=_T, league_id=_LEAGUE, season="2025")
    return gw.recent_form(_A, 10, "2025"), gw.standings_strength(_LEAGUE, "2025")


_BASE = _reconstruct(_PRIOR)


# ── Structurel : le filtre ne PEUT PAS être par matchday ──────────────────────
def test_canonical_match_has_no_matchday_field():
    fields = set(vars(_m(_A, _B, 1, 0, _utc(8, 15))))
    assert "matchday" not in fields          # filtrage par date garanti par construction


# ── Exclusions (le futur ne fuit pas) ─────────────────────────────────────────
def test_far_future_match_does_not_change_reconstruction():
    poison = _m(_A, _D, 5, 0, _T + timedelta(days=7))
    assert _reconstruct(_PRIOR + [poison]) == _BASE


def test_same_civil_day_but_after_T_is_excluded():
    # Même jour civil que T, mais quelques heures APRÈS le coup d'envoi évalué.
    poison = _m(_A, _D, 5, 0, _T + timedelta(hours=3))
    assert (_T + timedelta(hours=3)).date() == _T.date()   # bien le même jour civil
    assert _reconstruct(_PRIOR + [poison]) == _BASE


def test_match_exactly_at_T_is_excluded_strict_not_lte():
    # Le match évalué lui-même (ou un match simultané) : kickoff == T -> exclu.
    poison = _m(_A, _D, 5, 0, _T)
    assert _reconstruct(_PRIOR + [poison]) == _BASE


def test_same_matchday_later_date_is_excluded_by_time_not_matchday():
    # Deux matchs "de la même journée" à des dates différentes : celui joué après
    # T doit être exclu — preuve que le filtre est temporel, pas par matchday.
    poison = _m(_C, _B, 4, 0, _T + timedelta(hours=1))
    assert _reconstruct(_PRIOR + [poison]) == _BASE


# ── Inclusion : la frontière est EXACTEMENT T (strict) ────────────────────────
def test_match_one_second_before_T_is_included():
    included = _m(_A, _C, 5, 0, _T - timedelta(seconds=1))
    assert _reconstruct(_PRIOR + [included]) != _BASE     # il change bien la reconstruction


# ── Non-fuite de bout en bout via le VRAI chemin feature ──────────────────────
def test_feature_set_is_leak_free_end_to_end():
    event = CanonicalEvent(
        "evt-A-D", "football", _LEAGUE,
        (CanonicalParticipant(_A, "home"), CanonicalParticipant(_D, "away")), _T,
    )

    def features(matches):
        gw = PointInTimeGateway(matches, cutoff=_T, league_id=_LEAGUE, season="2025")
        return build_event_feature_set(event, gateway=gw, as_of=_T)

    base = features(_PRIOR)
    future = _m(_A, _D, 5, 0, _T + timedelta(days=3))
    # Ajouter un match postérieur ne change RIEN au feature set reconstruit à T.
    assert features(_PRIOR + [future]) == base
    # ... et les features attendues sont bien produites (forme présente avant T).
    assert "attack_strength" in base.participant_features[_A]
    assert "attack_strength" in base.participant_features[_D]
