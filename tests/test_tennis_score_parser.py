"""Lire un score de tennis sans jamais le compléter.

Le danger de ce parseur n'est pas d'échouer bruyamment : c'est de réussir sur un
score qui n'en est pas un. « 6-2 RET » se lit parfaitement comme une victoire en
un set, et apprend au modèle que des matchs se gagnent ainsi. Ces tests portent
donc surtout sur ce qui doit être REFUSÉ.

Tous les scores cités sont RÉELS, tirés du corpus embarqué.
"""

from __future__ import annotations

import pytest

from src.agents.quant.betting_engine.sports.tennis.score_parser import (
    StatutScore,
    parser_score,
)


# ══ Ce qui se lit ══════════════════════════════════════════════════════════
def test_un_score_complet_en_deux_sets():
    lu = parser_score("6-3 6-2", best_of=3)

    assert lu.statut is StatutScore.COMPLETE and lu.utilisable
    assert (lu.sets_p1, lu.sets_p2) == (2, 0)
    assert (lu.jeux_p1, lu.jeux_p2) == (12, 5)
    assert lu.total_sets == 2 and lu.total_jeux == 17
    assert lu.vainqueur == "p1" and lu.tiebreaks == 0


def test_le_tie_break_donne_le_score_du_perdant():
    """« 7-6(5) » : le perdant du jeu décisif a pris 5 points. C'est la
    convention universelle des archives, vérifiée sur 51 575 sets."""
    lu = parser_score("7-6(5) 6-1", best_of=3)

    assert lu.statut is StatutScore.COMPLETE
    assert lu.sets[0].a_tiebreak and lu.sets[0].tiebreak_perdant == 5
    assert lu.tiebreaks == 1 and lu.total_jeux == 20


def test_un_best_of_5_demande_trois_sets():
    lu = parser_score("6-2 6-2 6-7(9) 4-6 6-0", best_of=5)

    assert lu.statut is StatutScore.COMPLETE
    assert (lu.sets_p1, lu.sets_p2) == (3, 2) and lu.vainqueur == "p1"


# ══ Ce qui doit être refusé ════════════════════════════════════════════════
def test_un_abandon_n_est_pas_une_victoire_au_score():
    """« 6-2 RET » n'est pas une victoire 6-2 en deux sets. Compté comme un match
    normal, il apprend au modèle des victoires en un set — et fausse tout total
    de jeux et tout total de sets. Mesuré : 7 425 abandons dans le corpus."""
    lu = parser_score("6-2 RET", best_of=3)

    assert lu.statut is StatutScore.RETIREMENT
    assert not lu.utilisable
    assert lu.vainqueur is None            # personne n'a gagné AU SCORE
    assert lu.sets_p1 == 1                 # le score partiel reste lisible


def test_un_abandon_en_cours_de_set_conserve_son_score_partiel():
    lu = parser_score("6-7 7-6 1-1 RET", best_of=5)

    assert lu.statut is StatutScore.RETIREMENT
    assert lu.total_sets == 3 and lu.sets[2].gagnant is None


def test_un_forfait_n_a_aucun_jeu():
    lu = parser_score("W/O", best_of=3)

    assert lu.statut is StatutScore.WALKOVER
    assert lu.total_sets == 0 and lu.total_jeux == 0 and not lu.utilisable


def test_une_disqualification_est_distincte_d_un_abandon():
    """Les deux arrêtent le match, mais pas pour la même raison — et un rapport
    qui les confond ne peut plus dire lequel des deux augmente."""
    lu = parser_score("6-4 1-1 DEF", best_of=3)

    assert lu.statut is StatutScore.DEFAULT and not lu.utilisable


def test_un_score_qui_n_atteint_pas_le_format_est_incomplet():
    """Le cas le plus dangereux : chaque set se lit parfaitement, et pourtant le
    match n'est pas allé à son terme. Il ne ressemble pas à une erreur."""
    lu = parser_score("6-4 5-7", best_of=3)

    assert lu.statut is StatutScore.INCOMPLETE and not lu.utilisable
    assert "n'est pas à son terme" in lu.raison


