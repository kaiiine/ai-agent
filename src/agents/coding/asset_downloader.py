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


def _url_web(out: Path) -> str:
    """Le chemin servi par l'application, ou "" si le fichier est hors du projet.

    `out.relative_to(get_cwd())` levait une ValueID sur un `dest` absolu situé
    hors du cwd — APRÈS avoir écrit le fichier. L'agent recevait donc une
    exception au lieu d'un résultat, sur un téléchargement pourtant réussi.
    """
    try:
        return "/" + str(out.relative_to(get_cwd())).lstrip("/")
    except ValueError:
        return ""


def _sorties(dest_path: Path, query: str, count: int, exts_fichier: set[str]) -> list[Path]:
    """Un chemin de sortie par asset, tous DISTINCTS.

    Mesuré : `count=3` vers « img/hero.jpg » annonçait trois assets et n'écrivait
    qu'un fichier, chaque téléchargement écrasant le précédent. L'agent câblait
    trois `<img>` sur la même image.

    Un dest nommé avec `count > 1` numérote donc à partir de ce nom plutôt que de
    se contenter d'écraser — « hero.jpg » donne hero-1.jpg, hero-2.jpg, hero-3.jpg.
    C'est ce que l'appel voulait dire ; refuser aurait été défendable, mais perdre
    deux assets sur trois en silence ne l'est pas.
    """
    nomme = dest_path.suffix.lower() in exts_fichier
    if nomme and count == 1:
        return [dest_path]
    if nomme:
        tige, ext = dest_path.stem, dest_path.suffix
        return [dest_path.with_name(f"{tige}-{i + 1}{ext}") for i in range(count)]
    return []          # dossier : le nom est dérivé de la query, cf. appelants


#: Signatures acceptées par extension. Un fichier qui ne commence pas par la
#: sienne n'est pas du type qu'il prétend être.
_SIGNATURES: dict[str, tuple[bytes, ...]] = {
    ".jpg":  (b"\xff\xd8\xff",),
    ".jpeg": (b"\xff\xd8\xff",),
    ".png":  (b"\x89PNG\r\n\x1a\n",),
    ".webp": (b"RIFF",),
    ".glb":  (b"glTF",),
    ".gltf": (b"{",),
}


def _signature_valide(dest: Path) -> bool:
    """L'octet de tête dit-il le même type que l'extension ?

    `taille > 1024` ne validait rien. `_search_3d_ddg` cherche « site:poly.pizza
    … glb download » et rend des URL de PAGES, pas de fichiers ; la page HTML
    téléchargée pèse plus de 1024 octets, passait donc le contrôle, et était
    enregistrée en `.glb`. L'agent câblait ensuite `<model-viewer src="…glb">`
    sur du HTML — mesuré, avec `status: ok` et une licence affichée.
    """
    attendues = _SIGNATURES.get(dest.suffix.lower())
    if not attendues:
        return True
    try:
        tete = dest.read_bytes()[:12]
    except OSError:
        return False
    return any(tete.startswith(s) for s in attendues)


