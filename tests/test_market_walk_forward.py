"""Validation walk-forward FAMILLE PAR FAMILLE — la machinerie, pas la statistique.

Les chiffres de qualité viennent d'un rejeu sur données réelles (7 620 matchs,
7 championnats, 3 saisons). Ces tests-ci vérifient autre chose, et de plus
structurel : que le règlement historique de chaque famille est le bon, que la
porte anti-fuite reste fermée, et qu'aucune famille ne peut être promue par
héritage ni par un seuil réécrit pour l'occasion.

Un règlement faux est le défaut le plus coûteux du lot : il produit des métriques
parfaitement présentables sur un marché qui n'est pas celui qu'on croit évaluer.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.agents.quant.betting_engine.calibration.market_walk_forward import (
    VOID,
    MarketTarget,
    TargetRun,
    build_target_metrics,
    cibles_football,
    run_market_walk_forward,
    verdict_de_famille,
)
from src.agents.quant.gateway.sports.football.canonical_facts import CanonicalMatch

DEBUT = datetime(2025, 8, 1, 18, 0, tzinfo=timezone.utc)


def _match(i: int, gh: int, ga: int, *, home="team:a", away="team:b") -> CanonicalMatch:
    return CanonicalMatch(
        canonical_match_id=f"m{i}", league_id="competition:football:fra:ligue1",
        season="2025", home_team_id=home, away_team_id=away,
        kickoff=DEBUT + timedelta(days=i), status="FINISHED",
        goals_home=gh, goals_away=ga)


def _cible(cle: str):
    return next(c for c in cibles_football([0.5, 1.5, 2.5]) if c.key == cle)


# ── Le règlement historique, famille par famille ─────────────────────────────

@pytest.mark.parametrize("gh,ga,attendu", [(2, 0, "home"), (0, 1, "away"), (1, 1, "draw")])
def test_reglement_match_winner(gh, ga, attendu):
    assert _cible("MATCH_WINNER").settle(_match(1, gh, ga)) == attendu


@pytest.mark.parametrize("gh,ga,attendu", [(1, 1, "yes"), (3, 0, "no"), (0, 0, "no"), (2, 4, "yes")])
def test_reglement_btts(gh, ga, attendu):
    assert _cible("BTTS").settle(_match(1, gh, ga)) == attendu


@pytest.mark.parametrize("gh,ga,ligne,attendu", [
    (1, 1, 2.5, "under"), (2, 1, 2.5, "over"), (0, 0, 0.5, "under"), (1, 0, 0.5, "over"),
])
def test_reglement_totals(gh, ga, ligne, attendu):
    assert _cible(f"TOTALS(line={ligne})").settle(_match(1, gh, ga)) == attendu


def test_reglement_double_chance_couvre_bien_deux_issues():
    hd = _cible("DOUBLE_CHANCE(home_or_draw)")
    assert hd.settle(_match(1, 2, 0)) == "yes"      # victoire domicile
    assert hd.settle(_match(1, 1, 1)) == "yes"      # nul
    assert hd.settle(_match(1, 0, 2)) == "no"       # victoire extérieur


def test_le_nul_annule_le_rembourse_si_nul_au_lieu_de_le_perdre():
    """LE point à ne pas rater : un nul rembourse la mise. Compter ces matchs en
    pertes mesurerait un marché qui n'existe pas, et ferait paraître le modèle
    bien plus mauvais qu'il n'est."""
    dnb = _cible("DRAW_NO_BET(home)")
    assert dnb.settle(_match(1, 2, 0)) == "yes"
    assert dnb.settle(_match(1, 0, 2)) == "no"
    assert dnb.settle(_match(1, 1, 1)) == VOID


def test_le_score_exact_bascule_dans_other_hors_grille():
    es = _cible("EXACT_SCORE")
    assert es.settle(_match(1, 2, 1)) == "2:1"
    assert es.settle(_match(1, 7, 0)) == "other"    # la source expose cette issue
    assert es.settle(_match(1, 5, 5)) == "5:5"


# ── Le rejeu ─────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def rejeu():
    """Un mini-championnat réel dans sa forme (équipes multiples, scores variés)."""
    equipes = ["team:a", "team:b", "team:c", "team:d"]
    matchs = []
    scores = [(2, 0), (1, 1), (0, 3), (2, 2), (1, 0), (3, 1), (0, 0), (2, 1),
              (1, 2), (4, 0), (1, 1), (0, 1), (2, 3), (1, 0), (0, 2), (3, 3)]
    for i, (gh, ga) in enumerate(scores):
        matchs.append(_match(i, gh, ga,
                             home=equipes[i % 4], away=equipes[(i + 1) % 4]))
    return run_market_walk_forward(
        matchs, league_id="competition:football:fra:ligue1", season="2025",
        targets=cibles_football([1.5, 2.5]))


def test_les_premiers_matchs_sortent_faute_de_forme_anterieure(rejeu):
    """Aucune probabilité fabriquée : sans historique, on n'évalue pas."""
    assert rejeu.exclusions.get("INSUFFICIENT_DATA_no_prior_form", 0) > 0
    assert rejeu.n_predicted < rejeu.n_matches


