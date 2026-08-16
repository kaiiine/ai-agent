"""Portée des skills, et sens des dépendances de src/skills/."""
from __future__ import annotations

import pathlib

import pytest

from src.skills.retriever import SkillRetriever


@pytest.fixture
def skills(tmp_path):
    (tmp_path / "nextjs.md").write_text(
        "---\nname: nextjs\ndescription: Next.js App Router\n---\nRÈGLES NEXT", encoding="utf-8")
    (tmp_path / "blender.md").write_text(
        "---\nname: blender\ndescription: scène 3D\nscope: [coding, orchestrator]\n---\nRÈGLES BLENDER",
        encoding="utf-8")
    (tmp_path / "hors_code.md").write_text(
        "---\nname: hors_code\ndescription: d\nscope: orchestrator\n---\nC", encoding="utf-8")
    (tmp_path / "legacy.md").write_text("PAS DE FRONTMATTER", encoding="utf-8")
    return SkillRetriever(tmp_path)


# ── portées ─────────────────────────────────────────────────────────────────────
def test_defaut_coding_sans_scope(skills):
    assert {"nextjs", "legacy"} <= set(skills.list_names("coding"))
    assert not {"nextjs", "legacy"} & set(skills.list_names("orchestrator"))


def test_une_liste_rend_visible_des_deux_cotes(skills):
    assert "blender" in skills.list_names("coding")
    assert "blender" in skills.list_names("orchestrator")


def test_un_scope_unique_exclut_lautre(skills):
    assert "hors_code" in skills.list_names("orchestrator")
    assert "hors_code" not in skills.list_names("coding")


def test_sans_portee_aucun_filtrage(skills):
    assert len(skills.list_names()) == 4


def test_les_portees_declarees_sont_inspectables(skills):
    assert skills.scopes_in_use() == {"coding", "orchestrator"}


# ── le cloisonnement tient sur les QUATRE chemins de recherche ─────────────────
def test_un_skill_hors_portee_est_refuse_pas_remplace(skills):
    """Sans ce garde-fou, le sémantique servait un autre skill par ressemblance."""
    assert skills.get("nextjs", scope="coding") == "RÈGLES NEXT"
    assert "non disponible dans ce contexte" in skills.get("nextjs", scope="orchestrator")
    assert "non disponible dans ce contexte" in skills.get("NEXTJS", scope="orchestrator")
    # le message garde le préfixe attendu par les appelants (déclenche le repli)
    assert skills.get("nextjs", scope="orchestrator").startswith("Skill '")


def test_un_alias_ne_traverse_pas_la_portee(tmp_path):
    (tmp_path / "a.md").write_text(
        "---\nname: a\ndescription: d\naliases: [zz]\n---\nSECRET", encoding="utf-8")
    r = SkillRetriever(tmp_path)
    assert r.get("zz", scope="coding") == "SECRET"
    assert "non disponible dans ce contexte" in r.get("zz", scope="orchestrator")


# ── le tool fabriqué ────────────────────────────────────────────────────────────
@pytest.fixture
def retriever_patche(monkeypatch, skills):
    import src.skills.retriever as retriever_module

    monkeypatch.setattr(retriever_module, "_retriever", skills)
    return skills


def test_le_catalogue_du_tool_respecte_la_portee(retriever_patche):
    from src.skills.tools import make_load_skill

    assert "blender" in make_load_skill("orchestrator").description
    assert "nextjs" not in make_load_skill("orchestrator").description
    assert "nextjs" in make_load_skill("coding").description


def test_un_skill_hors_portee_est_refuse_franchement(retriever_patche):
    """Il exista un repli vers des copies Python des guides ; elles ont divergé des
    .md sans que personne ne le voie. Un refus net vaut mieux qu'un guide périmé."""
    from src.skills.tools import make_load_skill

    reponse = make_load_skill("orchestrator").invoke({"stack": "nextjs"})

    assert "non disponible" in reponse


def test_aucune_description_ne_contient_de_clause_negative():
    """Une clause « ne pas utiliser pour X » marche chez les agents qui LISENT la
    description. Ici elle est le page_content d'un Document Chroma : elle est
    embarquée, et un embedding ne représente pas la négation. Mesuré sur
    nomic-embed-text, ajouter « ne pas utiliser pour une présentation » à la
    description de nextjs augmente sa similarité à une requête PowerPoint de 71 %
    (0.374 → 0.640) — soit exactement l'inverse du but recherché.

    Ce qui filtre réellement ici, c'est `scope`, et il est déterministe.
    """
    import pathlib
    import re

    negations = re.compile(
        r"\bne (?:pas|jamais)\b|\bn'utilise\b|\bdo not use\b|\bdon't use\b|\bnever use\b",
        re.IGNORECASE)

    fautifs = []
    for fichier in sorted(pathlib.Path("skills").glob("*.md")):
        entete = fichier.read_text(encoding="utf-8").split("---")[1:2]
        if entete and negations.search(entete[0]):
            fautifs.append(fichier.name)

    assert not fautifs, f"clause négative dans le frontmatter (elle attire au lieu de repousser) : {fautifs}"


