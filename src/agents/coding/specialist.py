"""Agent de code délégué par l'orchestrateur.

Le modèle vient de `settings.coding_model` : le nommer ici l'a laissé mentir
pendant plusieurs changements de backend.
"""
from __future__ import annotations

import json
import re as _re
import uuid
from typing import Callable, Optional

from langchain_core.messages import AIMessage, SystemMessage, HumanMessage, ToolMessage
from src.agents.coding.prompts.base import BASE_PROMPT
from src.agents.memory.persistent import _persist_session_memory

# Module-level progress callback set by the streaming UI
_progress_cb: Optional[Callable[[str, dict, Optional[dict]], Optional[dict]]] = None

# Retriever cache — Chroma embed is expensive (~100 docs), rebuild only when tool set changes
_retriever_cache: Optional[object] = None
_retriever_tool_names: tuple = ()


def set_progress_callback(cb: Optional[Callable[[str, dict, Optional[dict]], Optional[dict]]]) -> None:
    global _progress_cb
    _progress_cb = cb


def _notifier(evenement: str, donnees: dict | None = None) -> None:
    """Un événement d'affichage ne doit jamais faire échouer le travail."""
    if not _progress_cb:
        return
    try:
        _progress_cb(evenement, donnees or {}, None)
    except Exception:   # noqa: BLE001
        pass


def _get_coding_llm():
    from src.llm.models import make_coding_llm
    return make_coding_llm()


def _get_coding_tools():
    from src.agents.coding.tools import (
        dev_plan_create, dev_plan_update, dev_plan_step_done, dev_explain, ask_clarification,
        find_git_repos, propose_file_change, edit_file, load_skill,
        project_graph_query,
    )
    from src.agents.filesystem.tools import (
        local_find_file, local_read_file, local_list_directory,
        local_grep, local_glob,
    )
    from src.agents.shell.tools import shell_run, shell_cd, shell_pwd, shell_ls, shell_kill_bg
    from src.agents.git.tools import (
        git_status, git_log, git_diff, git_suggest_commit,
        git_add, git_commit, git_checkout, git_stash,
        url_fetch,
    )
    from src.agents.memory.tools import axon_note
    from src.agents.search.tools import web_research_report, web_search_news
    from src.agents.mermaid.tools import mermaid_diagram
    from src.agents.coding.asset_downloader import download_asset
    from src.agents.notebook.tools import (
        notebook_read, notebook_edit_cell, notebook_insert_cell, notebook_run,
    )
    return [
        dev_plan_create, dev_plan_update, dev_plan_step_done, dev_explain, ask_clarification,
        find_git_repos, propose_file_change, edit_file, load_skill,
        project_graph_query,
        local_find_file, local_read_file, local_list_directory,
        local_grep, local_glob,
        shell_run, shell_cd, shell_pwd, shell_ls, shell_kill_bg,
        git_status, git_log, git_diff, git_suggest_commit,
        git_add, git_commit, git_checkout, git_stash,
        url_fetch,
        axon_note,
        web_research_report, web_search_news,
        mermaid_diagram,
        download_asset,
        notebook_read, notebook_edit_cell, notebook_insert_cell, notebook_run,
    ] + _outils_mcp()


