"""Wizard de spécification interactive guidée par l'IA."""
from __future__ import annotations
import json
import re
from typing import Optional

from prompt_toolkit.shortcuts import prompt as pt_prompt
from rich.text import Text
from rich.rule import Rule

from src.ui.picker import pick
from src.utils.paths import get_projects_dir


_ACCENT = "color(214)"

_QUESTION_DOMAINS = [
    "concept & positionnement — concept précis, cible, différenciation unique",
    "direction artistique — ambiance exacte (3 adjectifs), 2-3 références visuelles (sites/artistes/films), niveau luxe/minimal/expérimental, couleurs, typo, motion, traitement image",
    "stack technique — choisir une stack complète définitive ; backend, base de données et CMS seulement si nécessaires — zéro alternative, décision ferme",
    "UX & interactions clés — parcours galerie (masonry ? lightbox ? fiche œuvre ? navigation clavier ?), microinteractions, ce qui doit être fluide",
    "contenu & données — arborescence complète, modèle de données (entités + champs importants), ce qui est hors-scope pour la v1",
]

_QUESTION_SYSTEM = """\
Tu es un expert en direction produit et spécification de projets créatifs et techniques.
Tu reçois un projet et UN domaine précis à approfondir. Tu génères UNE question ciblée sur ce domaine.

Réponds UNIQUEMENT avec un objet JSON (pas de markdown, pas d'explication) :
{
  "project_name": "nom-kebab-case",
  "question": "Question précise et directe ?",
  "options": ["Option concrète A", "Option concrète B", "Option concrète C"],
  "skip": false
}

Règles :
- Options concrètes et différenciées — "Glassmorphism sombre + serif" pas "style moderne"
- Pour le domaine stack : option = stack complète ("Next.js + Prisma + PostgreSQL", pas "React ou Vue")
- Si prompt initial ou réponses précédentes couvrent déjà ce domaine → {"skip": true, "project_name": "...", "question": "", "options": []}
- 3 à 4 options qui tranchent vraiment
- project_name : kebab-case, sans espaces\
"""

_SPEC_SYSTEM = """\
Tu es un expert en direction produit, UX et architecture technique.
Génère une spécification COMPLÈTE, OPINIONÉE et ACTIONNABLE en Markdown.
Zéro "ou bien / selon les besoins / à définir". Chaque décision est tranchée.

Structure OBLIGATOIRE — respecte exactement ces sections :

# [Nom du projet]

## Vision
- Concept en une phrase percutante
- Cible précise (persona en 1 ligne)
- Différenciation unique / pourquoi ça n'existe pas déjà

## Direction Artistique
### Ambiance & Références
- Ambiance : 3 adjectifs précis
- Références visuelles (sites, artistes, films — 2-3 exemples concrets)
- Niveau : luxe / minimal / expérimental / artisanal / ...

### Système Visuel
- Palette : couleurs primaires + accents (codes hex)
- Typographies : heading + body (noms de polices)
- Layout : densité, marges, grille
- Iconographie : style précis (outline, filled, custom SVG, aucune)
- Textures / backgrounds : grain, dégradé, plat, image de fond

### Style à éviter
- Ce que le design ne doit surtout pas évoquer
- Patterns visuels interdits
- Niveau de sobriété / extravagance à ne pas dépasser

### Motion & Interactivité
- Philosophie motion (subtil / spectaculaire / fonctionnel)
- Transitions de page
- Micro-interactions clés (hover, focus, chargement)

### Traitement Image
- Ratio / cadrage attendu
- Effets / filtres éventuels
- Format & qualité des assets

## Architecture & Arborescence
[liste des pages avec sous-pages, format arbre indenté]

## Stack Technique (décision ferme)
- Frontend : [framework définitif — pourquoi en 1 phrase]
- Backend : [choix définitif, ou "aucun — site statique" si non nécessaire]
- Base de données : [choix définitif, ou "aucune — contenu Markdown/local" si applicable]
- CMS / Admin : [choix définitif ou "aucun — fichiers Markdown"]
- Hébergement : [choix définitif]
- Outils annexes : [auth, emails, stockage, analytics]

## Pages Clés
### [Nom de la page]
- Sections dans l'ordre
- Composants principaux
- Comportement spécifique / état vide / skeleton

## Modèle de Données
### [Entité]
| Champ | Type | Requis | Description |

## Parcours Utilisateurs
Décris 2-3 flows principaux step-by-step (verbes d'action)

## Critères d'Acceptation
- [ ] Critère mesurable et vérifiable (minimum 8)

## Hors Scope v1
- Ce qui est explicitement exclu de la v1\
"""

_FALLBACK_QUESTION = {
    "skip": False,
    "project_name": "projet",
    "question": "Quel est le concept principal du projet ?",
    "options": ["Application web créative", "Application mobile", "API / backend", "Autre"],
}


