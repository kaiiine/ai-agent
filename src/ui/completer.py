from __future__ import annotations

import subprocess
import time
from pathlib import Path

from prompt_toolkit.completion import Completer, Completion

_COMMANDS: list[tuple[str, str]] = [
    ("/attach",       "joint un fichier à ton prochain message"),
    ("/paste",        "colle une image depuis le presse-papiers"),
    ("/attachments",  "liste les pièces jointes en attente"),
    ("/detach",       "supprime une pièce jointe (ou toutes)"),
    ("/fiche",        "génère une fiche de révision depuis les PDF joints"),
    ("/exo",          "génère des exercices interactifs depuis les PDF joints"),
    ("/letter",       "génère une lettre de motivation"),
    ("/upgrade",      "améliore une lettre existante"),
    ("/clear",        "efface l'écran"),
    ("/new",          "démarre un nouveau thread"),
    ("/history",      "liste les threads passés"),
    ("/help",         "liste des commandes disponibles"),
    ("/backend",      "backend LLM — groq · ollama · ollama_cloud · gemini"),
    ("/model",        "change le modèle du backend actif"),
    ("/temp",         "change la température  ex: /temp 0.7"),
    ("/lang",         "force la langue — fr · en · auto"),
    ("/save",         "sauvegarde le transcript"),
    ("/config",       "affiche la configuration courante"),
    ("/undo",         "annule les dernières modifications"),
    ("/branch",       "fork le thread actuel pour explorer une autre piste"),
    ("/mode",         "mode d'édition — ask · auto"),
    ("/debug",        "active/désactive le mode debug"),
    ("/dump",         "affiche tous les messages du thread"),
]

_SUBCOMMANDS: dict[str, list[str]] = {
    "/backend": ["groq", "ollama", "ollama_cloud", "gemini"],
    "/lang":    ["fr", "en", "auto"],
    "/mode":    ["ask", "auto"],
}

# ── File cache for @ completion (invalidated on cwd change or TTL) ────────────
_file_cache: list[str] = []
_file_cache_ts: float = 0.0
_file_cache_cwd: str = ""
_CACHE_TTL = 5.0

_FS_EXCLUDE = {
    "node_modules", ".git", ".next", "dist", "build",
    "__pycache__", ".venv", "venv", ".mypy_cache", "coverage",
}


class SlashCompleter(Completer):
    def get_completions(self, document, complete_event):
        text = document.text_before_cursor

        at_idx = text.rfind("@")
        if at_idx != -1 and (at_idx == 0 or text[at_idx - 1] in " \t"):
            query = text[at_idx + 1:]
            if " " not in query:
                yield from self._at_completions(query)
                return

        if not text.startswith("/"):
            return

        parts = text.split(" ", 1)
        cmd = parts[0]

        if len(parts) == 2:
            sub = parts[1]
            options = _SUBCOMMANDS.get(cmd) or (self._model_options() if cmd == "/model" else [])
            for opt in options:
                if opt.startswith(sub):
                    yield Completion(opt, start_position=-len(sub))
            return

        for full_cmd, desc in _COMMANDS:
            if full_cmd.startswith(cmd):
                yield Completion(full_cmd, start_position=-len(cmd), display_meta=desc)

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

    def _model_options(self) -> list[str]:
        try:
            from src.infra.settings import settings
            from src.ui.commands import _get_model_options
            return _get_model_options(settings.llm_backend)
        except Exception:
            return []
