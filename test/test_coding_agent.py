"""Tests for new coding-agent invariants: inline spec detection, proof type guards,
and repetition-exempt set membership."""
import pytest
from src.agents.coding.pending import recent_tools


@pytest.fixture(autouse=True)
def reset_recent_tools():
    recent_tools.clear()
    yield
    recent_tools.clear()


# ── _extract_inline_spec ──────────────────────────────────────────────────────

BRIEF_SAMPLE = """\
## Visual direction
Background: #ffffff  Text: #111111  Accent: #c0392b
No UI library. Custom components only.
No animations. Sharp edges. No border-radius. No box-shadow.

## Section structure

### 01 — Hero
Titre : "Communiquer comme une grande équipe."
Sous-titre : CRM, newsletter, veille — unifiés.
CTA : lien texte uniquement, jamais un bouton.
Colonne droite : modules en rotation géométrique — noms en gris.

### 02 — La plateforme
8 modules réels : Dashboard, CRM, Newsletter, Terrain, Mémoire, Veille,
Réseaux sociaux, Analytics. Grille 4×2 avec hover rouge sur le numéro.

### 03 — Milo IA
3 échanges Q&A en langage naturel. Fond noir, monospace.

### 04 — Contact
Formulaire : Prénom, Email, Rôle (select), Message.
Bouton submit : texte seul "Envoyer →", aucun fond.
"""


def test_spec_detected_in_brief():
    from src.agents.coding.task_enricher import _extract_inline_spec
    result = _extract_inline_spec("Créer un site.\n" + BRIEF_SAMPLE)
    assert result is not None
    preview, path = result
    assert "Visual direction" in preview


def test_spec_preview_contains_first_section():
    from src.agents.coding.task_enricher import _extract_inline_spec
    preview, _ = _extract_inline_spec("Build this.\n" + BRIEF_SAMPLE)
    assert "No UI library" in preview


def test_spec_not_detected_in_short_task():
    from src.agents.coding.task_enricher import _extract_inline_spec
    result = _extract_inline_spec("Crée-moi une app Next.js avec une page d'accueil.")
    assert result is None


def test_spec_not_detected_single_section():
    from src.agents.coding.task_enricher import _extract_inline_spec
    single = "## Section\n" + "x" * 600
    result = _extract_inline_spec(single)
    assert result is None


def test_spec_writes_temp_file(tmp_path, monkeypatch):
    import hashlib
    from src.agents.coding.task_enricher import _extract_inline_spec, _SPEC_FILE_PREFIX
    result = _extract_inline_spec("Task.\n" + BRIEF_SAMPLE)
    assert result is not None
    _, path = result
    if path:
        from pathlib import Path
        assert Path(path).exists()
        assert Path(path).read_text(encoding="utf-8").startswith("## Visual direction")


# ── enrich_task with spec ──────────────────────────────────────────────────────

def test_enrich_task_with_spec_adds_label():
    from src.agents.coding.task_enricher import enrich_task
    enriched = enrich_task("Crée un site.\n" + BRIEF_SAMPLE)
    assert "SPEC PERMANENTE" in enriched


def test_enrich_task_spec_prefix_before_task():
    from src.agents.coding.task_enricher import enrich_task
    enriched = enrich_task("Crée un site.\n" + BRIEF_SAMPLE)
    spec_pos = enriched.index("SPEC PERMANENTE")
    task_pos = enriched.index("Crée un site.")
    assert spec_pos < task_pos


def test_enrich_task_without_spec_unchanged():
    from src.agents.coding.task_enricher import enrich_task
    task = "Corrige le bug dans src/app.py ligne 42."
    # No ## sections, no refs → must come back unchanged
    assert enrich_task(task) == task


# ── proof type guards ──────────────────────────────────────────────────────────

def test_analysis_proof_fails_when_no_read_tool():
    from src.agents.coding.tools import dev_plan_create, dev_plan_step_done
    dev_plan_create.invoke({"steps": ["Analyser le projet"]})
    # recent_tools already cleared by fixture
    result = dev_plan_step_done.invoke({"step_index": 0, "proof_type": "analysis"})
    assert result["status"] == "error"
    assert "analyse" in result["error"].lower() or "outil" in result["error"].lower()


def test_analysis_proof_passes_after_read_tool():
    from src.agents.coding.tools import dev_plan_create, dev_plan_step_done
    from src.agents.coding.pending import recent_tools
    dev_plan_create.invoke({"steps": ["Analyser le projet"]})
    recent_tools.record("local_read_file", {"path": "/tmp/x.py"}, {"content": "ok"})
    result = dev_plan_step_done.invoke({"step_index": 0, "proof_type": "analysis"})
    assert result["status"] == "ok"


def test_file_written_proof_fails_when_not_written(tmp_path):
    from src.agents.coding.tools import dev_plan_create, dev_plan_step_done
    dev_plan_create.invoke({"steps": ["Créer composant"]})
    fake_path = str(tmp_path / "component.tsx")
    result = dev_plan_step_done.invoke({
        "step_index": 0, "proof_type": "file_written", "proof_path": fake_path
    })
    assert result["status"] == "error"
    assert "propose_file_change" in result["error"]


def test_file_written_proof_passes_after_propose(tmp_path):
    from src.agents.coding.tools import dev_plan_create, dev_plan_step_done
    from src.agents.coding.pending import recent_tools
    dev_plan_create.invoke({"steps": ["Créer composant"]})
    written = tmp_path / "component.tsx"
    written.write_text("export default function Comp() { return <div>ok</div>; }")
    recent_tools.record(
        "propose_file_change",
        {"path": str(written)},
        {"status": "accepted", "path": str(written)},
    )
    result = dev_plan_step_done.invoke({
        "step_index": 0, "proof_type": "file_written", "proof_path": str(written)
    })
    assert result["status"] == "ok"


# ── _REPETITION_EXEMPT membership ─────────────────────────────────────────────

def test_repetition_exempt_excludes_read_tools():
    """Read tools must NOT be in _REPETITION_EXEMPT — that's what the guard is for."""
    from src.agents.coding.specialist import _REPETITION_EXEMPT
    read_tools = {"local_read_file", "notebook_read", "local_grep", "local_glob"}
    overlap = read_tools & _REPETITION_EXEMPT
    assert not overlap, f"Read tools in exempt set (would bypass guard): {overlap}"


def test_repetition_exempt_contains_write_tools():
    """Write/plan tools must be in _REPETITION_EXEMPT — blocking them would break the agent."""
    from src.agents.coding.specialist import _REPETITION_EXEMPT
    required = {"dev_plan_create", "dev_plan_step_done", "propose_file_change", "shell_run"}
    missing = required - _REPETITION_EXEMPT
    assert not missing, f"Write/plan tools missing from exempt set: {missing}"
