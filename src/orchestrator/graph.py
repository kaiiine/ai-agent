# src/orchestrator/graph.py
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import List

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import tools_condition
from rich.console import Console as RichConsole

from src.orchestrator.context import (
    _BACKEND_POLICY,
    _MAX_TOOL_MSG_CHARS,
    _SUMMARY_MARKER,
    _backend_policy,
    _cap_tool_messages,
    _compress_context,
    _drop_smartest,
    _estimate_tokens,
    _should_compress,
    _usable_budget,
)
from src.orchestrator.provider_quirks import (
    _MALFORMED_TOOL_CALL_RE,
    outil_ecrit_en_json,
    _sanitize_messages_for_mistral,
)
from src.orchestrator.invocation import invoke_with_recovery
from src.orchestrator.resilience import tool_error_to_message
from src.orchestrator.clarification import (
    appel_clarification, appels_en_attente, apres_les_outils, clarifier, clarifier_appel,
)
from src.orchestrator.confirmation import apres_confirmation, confirmer
from src.orchestrator.envoi import envoyer
from src.agents.coding.noeud import coder
from src.agents.deep.noeud import approfondir
from src.orchestrator.plan import plan_a_valider, valider
from src.orchestrator.revision import reviser, revision_attendue
from src.orchestrator.tool_node import CachedToolNode
from src.infra import trace

console = RichConsole()

# Certains modèles (minimax-m2.5 notamment — bug connu upstream, cf. issues
# sgl-project/sglang#16057, vllm-project/vllm#28963) émettent parfois leur appel
# d'outil en texte brut avec une balise maison ("xxx:tool_call ... </xxx:tool_call>")
# au lieu du vrai mécanisme de function calling. LangChain ne le reconnaît pas —
# tool_calls reste vide et la commande n'est jamais exécutée.



_MAX_TOOL_ROUNDS = 12

#: Demande explicite d'information — sans point d'interrogation, elle reste une
#: question posée à l'utilisateur.
_DEMANDE_EXPLICITE = re.compile(
    r"(?i)\b(veuillez préciser|merci de préciser|peux-tu préciser|"
    r"il me (?:manque|faut)|precise[rz]|please specify)\b")

#: Longueur, HORS questions, à partir de laquelle une réponse est considérée comme
#: livrée. Le seuil vaut environ trois lignes : de quoi porter un verdict et son
#: motif, pas seulement une formule d'attente.
#:
#: Le biais est assumé, et il penche vers « ne pas déclencher ». Un faux positif
#: impose un questionnaire à qui vient de recevoir sa réponse — c'est le défaut
#: rapporté. Un faux négatif laisse le modèle poser sa question en texte libre, et
#: l'utilisateur la lit puis répond en tapant : moins confortable que le
#: questionnaire, jamais bloquant.
_SUBSTANCE_REPONSE = 240

def _demande_de_precision(texte: str) -> bool:
    """Le modèle RÉCLAME-T-IL une information au lieu de répondre ?

    L'ancienne détection déclenchait sur un « ? » N'IMPORTE OÙ dans la réponse.
    Une réponse complète qui se terminait par « Tu veux que je détaille ? » était
    donc traitée comme une question en texte libre : le modèle recevait l'ordre de
    la reposer via `ask_clarification`, et l'utilisateur voyait un questionnaire
    arriver APRÈS sa réponse, sans objet. Chaque réponse contenant une seule
    interrogation coûtait en plus un aller-retour de correction.

    Ce qui distingue les deux cas n'est pas la présence d'une question mais
    l'absence de réponse : on mesure donc ce que le texte dit EN DEHORS de ses
    questions.
    """
    phrases = [p.strip() for p in re.split(r"(?<=[.!?])\s+|\n+", texte or "") if p.strip()]
    questions = [p for p in phrases if p.endswith("?")]
    substance = sum(len(p) for p in phrases if not p.endswith("?"))

    if not questions and not _DEMANDE_EXPLICITE.search(texte or ""):
        return False
    return substance < _SUBSTANCE_REPONSE

# ── Compile callback ───────────────────────────────────────────────────────────
_compile_callback = None
_compressed_this_turn: bool = False


