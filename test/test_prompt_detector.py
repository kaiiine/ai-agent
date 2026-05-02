"""Tests for src/agents/coding/prompts/detector.py and build_system_prompt."""
import json
import pytest
from pathlib import Path
from unittest.mock import patch


# ── detect_stacks — manifest rules ────────────────────────────────────────────

def _detect(root: Path) -> list[str]:
    from src.agents.coding.prompts.detector import detect_stacks
    return detect_stacks(_roots_override=[root])


def test_detects_rust(tmp_path):
    (tmp_path / "Cargo.toml").write_text('[package]\nname = "app"')
    assert "rust" in _detect(tmp_path)


def test_detects_go(tmp_path):
    (tmp_path / "go.mod").write_text("module example.com/app\ngo 1.21")
    assert "go" in _detect(tmp_path)


def test_detects_python_pyproject(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[tool.poetry]\nname = 'app'")
    assert "python" in _detect(tmp_path)


def test_detects_python_requirements(tmp_path):
    (tmp_path / "requirements.txt").write_text("fastapi\nuvicorn")
    assert "python" in _detect(tmp_path)


def test_detects_java_pom(tmp_path):
    (tmp_path / "pom.xml").write_text("<project/>")
    assert "java" in _detect(tmp_path)


def test_detects_java_gradle(tmp_path):
    (tmp_path / "build.gradle").write_text("plugins { id 'java' }")
    assert "java" in _detect(tmp_path)


def test_detects_systems_cmake(tmp_path):
    (tmp_path / "CMakeLists.txt").write_text("cmake_minimum_required(VERSION 3.20)")
    assert "systems" in _detect(tmp_path)


# ── detect_stacks — package.json parsing ──────────────────────────────────────

def _pkg(tmp_path: Path, deps: dict) -> list[str]:
    (tmp_path / "package.json").write_text(json.dumps({"dependencies": deps}))
    return _detect(tmp_path)


def test_detects_frontend_react(tmp_path):
    stacks = _pkg(tmp_path, {"react": "^18", "react-dom": "^18"})
    assert "frontend" in stacks


def test_detects_frontend_next(tmp_path):
    stacks = _pkg(tmp_path, {"next": "^14"})
    assert "frontend" in stacks


def test_detects_frontend_angular(tmp_path):
    stacks = _pkg(tmp_path, {"@angular/core": "^17"})
    assert "frontend" in stacks


def test_detects_frontend_vue(tmp_path):
    stacks = _pkg(tmp_path, {"vue": "^3"})
    assert "frontend" in stacks


def test_detects_frontend_svelte(tmp_path):
    stacks = _pkg(tmp_path, {"svelte": "^4"})
    assert "frontend" in stacks


def test_detects_node_backend_express(tmp_path):
    stacks = _pkg(tmp_path, {"express": "^4"})
    assert "node_backend" in stacks


def test_detects_node_backend_nestjs(tmp_path):
    stacks = _pkg(tmp_path, {"@nestjs/core": "^10"})
    assert "node_backend" in stacks


def test_detects_both_frontend_and_backend(tmp_path):
    """Full-stack package.json → both stacks detected."""
    stacks = _pkg(tmp_path, {"react": "^18", "express": "^4"})
    assert "frontend" in stacks
    assert "node_backend" in stacks


def test_unknown_package_json_falls_back_to_node_backend(tmp_path):
    stacks = _pkg(tmp_path, {"lodash": "^4"})
    assert "node_backend" in stacks


# ── detect_stacks — multi-stack / cap ─────────────────────────────────────────

def test_max_4_stacks(tmp_path):
    (tmp_path / "Cargo.toml").write_text("")
    (tmp_path / "go.mod").write_text("")
    (tmp_path / "pyproject.toml").write_text("")
    (tmp_path / "pom.xml").write_text("")
    (tmp_path / "CMakeLists.txt").write_text("")
    stacks = _detect(tmp_path)
    assert len(stacks) <= 4


def test_no_duplicates_in_result(tmp_path):
    # Two Python manifests → python appears once
    (tmp_path / "pyproject.toml").write_text("")
    (tmp_path / "requirements.txt").write_text("")
    stacks = _detect(tmp_path)
    assert stacks.count("python") == 1


def test_empty_directory_returns_empty(tmp_path):
    stacks = _detect(tmp_path)
    assert stacks == []


def test_subdir_manifest_detected(tmp_path):
    """Manifests in direct subdirectory are scanned (with lower confidence)."""
    sub = tmp_path / "backend"
    sub.mkdir()
    (sub / "Cargo.toml").write_text("")
    stacks = _detect(tmp_path)
    assert "rust" in stacks


def test_skip_dirs_ignored(tmp_path):
    """node_modules and target directories must be skipped."""
    for skip_dir in ("node_modules", "target", "__pycache__"):
        d = tmp_path / skip_dir
        d.mkdir()
        (d / "Cargo.toml").write_text("")
    stacks = _detect(tmp_path)
    # stacks may be empty or not rust
    assert "rust" not in stacks


def test_higher_confidence_stack_first(tmp_path):
    """Cargo.toml (confidence 10) must rank above requirements.txt (confidence 6)."""
    (tmp_path / "Cargo.toml").write_text("")
    (tmp_path / "requirements.txt").write_text("")
    stacks = _detect(tmp_path)
    assert stacks[0] == "rust"


# ── build_system_prompt ────────────────────────────────────────────────────────

def test_build_prompt_contains_base(tmp_path):
    from src.agents.coding.prompts import build_system_prompt
    prompt = build_system_prompt([])
    assert "dev_plan_create" in prompt
    assert "propose_file_change" in prompt


def test_build_prompt_injects_stack_section(tmp_path):
    from src.agents.coding.prompts import build_system_prompt
    prompt = build_system_prompt(["rust"])
    assert "RUST" in prompt
    assert "cargo fmt" in prompt


def test_build_prompt_injects_multiple_stacks():
    from src.agents.coding.prompts import build_system_prompt
    prompt = build_system_prompt(["python", "frontend"])
    assert "PYTHON" in prompt
    assert "FRONTEND" in prompt


def test_build_prompt_unknown_stack_ignored():
    from src.agents.coding.prompts import build_system_prompt
    prompt = build_system_prompt(["unknown_xyz"])
    assert "dev_plan_create" in prompt  # base still present


def test_build_prompt_shorter_than_monolith():
    """Single-stack prompt must be shorter than the old all-stacks monolith."""
    from src.agents.coding.prompts import build_system_prompt
    single = build_system_prompt(["python"])
    all_stacks = build_system_prompt(["python", "rust", "go", "java"])
    assert len(single) < len(all_stacks)


def test_all_stack_ids_have_a_prompt():
    from src.agents.coding.prompts import _STACK_PROMPTS
    expected = {"frontend", "node_backend", "python", "rust", "go", "java", "systems"}
    assert expected == set(_STACK_PROMPTS.keys())