def _make_llm():
    from src.infra.settings import settings
    from src.llm.models import make_llm, make_llm_ollama_cloud, make_llm_groq, make_llm_gemini, make_llm_mistral
    factories = {
        "groq": make_llm_groq,
        "ollama_cloud": make_llm_ollama_cloud,
        "gemini": make_llm_gemini,
        "mistral": make_llm_mistral,
    }
    return factories.get(settings.llm_backend, make_llm_ollama_cloud)()


def _slugify(name: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9_-]+", "-", name.lower()).strip("-")
    return s[:60] or "projet"


def _parse_json_response(text: str) -> dict:
    cleaned = re.sub(r"```(?:json)?\s*", "", text).replace("```", "").strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if m:
            try:
                return json.loads(m.group())
            except json.JSONDecodeError:
                pass
    return _FALLBACK_QUESTION


def _ask_llm_for_question(initial_prompt: str, qa_pairs: list[dict], llm, domain: str = "") -> dict:
    from langchain_core.messages import SystemMessage, HumanMessage

    history = ""
    if qa_pairs:
        history = "\n\nRéponses déjà collectées :\n"
        for qa in qa_pairs:
            history += f"- {qa['q']} → {qa['a']}\n"

    domain_hint = f"\n\nDomaine à couvrir maintenant : {domain}" if domain else ""
    user_content = f"Projet : {initial_prompt}{history}{domain_hint}"
    response = llm.invoke([SystemMessage(content=_QUESTION_SYSTEM), HumanMessage(content=user_content)])
    text = response.content if hasattr(response, "content") else str(response)
    return _parse_json_response(text)


def _collect_custom(prompt_text: str = "Votre réponse") -> str:
    try:
        return pt_prompt(f"  ✏  {prompt_text} : ").strip()
    except (KeyboardInterrupt, EOFError):
        return ""


def _generate_spec(initial_prompt: str, qa_pairs: list[dict], llm) -> str:
    from langchain_core.messages import SystemMessage, HumanMessage

    qa_text = "\n".join(f"- {qa['q']} → {qa['a']}" for qa in qa_pairs)
    user_content = f"Prompt initial : {initial_prompt}\n\nDétails collectés :\n{qa_text}"
    response = llm.invoke([SystemMessage(content=_SPEC_SYSTEM), HumanMessage(content=user_content)])
    return response.content if hasattr(response, "content") else str(response)


def run_spec_wizard(initial_prompt: str, console) -> None:
    from rich.panel import Panel
    from src.ui.panels import _BOX

    llm = _make_llm()
    qa_pairs: list[dict] = []
    project_name: Optional[str] = None

    console.print()
    console.print(Rule("création de spec", characters="·", style=f"dim {_ACCENT}"))

    # ── Boucle guidée par domaines ───────────────────────────────────────────
    for domain in _QUESTION_DOMAINS:
        data = _ask_llm_for_question(initial_prompt, qa_pairs, llm, domain=domain)

        if project_name is None and data.get("project_name"):
            project_name = data["project_name"]

        if data.get("skip") or not data.get("question"):
            continue  # Domaine déjà couvert par le prompt ou les réponses

        question = data["question"]
        options = data.get("options", []) + ["Autre (précisez)"]

        answer = pick(options, title=question)
        if answer is None:
            console.print(Text("  annulé", style=f"dim {_ACCENT}"))
            return

        if answer == "Autre (précisez)":
            answer = _collect_custom()
            if not answer:
                continue

        qa_pairs.append({"q": question, "a": answer})

    # ── Question finale ──────────────────────────────────────────────────────
    final = pick(
        ["Non, générer la spec", "Oui, ajouter des précisions"],
        title="Souhaitez-vous ajouter d'autres spécificités ?",
    )
    if final is None:
        console.print(Text("  annulé", style=f"dim {_ACCENT}"))
        return

    if final == "Oui, ajouter des précisions":
        extra = _collect_custom("Précisions supplémentaires")
        if extra:
            qa_pairs.append({"q": "Spécificités supplémentaires", "a": extra})

    # ── Génération de la spec ────────────────────────────────────────────────
    t = Text()
    t.append("  ⚙  ", style=f"bold {_ACCENT}")
    t.append("génération de la spec…", style="dim")
    console.print(t)

    spec_text = _generate_spec(initial_prompt, qa_pairs, llm)

    # ── Sauvegarde ───────────────────────────────────────────────────────────
    proj_slug = _slugify(project_name or "projet")
    projects_dir = get_projects_dir()
    proj_dir = projects_dir / proj_slug
    proj_dir.mkdir(parents=True, exist_ok=True)
    spec_path = proj_dir / "spec.md"
    spec_path.write_text(spec_text, encoding="utf-8")

    console.print(Panel(
        Text(str(spec_path), style=f"{_ACCENT}"),
        box=_BOX,
        border_style=f"dim {_ACCENT}",
        title="spec générée",
        padding=(0, 1),
    ))
