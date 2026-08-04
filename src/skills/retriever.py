"""SkillRetriever — charge les skills .md, indexe leurs descriptions, recherche sémantique."""
from __future__ import annotations
import re
from pathlib import Path
from typing import Optional

_SKILLS_DIR = Path(__file__).resolve().parents[2] / "skills"

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_KV_RE = re.compile(r"^(\w+)\s*:\s*(.+)$", re.MULTILINE)
_LIST_RE = re.compile(r"\[([^\]]*)\]")
_DEFAULT_SCOPE = "coding"

def _normalize_scope(raw) -> frozenset[str]:
    """`scope:`accepte un nom ou une liste: `orchestrator`, `[coding, orchestrator]`"""
    if raw is None:
        return frozenset({_DEFAULT_SCOPE})
    values = raw if isinstance(raw, list) else [raw]
    cleaned = {str(v).strip().lower() for v in values if str(v).strip()}
    return frozenset(cleaned) or frozenset({_DEFAULT_SCOPE})

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
    """Charge les .md depuis skills/, indexe leurs descriptions, offre une recherche sémantique.

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
                "anchors": [str(a) for a in meta.get("anchors", [])],
                "content": content.strip(),
                "path": str(f),
                "scope": _normalize_scope(meta.get("scope")),
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


    def _visible(self, scope: str|None) -> dict[str, dict]:
        """Skills visibles depuis un contexte. `None` ne filtre pas — les appels
        historiques gardent leur comportement."""
        self._load()
        if scope is None:
            return self._skills
        return {n: s for n, s in self._skills.items() if scope in s["scope"]}

    def get(self, query: str, k: int=1, scope: str|None=None) -> str:
        """Retourne le contenu du meilleur skill pour query.
           Priorité : exact name → aliases → semantic (Chroma) → fuzzy (contains)
        """
        visible = self._visible(scope)
        q = query.lower().strip()

        # Exact name
        if q in visible:
            return visible[q]["content"]

        # Aliases
        for skill in visible.values():
            if q in skill["aliases"]:
                return skill["content"]

        # Hors portée : le dire AVANT le sémantique, qui servirait sinon un autre
        # skill par ressemblance
        if scope is not None and (q in self._skills
                                  or any(q in s["aliases"] for s in self._skills.values())):
            return f"Skill '{query}' non disponible dans ce contexte. Disponibles : {', '.join(visible)}"

        # Semantic search
        self._build_index()
        if self._index is not None:
            try:
                results = self._index.similarity_search(query, k=k*4)
                names = [r.metadata["name"] for r in results if r.metadata.get("name") in visible]
                if names:
                    return "\n\n---\n\n".join(visible[n]["content"] for n in names[:k])
            except Exception:
                pass

        # Fuzzy on name
        for name, skill in visible.items():
            if q in name or name in q:
                return skill["content"]

        return f"Skill '{query}' non trouvé. Disponibles : {', '.join(visible)}"


    def list_names(self, scope: str|None = None) -> list[str]:
        self._load()
        return list(self._visible(scope))

    def describe(self, scope: str|None=None) -> list[tuple[str, str]]:
        return [(n, s["description"]) for n, s in self._visible(scope).items()]

    def anchors(self, scope: str|None=None) -> list[str]:
        """Phrases de retrieval déclarées par les skills, à défaut leur description
        — une description en mots-clés se retrouve mal."""
        out: list[str] = []
        for skill in self._visible(scope).values():
            out.extend(skill["anchors"] or [skill["description"]])
        return out

    def scopes_in_use(self) -> set[str]:
        """Portées déclarées — rend visible une faute de frappe qui masquerait un skill."""
        self._load()
        return {sc for s in self._skills.values() for sc in s["scope"]}



_retriever = SkillRetriever()


def get_skill(query: str, k: int = 1, scope: str | None = None) -> str:
    return _retriever.get(query, k=k, scope=scope)


def list_skills(scope: str | None = None) -> list[str]:
    return _retriever.list_names(scope)


def describe_skills(scope: str | None = None) -> list[tuple[str, str]]:
    return _retriever.describe(scope)


def skill_anchors(scope: str|None = None) -> list[str]:
    return _retriever.anchors(scope)



def scopes_in_use() -> set[str]:
    return _retriever.scopes_in_use()



def warmup() -> None:
    """Pré-construit l'index Chroma en arrière-plan — appeler au démarrage du specialist."""
    import threading
    threading.Thread(target=_retriever._build_index, daemon=True).start()
