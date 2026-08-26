"""Le skill qui apprend à piloter un vrai navigateur.

Playwright MCP est branché depuis longtemps, mais rien n'apprenait au modèle à
s'en servir : ses outils se décrivent en trois mots d'anglais (« Perform click on
a web page »), sans dire qu'il faut LIRE la page avant d'agir ni comment obtenir
une référence cliquable.
"""
from __future__ import annotations

from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parents[1] / "skills" / "browser-driving.md"


@pytest.fixture(scope="module")
def contenu() -> str:
    return SKILL.read_text(encoding="utf-8")


def test_le_skill_est_visible_de_l_orchestrateur_ET_PAS_du_code():
    """Deux pièges à la fois. Un `scope` inconnu le filtre en silence — il
    existe et le modèle ne le trouve jamais. Et le déclarer aussi en `coding` le
    faisait gagner contre `apple-design` et `nextjs` sur les requêtes françaises,
    parce que la portée écarte les concurrents avant lui."""
    from src.skills import list_skills

    assert "browser-driving" in list_skills("orchestrator")
    assert "browser-driving" not in list_skills("coding")


def test_le_skill_se_charge():
    from src.skills import get_skill

    contenu = get_skill("browser-driving", scope="orchestrator")
    assert contenu and len(contenu) > 1000


def test_sa_description_alimente_le_routage_des_skills():
    """Les ancres du groupe `skills` sont les DESCRIPTIONS, pas les noms."""
    from src.orchestrator.tool_retriever import _skill_topics

    ancres = " ".join(_skill_topics()).lower()
    assert "playwright" in ancres


@pytest.mark.parametrize("requete", [
    "va sur ce site et connecte-toi à mon compte",
    "ouvre lenovo.com et ajoute le Legion au panier",
    "clique sur le bouton accepter de la page",
])
def test_une_intention_de_navigation_atteint_load_skill(requete):
    """« remplis le formulaire de contact » n'y figure pas : mesuré, il ne route
    pas. La description du skill est en anglais comme celles du registre, et
    aucun de ses mots ne rapproche cette tournure française. Connu, pas masqué."""
    from src.orchestrator.registry import build_all_tools
    from src.orchestrator.tool_retriever import ToolRetriever

    outils = {t.name for t in ToolRetriever(build_all_tools()).get(requete)}
    assert "load_skill" in outils, f"« {requete} » n'atteint aucun skill"


@pytest.mark.parametrize("requete", [
    "quelle heure est-il",
    "cherche la doc de langchain",
    "lis le fichier src/main.py",
])
def test_le_quotidien_ne_charge_pas_de_skill(requete):
    """Un skill chargé coûte des tokens sur un tour qui n'en a pas besoin."""
    from src.orchestrator.registry import build_all_tools
    from src.orchestrator.tool_retriever import ToolRetriever

    outils = {t.name for t in ToolRetriever(build_all_tools()).get(requete)}
    assert "load_skill" not in outils


# ── Ce que le skill doit enseigner ───────────────────────────────────────────
def test_il_enseigne_de_LIRE_avant_d_agir(contenu):
    """La seule chose qu'aucune description d'outil ne dit, et sans laquelle le
    modèle clique sur des sélecteurs inventés."""
    assert "browser_snapshot" in contenu
    assert "référence" in contenu.lower()


def test_il_nomme_les_outils_qui_existent_vraiment(contenu):
    """Un skill qui cite un outil absent envoie le modèle dans le mur. Les noms
    sont ceux du serveur, pas ceux qu'on imagine."""
    import re

    cites = set(re.findall(r"browser_[a-z_]+", contenu))
    reels = {
        "browser_click", "browser_close", "browser_console_messages",
        "browser_drag", "browser_drop", "browser_evaluate", "browser_file_upload",
        "browser_fill_form", "browser_find", "browser_handle_dialog",
        "browser_hover", "browser_navigate", "browser_navigate_back",
        "browser_network_request", "browser_network_requests", "browser_press_key",
        "browser_resize", "browser_run_code_unsafe", "browser_select_option",
        "browser_snapshot", "browser_tabs", "browser_take_screenshot",
        "browser_type", "browser_wait_for",
    }
    assert cites <= reels, f"outils inventés : {sorted(cites - reels)}"


def test_il_dit_quand_ne_pas_ouvrir_un_navigateur(contenu):
    """Sans cette borne, le modèle ouvre un navigateur pour une question à
    laquelle la recherche web répond en une seconde."""
    assert "web_research_report" in contenu


def test_il_interdit_la_saisie_de_secrets(contenu):
    bas = contenu.lower()
    assert "mot de passe" in bas
    assert "carte" in bas


def test_il_met_en_garde_contre_l_execution_de_code_arbitraire(contenu):
    """`browser_run_code_unsafe` contourne tout ce que les autres outils rendent
    lisible — et il est proposé au modèle comme les autres."""
    assert "browser_run_code_unsafe" in contenu
    position = contenu.index("browser_run_code_unsafe")
    autour = contenu[position - 200:position + 400].lower()
    assert "ne pas l'utiliser" in autour or "presque jamais" in autour
