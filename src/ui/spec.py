"""Wizard de spécification interactive — la conversation, pas la méthode.

Ce module MÈNE l'échange : il affiche, demande, sauvegarde. Ce qu'il faut
demander, dans quel ordre, sous quelle forme écrire le résultat et ce qui manque
encore vivent dans `src/agents/spec/` — testables sans terminal.

La version précédente posait cinq questions FIXES, écrites pour des projets web
créatifs : elle demandait une palette de couleurs à un pipeline de données et ne
lui demandait jamais sa politique de reprise. Les questions viennent désormais du
projet, via une carte de couverture calculée sur le descriptif initial.
"""
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

_QUESTION_SYSTEM = """\
Tu rédiges UNE question de clarification sur un projet logiciel.

On te donne la catégorie à couvrir, ce qu'elle recouvre, et pourquoi elle compte.
Ta question doit obtenir une DÉCISION, pas une opinion.

Réponds UNIQUEMENT avec un objet JSON, sans markdown :
{
  "project_name": "nom-kebab-case",
  "question": "Question précise et directe ?",
  "options": ["Option concrète A", "Option concrète B", "Option concrète C"],
  "skip": false
}

Règles :
- 2 à 4 options MUTUELLEMENT EXCLUSIVES et concrètes. Une option est un choix
  qu'on peut implémenter tel quel : « PostgreSQL », pas « une base relationnelle » ;
  « Glassmorphism sombre + serif », pas « un style moderne ».
- Pour une stack : chaque option est une stack COMPLÈTE, pas un composant isolé.
- Si le descriptif tranche déjà la catégorie : {"skip": true, "project_name": "...",
  "question": "", "options": []}
- Ne pose jamais deux fois la même question sous deux formulations.
- project_name : kebab-case, sans espaces, stable d'une question à l'autre.\
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
    from src.llm.backends import fabriques as _registre

    factories = _registre()
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


_PROFIL_SYSTEM = """\
Tu identifies la NATURE d'un projet logiciel à partir de son descriptif.

Réponds UNIQUEMENT avec un objet JSON, sans markdown :
{"profil": "<identifiant>", "confiance": "haute|moyenne|basse"}

Identifiants autorisés, et rien d'autre :
site_web · application_web · api_service · cli · pipeline_donnees · mobile ·
bibliotheque · agent_ia · generique

Règles :
- « site_web » = vitrine, landing, portfolio : du contenu, peu ou pas de compte.
- « application_web » dès qu'il y a des comptes, des données propres à
  l'utilisateur, ou plusieurs écrans d'outil.
- En cas d'hésitation réelle : "generique" avec confiance "basse". Un mauvais
  profil pose des questions hors sujet, ce qui coûte plus qu'un profil neutre.\
"""


def _detecter_profil(descriptif: str, llm) -> tuple[str, str]:
    """La nature du projet — c'est elle qui décide des catégories à couvrir.

    Une erreur ici coûte cher : le profil ajoute les questions propres au type de
    projet, et se tromper revient à demander une palette de couleurs à un
    pipeline. D'où le repli sur `generique`, qui ne pose que le socle plutôt que
    des questions hors sujet.
    """
    from langchain_core.messages import HumanMessage, SystemMessage

    from src.agents.spec.taxonomy import LIBELLES_PROFIL

    try:
        reponse = llm.invoke([SystemMessage(content=_PROFIL_SYSTEM),
                              HumanMessage(content=descriptif[:4000])])
        data = _parse_json_response(getattr(reponse, "content", str(reponse)))
    except Exception:                                            # noqa: BLE001
        data = {}
    profil = str(data.get("profil", "")).strip()
    if profil not in LIBELLES_PROFIL:
        return "generique", "basse"
    return profil, str(data.get("confiance", "moyenne"))


def _ask_llm_for_question(initial_prompt: str, qa_pairs: list[dict], llm,
                          categorie=None) -> dict:
    from langchain_core.messages import SystemMessage, HumanMessage

    history = ""
    if qa_pairs:
        history = "\n\nRéponses déjà collectées :\n"
        for qa in qa_pairs:
            history += f"- {qa['q']} → {qa['a']}\n"

    # La catégorie apporte ce qu'elle recouvre ET pourquoi elle compte : sans le
    # « pourquoi », le modèle produit une question polie et sans conséquence.
    cible = ""
    if categorie is not None:
        cible = (f"\n\nCatégorie à couvrir : {categorie.libelle}"
                 f"\nCe qu'elle recouvre : {', '.join(categorie.couvre)}"
                 f"\nPourquoi elle compte : {categorie.pourquoi}")
    user_content = f"Projet : {_resolve_file_refs(initial_prompt)}{history}{cible}"
    response = llm.invoke([SystemMessage(content=_QUESTION_SYSTEM), HumanMessage(content=user_content)])
    text = response.content if hasattr(response, "content") else str(response)
    return _parse_json_response(text)


