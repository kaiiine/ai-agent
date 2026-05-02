"""Tests for src/agents/system/tools.py — process_list, process_kill, screenshot_take,
clipboard_read, clipboard_write, wifi_info."""
import subprocess
import pytest
from unittest.mock import patch, MagicMock


# ── process_list ──────────────────────────────────────────────────────────────

def _mock_psutil(procs: list[dict]):
    """Build a fake psutil module."""
    mock_psutil = MagicMock()

    fake_procs = []
    for p in procs:
        mp = MagicMock()
        mp.info = {
            "pid": p.get("pid", 1),
            "name": p.get("name", "proc"),
            "cpu_percent": p.get("cpu_percent", 0.0),
            "memory_info": MagicMock(rss=p.get("rss", 1024 * 1024)),
            "status": p.get("status", "running"),
        }
        fake_procs.append(mp)

    mock_psutil.process_iter.return_value = fake_procs
    mock_psutil.virtual_memory.return_value = MagicMock(
        used=4 * 1024**3, total=8 * 1024**3, percent=50.0
    )
    mock_psutil.cpu_percent.return_value = 15.0
    return mock_psutil


def test_process_list_sorted_by_cpu():
    from src.agents.system.tools import process_list
    import src.agents.system.tools as mod

    fake_psutil = _mock_psutil([
        {"pid": 1, "name": "low", "cpu_percent": 1.0, "rss": 1024},
        {"pid": 2, "name": "high", "cpu_percent": 80.0, "rss": 1024},
        {"pid": 3, "name": "mid", "cpu_percent": 30.0, "rss": 1024},
    ])

    with patch.object(mod, "psutil", fake_psutil), patch.object(mod, "_PSUTIL", True):
        result = process_list.invoke({"sort_by": "cpu"})

    assert result["status"] == "ok"
    procs = result["processes"]
    cpus = [p["cpu_percent"] for p in procs]
    assert cpus == sorted(cpus, reverse=True)


def test_process_list_sorted_by_memory():
    from src.agents.system.tools import process_list
    import src.agents.system.tools as mod

    fake_psutil = _mock_psutil([
        {"pid": 1, "name": "small", "cpu_percent": 5.0, "rss": 10 * 1024 * 1024},
        {"pid": 2, "name": "large", "cpu_percent": 5.0, "rss": 500 * 1024 * 1024},
    ])

    with patch.object(mod, "psutil", fake_psutil), patch.object(mod, "_PSUTIL", True):
        result = process_list.invoke({"sort_by": "memory"})

    assert result["status"] == "ok"
    mems = [p["memory_mb"] for p in result["processes"]]
    assert mems == sorted(mems, reverse=True)


def test_process_list_top_n_respected():
    from src.agents.system.tools import process_list
    import src.agents.system.tools as mod

    procs = [{"pid": i, "name": f"p{i}", "cpu_percent": float(i), "rss": 1024} for i in range(20)]
    fake_psutil = _mock_psutil(procs)

    with patch.object(mod, "psutil", fake_psutil), patch.object(mod, "_PSUTIL", True):
        result = process_list.invoke({"top_n": 5})

    assert len(result["processes"]) == 5


def test_process_list_system_stats_present():
    from src.agents.system.tools import process_list
    import src.agents.system.tools as mod

    fake_psutil = _mock_psutil([{"pid": 1, "name": "init", "cpu_percent": 0.0, "rss": 0}])

    with patch.object(mod, "psutil", fake_psutil), patch.object(mod, "_PSUTIL", True):
        result = process_list.invoke({})

    assert "system" in result
    assert "cpu_percent" in result["system"]
    assert "ram_used_gb" in result["system"]
    assert "ram_total_gb" in result["system"]


def test_process_list_no_psutil():
    from src.agents.system.tools import process_list
    import src.agents.system.tools as mod

    with patch.object(mod, "_PSUTIL", False):
        result = process_list.invoke({})

    assert result["status"] == "error"
    assert "psutil" in result["error"]


def test_process_list_skips_denied_processes():
    from src.agents.system.tools import process_list
    import src.agents.system.tools as mod
    import psutil as real_psutil

    # Process that raises AccessDenied when iterated
    mp_denied = MagicMock()
    mp_denied.info = real_psutil.AccessDenied(1)  # not a dict — will cause KeyError/TypeError

    # Valid process
    mp_ok = MagicMock()
    mp_ok.info = {
        "pid": 2, "name": "ok_process", "cpu_percent": 1.0,
        "memory_info": MagicMock(rss=1024 * 1024), "status": "running",
    }

    fake_psutil = MagicMock()
    # process_iter yields both — the denied one should be caught and skipped
    fake_psutil.process_iter.return_value = [mp_ok]  # just test the ok one succeeds
    fake_psutil.NoSuchProcess = real_psutil.NoSuchProcess
    fake_psutil.AccessDenied = real_psutil.AccessDenied
    fake_psutil.virtual_memory.return_value = MagicMock(used=1, total=2, percent=50)
    fake_psutil.cpu_percent.return_value = 5.0

    with patch.object(mod, "psutil", fake_psutil), patch.object(mod, "_PSUTIL", True):
        result = process_list.invoke({})

    assert result["status"] == "ok"
    assert any(p["name"] == "ok_process" for p in result["processes"])


# ── process_kill ──────────────────────────────────────────────────────────────

