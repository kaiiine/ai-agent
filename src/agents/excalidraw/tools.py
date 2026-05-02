"""Excalidraw tool — génère et ouvre des diagrammes Excalidraw dans le navigateur."""
from __future__ import annotations

import json
import subprocess
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, List

from langchain_core.tools import tool

_DIAGRAMS_DIR = Path.home() / "Documents" / "axon-diagrams"

# URLs CDN des dépendances (versionnées et stables)
_REACT_URL      = "https://unpkg.com/react@18.3.1/umd/react.production.min.js"
_REACT_DOM_URL  = "https://unpkg.com/react-dom@18.3.1/umd/react-dom.production.min.js"
_EXCALIDRAW_URL = "https://unpkg.com/@excalidraw/excalidraw@0.17.6/dist/excalidraw.production.min.js"

_JS_CACHE_DIR = _DIAGRAMS_DIR / ".js-cache"


def _ensure_js_cache() -> tuple[Path, Path, Path]:
    """Download Excalidraw + React bundles once, cache locally. Returns (react, react-dom, excalidraw) paths."""
    _JS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    files = {
        "react.js":       _REACT_URL,
        "react-dom.js":   _REACT_DOM_URL,
        "excalidraw.js":  _EXCALIDRAW_URL,
    }
    paths = {}
    for name, url in files.items():
        dest = _JS_CACHE_DIR / name
        if not dest.exists():
            try:
                urllib.request.urlretrieve(url, dest)
            except Exception as e:
                raise RuntimeError(f"Impossible de télécharger {name}: {e}") from e
        paths[name] = dest
    return paths["react.js"], paths["react-dom.js"], paths["excalidraw.js"]