def _outils_mcp():
    """Les serveurs MCP connectés — Blender, Motion, et les suivants.

    Le graphe conversationnel les branchait depuis toujours ; le specialist non.
    `/build` était donc le SEUL chemin d'AXON aveugle à MCP : un projet 3D
    pouvait demander Blender dans sa spec, l'agent de build ne pouvait pas le
    joindre et écrivait du code à la place — sans jamais dire qu'il lui manquait
    l'outil.

    Une panne MCP ne coûte JAMAIS le build : sans serveur joignable, la liste est
    vide et le specialist travaille comme avant.

    ── POURQUOI CE CHEMIN DIVERGE DE `graph.py` ────────────────────────────
    L'orchestrateur sépare les deux routages :

        selected_tools = retriever.get(query) + _mcp.select(query)

    Ici les outils MCP entrent au contraire dans l'index sémantique, avec les
    natifs. C'est DÉLIBÉRÉ et MESURÉ — ne pas « aligner » sans refaire la mesure.

    Sur 23 requêtes étiquetées (`tests/test_mcp_routing_specialist.py`), avec
    82 outils dont 43 MCP :

        index unique (ce fichier)     6/7 pos · 10/10 nég · 6/6 natif = 22/23
        deux voies (comme graph.py)   7/7 pos ·  0/10 nég · 6/6 natif = 13/23

    `mcp_runtime().select()` rend SEPT outils sur CHAQUE requête, sans exception
    — « montre-moi les fichiers modifiés dans le dépôt » comprise. Il ne
    discrimine pas. Dans une sélection conversationnelle large, sept outils de
    trop se noient ; ici ils seraient liés à chaque tour de chaque phase, et
    redeviendraient le bruit permanent que le routage par groupe (`0c9a03b`)
    avait supprimé.

    L'alignement paraît propre et coûte 9 cas sur 23. La divergence est le
    résultat de la mesure, pas un oubli de câblage.
    """
    try:
        from src.mcp_client.runtime import mcp_runtime
        return list(mcp_runtime().tools)
    except Exception:                                            # noqa: BLE001
        return []


_PROGRESS_TOOLS = {
    "dev_plan_create", "dev_plan_update", "dev_plan_step_done", "dev_explain",
    "ask_clarification", "propose_file_change", "edit_file", "axon_note",
    "local_read_file", "local_grep", "local_glob", "local_find_file", "local_list_directory",
    "shell_ls", "shell_pwd", "url_fetch", "web_research_report", "web_search_news",
    "git_status", "git_log", "git_diff",
    "notebook_read", "notebook_edit_cell", "notebook_insert_cell", "notebook_run",
    "load_skill", "project_graph_query",
}
_SHELL_PREVIEW_TOOLS = {"shell_run", "shell_cd"}
_MAX_ITERATIONS = 80
ECHEC_PREFIXE = "[ÉCHEC]"
_phase_max_iterations: int | None = None 
_phase_abort: bool = False               


def set_phase_max_iterations(n: int | None) -> None:
    global _phase_max_iterations
    _phase_max_iterations = n


def _abort_phase() -> None:
    global _phase_abort
    _phase_abort = True
# Outils exemptés du garde-fou de répétition : écritures, planification, et shell.
#
# `shell_run` DOIT y figurer. Le garde n'exécute pas l'outil au 3ᵉ appel identique
# et répond « le résultat n'a pas changé depuis la dernière lecture » — ce qui est
# vrai d'une lecture de fichier, et FAUX de la boucle corriger-vérifier :
#
#     shell_run("pytest")  ->  échec
#     edit_file(...)       ->  correction
#     shell_run("pytest")  ->  échec
#     edit_file(...)       ->  correction
#     shell_run("pytest")  ->  BLOQUÉ, tests jamais relancés
#
# L'agent se voyait alors affirmer qu'il avait déjà l'information, sans que la
# suite ait tourné une seule fois depuis sa correction. Le commentaire annonçait
# cette exemption ; seul `shell_cd` était listé, qui ne rejoue jamais rien.
#
# Le risque symétrique — un agent bloqué qui relance indéfiniment la même
# commande — reste couvert par `_phase_max_iterations`, qui borne la phase entière.
_REPETITION_EXEMPT = frozenset({
    "dev_plan_create", "dev_plan_update", "dev_plan_step_done", "dev_explain",
    "propose_file_change", "edit_file", "shell_cd", "shell_run",
})
# Keywords used to detect frontend projects for the load_skill() 
_FRONTEND_KW = frozenset({"next", "react", "vue", "svelte", "angular", "frontend"})
# Adaptive context budget per backend (chars ≈ tokens × 3)
_CONTEXT_CHAR_BUDGET: dict[str, int] = {
    "ollama_cloud": 120_000,   
    "groq":         120_000,   
    "ollama":        48_000,   
    "gemini":       400_000,   
    "mistral":      60_000,
}
_CONTEXT_CHAR_BUDGET_DEFAULT = 180_000  # fallback

