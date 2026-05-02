"""Study tools — save generated HTML revision sheets and exercises to disk."""
from __future__ import annotations

import re
import subprocess
from datetime import datetime
from pathlib import Path

from langchain_core.tools import tool


def _output_dir() -> Path:
    d = Path.home() / "Documents" / "axon_fiches"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _extract_html(raw: str) -> str:
    """Strip markdown fences if the LLM wrapped the HTML."""
    m = re.search(r"```html\s*(.*?)```", raw, re.DOTALL)
    return m.group(1).strip() if m else raw.strip()


def _open_browser(path: Path) -> None:
    try:
        subprocess.Popen(["xdg-open", str(path)])
    except Exception:
        pass


@tool("save_study_file")
def save_study_file(
    html: str = "",
    file_type: str = "fiche",
    filename: str = "",
    pdf_path: str = "",
) -> dict:
    """
    Generates and saves an HTML study file (revision sheet or interactive exercises) to disk,
    then opens it in the browser.

    Two modes:
    - Direct HTML: pass html="<complete html>" — use when the PDF content is small enough to fit in context.
    - From PDF path: pass pdf_path="/absolute/path/to/file.pdf" — use when the PDF is too large for
      the conversation context. The tool reads the PDF, generates the HTML internally, and saves it.

    Args:
        html:      complete HTML document (when generating inline)
        file_type: "fiche" for revision sheets, "exo" for interactive exercises
        filename:  optional base name without extension (e.g. "algo_tri")
        pdf_path:  absolute path to a PDF file (when the PDF is too large to inject in context)
    Returns:
        {"status": "ok", "path": str}
        {"status": "error", "error": str}
    """
    # ── Mode PDF path: generate HTML from file ────────────────────────────────
    if pdf_path and not html:
        p = Path(pdf_path)
        if not p.exists():
            return {"status": "error", "error": f"Fichier introuvable : {pdf_path}"}
        try:
            from src.ui.attachments import _extract_pdf
            content_text = _extract_pdf(p)
        except Exception as e:
            return {"status": "error", "error": f"Erreur lecture PDF : {e}"}

        try:
            from src.infra.settings import settings
            from src.llm.models import make_llm, make_llm_ollama_cloud, make_llm_groq, make_llm_gemini
            from langchain_core.messages import HumanMessage

            _factories = {
                "ollama": make_llm,
                "groq": make_llm_groq,
                "ollama_cloud": make_llm_ollama_cloud,
                "gemini": make_llm_gemini,
            }
            llm = _factories.get(settings.llm_backend, make_llm_ollama_cloud)()

            if file_type == "exo":
                from src.ui.streaming import _EXO_PROMPT
                prompt = _EXO_PROMPT.format(content=content_text, type_exo="Mélange de QCM (60%) et questions ouvertes (40%).")
            else:
                from src.ui.streaming import _FICHE_PROMPT
                prompt = _FICHE_PROMPT.format(content=content_text)

            response = llm.invoke([HumanMessage(content=prompt)])
            html = response.content if isinstance(response.content, str) else str(response.content)
        except Exception as e:
            return {"status": "error", "error": f"Erreur génération : {e}"}

    # ── Save HTML to disk ─────────────────────────────────────────────────────
    if not html or len(html) < 200:
        return {"status": "error", "error": "HTML vide ou trop court."}

    final_html = _extract_html(html)
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    base = filename.strip().replace(" ", "_") or (Path(pdf_path).stem if pdf_path else file_type)
    out = _output_dir() / f"{base}_{ts}.html"

    try:
        out.write_text(final_html, encoding="utf-8")
    except Exception as e:
        return {"status": "error", "error": str(e)}

    _open_browser(out)
    return {
        "status": "ok",
        "path": str(out),
        "message": f"Ouvert dans le navigateur : {out.name}",
    }
