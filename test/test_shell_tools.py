"""Tests for src/agents/shell/tools.py — RTK wrapping, security guards, shell_ls."""
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path


def _popen_factice(sortie: str = "ok", code: int = 0):
    """Processus simulé. `shell_run` DIFFUSE la sortie : il itère sur
    `proc.stdout` puis appelle `wait()`. Un `MagicMock` nu rendrait un itérateur
    infini, et la boucle de lecture ne se terminerait jamais."""
    proc = MagicMock()
    proc.stdout = iter([sortie + "\n"] if sortie else [])
    proc.wait.return_value = code
    proc.pid = 4242
    return proc


# ── _wrap_rtk ─────────────────────────────────────────────────────────────────

def _wrap(cmd, rtk_path="/usr/bin/rtk"):
    import src.agents.shell.tools as mod
    with patch.object(mod, "_RTK", rtk_path):
        return mod._wrap_rtk(cmd)


def test_wrap_rtk_prefixes_normal_command():
    result = _wrap("git status")
    # _RTK is the full path (/usr/bin/rtk), so check the command is appended after it
    assert result.endswith("git status")
    assert "rtk" in result


def test_wrap_rtk_skips_background_command():
    """Background commands (ending with &) must NOT be wrapped — rtk would block."""
    result = _wrap("npm run dev > /tmp/dev.log 2>&1 &")
    assert result.startswith("npm"), "Background command should not be prefixed with rtk"
    assert "rtk" not in result


def test_wrap_rtk_skips_when_rtk_not_found():
    """When rtk is absent (_RTK is None), return the command unchanged."""
    import src.agents.shell.tools as mod
    with patch.object(mod, "_RTK", None):
        result = mod._wrap_rtk("ls -la")
    assert result == "ls -la"


def test_wrap_rtk_handles_trailing_whitespace():
    """Trailing spaces don't accidentally trigger the background check."""
    result = _wrap("cargo build  ")
    assert "rtk" in result
    assert "cargo build" in result


def test_wrap_rtk_background_command_with_spaces():
    result = _wrap("  sleep 10 &  ")
    # stripped ends with &
    assert "rtk" not in result


# ── _is_destructive ───────────────────────────────────────────────────────────

def test_is_destructive_rm():
    from src.agents.shell.tools import _is_destructive
    assert _is_destructive("rm -rf /tmp/foo") is True


def test_is_destructive_git_reset_hard():
    from src.agents.shell.tools import _is_destructive
    assert _is_destructive("git reset --hard HEAD~1") is True


def test_is_destructive_git_push_force():
    from src.agents.shell.tools import _is_destructive
    assert _is_destructive("git push --force") is True


def test_is_destructive_safe_command():
    from src.agents.shell.tools import _is_destructive
    assert _is_destructive("git status") is False
    assert _is_destructive("ls -la") is False
    assert _is_destructive("cargo build") is False


# ── _is_file_write ────────────────────────────────────────────────────────────

def test_is_file_write_sed_i():
    from src.agents.shell.tools import _is_file_write
    assert _is_file_write("sed -i 's/foo/bar/g' file.txt") is True


def test_is_file_write_cat_redirect():
    from src.agents.shell.tools import _is_file_write
    assert _is_file_write("cat > /tmp/out.txt") is True


def test_is_file_write_safe_command():
    from src.agents.shell.tools import _is_file_write
    assert _is_file_write("cat README.md") is False
    assert _is_file_write("echo hello") is False


# ── shell_run — security guards ───────────────────────────────────────────────

def test_shell_run_blocks_destructive_without_confirmed():
    from src.agents.shell.tools import shell_run
    result = shell_run.invoke({"command": "rm -rf /tmp/test_axon"})
    assert result["status"] == "requires_confirmation"


def test_shell_run_blocks_file_write():
    from src.agents.shell.tools import shell_run
    # "echo > /" matches _WRITE_PATTERNS (redirect to absolute path)
    result = shell_run.invoke({"command": "echo > /tmp/axon_test.txt"})
    assert result["status"] == "blocked"


def test_shell_run_ok_safe_command():
    from src.agents.shell.tools import shell_run
    result = shell_run.invoke({"command": "echo hello"})
    assert result["status"] == "ok"
    assert "hello" in result["stdout"]