# Rotations de clé ET bascules de fournisseur pour une seule invocation.
# Ce qu'est un 401, un quota ou une panne serveur est décidé dans src/llm/rotation.py.
_MAX_ROTATIONS_CLE = 6

# Un seul résultat d'outil ne doit jamais pouvoir remplir le contexte à lui seul.
# `local_read_file` rend jusqu'à 200 000 caractères, soit 1,6× le budget entier
# d'ollama_cloud : la compression partait alors sur un unique appel, au prix d'un
# appel LLM complet. Tronquer à l'entrée coûte zéro.
_MAX_TOOL_RESULT_CHARS = 20_000
_TETE = 0.6   # le début porte le contenu d'un fichier, la fin porte l'erreur d'un build


def tronquer_resultat(texte: str, limite: int = _MAX_TOOL_RESULT_CHARS) -> str:
    """Garde le début et la fin, annonce ce qui manque et comment le récupérer."""
    if len(texte) <= limite:
        return texte
    garde = limite - 400                     # marge pour le marqueur lui-même
    tete = int(garde * _TETE)
    coupe = len(texte) - garde
    return (
        texte[:tete]
        + f"\n\n…[{coupe} caractères coupés au milieu — résultat tronqué à {limite}. "
          "Pour la partie manquante : local_read_file(offset=, limit=) sur un fichier, "
          "local_grep sur un motif précis, ou une commande shell plus ciblée.]\n\n"
        + texte[-(garde - tete):]
    )


def _compress_specialist_messages(messages: list, llm) -> list:
    """LLM-based context compression for the specialist — same philosophy as the orchestrator's
    'compiling' mechanism: produce a dense technical summary instead of truncating."""

    _notifier("specialist:compress")   # l'UI bascule sur l'animation de compilation

    system_msg = messages[0]   
    task_msg   = messages[1]   
    history    = messages[2:]  

    transcript_parts: list[str] = []
    for m in history:
        if isinstance(m, AIMessage):
            if isinstance(m.content, str) and m.content.strip():
                transcript_parts.append(f"[ASSISTANT]: {m.content[:3_000]}")
            for tc in getattr(m, "tool_calls", []) or []:
                args_str = str(tc.get("args", {}))[:800]
                transcript_parts.append(f"[TOOL CALL] {tc.get('name')}({args_str})")
        elif isinstance(m, ToolMessage):
            name = getattr(m, "name", "tool") or "tool"
            content = m.content if isinstance(m.content, str) else str(m.content)
            if name == "local_read_file":
                try:
                    import json as _json
                    parsed = _json.loads(content)
                    fpath = parsed.get("path", "") or ""
                    raw = parsed.get("content", "")
                    flines = raw.count("\n") + 1 if raw else 0
                except Exception:
                    fpath, flines = "", 0
                if fpath:
                    transcript_parts.append(
                        f"[TOOL RESULT] local_read_file: ⚠ Contenu compressé hors contexte."
                        f" Fichier : '{fpath}' ({flines} lignes). Re-lire OBLIGATOIREMENT avec"
                        f" local_read_file(path='{fpath}') avant tout propose_file_change sur ce fichier."
                    )
                else:
                    transcript_parts.append(f"[TOOL RESULT] {name}: {content[:2_500]}")
            else:
                transcript_parts.append(f"[TOOL RESULT] {name}: {content[:2_500]}")

    transcript = "\n".join(transcript_parts)
    # Cap transcript so the compression call itself never exceeds model limits
    if len(transcript) > 180_000:
        transcript = "…[début omis pour cause de longueur]\n" + transcript[-180_000:]

    prompt = (
        "Tu es un assistant de mémoire pour un agent de code actif.\n"
        "Voici la transcription COMPLÈTE des actions effectuées jusqu'ici par l'agent.\n\n"
        "Génère un résumé DENSE et TECHNIQUE qui lui permettra de continuer sans perte d'information.\n"
        "Préserve ABSOLUMENT :\n"
        "1. Le plan — étapes complétées ✓ et restantes ○ avec leurs indices\n"
        "2. Chaque fichier lu, modifié ou créé — chemin EXACT + contenu ou diff clé\n"
        "3. Le répertoire de travail courant (dernier shell_cd)\n"
        "4. Commandes exécutées et leur résultat (succès / erreur + cause)\n"
        "5. Dépendances installées, variables d'env, configs importantes\n"
        "6. Ce qui était exactement en cours au moment de la compression\n"
        "7. La spec/brief du message initial : modules listés, palette, typographie,\n"
        "   contraintes visuelles ('no animations', 'no rounded', 'no UI library'),\n"
        "   structure des sections, textes exacts — même si déjà mentionnés ailleurs.\n\n"
        f"TRANSCRIPTION :\n{transcript}\n\n"
        "Résumé dense (chemins exacts, noms de variables, valeurs de config — pas de généralités) :"
    )

    try:
        resp = llm.invoke([HumanMessage(content=prompt)])
        summary_content = resp.content
        if isinstance(summary_content, list):
            summary_content = " ".join(
                p.get("text", "") if isinstance(p, dict) else str(p)
                for p in summary_content
            )
        summary_msg = HumanMessage(
            content=f"[CONTEXTE COMPRESSÉ — continue la tâche]\n{summary_content}"
        )
        return [system_msg, task_msg, summary_msg]
    except Exception:
        # Fallback: keep only last 5 messages to guarantee the context fits
        return [system_msg, task_msg] + history[-5:]