def test_un_format_inconnu_interdit_de_conclure_a_la_completude():
    """17 435 matchs ATP se jouent en cinq sets : supposer best-of-3 par défaut
    déclarerait complets des matchs qui ne le sont pas."""
    lu = parser_score("6-3 6-2", best_of=None)

    assert lu.statut is StatutScore.INCOMPLETE
    assert "best_of" in lu.raison


@pytest.mark.parametrize("brut", ["UNK", "&nbsp;", "6-4 6-?", "6-1 ?-?", "6-4-6-2", ">"])
def test_les_formes_non_reconnues_sont_nommees_pas_ignorees(brut):
    """754 scores WTA sont dans ce cas. Les faire disparaître ferait croire à un
    corpus plus propre qu'il n'est."""
    lu = parser_score(brut, best_of=3)

    assert lu.statut is StatutScore.UNREADABLE and not lu.utilisable
    assert lu.sets == ()                   # rien de partiellement lu n'est conservé


def test_un_score_partiellement_lisible_est_entierement_refuse():
    """« 6-4 6-? » : le premier set se lit. Le garder reviendrait à inventer le
    second — pour la partie qu'on n'a justement pas lue."""
    lu = parser_score("6-4 6-?", best_of=3)

    assert lu.statut is StatutScore.UNREADABLE and lu.total_sets == 0


def test_l_absence_de_score_n_est_pas_une_illisibilite():
    """117 502 rencontres du corpus n'ont aucun score. « Pas de donnée » et
    « donnée que je ne sais pas lire » ne se réparent pas de la même façon."""
    assert parser_score(None, best_of=3).statut is StatutScore.ABSENT
    assert parser_score("   ", best_of=3).statut is StatutScore.ABSENT


# ══ Le commentaire ne peut que dégrader ════════════════════════════════════
def test_un_commentaire_d_abandon_degrade_un_score_apparemment_complet():
    """Les archives portent parfois « Retired » sur un score qui paraît fini."""
    lu = parser_score("6-3 6-2", best_of=3, comment="Retired")

    assert lu.statut is StatutScore.RETIREMENT and not lu.utilisable


def test_un_commentaire_completed_ne_rend_pas_lisible_un_score_illisible():
    """Une source qui se déclare complète ne le devient pas."""
    lu = parser_score("UNK", best_of=3, comment="Completed")

    assert lu.statut is StatutScore.UNREADABLE


# ══ La couverture réelle du corpus, mesurée ════════════════════════════════
def test_la_couverture_du_corpus_embarque_est_celle_mesuree():
    """Non pas un seuil à tenir, mais un TÉMOIN : si ce chiffre bouge, c'est le
    corpus ou le parseur qui a changé, et il faut savoir lequel."""
    from src.agents.quant.betting_engine.sports.tennis.elo_model import load_tennis_data
    from src.agents.quant.betting_engine.sports.tennis.score_parser import mesurer_couverture

    atp = mesurer_couverture(load_tennis_data("atp").matches)

    assert atp.total == 227933
    assert atp.utilisables == 151873
    assert atp.par_statut[StatutScore.RETIREMENT.value] == 4601
    assert atp.par_statut[StatutScore.WALKOVER.value] == 616
    # Aucune catégorie ne se perd : la somme boucle sur le corpus.
    assert sum(atp.par_statut.values()) == atp.total


# ══ Modèles de sets et de jeux : ce qui a été validé, et ce qui a été rejeté ══
def test_l_ordre_canonique_neutralise_le_biais_vainqueur_en_premier():
    """Le corpus range le VAINQUEUR en premier — `outcome` vaut « p1 » sur les
    227 933 rencontres ATP, sans exception. Un modèle qui traiterait p1 et p2
    comme deux camps apprendrait « p1 gagne toujours » : une fuite parfaite, un
    Brier de zéro, et une prédiction sans aucune valeur."""
    from collections import Counter

    from src.agents.quant.betting_engine.sports.tennis.elo_model import load_tennis_data
    from src.agents.quant.betting_engine.sports.tennis.game_model import rencontres_lisibles

    brut = load_tennis_data("atp").matches
    assert {m.outcome for m in brut} == {"p1"}          # le biais est bien là

    rencontres = rencontres_lisibles(brut[:20000])
    vainqueurs = Counter(r.vainqueur for r in rencontres)
    # Après remise en ordre canonique, aucun des deux camps ne domine.
    part_a = vainqueurs["a"] / sum(vainqueurs.values())
    assert 0.45 < part_a < 0.55, vainqueurs


