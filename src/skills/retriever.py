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


def _document(name: str, skill: dict) -> str:
    """Ce qu'on indexe pour un skill : son nom, ses alias, sa description.

    Mesuré sur dix requêtes de référence en français, réponse attendue connue,
    avec le filtrage de portée en place :

        description seule                    4/10
        + nom + alias                       10/10
        + nom + alias + ancres               9/10

    Les descriptions sont des chapelets de mots-clés anglais et les questions
    arrivent en français : le nom et les alias rapprochent les deux.

    Les ANCRES, elles, dégradent — et c'est contre-intuitif, puisqu'elles sont
    justement écrites dans la langue de l'utilisateur. Le skill Blender en
    déclare huit ; les ajouter allonge son document d'autant de phrases
    françaises, et « un serveur en Go » se met à rendre Blender. Le volume de
    texte joue ici le rôle que le NOMBRE de documents jouait dans l'index
    d'outils (voir l'en-tête de `orchestrator/tool_retriever.py`) : dans les deux
    cas, en écrire davantage sur un skill augmente sa probabilité d'être choisi
    indépendamment de la pertinence.

    Les ancres gardent leur emploi ailleurs : `tool_retriever._skill_topics()`
    les lit pour router vers le GROUPE d'outils. Elles ne servent pas à
    départager les skills entre eux.

    Le champ `lexique:` n'entre PAS ici, et c'est tout son intérêt. Il porte les
    tournures qui déclenchent un skill — « échec silencieux », « base de
    données » — pour la porte lexicale, où le nombre ne nuit pas puisque la
    correspondance est exacte. Les mettre dans `aliases:` les faisait indexer :
    sept phrases françaises ont suffi à faire de `silent-failure-hunter` le
    document le plus proche de « refais le design de mon site ». Mesuré, puis
    séparé — `aliases:` désigne, `lexique:` déclenche.
    """
    morceaux = [name, " ".join(skill.get("aliases") or []),
                skill.get("description") or ""]
    return ". ".join(m for m in morceaux if m.strip())


#: Radicaux qui ne nomment PAS une technologie : ce qui reste après le suffixe
#: de rôle est un mot générique. Ajouter un langage n'y touche pas — c'est ce
#: qui rend l'ajout de skills sans effet sur les requêtes qui ne le nomment pas.
_RADICAUX_GENERIQUES = frozenset({
    "code", "build-error", "refactor", "silent-failure", "security", "tdd",
    "performance", "type-design", "a11y", "seo",
})


_TERME = re.compile(r"[\w+#]+", re.UNICODE)
#: Suffixes de RÔLE : ce qui reste une fois retiré est le DOMAINE du skill.
#: `react-reviewer` et `frontend` (alias `react`) parlent donc du même domaine.
_SUFFIXES_DE_ROLE = ("-reviewer", "-resolver", "-cleaner", "-simplifier",
                     "-hunter", "-guide", "-optimizer", "-architect",
                     "-specialist", "-analyzer")


def termes_identifiants(name: str, skill: dict) -> set[str]:
    """Les mots qui DÉSIGNENT ce skill : son nom, son domaine, ses alias.

    Sert à repérer qu'une requête vise un domaine revendiqué par plusieurs
    skills — `python` (alias `fastapi`) et `fastapi-reviewer` par exemple.
    """
    termes = ({name.lower()}
              | {a.lower() for a in skill.get("aliases") or []}
              | {t.lower() for t in skill.get("lexique") or []})
    for suffixe in _SUFFIXES_DE_ROLE:
        if name.endswith(suffixe):
            base = name[: -len(suffixe)].lower()
            termes.add(base)
            # Le PREMIER segment aussi : `java-build-resolver` se désigne par
            # « java », pas seulement par « java-build » — sans quoi « mon build
            # Maven échoue » ne le trouvait ni ne le citait. Un seul suffixe est
            # retiré par la boucle, et les noms ECC en portent deux.
            tete = base.split("-", 1)[0]
            if tete and tete not in _RADICAUX_GENERIQUES:
                termes.add(tete)
            break
    return {t for t in termes if t}


