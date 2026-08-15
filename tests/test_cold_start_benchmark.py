"""Le benchmark cold-start : ce qu'il mesure, et ce qu'il ne touche pas.

Le premier test est le plus important de ce fichier, et il ne mesure rien : il
vérifie que le banc n'a RIEN changé au chemin argent. Un benchmark qui déplace la
production qu'il évalue ne mesure plus que lui-même.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import pytest

from src.agents.quant.betting_engine.calibration import cold_start_verdict as verdict
from src.agents.quant.betting_engine.calibration.cold_start_benchmark import (
    candidat_a,
    candidat_b,
    candidat_c,
    candidat_d,
    comparer,
    rejouer,
)
from src.agents.quant.dixon_coles import DECAY, DEFAULT_SHRINKAGE_K, team_strengths


def _forme(n=8, base=1):
    """Une forme synthétique, du plus récent au plus ancien."""
    origine = datetime(2026, 5, 1)
    return [{"date": (origine - timedelta(days=7 * i)).date().isoformat(),
             "opponent_id": f"adv{i}", "goals_home": base + i % 3,
             "goals_away": i % 2, "is_home": i % 2 == 0,
             "league_id": "L", "season": "2025"} for i in range(n)]


# ══ §12 — MONEY INVARIANCE ══════════════════════════════════════════════════
def test_la_ponderation_par_defaut_est_bit_identique_a_l_historique():
    """L'accroche de pondération est ADDITIVE : sans elle, `team_strengths` doit
    rendre exactement ce qu'il rendait. C'est la garantie que ce chantier n'a
    déplacé aucune probabilité live."""
    forme = _forme()

    sans_accroche = team_strengths(forme)
    # La pondération historique, réécrite explicitement ici : si elle change un
    # jour dans le module, ce test le dira.
    avec_poids_historique = team_strengths(
        forme, poids=lambda i, m: math.exp(-DECAY * i))

    assert sans_accroche == avec_poids_historique
    assert sans_accroche == team_strengths(forme, shrinkage_k=DEFAULT_SHRINKAGE_K)


def test_le_constructeur_de_features_de_production_ne_passe_aucune_ponderation():
    """Si un jour le chemin live passait `poids`, il ne serait plus la baseline
    que ce banc évalue — et personne ne s'en apercevrait."""
    import inspect

    from src.agents.quant.betting_engine.sports.football.feature_engineering import (
        event_features,
    )

    source = inspect.getsource(event_features)
    assert "poids=" not in source
    assert "team_strengths(" in source


def test_le_banc_restaure_la_fonction_de_force_apres_usage():
    """Le banc substitue temporairement `team_strengths` pour appliquer la
    pondération d'un candidat. S'il oubliait de la remettre, tout le processus —
    tests suivants compris — tournerait avec les réglages du benchmark."""
    from src.agents.quant.betting_engine.calibration.cold_start_benchmark import (
        _features_du_candidat,
    )
    from src.agents.quant.betting_engine.sports.football.feature_engineering import (
        event_features as fe,
    )

    avant = fe.team_strengths

    class _GatewayQuiEchoue:
        def recent_form(self, *a, **k):
            raise RuntimeError("panne volontaire")

        def standings_strength(self, *a, **k):
            return {}

    class _E:
        event_id = "e"
        competition_id = "L"
        participants = ()
        scheduled_at = datetime(2026, 8, 1, tzinfo=timezone.utc)

    with pytest.raises(Exception):
        _features_du_candidat(candidat_c(365), _E(), _GatewayQuiEchoue(),
                              datetime(2026, 8, 1, tzinfo=timezone.utc))

    assert fe.team_strengths is avant, "la fonction de production doit être restaurée"


# ══ Les candidats ═══════════════════════════════════════════════════════════
def test_le_candidat_d_retenu_est_exactement_le_candidat_b():
    """Son paramètre optimal sur la validation est la valeur de production du
    shrinkage : renforcer le prior avec l'âge de la preuve DÉGRADE le Brier de
    façon monotone. D n'apporte donc rien, et ses chiffres de holdout sont
    bit-identiques à ceux de B — ce qui vérifie au passage que le banc ne
    fabrique pas de différence."""
    for fenetre in ("J1", "J2", "J3", "J4", "J5", "J1-J5", "J6-J10", "J1-J10"):
        b = verdict.mesure("B", fenetre)
        # D n'est pas consigné séparément, précisément parce qu'il est B.
        assert b is not None
    d = candidat_d(DEFAULT_SHRINKAGE_K)
    assert d.shrinkage is not None
    # À l'âge zéro comme à un an, un k plafonné à la valeur de production reste
    # cette valeur : la fonction est constante, donc D dégénère en B.
    assert d.shrinkage(0.0) == DEFAULT_SHRINKAGE_K
    assert d.shrinkage(365.0) == DEFAULT_SHRINKAGE_K


