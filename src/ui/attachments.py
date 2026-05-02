from __future__ import annotations

import base64
import io
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

MAX_TEXT_SIZE         = 100_000  # extraction brute complète
_ORCHESTRATOR_INJECT  =  20_000  # seuil au-delà duquel on n'injecte pas le contenu dans la conversation

_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
_MIME = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
         "gif": "image/gif", "webp": "image/webp"}


def _fix_spaced_chars(text: str) -> str:
    """Corrige l'artefact pypdf où les lettres sont séparées par des espaces.
    """
    import re
    lines = []
    for line in text.split('\n'):
        words = line.split(' ')
        single = sum(1 for w in words if len(w) <= 1)
        # Si >60% des "mots" sont des lettres seules → ligne espacée
        if len(words) > 4 and single / len(words) > 0.6:
            line = re.sub(r'(?<=[A-Za-zÀ-ÿ0-9]) (?=[A-Za-zÀ-ÿ0-9])', '', line)
        lines.append(line)
    return '\n'.join(lines)


def _extract_pdf(path: Path) -> str:
    try:
        from pypdf import PdfReader
        reader = PdfReader(str(path))
        pages = []
        for i, page in enumerate(reader.pages):
            text = page.extract_text() or ""
            text = _fix_spaced_chars(text)
            if text.strip():
                pages.append(f"[Page {i + 1}]\n{text}")
        return "\n\n".join(pages)[:MAX_TEXT_SIZE] or "[PDF sans texte extractible]"
    except Exception as e:
        return f"[Erreur lecture PDF: {e}]"


@dataclass
class Attachment:
    name: str
    is_image: bool
    content: str = ""        # fichiers texte (extrait complet)
    b64: str = ""            # images
    mime: str = ""
    size_hint: str = ""
    source_path: str = ""    # chemin absolu d'origine (pour re-lecture par les tools)


class AttachmentStore:
    def __init__(self):
        self._items: List[Attachment] = []

    def add_file(self, path_str: str) -> Optional[Attachment]:
        path = Path(path_str)
        if not path.exists():
            return None
        if path.suffix.lower() in _IMAGE_EXTS:
            return self._add_image(path)
        return self._add_text(path)

    def add_clipboard_image(self, img) -> Attachment:
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode()
        w, h = img.size
        a = Attachment(name="clipboard.png", is_image=True,
                       b64=b64, mime="image/png", size_hint=f"{w}×{h}")
        self._items.append(a)
        return a

    def _add_image(self, path: Path) -> Attachment:
        data = path.read_bytes()
        b64 = base64.b64encode(data).decode()
        mime = _MIME.get(path.suffix.lstrip(".").lower(), "image/png")
        size_hint = f"{len(data) // 1024}KB"
        try:
            from PIL import Image
            with Image.open(path) as img:
                size_hint = f"{img.width}×{img.height}"
        except Exception:
            pass
        a = Attachment(name=path.name, is_image=True, b64=b64,
                       mime=mime, size_hint=size_hint)
        self._items.append(a)
        return a

    def _add_text(self, path: Path) -> Attachment:
        size = path.stat().st_size
        size_hint = f"{size // 1024}KB" if size >= 1024 else f"{size}B"
        if path.suffix.lower() == ".pdf":
            content = _extract_pdf(path)
        else:
            try:
                content = path.read_text(encoding="utf-8", errors="replace")[:MAX_TEXT_SIZE]
            except Exception as e:
                content = f"[erreur: {e}]"
        a = Attachment(name=path.name, is_image=False,
                       content=content, size_hint=size_hint,
                       source_path=str(path.resolve()))
        self._items.append(a)
        return a

    def pop_all(self) -> List[Attachment]:
        items = list(self._items)
        self._items.clear()
        return items

    def remove(self, name: str) -> bool:
        before = len(self._items)
        self._items = [a for a in self._items if a.name != name]
        return len(self._items) < before

    @property
    def items(self) -> List[Attachment]:
        return list(self._items)

    def __len__(self):
        return len(self._items)

    def __bool__(self):
        return bool(self._items)


def get_clipboard_image():
    """Retourne une PIL Image depuis le presse-papiers (Wayland + X11)."""
    import subprocess, io

    # Wayland : wl-paste
    try:
        r = subprocess.run(["wl-paste", "--type", "image/png"],
                           capture_output=True, timeout=3)
        if r.returncode == 0 and r.stdout:
            from PIL import Image
            return Image.open(io.BytesIO(r.stdout))
    except (FileNotFoundError, subprocess.TimeoutExpired, Exception):
        pass

    # X11 : xclip
    try:
        r = subprocess.run(["xclip", "-selection", "clipboard", "-t", "image/png", "-o"],
                           capture_output=True, timeout=3)
        if r.returncode == 0 and r.stdout:
            from PIL import Image
            return Image.open(io.BytesIO(r.stdout))
    except (FileNotFoundError, subprocess.TimeoutExpired, Exception):
        pass

    # Fallback PIL (X11)
    try:
        from PIL import ImageGrab
        img = ImageGrab.grabclipboard()
        if img is not None:
            return img
    except Exception:
        pass

    return None


def open_file_picker() -> Optional[str]:
    """Ouvre un sélecteur de fichier natif. Retourne le chemin ou None."""
    import subprocess

    # zenity (GNOME / Wayland)
    try:
        r = subprocess.run(
            ["zenity", "--file-selection", "--title=Joindre un fichier"],
            capture_output=True, text=True, timeout=120,
        )
        if r.returncode == 0:
            return r.stdout.strip() or None
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # kdialog (KDE)
    try:
        r = subprocess.run(
            ["kdialog", "--getopenfilename", ".", "--title", "Joindre un fichier"],
            capture_output=True, text=True, timeout=120,
        )
        if r.returncode == 0:
            return r.stdout.strip() or None
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # tkinter fallback
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.wm_attributes("-topmost", 1)
        root.update()
        path = filedialog.askopenfilename(title="Joindre un fichier")
        root.destroy()
        return path or None
    except Exception:
        pass

    return None


def build_message_with_attachments(text: str, attachments: List[Attachment]) -> dict:
    """
    Construit le message LangChain avec les pièces jointes injectées.
    - Fichiers texte → injectés dans le contenu textuel
    - Images → message multimodal (content list)
    """
    if not attachments:
        return {"role": "user", "content": text}

    text_parts = [text]
    images = []

    for a in attachments:
        if a.is_image:
            images.append(a)
        else:
            lang = Path(a.name).suffix.lstrip(".")
            if len(a.content) > _ORCHESTRATOR_INJECT:
                # Fichier trop grand pour être injecté : donne le chemin au LLM
                text_parts.append(
                    f"\n\n---\n**Fichier joint : {a.name}** (trop grand pour injection directe)\n"
                    f"Chemin : `{a.source_path}`\n"
                    f"Taille : {a.size_hint} — utilise save_study_file(pdf_path=\"{a.source_path}\") "
                    f"pour générer une fiche ou des exercices, ou local_read_file pour lire par sections."
                )
            else:
                text_parts.append(
                    f"\n\n---\n**Fichier joint : {a.name}**\n```{lang}\n{a.content}\n```"
                )

    full_text = "".join(text_parts)

    if not images:
        return {"role": "user", "content": full_text}

    content: list = [{"type": "text", "text": full_text}]
    for img in images:
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:{img.mime};base64,{img.b64}"},
        })
    return {"role": "user", "content": content}
