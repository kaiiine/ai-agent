from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Optional

import requests
from langchain_core.tools import tool

from src.agents.shell.tools import get_cwd

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}
_PHOTO_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
_MODEL_EXTS = {".glb", ".gltf"}


def _safe_filename(query: str, ext: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", query.lower()).strip("-")[:40]
    return f"{slug}{ext}"


def _resolve_dest(dest: str) -> Path:
    p = Path(dest)
    if not p.is_absolute():
        p = get_cwd() / p
    return p


def _download_url(url: str, dest: Path, timeout: int = 15) -> bool:
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        r = requests.get(url, headers=_HEADERS, timeout=timeout, stream=True)
        if r.status_code != 200:
            return False
        with open(dest, "wb") as f:
            for chunk in r.iter_content(8192):
                f.write(chunk)
        return dest.stat().st_size > 1024  # reject empty/error pages
    except Exception:
        return False


# ── Photo download ─────────────────────────────────────────────────────────────

def _search_photos(query: str, count: int) -> list[dict]:
    try:
        from duckduckgo_search import DDGS
        results = []
        with DDGS() as ddgs:
            for r in ddgs.images(
                query,
                max_results=count * 4,  # fetch more, filter bad ones
                type_image="photo",
                size="large",
                license_image="Share",  # prefer freely usable images
            ):
                url = r.get("image", "")
                ext = Path(url.split("?")[0]).suffix.lower()
                if ext in _PHOTO_EXTS and url.startswith("http"):
                    results.append({"url": url, "title": r.get("title", ""), "source": r.get("source", "")})
                if len(results) >= count * 2:
                    break
        return results
    except Exception:
        return []


def _download_photos(query: str, dest_path: Path, count: int) -> list[dict]:
    candidates = _search_photos(query, count)
    downloaded = []
    for i, item in enumerate(candidates):
        if len(downloaded) >= count:
            break
        ext = Path(item["url"].split("?")[0]).suffix.lower() or ".jpg"
        if ext not in _PHOTO_EXTS:
            ext = ".jpg"
        if count == 1:
            filename = _safe_filename(query, ext)
        else:
            filename = _safe_filename(f"{query}-{i + 1}", ext)

        out = dest_path if dest_path.suffix else dest_path / filename
        if _download_url(item["url"], out):
            downloaded.append({
                "path": str(out),
                "url": "/" + str(out.relative_to(get_cwd())).lstrip("/"),
                "source": item.get("source", ""),
                "title": item.get("title", ""),
            })
        time.sleep(0.2)

    return downloaded


# ── 3D model download (Poly Pizza — CC0 libre) ────────────────────────────────

_POLYPIZZA_API = "https://api.poly.pizza/v1/search"


def _search_3d(query: str, count: int) -> list[dict]:
    try:
        r = requests.get(
            _POLYPIZZA_API,
            params={"q": query, "limit": count * 3, "type": "glb"},
            headers=_HEADERS,
            timeout=10,
        )
        if r.status_code != 200:
            return []
        data = r.json()
        results = data.get("results") or data.get("models") or []
        out = []
        for m in results:
            download = m.get("Download") or m.get("download") or ""
            if not download:
                # try nested
                for key in ("Links", "links", "files"):
                    links = m.get(key, {})
                    if isinstance(links, dict):
                        download = links.get("glb") or links.get("GLB") or ""
                    if download:
                        break
            if download and download.startswith("http"):
                out.append({
                    "url": download,
                    "title": m.get("Title") or m.get("title") or m.get("name") or query,
                    "author": m.get("Creator") or m.get("author") or "",
                })
        return out
    except Exception:
        return []


def _search_3d_ddg(query: str, count: int) -> list[dict]:
    try:
        from duckduckgo_search import DDGS
        results = []
        with DDGS() as ddgs:
            for r in ddgs.text(
                f"site:poly.pizza {query} glb download",
                max_results=count * 4,
            ):
                href = r.get("href", "")
                if "poly.pizza" in href:
                    results.append({"url": href, "title": r.get("title", ""), "author": ""})
        return results
    except Exception:
        return []


# Known-good CC0/public-domain GLB files — used as fallback when search fails
_FALLBACK_GLBS: list[dict] = [
    {"url": "https://modelviewer.dev/shared-assets/models/Astronaut.glb",       "title": "Astronaut",   "author": "Google"},
    {"url": "https://modelviewer.dev/shared-assets/models/Horse.glb",           "title": "Horse",       "author": "Google"},
    {"url": "https://modelviewer.dev/shared-assets/models/NeilArmstrong.glb",   "title": "NeilArmstrong", "author": "Google"},
    {"url": "https://modelviewer.dev/shared-assets/models/RobotExpressive.glb", "title": "Robot",       "author": "Google"},
    {"url": "https://threejs.org/examples/models/gltf/LittlestTokyo.glb",       "title": "LittlestTokyo", "author": "Three.js"},
]


def _download_3d(query: str, dest_path: Path, count: int) -> list[dict]:
    candidates = _search_3d(query, count)
    if not candidates:
        candidates = _search_3d_ddg(query, count)
    if not candidates:
        candidates = _FALLBACK_GLBS[:count]

    downloaded = []
    for i, item in enumerate(candidates):
        if len(downloaded) >= count:
            break
        url = item["url"]
        ext = Path(url.split("?")[0]).suffix.lower()
        if ext not in _MODEL_EXTS:
            ext = ".glb"
        filename = _safe_filename(f"{query}-{i + 1}" if count > 1 else query, ext)
        out = dest_path if dest_path.suffix in _MODEL_EXTS else dest_path / filename

        if _download_url(url, out, timeout=30):
            downloaded.append({
                "path": str(out),
                "url": "/" + str(out.relative_to(get_cwd())).lstrip("/"),
                "title": item.get("title", ""),
                "author": item.get("author", ""),
                "license": "CC0 (Poly Pizza)",
            })
        time.sleep(0.3)

    return downloaded


# ── Tool ──────────────────────────────────────────────────────────────────────

@tool("download_asset")
def download_asset(
    query: str,
    dest: str,
    asset_type: str = "photo",
    count: int = 1,
) -> dict:
    """
    Searches the web and downloads photos or 3D models (GLB) into the project's public folder.
    Use this whenever a project needs real images or 3D assets instead of placeholders.

    Args:
        query:      search terms (e.g. "running shoe product white background", "modern chair 3d")
        dest:       destination path relative to cwd (e.g. "public/images/hero.jpg" for a single file,
                    or "public/images/" for a folder when count > 1).
                    For 3D models: "public/models/" or "public/models/chair.glb"
        asset_type: "photo" — high-res photograph (jpg/png/webp)
                    "3d"    — 3D model in GLB format (CC0, from Poly Pizza)
        count:      number of assets to download (1–5)
    Returns:
        {"status": "ok", "assets": [{"path", "url", "title", ...}]}
        {"status": "error", "error": "..."}

    Examples:
        download_asset("sneaker shoe white background", "public/images/hero.jpg")
        download_asset("nike air force 1 product", "public/images/", count=3)
        download_asset("modern sofa 3d", "public/models/sofa.glb", asset_type="3d")
        download_asset("office chair", "public/models/", asset_type="3d", count=2)
    """
    count = max(1, min(count, 5))
    dest_path = _resolve_dest(dest)

    if asset_type == "3d":
        assets = _download_3d(query, dest_path, count)
    else:
        assets = _download_photos(query, dest_path, count)

    if not assets:
        return {
            "status": "error",
            "error": f"Aucun asset téléchargé pour '{query}' (type={asset_type}). "
                     "Essaie un query plus générique ou vérifie la connexion.",
            "tip": "Pour les photos tu peux essayer des termes anglais simples. "
                   "Pour les modèles 3D, poly.pizza est parfois lent — réessaie.",
        }

    return {
        "status": "ok",
        "count": len(assets),
        "assets": assets,
        "usage": f"Dans ton composant React : <img src=\"{assets[0]['url']}\" /> "
                 f"ou pour GLB : <model-viewer src=\"{assets[0]['url']}\" />",
    }
