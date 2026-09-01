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


#: Observateurs PASSIFS d'appels d'outils. Volontairement séparés de
#: `_progress_cb`, qui peut remplacer un résultat (`override`) : un canal capable
#: de modifier ce que le modèle lit ne convient pas à un observateur, quelle que
#: soit la discipline de celui qui s'y branche.
#:
#: La valeur de retour d'un observateur est IGNORÉE. Il reçoit le résultat pour le
#: lire ; le contrat est de ne pas le muter, et il est vérifié par un test côté
#: appelant plutôt que par une copie défensive — copier chaque résultat d'outil
#: coûterait à chaque appel pour protéger d'un défaut qui ne s'est pas produit.
_observateurs: list[Callable[[str, object], None]] = []


def ajouter_observateur(cb: Callable[[str, object], None]) -> None:
    if cb not in _observateurs:
        _observateurs.append(cb)


def retirer_observateur(cb: Callable[[str, object], None]) -> None:
    if cb in _observateurs:
        _observateurs.remove(cb)


def _observer(nom: str, resultat: object) -> None:
    """Prévient les observateurs. Ne rend rien, ne propage aucune exception."""
    for obs in tuple(_observateurs):
        try:
            obs(nom, resultat)
        except Exception:   # noqa: BLE001
            pass


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
        find_git_repos, propose_file_change, propose_file_delete, deleguer, edit_file, load_skill,
        project_graph_query,
    )
    # Les requêtes du graphe, et de quoi le CONSTRUIRE : sans `graph_build`,
    # `no_graph` renvoyait vers `/graph`, une commande de l'interface que le
    # modèle ne peut pas taper — une impasse, dont il ressortait en lisant les
    # fichiers un à un. `project_graph_query` reste en repli : il ne fait qu'une
    # correspondance de sous-chaîne, mais il n'a besoin d'aucun sous-processus si
    # graphify venait à manquer.
    from src.agents.coding.graphe import (
        graph_affected, graph_build, graph_explain, graph_path, graph_query,
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
        find_git_repos, propose_file_change, propose_file_delete, edit_file, load_skill,
        # `deleguer` ouvre un éventail d'explorations en lecture seule : le
        # modèle reçoit un rapport, pas les vingt lectures qui l'ont produit.
        deleguer,
        graph_affected, graph_build, graph_explain, graph_path, graph_query,
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

#: Ce qu'une exploration déléguée peut appeler. Lecture seule, délibérément :
#: elle tourne sous `Send`, où une interruption ne remonte pas proprement — donc
#: rien qui puisse exiger un accord. Elle rapporte, elle ne construit pas.
_OUTILS_LECTURE = frozenset({
    "local_read_file", "local_grep", "local_glob", "local_find_file",
    "local_list_directory", "graph_query", "graph_explain", "graph_path",
    "graph_affected", "git_log", "git_diff", "git_status", "notebook_read",
})

#: Les statuts par lesquels un outil refuse — mêmes noms que dans `cron_daemon`.
_STATUTS_DE_REFUS = ("requires_confirmation", "blocked")


def _refus_definitif(nom: str, resultat):
    """Transforme un refus en impasse explicite, pour que le modèle change de voie.

    Le specialist n'a pas de graphe : aucun questionnaire ne peut s'afficher
    depuis sa boucle. Un refus y est donc irrécupérable, et le présenter comme un
    incident passager invite à réessayer.
    """
    if not isinstance(resultat, dict) or resultat.get("status") not in _STATUTS_DE_REFUS:
        return resultat
    return {
        "status": "error",
        "error": (
            f"`{nom}` a refusé cette commande ({resultat.get('reason') or 'non autorisée'}) "
            "et AUCUNE confirmation ne peut être demandée depuis l'agent de code. "
            "Ne relance pas la même commande : elle sera refusée à l'identique. "
            "Passe par `edit_file` ou `propose_file_change` pour écrire un fichier, "
            "ou termine en expliquant ce qui reste à faire à l'utilisateur."
        ),
        "command": resultat.get("command"),
    }
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
    "nvidia":       60_000,   # aligné sur la fenêtre prudente de context.py
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
    """Un run complet, HORS graphe. `/build` passe par ici, phase par phase.

    Aucune confirmation n'y est possible : rien au-dessus ne sait interrompre.
    Le chemin normal est le nœud `coder`, qui invoque le même sous-graphe depuis
    le graphe principal.
    """
    from src.agents.coding.pending import dev_plan

    _vram_swap_in()
    try:
        # Le temps de ce run SEULEMENT, écrire un fichier exige d'avoir planifié.
        with dev_plan.run_specialist():
            graphe, finaliser = preparer(task)
            return finaliser(graphe.invoke({"tache": task}))
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





#: Relances déjà consommées sur un plan inachevé, pour ce run.
_relances = {"texte": 0, "outils": 0, "skill": False, "produit": False, "vide": 0}

#: Les outils qui PRODUISENT quelque chose. Conclure sans en avoir appelé un
#: seul, c'est avoir décrit le travail au lieu de le faire — vécu : le modèle
#: rendait le plan dans `dev_explain` et le fichier en texte, sans jamais
#: appeler `propose_file_change`.
_OUTILS_PRODUCTIFS = frozenset({
    "propose_file_change", "propose_file_delete", "edit_file", "shell_run",
    "notebook_edit_cell", "notebook_insert_cell", "git_commit",
})


def interpreter_reponse(reponse, messages: list, tool_map: dict, tache: str):
    """`(appels, fini, rappel)` — ce que la boucle décidait après chaque réponse.

    Trois politiques qui n'ont rien de structurel et qui restent donc ici :
    récupérer un appel d'outil écrit en JSON (les petits modèles le font),
    refuser de conclure sur un plan inachevé, et rappeler `load_skill` sur une
    tâche front.
    """
    from src.agents.coding.pending import dev_plan

    appels = list(getattr(reponse, "tool_calls", None) or [])

    if not appels and getattr(reponse, "content", ""):
        parse = _extract_json_tool_call(reponse.content)
        if parse and parse["name"] in tool_map:
            appels = [{"name": parse["name"], "args": parse["args"], "id": str(uuid.uuid4())}]

    if appels:
        _relances["outils"] += 1
        if any(a["name"] in _OUTILS_PRODUCTIFS for a in appels):
            _relances["produit"] = True
        if (_relances["outils"] == 5 and not _relances["skill"]
                and any(mot in tache.lower() for mot in _FRONTEND_KW)
                and not any(a["name"] == "load_skill" for a in appels)):
            return appels, False, (
                "[Rappel automatique] load_skill() n'a pas encore été appelé après "
                "5 actions. Charge le guide de la stack avant de continuer.")
        if any(a["name"] == "load_skill" for a in appels):
            _relances["skill"] = True
        return appels, False, ""

    # Pas d'appel : conclure n'est légitime que si le plan est achevé.
    #
    # Et à condition d'avoir produit quelque chose. Sans plan, la première
    # réponse en texte terminait le run — le modèle décrivait son plan dans
    # `dev_explain`, écrivait le fichier en TEXTE, et personne ne relevait qu'il
    # n'avait rien proposé.
    if not _relances["produit"] and _relances["vide"] < 1:
        _relances["vide"] += 1
        return [], False, (
            "[SYSTEME] Tu n'as encore RIEN écrit : aucun fichier proposé, aucune "
            "commande lancée. Décrire le travail ne le fait pas. Appelle "
            "`propose_file_change` avec le contenu complet du fichier — c'est le "
            "seul moyen de le créer, et l'utilisateur le relira avant écriture.")

    reste = [e for e in dev_plan.steps if not e.done] if dev_plan.steps else []
    if not reste:
        return [], True, ""
    if _relances["texte"] < 2:
        _relances["texte"] += 1
        return [], False, ("[System] You still have incomplete plan steps. "
                           "Use your tools to continue — don't summarize yet.")
    # Un plan inachevé n'est pas un résultat, mais insister sans fin non plus.
    return [], True, ""


class SessionModele:
    """Un appel au modèle, et tout ce qu'il faut pour qu'il aboutisse.

    Extrait de la boucle sans rien changer : clés du pool essayées l'une après
    l'autre, bascule de fournisseur ANNONCÉE et persistée dans `settings`,
    compression sur erreur de contexte, backoff sur erreur serveur. Un nœud de
    graphe ne peut pas porter ça en variables locales — d'où l'objet.
    """

    def __init__(self) -> None:
        from src.infra.settings import settings as _settings
        from src.llm.key_pool import get_pool
        from src.llm.models import make_coding_llm_with_key

        self._faire = make_coding_llm_with_key
        self._pool = get_pool()
        self.fournisseur = _settings.llm_backend
        # Jamais de clé vide : un client sans clé s'authentifie avec l'identité
        # machine, donc sur un compte qu'on ne surveille pas.
        self.cle = self._pool.next_healthy(self.fournisseur) or ""
        if not self.cle:
            configurees = self._pool.keys_for(self.fournisseur) or []
            if configurees:
                self.cle = configurees[0]
        self.llm = self._faire(self.fournisseur, self.cle) if self.cle else _get_coding_llm()
        self.budget = _CONTEXT_CHAR_BUDGET.get(self.fournisseur, _CONTEXT_CHAR_BUDGET_DEFAULT)

    def _basculer(self, essayes: set[str]) -> bool:
        from src.infra.settings import settings as _settings
        from src.llm import rotation

        precedent = self.fournisseur
        essayes.add(self.fournisseur)
        trouve = rotation.fournisseur_suivant(essayes)
        if trouve is None:
            return False
        suivant, cle = trouve
        _settings.llm_backend = suivant
        self.fournisseur, self.cle = suivant, cle
        self.llm = self._faire(suivant, cle)
        self.budget = _CONTEXT_CHAR_BUDGET.get(suivant, _CONTEXT_CHAR_BUDGET_DEFAULT)
        _notifier("specialist:backend_switch",
                  {"from": precedent, "to": suivant, "key": cle[:10] + "..."})
        return True

    def appeler(self, messages: list, outils: list, lier: bool = True):
        """Rend `(reponse, echec, messages)`.

        `messages` peut différer de l'entrée : une erreur de contexte déclenche
        une compression, et c'est la liste compressée qui a servi.
        """
        import time as _time

        from src.llm import rotation

        derniere, en_faute = "aucune", self.fournisseur
        cles_essayees: set[str] = set()
        fournisseurs_essayes: set[str] = set()
        compresse = False
        tentatives = rotations = 0

        while tentatives < 3 and rotations < _MAX_ROTATIONS_CLE:
            essai = tentatives
            invoker = self.llm.bind_tools(outils) if (lier and outils) else self.llm
            try:
                return invoker.invoke(messages), None, messages
            except Exception as erreur:
                derniere, en_faute = str(erreur), self.fournisseur
                genre = rotation.classer_erreur(erreur)

                if genre in ("cle_morte", "quota"):
                    rotation.marquer_echec(self.fournisseur, self.cle, erreur)
                    cles_essayees.add(self.cle)
                    suivante = rotation.cle_suivante(self.fournisseur, cles_essayees)
                    if suivante:
                        self.cle = suivante
                        self.llm = self._faire(self.fournisseur, suivante)
                        _notifier("specialist:key_rotate", {
                            "provider": self.fournisseur,
                            "key": suivante[:10] + "...",
                            "raison": "clé invalide" if genre == "cle_morte" else "quota atteint",
                        })
                        rotations += 1        # une rotation n'est pas une tentative
                        continue
                    if self._basculer(fournisseurs_essayes):
                        cles_essayees.clear()
                        rotations += 1
                        continue
                    combien = len(self._pool.keys_for(self.fournisseur) or [])
                    return None, (
                        ECHEC_PREFIXE + f" Toutes les clés de « {self.fournisseur} » sont "
                        f"épuisées ou invalides ({combien} clé(s) configurée(s)), "
                        f"et aucun autre fournisseur n'a de clé disponible.\n"
                        f"Erreur du fournisseur : {derniere}\n"
                        "→ Attendre le renouvellement d'un quota, ou ajouter "
                        "une clé (`/config` pour l'état courant)."), messages

                if genre == "contexte":
                    if not compresse and len(messages) > 3:
                        messages = _compress_specialist_messages(messages, self.llm)
                        compresse = True
                        tentatives += 1
                        continue
                    # Au premier tour il n'y a rien à compresser : ne pas
                    # prétendre l'avoir fait.
                    quoi = ("même après compression" if compresse
                            else "et il n'y avait rien à compresser (premier tour)")
                    return None, (ECHEC_PREFIXE + f" Le modèle a refusé la requête {quoi}.\n"
                                  f"Erreur du fournisseur : {derniere}"), messages

                if genre == "serveur" and essai < 2:
                    _time.sleep(2 ** essai)
                    tentatives += 1
                    continue
                raise

        return None, (ECHEC_PREFIXE + " Aucun fournisseur LLM n'a répondu après 3 tentatives.\n"
                      f"Dernière erreur ({en_faute}) : {derniere}\n"
                      "→ Si c'est un quota : `/backend <autre>` pour changer de fournisseur, "
                      "et `/config` pour voir lequel est actif."), messages


def executer_un_outil(nom: str, args: dict, tool_map: dict, compteurs: dict) -> object:
    """Un appel d'outil, avec toute la politique qui l'entoure.

    Extrait de la boucle pour qu'un nœud de graphe puisse l'appeler tel quel :
    ce qui est réglé ici — garde anti-répétition, cache, aperçu shell, refus
    définitif, suivi du plan — ne doit pas être réécrit en changeant de
    structure. `compteurs` porte l'état du run que la boucle tenait en local.
    """
    from src.agents.coding.pending import dev_plan, recent_tools
    from src.infra.tools_cache import CACHEABLE_TOOLS, session_cache

    if _progress_cb and nom in _SHELL_PREVIEW_TOOLS:
        try:
            _progress_cb(f"{nom}:before", args)
        except Exception:
            pass

    cle = (nom, json.dumps(args, sort_keys=True, ensure_ascii=False, default=str))
    compteurs[cle] = compteurs.get(cle, 0) + 1

    outil = tool_map.get(nom)
    if not outil:
        resultat = {"status": "error", "error": f"Outil inconnu : {nom}"}
    elif compteurs[cle] >= 3 and nom not in _REPETITION_EXEMPT:
        resultat = {
            "status": "repeated_call",
            "message": (
                f"'{nom}' a été appelé {compteurs[cle]} fois avec les mêmes arguments. "
                "Le résultat n'a pas changé depuis la dernière lecture. "
                "→ Si tu attends un changement suite à une écriture, vérifie que "
                "propose_file_change a bien été accepté. "
                "→ Sinon, tu as déjà l'information — avance à l'étape suivante du plan."
            ),
        }
    elif nom in CACHEABLE_TOOLS and (hit := session_cache.get(nom, args)) is not None:
        resultat = hit
    else:
        def _flux(actif: bool) -> None:
            if nom != "shell_run":
                return
            try:
                from src.agents.shell.tools import set_shell_stream_callback
                if not actif:
                    set_shell_stream_callback(None)
                    return

                def _ligne(ligne: str):
                    if _progress_cb:
                        _progress_cb("shell_run:stream", {"line": ligne}, None)
                set_shell_stream_callback(_ligne)
            except Exception:
                pass

        try:
            _flux(True)
            resultat = outil.invoke(args)
            _flux(False)
            if nom in CACHEABLE_TOOLS:
                session_cache.set(nom, args, resultat)
            session_cache.on_tool_executed(nom)
        except Exception as erreur:
            _flux(False)
            resultat = {"status": "error", "error": str(erreur)}

    resultat = _refus_definitif(nom, resultat)
    _observer(nom, resultat)

    if _progress_cb and (nom in _PROGRESS_TOOLS or nom in _SHELL_PREVIEW_TOOLS):
        saute = (nom == "dev_plan_step_done" and isinstance(resultat, dict)
                 and resultat.get("status") in ("already_done", "error"))
        if not saute:
            try:
                remplacement = _progress_cb(nom, args, resultat)
                if isinstance(remplacement, dict):
                    resultat = remplacement
            except Exception:
                pass

    if nom != "dev_plan_step_done":
        recent_tools.record(nom, args, resultat)
    if nom == "dev_plan_create" and isinstance(resultat, dict) and resultat.get("status") == "ok":
        recent_tools.clear()
        compteurs.clear()
    if nom == "dev_plan_step_done" and isinstance(resultat, dict) and resultat.get("status") == "ok":
        compteurs.clear()
    return resultat


def preparer(task: str):
    """Le sous-graphe prêt à tourner, et de quoi finaliser sa sortie.

    Construire et invoquer sont séparés : le nœud `coder` du graphe principal
    invoque LUI-MÊME, sans passer par un outil. Un outil est atomique, et son
    enveloppe est ré-entrée à chaque reprise.

    Ce qui reste ici est la politique : quel client, quels outils, quoi faire
    d'une réponse. La structure — quels pas sont checkpointés, où l'on peut
    interrompre sans tout rejouer — est dans `graphe_agent.py`.
    """
    from src.agents.coding.graphe_agent import construire
    from src.agents.coding.task_enricher import enrich_task
    from src.agents.coding.tool_retriever import CodingToolRetriever, retrieval_query
    from src.infra.settings import settings as _settings

    global _phase_abort, _retriever_cache, _retriever_tool_names
    _phase_abort = False
    _relances.update({"texte": 0, "outils": 0, "skill": False,
                      "produit": False, "vide": 0})

    session = SessionModele()
    outils = _get_coding_tools()
    # `tool_map` couvre TOUS les outils : un outil non lié reste exécutable.
    par_nom = {o.name: o for o in outils}
    compteurs: dict = {}

    noms = tuple(o.name for o in outils)
    if _retriever_cache is None or _retriever_tool_names != noms:
        _retriever_cache = CodingToolRetriever(outils, k=8)
        _retriever_tool_names = noms
    retriever = _retriever_cache

    _notifier("specialist:start", {"model": getattr(session.llm, "model", "unknown")})
    try:
        from src.skills import warmup as _skill_warmup
        _skill_warmup()
    except Exception:
        pass

    tache_vue = {"texte": task}

    def _enrichir(brut: str) -> str:
        tache_vue["texte"] = enrich_task(brut)
        return tache_vue["texte"]

    def _selectionner(messages: list, tache: str) -> list:
        return retriever.get(retrieval_query(messages, tache or tache_vue["texte"]))

    def _appeler(messages: list, actifs: list, _fournisseur: str):
        if _phase_abort:
            return None, (ECHEC_PREFIXE + " Tâche interrompue (boucle détectée — "
                          "phase abandonnée par le système)."), messages
        return session.appeler(messages, actifs)

    def _interpreter(reponse, messages: list):
        return interpreter_reponse(reponse, messages, par_nom, tache_vue["texte"])

    sous_graphe = construire(
        outils=outils,
        selectionner=_selectionner,
        appeler_modele=_appeler,
        enrichir=_enrichir,
        prompt_systeme=BASE_PROMPT,
        executer=lambda nom, args: executer_un_outil(nom, args, par_nom, compteurs),
        tracer=_build_specialist_trace,
        rendre=lambda r: tronquer_resultat(
            r if isinstance(r, str) else json.dumps(r, ensure_ascii=False, default=str)),
        interpreter=_interpreter,
        outils_exploration=[o for o in outils if o.name in _OUTILS_LECTURE],
        notifier=_notifier,
    )

    def finaliser(sortie: dict) -> str:
        resultat = _clean_output(str(sortie.get("resultat") or "")) or "Task completed"
        _persist_session_memory(sortie.get("messages") or [], tache_vue["texte"],
                                resultat, _settings.llm_backend)
        return resultat

    return sous_graphe, finaliser
