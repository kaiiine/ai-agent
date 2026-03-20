from __future__ import annotations
import subprocess
import shutil
import base64
import tempfile
from pathlib import Path
from typing import Dict, Any, Optional

from langchain_core.tools import tool

try:
    import psutil
    _PSUTIL = True
except ImportError:
    _PSUTIL = False


# ─── CLIPBOARD ────────────────────────────────────────────────────────────────

def _clipboard_cmd_read() -> list[str] | None:
    if shutil.which("wl-paste"):
        return ["wl-paste"]
    if shutil.which("xclip"):
        return ["xclip", "-selection", "clipboard", "-o"]
    if shutil.which("xsel"):
        return ["xsel", "--clipboard", "--output"]
    return None

def _clipboard_cmd_write() -> list[str] | None:
    if shutil.which("wl-copy"):
        return ["wl-copy"]
    if shutil.which("xclip"):
        return ["xclip", "-selection", "clipboard", "-i"]
    if shutil.which("xsel"):
        return ["xsel", "--clipboard", "--input"]
    return None


@tool("clipboard_read")
def clipboard_read() -> Dict[str, Any]:
    """
    Lit le contenu textuel du presse-papiers (Wayland ou X11).
    Utile pour récupérer du code, une URL, ou du texte copié.
    """
    cmd = _clipboard_cmd_read()
    if not cmd:
        return {"status": "error", "error": "Aucun outil clipboard disponible (wl-paste, xclip, xsel)"}
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        content = res.stdout
        if not content:
            return {"status": "empty", "content": ""}
        return {"status": "ok", "content": content, "length": len(content)}
    except subprocess.TimeoutExpired:
        return {"status": "error", "error": "Timeout"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@tool("clipboard_write")
def clipboard_write(text: str) -> Dict[str, Any]:
    """
    Écrit du texte dans le presse-papiers (Wayland ou X11).
    Utile pour préparer du texte à coller ailleurs.

    Args:
        text: texte à mettre dans le presse-papiers
    """
    cmd = _clipboard_cmd_write()
    if not cmd:
        return {"status": "error", "error": "Aucun outil clipboard disponible (wl-copy, xclip, xsel)"}
    try:
        res = subprocess.run(cmd, input=text, text=True, capture_output=True, timeout=5)
        if res.returncode != 0:
            return {"status": "error", "error": res.stderr.strip()}
        return {"status": "ok", "message": f"{len(text)} caractères copiés dans le presse-papiers"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


# ─── SCREENSHOT ───────────────────────────────────────────────────────────────

@tool("screenshot_take")
def screenshot_take(region: Optional[str] = None) -> Dict[str, Any]:
    """
    Prend un screenshot de l'écran et l'analyse visuellement.
    Fonctionne sur Wayland (grim) et X11 (scrot, import).

    Args:
        region: optionnel, region à capturer au format "x,y,width,height" (Wayland uniquement)
    Returns:
        {"status": "ok", "path": "...", "image_b64": "...", "size_kb": N}
    """
    tmp = Path(tempfile.mktemp(suffix=".png"))

    # Wayland — grim
    if shutil.which("grim"):
        cmd = ["grim"]
        if region:
            cmd += ["-g", region]
        cmd.append(str(tmp))
        res = subprocess.run(cmd, capture_output=True, timeout=10)
        if res.returncode != 0:
            return {"status": "error", "error": res.stderr.decode().strip()}

    # X11 — scrot
    elif shutil.which("scrot"):
        res = subprocess.run(["scrot", str(tmp)], capture_output=True, timeout=10)
        if res.returncode != 0:
            return {"status": "error", "error": res.stderr.decode().strip()}

    # X11 — import (ImageMagick)
    elif shutil.which("import"):
        res = subprocess.run(["import", "-window", "root", str(tmp)], capture_output=True, timeout=10)
        if res.returncode != 0:
            return {"status": "error", "error": res.stderr.decode().strip()}

    else:
        return {"status": "error", "error": "Aucun outil screenshot disponible (grim, scrot, import)"}

    if not tmp.exists():
        return {"status": "error", "error": "Screenshot non créé"}

    size_kb = tmp.stat().st_size // 1024
    b64 = base64.b64encode(tmp.read_bytes()).decode()
    tmp.unlink(missing_ok=True)

    return {
        "status": "ok",
        "size_kb": size_kb,
        "image_b64": b64,
        "mime": "image/png",
        "note": "Image disponible pour analyse visuelle",
    }


# ─── PROCESS MONITOR ──────────────────────────────────────────────────────────

@tool("process_list")
def process_list(sort_by: str = "cpu", top_n: int = 15) -> Dict[str, Any]:
    """
    Liste les processus actifs triés par consommation CPU ou mémoire.

    Args:
        sort_by: "cpu" ou "memory" (défaut: "cpu")
        top_n: nombre de processus à retourner (défaut: 15)
    Returns:
        {"status": "ok", "processes": [{"pid", "name", "cpu_percent", "memory_mb", "status"}, ...]}
    """
    if not _PSUTIL:
        return {"status": "error", "error": "psutil non installé — `pip install psutil`"}

    procs = []
    for p in psutil.process_iter(["pid", "name", "cpu_percent", "memory_info", "status"]):
        try:
            info = p.info
            procs.append({
                "pid": info["pid"],
                "name": info["name"] or "?",
                "cpu_percent": info["cpu_percent"] or 0.0,
                "memory_mb": round((info["memory_info"].rss if info["memory_info"] else 0) / 1024 / 1024, 1),
                "status": info["status"],
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    key = "cpu_percent" if sort_by == "cpu" else "memory_mb"
    procs.sort(key=lambda x: x[key], reverse=True)

    total_ram = psutil.virtual_memory()
    return {
        "status": "ok",
        "processes": procs[:top_n],
        "system": {
            "cpu_percent": psutil.cpu_percent(interval=0.1),
            "ram_used_gb": round(total_ram.used / 1024**3, 2),
            "ram_total_gb": round(total_ram.total / 1024**3, 2),
            "ram_percent": total_ram.percent,
        },
    }


@tool("process_kill")
def process_kill(pid: int, name_hint: str = "") -> Dict[str, Any]:
    """
    Termine un processus par son PID. TOUJOURS demander confirmation avant d'appeler.

    Args:
        pid: PID du processus à terminer
        name_hint: nom du processus (pour confirmation visuelle)
    """
    if not _PSUTIL:
        return {"status": "error", "error": "psutil non installé"}
    try:
        p = psutil.Process(pid)
        actual_name = p.name()
        p.terminate()
        return {"status": "ok", "message": f"Processus {actual_name} (PID {pid}) terminé."}
    except psutil.NoSuchProcess:
        return {"status": "error", "error": f"PID {pid} introuvable"}
    except psutil.AccessDenied:
        return {"status": "error", "error": f"Accès refusé pour PID {pid} — essaie avec sudo"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


# ─── WIFI / RÉSEAU ────────────────────────────────────────────────────────────

@tool("wifi_info")
def wifi_info() -> Dict[str, Any]:
    """
    Affiche les informations réseau : SSID, IP locale, IP publique, signal Wi-Fi.
    """
    result: Dict[str, Any] = {"status": "ok"}

    # SSID
    for cmd in [["iwgetid", "-r"], ["nmcli", "-t", "-f", "active,ssid", "dev", "wifi"]]:
        if shutil.which(cmd[0]):
            try:
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
                ssid = r.stdout.strip().splitlines()[0] if r.stdout.strip() else ""
                if ssid and "yes:" in ssid:
                    ssid = ssid.split("yes:")[-1]
                if ssid:
                    result["ssid"] = ssid
                break
            except Exception:
                pass

    # IP locale
    try:
        r = subprocess.run(["ip", "route", "get", "1.1.1.1"], capture_output=True, text=True, timeout=5)
        for token in r.stdout.split():
            if token == "src":
                result["ip_local"] = r.stdout.split()[r.stdout.split().index("src") + 1]
                break
    except Exception:
        pass

    # Signal Wi-Fi
    if shutil.which("iwconfig"):
        try:
            r = subprocess.run(["iwconfig"], capture_output=True, text=True, timeout=5)
            for line in r.stdout.splitlines():
                if "Signal level" in line:
                    import re
                    m = re.search(r"Signal level=(-\d+)", line)
                    if m:
                        result["signal_dbm"] = int(m.group(1))
                    break
        except Exception:
            pass

    # Ping latence
    try:
        r = subprocess.run(["ping", "-c", "1", "-W", "2", "1.1.1.1"], capture_output=True, text=True, timeout=5)
        import re
        m = re.search(r"time=([\d.]+)", r.stdout)
        if m:
            result["ping_ms"] = float(m.group(1))
    except Exception:
        pass

    return result
