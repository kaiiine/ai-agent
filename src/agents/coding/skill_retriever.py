"""SkillRetriever — charge les skills .md, indexe leurs descriptions, recherche sémantique."""
from __future__ import annotations
import re
from pathlib import Path
from typing import Optional

_SKILLS_DIR = Path(__file__).parent.parent.parent / "skills"

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_KV_RE = re.compile(r"^(\w+)\s*:\s*(.+)$", re.MULTILINE)
_LIST_RE = re.compile(r"\[([^\]]*)\]")


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    raw = m.group(1)
    meta: dict = {}
    for key, val in _KV_RE.findall(raw):
        val = val.strip()
        lm = _LIST_RE.match(val)
        if lm:
            meta[key] = [v.strip().strip("\"'") for v in lm.group(1).split(",") if v.strip()]
        else:
            meta[key] = val.strip("\"'")
    content = text[m.end():]
    return meta, content


class SkillRetriever:
    """Charge les .md depuis src/skills/, indexe leurs descriptions, offre une recherche sémantique.

    Réutilise la même infrastructure que CodingToolRetriever (Chroma + nomic-embed-text).
    Fallback : matching exact sur name/aliases si Ollama non disponible.
    """

    def __init__(self, skills_dir: Path = _SKILLS_DIR):
        self._dir = skills_dir
        self._skills: dict[str, dict] = {}   # name → {content, description, aliases, path}
        self._index = None          # Chroma vectorstore
        self._ready = False

    def _load(self) -> None:
        if self._ready:
            return
        for f in sorted(self._dir.glob("*.md")):
            if f.stat().st_size == 0:
                continue
            text = f.read_text(encoding="utf-8")
            meta, content = _parse_frontmatter(text)
            name = meta.get("name") or f.stem
            self._skills[name] = {
                "name": name,
                "description": meta.get("description", name),
                "aliases": [a.lower() for a in meta.get("aliases", [])],
                "content": content.strip(),
                "path": str(f),
            }
        self._ready = True

    def _build_index(self) -> None:
        if self._index is not None:
            return
        self._load()
        if not self._skills:
            return
        try:
            from langchain_ollama import OllamaEmbeddings
            from langchain_chroma import Chroma
            from langchain_core.documents import Document
            embedder = OllamaEmbeddings(model="nomic-embed-text")
            docs = [
                Document(
                    page_content=skill["description"],
                    metadata={"name": name}
                )
                for name, skill in self._skills.items()
            ]
            self._index = Chroma.from_documents(docs, embedder)
        except Exception:
            self._index = None

    def get(self, query: str, k: int = 1) -> str:
        """Retourne le contenu du meilleur skill pour query.

        Priorité : exact name → aliases → semantic (Chroma) → fuzzy (contains)
        """
        self._load()
        q = query.lower().strip()

        # 1. Exact name
        if q in self._skills:
            return self._skills[q]["content"]

        # 2. Aliases
        for skill in self._skills.values():
            if q in skill["aliases"]:
                return skill["content"]

        # 3. Semantic search
        self._build_index()
        if self._index is not None:
            try:
                results = self._index.similarity_search(query, k=k)
                names = [r.metadata["name"] for r in results if r.metadata.get("name") in self._skills]
                if names:
                    return "\n\n---\n\n".join(self._skills[n]["content"] for n in names)
            except Exception:
                pass

        # 4. Fuzzy on name (contains)
        for name, skill in self._skills.items():
            if q in name or name in q:
                return skill["content"]

        return f"Skill '{query}' non trouvé. Disponibles : {', '.join(self._skills)}"

    def list_names(self) -> list[str]:
        self._load()
        return list(self._skills)


_retriever = SkillRetriever()


def get_skill(query: str, k: int = 1) -> str:
    return _retriever.get(query, k=k)


def list_skills() -> list[str]:
    return _retriever.list_names()


def warmup() -> None:
    """Pré-construit l'index Chroma en arrière-plan — appeler au démarrage du specialist."""
    import threading
    threading.Thread(target=_retriever._build_index, daemon=True).start()
