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
    paramètre, le défaut de LangGraph reprend la main silencieusement.

    Vérifié sur l'OBJET construit, pas sur le texte du module : c'est
    l'extraction de `CachedToolNode` dans son propre fichier qui rend cette
    inspection possible, là où il fallait auparavant se rabattre sur un grep."""
    from src.orchestrator.tool_node import CachedToolNode

    noeud = CachedToolNode(tools=[])

    assert noeud._inner._handle_tool_errors is tool_error_to_message


# ── niveau 2 : le provider qui échoue ne termine pas le tour ────────────────────
#
# Ces tests appelaient auparavant `inspect.getsource(graph)` pour y chercher des
# chaînes — un aveu : la boucle était enfouie dans une fonction de 485 lignes et
# ne pouvait pas être atteinte. Son extraction dans `invocation.py` permet de la
# faire réellement échouer et d'observer ce qu'elle tente.


class _LLM:
    """LLM factice : lève ce qu'on lui donne, puis répond."""

    def __init__(self, *erreurs, reponse="ok"):
        self.restantes = list(erreurs)
        self.reponse = reponse
        self.appels = 0

    def invoke(self, messages):
        self.appels += 1
        if self.restantes:
            raise self.restantes.pop(0)
        return self.reponse

    def bind_tools(self, tools):
        return self


def _invoquer(llm, **kw):
    from src.orchestrator.invocation import invoke_with_recovery

    notes: list[str] = []
    defauts = dict(
        backend="ollama_cloud", factory=lambda: _LLM(reponse="sans-outils"),
        selected_tools=[], force_text=False, on_compress=lambda: None,
        notify=notes.append, sleep=lambda _s: None,
    )
    defauts.update(kw)
    issue = invoke_with_recovery(llm, [], **defauts)
    return issue, notes


def test_une_coupure_de_flux_est_reprise():
    llm = _LLM(Exception("IncompleteRead(1 bytes read, 99 more expected)"))

    issue, notes = _invoquer(llm)

    assert issue.response == "ok"
    assert llm.appels == 2
    assert any("reprise" in n for n in notes)


def test_la_reprise_transitoire_finit_par_abandonner():
    """Borné : au-delà, la panne n'est plus transitoire et la masquer par des
    reprises indéfinies serait pire que de la signaler."""
    from src.orchestrator.invocation import MAX_TRANSIENT_RETRIES

    coupure = Exception("connection reset")
    llm = _LLM(*[coupure] * (MAX_TRANSIENT_RETRIES + 1))

    with pytest.raises(Exception, match="connection reset"):
        _invoquer(llm)

    assert llm.appels == MAX_TRANSIENT_RETRIES + 1


def test_la_pause_croit_entre_deux_reprises():
    """Marteler un service qui vient de couper le fait tomber plus longtemps."""
    pauses: list[float] = []
    llm = _LLM(Exception("readtimeout"), Exception("readtimeout"))

    _invoquer(llm, sleep=pauses.append)

    assert pauses == sorted(pauses) and len(set(pauses)) == len(pauses)


def test_une_erreur_inconnue_tente_le_repli_sans_outils():
    """Un schéma d'outil refusé par le provider est une cause fréquente : sans
    outils, le modèle peut encore expliquer ce qui s'est passé."""
    llm = _LLM(Exception("400 INVALID_ARGUMENT: items missing field"))

    issue, notes = _invoquer(llm)

    assert issue.response == "sans-outils"
    assert any("sans outils" in n for n in notes)


def test_le_repli_sans_outils_explique_l_echec_au_modele():
    """Le modèle doit pouvoir DIRE ce qui a échoué — sinon il improvise."""
    llm = _LLM(Exception("400 INVALID_ARGUMENT"))

    issue, _ = _invoquer(llm)

    consigne = str(issue.working[-1].content)
    assert "échou" in consigne.lower()
    assert "n'invente aucun résultat" in consigne.lower()


def test_le_repli_sans_outils_n_est_tente_qu_une_fois():
    """Sans garde, la boucle réessaierait sans fin la même stratégie."""
    llm = _LLM(Exception("400 INVALID"), Exception("400 INVALID"))

    with pytest.raises(Exception):
        _invoquer(llm, factory=lambda: _LLM(Exception("400 INVALID")))


def test_force_text_ne_declenche_pas_le_repli_sans_outils():
    """Il n'y a rien à retirer : l'appel est déjà sans outils."""
    llm = _LLM(Exception("400 INVALID_ARGUMENT"))

    with pytest.raises(Exception):
        _invoquer(llm, force_text=True)