_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8" />
  <title>{title}</title>
  <style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{ background: #1a1a2e; }}
    #root {{ height: 100vh; width: 100vw; }}
  </style>
</head>
<body>
  <div id="root"></div>
  <script src="{react_src}"></script>
  <script src="{react_dom_src}"></script>
  <script src="{excalidraw_src}"></script>
  <script>
    const SCENE = {scene_json};

    const App = () => {{
      return React.createElement(ExcalidrawLib.Excalidraw, {{
        initialData: SCENE,
        UIOptions: {{
          canvasActions: {{
            export: {{ saveFileToDisk: true }},
          }},
        }},
        theme: "dark",
      }});
    }};

    const container = document.getElementById("root");
    const root = ReactDOM.createRoot(container);
    root.render(React.createElement(App));
  </script>
</body>
</html>
"""

# ── Element helpers ────────────────────────────────────────────────────────────

def _base(type_: str, x: int, y: int, w: int, h: int, **kw) -> dict:
    return {
        "id": f"{type_}_{x}_{y}_{int(time.time()*1000)}",
        "type": type_,
        "x": x, "y": y, "width": w, "height": h,
        "angle": 0,
        "strokeColor": kw.get("strokeColor", "#e2e8f0"),
        "backgroundColor": kw.get("backgroundColor", "transparent"),
        "fillStyle": kw.get("fillStyle", "solid"),
        "strokeWidth": kw.get("strokeWidth", 2),
        "strokeStyle": kw.get("strokeStyle", "solid"),
        "roughness": kw.get("roughness", 1),
        "opacity": kw.get("opacity", 100),
        "roundness": kw.get("roundness", None),
        "seed": int(time.time() * 1000) % 999999,
        "version": 1,
        "versionNonce": 0,
        "isDeleted": False,
        "groupIds": [],
        "boundElements": [],
        "updated": int(time.time() * 1000),
        "link": None,
        "locked": False,
        **{k: v for k, v in kw.items() if k not in (
            "strokeColor", "backgroundColor", "fillStyle",
            "strokeWidth", "strokeStyle", "roughness", "opacity", "roundness"
        )},
    }


def _text_el(text: str, x: int, y: int, font_size: int = 20, color: str = "#e2e8f0",
             align: str = "center") -> dict:
    el = _base("text", x, y, len(text) * font_size * 0.6, font_size + 8, strokeColor=color)
    el.update({
        "text": text,
        "fontSize": font_size,
        "fontFamily": 1,
        "textAlign": align,
        "verticalAlign": "middle",
        "baseline": font_size,
        "containerId": None,
        "originalText": text,
        "lineHeight": 1.25,
    })
    return el


# ── Main tool ──────────────────────────────────────────────────────────────────

@tool("excalidraw_create")
def excalidraw_create(
    title: str,
    elements: List[Dict[str, Any]],
    background_color: str = "#1e1e2e",
    open_browser: bool = True,
    export_svg_to: str = "",
) -> Dict[str, Any]:
    """
    Creates an Excalidraw diagram, saves it as an HTML file and opens it in the browser.

    Use this tool whenever the user asks for a schema, diagram, architecture drawing,
    flowchart, sequence diagram, mind map, or any visual representation.

    ELEMENT TYPES and required fields:
    ─────────────────────────────────
    Rectangle / Ellipse / Diamond:
      { "type": "rectangle"|"ellipse"|"diamond",
        "x": int, "y": int, "width": int, "height": int,
        "strokeColor": "#hex", "backgroundColor": "#hex"|"transparent",
        "fillStyle": "solid"|"hachure"|"cross-hatch"|"dots",
        "strokeWidth": 1|2|4, "roundness": {"type": 3} or null,
        "label": {"text": "..."} }   ← optional inline label

    Text:
      { "type": "text", "x": int, "y": int,
        "text": "...", "fontSize": 16|20|28|36,
        "fontFamily": 1, "textAlign": "left"|"center"|"right",
        "strokeColor": "#hex" }

    Arrow / Line:
      { "type": "arrow"|"line",
        "x": int, "y": int, "width": int, "height": int,
        "points": [[0,0],[width,height]],
        "startArrowhead": null|"arrow"|"dot",
        "endArrowhead": null|"arrow"|"dot",
        "strokeColor": "#hex" }

    DESIGN TIPS:
    • Grid: place elements on a 20px grid for clean alignment.
    • Flowchart: rectangles for steps, diamonds for decisions, arrows between them.
    • Architecture: nested rectangles for layers, arrows for data flow.
    • Use backgroundColor with fillStyle="solid" to highlight important boxes.
    • Dark palette: bg #1e1e2e, boxes #2d2d3f stroke #7c3aed fill, text #e2e8f0.
    • Light palette: bg #ffffff, boxes #eff6ff stroke #2563eb fill, text #1e293b.

    Args:
        title: diagram title (used as filename and page title)
        elements: list of Excalidraw element dicts (see types above)
        background_color: canvas background color (default: dark #1e1e2e)
        open_browser: whether to open the diagram in the browser immediately
        export_svg_to: absolute path where to copy the exported SVG
                       (e.g. "/home/kaine/.../my-site/public/diagrams/arch.svg").
                       Use this when embedding a diagram in a Next.js / web project.
    Returns:
        {
          "status": "ok",
          "html_path": str,
          "excalidraw_path": str,
          "svg_path": str | None,
          "embed_snippet": str,   ← ready-to-use <img> or Next.js <Image> tag
        }
    """
    _DIAGRAMS_DIR.mkdir(parents=True, exist_ok=True)
    react_js, react_dom_js, excalidraw_js = _ensure_js_cache()

    slug = title.lower().replace(" ", "-").replace("/", "-")[:40]
    ts = int(time.time())
    base = _DIAGRAMS_DIR / f"{slug}-{ts}"
    excalidraw_path = base.with_suffix(".excalidraw")
    html_path = base.with_suffix(".html")

    # Normalize elements: assign stable IDs + convert label shortcuts to bound text elements
    normalized: list[dict] = []
    for i, el in enumerate(elements):
        el = dict(el)
        if "id" not in el:
            el["id"] = f"el_{i}_{ts}"
        el.setdefault("seed", i * 1337 + ts % 99999)
        el.setdefault("version", 1)
        el.setdefault("versionNonce", 0)
        el.setdefault("isDeleted", False)
        el.setdefault("groupIds", [])
        el.setdefault("boundElements", [])
        el.setdefault("updated", ts * 1000)
        el.setdefault("link", None)
        el.setdefault("locked", False)
        el.setdefault("angle", 0)
        el.setdefault("opacity", 100)

        # Convert label shorthand → bound text element
        label_info = el.pop("label", None)
        label_text = None
        if isinstance(label_info, dict):
            label_text = label_info.get("text", "")
        elif isinstance(label_info, str):
            label_text = label_info

        # Auto-size box to fit label text before appending
        if label_text and el.get("type") in ("rectangle", "ellipse", "diamond"):
            font_size = 16
            # Virgil font: ~0.58 * fontSize px per char
            char_w = font_size * 0.58
            h_padding = 32  # horizontal padding inside box
            v_padding = 20  # vertical padding inside box
            min_w = int(len(label_text) * char_w + h_padding * 2)
            min_h = int(font_size + v_padding * 2)
            if el.get("width", 0) < min_w:
                el["width"] = min_w
            if el.get("height", 0) < min_h:
                el["height"] = min_h

        normalized.append(el)

        if label_text and el.get("type") in ("rectangle", "ellipse", "diamond"):
            txt_id = f"txt_{el['id']}"
            font_size = 16
            el_w = el.get("width", 160)
            el_h = el.get("height", 60)
            txt_w = el_w - 8
            txt_h = font_size + 8
            txt_x = el["x"] + (el_w - txt_w) / 2
            txt_y = el["y"] + (el_h - txt_h) / 2

            txt_el = {
                "id": txt_id,
                "type": "text",
                "x": txt_x,
                "y": txt_y,
                "width": txt_w,
                "height": txt_h,
                "angle": 0,
                "strokeColor": el.get("strokeColor", "#e2e8f0"),
                "backgroundColor": "transparent",
                "fillStyle": "solid",
                "strokeWidth": 1,
                "strokeStyle": "solid",
                "roughness": 0,
                "opacity": 100,
                "text": label_text,
                "fontSize": font_size,
                "fontFamily": 1,
                "textAlign": "center",
                "verticalAlign": "middle",
                "baseline": font_size,
                "containerId": el["id"],
                "originalText": label_text,
                "lineHeight": 1.25,
                "seed": i * 999 + ts % 12345,
                "version": 1,
                "versionNonce": 0,
                "isDeleted": False,
                "groupIds": [],
                "boundElements": [],
                "updated": ts * 1000,
                "link": None,
                "locked": False,
            }
            # Link text back to the container
            el["boundElements"].append({"id": txt_id, "type": "text"})
            normalized.append(txt_el)

    elements = normalized

    scene = {
        "type": "excalidraw",
        "version": 2,
        "source": "axon-agent",
        "elements": elements,
        "appState": {
            "viewBackgroundColor": background_color,
            "gridSize": 20,
            "gridColor": {"Bold": "#2a2a3e", "Regular": "#232333"},
        },
        "files": {},
    }

    # Save .excalidraw file
    excalidraw_path.write_text(json.dumps(scene, indent=2, ensure_ascii=False))

    # Save HTML viewer — use relative paths so the HTTP server can serve JS locally
    rel_react     = f".js-cache/{react_js.name}"
    rel_react_dom = f".js-cache/{react_dom_js.name}"
    rel_excalidraw = f".js-cache/{excalidraw_js.name}"
    html = _HTML_TEMPLATE.format(
        title=title,
        scene_json=json.dumps(scene, ensure_ascii=False),
        react_src=rel_react,
        react_dom_src=rel_react_dom,
        excalidraw_src=rel_excalidraw,
    )
    html_path.write_text(html, encoding="utf-8")

    if open_browser:
        try:
            subprocess.Popen(
                ["xdg-open", str(html_path)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            pass

    # ── SVG export via playwright ──────────────────────────────────────────────
    svg_path: str | None = None
    embed_snippet = ""

    if export_svg_to:
        svg_path = _export_svg(html_path, export_svg_to, scene)

    if svg_path:
        # Build embed snippet depending on file location
        p = Path(svg_path)
        # Detect Next.js project: public/ folder → /diagrams/name.svg
        try:
            public_idx = p.parts.index("public")
            web_path = "/" + "/".join(p.parts[public_idx + 1:])
            embed_snippet = (
                f'<Image src="{web_path}" alt="{title}" '
                f'width={{800}} height={{500}} className="w-full h-auto" />'
            )
        except ValueError:
            embed_snippet = f'<img src="{svg_path}" alt="{title}" />'

    return {
        "status": "ok",
        "title": title,
        "html_path": str(html_path),
        "excalidraw_path": str(excalidraw_path),
        "svg_path": svg_path,
        "embed_snippet": embed_snippet,
        "element_count": len(elements),
        "message": (
            f"Diagramme '{title}' créé ({len(elements)} éléments)"
            + (f" · SVG → {svg_path}" if svg_path else "")
        ),
    }


def _export_svg(html_path: Path, dest: str, scene: dict) -> str | None:
    """Serve the HTML via a local HTTP server (so CDN scripts load), call exportToSvg, save SVG."""
    import http.server
    import socket
    import threading
    from functools import partial

    dest_path = Path(dest)
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    # Find a free port
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]

    # Serve html_path.parent over HTTP so CDN <script> tags are not blocked
    handler = partial(http.server.SimpleHTTPRequestHandler, directory=str(html_path.parent))
    httpd = http.server.HTTPServer(("127.0.0.1", port), handler)
    srv_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    srv_thread.start()

    elements_json = json.dumps(scene.get("elements", []))
    bg = scene.get("appState", {}).get("viewBackgroundColor", "#1e1e2e")

    svg_script = f"""
async () => {{
    await new Promise(r => setTimeout(r, 3000));
    if (typeof ExcalidrawLib === 'undefined') return null;
    const svg = await ExcalidrawLib.exportToSvg({{
        elements: {elements_json},
        appState: {{ exportWithDarkMode: false, exportBackground: false, viewBackgroundColor: '{bg}' }},
        files: {{}},
    }});
    return new XMLSerializer().serializeToString(svg);
}}
"""

    try:
        from playwright.sync_api import sync_playwright

        _CHROMIUM_CANDIDATES = (
            "/usr/bin/chromium", "/usr/bin/chromium-browser",
            "/usr/bin/google-chrome", "/usr/bin/google-chrome-stable",
        )
        chromium = next((c for c in _CHROMIUM_CANDIDATES if Path(c).exists()), None)
        if not chromium:
            return None

        with sync_playwright() as p:
            browser = p.chromium.launch(
                executable_path=chromium,
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            page = browser.new_page(viewport={"width": 1600, "height": 900})
            page.goto(
                f"http://127.0.0.1:{port}/{html_path.name}",
                wait_until="networkidle",
                timeout=25_000,
            )
            page.wait_for_timeout(4000)
            svg_str = page.evaluate(svg_script)
            browser.close()

        if svg_str and svg_str.strip().startswith("<svg"):
            dest_path.write_text(svg_str, encoding="utf-8")
            return str(dest_path)
    except Exception:
        pass
    finally:
        httpd.shutdown()

    return None
