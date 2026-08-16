"""Troncature à l'entrée, plan révisable, prompt allégé.

Trois défauts constatés sur le même chemin :
  · `local_read_file` rend jusqu'à 200 000 caractères — 1,6× le budget entier
    d'ollama_cloud. Un seul appel déclenchait la compression, qui coûte un appel
    LLM complet, là où tronquer coûte zéro.
  · `dev_plan_create` refusait de rejouer : un plan invalidé par l'analyse
    laissait le choix entre mentir sur une étape et abandonner.
  · Le prompt enseignait `.scaffold`, un nom que npm refuse.
"""
from __future__ import annotations

import pytest

from src.agents.coding.pending import dev_plan
from src.agents.coding.prompts import BASE_PROMPT
from src.agents.coding.specialist import _MAX_TOOL_RESULT_CHARS, tronquer_resultat
from src.agents.coding.tools import dev_plan_create, dev_plan_update


# ── Troncature ───────────────────────────────────────────────────────────────

def test_un_resultat_court_passe_intact():
    assert tronquer_resultat("court") == "court"


def test_un_resultat_enorme_tient_dans_la_limite():
    assert len(tronquer_resultat("x" * 500_000)) <= _MAX_TOOL_RESULT_CHARS


def test_un_seul_resultat_ne_peut_plus_remplir_le_contexte():
    """Le plus petit budget configuré doit absorber plusieurs résultats."""
    from src.agents.coding.specialist import _CONTEXT_CHAR_BUDGET

    assert _MAX_TOOL_RESULT_CHARS < min(_CONTEXT_CHAR_BUDGET.values()) / 2


def test_le_debut_et_la_fin_survivent():
    """Un fichier porte son sens au début, un build son erreur à la fin."""
    texte = "DÉBUT" + "m" * 500_000 + "FIN"

    coupe = tronquer_resultat(texte)

    assert coupe.startswith("DÉBUT")
    assert coupe.endswith("FIN")


def test_la_coupe_est_annoncee_et_dit_comment_recuperer_la_suite():
    """Tronquer en silence ferait conclure au modèle que le fichier s'arrête là."""
    coupe = tronquer_resultat("x" * 100_000)

    assert "tronqué" in coupe
    assert "local_read_file(offset=" in coupe


def test_le_specialist_tronque_avant_de_mettre_en_contexte():
    import inspect

    from src.agents.coding import specialist

    source = inspect.getsource(specialist._run)

    assert "tronquer_resultat(_brut)" in source


# ── Plan révisable ───────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _plan_propre():
    dev_plan.clear()
    yield
    dev_plan.clear()


def _plan(*etapes):
    dev_plan_create.invoke({"steps": list(etapes)})


def test_les_etapes_restantes_sont_reecrites():
    _plan("A", "B", "C")

    resultat = dev_plan_update.invoke({"steps": ["A2", "B2"], "reason": "mauvaise piste"})

    assert resultat["status"] == "ok"
    assert [s.label for s in dev_plan.steps] == ["A2", "B2"]


def test_une_etape_deja_cochee_reste_cochee():
    _plan("A", "B", "C")
    dev_plan.check(0)

    dev_plan_update.invoke({"steps": ["A", "B2", "C2", "D"], "reason": "B était faux"})

    assert [(s.label, s.done) for s in dev_plan.steps] == [
        ("A", True), ("B2", False), ("C2", False), ("D", False)]


def test_on_ne_peut_pas_effacer_une_etape_deja_faite():
    """Réécrire l'histoire ferait perdre la preuve d'un travail réellement fait."""
    _plan("A", "B")
    dev_plan.check(0)

    resultat = dev_plan_update.invoke({"steps": ["X", "Y"], "reason": "hop"})

    assert resultat["status"] == "error"
    assert [s.label for s in dev_plan.steps] == ["A", "B"]


def test_une_revision_doit_dire_ce_qu_elle_a_appris():
    _plan("A")

    assert dev_plan_update.invoke({"steps": ["B"], "reason": "  "})["status"] == "error"


def test_le_plan_reste_creable_une_seule_fois():
    """dev_plan_update est la porte de sortie ; en rouvrir une seconde par
    dev_plan_create ferait perdre les étapes cochées sans le dire."""
    _plan("A")

    assert dev_plan_create.invoke({"steps": ["Z"]})["status"] == "already_exists"


# ── Prompt ───────────────────────────────────────────────────────────────────

def test_le_prompt_enseigne_un_nom_de_scaffold_que_npm_accepte():
    """`.scaffold` était refusé (« name cannot start with a period ») : le prompt
    enseignait la commande dont build_runner documente qu'elle échoue."""
    from src.agents.coding.build_runner import SCAFFOLD_DIRNAME

    assert SCAFFOLD_DIRNAME in BASE_PROMPT
    assert ".scaffold" not in BASE_PROMPT
    assert not SCAFFOLD_DIRNAME[0] in "._"


def test_le_prompt_porte_l_echelle_de_decision():
    """Une interdiction dit quoi ne pas faire ; un barreau dit où s'arrêter de
    chercher — c'est ce qu'un modèle peut exécuter."""
    for barreau in ("bibliothèque standard", "Une fonctionnalité native",
                    "Ça tient en une ligne", "dépendance déjà installée"):
        assert barreau in BASE_PROMPT


def test_l_echelle_ne_s_applique_jamais_a_la_lecture():
    assert "jamais à la lecture" in BASE_PROMPT
    assert "CAUSE RACINE" in BASE_PROMPT


def test_l_echelle_nomme_ce_qu_on_ne_simplifie_pas():
    """Sans cette clause, « le minimum qui marche » supprime les gardes."""
    for intouchable in ("sécurité", "accessibilité", "perte de données"):
        assert intouchable in BASE_PROMPT


def test_le_prompt_a_cesse_de_grossir():
    """Il avait atteint 19 469 caractères et une quarantaine de ❌ : une liste
    d'interdictions, pas une méthode."""
    assert len(BASE_PROMPT) < 15_000
    assert BASE_PROMPT.count("❌") < 20


def test_le_prompt_designe_l_edition_comme_defaut():
    assert "edit_file" in BASE_PROMPT
    assert BASE_PROMPT.index("edit_file") < BASE_PROMPT.index("propose_file_change")


def test_le_prompt_documente_la_revision_de_plan():
    assert "dev_plan_update" in BASE_PROMPT


def test_le_prompt_donne_la_convention_de_raccourci_assume():
    """Un raccourci sans plafond ni condition devient définitif en silence."""
    assert "# axon:" in BASE_PROMPT