def _collect_custom(prompt_text: str = "Votre réponse") -> str:
    try:
        return pt_prompt(f"  ✏  {prompt_text} : ").strip()
    except (KeyboardInterrupt, EOFError):
        return ""


def _read_dir(path) -> str | None:
    """Read README.md or AXON.md from a directory, return content or None."""
    from pathlib import Path
    p = Path(path)
    for candidate in ('README.md', 'readme.md', 'AXON.md'):
        f = p / candidate
        if f.is_file():
            try:
                return f.read_text(encoding='utf-8', errors='replace')[:6000]
            except Exception:
                pass
    return None


def _resolve_file_refs(text: str) -> str:
    """Detect file/dir references in text (absolute paths + project names), inject contents."""
    import re
    from pathlib import Path

    already_read: set[str] = set()
    found: list[str] = []

    def _inject(p: Path, label: str) -> None:
        key = str(p.resolve())
        if key in already_read:
            return
        already_read.add(key)
        try:
            if p.is_file() and p.suffix in ('.md', '.txt', '.yaml', '.yml', '.toml', '.json', '.py', '.ts'):
                content = p.read_text(encoding='utf-8', errors='replace')[:6000]
                found.append(f"\n\n[Contenu de {label}]\n{content}\n[/Contenu]")
            elif p.is_dir():
                # Sommaire INTÉGRAL + corps large. `_read_dir` coupait à 6 000
                # caractères au milieu du document : sur un README de 19 196, la
                # spec n'a vu que trois fonctionnalités sur quinze, et a décrit
                # un produit réduit à son premier tiers.
                from src.agents.spec.sources import resumer_source
                resume = resumer_source(p)
                if resume:
                    found.append(resume)
                else:
                    content = _read_dir(p)
                    if content:
                        found.append(f"\n\n[Contenu de {label}/README]\n{content}\n[/Contenu]")
                # Une charte visuelle n'est presque JAMAIS dans le README : elle
                # vit dans un SVG, une config Tailwind, un globals.css. Lire le
                # seul README revenait à ouvrir la source pointée et à n'y rien
                # trouver — puis à inventer. Mesuré : « regarder dans le repo
                # ai-agent » a produit une palette cyan/corail là où l'identité
                # réelle est ambre et violet, dans assets/banner.svg.
                from src.agents.spec.sources import extraire_design
                found.append(extraire_design(p).rendu(label))
        except Exception:
            pass

    # 1. Chemins absolus : /home/... ou ~/...
    for m in re.finditer(r'(~?/[\w./\-]+)', text):
        raw = m.group(1).replace('~', str(Path.home()))
        _inject(Path(raw), m.group(1))

    # 2. Noms de projets connus dans le répertoire projets
    try:
        projects_dir = get_projects_dir()
        # Cherche les mots du texte qui correspondent à un sous-dossier
        words = re.findall(r'[\w][\w\-\.]{2,}', text)
        for word in set(words):
            candidate = projects_dir / word
            if candidate.is_dir():
                _inject(candidate, word)
    except Exception:
        pass

    # 3. Mention explicite de "readme" sans chemin → essaie le cwd
    if re.search(r'\breadme\b', text, re.IGNORECASE) and not found:
        _inject(Path.cwd(), 'cwd')

    return text + ''.join(found)


def _generate_spec(initial_prompt: str, qa_pairs: list[dict], llm,
                   profil: str = "generique") -> str:
    """La spec, écrite selon le plan du PROFIL et non un plan unique.

    Le journal des clarifications est ajouté APRÈS la génération, pas demandé au
    modèle : il doit reproduire les réponses telles qu'elles ont été données, et
    un modèle qui les reformule perd précisément ce qui rend le journal utile.
    """
    from langchain_core.messages import SystemMessage, HumanMessage

    from src.agents.spec.template import (
        journal_des_clarifications, systeme_de_generation,
    )

    resolved_pairs = [{"q": qa["q"], "a": _resolve_file_refs(qa["a"])} for qa in qa_pairs]
    qa_text = "\n".join(f"- {qa['q']} → {qa['a']}" for qa in resolved_pairs)
    resolved_prompt = _resolve_file_refs(initial_prompt)
    user_content = (f"Descriptif initial : {resolved_prompt}\n\n"
                    f"Décisions collectées :\n{qa_text}")
    response = llm.invoke([SystemMessage(content=systeme_de_generation(profil)),
                           HumanMessage(content=user_content)])
    spec = response.content if hasattr(response, "content") else str(response)
    return spec.rstrip() + "\n" + journal_des_clarifications(qa_pairs)


