"""Exécution séquentielle d'un projet par phases — réduit la consommation de tokens."""
from __future__ import annotations
import json, os
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.agents.coding.task_decomposer import decompose, Phase

# Marqueurs d'échec détectables dans le résultat du specialist (FR + EN)
_PHASE_FAILED_MARKERS = (
    "impossible d'invoquer le modèle",
    "contexte trop volumineux",
    "cannot invoke the model",
    "context too large",
    "rate limit",
    "quota exceeded",
    "resource_exhausted",
)
# TODO V2 : remplacer détection string par objet BuildResult(success, error_type)

_PHASE_ITER_BUDGET = {
    "mistral": 15, "groq": 35, "gemini": 40,
    "ollama_cloud": 35, "ollama": 12,
}


def _find_spec(project_name: str) -> Optional[Path]:
    from src.utils.paths import get_projects_dir
    p = Path(project_name)
    if p.is_file():
        return p
    candidate = get_projects_dir() / project_name / "spec.md"
    if candidate.is_file():
        return candidate
    for d in get_projects_dir().iterdir():
        if d.is_dir() and project_name.lower() in d.name.lower():
            c = d / "spec.md"
            if c.is_file():
                return c
    return None


def _atomic_write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        f.write(json.dumps(data, indent=2, ensure_ascii=False))
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _state_path(project_dir: Path) -> Path:
    return project_dir / ".axon" / "build-state.json"


def _load_state(project_dir: Path) -> Optional[dict]:
    p = _state_path(project_dir)
    if p.is_file():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return None


def _save_state(project_dir: Path, state: dict) -> None:
    _atomic_write_json(_state_path(project_dir), state)


def _load_axon_context(project_dir: Path) -> str:
    """Lit .axon/memory/ (journal + décisions) pour enrichir le contexte inter-phases."""
    parts = []
    mdir = project_dir / ".axon" / "memory"
    if not mdir.exists():
        return ""
    journal = mdir / "journal.md"
    if journal.is_file():
        content = journal.read_text(encoding="utf-8")
        entries = content.split("\n## ")
        if len(entries) > 1:
            last = "## " + entries[-1]
            parts.append(f"Dernière session (journal) :\n{last[:1500]}")
    decisions = mdir / "decisions.md"
    if decisions.is_file():
        content = decisions.read_text(encoding="utf-8")
        blocks = content.split("\n## ")
        recent = [b for b in blocks[1:3] if b.strip()]
        if recent:
            parts.append("Décisions récentes :\n" + "\n---\n".join(f"## {b}" for b in recent)[:1500])
    return "\n\n".join(parts)


def _compress_spec_for_phase(spec_text: str, phases: list[Phase], current: Phase) -> str:
    """Phase 1 reçoit la spec complète. Phases suivantes : intro + liste ultra-compacte."""
    if current.index == 1:
        return spec_text[:6000]
    intro = spec_text[:500]
    others = "\n".join(
        f"  Phase {p.index} ({p.title}) : {'✓ faite' if p.index < current.index else 'à venir'}"
        for p in phases if p.index != current.index
    )
    return f"{intro}\n\nAutres phases :\n{others}"


def _build_phase_task(phase: Phase, spec_text: str, project_name: str,
                      project_dir: Path, phases: list[Phase]) -> str:
    axon_ctx = _load_axon_context(project_dir)
    spec_part = _compress_spec_for_phase(spec_text, phases, phase)
    task = (
        f"[Phase {phase.index}/{len(phases)} — {phase.title}]\n"
        f"Projet : {project_name}\n\n"
        f"SCOPE DE CETTE PHASE (et uniquement ça) :\n{phase.scope}\n\n"
        f"RÈGLE ABSOLUE : Si une tâche n'est PAS dans le scope ci-dessus, ignore-la "
        f"même si tu sais la faire. Ne jamais anticiper sur les phases suivantes.\n\n"
        f"SPEC (référence) :\n{spec_part}\n\n"
    )
    if axon_ctx:
        task += f"CONTEXTE PROJET (sessions précédentes) :\n{axon_ctx}\n\n"
    task += (
        "Instructions :\n"
        "- Réalise UNIQUEMENT le scope défini ci-dessus.\n"
        "- Les phases précédentes ont déjà été exécutées — ne pas re-scaffolder.\n"
        "- En fin de phase : appelle axon_note() si une décision importante a été prise."
    )
    return task


def _phase_failed(result: str) -> bool:
    lower = result.lower()
    return any(marker in lower for marker in _PHASE_FAILED_MARKERS)