def set_compile_callback(fn) -> None:
    global _compile_callback, _compressed_this_turn
    _compile_callback = fn
    _compressed_this_turn = False  # reset at start of each user turn


# ── Language preference ────────────────────────────────────────────────────────
_lang_pref: str = "fr"


def set_lang_pref(lang: str) -> None:
    global _lang_pref
    _lang_pref = lang


def get_lang_pref() -> str:
    return _lang_pref


# ── Last selected tools (for /debug) ──────────────────────────────────────────
_last_selected_tools: list[str] = []


def get_last_selected_tools() -> list[str]:
    return _last_selected_tools


def _on_compress() -> None:
    if _compile_callback:
        _compile_callback()


# ── Tool-round counter ────────────────────────────────────────────────────────


def _consecutive_tool_rounds(messages: List) -> int:
    """Count total AI→Tool rounds since the last HumanMessage (not just consecutive).
    This catches loops where the LLM interleaves text between tool calls to reset the counter."""
    rounds = 0
    for m in reversed(messages):
        if isinstance(m, HumanMessage):
            break
        if isinstance(m, AIMessage) and getattr(m, "tool_calls", None):
            rounds += 1
    return rounds




# ── Orchestrator ───────────────────────────────────────────────────────────────

from src.infra.checkpoint import build_checkpointer
from src.llm.models import (
    make_llm,
    make_llm_gemini,
    make_llm_groq,
    make_llm_mistral,
    make_llm_ollama_cloud,
    make_llm_nvidia,
    make_orchestrator_llm_with_key,
)
from src.llm.prompts import build_system_prompt
from src.orchestrator.registry import build_all_tools
from src.orchestrator.state import GlobalState
from src.orchestrator.catalogue import (
    indexer as _indexer, menu as _menu, obtenir_outil, ouverts as _ouverts,
    signaler_delegation as _signaler_delegation, _EXPLORATION,
    outil as _outil_du_catalogue, serveurs_actifs as _serveurs_actifs,
)
from src.orchestrator.ellipse import est_une_ellipse
from src.orchestrator.tool_retriever import ToolRetriever


def _ensure_system_prompt(
    messages: List, selected_tools: List, today: str, plan_mode: bool = False,
    catalogue: str = "",
) -> List:
    import os

    user_name = os.getenv("USER_NAME", "l'utilisateur")
    tool_names = [t.name for t in selected_tools]
    system_msg = SystemMessage(
        content=build_system_prompt(
            tool_names, today, user_name, plan_mode=plan_mode, lang=_lang_pref,
            catalogue=catalogue,
        )
    )
    if not messages:
        return [system_msg]
    first = messages[0]
    role0 = (
        first.get("type") if isinstance(first, dict) else getattr(first, "type", None)
    )
    if role0 == "system":
        return [system_msg] + messages[1:]
    return [system_msg] + messages


def _panneau_debug(selected_tools: list, working: list) -> None:
    """Ce qui part RÉELLEMENT au modèle, imprimé au moment où ça part.

    L'affichage vivait dans `streaming.py`, appelé AVANT le tour : il montrait
    donc la sélection du tour précédent, et un prompt reconstruit depuis la liste
    complète des outils au lieu du prompt envoyé. Vécu sur « schématise un RAG en
    prod » : le panneau listait shell, cron, blender et playwright — les outils
    d'une requête d'avant — sans `mermaid_diagram`, pourtant le seul appelé.
    """
    from rich.box import SIMPLE_HEAD
    from rich.panel import Panel

    from src.ui.commands import debug_state

    if not debug_state.get("enabled"):
        return
    lignes = [f"[dim]tools sélectionnés :[/dim] {', '.join(t.name for t in selected_tools)}"]
    for message in working:
        role = getattr(message, "type", "?")
        contenu = str(getattr(message, "content", ""))
        lignes.append(f"[dim]{role}:[/dim] {contenu[:300]}{'...' if len(contenu) > 300 else ''}")
    console.print(Panel("\n\n".join(lignes), box=SIMPLE_HEAD,
                        border_style="dim", title="prompt"))


