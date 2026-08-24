"""Aucun outil ne doit dire au modèle « un objet quelconque ».

Symptôme d'origine, sur `gpt-oss:120b-cloud` : l'appel d'`ask_clarification`
s'est affiché EN TEXTE au lieu d'être exécuté —

    { "questions": [ { "question": "…", "choices": [] }, … ] }

`tool_calls` vide, donc Axon a pris ce JSON pour la réponse finale. Trois causes
superposées, dont une seule est corrigée ici :

  1. le schéma déclarait `questions: list[dict]` → « tableau d'objets
     quelconques ». La vraie structure ne vivait que dans la prose de la
     docstring. Un modèle moyen n'a alors aucune contrainte sur quoi s'appuyer ;
  2. le garde-fou de `graph.py` ne reconnaît que le balisage `<xxx:tool_call>`
     de MiniMax, pas un JSON nu — il n'a donc pas mordu ;
  3. le modèle lui-même émet parfois du texte au lieu d'un appel structuré.

Typer le schéma s'attaque à (1), la seule cause qui soit chez nous et qui vaille
pour TOUS les backends d'un coup.

Ces tests portent sur les schémas, jamais sur un modèle : ils sont déterministes
et rapides. Que le modèle appelle correctement l'outil, c'est une eval
comportementale, et elle ne peut pas vivre ici.
"""
import pytest

from src.orchestrator.registry import build_all_tools


def _defauts(schema: dict) -> list[str]:
    """Les champs qui ne contraignent rien, donc n'informent pas le modèle."""
    manques = []
    for champ, spec in (schema.get("properties") or {}).items():
        genre = spec.get("type")
        if genre == "array":
            items = spec.get("items") or {}
            if items.get("type") == "object" and not items.get("properties") and "$ref" not in items:
                manques.append(f"{champ}: liste d'objets non décrits")
            elif not items:
                manques.append(f"{champ}: liste sans type d'élément")
        elif genre == "object" and not spec.get("properties"):
            manques.append(f"{champ}: objet libre")
    return manques


def _schema(outil):
    try:
        return outil.args_schema.model_json_schema()
    except Exception:                                        # noqa: BLE001
        return None


# ── L'invariant, pour tous les outils présents et à venir ─────────────────────
def test_aucun_outil_n_expose_un_objet_non_decrit():
    """Le garde qui vaut pour les 98 outils, et pour le 99e.

    Deux le violaient — `ask_clarification` et `jira_create_issues_bulk` — et
    c'est le premier qui a produit le bug visible.
    """
    coupables = []
    for outil in build_all_tools():
        s = _schema(outil)
        if s and (d := _defauts(s)):
            coupables.append(f"{outil.name}: {', '.join(d)}")

    assert not coupables, "schémas sans contrainte structurelle :\n" + "\n".join(coupables)


def test_le_garde_detecte_vraiment_un_schema_lache():
    """Un garde qu'on ne vérifie pas peut être devenu aveugle sans qu'on le
    sache — il passerait au vert en ayant cessé de regarder."""
    lache = {"properties": {"items": {"type": "array",
                                      "items": {"type": "object"}}}}

    assert _defauts(lache)


def test_le_specialist_est_couvert_aussi():
    """Il a sa PROPRE `ask_clarification`, absente du registre orchestrateur.
    Ne typer que celle du registre aurait laissé la moitié du défaut en place."""
    from src.agents.coding.tools import ask_clarification

    assert _defauts(ask_clarification.args_schema.model_json_schema()) == []


# ── Ce que le schéma d'ask_clarification doit dire ────────────────────────────
@pytest.mark.parametrize("module", ["src.agents.clarify.tools", "src.agents.coding.tools"])
def test_le_schema_decrit_la_forme_d_une_question(module):
    import importlib

    outil = getattr(importlib.import_module(module), "ask_clarification")
    q = outil.args_schema.model_json_schema()["$defs"]["Question"]

    assert list(q["properties"]) == ["question", "choices"]
    assert q["required"] == ["question"]


# ── La tolérance ne disparaît pas ─────────────────────────────────────────────
#
# Typer guide le modèle ; la coercition rattrape celui qui envoie autre chose.
# Durcir sans elle transformerait une erreur récupérable en échec dur — et
# `normaliser_questions` documente déjà l'incident qui l'a motivée : une chaîne
# passée telle quelle devenait 1312 questions d'un caractère.

@pytest.mark.parametrize("brut, attendu", [
    ([{"question": "Quel projet ?", "choices": ["a", "b"]}], "Quel projet ?"),
    ([{"question": "Décris ton besoin"}], "Décris ton besoin"),
    ("Une seule question ?", "Une seule question ?"),
    (["Q1"], "Q1"),
])
def test_une_forme_approchante_reste_acceptee(brut, attendu):
    import json

    from src.agents.clarify.tools import ask_clarification

    charge = json.loads(ask_clarification.invoke({"questions": brut}))

    assert charge["questions"][0]["question"] == attendu


def test_une_chaine_ne_devient_jamais_une_question_par_caractere():
    """Le défaut exact que `normaliser_questions` a été écrite pour empêcher."""
    import json

    from src.agents.clarify.tools import ask_clarification

    charge = json.loads(ask_clarification.invoke({"questions": "Toutes les sections ?"}))

    assert len(charge["questions"]) == 1


def test_une_question_ouverte_n_emporte_pas_de_choix_vide():
    """L'interface distingue une question ouverte d'une question à choix par
    l'ABSENCE de la clé, pas par une liste vide."""
    import json

    from src.agents.clarify.tools import ask_clarification

    charge = json.loads(ask_clarification.invoke({"questions": [{"question": "Ton besoin ?"}]}))

    assert "choices" not in charge["questions"][0]


# ── Jira ──────────────────────────────────────────────────────────────────────
def test_le_schema_jira_porte_ce_que_la_docstring_decrivait():
    from src.agents.jira.tools import jira_create_issues_bulk

    issue = jira_create_issues_bulk.args_schema.model_json_schema()["$defs"]["Issue"]

    assert issue["required"] == ["summary"]
    assert set(issue["properties"]) >= {"summary", "issue_type", "epic_key", "parent_key"}


def test_les_types_de_ticket_sont_une_enumeration():
    """En texte libre, le modèle invente « User Story » ou « Feature » et l'API
    les refuse un par un, à l'exécution."""
    from src.agents.jira.tools import jira_create_issues_bulk

    issue = jira_create_issues_bulk.args_schema.model_json_schema()["$defs"]["Issue"]

    assert set(issue["properties"]["issue_type"]["enum"]) == {
        "Epic", "Story", "Task", "Bug", "Subtask"}


def test_un_ticket_seul_vaut_une_liste_d_un_element():
    """Le cas le plus fréquent quand il n'y en a qu'un à créer."""
    from src.agents.jira.tools import ArgsBulk

    args = ArgsBulk(project_key="KAN", issues={"summary": "Un seul ticket"})

    assert len(args.issues) == 1 and args.issues[0].issue_type == "Story"
