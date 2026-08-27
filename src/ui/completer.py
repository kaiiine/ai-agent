from __future__ import annotations

import subprocess
import time
from pathlib import Path

from prompt_toolkit.completion import Completer, Completion

_COMMANDS: list[tuple[str, str]] = [
    ("/compact", "compresse le contexte de la session courante en un résumé dense"),
    ("/attach",            "joint un fichier (code, texte, PDF, image) à ton prochain message"),
    ("/paste",             "colle une image depuis le presse-papiers"),
    ("/attachments",       "liste les pièces jointes en attente"),
    ("/detach [fichier]",  "supprime une pièce jointe (ou toutes si sans argument)"),
    ("/letter",            "génère une lettre de motivation — attach ton CV d'abord, puis colle l'offre"),
    ("/upgrade",           "améliore une lettre existante — attach ton CV, colle la lettre puis l'offre"),
    ("/fiche",             "fiche de révision HTML/CSS depuis PDF(s) — /attach tes cours d'abord"),
    ("/exo",               "exercices interactifs HTML/JS (QCM, ouvert…) depuis PDF(s) — /attach tes cours"),
    ("/spec [prompt]",     "wizard interactif de spécification — l'IA pose des questions guidées"),
    ("/build [projet]",   "exécute spec.md par phases — 60-70% moins de tokens qu'une session unique"),
    ("/deep <sujet>",     "recherche approfondie — décompose en sous-questions, cherche, recoupe"),
    ("/clear",             "efface l'écran et réaffiche l'en-tête"),
    ("/new",               "démarre un nouveau thread de conversation"),
    ("/history",           "liste les threads passés et permet d'en reprendre un (flèches ↑↓)"),
    ("/help",              "affiche cette liste de commandes"),
    ("/backend",       "change le backend LLM — groq · ollama · ollama_cloud · gemini · mistral"),
    ("/model",       "change le modèle du backend actif (ex: llama3.1:8b, openai/gpt-oss-20b)"),
    ("/temp <val>",        "change la température (ex: /temp 0.7)"),
    ("/lang <fr|en>",      "force la langue de réponse"),
    ("/save",              "sauvegarde le transcript de la session"),
    ("/config",            "affiche la configuration courante"),
    ("/purge",             "supprime les blobs d'images bloqués dans l'état du thread courant"),
    ("/undo",              "annule les dernières modifications appliquées par le coding agent"),
    ("/mode <ask|auto>",   "mode d'édition — ask (valide fichier par fichier) ou auto (écrit sans confirmation)"),
    ("/branch",            "fork le thread actuel pour explorer une autre piste"),
    ("/debug",             "active/désactive le mode debug"),
    ("/dump",              "affiche tous les messages du thread"),
    ("/mcp",               "serveurs MCP — list · add · test · tools · refresh · restart…"),
    ("/graph",             "génère GRAPH_REPORT.md + graph.json + notes Obsidian via graphify"),
    ("/keys",              "état des clés API (multi-comptes) · /keys reset pour tout remettre sain"),
    ("q / exit",           "quitte Axon"),
    ("Ctrl+T",             "bascule le mode plan — l'IA planifie sans écrire"),
    ("Ctrl+O",             "attacher un fichier  (= /attach)"),
    ("Ctrl+P",             "coller une image     (= /paste)"),
    ("Ctrl+D",             "supprimer toutes les pièces jointes"),
    ("@fichier",           "injecte un fichier dans ton message — autocomplété par Tab"),
]

#: `/backend` N'EST PAS ici : sa liste est celle de `commands._BACKENDS`, et la
#: recopier la fait dériver. Elle avait déjà perdu `mistral`, puis `nvidia` —
#: deux backends utilisables que la complétion ne proposait pas, ce qui les rend
#: invisibles à qui découvre l'outil par la touche Tab.
_SUBCOMMANDS: dict[str, list[str]] = {
    "/lang":    ["fr", "en", "auto"],
    "/mode":    ["ask", "auto"],
}

# ── /mcp : sous-commandes, puis noms de serveurs ──────────────────────────────
_MCP_SUBCOMMANDS: dict[str, str] = {
    "list":    "état de tous les serveurs déclarés",
    "add":     "ajoute un serveur puis le teste",
    "remove":  "retire le serveur et désindexe ses tools",
    "enable":  "active, connecte et indexe",
    "disable": "désactive et désindexe",
    "test":    "diagnostic par étapes (--deep sonde un tool read-only)",
    "tools":   "schémas et table des trois noms",
    "refresh": "re-tools/list sans redémarrer le processus",
    "restart": "redémarre le sous-processus puis resynchronise",
}
# Sous-commandes attendant un nom de serveur en second argument.
_MCP_WANTS_SERVER = frozenset(_MCP_SUBCOMMANDS) - {"list", "add"}

# ── File cache for @ completion (invalidated on cwd change or TTL) ────────────
_file_cache: list[str] = []
_file_cache_ts: float = 0.0
_file_cache_cwd: str = ""
_CACHE_TTL = 5.0

_FS_EXCLUDE = {
    "node_modules", ".git", ".next", "dist", "build",
    "__pycache__", ".venv", "venv", ".mypy_cache", "coverage",
}