def _restreindre_les_skills(outils: list, requete: str, portee: str) -> list:
    """Remplace `load_skill` par une version qui ne montre que ce qui concerne
    la requête.

    Son catalogue est DANS sa description : 49 skills, 2 241 tokens, à chaque
    tour où l'outil est lié. C'est l'inverse de ce que fait le routage pour les
    outils — et devant une liste pareille, le modèle n'en choisissait aucune.

    Mesuré sur « fais-moi un site vitrine en Next.js » : 2 241 → 488 tokens, et
    `nextjs` entre dans les cinq montrées, là où le classement dense seul le
    plaçait cinquième derrière `fiche`, `exo` et `browser-driving`.

    Un échec de restriction rend la liste entière : perdre des tokens vaut mieux
    que cacher la skill qu'il fallait.
    """
    if not requete.strip() or not any(o.name == "load_skill" for o in outils):
        return outils
    try:
        from src.skills.tools import make_load_skill

        etroit = make_load_skill(portee, requete)
    except Exception:                                        # noqa: BLE001
        return outils
    return [etroit if o.name == "load_skill" else o for o in outils]


def _chat_node_factory():
    # Lues au REGISTRE : cette table était recopiée dans six fichiers, et quatre
    # d'entre eux avaient déjà perdu un backend en route. Un fournisseur ajouté
    # ici seulement restait invisible ailleurs, sans que rien ne lève.
    from src.llm.backends import fabriques as _fabriques

    _factories = _fabriques()
    tools = build_all_tools()
    retriever = ToolRetriever(tools)


    from src.mcp_client.runtime import mcp_runtime

    _mcp = mcp_runtime()
    # `obtenir_outil` est lié à chaque tour côté modèle, mais le ToolNode est
    # construit une fois : sans lui ici, l'appel remonterait « outil inconnu ».
    tools = tools + _mcp.tools + [obtenir_outil]

    def chatbot(state: GlobalState):
        from src.infra.settings import settings
        from src.ui.plan_mode import BLOCKED_TOOLS
        from src.ui.plan_mode import is_active as _is_plan_mode

        global _compressed_this_turn
        last = state["messages"][-1] if state["messages"] else None
        if isinstance(last, HumanMessage):
            _compressed_this_turn = False
            # Un run = un TOUR d'utilisateur, pas un passage dans ce nœud : la
            # boucle d'outils y revient N fois, et ces N passages racontent la
            # même demande. C'est le regroupement qui rend la trace lisible.
            trace.nouveau_run()

        # Une bascule automatique (rate-limit) est TEMPORAIRE : si le provider préféré
        # a de nouveau une clé saine, on y revient avant de choisir le backend du tour.
        try:
            from src.llm.key_pool import restore_preferred_backend as _restore
            _restored = _restore(settings)
            if _restored:
                console.print(f"[dim]  ↩  retour au provider préféré : {_restored}[/dim]")
        except Exception:
            pass

        backend = settings.llm_backend
        factory = _factories.get(backend, make_llm_ollama_cloud)

        last_human = next(
            (m for m in reversed(state["messages"]) if isinstance(m, HumanMessage)),
            None,
        )
        last_message = state["messages"][-1]

        def _content_to_str(content) -> str:
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                return " ".join(
                    p.get("text", "") if isinstance(p, dict) else str(p)
                    for p in content
                )
            return str(content)

        if last_human:
            query = _content_to_str(last_human.content)
            # Le test portait sur la LONGUEUR seule (« moins de huit mots ») et
            # ratait « reprend ou tu en étais sans rien oublier » — huit mots
            # pile, aucun domaine, et le routeur y répondait par `shell_ls`.
            # `est_une_ellipse` exige en plus l'absence de signal de domaine :
            # même rappel sur le jeu de réglage, +30 points sur le jeu tenu à
            # l'écart, pour un coût de faux positif mesuré NUL.
            if est_une_ellipse(query):
                human_msgs = [
                    _content_to_str(m.content)
                    for m in state["messages"]
                    if isinstance(m, HumanMessage)
                ]
                # Premier tour d'une conversation : `human_msgs` ne contient que
                # la requête elle-même, et le recollage la rend à l'identique.
                # Le repli est donc défini, pas implicite — il n'y a rien à
                # injecter quand il n'y a pas de tour d'avant.
                query = " ".join(human_msgs[-3:])
        else:
            query = (
                _content_to_str(last_message.content)
                if hasattr(last_message, "content")
                else str(last_message)
            )
        selected_tools = retriever.get(query) + _mcp.select(
            query, actifs=_serveurs_actifs(state["messages"]))
        selected_tools = _restreindre_les_skills(selected_tools, query, "orchestrator")

        global _last_selected_tools
        _last_selected_tools = [t.name for t in selected_tools]

        # Plan mode — force-include all read-only tools, strip writes
        plan_mode = _is_plan_mode()
        if plan_mode:
            from src.orchestrator.tool_retriever import TOOL_GROUPS

            _read_groups = ("filesystem", "search", "news", "git", "drive", "time")
            _tools_by_name = {t.name: t for t in tools}
            _selected_names = {t.name for t in selected_tools}
            for _g in _read_groups:
                for _tname in TOOL_GROUPS[_g].tools:
                    if _tname not in _selected_names and _tname in _tools_by_name:
                        selected_tools.append(_tools_by_name[_tname])
            selected_tools = [t for t in selected_tools if t.name not in BLOCKED_TOOLS]

        # Le CATALOGUE, reconstruit à chaque tour : les outils MCP apparaissent et
        # disparaissent avec leurs serveurs, une liste figée au démarrage mentirait.
        _indexer(tools + _mcp.tools)
        # Déléguer est possible ce tour-ci : le catalogue refuse alors d'ouvrir
        # les outils qui fouillent un projet. `ouverts()` relit l'historique, où
        # un nom refusé figure encore — la boucle doit donc filtrer aussi.
        _peut_deleguer = any(t.name == "run_coding_agent" for t in selected_tools)
        _signaler_delegation(_peut_deleguer)
        _interdits = set(BLOCKED_TOOLS) if plan_mode else set()
        if _peut_deleguer:
            _interdits |= _EXPLORATION
        _noms = {t.name for t in selected_tools}
        for _nom in _ouverts(state["messages"]):
            if _nom in _noms or _nom in _interdits:
                continue
            _reclame = _outil_du_catalogue(_nom)
            if _reclame is not None:
                selected_tools.append(_reclame)
                _noms.add(_nom)
                # Visible : c'est ce taux qui dira jusqu'où la sélection peut
                # être resserrée. Sans trace, l'arbitrage se referait au doigt.
                console.print(f"[dim]  +  catalogue → {_nom}[/dim]")
                # Et écrit, maintenant : à l'écran le taux défile et disparaît
                # avec la session. C'est pourtant LA mesure qui dit si le filet
                # tient — le n° 19 des scénarios, validé sur trois cas.
                trace.inscrire(trace.Action(
                    genre=trace.RATTRAPAGE, intent=query[:200], outil=_nom))
        selected_tools.append(obtenir_outil)
        catalogue = _menu(_interdits)

        # Tool-round cap — force text response after _MAX_TOOL_ROUNDS consecutive rounds
        force_text = _consecutive_tool_rounds(state["messages"]) >= _MAX_TOOL_ROUNDS
        if force_text:
            console.print(
                f"[dim]  ↩  {_MAX_TOOL_ROUNDS} rounds atteints — synthèse forcée[/dim]"
            )
            llm_with_tools = factory()
            catalogue = ""
        else:
            llm_with_tools = factory().bind_tools(selected_tools)

        # APRÈS la liaison, pas avant : sous synthèse forcée, aucun outil n'est
        # lié. Inscrire la sélection plus haut aurait écrit une liste que le
        # modèle n'a jamais reçue — peindre en vert ce qui n'a pas eu lieu.
        trace.inscrire(trace.Action(
            genre=trace.ROUTE,
            intent=query[:200],
            groupes=tuple(getattr(retriever, "derniere_route", ()) or ()),
            outils_lies=() if force_text else tuple(t.name for t in selected_tools),
            backend=backend,
            extra={"synthese_forcee": True} if force_text else {},
        ))

        messages = state["messages"]
        today = datetime.now().strftime("%Y-%m-%d")
        messages = _ensure_system_prompt(
            messages, selected_tools, today, plan_mode=plan_mode,
            catalogue=catalogue,
        )

        # Proactive compression before calling the LLM (once per user turn max)
        working = messages
        _state_removals: list = []  # original msgs replaced by summary → RemoveMessage
        _summary_msg = None  # compressed SystemMessage to persist

        if _should_compress(working, backend) and not _compressed_this_turn:
            _compressed_this_turn = True
            console.print("[dim]  ↩  contexte chargé — compression proactive…[/dim]")
            _on_compress()
            plain_llm = factory()
            working = _cap_tool_messages(working)
            working, _state_removals = _compress_context(working, plain_llm, backend)
            before_tokens = _estimate_tokens(messages)
            after_tokens = _estimate_tokens(working)
            freed = before_tokens - after_tokens
            console.print(
                f"[dim]  ↩  compression: -{freed:,} tokens estimés "
                f"({before_tokens:,} → {after_tokens:,})[/dim]"
            )
            # Find compressed summary SystemMessage
            _summary_msg = next(
                (
                    m
                    for m in working
                    if isinstance(m, SystemMessage)
                    and _SUMMARY_MARKER in str(m.content)
                ),
                None,
            )

        if backend == "mistral":
            working = _sanitize_messages_for_mistral(working)

        capped = False
        compressed = False
        transient_retries = 0
        degraded = False
        def _notifier(msg: str) -> None:
            console.print(f"[dim]  ↩  {msg}[/dim]")

        def _compresser_une_fois() -> None:
            global _compressed_this_turn
            if not _compressed_this_turn:
                _compressed_this_turn = True
                _on_compress()

        _panneau_debug(selected_tools, working)

        _issue = invoke_with_recovery(
            llm_with_tools, working,
            backend=backend, factory=factory, selected_tools=selected_tools,
            force_text=force_text, on_compress=_compresser_une_fois, notify=_notifier,
        )
        response = _issue.response
        working = _issue.working
        _state_removals.extend(r for r in _issue.removals if r not in _state_removals)
        _summary_msg = _issue.summary or _summary_msg

        # Garde-fou : le LLM rappelle ask_clarification avec une question à laquelle
        # il a déjà une réponse dans cette conversation (le modèle ignore la réponse
        # qu'il vient de recevoir). Provoque une double popup identique côté utilisateur.
        # Détection + un seul retry pour lui faire utiliser la réponse déjà donnée.
        if not force_text:
            ask_calls = [
                tc for tc in (getattr(response, "tool_calls", None) or [])
                if tc.get("name") == "ask_clarification"
            ]
            if ask_calls:
                answered_questions: set[str] = set()
                for m in working:
                    if isinstance(m, ToolMessage) and getattr(m, "name", None) == "ask_clarification":
                        try:
                            content = m.content if isinstance(m.content, str) else json.dumps(m.content)
                            payload = json.loads(content)
                            for q_text in (payload.get("answers") or {}):
                                if q_text != "_extra":
                                    answered_questions.add(q_text.strip().lower())
                        except Exception:
                            pass

                is_duplicate = any(
                    (q.get("question") if isinstance(q, dict) else str(q) or "").strip().lower()
                    in answered_questions
                    for tc in ask_calls
                    for q in (tc.get("args", {}).get("questions") or [])
                )

                if is_duplicate:
                    console.print(
                        "[dim]  ↩  question déjà répondue reposée — correction…[/dim]"
                    )
                    dup_reminder = HumanMessage(
                        content=(
                            "[SYSTEME] Tu viens de reposer une question à laquelle tu as déjà "
                            "une réponse dans cette conversation (visible dans un précédent "
                            "résultat de ask_clarification). Utilise cette réponse directement, "
                            "ne la redemande pas. Continue l'action demandée avec les outils "
                            "appropriés."
                        )
                    )
                    try:
                        response = llm_with_tools.invoke(working + [response, dup_reminder])
                    except Exception:
                        pass  # échec de la correction → on garde la réponse originale

        # Garde-fou : certains modèles (minimax-m2.5 notamment, bug connu upstream)
        # écrivent parfois leur appel d'outil en texte brut ("xxx:tool_call ... "
        # "</xxx:tool_call>") au lieu du vrai mécanisme de function calling —
        # tool_calls reste vide et la commande n'est jamais exécutée. Détection +
        # un seul retry pour forcer un vrai appel structuré.
        if not force_text:
            no_real_tool_call = not getattr(response, "tool_calls", None)
            raw_text = _content_to_str(response.content)
            _en_json = (outil_ecrit_en_json(raw_text, selected_tools)
                        if no_real_tool_call else None)
            if no_real_tool_call and (_MALFORMED_TOOL_CALL_RE.search(raw_text) or _en_json):
                console.print(
                    f"[dim]  ↩  appel d'outil écrit en texte"
                    f"{f' ({_en_json})' if _en_json else ''} — correction…[/dim]"
                )
                fix_reminder = HumanMessage(
                    content=(
                        "[SYSTEME] Ta dernière réponse contenait un faux appel d'outil "
                        "écrit en texte brut au lieu d'un vrai appel : une balise "
                        "'xxx:tool_call', ou les arguments rendus comme objet JSON. "
                        "Ni l'un ni l'autre n'exécute quoi que ce soit. "
                        "Refais le même appel en utilisant le vrai mécanisme de function "
                        "calling à ta disposition, pas du texte."
                    )
                )
                try:
                    response = llm_with_tools.invoke(working + [response, fix_reminder])
                except Exception:
                    pass  # échec de la correction → on garde la réponse originale

        # Garde-fou : le prompt interdit les questions en texte libre (elles doivent
        # passer par ask_clarification), mais rien n'empêche mécaniquement le LLM de
        # le faire quand même. Détection + un seul retry corrigé.
        # Exclus volontairement : les flows dont le design PRÉVOIT une confirmation
        # en texte libre ("brouillon + attends ton oui") — Slack (_SLACK) et le commit
        # git (_SHELL: "propose le message, attend la validation"), ainsi que le mode
        # plan (_PLAN_MODE: "wait for explicit validation"). Les intercepter casserait
        # ces flows volontairement conçus ainsi, ce qui serait pire que le bug d'origine.
        # L'exclusion se réglait sur la LIAISON de l'outil, pas sur le sujet du
        # tour. Or le routeur fait entrer `slack_send_message` par ricochet :
        # mesuré sur les 142 requêtes réelles, 33 tours liaient un outil de flow
        # et 29 n'avaient RIEN à voir avec Slack ou un commit — vingt pour cent
        # des tours perdaient le garde-fou en silence, dont toutes les demandes
        # de paris. Le groupe élu au rang 1 dit ce que le tour VISE, là où la
        # liaison dit seulement ce qui était à portée : exiger le rang 1 fait
        # tomber les exclusions accidentelles de 29 à 2, et les trois quarts des
        # tours Slack légitimes y sont déjà.
        #
        # Le seuil a été BALAYÉ, pas choisi : élargir ne récupère rien avant le
        # rang 3, et le coût y est prohibitif.
        #
        #     rang ≤ 1    3/4 légitimes    2 exclusions accidentelles   ← retenu
        #     rang ≤ 2    3/4 légitimes    9   — dominé : rien de plus, 4,5×
        #     rang ≤ 3    4/4 légitimes   15   — le 4e cas coûte 13 faux
        #
        # Le quatrième, à rang 3, perd son exclusion. Risque assumé et NON
        # mesuré : un brouillon Slack court serait pris pour une question. Il
        # n'est pas apparu sur les quatre tours légitimes — `gpt-oss` y appelle
        # un outil, `gemini` y pose une vraie question — mais ces tours ont été
        # joués SANS historique, or le brouillon ne naît qu'avec le contexte.
        # `_has_prior_answers` reste la seconde échappatoire.
        confirmation_flow_tools = {"slack_send_message", "git_commit"}
        _groupes_de_flow = {"slack", "git"}
        has_confirmation_flow = (
            any(t.name in confirmation_flow_tools for t in selected_tools)
            and retriever.groupe_de_tete in _groupes_de_flow)

        # L'utilisateur a-t-il DÉJÀ répondu à un questionnaire dans cette conversation ?
        # Si oui, reposer des questions en texte libre est TOUJOURS une erreur — même
        # dans un flow de confirmation (Slack/git). Sans cela, une simple demande
        # « poste sur le canal … » suffisait à désactiver le garde-fou, et le modèle
        # redemandait des informations déjà fournies (cas rapporté).
        _has_prior_answers = any(
            isinstance(m, ToolMessage) and getattr(m, "name", None) == "ask_clarification"
            and "answers" in (m.content if isinstance(m.content, str) else json.dumps(m.content))
            for m in working
        )
        if not force_text and not plan_mode and (not has_confirmation_flow or _has_prior_answers):
            no_tool_call = not getattr(response, "tool_calls", None)
            resp_text = _content_to_str(response.content).strip()
            # Une question en texte libre ne finit pas forcément par « ? » : le modèle
            # énumère souvent « 1 … 2 … 3 … » et termine par un point. Mais toute
            # interrogation n'est pas une demande — une réponse livrée peut se
            # clore sur « Tu veux que je détaille ? » sans rien attendre pour
            # continuer. Le critère est l'absence de réponse, pas la ponctuation.
            if no_tool_call and _demande_de_precision(resp_text):
                console.print(
                    "[dim]  ↩  question en texte libre détectée — correction…[/dim]"
                )
                _answers_recap = ""
                if _has_prior_answers:
                    _pairs = []
                    for m in working:
                        if isinstance(m, ToolMessage) and getattr(m, "name", None) == "ask_clarification":
                            try:
                                _c = m.content if isinstance(m.content, str) else json.dumps(m.content)
                                for _q, _a in (json.loads(_c).get("answers") or {}).items():
                                    if _q != "_extra" and _a:
                                        _pairs.append(f"- {_q} -> {_a}")
                            except Exception:
                                pass
                    if _pairs:
                        _answers_recap = (
                            "\nRéponses DÉJÀ données par l'utilisateur (utilise-les, ne les "
                            "redemande pas) :\n" + "\n".join(_pairs)
                        )
                reminder = HumanMessage(
                    content=(
                        "[SYSTEME] Tu viens de répondre par une question en texte libre — "
                        "c'est interdit. Si l'info est déjà présente ailleurs dans cette "
                        "conversation (y compris une réponse précédente à ask_clarification), "
                        "utilise-la directement sans la redemander. Sinon, repose la question "
                        "immédiatement via ask_clarification(questions=[...])."
                        + _answers_recap
                    )
                )
                try:
                    _corrected = llm_with_tools.invoke(working + [response, reminder])
                    response = _corrected
                except Exception:
                    pass  # échec de la correction → on garde la réponse originale

        # Garde BETTING nº1 : une clarification de PÉRIMÈTRE à laquelle le tour
        # courant a déjà répondu. Observé en conversation réelle : après un scan
        # complet rendu par `betting_recommend`, le modèle propose « restreindre à
        # un sport ? » — trois fois de suite. C'est la boucle du dump, déplacée
        # après le scan au lieu d'avant. Le garde de doublon existant ne l'attrape
        # pas : la question est nouvelle, c'est sa RÉPONSE qui est déjà connue.
        _ask = [tc for tc in (getattr(response, "tool_calls", None) or [])
                if tc.get("name") == "ask_clarification"]
        if _ask:
            from src.agents.quant.conversation.evidence import redundant_scope_question

            if all(redundant_scope_question(working, tc.get("args", {}).get("questions") or [])
                   for tc in _ask):
                console.print(
                    "[dim]  ↩  clarification de périmètre déjà répondue — correction…[/dim]")
                _rappel = HumanMessage(content=(
                    "[SYSTEME] Tu redemandes un périmètre (sport, compétition, "
                    "marché, période ou bankroll) que l'utilisateur a déjà fixé et "
                    "que betting_recommend a déjà appliqué dans ce tour. La réponse "
                    "est dans le champ `rendered` de son résultat : restitue-la "
                    "telle quelle, sans poser de question. Si l'utilisateur veut "
                    "restreindre, il le dira de lui-même."))
                try:
                    response = llm_with_tools.invoke(working + [response, _rappel])
                except Exception:
                    pass  # échec de la correction → on garde la réponse originale

        # Garde de provenance BETTING — programmatique, jamais un prompt.
        # Une réponse de pari doit venir de la chaîne structurée du TOUR COURANT.
        # Sans preuve, le texte est remplacé : le modèle n'est pas convaincu, il
        # est court-circuité. Ne s'applique qu'à la réponse finale (un tour
        # intermédiaire n'affirme rien à l'utilisateur).
        if not getattr(response, "tool_calls", None):
            from src.agents.quant.conversation.evidence import (
                extract_evidence,
                has_structured_output,
            )
            from src.agents.quant.conversation.guard import enforce as _enforce_betting

            _verdict = _enforce_betting(
                _content_to_str(response.content),
                extract_evidence(working),
                has_structured_output=has_structured_output(working),
            )
            if _verdict.blocked:
                console.print(
                    f"[dim]  ⛔ réponse de pari non sourcée — remplacée "
                    f"({_verdict.reason})[/dim]"
                )
                response = AIMessage(content=_verdict.replacement)

        # Persist compression to LangGraph state so subsequent chatbot calls
        # start with the compressed history, not the original bloated one.
        from langchain_core.messages import RemoveMessage

        result: list = []
        if _state_removals:
            result += [
                RemoveMessage(id=m.id)
                for m in _state_removals
                if getattr(m, "id", None)
            ]
            if _summary_msg:
                result.append(_summary_msg)
        result.append(response)
        return {"messages": result}

    return chatbot, tools