def test_un_succes_immediat_ne_tente_aucune_strategie():
    llm = _LLM()

    issue, notes = _invoquer(llm)

    assert (issue.response, llm.appels, notes) == ("ok", 1, [])


def test_le_contexte_trop_long_est_reduit_avant_d_abandonner():
    llm = _LLM(Exception("context length exceeded"))

    issue, notes = _invoquer(llm)

    assert issue.response == "ok"
    assert any("contexte trop long" in n for n in notes)


# ── ce qui doit TOUJOURS s'arrêter ──────────────────────────────────────────────
def test_les_interruptions_utilisateur_ne_sont_pas_rattrapees():
    """`KeyboardInterrupt` et `SystemExit` ne dérivent pas d'`Exception` : ils ne
    passent donc jamais par le handler. Ce test fige cette propriété du langage,
    dont dépend la possibilité d'interrompre Axon au clavier."""
    assert not issubclass(KeyboardInterrupt, Exception)
    assert not issubclass(SystemExit, Exception)


# ── niveau 3 : mesurer, pour ne plus raisonner à l'impression ───────────────────
@pytest.mark.parametrize("erreur,strategie,rattrape", [
    (Exception("IncompleteRead(1 bytes read, 9 more expected)"), "retry", True),
    (Exception("400 INVALID_ARGUMENT"), "no_tools", True),
])
def test_chaque_strategie_est_journalisee(monkeypatch, erreur, strategie, rattrape):
    """« gemini foire tout le temps » est peut-être vrai, mais invérifiable sans
    compter — et on ne saurait pas non plus ce qu'un correctif a changé."""
    entrees: list[tuple] = []
    monkeypatch.setattr(
        "src.orchestrator.invocation._log_failure",
        lambda backend, exc, strat, ok: entrees.append((strat, ok)))

    _invoquer(_LLM(erreur))

    assert (strategie, rattrape) in entrees


def test_l_abandon_definitif_est_journalise_comme_non_rattrape(monkeypatch):
    """Un échec final mal étiqueté gonflerait le taux de récupération et
    masquerait précisément ce qu'on cherche à mesurer."""
    entrees: list[tuple] = []
    monkeypatch.setattr(
        "src.orchestrator.invocation._log_failure",
        lambda backend, exc, strat, ok: entrees.append((strat, ok)))

    with pytest.raises(Exception):
        _invoquer(_LLM(Exception("400 INVALID")),
                  factory=lambda: _LLM(Exception("400 INVALID")))

    assert ("none", False) in entrees


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


# ── comptage de tokens ──────────────────────────────────────────────────────────
def test_le_comptage_utilise_un_vrai_tokenizer():
    """`len(texte) // 3` surestimait de 6 % à 74 % — typiquement +45 % sur du
    français et du code. Le même compteur décidant du seuil de compression, on
    compressait bien avant d'en avoir besoin."""
    from langchain_core.messages import HumanMessage

    from src.orchestrator.context import _CHARS_PAR_TOKEN_DEFAUT, _estimate_tokens

    texte = "Peux-tu envoyer le récapitulatif des incontournables de Nice sur Slack ?"
    reel = _estimate_tokens([HumanMessage(content=texte)])
    ancien = len(texte) // _CHARS_PAR_TOKEN_DEFAUT

    assert reel < ancien, "le comptage doit être plus fin que le ratio au caractère"


def test_le_comptage_inclut_les_appels_d_outils():
    """Les arguments d'un appel d'outil pèsent dans la fenêtre au même titre que
    le texte : les ignorer sous-estimerait une conversation riche en outils."""
    from langchain_core.messages import AIMessage

    from src.orchestrator.context import _estimate_tokens

    nu = AIMessage(content="")
    avec = AIMessage(content="", tool_calls=[
        {"name": "slack_send_message", "args": {"channel": "U06KZGGL403",
                                                "text": "x" * 400},
         "id": "1", "type": "tool_call"}])

    assert _estimate_tokens([avec]) > _estimate_tokens([nu]) + 50


def test_le_comptage_fonctionne_sans_tokenizer(monkeypatch):
    """Si tiktoken venait à manquer, le comptage doit dégrader vers l'estimation
    au caractère plutôt que de faire échouer un tour."""
    from langchain_core.messages import HumanMessage

    from src.orchestrator import context

    context._encodeur.cache_clear()
    monkeypatch.setattr(context, "_encodeur", lambda: None)

    assert context._estimate_tokens([HumanMessage(content="a" * 300)]) > 0


