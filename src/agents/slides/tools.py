"""Slides tool — generates professional Reveal.js + PPTX presentations."""
from __future__ import annotations

import base64
import subprocess
import tempfile
from pathlib import Path
from typing import List, Dict, Any, Optional

from langchain_core.tools import tool
from pydantic import BaseModel, ConfigDict, Field


def _open_browser(path: Path) -> None:
    for cmd in (["xdg-open"], ["open"], ["wslview"]):
        try:
            subprocess.Popen(cmd + [str(path)],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        except FileNotFoundError:
            continue


#: Navigateurs système utilisables à défaut de celui que Playwright embarque.
#: Ordre : Chromium libre d'abord, Chrome ensuite, puis les emplacements macOS
#: et Windows.
_NAVIGATEURS = (
    "chromium", "chromium-browser", "google-chrome-stable", "google-chrome",
    "brave-browser", "msedge",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
)


def _navigateur_systeme() -> str | None:
    """Un navigateur déjà installé, s'il y en a un.

    `playwright install` télécharge ~150 Mo de Chromium ; une machine qui a déjà
    Chrome ou Chromium n'a aucune raison de le faire. Sans ce repli, l'export
    PDF échouait en SILENCE — la présentation se générait, le bouton PDF restait
    inerte, et rien ne disait pourquoi.
    """
    import shutil
    from pathlib import Path as _P
    for candidat in _NAVIGATEURS:
        if "/" in candidat or "\\" in candidat:
            if _P(candidat).exists():
                return candidat
        elif shutil.which(candidat):
            return shutil.which(candidat)
    return None


def _generate_pdf(html_path: Path) -> bytes | None:
    """Rend la présentation en PDF, avec le navigateur qu'on trouve."""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch()
            except Exception:
                systeme = _navigateur_systeme()
                if not systeme:
                    raise
                browser = p.chromium.launch(executable_path=systeme)
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


class Diapositive(BaseModel):
    """Une diapositive. Seul `type` est exigé ; le reste dépend du type.

    Les types sont hétérogènes — une diapo `stats` ne porte pas les mêmes champs
    qu'une diapo `table` — donc `extra="allow"` : ce modèle CONTRAINT la forme
    sans prétendre l'énumérer, et le détail de chaque type vit dans le docstring
    de l'outil.

    Sa raison d'être est aussi mécanique : `List[Dict[str, Any]]` produit un
    schéma `items: {}` que Gemini refuse. Un modèle nommé produit un `$ref`,
    qu'il accepte — mesuré.
    """
    model_config = ConfigDict(extra="allow")

    type: str = Field(description=
        "title · agenda · timeline · section · content · code · compare · "
        "punch · tree · flow · cycle · quadrant · split · split3 · stats · "
        "table · cases · quote · closing")
    title: str = Field(default="", description="Titre de la diapositive.")


class ArgsCreateSlides(BaseModel):
    title: str = Field(description="Titre de la présentation.")
    slides: List[Diapositive] = Field(
        description="Les diapositives, dans l'ordre. Voir le docstring pour les "
                    "champs propres à chaque type.")
    export_to: str = Field(default="", description="Chemin d'export optionnel.")
    theme: Optional[Dict[str, str]] = Field(
        default=None,
        description="Surcharge de thème : {\"accents\": [...], \"bg\": \"#...\"}. "
                    "À LAISSER VIDE dans le cas normal — la charte d'Axon "
                    "s'applique alors, et deux présentations se ressemblent.")


@tool("create_slides", args_schema=ArgsCreateSlides)
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

    VARIER LES TYPES — la règle qui décide si le deck est beau ou plat.
    Mesuré sur un deck réel de 18 diapositives : 8 étaient du type "content",
    c'est-à-dire la MÊME mise en page huit fois, et "split", "split3", "cases"
    et "timeline" n'apparaissaient pas une seule fois. Le résultat se lit comme
    un document, pas comme une présentation.
      - jamais plus de DEUX "content" de suite ;
      - un deck de 10 diapos ou plus doit employer au moins QUATRE types ;
      - une inter-partie ("section") ne porte qu'un numéro et un titre : n'en
        mettre qu'entre deux parties réelles, et préférer "punch" pour marquer
        une idée forte.

    MONTRER PLUTÔT QUE LISTER. Une hiérarchie, un enchaînement d'étapes, une
    boucle ou un positionnement ne se rendent PAS en puces : "tree", "flow",
    "cycle" et "quadrant" existent pour ça et se lisent d'un coup d'œil.

    POUR UN SUJET TECHNIQUE, montrer du CODE. Une présentation sur un langage
    sans un seul bloc de code n'apprend rien — utiliser "code" et "compare",
    pas des `backticks` noyés dans des puces.

    Args:
        title:     Titre principal de la présentation
        slides:    Liste de slides. Chaque slide est un dict avec :

                   ━━ SCHÉMAS ━━ Les types qui DESSINENT plutôt qu'aligner du
                   texte. Un enchaînement, une hiérarchie ou un positionnement
                   se comprennent d'un coup d'œil sous forme de schéma, et pas
                   du tout sous forme de puces.

                   TYPE "tree" (organigramme, arborescence — 3 niveaux max) :
                     title,
                     root: {label, sub?, children: [
                       {label, sub?, children: [{label}, ...]}, ...]}
                     Au-delà de 5 branches ou 3 niveaux les boîtes deviennent
                     illisibles : faire deux diapositives.

                   TYPE "flow" (étapes reliées par des flèches — un processus) :
                     title, steps: [{label, sub?}, ...],
                     orientation?: "h" (défaut) | "v"

                   TYPE "cycle" (boucle : les étapes reviennent au début) :
                     title, steps: [{label, sub?}, ...] (3 à 6),
                     center?: "la phrase au centre de la boucle"

                   TYPE "quadrant" (deux axes, positionner des options les unes
                   par rapport aux autres) :
                     title, x_label, y_label,
                     items: [{label, x: 0..1, y: 0..1}, ...]

                   TYPE "code" (un extrait en grand, coloré) :
                     title, code: "...", lang?: "typescript", caption?, note?

                   TYPE "compare" (deux panneaux face à face — idéal avant/après,
                   ou un langage contre un autre) :
                     title,
                     left:  {heading, code?, lang?, bullets?},
                     right: {heading, code?, lang?, bullets?},
                     verdict?: "la phrase qui conclut la comparaison"

                   TYPE "punch" (UNE affirmation, plein écran — pour marquer une
                   idée forte, bien plus utile qu'une inter-partie muette) :
                     text, eyebrow?, source?

                   - "type" (obligatoire) : "title" | "agenda" | "section" | "content" | "split" | "split3" | "stats" | "table" | "cases" | "quote" | "closing"

                   TYPE "title" (slide d'ouverture) :
                     title, subtitle?, author?, date?, image_query?

                   TYPE "agenda" (sommaire en cartes, fond clair) :
                     title, items: ["str", ...] ou [{"label": "...", "sub": "..."}]

                   TYPE "timeline" (sommaire horizontal EPF, fond clair — PRÉFÉRER à agenda) :
                     title, subtitle?,
                     steps: [
                       {num?: "01", label: "Introduction", sub?: "Contexte et enjeux", duration?: "20 min"},
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
                       {heading: "Option A", body?, bullets?: [...]},
                       {heading: "Option B", body?, bullets?: [...]},
                       {heading: "Option C", body?, bullets?: [...]},
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

    # `args_schema` valide l'entrée et rend des `Diapositive`, alors que les deux
    # renderers lisent des dicts. On repasse en dict ici plutôt que d'adapter les
    # renderers : ils sont aussi appelés directement par les tests et par
    # `render_html()`, qui n'ont aucune raison de connaître le modèle Pydantic.
    slides = [
        d if isinstance(d, dict) else d.model_dump(exclude_none=True)
        for d in (slides or [])
    ]

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
    monotonie = _diagnostiquer_monotonie(slides)
    if monotonie:
        lines += ["", monotonie]
    return "\n".join(lines)


def _diagnostiquer_monotonie(slides: List[Dict[str, Any]]) -> str:
    """Dit au modèle que son deck est plat, pendant qu'il peut encore le refaire.

    Une règle écrite dans le docstring est lue AVANT de composer ; celle-ci
    constate APRÈS, sur le résultat réel. C'est la seule qui puisse rattraper le
    deck mesuré à l'origine du chantier : 8 « content » sur 18, et quatre types
    jamais employés.

    Elle ne corrige rien d'elle-même — réécrire le deck à la place de l'auteur
    serait pire que le laisser plat.
    """
    from collections import Counter

    types = [str(d.get("type", "content")) for d in slides]
    if len(types) < 5:
        return ""

    remarques: list[str] = []
    compte = Counter(types)
    dominant, n = compte.most_common(1)[0]
    if n / len(types) > 0.45:
        remarques.append(
            f"{n} diapositives sur {len(types)} sont du type « {dominant} » — "
            f"la même mise en page répétée.")
    if len(compte) < 4 and len(types) >= 10:
        remarques.append(
            f"seulement {len(compte)} types employés sur les 15 disponibles.")

    suite, pire = 1, 1
    for a, b in zip(types, types[1:]):
        suite = suite + 1 if a == b == "content" else 1
        pire = max(pire, suite)
    if pire > 2:
        remarques.append(f"{pire} diapositives « content » consécutives.")

    if not remarques:
        return ""
    return ("⚠ Deck peu varié : " + " ".join(remarques)
            + " Un deck se lit mieux en alternant : « compare » et « code » pour "
              "les sujets techniques, « punch » pour une idée forte, « tree » "
              "pour une hiérarchie, « flow » pour un enchaînement, « cycle » "
              "pour une boucle, « quadrant » pour un positionnement, et "
              "« stats », « table » ou « timeline » selon la matière. "
              "Rappelle create_slides avec des types variés si tu peux faire mieux.")
