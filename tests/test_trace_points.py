"""Ce que les points d'émission LISENT, plutôt que ce qu'ils supposent.

Le défaut d'origine tient en une phrase : un refus d'outil rend un STATUT, il ne
lève pas. Une tâche cron a donc logué « ok » alors que toutes ses commandes
avaient été bloquées. La trace ne vaut que si elle lit ce statut au seul endroit
où tous les résultats passent — et si elle distingue « vérifié » de « personne ne
sait vérifier ça ».
"""

from langchain_core.messages import ToolMessage

from src.infra import trace
from src.orchestrator.tool_node import _verdict
from src.orchestrator.verification import sait_verifier


def _resultat(charge: str, statut: str = "success") -> ToolMessage:
    return ToolMessage(content=charge, tool_call_id="1", name="shell_run",
                       status=statut)


def test_un_refus_est_lu_comme_un_refus():
    """`blocked` : le garde a tranché, l'outil n'a pas tourné."""
    policy, resultat, code = _verdict(_resultat('{"status": "blocked", "command": "rm -rf /"}'))
    assert (policy, resultat, code) == (trace.REFUSE, trace.BLOQUE, "blocked")


def test_une_confirmation_attendue_n_est_pas_un_succes():
    policy, resultat, code = _verdict(
        _resultat('{"status": "requires_confirmation", "command": "rm x"}'))
    assert (policy, resultat) == (trace.A_CONFIRMER, trace.BLOQUE)
    assert code == "requires_confirmation"


def test_une_erreur_d_outil_est_une_erreur():
    policy, resultat, code = _verdict(_resultat("boum", statut="error"))
    assert (policy, resultat, code) == (trace.AUTORISE, trace.ERREUR, "tool_error")


def test_un_resultat_ordinaire_passe_pour_ce_qu_il_est():
    assert _verdict(_resultat("3 fichiers trouvés")) == (trace.AUTORISE, trace.OK, "")
    assert _verdict(_resultat('{"status": "ok", "n": 3}')) == (
        trace.AUTORISE, trace.OK, "")


def test_un_json_casse_ne_fait_pas_echouer_la_lecture():
    """Un contenu qui commence par `{` sans être du JSON ne doit pas lever :
    c'est le journal qui casserait le tour qu'il observe."""
    assert _verdict(_resultat('{ceci n\'est pas du json')) == (
        trace.AUTORISE, trace.OK, "")


def test_un_code_d_erreur_reste_court_et_groupable():
    """Ce qui se compte doit se grouper. Un message complet donnerait une ligne
    distincte par occurrence, et le total se perdrait."""
    _, _, code = _verdict(_resultat(
        '{"status": "blocked", "reason": "une explication très longue qui varie '
        'à chaque appel selon la commande et son contexte"}'))
    assert code == "blocked"


# ── L'honnêteté de la colonne `verification` ─────────────────────────────────
def test_on_sait_dire_ce_qu_on_ne_sait_pas_verifier():
    """`verifier()` ne couvre que `.py` et `.json`.

    Écrire `ok` pour un `.ts` ferait passer deux extensions pour une garantie
    générale, et le trou ne se compterait jamais.
    """
    assert sait_verifier("/tmp/a.py")
    assert sait_verifier("/tmp/a.json")
    assert not sait_verifier("/tmp/a.ts")
    assert not sait_verifier("/tmp/Makefile")


# ── Le point d'émission ne casse jamais le lot qu'il observe ─────────────────
def test_une_panne_de_la_trace_n_emporte_pas_le_lot_d_outils():
    """La conséquence serait pire qu'une ligne perdue.

    `_inscrire_les_appels` passe par `src.ui.journal` pour nommer la cible. Si
    cet import ou cet appel échoue — écran absent, module déplacé — le lot
    d'outils entier échouerait. Le journal casserait le tour qu'il observe :
    exactement le défaut qu'il existe pour montrer.
    """
    from src.orchestrator import tool_node

    # `tc_by_id` n'est pas un dict : `.get` n'existe pas, l'intérieur lève.
    tool_node._inscrire_les_appels(
        [_resultat("ok")], tc_by_id=object(), latence_ms=0, lot=1)


def test_un_refus_traverse_le_noeud_jusqu_a_la_trace(tmp_path, monkeypatch):
    """De bout en bout : un outil qui refuse laisse une ligne `deny`.

    Le test qui compte, parce que le défaut d'origine n'était pas dans la
    lecture du statut mais dans le fait que personne ne la faisait.
    """
    import json as _json

    from langchain_core.messages import AIMessage
    from langchain_core.tools import tool as lc_tool
    from langgraph.graph import END, START, MessagesState, StateGraph

    from src.orchestrator.tool_node import CachedToolNode

    chemin = tmp_path / "decisions.jsonl"
    monkeypatch.setattr(trace, "FICHIER", chemin)

    @lc_tool("shell_run")
    def shell_run(command: str) -> str:
        """Exécute une commande."""
        return _json.dumps({"status": "blocked", "command": command})

    graphe = StateGraph(MessagesState)
    graphe.add_node("tools", CachedToolNode([shell_run]))
    graphe.add_edge(START, "tools")
    graphe.add_edge("tools", END)
    appel = AIMessage(content="", tool_calls=[
        {"name": "shell_run", "args": {"command": "rm -rf /"}, "id": "a1"}])

    trace.nouveau_run("tui")
    graphe.compile().invoke({"messages": [appel]})

    lignes = trace.lire(fichier=chemin)
    assert len(lignes) == 1
    assert lignes[0]["policy"] == trace.REFUSE
    assert lignes[0]["resultat"] == trace.BLOQUE
    assert lignes[0]["outil"] == "shell_run"
    assert lignes[0]["erreur"] == "blocked"
