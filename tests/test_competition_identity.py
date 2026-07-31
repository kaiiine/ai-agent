"""Désambiguïsation compétition par chevauchement de roster (§2) — hermétique.

Prouve qu'un homonyme Winamax (deux « Bundesliga ») est résolu par les ÉQUIPES, jamais
par le nom, et que l'ambiguïté/absence est refusée explicitement (fail-safe money-safe).
"""

from __future__ import annotations

from src.agents.quant.betting_engine.competition_identity import (
    COMPETITION_IDENTITY_AMBIGUOUS,
    COMPETITION_IDENTITY_RESOLVED,
    COMPETITION_IDENTITY_UNRESOLVED,
    disambiguate,
    roster_overlap,
)

# Rosters provider (extraits) — Allemagne vs Autriche : DISJOINTS.
_BL1_DE = ["FC Bayern München", "Borussia Dortmund", "RB Leipzig", "Bayer 04 Leverkusen",
           "Eintracht Frankfurt", "VfB Stuttgart", "SC Freiburg", "VfL Wolfsburg"]
_BL_AT = ["FC Red Bull Salzburg", "SK Rapid Wien", "SK Sturm Graz", "LASK",
          "Austria Wien", "Wolfsberger AC", "TSV Hartberg", "SCR Altach"]

# Noms Winamax (français) de la Bundesliga ALLEMANDE — variantes cross-langue.
_WNM_BL_DE = ["Bayern Munich", "Borussia Dortmund", "RB Leipzig", "Bayer Leverkusen",
              "Eintracht Francfort", "VfB Stuttgart", "Fribourg", "Wolfsbourg"]


def test_cross_language_overlap_detects_german_roster():
    # Tokens distinctifs partagés malgré la langue (bayern, dortmund, leipzig, stuttgart…).
    de = roster_overlap(_WNM_BL_DE, _BL1_DE)
    at = roster_overlap(_WNM_BL_DE, _BL_AT)
    assert de >= 0.6 and at <= 0.15 and de > at


def test_homonym_resolved_by_roster_not_name():
    res = disambiguate(_WNM_BL_DE, {
        "competition:football:deu:bundesliga": _BL1_DE,
        "competition:football:aut:bundesliga": _BL_AT,
    })
    assert res.status == COMPETITION_IDENTITY_RESOLVED
    assert res.competition_id == "competition:football:deu:bundesliga"


def test_ambiguous_when_two_candidates_share_the_roster():
    # Deux candidats au même roster -> aucune décision univoque -> refus explicite.
    res = disambiguate(_WNM_BL_DE, {"competition:a": _BL1_DE, "competition:b": _BL1_DE})
    assert res.status == COMPETITION_IDENTITY_AMBIGUOUS
    assert res.competition_id is None


def test_unresolved_when_no_candidate_overlaps():
    res = disambiguate(_WNM_BL_DE, {"competition:football:aut:bundesliga": _BL_AT})
    assert res.status == COMPETITION_IDENTITY_UNRESOLVED
    assert res.competition_id is None


def test_empty_candidates_is_unresolved_not_crash():
    res = disambiguate(_WNM_BL_DE, {})
    assert res.status == COMPETITION_IDENTITY_UNRESOLVED and res.scores == {}


def test_generic_form_words_do_not_create_false_overlap():
    # « FC »/« SC » communs ne doivent PAS créer un faux recouvrement entre disjoints.
    assert roster_overlap(["FC Alpha", "SC Beta"], ["FC Gamma", "SC Delta"]) == 0.0