def _vram_swap_in() -> None:
    """On local ollama: unload the main agentic model to free VRAM for the coding specialist."""
    from src.infra.settings import settings
    if settings.llm_backend != "ollama":
        return
    from src.llm.models import _ollama_unload
    _ollama_unload(settings.ollama_model)


def _vram_swap_out() -> None:
    """On local ollama: unload the coding model so the main model can reload on next use."""
    from src.infra.settings import settings
    if settings.llm_backend != "ollama":
        return
    from src.llm.models import _ollama_unload
    _ollama_unload(settings.coding_model_local)


def run_coding_task(task: str) -> str:
    """
    Runs a coding task using the specialized coding LLM.
    Calls the global progress callback on plan/file events so the UI can update in real time.
    Returns a summary string.
    """
    _vram_swap_in()
    try:
        return _run(task)
    finally:
        _vram_swap_out()


_MSG_REPR_RE = _re.compile(
    r'\[?\s*(?:Human|System|AI|Tool)Message\s*\(.*?\)\s*\]?',
    _re.DOTALL,
)


def _clean_output(content: str) -> str:
    """Remove Python LangChain message repr blocks from model output."""
    # Remove entire [...Message(...)] blocks wherever they appear
    cleaned = _MSG_REPR_RE.sub('', content)
    # Collapse excessive blank lines left by removal
    cleaned = _re.sub(r'\n{3,}', '\n\n', cleaned).strip()
    return cleaned or content  # fallback to original if we wiped everything



def _extract_json_tool_call(content: str) -> dict | None:
    """Some small models output tool calls as JSON text instead of using the API.
    Detect and parse them so we can execute them properly."""
    s = content.strip()
    # Strip markdown code fences if present
    if s.startswith("```"):
        s = _re.sub(r'^```(?:json)?\s*', '', s)
        s = _re.sub(r'\s*```$', '', s.strip())
    try:
        obj = json.loads(s)
        name = obj.get("name") or obj.get("tool") or obj.get("function")
        args = obj.get("arguments") or obj.get("args") or obj.get("parameters") or {}
        if name and isinstance(name, str):
            return {"name": name, "args": args}
    except Exception:
        pass
    return None


