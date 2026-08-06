"""Une erreur ne doit plus coûter le tour entier.

Trois niveaux, du plus fin au plus grossier :

1. un OUTIL qui échoue rend un résultat d'erreur — le modèle le lit et contourne ;
2. le PROVIDER qui échoue déclenche une bascule, puis un repli sans outils ;
3. le FLUX qui casse est repris.

Le fil commun : à aucun moment l'utilisateur ne doit perdre son tour sur un
message brut qu'il ne peut pas exploiter. Soit le modèle tente autre chose, soit
il dit clairement qu'il n'a pas pu.
"""

from __future__ import annotations

import inspect
import json

import pytest

from src.orchestrator import graph as graph_module
from src.orchestrator.graph import tool_error_to_message

SOURCE = inspect.getsource(graph_module)


# ── niveau 1 : l'échec d'un outil est un RÉSULTAT ───────────────────────────────
@pytest.mark.parametrize("exc", [
    RuntimeError("panne interne"),
    ValueError("Canal ou utilisateur introuvable : 'U06KZGGL403'"),
    KeyError("champ_absent"),
    ConnectionError("provider injoignable"),
    TimeoutError("délai dépassé"),
    Exception(""),                       # échec sans message
])
def test_toute_exception_d_outil_devient_un_message(exc):
    """LangGraph ne rattrape par défaut que les arguments invalides et re-lève
    tout le reste : une panne réseau dans n'importe quel outil tuait le tour."""
    charge = json.loads(tool_error_to_message(exc))

    assert charge["status"] == "TOOL_ERROR"
    assert charge["error_type"] == type(exc).__name__
    assert charge["message"]                       # jamais vide
    assert "n'invente" in charge["note"].lower()


def test_le_message_d_erreur_interdit_de_le_prendre_pour_un_resultat():
    """Sans cette consigne, le modèle raconte l'échec comme une donnée — c'est le
    même piège que les serveurs MCP qui renvoient leur panne avec isError=False."""
    note = json.loads(tool_error_to_message(RuntimeError("x")))["note"]
    assert "pas un résultat" in note.lower() or "n'est pas un résultat" in note.lower()


def test_les_interruptions_de_graphe_ne_sont_pas_avalees():
    """`interrupt()` et `Command` passent par GraphBubbleUp : les rattraper
    casserait les confirmations utilisateur, qui ne sont pas des erreurs."""
    from langgraph.errors import GraphBubbleUp

    with pytest.raises(GraphBubbleUp):
        tool_error_to_message(GraphBubbleUp())


def test_le_handler_est_bien_branche_sur_le_ToolNode():
    """Le handler ne sert à rien s'il n'est pas passé à `ToolNode` : sans ce
    paramètre, le défaut de LangGraph reprend la main silencieusement."""
    assert "handle_tool_errors=tool_error_to_message" in SOURCE


# ── niveau 2 : le provider qui échoue ne termine pas le tour ────────────────────
def test_une_erreur_inconnue_declenche_une_bascule_avant_d_abandonner():
    """Avant : tout ce qui n'était ni rate-limit ni contexte faisait `raise`.
    Un modèle retiré ou un schéma d'outil refusé coûtait le tour entier."""
    assert "if not degraded:" in SOURCE
    assert "bascule sur" in SOURCE


def test_le_dernier_recours_repond_en_texte_sans_outils():
    """Un schéma d'outil rejeté par le provider est une cause fréquente : sans
    outils, le modèle peut encore expliquer ce qui s'est passé."""
    assert "if not stripped_tools and not force_text:" in SOURCE
    assert "dernière tentative sans" in SOURCE
    assert "N'invente aucun résultat" in SOURCE


def test_les_replis_sont_tentes_une_seule_fois():
    """Deux drapeaux, deux tentatives : sans eux la boucle réessaierait sans fin
    la même stratégie sur une panne durable."""
    assert "degraded = False" in SOURCE
    assert "stripped_tools = False" in SOURCE
    assert "degraded = True" in SOURCE
    assert "stripped_tools = True" in SOURCE


def test_l_ordre_des_strategies_va_du_moins_au_plus_degrade():
    """Reprise < bascule de provider < abandon des outils. Inverser ferait perdre
    les outils sur une simple coupure réseau."""
    i_transient = SOURCE.index("_TRANSIENT_MARKERS)")
    i_degraded = SOURCE.index("if not degraded:")
    i_stripped = SOURCE.index("if not stripped_tools and not force_text:")
    assert i_transient < i_degraded < i_stripped


# ── ce qui doit TOUJOURS s'arrêter ──────────────────────────────────────────────
def test_les_interruptions_utilisateur_ne_sont_pas_rattrapees():
    """`KeyboardInterrupt` et `SystemExit` ne dérivent pas d'`Exception` : ils ne
    passent donc jamais par le handler. Ce test fige cette propriété du langage,
    dont dépend la possibilité d'interrompre Axon au clavier."""
    assert not issubclass(KeyboardInterrupt, Exception)
    assert not issubclass(SystemExit, Exception)


# ── niveau 3 : mesurer, pour ne plus raisonner à l'impression ───────────────────
def test_chaque_strategie_est_journalisee():
    """« gemini foire tout le temps » est peut-être vrai, mais invérifiable sans
    compter — et on ne saurait pas non plus ce qu'un correctif a changé."""
    for strategie in ('"retry"', '"provider_switch"', '"no_tools"', '"none"'):
        assert f"_log_failure(" in SOURCE and strategie in SOURCE, strategie


def test_le_journal_ne_casse_jamais_le_tour_qu_il_observe(tmp_path):
    """Un journal qui lève serait exactement le défaut qu'on corrige."""
    from src.infra.failure_log import record

    record(backend="x", error_type="T", message="m", strategy="retry",
           recovered=True, path=tmp_path / "sous" / "dossier" / "absent.jsonl")


def test_le_resume_agrege_par_backend(tmp_path):
    from src.infra.failure_log import record, summary

    cible = tmp_path / "f.jsonl"
    record(backend="gemini", error_type="BadRequest", message="m",
           strategy="provider_switch", recovered=True, path=cible)
    record(backend="gemini", error_type="BadRequest", message="m",
           strategy="none", recovered=False, path=cible)

    s = summary(cible)
    assert s["gemini"]["total"] == 2
    assert s["gemini"]["recovery_rate"] == 0.5
    assert s["gemini"]["types"]["BadRequest"] == 2


def test_une_ligne_corrompue_n_invalide_pas_le_journal(tmp_path):
    """Un fichier tronqué par un arrêt brutal doit rester exploitable."""
    from src.infra.failure_log import record, summary

    cible = tmp_path / "f.jsonl"
    record(backend="gemini", error_type="T", message="m", strategy="retry",
           recovered=True, path=cible)
    with cible.open("a", encoding="utf-8") as fh:
        fh.write("{ceci n'est pas du json\n")

    assert summary(cible)["gemini"]["total"] == 1
