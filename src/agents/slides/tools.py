"""Slides tool — generates professional Reveal.js + PPTX presentations."""
from __future__ import annotations

import base64
import subprocess
import tempfile
from pathlib import Path
from typing import List, Dict, Any, Optional

from langchain_core.tools import tool


def _open_browser(path: Path) -> None:
    for cmd in (["xdg-open"], ["open"], ["wslview"]):
        try:
            subprocess.Popen(cmd + [str(path)],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        except FileNotFoundError:
            continue


def _generate_pdf(html_path: Path) -> bytes | None:
    """Render the presentation with Playwright and return PDF bytes."""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1280, "height": 720})
            page.goto(
                f"file://{html_path.resolve()}?print-pdf",
                wait_until="networkidle",
                timeout=30_000,
            )
            page.wait_for_timeout(3000)
            pdf = page.pdf(
                width="1280px",
                height="720px",
                print_background=True,
                margin={"top": "0", "right": "0", "bottom": "0", "left": "0"},
            )
            browser.close()
            return pdf
    except Exception as e:
        print(f"[slides] PDF generation failed: {e}")
        return None


@tool("create_slides")
def create_slides(
    title: str,
    slides: List[Dict[str, Any]],
    export_to: str = "",
    theme: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Génère une présentation professionnelle (HTML Reveal.js + PPTX) et l'ouvre dans le navigateur.

    TOUJOURS utiliser cet outil (et uniquement celui-ci) quand l'utilisateur demande :
    - une présentation, un diaporama, des slides, un PowerPoint, un PPTX
    - un pitch deck, une présentation Gamma-style
    - synthétiser un sujet en slides
    - "fais-moi une présentation sur X"

    Ne JAMAIS déléguer une demande de présentation à run_coding_agent.

    WORKFLOW RECOMMANDÉ :
      1. Utilise web_research_report() pour faire des recherches approfondies sur le sujet
      2. Structure le contenu en slides cohérentes et riches
      3. Appelle create_slides() directement avec les données structurées

    Args:
        title:     Titre principal de la présentation
        slides:    Liste de slides. Chaque slide est un dict avec :
                   - "type" (obligatoire) : "title" | "agenda" | "section" | "content" | "split" | "split3" | "stats" | "table" | "cases" | "quote" | "closing"

                   TYPE "title" (slide d'ouverture) :
                     title, subtitle?, author?, date?, image_query?

                   TYPE "agenda" (sommaire en cartes, fond clair) :
                     title, items: ["str", ...] ou [{"label": "...", "sub": "..."}]

                   TYPE "timeline" (sommaire horizontal EPF, fond clair — PRÉFÉRER à agenda) :
                     title, subtitle?,
                     steps: [
                       {num?: "01", label: "Introduction", sub?: "Contexte et enjeux", duration?: "20 min", color?: "#4a90d9"},
                       ...
                     ]

                   TYPE "section" (inter-partie style EPF — fond sombre, grand numéro à gauche) :
                     title, num?: "01", eyebrow?: "PARTIE", subtitle?

                   TYPE "content" (texte + bullets) :
                     title, body?: "paragraphe", bullets?: ["point 1", ...], icon?: "emoji"

                   TYPE "split" (2 colonnes côte à côte, fond sombre) :
                     title,
                     left:  {heading?, body?, bullets?},
                     right: {heading?, body?, bullets?}

                   TYPE "split3" (3 colonnes avec header coloré, fond sombre — idéal pour comparaisons à 3 options) :
                     title, body? (sous-titre),
                     columns: [
                       {heading: "Option A", color?: "#4a90d9", body?, bullets?: [...]},
                       {heading: "Option B", color?: "#f5a623", body?, bullets?: [...]},
                       {heading: "Option C", color?: "#00c896", body?, bullets?: [...]},
                     ]

                   TYPE "stats" (chiffres clés, fond clair — cartes blanches colorées) :
                     title, source?: "Sources : ...",
                     stats: [{value: "85%", label: "Précision", icon?: "🎯", source?: "..."}, ...]

                   TYPE "table" (comparaison en tableau, fond sombre) :
                     title,
                     columns: [{label: "Monolithe"}, {label: "Microservices"}],
                     rows: [
                       {dim: "Démarrage", values: ["✅ Rapide", "❌ Setup complexe"]},
                       ...
                     ]

                   TYPE "cases" (grille 2×2 de cas d'usage, fond clair) :
                     title,
                     cases: [
                       {company: "Netflix", icon: "▶", arch: "Microservices",
                        body: "...", lesson: "→ Clé : ..."},
                       ...
                     ]

                   TYPE "quote" (citation plein écran) :
                     quote: "texte", author: "nom", role?: "titre"

                   TYPE "closing" (slide de fin) :
                     title, subtitle?, cta?: "Call to action", eyebrow?: "MERCI"

        export_to: Chemin optionnel pour sauvegarder (ex: "/home/user/projet/slides/").
                   Si vide → dossier temporaire.

    Returns:
        Chemins des fichiers générés (HTML + PPTX).
    """
    from .html_renderer import render_html
    from .pptx_renderer import render_pptx

    if not slides:
        return "Erreur : aucune slide fournie."

    # ── Resolve output paths ──────────────────────────────────────────────────
    if export_to:
        base = Path(export_to).expanduser()
        base.mkdir(parents=True, exist_ok=True)
        safe_name = title.lower().replace(" ", "_").replace("/", "-")[:40]
    else:
        tmp_dir = Path(tempfile.mkdtemp(prefix="axon_slides_"))
        safe_name = title.lower().replace(" ", "_").replace("/", "-")[:40]
        base = tmp_dir

    html_path = base / f"{safe_name}.html"
    pptx_path = base / f"{safe_name}.pptx"
    pdf_path  = base / f"{safe_name}.pdf"

    # ── Step 1 : Write initial HTML (needed for Playwright) ───────────────────
    html_path.write_text(render_html(title, slides, theme=theme), encoding="utf-8")

    # ── Step 2 : Generate PPTX ────────────────────────────────────────────────
    pptx_ok = render_pptx(title, slides, pptx_path)

    # ── Step 3 : Generate PDF via Playwright ──────────────────────────────────
    pdf_bytes = _generate_pdf(html_path)
    if pdf_bytes:
        pdf_path.write_bytes(pdf_bytes)

    # ── Step 4 : Build base64 download links ──────────────────────────────────
    pdf_mime  = "application/pdf"
    pptx_mime = "application/vnd.openxmlformats-officedocument.presentationml.presentation"

    if pdf_bytes:
        pdf_b64  = base64.b64encode(pdf_bytes).decode()
        pdf_link = f'href="data:{pdf_mime};base64,{pdf_b64}" download="{safe_name}.pdf"'
    else:
        # Fallback: open print dialog in a new tab
        pdf_link = "onclick=\"var u=location.href.split('?')[0]+'?print-pdf';window.open(u,'_blank')\""

    if pptx_ok:
        pptx_b64  = base64.b64encode(pptx_path.read_bytes()).decode()
        pptx_link = f'href="data:{pptx_mime};base64,{pptx_b64}" download="{safe_name}.pptx"'
    else:
        pptx_link = 'class="exp-btn disabled" onclick="return false"'

    # ── Step 5 : Write final HTML with download links ─────────────────────────
    html_path.write_text(
        render_html(title, slides, theme=theme, pdf_link=pdf_link, pptx_link=pptx_link),
        encoding="utf-8",
    )
    _open_browser(html_path)

    # ── Report ────────────────────────────────────────────────────────────────
    lines = [f"✅ Présentation générée — {len(slides)} slides\n"]
    lines.append(f"HTML : {html_path}")
    if pdf_bytes:
        lines.append(f"PDF  : {pdf_path} (bouton ⬇ PDF pour télécharger)")
    if pptx_ok:
        lines.append(f"PPTX : {pptx_path} (bouton ⬇ PPTX pour télécharger)")
    lines += ["", "Navigation : ← → · F (plein écran) · S (speaker notes)"]
    return "\n".join(lines)