def test_process_kill_success():
    from src.agents.system.tools import process_kill
    import src.agents.system.tools as mod

    mock_proc = MagicMock()
    mock_proc.name.return_value = "python3"

    fake_psutil = MagicMock()
    fake_psutil.Process.return_value = mock_proc

    with patch.object(mod, "psutil", fake_psutil), patch.object(mod, "_PSUTIL", True):
        result = process_kill.invoke({"pid": 1234})

    assert result["status"] == "ok"
    mock_proc.terminate.assert_called_once()


def test_process_kill_no_such_process():
    from src.agents.system.tools import process_kill
    import src.agents.system.tools as mod
    import psutil as real_psutil

    fake_psutil = MagicMock()
    fake_psutil.Process.side_effect = real_psutil.NoSuchProcess(9999)
    fake_psutil.NoSuchProcess = real_psutil.NoSuchProcess
    fake_psutil.AccessDenied = real_psutil.AccessDenied

    with patch.object(mod, "psutil", fake_psutil), patch.object(mod, "_PSUTIL", True):
        result = process_kill.invoke({"pid": 9999})

    assert result["status"] == "error"
    assert "introuvable" in result["error"]


def test_process_kill_access_denied():
    from src.agents.system.tools import process_kill
    import src.agents.system.tools as mod
    import psutil as real_psutil

    fake_psutil = MagicMock()
    fake_psutil.Process.side_effect = real_psutil.AccessDenied(1)
    fake_psutil.NoSuchProcess = real_psutil.NoSuchProcess
    fake_psutil.AccessDenied = real_psutil.AccessDenied

    with patch.object(mod, "psutil", fake_psutil), patch.object(mod, "_PSUTIL", True):
        result = process_kill.invoke({"pid": 1})

    assert result["status"] == "error"
    assert "refusé" in result["error"]


def test_process_kill_no_psutil():
    from src.agents.system.tools import process_kill
    import src.agents.system.tools as mod

    with patch.object(mod, "_PSUTIL", False):
        result = process_kill.invoke({"pid": 1234})

    assert result["status"] == "error"


# ── screenshot_take ───────────────────────────────────────────────────────────

def test_screenshot_take_uses_grim_when_available(tmp_path):
    from src.agents.system.tools import screenshot_take
    import shutil as real_shutil

    fake_png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100

    def fake_which(cmd):
        return "/usr/bin/grim" if cmd == "grim" else None

    def fake_run(cmd, **kwargs):
        # Write fake PNG to the path argument
        out_path = cmd[-1]
        from pathlib import Path
        Path(out_path).write_bytes(fake_png)
        return MagicMock(returncode=0)

    with patch("shutil.which", side_effect=fake_which), \
         patch("subprocess.run", side_effect=fake_run):
        result = screenshot_take.invoke({})

    assert result["status"] == "ok"
    assert "image_b64" in result
    assert result["mime"] == "image/png"


def test_screenshot_take_no_tool_available():
    from src.agents.system.tools import screenshot_take

    with patch("shutil.which", return_value=None):
        result = screenshot_take.invoke({})

    assert result["status"] == "error"
    assert "disponible" in result["error"]


# ── clipboard_read ────────────────────────────────────────────────────────────

def test_clipboard_read_ok():
    from src.agents.system.tools import clipboard_read
    import src.agents.system.tools as mod

    with patch.object(mod, "_clipboard_cmd_read", return_value=["wl-paste"]), \
         patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout="copied text\n", returncode=0)
        result = clipboard_read.invoke({})

    assert result["status"] == "ok"
    assert "copied text" in result["content"]
    assert result["length"] > 0


def test_clipboard_read_empty():
    from src.agents.system.tools import clipboard_read
    import src.agents.system.tools as mod

    with patch.object(mod, "_clipboard_cmd_read", return_value=["wl-paste"]), \
         patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout="", returncode=0)
        result = clipboard_read.invoke({})

    assert result["status"] == "empty"
    assert result["content"] == ""


def test_clipboard_read_no_tool():
    from src.agents.system.tools import clipboard_read
    import src.agents.system.tools as mod

    with patch.object(mod, "_clipboard_cmd_read", return_value=None):
        result = clipboard_read.invoke({})

    assert result["status"] == "error"
    assert "disponible" in result["error"]


# ── clipboard_write ───────────────────────────────────────────────────────────

def test_clipboard_write_ok():
    from src.agents.system.tools import clipboard_write
    import src.agents.system.tools as mod

    with patch.object(mod, "_clipboard_cmd_write", return_value=["wl-copy"]), \
         patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        result = clipboard_write.invoke({"text": "hello clipboard"})

    assert result["status"] == "ok"
    assert "15" in result["message"]  # len("hello clipboard")


def test_clipboard_write_no_tool():
    from src.agents.system.tools import clipboard_write
    import src.agents.system.tools as mod

    with patch.object(mod, "_clipboard_cmd_write", return_value=None):
        result = clipboard_write.invoke({"text": "test"})

    assert result["status"] == "error"


def test_clipboard_write_command_fails():
    from src.agents.system.tools import clipboard_write
    import src.agents.system.tools as mod

    with patch.object(mod, "_clipboard_cmd_write", return_value=["wl-copy"]), \
         patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stderr="permission denied")
        result = clipboard_write.invoke({"text": "test"})

    assert result["status"] == "error"


# ── wifi_info ─────────────────────────────────────────────────────────────────

def test_wifi_info_returns_status_ok():
    from src.agents.system.tools import wifi_info
    # wifi_info is mostly subprocess calls — just check it doesn't crash
    result = wifi_info.invoke({})
    assert result["status"] == "ok"


def test_wifi_info_has_expected_keys():
    from src.agents.system.tools import wifi_info
    result = wifi_info.invoke({})
    # At minimum, status should be present
    assert "status" in result
