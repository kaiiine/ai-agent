"""Calibration point-in-time, générique aux issues du marché.

Deux boucles de walk-forward coexistaient — `run_elo_walk_forward` (NBA) et
`run_pairwise_elo` — pour un comportement identique, à ceci près que l'une lisait
des constantes de module et que seule l'autre pouvait recevoir un calibrateur.
Et la primitive de calibration, générique de nom, lisait en réalité les issues
football `home/draw/away` : appliquée à un marché 2-way, elle échouait sur la
clé `draw` absente.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.agents.quant.betting_engine.calibration.calibrator import (
    HistogramBinningCalibrator,
)
from src.agents.quant.betting_engine.sports.pairwise_elo import (
    EloParams,
    PairwiseGame,
    run_pairwise_elo,
)

_T0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
_PARAMS = EloParams(init_rating=1500.0, k_factor=20.0, home_edge=100.0,
                    min_prior_games=2, notes="test")


def _jeux(n: int, *, gagnant_domicile: int) -> list[PairwiseGame]:
    """`gagnant_domicile` premières rencontres gagnées à domicile, le reste à
    l'extérieur — de quoi produire une vraie miscalibration."""
    equipes = [f"e{i}" for i in range(8)]
    jeux = []
    for i in range(n):
        h, a = equipes[i % 8], equipes[(i + 3) % 8]
        domicile = i < gagnant_domicile
        jeux.append(PairwiseGame(
            game_id=f"g{i}", tipoff=_T0 + timedelta(days=i),
            home_id=h, away_id=a,
            home_score=2 if domicile else 0, away_score=0 if domicile else 2))
    return jeux


# ══ §3 — La primitive ne connaît plus d'issues sportives ═══════════════════
def test_le_calibrateur_accepte_un_marche_2way():
    """`home/draw/away` en dur levait une KeyError sur un marché sans nul."""
    calibrateur = HistogramBinningCalibrator.fit(
        [({"home": 0.6, "away": 0.4}, "home")] * 60
        + [({"home": 0.6, "away": 0.4}, "away")] * 40)

    corrigee = calibrateur.apply({"home": 0.62, "away": 0.38})

    assert set(corrigee) == {"home", "away"}
    assert abs(sum(corrigee.values()) - 1.0) < 1e-9


def test_le_calibrateur_accepte_toujours_un_marche_3way():
    """La généralisation ne doit rien retirer au football."""
    calibrateur = HistogramBinningCalibrator.fit(
        [({"home": 0.5, "draw": 0.3, "away": 0.2}, "home")] * 60
        + [({"home": 0.5, "draw": 0.3, "away": 0.2}, "draw")] * 40)

    corrigee = calibrateur.apply({"home": 0.5, "draw": 0.3, "away": 0.2})

    assert set(corrigee) == {"home", "draw", "away"}
    assert abs(sum(corrigee.values()) - 1.0) < 1e-9


def test_la_somme_des_issues_vaut_un_quel_que_soit_leur_nombre():
    """La calibration ne crée ni ne détruit de masse de probabilité."""
    for issues in ({"a": 0.5, "b": 0.5}, {"a": 0.4, "b": 0.35, "c": 0.25},
                   {"a": 0.25, "b": 0.25, "c": 0.25, "d": 0.25}):
        calibrateur = HistogramBinningCalibrator.fit(
            [(issues, next(iter(issues)))] * 100)
        assert abs(sum(calibrateur.apply(issues).values()) - 1.0) < 1e-9


def test_le_calibrateur_ne_renomme_ni_ne_permute_les_issues():
    """Inverser silencieusement l'identité des issues échangerait deux équipes."""
    calibrateur = HistogramBinningCalibrator.fit(
        [({"home": 0.8, "away": 0.2}, "home")] * 100)

    corrigee = calibrateur.apply({"home": 0.8, "away": 0.2})

    assert corrigee["home"] > corrigee["away"]      # l'ordre est conservé


# ══ §5 — Anti-fuite : le futur ne peut pas changer le passé ════════════════
def test_modifier_le_futur_ne_change_aucune_prediction_anterieure():
    """Le test que réclame un calibrateur point-in-time. Un calibrateur ajusté
    une fois sur tout le dataset puis appliqué rétroactivement passerait tous les
    autres contrôles et serait pourtant faux."""
    reference = run_pairwise_elo(_jeux(120, gagnant_domicile=80), _PARAMS,
                                 calibrate=True)

    # Mêmes 60 premières rencontres, issues des suivantes toutes inversées.
    modifies = _jeux(120, gagnant_domicile=80)
    for i in range(60, 120):
        g = modifies[i]
        modifies[i] = PairwiseGame(
            game_id=g.game_id, tipoff=g.tipoff, home_id=g.home_id, away_id=g.away_id,
            home_score=g.away_score, away_score=g.home_score)
    perturbe = run_pairwise_elo(modifies, _PARAMS, calibrate=True)

    # Les prédictions correspondant aux rencontres antérieures à la perturbation
    # doivent être identiques, calibration comprise.
    communes = [i for i, gid in enumerate(reference.predicted_game_ids)
                if int(gid[1:]) < 60]
    assert communes, "aucune prédiction antérieure à comparer"
    for i in communes:
        assert reference.model_predictions[i] == perturbe.model_predictions[i], i


def test_la_premiere_prediction_n_est_jamais_calibree():
    """Sans historique, il n'y a rien sur quoi ajuster — et une correction
    fabriquée à partir de rien serait pire que pas de correction."""
    run = run_pairwise_elo(_jeux(60, gagnant_domicile=40), _PARAMS, calibrate=True)

    assert run.model_predictions[0] == run.raw_predictions[0]


# ══ §6 — Brute ET calibrée, toutes deux conservées ═════════════════════════
def test_la_probabilite_brute_reste_disponible_pour_l_audit():
    """Une correction qu'on ne peut pas comparer à son absence n'est pas
    vérifiable."""
    run = run_pairwise_elo(_jeux(200, gagnant_domicile=140), _PARAMS, calibrate=True)

    assert len(run.raw_predictions) == len(run.model_predictions)
    assert run.n_calibrated > 0
    assert any(brut != calibre for (brut, _), (calibre, _)
               in zip(run.raw_predictions, run.model_predictions))


def test_sans_calibration_la_sortie_est_exactement_la_brute():
    """L'opt-in doit être un vrai interrupteur : éteint, rien ne change."""
    run = run_pairwise_elo(_jeux(200, gagnant_domicile=140), _PARAMS, calibrate=False)

    assert run.model_predictions == run.raw_predictions
    assert run.n_calibrated == 0


# ══ §10 — Aucun calibrateur par effet de bord ══════════════════════════════
def test_la_calibration_est_desactivee_par_defaut():
    """Un calibrateur ne doit jamais apparaître par famille : chacun se mérite
    sur ses propres mesures. Le volley l'a mesuré et REFUSÉ."""
    import inspect

    signature = inspect.signature(run_pairwise_elo)

    assert signature.parameters["calibrate"].default is False


@pytest.mark.parametrize("module,fonction", [
    ("baseball.moneyline", "assess_mlb"),
    ("american_football.moneyline", "assess_nfl"),
    ("volleyball.moneyline", "assess_volleyball"),
])
def test_les_autres_modeles_pairwise_restent_non_calibres(module, fonction):
    """Le volley en particulier : son benchmark a montré un logloss dégradé, et
    l'intégration NBA ne doit pas servir de prétexte à l'activer."""
    import importlib

    mod = importlib.import_module(
        f"src.agents.quant.betting_engine.sports.{module}")

    assert getattr(mod, fonction)().run.n_calibrated == 0
