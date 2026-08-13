"""Fusionner deux providers sans compter deux fois la même rencontre.

Un critère de maturité franchi par duplication est pire qu'un critère non
franchi : `min_sample_size` passerait, la calibration serait mesurée sur des
doublons, et rien ne le signalerait.

MESURÉ sur la Champions League : football-data.org 503 rencontres, api-sports
707. La fusion n'a apparié que 14 doublons — non par défaut d'algorithme, mais
parce que les deux sources nomment les clubs différemment (`AFC Ajax` contre
`Ajax`). Le module a refusé de rapprocher ce qu'il ne pouvait pas prouver
identique, plutôt que de gonfler l'échantillon.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest

from src.agents.quant.betting_engine.acquisition.reconciliation import (
    TOLERANCE_HEURES,
    reconcilier,
)

CL = "competition:football:eur:champions_league"
KO = datetime(2026, 9, 17, 19, tzinfo=timezone.utc)


@dataclass(frozen=True)
class _M:
    canonical_match_id: str
    league_id: str
    season: str
    home_team_id: str
    away_team_id: str
    kickoff: datetime
    status: str
    goals_home: int
    goals_away: int


def _match(mid, dom="team:a", ext="team:b", ko=KO, dh=2, da=1, comp=CL):
    return _M(mid, comp, "2026", dom, ext, ko, "FINISHED", dh, da)


# ── Dédoublonnage ───────────────────────────────────────────────────────────

def test_la_meme_rencontre_vue_par_deux_providers_ne_compte_qu_une_fois():
    r = reconcilier({"p1": [_match("p1:1")], "p2": [_match("p2:1")]})

    assert r.resume["raw_total"] == 2
    assert r.resume["unique_canonical"] == 1
    assert r.resume["duplicates_matched"] == 1


def test_l_inversion_domicile_exterieur_n_empeche_pas_l_appariement():
    """Un provider peut lister la rencontre dans l'autre sens."""
    r = reconcilier({
        "p1": [_match("p1:1", dom="team:a", ext="team:b")],
        "p2": [_match("p2:1", dom="team:b", ext="team:a")]})

    assert r.resume["unique_canonical"] == 1


def test_un_decalage_horaire_modere_reste_la_meme_rencontre():
    """Fuseau, heure annoncée contre heure réelle : les sources divergent."""
    r = reconcilier({"p1": [_match("p1:1")],
                     "p2": [_match("p2:1", ko=KO + timedelta(hours=2))]})

    assert r.resume["unique_canonical"] == 1


def test_au_dela_de_la_tolerance_ce_sont_deux_rencontres():
    """Une même paire peut se rencontrer deux fois — aller et retour."""
    r = reconcilier({"p1": [_match("p1:1")],
                     "p2": [_match("p2:1", ko=KO + timedelta(hours=TOLERANCE_HEURES + 2))]})

    assert r.resume["unique_canonical"] == 2
    assert r.resume["duplicates_matched"] == 0


def test_deux_competitions_ne_fusionnent_jamais():
    r = reconcilier({"p1": [_match("p1:1")],
                     "p2": [_match("p2:1", comp="competition:football:fra:ligue1")]})

    assert r.resume["unique_canonical"] == 2


# ── Conflits : rapportés, jamais arbitrés ───────────────────────────────────

def test_deux_scores_divergents_produisent_un_conflit_pas_un_choix():
    """Choisir « le premier » serait une décision statistique déguisée en détail
    d'implémentation."""
    r = reconcilier({"p1": [_match("p1:1", dh=2, da=1)],
                     "p2": [_match("p2:1", dh=3, da=1)]})

    assert r.resume["conflicts"] == 1
    assert r.resume["unique_canonical"] == 0, "une rencontre litigieuse n'entre pas"


def test_un_conflit_rapporte_les_deux_versions():
    r = reconcilier({"p1": [_match("p1:1", dh=2, da=1)],
                     "p2": [_match("p2:1", dh=3, da=1)]})

    scores = {(p, h, a) for p, h, a in r.conflicts[0].scores}

    assert scores == {("p1", 2, 1), ("p2", 3, 1)}


def test_le_meme_score_vu_deux_fois_n_est_pas_un_conflit():
    r = reconcilier({"p1": [_match("p1:1")], "p2": [_match("p2:1")]})

    assert r.resume["conflicts"] == 0


# ── Déterminisme ────────────────────────────────────────────────────────────

def test_l_ordre_des_providers_ne_change_pas_le_resultat():
    """Sinon la taille de l'échantillon dépendrait de l'ordre d'un dictionnaire."""
    a = reconcilier({"p1": [_match("p1:1")], "p2": [_match("p2:1")]}).resume
    b = reconcilier({"p2": [_match("p2:1")], "p1": [_match("p1:1")]}).resume

    assert a == b


def test_aucun_rapprochement_flou_n_est_tente():
    """Une similarité de nom ferait fusionner deux rencontres réellement
    distinctes, et l'erreur serait invisible dans le benchmark."""
    import inspect

    from src.agents.quant.betting_engine.acquisition import reconciliation

    source = inspect.getsource(reconciliation)

    for interdit in ("difflib", "SequenceMatcher", "fuzz", "levenshtein"):
        assert interdit not in source.lower()


def test_les_rencontres_sont_rendues_en_ordre_chronologique():
    """Le walk-forward en dépend : mal ordonné, il fuiterait."""
    r = reconcilier({"p1": [_match("p1:2", ko=KO + timedelta(days=3)),
                            _match("p1:1", ko=KO)]})

    assert [m.kickoff for m in r.matches] == sorted(m.kickoff for m in r.matches)


def test_un_seul_provider_passe_sans_doublon():
    r = reconcilier({"p1": [_match("p1:1"), _match("p1:2", ko=KO + timedelta(days=3))]})

    assert r.resume == {"raw_par_provider": {"p1": 2}, "raw_total": 2,
                        "unique_canonical": 2, "duplicates_matched": 0,
                        "conflicts": 0, "unresolved": 0}


def test_le_compte_brut_par_provider_est_conserve():
    """Sans lui, impossible de dire ce que la fusion a réellement absorbé."""
    r = reconcilier({"p1": [_match("p1:1")], "p2": [_match("p2:1"), _match("p2:2",
                     ko=KO + timedelta(days=5))]})

    assert r.resume["raw_par_provider"] == {"p1": 1, "p2": 2}
