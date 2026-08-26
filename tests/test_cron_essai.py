"""`axon cron-test` : lancer une tâche maintenant, sans effets.

Répond à « est-ce que ma tâche marche ? » sans attendre son déclenchement.

L'exigence qui commande la conception : l'essai traverse le MÊME chemin que
l'exécution réelle — outils, autorisations, comparaison de veille — et ne
suspend que les effets. Un essai qui contournerait ces chemins dirait « ça
marche » d'une tâche qui serait bloquée en production.
"""
from __future__ import annotations

import inspect

from src.agents.cron.essai import rendre


def test_l_essai_traverse_le_meme_chemin_que_l_execution():
    """Vérifié sur le code : `essayer` appelle `_run_task`, il ne réimplémente
    pas une exécution parallèle qui divergerait au premier changement."""
    from src.agents.cron import essai

    source = inspect.getsource(essai.essayer)
    assert "_run_task" in source
    assert "essai=True" in source


def test_les_effets_sont_suspendus_et_eux_seuls():
    """Notification, persistance de l'état, journal et arrêt automatique : tout
    ce qui laisse une trace est conditionné. Le reste tourne."""
    from src import cron_daemon

    source = inspect.getsource(cron_daemon._run_task)
    for effet, garde in [
        ("_send_notification", "if essai:"),
        ("update_task(task[\"id\"], last_run", "if not essai:"),
        ("append_log", "if not essai:"),
    ]:
        assert effet in source, f"{effet} a disparu"
    assert "if not essai:" in source and "if essai:" in source
    assert "if stop and not essai:" in source, (
        "un essai désactiverait la tâche en atteignant sa condition d'arrêt")


def test_les_autorisations_shell_sont_declarees_meme_en_essai():
    """Le point le plus important : sans elles, l'essai montrerait des refus qui
    n'auraient pas lieu en production — ou l'inverse."""
    from src import cron_daemon

    source = inspect.getsource(cron_daemon._run_task)
    position_declaration = source.index("declarer(source_autorisation")
    position_essai = source.index("if not task.get(\"active\") and not essai")
    assert position_declaration > position_essai
    assert "if essai" not in source[position_declaration - 200:position_declaration], (
        "la déclaration des permissions est conditionnée à l'essai")


def test_une_tache_arretee_reste_essayable():
    """C'est même le cas le plus utile : on la répare avant de la réactiver."""
    from src import cron_daemon

    source = inspect.getsource(cron_daemon._run_task)
    assert 'if not task.get("active") and not essai:' in source


# ── Le compte rendu ──────────────────────────────────────────────────────────
def test_le_compte_rendu_dit_ce_qui_AURAIT_ete_envoye():
    texte = rendre({
        "status": "essai", "id": "cron_x", "description": "Prix", "active": True,
        "duree_ms": 120, "resultat": "ok",
        "aurait_notifie": {"canaux": ["desktop", "slack"], "message": "le prix a baissé"},
    })
    assert "AURAIT PRÉVENU" in texte
    assert "desktop, slack" in texte
    assert "le prix a baissé" in texte


def test_le_compte_rendu_dit_quand_rien_n_aurait_ete_envoye():
    texte = rendre({"status": "essai", "id": "x", "description": "Prix",
                    "active": True, "duree_ms": 10, "resultat": "inchangé"})
    assert "n'aurait rien envoyé" in texte


def test_une_tache_inactive_est_signalee():
    """Sinon on essaie une tâche qui marche, on est rassuré, et elle ne tourne
    jamais."""
    texte = rendre({"status": "essai", "id": "x", "description": "Prix",
                    "active": False, "duree_ms": 10, "resultat": ""})
    assert "elle ne tournera pas" in texte


def test_le_verdict_de_veille_est_montre():
    texte = rendre({
        "status": "essai", "id": "x", "description": "Prix", "active": True,
        "duree_ms": 10, "resultat": "",
        "surveillance": {"valeur": "1199 €", "raison": "baisse : 1299.0 → 1199.0"},
    })
    assert "1199 €" in texte and "baisse" in texte


def test_une_tache_introuvable_le_dit():
    assert "Aucune tâche" in rendre({"status": "introuvable", "id": "cron_absent"})


def test_la_commande_existe_dans_le_point_d_entree():
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "src" / "ui" / "main.py").read_text()
    assert '"cron-test"' in source
    assert "from src.agents.cron.essai import essayer, rendre" in source