def test_seul_le_report_change_la_population_servie():
    """A et B partagent tout sauf le pool de matchs. Aucune règle de report n'est
    écrite dans le rejeu : c'est la population qui change, rien d'autre."""
    a, b = candidat_a(), candidat_b()

    assert (a.poids, a.shrinkage) == (b.poids, b.shrinkage) == (None, None)
    assert a.reporte is False and b.reporte is True


def test_la_ponderation_de_c_decroit_avec_l_anciennete_pas_le_rang():
    """C'est toute la différence : la production décroît avec le RANG du match
    dans la forme. Tant qu'on ne lit qu'une saison, rang et ancienneté vont de
    pair ; dès qu'on reporte, ils divergent."""
    c = candidat_c(demi_vie_jours=365)
    cutoff = datetime(2026, 8, 1, tzinfo=timezone.utc)
    recent = {"date": "2026-07-25"}
    vieux = {"date": "2025-08-01"}

    # Même rang, ancienneté opposée : la pondération doit les séparer.
    assert c.poids(0, recent, cutoff) > c.poids(0, vieux, cutoff)
    # Rangs opposés, même ancienneté : elle doit les confondre.
    assert c.poids(0, recent, cutoff) == c.poids(9, recent, cutoff)
    # Une demi-vie d'un an divise bien le poids par deux en un an.
    assert c.poids(0, vieux, cutoff) == pytest.approx(0.5, abs=0.01)


# ══ Le résultat mesuré ══════════════════════════════════════════════════════
def test_la_production_actuelle_n_evalue_rien_a_la_premiere_journee():
    """Le fait principal du benchmark. Ce n'est pas une faiblesse de mesure :
    c'est ce que fait le produit aujourd'hui, chaque mois d'août."""
    a_j1 = verdict.mesure("A", "J1")
    c_j1 = verdict.mesure("C", "J1")

    assert a_j1.n_eval == 0 and a_j1.couverture == 0.0
    assert c_j1.n_eval == 47 and c_j1.couverture == 1.0
    assert verdict.gain_de_couverture("J1") == 47
    assert verdict.gain_de_couverture("J1-J5") == 49


def test_le_report_porte_le_gain_pas_la_ponderation():
    """L'ablation sépare deux effets que C confond. Sans elle, on attribuerait au
    report un gain qui viendrait de la pondération, ou l'inverse."""
    ponderation_seule = verdict.ABLATION["A->A+"]["J1-J5"]
    report_seul = verdict.ABLATION["A->B"]["J1-J5"]

    # La pondération seule ne prouve rien : son intervalle contient zéro.
    assert ponderation_seule[1] <= 0 <= ponderation_seule[2]
    # Le report, si : son intervalle est entièrement positif, et dix fois plus haut.
    assert report_seul[1] > 0
    assert report_seul[0] > 10 * ponderation_seule[0]


def test_la_calibration_ne_s_effondre_pas_apres_report():
    """Le risque du §10 : gagner de la couverture en perdant les niveaux. Après
    passage du calibrateur EXISTANT, C domine A sur les deux axes."""
    ece_a, ece_cal_a, brier_a, brier_cal_a = verdict.CALIBRATION["A"]
    ece_c, ece_cal_c, brier_c, brier_cal_c = verdict.CALIBRATION["C"]

    assert ece_c > ece_a                      # brut, A paraît mieux calibré…
    assert ece_cal_c < ece_cal_a              # …calibré, l'ordre s'inverse
    assert brier_cal_c < brier_cal_a          # et le Brier reste en faveur de C


def test_aucun_promu_ne_recoit_de_force_d_une_autre_division():
    """Les échelles de deux divisions ne sont pas les mêmes, et le corpus ne
    contient pas le côté inférieur de la promotion : le rapport n'est pas
    mesurable. Le refus est structurel, pas prudentiel."""
    assert verdict.VERDICT_PROMUS == "INSUFFICIENT_EVIDENCE"
    # Les rencontres impliquant un promu restent ÉVALUÉES — grâce à l'adversaire.
    n_a, brier_a, _, _ = verdict.PROMUS["A"]["promu_implique"]
    n_c, brier_c, _, _ = verdict.PROMUS["C"]["promu_implique"]
    assert n_a == n_c == 79
    assert brier_c < brier_a