# ── jauge de contexte ───────────────────────────────────────────────────────────
def test_la_jauge_et_le_seuil_partagent_la_meme_table():
    """Deux tables identiques finissent toujours par diverger : l'une décide de
    compresser, l'autre affiche le remplissage, et l'utilisateur voit 60 % pendant
    qu'une compression se déclenche."""
    from src.orchestrator.context import _CONTEXT_LIMITS
    from src.ui import token_gauge

    assert token_gauge._CONTEXT_LIMITS is _CONTEXT_LIMITS


@pytest.mark.parametrize("backend", ["ollama", "ollama_cloud", "groq", "gemini", "mistral"])
def test_chaque_backend_declare_sa_fenetre(backend):
    """`mistral` manquait et retombait sur le défaut. Il tombait juste par
    chance — une absence qui donne le bon résultat ne se signale jamais."""
    from src.orchestrator.context import _BACKEND_POLICY, _CONTEXT_LIMITS

    assert backend in _CONTEXT_LIMITS, f"{backend} sans fenêtre déclarée"
    assert backend in _BACKEND_POLICY, f"{backend} sans politique de compression"


def test_la_jauge_se_remplit_avec_la_fenetre_du_backend():
    """Le même nombre de tokens ne remplit pas autant une fenêtre de 128 k que
    celle d'un million : la jauge doit suivre le backend courant."""
    from src.ui import token_gauge

    token_gauge.update_usage({"input_tokens": 64_000, "output_tokens": 0})

    assert token_gauge.get_ratio("ollama_cloud") > 0.45
    assert token_gauge.get_ratio("gemini") < 0.10
    token_gauge.reset()


def test_le_seuil_de_compression_reste_sous_la_fenetre():
    """Compresser après avoir dépassé la fenêtre ne sert à rien : le provider a
    déjà refusé."""
    from src.orchestrator.context import _CONTEXT_LIMITS, _usable_budget

    for backend, fenetre in _CONTEXT_LIMITS.items():
        assert _usable_budget(backend) < fenetre


# ── la compression s'exécute réellement ─────────────────────────────────────────
class _LLMResume:
    """Rend un résumé, comme le ferait un vrai modèle."""

    def invoke(self, messages):
        from langchain_core.messages import AIMessage
        return AIMessage(content="Résumé : l'utilisateur préparait un voyage à Nice.")


def _conversation(n: int):
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

    msgs = [SystemMessage(content="Tu es Axon.")]
    for i in range(n):
        msgs.append(HumanMessage(content=f"question {i} à propos du code et des fichiers"))
        msgs.append(AIMessage(content=f"réponse {i} " + "détaillée " * 20))
    return msgs


def test_la_compression_s_execute_de_bout_en_bout():
    """`/compact` échouait sur « name '_is_coding_session' is not defined » : la
    fonction était restée dans `graph.py` quand la compression a été extraite.
    Aucun test n'appelait `_compress_context`, donc rien ne l'a signalé — le
    découpage était vérifié par la suite, son exécution ne l'était pas."""
    from src.orchestrator.context import _compress_context

    avant = _conversation(20)

    apres, retires = _compress_context(avant, _LLMResume(), "ollama_cloud")

    assert len(apres) < len(avant), "rien n'a été compressé"
    assert any("Résumé" in str(m.content) for m in apres)


def test_la_compression_garde_les_messages_recents_intacts():
    """Compresser le présent ferait perdre le fil de la tâche en cours."""
    from src.orchestrator.context import _backend_policy, _compress_context

    avant = _conversation(20)
    garde = _backend_policy("ollama_cloud")["keep_recent"]

    apres, _ = _compress_context(avant, _LLMResume(), "ollama_cloud")

    assert avant[-1] in apres
    assert sum(1 for m in avant[-garde:] if m in apres) >= garde - 1


def test_la_compression_ne_touche_pas_une_conversation_courte():
    """En dessous du seuil il n'y a rien à gagner, et un appel LLM à perdre."""
    from src.orchestrator.context import _compress_context

    courte = _conversation(2)

    apres, retires = _compress_context(courte, _LLMResume(), "ollama_cloud")

    assert apres == courte and retires == []


@pytest.mark.parametrize("backend", ["ollama", "ollama_cloud", "groq", "gemini", "mistral"])
def test_la_compression_fonctionne_sur_chaque_backend(backend):
    """Chaque backend a sa propre politique `keep_recent` : une clé manquante
    ferait échouer la compression pour ce backend seulement."""
    from src.orchestrator.context import _compress_context

    apres, _ = _compress_context(_conversation(30), _LLMResume(), backend)

    assert len(apres) > 0
