"""Le modèle demandait la permission d'écrire — trois fois, reformulée à chaque
tour.

Le flux n'était pas en cause : il recevait bien `{"status": "answered",
"answers": {…: "Oui"}}` avec l'ordre de ne pas redemander. Ce qui manquait, c'est
qu'aucune ligne de son prompt ne lui disait que l'utilisateur relit CHAQUE diff
avant écriture. Ne connaissant pas ce canal, il en inventait un.

Un garde comptait les tours de questions. Il traitait le symptôme et alourdissait
la boucle pour rien : retiré une fois la cause dite.
"""
from __future__ import annotations


# ── la cause, pas le symptôme ─────────────────────────────────────────────────
def test_le_prompt_dit_que_lecriture_est_deja_relue():
    """Le garde ci-dessus n'explique pas POURQUOI le modèle demandait.

    Le flux était correct — il recevait bien `{"status": "answered", "answers":
    {…: "Oui"}}`. Ce qui manquait, c'est qu'aucune ligne ne lui disait que
    l'utilisateur relit CHAQUE diff avant écriture. Ne connaissant pas ce canal,
    il en inventait un : il demandait la permission d'écrire.
    """
    from src.agents.coding.prompts.base import BASE_PROMPT

    assert "MONTRÉ à" in BASE_PROMPT, "le mécanisme de revue doit être énoncé"
    assert "permission d'écrire" in BASE_PROMPT
    assert "revue du diff" in BASE_PROMPT


def test_le_prompt_annonce_les_statuts_que_les_outils_rendent():
    """`applied` et `unchanged` sont apparus avec la revue et le refus du no-op.
    Un statut qu'un modèle ne sait pas lire est un statut qu'il interprète."""
    from src.agents.coding.prompts.base import BASE_PROMPT

    for statut in ("proposed", "rejected", "applied", "unchanged"):
        assert statut in BASE_PROMPT, statut


# ── le plan ne doit exister que s'il sert ────────────────────────────────────
def test_le_chemin_court_couvre_la_CREATION_dun_fichier():
    """Il ne montrait que des modifications — « change la valeur X », « corrige ce
    bug » — et ses étapes passaient par `edit_file`, qui ne marche pas sur un
    fichier absent.

    « écris un script tri.py qui trie une liste » remplit pourtant ses critères :
    un fichier, tâche claire, aucune dépendance. Ne s'y reconnaissant pas, le
    modèle tombait dans le chemin normal — qui exigeait un plan.
    """
    from src.agents.coding.prompts.base import BASE_PROMPT

    court = BASE_PROMPT[BASE_PROMPT.index("LE CHEMIN COURT"):
                        BASE_PROMPT.index("LE CHEMIN NORMAL")]
    assert "CRÉER un fichier" in court
    assert "propose_file_change" in court
    assert "Pas de plan" in court


def test_le_nombre_detapes_nest_plus_impose():
    """« 3-8 étapes concrètes » forçait à gonfler un plan de deux actions. Vécu :
    « 2. Marquer l'étape comme terminée après validation du fichier créé »."""
    from src.agents.coding.prompts.base import BASE_PROMPT

    assert "3-8 étapes" not in BASE_PROMPT
    # Le prompt est enveloppé : on vise un fragment qui tient sur une ligne.
    assert "Autant d'étapes qu'il y a d'actions" in BASE_PROMPT
    assert "travail imaginaire" in BASE_PROMPT


def test_une_etape_de_plan_porte_sur_le_projet_pas_sur_le_plan():
    """La règle, pas sa formulation : le test verrouillait « action sur le
    PROJET » et est tombé sur « agit sur le PROJET », à sens identique."""
    from src.agents.coding.prompts.base import BASE_PROMPT

    assert "PROJET" in BASE_PROMPT
    assert "jamais sur le plan lui-même" in BASE_PROMPT
    assert "marquer l'étape terminée" in BASE_PROMPT.lower()