def test_les_ancres_viennent_des_descriptions(retriever_patche):
    from src.skills.tools import anchors_for

    assert anchors_for("orchestrator") == ["scène 3D", "d"]


# ── séparation code / contenu ───────────────────────────────────────────────────
def test_le_repertoire_de_contenu_ne_contient_que_des_skills():
    """skills/ = contenu, src/skills/ = code. Un .py ici perdrait la frontière."""
    contenu = pathlib.Path("skills")
    intrus = [p.name for p in contenu.iterdir() if p.suffix != ".md"]
    assert intrus == [], f"fichiers non-markdown dans skills/ : {intrus}"
    assert len(list(contenu.glob("*.md"))) >= 14


def test_le_paquet_de_code_ne_contient_aucun_skill():
    assert list(pathlib.Path("src/skills").glob("*.md")) == []


def test_le_paquet_skills_ne_depend_ni_des_agents_ni_de_lorchestrateur():
    """La dépendance ne va que dans un sens."""
    for fichier in pathlib.Path("src/skills").glob("*.py"):
        source = fichier.read_text(encoding="utf-8")
        assert "src.agents" not in source, f"{fichier} dépend d'un agent"
        assert "src.orchestrator" not in source, f"{fichier} dépend de l'orchestrateur"


# ── câblage réel ────────────────────────────────────────────────────────────────
def test_load_skill_est_expose_par_lorchestrateur():
    from src.orchestrator.registry import build_all_tools

    outils = {t.name: t for t in build_all_tools()}
    assert "load_skill" in outils
    # côté orchestrateur, le catalogue ne montre que blender
    description = outils["load_skill"].description
    assert "blender" in description and "nextjs" not in description


def test_le_prompt_skills_est_injecte_avec_le_tool():
    from src.llm.prompts import build_system_prompt

    avec = build_system_prompt(["load_skill"], "2026-08-04", "kaine")
    sans = build_system_prompt(["get_current_time"], "2026-08-04", "kaine")
    assert "PROJECT SKILLS" in avec and "PROJECT SKILLS" not in sans


# ── la consigne reste une décision du modèle, mais impérative ──────────────────
def test_la_consigne_est_imperative_et_inconditionnelle():
    """On durcit la consigne plutôt que de contourner le modèle : le chargement
    reste un appel d'outil, pas une injection hors boucle."""
    from src.llm.prompts import _SKILLS

    for marqueur in ("MANDATORY FIRST STEP", "UNCONDITIONAL", "BEFORE anything else"):
        assert marqueur in _SKILLS
    assert 'Do NOT first decide whether the task "needs" a skill' in _SKILLS


def test_la_section_precede_les_sections_metier():
    """Une consigne de première étape reléguée après les règles d'outils la perd."""
    from src.llm.prompts import build_system_prompt

    p = build_system_prompt(["load_skill", "shell_run", "alpha__t"], "2026-08-04", "kaine")
    assert p.index("━━ PROJECT SKILLS ━━") < p.index("━━ SHELL & GIT ━━")
    assert p.index("━━ PROJECT SKILLS ━━") < p.index("━━ EXTERNAL SERVERS (MCP) ━━")


def test_la_description_du_tool_porte_la_meme_exigence():
    from src.skills.tools import make_load_skill

    d = make_load_skill("orchestrator").description
    assert "Call this FIRST" in d and "unconditional" in d


def test_aucune_injection_hors_boucle_doutil():
    """Le contenu d'un skill n'entre dans le prompt que par un appel de tool."""
    from src.llm.prompts import build_system_prompt

    p = build_system_prompt(["load_skill", "alpha__t"], "2026-08-04", "kaine")
    assert "━━ SKILL :" not in p


def test_la_delegation_coding_est_bornee_au_deliverable():
    """« pas de code » et « je l'exporterai pour le web » ne doivent pas router
    vers l'agent coding : il n'a pas les tools qui agissent sur la cible."""
    from src.llm.prompts import _CODING

    assert "DELIVERABLE is source files" in _CODING
    assert "NEVER delegate a task you can perform yourself" in _CODING
    assert '"no code" → never run_coding_agent' in _CODING