def at_query(text: str) -> str | None:
    """Le fragment de chemin en cours de saisie après un `@`, ou `None`.

    Un `@` ne compte que collé au début d'un mot — sinon une adresse e-mail
    ouvrirait un menu de fichiers. Le fragment s'arrête au premier espace : au-delà,
    l'utilisateur écrit autre chose.
    """
    at_idx = text.rfind("@")
    if at_idx == -1 or not (at_idx == 0 or text[at_idx - 1] in " \t"):
        return None
    query = text[at_idx + 1:]
    return None if " " in query else query


def completion_context(text: str) -> bool:
    """Ce texte appartient-il au menu de complétion ?

    Source unique de vérité, partagée avec la suggestion de saisie
    (`src/ui/suggest.py`). Les deux mécanismes se disputent la touche Tab : s'ils
    délimitaient leur territoire chacun de leur côté, une divergence rendrait Tab
    imprévisible sans qu'aucun test ne le voie.
    """
    return text.startswith("/") or at_query(text) is not None


class SlashCompleter(Completer):
    def get_completions(self, document, complete_event):
        text = document.text_before_cursor

        query = at_query(text)
        if query is not None:
            yield from self._at_completions(query)
            return

        if not text.startswith("/"):
            return

        parts = text.split(" ", 1)
        cmd = parts[0]

        if len(parts) == 2:
            sub = parts[1]
            if cmd == "/mcp":
                yield from self._mcp_completions(sub)
                return
            if cmd == "/backend":
                options = self._backend_options()
            elif cmd == "/model":
                options = self._model_options()
            else:
                options = _SUBCOMMANDS.get(cmd, [])
            for opt in options:
                if opt.startswith(sub):
                    yield Completion(opt, start_position=-len(sub))
            return

        for full_cmd, desc in _COMMANDS:
            if full_cmd.startswith(cmd):
                yield Completion(full_cmd, start_position=-len(cmd), display_meta=desc)

    def _mcp_completions(self, sub: str):
        """Trois niveaux : sous-commande, puis nom de serveur, puis `--deep`."""
        tokens = sub.split(" ")
        current = tokens[-1]

        if len(tokens) == 1:
            for opt, desc in _MCP_SUBCOMMANDS.items():
                if opt.startswith(current):
                    yield Completion(opt, start_position=-len(current), display_meta=desc)
            return

        action = tokens[0]
        if len(tokens) == 2 and action in _MCP_WANTS_SERVER:
            for name, state in self._mcp_servers():
                if name.startswith(current):
                    yield Completion(name, start_position=-len(current), display_meta=state)
        elif len(tokens) == 3 and action == "test" and "--deep".startswith(current):
            yield Completion("--deep", start_position=-len(current),
                             display_meta="sonde un tool read-only (effets de bord possibles)")

    def _mcp_servers(self) -> list[tuple[str, str]]:
        """Serveurs déjà connus du runtime, avec leur état.

        On lit le singleton SANS jamais le démarrer : la complétion s'exécute à
        chaque frappe, elle ne doit pouvoir ni lancer de sous-processus ni lire
        une configuration. Runtime absent -> aucune proposition."""
        try:
            from src.mcp_client import runtime as _runtime_module

            current = _runtime_module._runtime
            if current is None:
                return []
            return sorted((name, rt.state.value) for name, rt in current.status().items())
        except Exception:
            return []

    def _at_completions(self, query: str):
        ql = query.lower()
        for filepath in self._files():
            if ql in filepath.lower():
                yield Completion(
                    filepath,
                    start_position=-len(query),
                    display=f"  {Path(filepath).name}",
                    display_meta=filepath,
                )

    def _files(self) -> list[str]:
        global _file_cache, _file_cache_ts, _file_cache_cwd
        try:
            from src.agents.shell.tools import get_cwd
            cwd = str(get_cwd())
        except Exception:
            cwd = ""
        now = time.monotonic()
        if cwd == _file_cache_cwd and now - _file_cache_ts < _CACHE_TTL:
            return _file_cache
        base = Path(cwd) if cwd else Path.cwd()
        try:
            r = subprocess.run(
                ["git", "ls-files"], capture_output=True, text=True, timeout=5, cwd=str(base)
            )
            files = r.stdout.strip().splitlines()
            if not files:
                files = [
                    str(p.relative_to(base))
                    for p in base.rglob("*")
                    if p.is_file() and not any(x in _FS_EXCLUDE for x in p.parts)
                ]
        except Exception:
            files = []
        _file_cache = files
        _file_cache_ts = now
        _file_cache_cwd = cwd
        return _file_cache

    def _backend_options(self) -> list[str]:
        """La liste qui fait foi, lue chez `commands` — jamais recopiée."""
        try:
            from src.ui.commands import _BACKENDS
            return list(_BACKENDS)
        except Exception:
            return []

    def _model_options(self) -> list[str]:
        try:
            from src.infra.settings import settings
            from src.ui.commands import _get_model_options
            return _get_model_options(settings.llm_backend)
        except Exception:
            return []
