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
    ("/clear",             "efface l'écran et réaffiche l'en-tête"),
    ("/new",               "démarre un nouveau thread de conversation"),
    ("/history",           "liste les threads passés et permet d'en reprendre un (flèches ↑↓)"),
    ("/help",              "affiche cette liste de commandes"),
    ("/backend",       "change le backend LLM — groq · ollama · ollama_cloud · gemini · mistral"),
    ("/model <nom>",       "change le modèle du backend actif (ex: llama3.1:8b, openai/gpt-oss-20b)"),
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
    ("q / exit",           "quitte Axon"),
    ("Ctrl+T",             "bascule le mode plan — l'IA planifie sans écrire"),
    ("Ctrl+O",             "attacher un fichier  (= /attach)"),
    ("Ctrl+P",             "coller une image     (= /paste)"),
    ("Ctrl+D",             "supprimer toutes les pièces jointes"),
    ("@fichier",           "injecte un fichier dans ton message — autocomplété par Tab"),
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