def _download_url(url: str, dest: Path, timeout: int = 15) -> bool:
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        r = requests.get(url, headers=_HEADERS, timeout=timeout, stream=True)
        if r.status_code != 200:
            return False
        with open(dest, "wb") as f:
            for chunk in r.iter_content(8192):
                f.write(chunk)
        if dest.stat().st_size <= 1024 or not _signature_valide(dest):
            dest.unlink(missing_ok=True)   # ne pas laisser un leurre sur le disque
            return False
        return True
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
    nommes = _sorties(dest_path, query, count, _PHOTO_EXTS)
    downloaded = []
    for item in candidates:
        if len(downloaded) >= count:
            break
        ext = Path(item["url"].split("?")[0]).suffix.lower() or ".jpg"
        if ext not in _PHOTO_EXTS:
            ext = ".jpg"
        if nommes:
            out = nommes[len(downloaded)]
        else:
            rang = query if count == 1 else f"{query}-{len(downloaded) + 1}"
            out = dest_path / _safe_filename(rang, ext)

        if _download_url(item["url"], out):
            downloaded.append({
                "path": str(out),
                "url": _url_web(out),
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


# `_search_3d_ddg` a été supprimé. Il cherchait « site:poly.pizza … glb
# download » et rendait les `href` des résultats, c'est-à-dire des URL de PAGES
# HTML — jamais de fichiers. Le contrôle de signature les rejette toutes : cette
# recherche ne pouvait donc plus produire un seul modèle, elle ne faisait que
# retarder le repli d'un aller-retour réseau.
#
# C'est elle qui rendait le défaut visible : sa page HTML pesait plus de 1024
# octets, passait donc l'unique contrôle de l'époque, et était enregistrée en
# `.glb` avec `status: ok` et une licence affichée.


# Repli quand la recherche ne rend rien. Ce sont des assets de DÉMONSTRATION de
# model-viewer et Three.js — utiles pour qu'une page ne reste pas vide, mais ils
# n'ont rien à voir avec Poly Pizza et leur licence n'est pas CC0.
#
# La licence était pourtant annoncée « CC0 (Poly Pizza) » pour tout modèle 3D,
# repli compris : mesuré, `Astronaut.glb` de Google repartait sous cette
# étiquette. Une licence fausse sur un asset qui part en production n'est pas une
# imprécision de log. Elle est donc portée PAR la source, jamais affirmée après.
_LICENCE_A_VERIFIER = "à vérifier — asset de démonstration, licence non garantie"

_FALLBACK_GLBS: list[dict] = [
    {"url": "https://modelviewer.dev/shared-assets/models/Astronaut.glb",       "title": "Astronaut",     "author": "Google model-viewer", "license": _LICENCE_A_VERIFIER},
    {"url": "https://modelviewer.dev/shared-assets/models/Horse.glb",           "title": "Horse",         "author": "Google model-viewer", "license": _LICENCE_A_VERIFIER},
    {"url": "https://modelviewer.dev/shared-assets/models/NeilArmstrong.glb",   "title": "NeilArmstrong", "author": "Google model-viewer", "license": _LICENCE_A_VERIFIER},
    {"url": "https://modelviewer.dev/shared-assets/models/RobotExpressive.glb", "title": "Robot",         "author": "Google model-viewer", "license": _LICENCE_A_VERIFIER},
    {"url": "https://threejs.org/examples/models/gltf/LittlestTokyo.glb",       "title": "LittlestTokyo", "author": "Three.js examples",   "license": _LICENCE_A_VERIFIER},
]


def _download_3d(query: str, dest_path: Path, count: int) -> list[dict]:
    candidates = _search_3d(query, count)
    if not candidates:
        candidates = _FALLBACK_GLBS[:count]

    nommes = _sorties(dest_path, query, count, _MODEL_EXTS)
    downloaded = []
    for item in candidates:
        if len(downloaded) >= count:
            break
        url = item["url"]
        ext = Path(url.split("?")[0]).suffix.lower()
        if ext not in _MODEL_EXTS:
            ext = ".glb"
        if nommes:
            out = nommes[len(downloaded)]
        else:
            rang = query if count == 1 else f"{query}-{len(downloaded) + 1}"
            out = dest_path / _safe_filename(rang, ext)

        if _download_url(url, out, timeout=30):
            downloaded.append({
                "path": str(out),
                "url": _url_web(out),
                "title": item.get("title", ""),
                "author": item.get("author", ""),
                # Portée par la source. `_search_3d` interroge bien l'API Poly
                # Pizza, dont le catalogue est CC0 ; le repli, non.
                "license": item.get("license", "CC0 (Poly Pizza)"),
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

    # Sans `url`, l'asset est hors du projet et aucune balise ne peut le servir :
    # mieux vaut le dire que proposer un `src` qui rendra 404.
    premier = assets[0]
    if premier["url"]:
        usage = (f"Dans ton composant React : <img src=\"{premier['url']}\" /> "
                 f"ou pour GLB : <model-viewer src=\"{premier['url']}\" />")
    else:
        usage = ("Ces fichiers sont HORS du projet servi : aucune URL web ne les "
                 "atteint. Déplace-les sous public/ ou relance avec un `dest` "
                 "relatif au projet avant de les référencer.")

    resultat = {
        "status": "ok",
        "count": len(assets),
        "assets": assets,
        "usage": usage,
    }
    if any(_LICENCE_A_VERIFIER in (a.get("license") or "") for a in assets):
        resultat["avertissement"] = (
            "La recherche n'a rien donné : ce sont des assets de DÉMONSTRATION, "
            "servis pour ne pas laisser la page vide. Leur licence n'est pas "
            "garantie — ne les laisse pas partir en production sans la vérifier."
        )
    return resultat