def test_toutes_les_familles_partagent_la_meme_population(rejeu):
    """Même matrice, même match, même population — sauf le remboursé-si-nul, dont
    les nuls sortent par définition."""
    tailles = {cle: len(r.predictions) for cle, r in rejeu.runs.items()}
    hors_dnb = {c: n for c, n in tailles.items() if not c.startswith("DRAW_NO_BET")}
    assert len(set(hors_dnb.values())) == 1, tailles
    for cle, run in rejeu.runs.items():
        if cle.startswith("DRAW_NO_BET"):
            assert len(run.predictions) + run.n_void == rejeu.n_predicted


def test_la_data_quality_est_mesuree_et_non_supposee(rejeu):
    assert len(rejeu.data_qualities) == rejeu.n_predicted
    assert all(0.0 <= q <= 1.0 for q in rejeu.data_qualities)


def test_les_probabilites_de_chaque_cible_somment_a_un(rejeu):
    for cle, run in rejeu.runs.items():
        for probs, _ in run.predictions:
            assert abs(sum(probs.values()) - 1.0) < 1e-9, cle


def test_la_baseline_ne_voit_que_le_passe():
    """Test de FUITE, pas de forme : le futur est rendu radicalement différent du
    passé. Une baseline qui verrait tout l'échantillon annoncerait déjà le
    changement — et le critère `must_beat_baselines` deviendrait décoratif.

    Ici les huit premières rencontres n'ont aucun BTTS, les suivantes en ont
    toutes un. La baseline des premières prédictions doit valoir 0 %.
    """
    equipes = ["team:a", "team:b", "team:c", "team:d"]
    scores = [(2, 0), (0, 3), (1, 0), (0, 2), (3, 0), (0, 1), (2, 0), (0, 4)] + \
             [(1, 1), (2, 1), (1, 2), (3, 2), (2, 2), (1, 3), (2, 1), (1, 1)]
    matchs = [_match(i, gh, ga, home=equipes[i % 4], away=equipes[(i + 1) % 4])
              for i, (gh, ga) in enumerate(scores)]
    run = run_market_walk_forward(
        matchs, league_id="competition:football:fra:ligue1", season="2025",
        targets=[_cible("BTTS")]).runs["BTTS"]

    premieres = [freq for freq, _ in run.baseline[:3]]
    assert premieres, "il faut au moins une baseline pour tester la fuite"
    assert all(f["yes"] == 0.0 for f in premieres), premieres
    # …et elle finit par intégrer le changement, une fois qu'il est PASSÉ.
    assert run.baseline[-1][0]["yes"] > 0.0


# ── Métriques et verdict ─────────────────────────────────────────────────────

def test_les_metriques_declarent_ce_qui_n_est_pas_mesure(rejeu):
    m = build_target_metrics(rejeu.runs["BTTS"])
    assert m["probability_low_coverage"] == "NOT_MEASURED"
    assert m["n_eval"] > 0 and m["classes"] == ["yes", "no"]


def test_une_cible_sans_population_ne_produit_pas_de_metriques():
    vide = TargetRun(_cible("BTTS"))
    m = build_target_metrics(vide)
    assert m["n_eval"] == 0 and m["status"] == "NOT_EVALUATED"
    assert "brier" not in m, "aucun score ne doit être publié sans population"


