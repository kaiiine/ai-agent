"""Le rapport de l'agent de code est MONTRÉ, pas re-raconté.

Il partait à l'orchestrateur — un autre modèle — avec « Restitue-le à
l'utilisateur sans rien y ajouter ». Une prière, pas une garantie. Vécu :
l'agent avait écrit un vrai résumé (« Le script tri.py fonctionne correctement…
Vous pouvez l'utiliser tel quel »), et l'orchestrateur l'a jeté pour répondre
lui-même à la demande d'origine, en réimprimant un script DIFFÉRENT de celui du
disque — un `sorted()` là où le fichier triait par insertion. Son propre prompt le
lui interdisait pourtant, mot pour mot.

Un texte qui existe n'a rien à gagner à repasser par un modèle : on l'affiche, et
on ne donne à l'orchestrateur qu'un état compact, sur lequel il n'a rien à
récrire.
"""
from __future__ import annotations

import json

import pytest
from langchain_core.messages import ToolMessage

from src.agents.coding import noeud
from src.orchestrator.note_interne import est_interne

RAPPORT = ("[SPECIALIST-TRACE]\ncwd:/home/kaine\nfiles:/tmp/axon-essai/tri.py\n"
           "[/SPECIALIST-TRACE]\n"
           "Le script **tri.py** utilise un tri par insertion. Exécuté avec "
           "`5 2 9` : `[2, 5, 9]`. Aucun autre changement n'est requis.")


@pytest.fixture
def run(monkeypatch):
    """Fait tourner `coder` sur un résultat donné. Rend (ce qui est montré, message)."""
    def _run(resultat: str):
        from src.agents.coding import specialist

        montre: list = []
        monkeypatch.setattr(specialist, "set_progress_callback", lambda cb: None)
        monkeypatch.setattr(specialist, "_progress_cb",
                            lambda nom, args, res=None: montre.append((nom, args)),
                            raising=False)
        monkeypatch.setattr(specialist, "preparer", lambda t: (
            type("G", (), {"invoke": lambda s, e: {}})(), lambda r: resultat))
        monkeypatch.setattr(specialist, "_vram_swap_in", lambda: None)
        monkeypatch.setattr(specialist, "_vram_swap_out", lambda: None)

        sortie = noeud.coder({"messages": [ToolMessage(
            content=json.dumps({"status": noeud.MARQUEUR, "tache": "écris tri.py"}),
            tool_call_id="c1", name="run_coding_agent")]})
        affiche = next((a["texte"] for n, a in montre if n == noeud.RAPPORT), "")
        return affiche, sortie["messages"][0]
    return _run


def test_le_rapport_est_montre_tel_quel(run):
    affiche, _ = run(RAPPORT)

    assert "tri par insertion" in affiche
    assert "[2, 5, 9]" in affiche


def test_la_plomberie_ne_saffiche_pas(run):
    """`[SPECIALIST-TRACE]`, `cwd:`, `files:` — n'était retiré qu'à la relecture."""
    affiche, _ = run(RAPPORT)

    assert "SPECIALIST-TRACE" not in affiche
    assert "cwd:" not in affiche


def test_lorchestrateur_na_plus_le_rapport_a_recrire(run):
    _, message = run(RAPPORT)

    assert "tri par insertion" not in message.content
    assert "[2, 5, 9]" not in message.content


def test_lorchestrateur_sait_quels_fichiers_ont_bouge(run):
    """Ce qu'il lui faut pour enchaîner — « puis envoie-le par mail »."""
    _, message = run(RAPPORT)

    assert "/tmp/axon-essai/tri.py" in message.content


def test_il_lui_est_dit_de_ne_pas_ecrire_de_code(run):
    _, message = run(RAPPORT)

    assert "n'écris aucun" in message.content


def test_un_rapport_vide_nest_pas_maquille_en_succes(run):
    affiche, message = run("")

    assert affiche == ""
    assert "rien produit" in message.content


def test_la_note_est_marquee_interne(run):
    """Sans quoi la relecture du thread la rejoue avec le chevron, comme si
    l'utilisateur l'avait tapée — plomberie et consignes comprises."""
    _, message = run(RAPPORT)

    assert est_interne(message)


def test_un_vrai_tour_dutilisateur_nest_pas_marque():
    from langchain_core.messages import HumanMessage

    assert not est_interne(HumanMessage("écris un script tri.py"))


def test_la_relecture_ne_rejoue_pas_les_notes_internes():
    from src.orchestrator.note_interne import note
    from src.infra.checkpoint import _text_of  # noqa: F401 — garde l'import stable

    interne = note("L'agent de code a terminé.")
    messages = [{"role": "human", "content": "écris tri.py", "interne": False},
                {"role": "human", "content": interne.content, "interne": True}]

    visible = [m for m in messages if not m.get("interne")]

    assert [m["content"] for m in visible] == ["écris tri.py"]


# ── quand le modèle ne conclut pas ────────────────────────────────────────────
# Le sous-graphe rend « la trace + le texte du DERNIER `AIMessage` ». Ce dernier
# message porte souvent des appels d'outils — un `shell_run` de vérification — et
# son texte est alors VIDE. Vécu : tri.py écrit, relu, exécuté deux fois avec
# succès (`1 2 5 9`, `apple banana cherry`), et pour toute conclusion « L'agent de
# code n'a rien produit ». Le travail avait eu lieu ; c'est le récit qui manquait.
TRACE_SEULE = ("[SPECIALIST-TRACE]\ncwd:/home/kaine\nfiles:/tmp/axon-essai/tri.py\n"
               "plan:✓Créer tri.py|○Tester le script\n[/SPECIALIST-TRACE]\n")


def test_un_travail_sans_conclusion_nest_pas_annonce_comme_rien(run):
    affiche, message = run(TRACE_SEULE)

    assert "rien produit" not in message.content
    assert "/tmp/axon-essai/tri.py" in affiche


def test_le_repli_dit_ou_en_est_le_plan(run):
    affiche, _ = run(TRACE_SEULE)

    assert "1 étape(s) du plan sur 2" in affiche
    assert "Tester le script" in affiche


def test_le_repli_annonce_quil_est_un_repli(run):
    """Sans ça, l'utilisateur croit que l'agent s'est contenté de ça."""
    affiche, _ = run(TRACE_SEULE)

    assert "n'a pas rédigé de conclusion" in affiche


def test_une_vraie_conclusion_nest_pas_remplacee(run):
    affiche, _ = run(TRACE_SEULE + "Le script trie par insertion et je l'ai exécuté.")

    assert affiche == "Le script trie par insertion et je l'ai exécuté."


def test_rien_du_tout_reste_rien_du_tout(run):
    """Le repli ne doit pas maquiller une vraie absence de travail en succès."""
    affiche, message = run("[SPECIALIST-TRACE]\ncwd:/home/kaine\n[/SPECIALIST-TRACE]\n")

    assert affiche == ""
    assert "rien produit" in message.content