def build_orchestrator():
    chatbot, tools = _chat_node_factory()

    g = StateGraph(GlobalState)
    g.add_node("chatbot", chatbot)
    g.add_node("tools", CachedToolNode(tools))
    g.add_node("clarifier", clarifier)
    g.add_node("clarifier_appel", clarifier_appel)
    g.add_node("confirmer", confirmer)
    g.add_node("reviser", reviser)
    g.add_node("envoyer", envoyer)
    g.add_node("valider_plan", valider)
    g.add_node("approfondir", approfondir)
    g.add_node("coder", coder)

    g.add_edge(START, "chatbot")
    # `tools_condition` mène à `tools` ou à la fin. On s'intercale avant la fin :
    # un plan se valide sur le TEXTE du modèle, pas sur un appel d'outil.
    def _apres_chatbot(state):
        route = tools_condition(state)
        if route == "tools" and appel_clarification(state["messages"][-1]):
            return "clarifier_appel"
        if route == END and plan_a_valider(state):
            return "valider_plan"
        return route

    g.add_conditional_edges("chatbot", _apres_chatbot,
                            {"tools": "tools", "clarifier_appel": "clarifier_appel",
                             "valider_plan": "valider_plan", END: END})
    # `tools` ne revient au modèle que si aucun nœud de demande n'a la main.
    g.add_conditional_edges("tools", apres_les_outils, {
        "clarifier": "clarifier",
        "confirmer": "confirmer",
        "reviser": "reviser",
        "envoyer": "envoyer",
        "approfondir": "approfondir",
        "coder": "coder",
        "chatbot": "chatbot",
    })
    # `clarifier` a déjà les réponses, réinscrites dans l'historique.
    g.add_edge("clarifier", "chatbot")
    # Le reste du lot doit être servi : un appel déclaré sans résultat déséquilibre
    # les paires, et le fournisseur refuse le tour.
    g.add_conditional_edges("clarifier_appel",
                            lambda e: "tools" if appels_en_attente(e) else "chatbot",
                            {"tools": "tools", "chatbot": "chatbot"})
    # `confirmer` réémet l'appel sur un accord, un simple message sur un refus.
    g.add_conditional_edges("confirmer", apres_confirmation,
                            {"tools": "tools", "chatbot": "chatbot"})
    # La revue rend son compte rendu au modèle : appliqué, refusé, ou à ajuster.
    g.add_edge("reviser", "chatbot")
    g.add_edge("envoyer", "chatbot")
    # La décision revient au modèle : exécuter, réviser, ou renoncer.
    g.add_edge("valider_plan", "chatbot")
    g.add_edge("approfondir", "chatbot")
    # PAS une arête simple : l'agent de code dépose ses fichiers dans
    # `pending_changes` et compte sur le nœud `reviser` pour les faire relire —
    # c'est écrit dans `_coding_progress`, mode `ask`. Le renvoyer droit au modèle
    # laissait la proposition en plan : aucun diff, rien d'écrit, et le modèle
    # redemandait confirmation d'un fichier que personne ne lui montrait.
    g.add_conditional_edges("coder",
                            lambda e: "reviser" if revision_attendue(e) else "chatbot",
                            {"reviser": "reviser", "chatbot": "chatbot"})

    return g.compile(checkpointer=build_checkpointer())