def _plie(texte: str) -> str:
    """Sans accents ni casse : « référencement » doit rencontrer « referencement »."""
    import unicodedata

    plie = unicodedata.normalize("NFD", texte.lower())
    return "".join(c for c in plie if unicodedata.category(c) != "Mn")


def _mots_de(requete: str) -> set[str]:
    """Les mots ENTIERS de la requête. Un fragment ferait élire `go` par « django »."""
    return set(re.findall(r"[a-z0-9.+#-]+", _plie(requete)))


def voisins_de_domaine(requete: str, visible: dict, choisi: str) -> list[str]:
    """Les autres skills que la requête désigne aussi, par un terme partagé.

    C'est le mécanisme qui rend l'ajout de skills ADDITIF. Mesuré : importer
    douze skills n'a cassé qu'une seule requête préexistante — « crée une API
    FastAPI », parce que `fastapi-reviewer` revendique un terme que `python`
    déclarait déjà comme alias. Le premier choix ne peut pas être réparé :
    quatre mécanismes de désambiguïsation ont été mesurés (filet lexical,
    lexique de verbes, centroïdes d'intention, comparaison à la première
    phrase), tous sous la baseline, parce que `nomic-embed-text` ne sépare pas
    « créer » de « relire » sur une phrase française.

    Alors on ne répare pas le premier choix, on le rend RÉCUPÉRABLE : le skill
    servi cite ses voisins, et le modèle rappelle `load_skill` s'il s'est trompé
    de rôle. Un nouveau skill ne peut donc plus voler une requête sans recours —
    au pire il ajoute une ligne de renvoi.
    """
    mots = {m.group(0).lower() for m in _TERME.finditer(requete or "")}
    partages = [n for n, s in visible.items()
                if n != choisi and termes_identifiants(n, s) & mots]
    if partages:
        return partages

    # Aucune technologie nommée : la requête décrit un RÔLE (« ce module est
    # illisible », « quelles fonctions ne sont plus appelées »). Les skills de
    # rôle sans domaine sont alors tous plausibles et se départagent mal — cinq
    # mécanismes de désambiguïsation ont été mesurés sans en battre aucun. On
    # les cite plutôt que de faire semblant d'avoir tranché.
    if choisi not in _roles_sans_domaine(visible):
        return []
    return [n for n in _roles_sans_domaine(visible) if n != choisi]