def _build_specialist_trace(messages: list) -> str:
    """Build a compact trace block prepended to the specialist's return value."""
    from src.agents.coding.pending import dev_plan
    from src.agents.shell.tools import get_cwd

    parts: list[str] = []

    cwd = str(get_cwd())
    parts.append(f"cwd:{cwd}")

    written: list[str] = []
    for m in messages:
        if not isinstance(m, AIMessage):
            continue
        for tc in (getattr(m, "tool_calls", None) or []):
            if tc.get("name") in ("propose_file_change", "edit_file"):
                p = (tc.get("args") or {}).get("path", "")
                if p and p not in written:
                    written.append(p)
    if written:
        parts.append("files:" + ",".join(written))

    steps = dev_plan.steps
    if steps:
        plan_parts = [f"✓{s.label}" if s.done else f"○{s.label}" for s in steps]
        parts.append("plan:" + "|".join(plan_parts))

    return "[SPECIALIST-TRACE]\n" + "\n".join(parts) + "\n[/SPECIALIST-TRACE]\n"


def _run(task: str) -> str:
    import time as _time
    from src.agents.coding.tool_retriever import CodingToolRetriever, retrieval_query
    from src.infra.settings import settings as _settings

    from src.llm import rotation
    from src.llm.key_pool import get_pool as _get_pool
    from src.llm.models import make_coding_llm_with_key as _make_llm_key
    _pool = _get_pool()
    _current_provider: str = _settings.llm_backend
    # Jamais de clé vide : un client sans clé s'authentifie avec l'identité
    # machine, donc sur un compte qu'on ne surveille pas.
    _current_key: str = _pool.next_healthy(_current_provider) or ""
    if not _current_key:
        _configurees = _pool.keys_for(_current_provider) or []
        if _configurees:
            _current_key = _configurees[0]
    if _current_key:
        llm = _make_llm_key(_current_provider, _current_key)
    else:
        llm = _get_coding_llm()

    all_tools = _get_coding_tools()
    tool_map = {t.name: t for t in all_tools}  # full map — every tool remains callable

    # DEUX VOIES, comme l'orchestrateur (graph.py) : les outils natifs passent par
    # l'index sémantique, les outils MCP par LEUR PROPRE routeur à deux étages,
    # qui lit déjà le `capabilities_hint` de chaque serveur.
    #
    # Les indexer ensemble faisait une TROISIÈME architecture, différente des deux
    # qui existaient. Mesurée, elle ne dégradait rien (22/23 sur un jeu de
    # référence incluant cinq requêtes ambiguës) — mais elle portait 31 % de la
    # cardinalité de l'index, et surtout elle faisait diverger deux chemins qui
    # résolvent le même problème. C'est cette divergence qui coûte : le jour où
    # l'un des deux évolue, l'autre le suit par erreur ou reste en arrière sans
    # que rien ne le signale.
    #
    # `tool_map` reste construit sur TOUS les outils : un outil non lié demeure
    # exécutable, et retirer MCP de l'index ne doit pas retirer ce filet.
    # Re-use cached retriever — rebuilding Chroma embeds ~100 docs on every call otherwise
    global _retriever_cache, _retriever_tool_names
    _names = tuple(t.name for t in all_tools)
    if _retriever_cache is None or _retriever_tool_names != _names:
        _retriever_cache = CodingToolRetriever(all_tools, k=8)
        _retriever_tool_names = _names
    retriever = _retriever_cache

    _budget = _CONTEXT_CHAR_BUDGET.get(_current_provider, _CONTEXT_CHAR_BUDGET_DEFAULT)

    from src.agents.coding.task_enricher import enrich_task
    enriched_task = enrich_task(task)

    messages = [SystemMessage(BASE_PROMPT), HumanMessage(enriched_task)]
    _plan_complete = False
    _call_counts: dict[tuple, int] = {}  # (tool, args_json) → count, reset per plan step
    _load_skill_called = False
    _tool_call_count = 0
    _is_frontend_task = any(kw in enriched_task.lower() for kw in _FRONTEND_KW)
    _text_only_retries = 0

    _notifier("specialist:start", {"model": getattr(llm, "model", "unknown")})

    try:
        from src.skills import warmup as _skill_warmup
        _skill_warmup()
    except Exception:
        pass

    global _phase_abort
    _phase_abort = False  # reset at start of each run
    _iter_limit = _phase_max_iterations if _phase_max_iterations is not None else _MAX_ITERATIONS
    for _ in range(_iter_limit):
        if _phase_abort:
            return ECHEC_PREFIXE + " Tâche interrompue (boucle détectée — phase abandonnée par le système)."
        total_chars = sum(len(str(getattr(m, "content", ""))) for m in messages)
        # Guard: never compress with only system+task — transcript would be empty → infinite loop
        if total_chars > _budget and len(messages) > 3:
            messages = _compress_specialist_messages(messages, llm)

        # Per-turn tool selection: only bind tools relevant to the current step
        _query = retrieval_query(messages, enriched_task)
        _active_tools = retriever.get(_query)
        _bound_llm = llm.bind_tools(_active_tools)

        invoker = llm if _plan_complete else _bound_llm
        response = None
        _compressed = False
        _derniere_erreur = "aucune"
        _provider_en_faute = _current_provider
        _cles_essayees: set[str] = set()
        # Fournisseurs déjà vidés dans ce run : empêche la bascule de boucler.
        _fournisseurs_essayes: set[str] = set()

        def _reconstruire(fournisseur: str, cle: str) -> None:
            """Rebâtit le client sur (fournisseur, clé) et re-lie les outils du tour."""
            nonlocal llm, _bound_llm, invoker, _current_provider, _current_key
            _current_provider, _current_key = fournisseur, cle
            llm = _make_llm_key(fournisseur, cle)
            _bound_llm = llm.bind_tools(_active_tools)
            invoker = llm if _plan_complete else _bound_llm

        def _basculer_fournisseur() -> bool:
            """Passe au fournisseur suivant qui a une clé saine. `False` si aucun.

            ANNONCÉE ET PERSISTÉE : `settings.llm_backend` est réellement mis à
            jour, sinon `/config` et `/backend` afficheraient le fournisseur
            épuisé pendant que le travail se fait ailleurs.
            """
            nonlocal _budget
            precedent = _current_provider
            _fournisseurs_essayes.add(_current_provider)
            trouve = rotation.fournisseur_suivant(_fournisseurs_essayes)
            if trouve is None:
                return False
            suivant, cle = trouve
            _settings.llm_backend = suivant
            _cles_essayees.clear()
            _budget = _CONTEXT_CHAR_BUDGET.get(suivant, _CONTEXT_CHAR_BUDGET_DEFAULT)
            _reconstruire(suivant, cle)
            _notifier("specialist:backend_switch",
                      {"from": precedent, "to": suivant, "key": cle[:10] + "..."})
            return True

        _tentatives, _rotations = 0, 0
        while _tentatives < 3 and _rotations < _MAX_ROTATIONS_CLE:
            attempt = _tentatives
            try:
                response = invoker.invoke(messages)
                break
            except Exception as e:
                _derniere_erreur = str(e)
                _provider_en_faute = _current_provider
                _genre = rotation.classer_erreur(e)

                if _genre in ("cle_morte", "quota"):
                    rotation.marquer_echec(_current_provider, _current_key, e)
                    _cles_essayees.add(_current_key)
                    # Toutes les clés du fournisseur d'abord ; on ne bascule qu'après.
                    _suivante = rotation.cle_suivante(_current_provider, _cles_essayees)
                    if _suivante:
                        _reconstruire(_current_provider, _suivante)
                        _notifier("specialist:key_rotate", {
                            "provider": _current_provider,
                            "key": _suivante[:10] + "...",
                            "raison": "clé invalide" if _genre == "cle_morte" else "quota atteint",
                        })
                        # Une rotation n'est pas une tentative : budget d'essais intact.
                        _rotations += 1
                        continue
                    if _basculer_fournisseur():
                        _rotations += 1
                        continue
                    _n = len(_pool.keys_for(_current_provider) or [])
                    return (
                        ECHEC_PREFIXE + f" Toutes les clés de « {_current_provider} » sont "
                        f"épuisées ou invalides ({_n} clé(s) configurée(s)), "
                        f"et aucun autre fournisseur n'a de clé disponible.\n"
                        f"Erreur du fournisseur : {_derniere_erreur}\n"
                        "→ Attendre le renouvellement d'un quota, ou ajouter "
                        "une clé (`/config` pour l'état courant)."
                    )

                if _genre == "contexte":
                    if not _compressed and len(messages) > 3:
                        messages = _compress_specialist_messages(messages, llm)
                        invoker = llm if _plan_complete else _bound_llm
                        _compressed = True
                        _tentatives += 1
                        continue
                    # Au premier tour il n'y a rien à compresser : ne pas
                    # prétendre l'avoir fait.
                    _quoi = ("même après compression" if _compressed
                             else "et il n'y avait rien à compresser (premier tour)")
                    return (ECHEC_PREFIXE + f" Le modèle a refusé la requête {_quoi}.\n"
                            f"Erreur du fournisseur : {_derniere_erreur}")

                if _genre == "serveur" and attempt < 2:
                    _time.sleep(2 ** attempt)  # 1s, 2s backoff
                    _tentatives += 1
                    continue
                raise
        if response is None:
            # La vraie erreur du fournisseur, jamais une cause supposée.
            return (ECHEC_PREFIXE + " Aucun fournisseur LLM n'a répondu après 3 tentatives.\n"
                    f"Dernière erreur ({_provider_en_faute}) : {_derniere_erreur}\n"
                    "→ Si c'est un quota : `/backend <autre>` pour changer de fournisseur, "
                    "et `/config` pour voir lequel est actif.")
        tool_calls = response.tool_calls or []

        # Small models sometimes return tool calls as JSON text instead of using the API
        if not tool_calls and response.content:
            parsed = _extract_json_tool_call(response.content)
            if parsed and parsed["name"] in tool_map:
                tc_id = str(uuid.uuid4())
                tool_calls = [{"name": parsed["name"], "args": parsed["args"], "id": tc_id}]
                # Declare the tool_call in the AIMessage so Mistral sees balanced pairs
                messages.append(AIMessage(content="", tool_calls=tool_calls))
            else:
                messages.append(response)
                from src.agents.coding.pending import dev_plan

                plan_complete = all(s.done for s in dev_plan.steps) if dev_plan.steps else False
                if plan_complete or not dev_plan.steps:
                    trace = _build_specialist_trace(messages)
                    _result = _clean_output(response.content) or "Task completed"
                    _persist_session_memory(messages, enriched_task, _result, _settings.llm_backend)
                    return trace + _result
                else:
                    if _text_only_retries < 2:
                        _text_only_retries += 1
                        messages.append(HumanMessage(content=(
                            "[System] You still have incomplete plan steps. "
                            "Use your tools to continue — don't summarize yet."
                        )))
                        continue
                    else:
                        _text_only_retries = 0
                        trace = _build_specialist_trace(messages)
                        _result = _clean_output(response.content) or "Task completed"
                        # Un plan inachevé n'est pas un résultat. Le rendre tel quel
                        # laissait croire le site livré alors que quatre étapes sur
                        return trace + _result
        else:
            messages.append(response)

        for tc in tool_calls:
            name = tc["name"]
            args = tc.get("args", {})

            # load_skill() reminder guard: if 5 tool calls pass without load_skill on frontend
            _tool_call_count += 1
            if name == "load_skill":
                _load_skill_called = True
            elif (
                _tool_call_count == 5
                and not _load_skill_called
                and _is_frontend_task
            ):
                messages.append(HumanMessage(
                    content=(
                        "[Rappel automatique] load_skill() n'a pas encore été appelé après 5 actions. "
                        "Pour ce projet frontend, appelle load_skill('nextjs') / load_skill('vue') / etc. "
                        "MAINTENANT, avant de modifier d'autres fichiers."
                    )
                ))

            # Pre-execution hook: show shell commands BEFORE they run
            if _progress_cb and name in _SHELL_PREVIEW_TOOLS:
                try:
                    _progress_cb(f"{name}:before", args)
                except Exception:
                    pass

            # Execute the tool (with session cache for read-only tools)
            from src.infra.tools_cache import session_cache, CACHEABLE_TOOLS
            from src.agents.coding.pending import recent_tools, dev_plan

            # Repetition guard: same read tool called ≥3 times → redirect instead of re-executing
            _args_key = (name, json.dumps(args, sort_keys=True, ensure_ascii=False, default=str))
            _call_counts[_args_key] = _call_counts.get(_args_key, 0) + 1

            tool_fn = tool_map.get(name)
            if not tool_fn:
                result = {"status": "error", "error": f"Outil inconnu : {name}"}
            elif _call_counts[_args_key] >= 3 and name not in _REPETITION_EXEMPT:
                result = {
                    "status": "repeated_call",
                    "message": (
                        f"'{name}' a été appelé {_call_counts[_args_key]} fois avec les mêmes arguments. "
                        "Le résultat n'a pas changé depuis la dernière lecture. "
                        "→ Si tu attends un changement suite à une écriture, vérifie que propose_file_change a bien été accepté. "
                        "→ Sinon, tu as déjà l'information — avance à l'étape suivante du plan."
                    ),
                }
            elif name in CACHEABLE_TOOLS and (hit := session_cache.get(name, args)) is not None:
                result = hit
            else:
                try:
                    if name == "shell_run":
                        try:
                            from src.agents.shell.tools import set_shell_stream_callback

                            def _stream_line(line: str):
                                if _progress_cb:
                                    _progress_cb("shell_run:stream", {"line": line}, None)

                            set_shell_stream_callback(_stream_line)
                        except Exception:
                            pass
                    result = tool_fn.invoke(args)
                    if name == "shell_run":
                        try:
                            from src.agents.shell.tools import set_shell_stream_callback
                            set_shell_stream_callback(None)
                        except Exception:
                            pass
                    if name in CACHEABLE_TOOLS:
                        session_cache.set(name, args, result)
                    session_cache.on_tool_executed(name)
                except Exception as e:
                    if name == "shell_run":
                        try:
                            from src.agents.shell.tools import set_shell_stream_callback
                            set_shell_stream_callback(None)
                        except Exception:
                            pass    
                    result = {"status": "error", "error": str(e)}

            # Post-execution hook: notify UI of result — MUST run before record() so
            # propose_file_change gets the "accepted" override before being tracked.
            if _progress_cb and (name in _PROGRESS_TOOLS or name in _SHELL_PREVIEW_TOOLS):
                skip = (name == "dev_plan_step_done" and
                        isinstance(result, dict) and
                        result.get("status") in ("already_done", "error"))
                if not skip:
                    try:
                        override = _progress_cb(name, args, result)
                        if isinstance(override, dict):
                            result = override
                    except Exception:
                        pass

            # Record tool outcome for proof validation (after override so "accepted" is captured)
            if name != "dev_plan_step_done":
                recent_tools.record(name, args, result)
            # Reset state when a new plan is created or a step is completed
            if name == "dev_plan_create" and isinstance(result, dict) and result.get("status") == "ok":
                recent_tools.clear()
                _call_counts.clear()
            if name == "dev_plan_step_done" and isinstance(result, dict) and result.get("status") == "ok":
                _call_counts.clear()

            _brut = (result if isinstance(result, str)
                     else json.dumps(result, ensure_ascii=False))
            messages.append(ToolMessage(
                content=tronquer_resultat(_brut),
                tool_call_id=tc["id"],
                name=name,
            ))

            if name == "dev_plan_step_done" and isinstance(result, dict) and result.get("remaining") == 0:
                _plan_complete = True

    trace = _build_specialist_trace(messages)
    _persist_session_memory(messages, enriched_task, "Tâche interrompue.", _settings.llm_backend)
    return trace + "Tâche interrompue (limite d'itérations atteinte)."  # end of _run