def run_build(project_name: str, console) -> None:
    from rich.text import Text
    from rich.rule import Rule
    from src.infra.settings import settings
    from src.agents.coding.specialist import run_coding_task, set_phase_max_iterations
    from src.agents.coding.pending import reset_specialist_state
    from src.ui.panels import command_panel

    ACCENT = "color(214)"

    spec_path = _find_spec(project_name)
    if spec_path is None:
        console.print(command_panel(
            f"spec.md introuvable pour '{project_name}' — lance d'abord /spec {project_name}",
            error=True
        ))
        return

    spec_text = spec_path.read_text(encoding="utf-8")
    project_dir = spec_path.parent

    console.print()
    console.print(Rule(f"build · {project_name}", characters="·", style=f"dim {ACCENT}"))

    # Vérifier si reprise possible
    existing_state = _load_state(project_dir)
    resume_from = 1
    if existing_state and existing_state.get("project") == project_name:
        completed = existing_state.get("completed", [])
        total = existing_state.get("total", 0)
        if completed and len(completed) < total:
            resume_from = max(completed) + 1
            t = Text()
            t.append("  ↺  ", style=f"bold {ACCENT}")
            t.append(f"reprise depuis la phase {resume_from} (complétées : {completed})", style="dim")
            console.print(t)

    # Décomposer (ou réutiliser plan existant)
    if existing_state and existing_state.get("phases_plan") and existing_state.get("project") == project_name:
        raw = existing_state["phases_plan"]
        phases = [Phase(index=p["index"], title=p["title"], scope=p["scope"]) for p in raw]
        console.print(Text("  ↺  plan de phases rechargé depuis build-state.json", style=f"dim {ACCENT}"))
    else:
        t = Text()
        t.append("  ⚙  ", style=f"bold {ACCENT}")
        t.append("décomposition de la spec en phases…", style="dim")
        console.print(t)
        phases = decompose(spec_text, settings.llm_backend)

    for ph in phases:
        done = ph.index < resume_from
        t = Text()
        t.append(f"  {'✓' if done else str(ph.index)}. ", style=f"bold {'green' if done else ACCENT}")
        t.append(ph.title, style="dim" if done else "white")
        console.print(t)
    console.print()

    phase_iter_budget = _PHASE_ITER_BUDGET.get(settings.llm_backend, 20)

    build_state = {
        "project": project_name,
        "spec_path": str(spec_path),
        "total": len(phases),
        "completed": list(range(1, resume_from)),
        "failed": [],
        "last_run": datetime.now().isoformat(),
        "backend": settings.llm_backend,
        "phases_plan": [{"index": p.index, "title": p.title, "scope": p.scope} for p in phases],
    }
    _save_state(project_dir, build_state)

    for phase in phases:
        if phase.index < resume_from:
            continue

        console.print(Rule(
            f"phase {phase.index}/{len(phases)} · {phase.title}",
            characters="─", style=f"dim {ACCENT}"
        ))

        # Isolation : reset tous les singletons + budget d'itérations
        reset_specialist_state()
        set_phase_max_iterations(phase_iter_budget)

        task = _build_phase_task(phase, spec_text, project_name, project_dir, phases)

        success = False
        result = ""
        for attempt in range(2):
            try:
                result = run_coding_task(task)
                if _phase_failed(result):
                    raise RuntimeError(result[:120])
                success = True
                break
            except Exception as exc:
                if attempt == 0:
                    t = Text()
                    t.append("  ⚠  ", style="bold yellow")
                    t.append(f"phase {phase.index} échouée, retry… ({str(exc)[:80]})", style="dim yellow")
                    console.print(t)
                    reset_specialist_state()
                    set_phase_max_iterations(phase_iter_budget)

        set_phase_max_iterations(None)

        if success:
            build_state["completed"].append(phase.index)
            summary = " ".join(
                l for l in result.splitlines()
                if l.strip()
                   and not l.startswith("[SPECIALIST") and not l.startswith("[/SPECIALIST")
                   and not l.startswith("cwd:") and not l.startswith("files:") and not l.startswith("plan:")
            )
            if summary:
                console.print(Text("  " + summary[:140], style="dim"))
        else:
            build_state["failed"].append(phase.index)
            t = Text()
            t.append("  ✗  ", style="bold red")
            t.append(f"phase {phase.index} échouée après retry — build continue", style="dim red")
            console.print(t)

        build_state["last_run"] = datetime.now().isoformat()
        _save_state(project_dir, build_state)
        console.print()

    failed = build_state["failed"]
    console.print(Rule("build terminé", characters="·", style=f"dim {ACCENT}"))
    t = Text()
    if not failed:
        t.append("  ✓  ", style=f"bold {ACCENT}")
        t.append(f"{len(phases)} phases · spec : ", style="dim")
        t.append(str(spec_path), style=ACCENT)
    else:
        t.append("  ⚠  ", style="bold yellow")
        t.append(
            f"terminé avec échecs phases {failed} · relance /build {project_name} pour reprendre",
            style="dim"
        )
    console.print(t)
