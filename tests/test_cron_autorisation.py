"""Une tâche planifiée n'a personne devant l'écran — deux conséquences.

PREMIÈRE : elle ne peut pas répondre à une demande de confirmation. Ses
permissions shell doivent donc être DÉCLARÉES par l'utilisateur dans la tâche.
Écrites par lui, jamais par le modèle : c'est ce qui distingue une permission
d'une autorisation que l'agent s'accorderait tout seul.

SECONDE : un outil refusé ne lève PAS d'exception, il rend un statut. Le
`try/except` du démon ne voyait donc rien, et la tâche loguait `status: "ok"` en
n'ayant rien fait. Un succès mensonger est pire qu'un échec bruyant : il ne se
voit nulle part, et la tâche paraît tourner pendant des semaines.
"""
from __future__ import annotations

import json

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from src.agents.shell import autorisation
from src.cron_daemon import _refus_d_outil


@pytest.fixture(autouse=True)
def propre():
    autorisation.reinitialiser()
    yield
    autorisation.reinitialiser()


def _resultat(**charge):
    return ToolMessage(content=json.dumps(charge), tool_call_id="tc", name="shell_run")


# ── Les refus remontent ──────────────────────────────────────────────────────
@pytest.mark.parametrize("statut", ["requires_confirmation", "blocked"])
def test_un_refus_d_outil_est_repere(statut):
    messages = [_resultat(status=statut, command="rm -rf /var/log")]
    assert _refus_d_outil(messages) == ["rm -rf /var/log"]


def test_un_tour_sans_refus_ne_signale_rien():
    messages = [_resultat(status="ok", stdout="tout va bien"),
                AIMessage(content="terminé")]
    assert _refus_d_outil(messages) == []


def test_un_contenu_qui_n_est_pas_du_json_ne_casse_rien():
    assert _refus_d_outil([AIMessage(content="texte libre {pas du json")]) == []


def test_plusieurs_refus_sont_tous_comptes():
    """Le log doit dire COMBIEN, pas seulement qu'il y en a eu : une tâche dont
    une commande sur dix a été refusée n'est pas dans le même état qu'une tâche
    entièrement bloquée."""
    messages = [_resultat(status="blocked", command="rm -rf a"),
                _resultat(status="ok", stdout="…"),
                _resultat(status="requires_confirmation", command="rm -rf b")]
    assert _refus_d_outil(messages) == ["rm -rf a", "rm -rf b"]


def test_le_demon_transforme_un_refus_en_echec():
    """Le code qui décide du statut logué. Vérifié sur le source parce que la
    boucle du démon exige un LLM et un scheduler pour tourner."""
    import inspect

    from src import cron_daemon

    source = inspect.getsource(cron_daemon._run_task)
    assert "_refus_d_outil" in source, "le démon ne lit pas les refus"
    position_refus = source.index("_refus_d_outil")
    position_statut = source.index('log_entry["status"] = "skipped" if stop else "ok"')
    assert position_refus > position_statut, (
        "le refus doit ÉCRASER le statut optimiste, donc être lu après lui")


# ── Les permissions déclarées ────────────────────────────────────────────────
def test_une_tache_ne_peut_lancer_que_ce_qu_elle_a_declare():
    autorisation.declarer("cron:abc", ["docker system prune -af"])
    assert autorisation.est_autorisee("docker system prune -af")
    assert not autorisation.est_autorisee("rm -rf /var/log")


def test_sans_declaration_une_tache_n_a_aucune_permission():
    """Le défaut, et il est volontaire : une commande destructive lancée sans
    personne devant l'écran est le cas où l'on veut une barrière, pas une
    exemption."""
    autorisation.declarer("cron:abc", [])
    assert not autorisation.est_autorisee("rm -rf /var/log")


def test_les_permissions_sont_retirees_a_la_fin_de_la_tache():
    """Une permission qui survivrait profiterait au tour suivant, qui ne l'a pas
    demandée — et à toute autre tâche du même processus."""
    import inspect

    from src import cron_daemon

    source = inspect.getsource(cron_daemon._run_task)
    assert "declarer(source_autorisation" in source
    assert "retirer(source_autorisation)" in source
    assert "finally:" in source, (
        "le retrait doit avoir lieu même si la tâche lève")


def test_le_champ_declaratif_existe_dans_le_type_de_tache():
    from src.agents.cron.type import CronTask

    assert "commandes_autorisees" in CronTask.__annotations__


def test_une_tache_ancienne_sans_le_champ_fonctionne():
    """`TypedDict` : le champ est optionnel, les tâches déjà enregistrées n'ont
    pas à être migrées."""
    tache = {"id": "cron_vieille", "prompt": "…"}
    autorisation.declarer(f"cron:{tache['id']}",
                          list(tache.get("commandes_autorisees") or []))
    assert not autorisation.est_autorisee("rm -rf /")