def test_le_verdict_passe_par_la_politique_existante(rejeu):
    """Aucun verdict maison : mêmes critères et mêmes seuils que le 1X2.

    Un verdict local, même prudent, finirait par autoriser une famille à passer
    une porte que le marché principal n'a pas franchie.
    """
    from src.agents.quant.betting_engine.maturity import load_maturity_policy

    politique = load_maturity_policy()
    m = build_target_metrics(rejeu.runs["BTTS"])
    decision = verdict_de_famille(m, model_name="football_derived",
                                  model_version="football.derived.btts.v0",
                                  n_catalogue=rejeu.n_matches)
    noms = {c.name for c in decision.criteria}
    assert "min_sample_size" in noms and "max_calibration_error" in noms
    assert decision.policy_version == politique.config_version
    assert decision.status != "SUPPORTED"     # jamais promu par ce chemin


def test_la_clv_reste_non_mesurable_faute_de_cotes_historiques(rejeu):
    """§6 : la validation PROBABILISTE ne vaut pas validation ÉCONOMIQUE. Sans
    cotes historiques de Plus/Moins, la CLV n'est pas « mauvaise », elle est
    inexistante — et on ne reconstruit jamais une cote depuis un résultat."""
    m = build_target_metrics(rejeu.runs["TOTALS(line=2.5)"])
    decision = verdict_de_famille(m, model_name="football_derived",
                                  model_version="football.derived.totals.v0",
                                  n_catalogue=rejeu.n_matches)
    clv = next(c for c in decision.criteria if c.name == "positive_clv")
    assert clv.verdict.value == "NOT_MEASURABLE"


def test_chaque_famille_porte_sa_propre_identite_de_modele(rejeu):
    """Sans identité propre, la promotion d'une famille promouvrait les autres."""
    versions = set()
    for cle in ("BTTS", "TOTALS(line=2.5)", "MATCH_WINNER"):
        m = build_target_metrics(rejeu.runs[cle])
        famille = m["family"].lower()
        versions.add(f"football.derived.{famille}.v0")
    assert len(versions) == 3


# ── §1 : un PUSH n'est pas une donnée manquante ───────────────────────────────

def test_le_push_est_compte_separement_et_jamais_en_perte(rejeu):
    """La décision de policy, vérifiée là où elle se joue.

    Un nul rembourse un « remboursé si match nul » : le match a eu lieu, ses
    features étaient là, le marché s'est réglé. WIN, PUSH et LOSS sont trois
    règlements observés — pas deux règlements et une lacune.
    """
    m = build_target_metrics(rejeu.runs["DRAW_NO_BET(home)"])
    s = m["settlement"]

    assert s["push"] > 0
    assert s["win"] + s["loss"] == s["non_push_evaluated"]
    assert s["win"] + s["loss"] + s["push"] == s["events_with_usable_features"]
    assert 0 < s["push_rate"] < 1
    # Les issues évaluées ne contiennent JAMAIS le push déguisé en perte.
    assert m["outcome_distribution"]["no"] == s["loss"]


def test_la_couverture_de_donnees_ne_penalise_pas_le_push(rejeu):
    """`min_data_coverage` mesure les DONNÉES, pas la règle du marché. Avant
    correction, DNB tombait à 0,719 sur un corpus complet à 97 % — un marché sain
    recalé par un critère qui ne le concernait pas."""
    dnb = build_target_metrics(rejeu.runs["DRAW_NO_BET(home)"])
    btts = build_target_metrics(rejeu.runs["BTTS"])

    v_dnb = verdict_de_famille(dnb, model_name="x", model_version="football.derived.dnb.v0",
                               n_catalogue=rejeu.n_matches)
    v_btts = verdict_de_famille(btts, model_name="x", model_version="football.derived.btts.v0",
                                n_catalogue=rejeu.n_matches)
    couverture = {v.model_version: next(c.observed for c in v.criteria
                                        if c.name == "min_data_coverage")
                  for v in (v_dnb, v_btts)}
    assert len(set(couverture.values())) == 1, (
        f"le push ne doit rien coûter à la couverture : {couverture}")


def test_la_correction_ne_promeut_aucune_autre_famille(rejeu):
    """L'effet de bord qu'il fallait exclure : élargir le numérateur de couverture
    ne doit rien changer là où il n'y a pas de push."""
    for cle, run in rejeu.runs.items():
        m = build_target_metrics(run)
        if m["n_eval"] == 0:
            continue
        s = m["settlement"]
        if s["push"] == 0:
            assert s["events_with_usable_features"] == m["n_eval"], cle
        v = verdict_de_famille(m, model_name="x", model_version=f"v.{cle}",
                               n_catalogue=rejeu.n_matches)
        assert v.status != "SUPPORTED", cle
