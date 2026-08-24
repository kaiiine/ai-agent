"""Un prompt, un fichier, un seul endroit où chercher.

Ils vivaient dans cinq fichiers différents, chacun collé au code qui l'appelait :
`prompts.py` pour l'orchestrateur, mais aussi une constante au milieu de
`cron_daemon.py`, une autre dans `spec/review.py`, une troisième dans
`task_decomposer.py`. Pour relire ou corriger un prompt, il fallait d'abord
deviner lequel des cinq le contenait — et l'audit du 18 août a montré que ce qui
ne se relit pas dérive : une section morte, une contradiction interne, une charte
recopiée d'un skill.

Le regroupement ne corrige aucun de ces défauts : c'est du rangement, pas une
correction. Il rend seulement leur relecture possible. Ces tests gardent donc
deux choses — que le rangement tienne, et qu'il n'ait rien changé au contenu.

Le prompt du SPECIALIST reste volontairement dans `src/agents/coding/prompts/` :
il a son propre paquet de longue date, et les guides par stack s'y référaient.
"""
import ast
import subprocess
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parent.parent
DOSSIER = RACINE / "src" / "llm" / "prompts"


def _source_au_commit(chemin: str) -> str:
    return subprocess.run(["git", "show", f"HEAD:{chemin}"],
                          cwd=RACINE, capture_output=True, text=True).stdout


def _constante(source: str, nom: str):
    """La valeur d'une constante littérale, évaluée comme Python le ferait.

    Comparer le SOURCE brut d'un côté à la chaîne ÉVALUÉE de l'autre donne de
    faux écarts — `\\\\"` dans le fichier vaut `\\"` une fois lu. Les deux côtés
    passent donc par le même chemin.
    """
    for n in ast.walk(ast.parse(source)):
        if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == nom:
            return ast.literal_eval(n.value)
    return None


# ── Le rangement ──────────────────────────────────────────────────────────────
def test_le_paquet_existe_avec_un_fichier_par_prompt():
    attendus = {"__init__.py", "orchestrateur.py", "revue_spec.py",
                "cron.py", "decomposeur.py"}

    assert attendus <= {f.name for f in DOSSIER.glob("*.py")}


def test_le_passage_en_paquet_ne_casse_aucun_import():
    """`src/llm/prompts.py` est devenu `src/llm/prompts/`. Douze sites
    importaient déjà de `src.llm.prompts`, dont trois des noms privés — le
    paquet doit tous les servir, sinon le rangement coûte une réécriture."""
    from src.llm.prompts import (  # noqa: F401
        _CORE, _LANG_INSTRUCTIONS, _SKILLS, _WEB, build_system_prompt,
    )


@pytest.mark.parametrize("module, nom", [
    ("src.llm.prompts.cron", "SYSTEME"),
    ("src.llm.prompts.revue_spec", "SYSTEME"),
    ("src.llm.prompts.decomposeur", "SYSTEME"),
])
def test_chaque_prompt_deplace_est_importable(module, nom):
    import importlib

    valeur = getattr(importlib.import_module(module), nom)

    assert isinstance(valeur, str) and len(valeur) > 300


# ── Le contenu n'a pas bougé ──────────────────────────────────────────────────
@pytest.mark.parametrize("fichier, ancien, module, neuf", [
    ("src/cron_daemon.py", "_SYSTEM", "src.llm.prompts.cron", "SYSTEME"),
    ("src/agents/spec/review.py", "_SYSTEME", "src.llm.prompts.revue_spec", "SYSTEME"),
    ("src/agents/coding/task_decomposer.py", "_DECOMPOSE_SYSTEM",
     "src.llm.prompts.decomposeur", "SYSTEME"),
])
def test_le_prompt_deplace_est_identique_a_l_original(fichier, ancien, module, neuf):
    """Un déplacement qui modifie le texte n'est plus un déplacement : c'est un
    changement de comportement non mesuré, glissé dans un commit de rangement."""
    import importlib

    avant = _constante(_source_au_commit(fichier), ancien)
    if avant is None:
        pytest.skip(f"{ancien} déjà retiré de {fichier} dans HEAD")
    apres = getattr(importlib.import_module(module), neuf)

    assert avant == apres


# ── Les appelants s'en servent vraiment ───────────────────────────────────────
def test_le_daemon_cron_utilise_le_prompt_range():
    import src.cron_daemon as daemon
    from src.llm.prompts.cron import SYSTEME

    assert daemon._SYSTEM is SYSTEME


def test_la_revue_de_spec_utilise_le_prompt_range():
    import src.agents.spec.review as review
    from src.llm.prompts.revue_spec import SYSTEME

    assert review._SYSTEME is SYSTEME


def test_le_decomposeur_appelle_le_prompt_range():
    """Il ne se contente pas d'importer : il passe par `systeme_pour`, seul
    endroit qui connaisse la table de budget."""
    import inspect

    from src.agents.coding.task_decomposer import decompose

    assert "systeme_pour(backend)" in inspect.getsource(decompose)


def test_aucun_prompt_ne_traine_plus_dans_les_appelants():
    """Le rangement serait vide de sens si une copie restait sur place : c'est
    la duplication qui a fait diverger les guides par stack, et `_STUDY` du
    skill `fiche`."""
    for fichier, nom in [("src/cron_daemon.py", "_SYSTEM"),
                         ("src/agents/spec/review.py", "_SYSTEME"),
                         ("src/agents/coding/task_decomposer.py", "_DECOMPOSE_SYSTEM")]:
        source = (RACINE / fichier).read_text(encoding="utf-8")
        assert f'{nom} = """' not in source, f"{fichier} garde une copie de {nom}"


# ── Le gabarit du décomposeur ─────────────────────────────────────────────────
@pytest.mark.parametrize("backend", ["mistral", "gemini", "ollama", "inconnu"])
def test_le_budget_est_injecte_pour_tout_backend(backend):
    from src.llm.prompts.decomposeur import systeme_pour

    p = systeme_pour(backend)

    assert "{budget}" not in p, "le champ n'a pas été rempli"
    assert "Budget : Backend" in p


def test_les_accolades_du_gabarit_json_survivent_au_format():
    """Elles sont DOUBLÉES dans la source parce que le prompt passe par
    `.format()`. Les dédoubler « pour faire propre » casserait le JSON attendu,
    et l'erreur ne se verrait qu'à l'exécution d'un `/build`."""
    from src.llm.prompts.decomposeur import systeme_pour

    p = systeme_pour("mistral")

    assert "{{" not in p and "}}" not in p
    assert '{\n  "phases"' in p
