"""Headless browser utilities — screenshot + visual audit via Playwright + system Chromium."""
from __future__ import annotations

import time
from pathlib import Path

_SCREENSHOT_DIR = Path("/tmp")

_CHROMIUM_CANDIDATES = (
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
)


def _find_chromium() -> str:
    for path in _CHROMIUM_CANDIDATES:
        if Path(path).exists():
            return path
    raise FileNotFoundError(
        f"Aucun navigateur Chromium trouvé. Chemins essayés : {list(_CHROMIUM_CANDIDATES)}"
    )


# JS injected into the page to detect layout / visual issues
_AUDIT_JS = """\
() => {
    const issues = [];
    const vw = window.innerWidth;
    const vh = window.innerHeight;

    document.querySelectorAll('body *').forEach(el => {
        const rect = el.getBoundingClientRect();
        const style = window.getComputedStyle(el);

        // Skip invisible / zero-size elements
        if (rect.width < 2 || rect.height < 2) return;
        if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return;

        const tag = el.tagName.toLowerCase();
        const cls = (el.className && typeof el.className === 'string')
            ? el.className.trim().split(/\\s+/)[0]
            : '';
        const label = cls ? `${tag}.${cls}` : tag;

        // 1. Text cropped horizontally (overflow: hidden + scrollWidth > clientWidth)
        if (el.scrollWidth > el.clientWidth + 3 &&
            (style.overflow === 'hidden' || style.overflowX === 'hidden') &&
            el.innerText && el.innerText.trim().length > 0) {
            issues.push({
                type: 'text_cropped',
                element: label,
                text: el.innerText.trim().slice(0, 80),
                detail: `scrollWidth ${el.scrollWidth}px > clientWidth ${el.clientWidth}px`,
            });
        }

        // 2. Element partially outside the right edge of the viewport
        if (rect.right > vw + 5 && rect.left < vw) {
            issues.push({
                type: 'outside_viewport_right',
                element: label,
                detail: `right edge at ${Math.round(rect.right)}px, viewport is ${vw}px`,
            });
        }

        // 3. Element partially outside the bottom edge of the viewport
        if (rect.bottom > vh + 5 && rect.top < vh && rect.top > 0) {
            issues.push({
                type: 'outside_viewport_bottom',
                element: label,
                detail: `bottom edge at ${Math.round(rect.bottom)}px, viewport height is ${vh}px`,
            });
        }
    });

    // 4. Main content centering check
    const containers = [
        document.querySelector('main'),
        document.querySelector('[class*="container"]'),
        document.querySelector('[class*="wrapper"]'),
        document.querySelector('#root > div'),
        document.querySelector('#__next > div'),
    ].filter(Boolean);

    containers.forEach(el => {
        const rect = el.getBoundingClientRect();
        const leftMargin = rect.left;
        const rightMargin = vw - rect.right;
        const diff = Math.abs(leftMargin - rightMargin);
        if (diff > 30 && rect.width > 200) {
            issues.push({
                type: 'not_centered',
                element: el.tagName.toLowerCase() + (el.className ? '.' + el.className.trim().split(/\\s+/)[0] : ''),
                detail: `marge gauche ${Math.round(leftMargin)}px vs droite ${Math.round(rightMargin)}px (écart ${Math.round(diff)}px)`,
            });
        }
    });

    // 5. Empty or near-empty sections
    document.querySelectorAll('section, article, [class*="section"], [class*="block"]').forEach(el => {
        const text = el.innerText ? el.innerText.trim() : '';
        const hasMedia = el.querySelectorAll('img, video, svg, canvas, iframe').length > 0;
        if (text.length < 5 && !hasMedia) {
            const cls = (el.className && typeof el.className === 'string')
                ? el.className.trim().split(/\\s+/)[0] : '';
            issues.push({
                type: 'empty_section',
                element: `${el.tagName.toLowerCase()}${cls ? '.' + cls : ''}`,
                detail: 'section vide (pas de texte ni de media)',
            });
        }
    });

    // 6. Broken images
    document.querySelectorAll('img').forEach(img => {
        if (!img.complete || img.naturalWidth === 0) {
            issues.push({
                type: 'broken_image',
                element: 'img',
                detail: `src: ${(img.src || '').slice(0, 100)}`,
            });
        }
    });

    const h1s = Array.from(document.querySelectorAll('h1')).map(h => h.innerText.trim().slice(0, 80));

    return {
        title: document.title || '',
        h1s,
        viewport: { width: vw, height: vh },
        issueCount: issues.length,
        issues,
    };
}
"""


def screenshot_url(
    url: str,
    width: int = 1280,
    height: int = 900,
    wait_ms: int = 2500,
) -> dict:
    """
    Takes a headless screenshot of `url` and runs a visual audit.

    Returns:
        {
          "status": "ok",
          "screenshot_path": str,
          "page_text": str,
          "audit": {
              "title": str,
              "h1s": list[str],
              "issueCount": int,
              "issues": [{"type", "element", "detail"}, ...]
          }
        }
        or {"status": "error", "error": str}
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return {"status": "error", "error": "playwright non installé — lance : pip install playwright"}

    try:
        chromium_path = _find_chromium()
    except FileNotFoundError as e:
        return {"status": "error", "error": str(e)}

    ts = int(time.time())
    out_path = _SCREENSHOT_DIR / f"axon_screenshot_{ts}.png"

    page_text = ""
    audit: dict = {"issues": [], "issueCount": 0}

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                executable_path=chromium_path,
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
            )
            try:
                page = browser.new_page(viewport={"width": width, "height": height})

                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=15_000)
                except Exception as e:
                    return {
                        "status": "error",
                        "error": (
                            f"Impossible de charger {url} : {e}\n"
                            "Vérifie que le serveur de dev est bien lancé (npm run dev, etc.)."
                        ),
                    }

                page.wait_for_timeout(wait_ms)
                page.screenshot(path=str(out_path), full_page=False)

                try:
                    audit = page.evaluate(_AUDIT_JS)
                except Exception as e:
                    audit = {"error": str(e), "issues": [], "issueCount": 0}

                try:
                    page_text = page.inner_text("body")
                    page_text = " ".join(page_text.split())
                    if len(page_text) > 6000:
                        page_text = page_text[:6000] + "…[tronqué]"
                except Exception:
                    page_text = ""

            finally:
                browser.close()

    except Exception as e:
        return {"status": "error", "error": str(e)}

    return {
        "status": "ok",
        "screenshot_path": str(out_path),
        "url": url,
        "page_text": page_text or "(texte non disponible)",
        "audit": audit,
    }