def _roles_sans_domaine(visible: dict) -> list[str]:
    """Les skills de rôle qui ne visent aucune technologie en particulier."""
    out = []
    for nom in visible:
        base = nom.lower()
        for suffixe in _SUFFIXES_DE_ROLE:
            if base.endswith(suffixe):
                base = base[: -len(suffixe)]
                break
        else:
            continue                      # pas un skill de rôle
        if base in _RADICAUX_GENERIQUES:
            out.append(nom)
    return out


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
                # Ce qui DÉCLENCHE, par opposition à ce qui DÉSIGNE. Lu par la
                # porte lexicale seule ; `_document` l'ignore délibérément.
                "lexique": [t.lower() for t in meta.get("lexique", [])],
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
                Document(page_content=_document(name, skill), metadata={"name": name})
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

    def _avec_renvoi(self, nom: str, visible: dict, requete: str) -> str:
        """Le contenu du skill, suivi de ses voisins de domaine s'il y en a.

        Quelques dizaines de tokens qui remplacent une erreur sans issue par un
        aiguillage. Rien n'est ajouté quand la requête ne désigne qu'un skill,
        c'est-à-dire dans l'immense majorité des cas.
        """
        voisins = voisins_de_domaine(requete, visible, nom)
        contenu = visible[nom]["content"]
        if not voisins:
            return contenu
        lignes = "\n".join(
            f"  - {v} : {visible[v]['description'].split('.')[0].strip()}."
            for v in voisins)
        return (f"{contenu}\n\n---\n"
                f"Ce domaine est couvert par d'autres skills. Si celui-ci ne "
                f"correspond pas à ce qui est demandé, rappelle `load_skill` "
                f"avec l'un d'eux :\n{lignes}")

    def get(self, query: str, k: int=1, scope: str|None=None) -> str:
        """Retourne le contenu du meilleur skill pour query.
           Priorité : exact name → aliases → semantic (Chroma) → fuzzy (contains)
        """
        visible = self._visible(scope)
        q = query.lower().strip()

        # Exact name — le skill est NOMMÉ, aucun doute à lever, pas de renvoi.
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
                # On demande de quoi survivre au filtrage de portée. L'index
                # contient TOUS les skills, y compris ceux qu'aucun agent ne lit
                # (`scope: template`, réservé aux commandes /fiche et /exo). Avec
                # `k*4`, ces intrus occupaient les premières places puis étaient
                # écartés, et le rebut restant gagnait : « un serveur en Go »
                # rendait le skill Blender. Filtrer après une recherche trop
                # courte, c'est choisir parmi ce qui a survécu, pas parmi ce qui
                # convient.
                combien = max(k * 4, len(self._skills))
                results = self._index.similarity_search(query, k=combien)
                names = [r.metadata["name"] for r in results if r.metadata.get("name") in visible]
                if names:
                    if k == 1:
                        return self._avec_renvoi(names[0], visible, query)
                    return "\n\n---\n\n".join(visible[n]["content"] for n in names[:k])
            except Exception:
                pass

        # Fuzzy on name
        for name, skill in visible.items():
            if q in name or name in q:
                return self._avec_renvoi(name, visible, query)

        return f"Skill '{query}' non trouvé. Disponibles : {', '.join(visible)}"


    def pertinentes(self, requete: str, scope: str | None = None,
                    budget: int = 5) -> list[str]:
        """Les skills que cette requête pourrait vouloir — les plus proches d'abord.

        Sert à RESTREINDRE le catalogue montré au modèle. Il en voyait 49 d'un
        coup, soit 2 241 tokens dans la description de `load_skill`, à chaque
        tour ; devant une liste pareille, il n'en choisissait aucune.

        Le classement est HYBRIDE, et l'ordre a été mesuré sur vingt requêtes dont
        on connaît la bonne réponse :

            dense seul                  rappel@1 55 %   rappel@3 65 %
            dense + pont linguistique   rappel@1 55 %   rappel@3 70 %
            lexical puis dense          rappel@1 75 %   rappel@3 80 %   @5 95 %

        Le pont linguistique n'apporte presque rien : la langue n'était pas la
        cause. `fiche` et `exo` disent « HTML/CSS » et « HTML/JS », ce qui les
        rapproche de toute requête web — la largeur d'un document achète de la
        proximité avec tout, comme pour les groupes d'outils.

        Ce qui débloque, ce sont les alias curés à la main : une requête qui NOMME
        un domaine (`next.js`, `accessible`, `référencement`) élit sa skill sans
        passer par l'embedding. « fais-moi un site vitrine en Next.js » rendait
        `fiche, exo, browser-driving` et met maintenant `nextjs` en tête.
        """
        visible = self._visible(scope)
        if not visible:
            return []

        nommees = [n for n in visible if _mots_de(requete) & termes_identifiants(n, visible[n])
                   or any(" " in t and t in _plie(requete)
                          for t in termes_identifiants(n, visible[n]))]

        self._build_index()
        denses: list[str] = []
        if self._index is not None:
            try:
                trouves = self._index.similarity_search(
                    requete, k=max(budget * 4, len(self._skills)))
                denses = [r.metadata["name"] for r in trouves
                          if r.metadata.get("name") in visible]
            except Exception:                                # noqa: BLE001
                denses = []

        classe = nommees + [n for n in denses if n not in nommees]
        return classe[:budget] or list(visible)[:budget]

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



def skills_pertinentes(requete: str, scope: str | None = None,
                       budget: int = 5) -> list[str]:
    """Les skills à montrer pour cette requête. Vide si rien n'est indexable."""
    try:
        return _retriever.pertinentes(requete, scope, budget)
    except Exception:                                        # noqa: BLE001
        return []


def scopes_in_use() -> set[str]:
    return _retriever.scopes_in_use()



def warmup() -> None:
    """Pré-construit l'index Chroma en arrière-plan — appeler au démarrage du specialist."""
    import threading
    threading.Thread(target=_retriever._build_index, daemon=True).start()