def test_shell_run_returns_exit_code():
    from src.agents.shell.tools import shell_run
    result = shell_run.invoke({"command": "python3 -c 'import sys; sys.exit(42)'", "timeout": 5})
    assert result["exit_code"] == 42


def test_shell_run_timeout_respected():
    """Le délai doit COUPER, pas seulement être rapporté.

    La lecture ligne à ligne bloquait jusqu'à la fermeture du flux : le
    `wait(timeout=...)` qui suivait n'était atteint qu'une fois la commande
    finie. `sleep 10` avec `timeout=1` tournait dix secondes et rendait « ok ».
    On mesure donc la DURÉE, pas seulement le statut.
    """
    import time

    from src.agents.shell.tools import shell_run

    debut = time.monotonic()
    result = shell_run.invoke({"command": "sleep 10", "timeout": 1})
    ecoule = time.monotonic() - debut

    assert result["status"] == "timeout"
    assert ecoule < 5, f"le délai n'a pas coupé : {ecoule:.1f}s pour un timeout de 1s"


def test_shell_run_timeout_clamped_to_300():
    """Timeouts above 300 must be clamped, not passed as-is to subprocess."""
    from src.agents.shell.tools import shell_run

    # `shell_run` diffuse la sortie ligne à ligne : il utilise Popen, pas
    # `subprocess.run`. Patcher `run` ne mockait plus rien et le test lisait
    # `call_args` à None.
    with patch("src.agents.shell.tools.threading.Timer") as mock_timer:
        shell_run.invoke({"command": "echo hi", "timeout": 9999})
        delai = mock_timer.call_args[0][0]
        assert delai <= 300


def test_shell_run_rtk_prefix_applied():
    """When _RTK is set, shell_run must prefix the command with rtk."""
    import src.agents.shell.tools as mod
    from src.agents.shell.tools import shell_run
    with patch.object(mod, "_RTK", "/usr/bin/rtk"), \
         patch("src.agents.shell.tools.subprocess.Popen") as mock_popen:
        mock_popen.return_value = _popen_factice()
        shell_run.invoke({"command": "ls"})
        cmd = mock_popen.call_args[0][0]
        assert "rtk" in cmd and "ls" in cmd, f"Expected rtk prefix, got: {cmd!r}"


def test_shell_run_no_rtk_prefix_when_absent():
    """When _RTK is None, shell_run runs the raw command."""
    import src.agents.shell.tools as mod
    from src.agents.shell.tools import shell_run
    with patch.object(mod, "_RTK", None), \
         patch("src.agents.shell.tools.subprocess.Popen") as mock_popen:
        mock_popen.return_value = _popen_factice()
        shell_run.invoke({"command": "ls"})
        cmd = mock_popen.call_args[0][0]
        assert cmd == "ls", f"Expected raw command, got: {cmd!r}"


# ── shell_ls ──────────────────────────────────────────────────────────────────

def test_shell_ls_lists_directory(tmp_path):
    (tmp_path / "file.txt").write_text("hello")
    (tmp_path / "subdir").mkdir()
    from src.agents.shell.tools import shell_ls
    result = shell_ls.invoke({"path": str(tmp_path)})
    assert result["status"] == "ok"
    names = [e["name"] for e in result["entries"]]
    assert "file.txt" in names
    assert "subdir/" in names


def test_shell_ls_hides_dotfiles_by_default(tmp_path):
    (tmp_path / ".hidden").write_text("secret")
    (tmp_path / "visible.py").write_text("code")
    from src.agents.shell.tools import shell_ls
    result = shell_ls.invoke({"path": str(tmp_path)})
    names = [e["name"] for e in result["entries"]]
    assert ".hidden" not in names
    assert "visible.py" in names


def test_shell_ls_shows_dotfiles_when_all_files(tmp_path):
    (tmp_path / ".env").write_text("KEY=value")
    from src.agents.shell.tools import shell_ls
    result = shell_ls.invoke({"path": str(tmp_path), "all_files": True})
    names = [e["name"] for e in result["entries"]]
    assert ".env" in names


def test_shell_ls_error_on_missing_path():
    from src.agents.shell.tools import shell_ls
    result = shell_ls.invoke({"path": "/nonexistent/path/xyz"})
    assert result["status"] == "error"
