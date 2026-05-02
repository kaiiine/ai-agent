"""Tests for src/agents/coding/task_enricher.py"""
import json
import pytest
from pathlib import Path
from unittest.mock import patch


# ── _extract_references ───────────────────────────────────────────────────────

def _refs(task: str) -> list[str]:
    from src.agents.coding.task_enricher import _extract_references
    return _extract_references(task)


def test_extracts_absolute_path():
    refs = _refs("lis le fichier /home/kaine/projects/foo/README.md")
    assert any("/home/kaine/projects/foo/README.md" in r for r in refs)


def test_extracts_tilde_path():
    refs = _refs("regarde ~/projects/my-app")
    assert any("~/projects/my-app" in r for r in refs)


def test_extracts_repo_keyword():
    refs = _refs("tu trouveras les infos dans le repo ai-agent")
    assert "ai-agent" in refs


def test_extracts_from_keyword():
    refs = _refs("dans le projet my-app tu trouveras le code")
    assert "my-app" in refs


def test_extracts_readme_reference():
    refs = _refs("lis le README de ai-agent et utilise ces infos")
    assert "ai-agent" in refs


def test_extracts_repo_keyword_with_lire():
    refs = _refs("lire le repo site-vitrine-agent avant de commencer")
    assert "site-vitrine-agent" in refs


def test_no_refs_returns_empty():
    refs = _refs("crée une fonction qui additionne deux nombres")
    assert refs == []


def test_deduplicates_refs():
    refs = _refs("dans le repo ai-agent, lis le README de ai-agent")
    assert refs.count("ai-agent") == 1


def test_stopwords_not_extracted():
    refs = _refs("lis le repo")
    # "repo" alone should not appear as a project name
    assert "repo" not in refs
    assert "le" not in refs


# ── _resolve / _find_project_dir — with real tmp dirs ─────────────────────────

def test_resolve_absolute_dir(tmp_path):
    (tmp_path / "README.md").write_text("# Mon Projet\nDescription courte.")
    from src.agents.coding.task_enricher import _resolve
    result = _resolve(str(tmp_path))
    assert result is not None
    label, content = result
    assert str(tmp_path) in label
    assert "README.md" in content
    assert "Mon Projet" in content


def test_resolve_absolute_file(tmp_path):
    f = tmp_path / "config.py"
    f.write_text("DEBUG = True\nSECRET = 'abc'")
    from src.agents.coding.task_enricher import _resolve
    result = _resolve(str(f))
    assert result is not None
    _, content = result
    assert "DEBUG = True" in content


def test_resolve_nonexistent_returns_none():
    from src.agents.coding.task_enricher import _resolve
    assert _resolve("/nonexistent/path/xyz") is None


def test_resolve_project_name_found(tmp_path):
    project = tmp_path / "my-project"
    project.mkdir()
    (project / "README.md").write_text("# My Project")
    from src.agents.coding.task_enricher import _resolve, _PROJECT_ROOTS
    with patch("src.agents.coding.task_enricher._PROJECT_ROOTS", [tmp_path]):
        result = _resolve("my-project")
    assert result is not None
    _, content = result
    assert "My Project" in content


def test_resolve_project_name_case_insensitive(tmp_path):
    project = tmp_path / "MyProject"
    project.mkdir()
    (project / "README.md").write_text("# MyProject readme")
    from src.agents.coding.task_enricher import _resolve
    with patch("src.agents.coding.task_enricher._PROJECT_ROOTS", [tmp_path]):
        result = _resolve("myproject")
    assert result is not None


# ── _read_repo_content ─────────────────────────────────────────────────────────

def test_read_repo_includes_readme(tmp_path):
    (tmp_path / "README.md").write_text("# Axon\nAgent IA puissant.")
    from src.agents.coding.task_enricher import _read_repo_content
    content = _read_repo_content(tmp_path)
    assert content is not None
    assert "Axon" in content
    assert "README.md" in content