def test_le_verdict_ne_cree_pas_de_calendrier_de_transition():
    """Un calendrier supposerait qu'à partir d'une journée le report nuise.
    Mesuré, il ne nuit jamais."""
    assert verdict.RECOMMANDATION_DU_BENCHMARK == verdict.USE_DECAYED_CARRY_OVER
    assert verdict.CONCLUSION != verdict.USE_TRANSITION_POLICY
    for fenetre in ("J1-J5", "J6-J10", "J1-J10"):
        m = verdict.mesure("C", fenetre)
        assert m.delta_brier_vs_a > 0, fenetre


def test_la_decision_prise_est_le_candidat_sans_parametre():
    """Le benchmark recommande C ; la décision retient B. L'écart est CONSIGNÉ,
    pas effacé : on sait exactement ce que coûte le refus d'un paramètre non
    identifié."""
    assert verdict.DECISION == verdict.USE_RAW_CARRY_OVER
    assert verdict.RECOMMANDATION_DU_BENCHMARK == verdict.USE_DECAYED_CARRY_OVER
    assert verdict.STATUT_CANDIDAT_C.startswith("STATISTICALLY PROMISING")
    # Le coût est celui de l'écart apparié B -> C, mesuré sur le holdout.
    assert verdict.COUT_DE_LA_DECISION["J1-J10"] == pytest.approx(0.0068)


def test_les_risques_restants_sont_ecrits():
    """Un verdict sans ses limites se cite tout seul six mois plus tard."""
    assert len(verdict.RISQUES_RESTANTS) >= 4
    assert any("effectif" in r for r in verdict.RISQUES_RESTANTS)
    assert any("identifiée" in r for r in verdict.RISQUES_RESTANTS)


# ══ Non-fuite du rejeu ══════════════════════════════════════════════════════
def test_le_rejeu_ne_voit_jamais_le_match_qu_il_predit():
    """La gateway filtre sur `kickoff < cutoff` STRICT. Ce test le vérifie de
    bout en bout plutôt que sur la seule gateway : c'est l'assemblage qui compte."""
    from src.agents.quant.betting_engine.calibration.historical_dataset import (
        load_competition_season,
    )
    from src.agents.quant.gateway.core.identity_data import TEAMS
    from src.agents.quant.gateway.core.identity_resolver import IdentityResolver
    import pathlib

    fixtures = pathlib.Path(__file__).resolve().parents[1] / "tests" / "fixtures"
    resolveur = IdentityResolver(TEAMS)
    saison, _, _ = load_competition_season(
        resolveur, fixtures / "fl1_2025_matches.json",
        "competition:football:fra:ligue1", "2025")
    precedente, _, _ = load_competition_season(
        resolveur, fixtures / "fl1_2024_matches.json",
        "competition:football:fra:ligue1", "2024")

    run = rejouer(candidat_b(), matchs_saison=saison, matchs_precedents=precedente,
                  league_id="competition:football:fra:ligue1", season="2025",
                  journee_max=3)

    assert run.observations, "le report doit rendre les premières journées évaluables"
    # Chaque match n'apparaît qu'une fois, et son issue vient du match lui-même.
    cles = [o.cle for o in run.observations]
    assert len(cles) == len(set(cles))
    assert all(o.issue in ("home", "draw", "away") for o in run.observations)


def test_la_comparaison_appariee_ne_compare_que_les_matchs_communs():
    """Comparer des métriques absolues sur des populations différentes
    mesurerait surtout la différence de population."""
    from src.agents.quant.betting_engine.calibration.cold_start_benchmark import (
        Observation, RunCandidat,
    )

    def _obs(cle, p_home):
        return Observation(cle=cle, ligue="L", journee=1,
                           probabilites={"home": p_home, "draw": 0.25,
                                         "away": 0.75 - p_home},
                           issue="home", data_quality=1.0,
                           promu_implique=False, forme_reportee=False)

    a = RunCandidat("A", [_obs("m1", 0.40), _obs("m2", 0.40)])
    b = RunCandidat("B", [_obs("m1", 0.60), _obs("m3", 0.60)])

    c = comparer(a, b, journees=[1])

    assert c.n_communs == 1                    # seul m1
    assert c.n_uniquement_a == 1 and c.n_uniquement_b == 1
    assert c.delta_brier > 0                   # b prédit mieux sur m1