def test_le_premier_set_n_est_pas_la_majorite_des_jeux():
    """Deux marchés distincts. Un joueur peut perdre le premier set et gagner
    plus de jeux sur la rencontre — les confondre mesurerait un marché à la
    place de l'autre."""
    from src.agents.quant.betting_engine.sports.tennis.game_model import rencontres_lisibles

    class _M:
        tourney_id, round, p1_name, p2_name = "t", "R32", "Alpha A.", "Beta B."
        score, best_of, comment = "3-6 6-4 6-4", 3, None
        tourney_date, surface, est_cible_d_evaluation, circuit = None, "Hard", False, "tour"

    r = rencontres_lisibles([_M()])[0]

    assert r.vainqueur == "a"                    # Alpha gagne le match
    assert r.premier_set == "b"                  # mais Beta gagne le premier set
    assert r.jeux_a == 15 and r.jeux_b == 14     # et les jeux sont serrés


def test_les_verdicts_tennis_sont_ceux_que_la_mesure_a_rendus():
    """Trois marchés sur cinq sont REJETÉS, et c'est le résultat principal :
    l'hypothèse d'indépendance des jeux suffit à dire QUI gagne un set, pas
    COMBIEN de jeux se joueront."""
    from src.agents.quant.betting_engine.sports.tennis.set_markets import (
        MESURES, verdicts,
    )

    rendus = verdicts()
    assert rendus["SET_WINNER"] == "VALIDATED"
    assert rendus["MATCH_SET_SCORE"] == "VALIDATED"
    assert rendus["TOTAL_SETS"] == "REJECTED_NO_SKILL"
    assert rendus["TOTAL_GAMES"] == "REJECTED_NO_SKILL"
    assert rendus["GAME_HANDICAP"] == "REJECTED_NO_SKILL"

    # Chaque ligne VALIDÉE tient les deux critères, sans exception.
    for m in MESURES:
        if m.verdict == "VALIDATED":
            assert m.bat_la_baseline and m.calibre, m


def test_une_famille_ne_se_valide_pas_sur_sa_meilleure_ligne():
    """Le `GAME_HANDICAP` ATP a une ligne à 0,036 d'ECE — et quatre au-dessus de
    0,08. Ne consigner que la première aurait validé la famille sur son meilleur
    échantillon, ce qui est exactement la sélection que la règle par ligne du
    football interdit déjà."""
    from src.agents.quant.betting_engine.sports.tennis.set_markets import (
        MESURES, famille, verdict_de_famille,
    )

    handicaps = [m for m in MESURES if famille(m.marche) == "GAME_HANDICAP"]
    assert any(m.calibre for m in handicaps)          # une ligne passe…
    assert not all(m.calibre for m in handicaps)      # …et la famille ne passe pas
    assert verdict_de_famille("GAME_HANDICAP").startswith("REJECTED")


def test_la_derivation_des_sets_reste_une_partition():
    from src.agents.quant.betting_engine.sports.tennis.game_model import (
        issues_sets, p_match, p_set, total_sets,
    )

    for p_jeu in (0.35, 0.5, 0.62, 0.75):
        ps = p_set(p_jeu)
        for best_of in (3, 5):
            assert sum(issues_sets(ps, best_of).values()) == pytest.approx(1.0, abs=1e-9)
            assert sum(total_sets(ps, best_of).values()) == pytest.approx(1.0, abs=1e-9)
        assert 0.0 <= p_match(ps, 3) <= 1.0
    assert p_set(0.5) == pytest.approx(0.5, abs=1e-9)     # symétrie exacte