def _afficher_constats(constats, console) -> None:
    """Ce qui manque encore, du plus grave au moins grave.

    Affiché même quand tout va bien : « aucun constat » est une information, et
    son absence laisserait croire que la vérification n'a pas eu lieu.
    """
    from src.agents.spec.analyze import resume

    couleurs = {"CRITIQUE": "red", "HAUTE": _ACCENT,
                "MOYENNE": "yellow", "BASSE": "dim"}
    console.print()
    t = Text()
    t.append("  ⌖  vérification : ", style="dim")
    t.append(resume(constats), style=_ACCENT if constats else "green")
    console.print(t)
    for c in constats[:12]:
        ligne = Text("     ")
        ligne.append(f"{c.severite:<9}", style=couleurs.get(c.severite, "dim"))
        if c.ligne:
            ligne.append(f"L{c.ligne:<5}", style="dim")
        ligne.append(c.message, style="dim")
        console.print(ligne)
    if len(constats) > 12:
        console.print(Text(f"     … et {len(constats) - 12} autre(s)", style="dim"))


def run_spec_wizard(initial_prompt: str, console) -> None:
    from rich.panel import Panel
    from src.ui.panels import _BOX

    from src.agents.spec.coverage import a_demander, resume, scanner
    from src.agents.spec.taxonomy import LIBELLES_PROFIL

    llm = _make_llm()
    qa_pairs: list[dict] = []
    project_name: Optional[str] = None
    descriptif = _resolve_file_refs(initial_prompt)

    console.print()
    console.print(Rule("création de spec", characters="·", style=f"dim {_ACCENT}"))

    # ── 1. Nature du projet — elle décide des catégories à couvrir ───────────
    profil, confiance = _detecter_profil(descriptif, llm)
    if confiance != "haute":
        # Un profil deviné change les questions posées : quand le modèle hésite,
        # c'est à l'utilisateur de trancher, pas au repli de décider en silence.
        choix = pick([LIBELLES_PROFIL[p] for p in LIBELLES_PROFIL],
                     title="De quel type de projet s'agit-il ?")
        if choix is None:
            console.print(Text("  annulé", style=f"dim {_ACCENT}"))
            return
        profil = next(p for p, lib in LIBELLES_PROFIL.items() if lib == choix)

    t = Text()
    t.append("  ◈  ", style=f"bold {_ACCENT}")
    t.append(f"{LIBELLES_PROFIL[profil]}", style=_ACCENT)
    t.append("  ·  analyse de ce qui est déjà décidé…", style="dim")
    console.print(t)

    # ── 2. Carte de couverture — ce qui est dit, ce qui manque ───────────────
    lectures = scanner(descriptif, profil, llm)
    console.print(Text(resume(lectures), style="dim"))

    questions = a_demander(lectures)
    if not questions:
        console.print(Text("  tout est déjà tranché — génération directe", style="dim"))

    # ── 3. Questions, les plus décisives d'abord ─────────────────────────────
    for lecture in questions:
        data = _ask_llm_for_question(descriptif, qa_pairs, llm,
                                     categorie=lecture.categorie)

        if project_name is None and data.get("project_name"):
            project_name = data["project_name"]

        if data.get("skip") or not data.get("question"):
            continue  # le modèle voit une décision que le scan avait manquée

        question = data["question"]
        options = data.get("options", []) + ["Autre (précisez)", "Sans avis — tranche pour moi"]

        answer = pick(options, title=question)
        if answer is None:
            console.print(Text("  annulé", style=f"dim {_ACCENT}"))
            return

        if answer == "Autre (précisez)":
            answer = _collect_custom()
            if not answer:
                continue
        elif answer == "Sans avis — tranche pour moi":
            # Déléguer est un choix légitime, mais il doit rester TRAÇABLE :
            # dans le journal, cette ligne dira que la décision vient du modèle.
            answer = "(délégué — le rédacteur tranche et justifie en une ligne)"

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

    spec_text = _generate_spec(initial_prompt, qa_pairs, llm, profil=profil)

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

    # ── Vérification — avant de brûler des tokens en build ───────────────────
    #
    # DEUX passes. La déterministe voit la forme : gabarit oublié, identifiant en
    # double, adjectif sans chiffre. La sémantique voit le sens : contradictions,
    # combinaisons techniques impossibles, cibles arbitraires, cœur du produit
    # moins détaillé que sa périphérie. Aucune ne remplace l'autre.
    from src.agents.spec.analyze import analyser, bloquant
    from src.agents.spec.review import fusionner, relire

    t = Text()
    t.append("  ⌖  ", style="dim")
    t.append("relecture…", style="dim")
    console.print(t)

    # La DEMANDE entre dans l'analyse : une exigence explicite qui n'a pas
    # survécu jusqu'au document est invisible à tout contrôle interne.
    demande = initial_prompt + "\n" + "\n".join(
        f"{p['q']} {p['a']}" for p in qa_pairs)
    constats = fusionner(analyser(spec_text, demande), relire(spec_text, llm))
    _afficher_constats(constats, console)
    if bloquant(constats):
        console.print()
        console.print(Text(
            "  ⚠  des constats CRITIQUES subsistent : `/build` produira des "
            "décisions arbitraires sur ces points.", style=_ACCENT))