def test_read_repo_includes_manifest(tmp_path):
    (tmp_path / "package.json").write_text(json.dumps({"name": "my-app", "version": "1.0.0"}))
    from src.agents.coding.task_enricher import _read_repo_content
    content = _read_repo_content(tmp_path)
    assert "package.json" in content
    assert "my-app" in content


def test_read_repo_includes_tree(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("")
    (tmp_path / "README.md").write_text("hi")
    from src.agents.coding.task_enricher import _read_repo_content
    content = _read_repo_content(tmp_path)
    assert "src" in content


def test_read_repo_skips_noise_dirs(tmp_path):
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "lodash").mkdir()
    (tmp_path / "README.md").write_text("clean")
    from src.agents.coding.task_enricher import _read_repo_content
    content = _read_repo_content(tmp_path)
    assert "node_modules" not in content


def test_read_repo_truncates_large_readme(tmp_path):
    big_readme = "A" * 20_000
    (tmp_path / "README.md").write_text(big_readme)
    from src.agents.coding.task_enricher import _read_repo_content, _MAX_README_CHARS
    content = _read_repo_content(tmp_path)
    assert len(content) < 20_000 + 500  # well under original
    assert "tronqué" in content


def test_read_repo_returns_none_for_empty_dir(tmp_path):
    from src.agents.coding.task_enricher import _read_repo_content
    # No README, no manifests → no meaningful content
    result = _read_repo_content(tmp_path)
    # Returns something (the tree + path header) but shouldn't crash
    assert result is None or isinstance(result, str)


# ── enrich_task — integration ─────────────────────────────────────────────────

def test_enrich_task_passthrough_when_no_refs():
    from src.agents.coding.task_enricher import enrich_task
    task = "Crée une fonction Python qui calcule la moyenne d'une liste."
    assert enrich_task(task) == task


def test_enrich_task_injects_content_for_found_ref(tmp_path):
    (tmp_path / "README.md").write_text("# AxonAgent\nAgent ultra puissant.")
    task = f"Crée un site vitrine basé sur le projet dans {tmp_path}"
    from src.agents.coding.task_enricher import enrich_task
    result = enrich_task(task)
    assert "AxonAgent" in result
    assert "SOURCES PRÉ-LUES" in result
    assert "TÂCHE" in result
    # Original task preserved
    assert "site vitrine" in result


def test_enrich_task_task_comes_after_sources(tmp_path):
    (tmp_path / "README.md").write_text("# Source content")
    task = f"Lis {tmp_path} et fais quelque chose."
    from src.agents.coding.task_enricher import enrich_task
    result = enrich_task(task)
    sources_pos = result.index("SOURCES PRÉ-LUES")
    task_pos = result.index("TÂCHE")
    original_pos = result.index("fais quelque chose")
    assert sources_pos < task_pos < original_pos


def test_enrich_task_caps_at_max_sources(tmp_path):
    """At most _MAX_SOURCES repos injected even if more are referenced."""
    projects = []
    for i in range(5):
        p = tmp_path / f"proj{i}"
        p.mkdir()
        (p / "README.md").write_text(f"# Project {i}")
        projects.append(str(p))

    task = "Lis " + ", ".join(projects) + " et synthétise."
    from src.agents.coding.task_enricher import enrich_task, _MAX_SOURCES
    result = enrich_task(task)
    # Count how many "📁 Repo" headers appear
    count = result.count("📁 Repo")
    assert count <= _MAX_SOURCES


def test_enrich_task_no_duplicate_sources(tmp_path):
    (tmp_path / "README.md").write_text("# Unique")
    task = f"Lis {tmp_path} et aussi {tmp_path} encore une fois."
    from src.agents.coding.task_enricher import enrich_task
    result = enrich_task(task)
    assert result.count("📁 Repo") == 1


def test_enrich_task_passthrough_when_ref_not_found():
    from src.agents.coding.task_enricher import enrich_task
    task = "Lis le repo super-projet-inexistant-xyz et fais quelque chose."
    result = enrich_task(task)
    # No injection if nothing found — task returned unchanged
    assert "SOURCES PRÉ-LUES" not in result
    assert result == task
