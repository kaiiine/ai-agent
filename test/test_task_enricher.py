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


# ── Une tâche qui porte son inventaire ne se fait pas pré-lire ────────────────
#
# Mesuré sur une phase « Pages » réaliste, avant correction : 2 672 caractères de
# tâche devenaient 10 872, soit +8 200 (≈ 2 000 tokens) à CHAQUE phase de CHAQUE
# build. Le contenu injecté venait de `Footer.tsx`, `Header.tsx`, `page.tsx` —
# noms lus dans l'inventaire que la tâche vient d'énoncer — plus
# `tailwind.config.js` et `globals.css`, récoltés dans l'EXEMPLE de steps du bloc
# Instructions, où ils n'illustrent qu'une granularité de plan.

def _tache_de_phase(tmp_path):
    from src.agents.coding.build_runner import _build_phase_task
    from src.agents.coding.task_decomposer import Phase

    phases = [Phase(1, "Setup", "scaffold"), Phase(2, "Composants", "ui"),
              Phase(3, "Pages", "sections"), Phase(4, "Polish", "vérif")]
    for nom in ("Header.tsx", "Footer.tsx", "page.tsx"):
        (tmp_path / nom).write_text("export function X() {}")
    spec = "\n".join(f"## Module {i}\n" + "Contenu de spec. " * 30 for i in range(1, 9))
    return _build_phase_task(phases[2], spec, "un-projet", tmp_path, phases)


def test_une_tache_de_phase_n_est_pas_re_enrichie(tmp_path):
    from src.agents.coding.task_enricher import enrich_task

    tache = _tache_de_phase(tmp_path)
    assert enrich_task(tache) == tache


def test_l_enrichissement_ne_mange_pas_les_instructions_de_phase(tmp_path):
    """Le bloc Instructions vient APRÈS la spec dans une tâche de phase, et c'est
    lui qui porte « ÉCRIS TÔT » et l'appel obligatoire à axon_note — les deux
    correctifs de la boucle de build. Les perdre les annulerait en silence."""
    from src.agents.coding.task_enricher import enrich_task

    enrichie = enrich_task(_tache_de_phase(tmp_path))

    for marqueur in ("ÉCRIS TÔT", "axon_note", "SCOPE DE CETTE PHASE", "Instructions :"):
        assert marqueur in enrichie, f"perdu à l'enrichissement : {marqueur}"


def test_le_marqueur_d_inventaire_est_bien_celui_que_le_build_ecrit(tmp_path):
    """Le garde-fou repose sur une chaîne partagée entre deux modules. Sans ce
    test, la renommer dans build_runner rendrait l'autre muet — et le silence
    d'un garde-fou ne se voit pas."""
    from src.agents.coding.task_enricher import _INVENTAIRE_MARQUEUR

    assert _INVENTAIRE_MARQUEUR in _tache_de_phase(tmp_path)


def test_une_demande_utilisateur_reste_enrichie(tmp_path):
    """Non-régression du chemin pour lequel l'enrichissement existe : quand
    l'utilisateur cite une source, elle est bien pré-lue."""
    from src.agents.coding.task_enricher import enrich_task

    (tmp_path / "README.md").write_text("# Projet\n" + "Description. " * 50)
    enrichie = enrich_task(f"lis le fichier {tmp_path / 'README.md'} et résume-le")

    assert "SOURCES PRÉ-LUES" in enrichie
    assert "Description." in enrichie


# ── Un nom de fichier ambigu ne résout rien ───────────────────────────────────

def test_un_nom_de_fichier_homonyme_n_injecte_rien(tmp_path, monkeypatch):
    """`_cwd` vaut `$HOME` par défaut et le build ne le déplace jamais — il passe
    `cwd=` à ses sous-processus, pas à la session shell. La version précédente
    rendait le PREMIER match du parcours : une phase construisant un projet
    voyait injecter, sous « SOURCES PRÉ-LUES — contenu disponible directement »,
    le fichier homonyme d'un AUTRE projet du disque.

    Injecter le mauvais fichier est pire que n'en injecter aucun : l'agent ne
    peut pas savoir qu'il lit le mauvais, alors que rien du tout le laisse lire
    lui-même avec un chemin explicite.
    """
    import src.agents.shell.tools as shell_tools
    from src.agents.coding import task_enricher

    for projet in ("projet_a", "projet_b"):
        (tmp_path / projet).mkdir()
        (tmp_path / projet / "Footer.tsx").write_text(f"// {projet}")
    monkeypatch.setattr(shell_tools, "_cwd", tmp_path)
    monkeypatch.setattr(task_enricher, "_PROJECT_ROOTS", [])

    assert task_enricher._find_file_in_scope("Footer.tsx") is None


def test_un_nom_de_fichier_unique_resout_toujours(tmp_path, monkeypatch):
    """Le contrepoids : se taire sur l'ambiguïté ne doit pas rendre muet sur le
    cas certain."""
    import src.agents.shell.tools as shell_tools
    from src.agents.coding import task_enricher

    (tmp_path / "projet").mkdir()
    (tmp_path / "projet" / "Unique.tsx").write_text("// seul")
    monkeypatch.setattr(shell_tools, "_cwd", tmp_path)
    monkeypatch.setattr(task_enricher, "_PROJECT_ROOTS", [])

    trouve = task_enricher._find_file_in_scope("Unique.tsx")
    assert trouve is not None and trouve.name == "Unique.tsx"
