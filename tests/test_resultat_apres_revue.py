"""Un outil de proposition rend « en attente » et rien ne le met à jour.

Vécu : « crée un fichier x.py » a produit DEUX panneaux pour le même fichier, le
second avec un diff vide. Le modèle lisait deux affirmations contradictoires —
son propre résultat d'outil disant `awaiting_confirmation: true`, et une note
humaine disant « 1 fichier écrit ». Il croit son outil.

Le chemin du specialist corrigeait déjà le résultat (`_progress_cb` rend
« accepted ») ; l'orchestrateur le laissait mentir.
"""
from __future__ import annotations

import json

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from src.orchestrator.revision import _corriger_les_resultats


def _propose(id_msg: str = "m1", outil: str = "propose_file_change") -> ToolMessage:
    return ToolMessage(
        content=json.dumps({"status": "proposed", "path": "/tmp/x.py",
                            "awaiting_confirmation": True}),
        tool_call_id="w1", name=outil, id=id_msg)


def test_le_resultat_dit_ce_qui_a_eu_lieu():
    corriges = _corriger_les_resultats([_propose()], "applied")

    assert len(corriges) == 1
    charge = json.loads(corriges[0].content)
    assert charge["status"] == "applied"
    assert "awaiting_confirmation" not in charge


def test_le_refus_est_dit_aussi():
    charge = json.loads(_corriger_les_resultats([_propose()], "rejected")[0].content)
    assert charge["status"] == "rejected"


def test_la_correction_remplace_au_lieu_dempiler():
    """`add_messages` remplace un message de même `id` : garder l'identifiant
    réécrit sur place, sinon le transcript porte les deux versions."""
    origine = _propose(id_msg="abc")
    assert _corriger_les_resultats([origine], "applied")[0].id == "abc"


def test_seuls_les_outils_de_proposition_sont_touches():
    autre = ToolMessage(content=json.dumps({"status": "ok", "stdout": "hello"}),
                        tool_call_id="t1", name="shell_run", id="m2")
    assert _corriger_les_resultats([autre], "applied") == []


def test_un_resultat_deja_conclu_nest_pas_retouche():
    conclu = ToolMessage(content=json.dumps({"status": "applied", "path": "/tmp/x.py"}),
                         tool_call_id="w1", name="propose_file_change", id="m3")
    assert _corriger_les_resultats([conclu], "applied") == []


def test_un_contenu_illisible_ne_casse_rien():
    casse = ToolMessage(content="awaiting_confirmation mais pas du json",
                        tool_call_id="w1", name="propose_file_change", id="m4")
    assert _corriger_les_resultats([casse, AIMessage("x"), HumanMessage("y")],
                                   "applied") == []


def test_le_recit_suit_le_statut():
    """`_coding_progress` écrit « Proposition enregistrée. L'utilisateur la relira
    avant écriture ». Laissé tel quel après la revue, l'objet disait à la fois
    « appliqué » et « on va te la relire » — et le modèle reproposait."""
    origine = ToolMessage(
        content=json.dumps({"status": "proposed", "path": "/tmp/x.py",
                            "awaiting_confirmation": True,
                            "message": "Proposition enregistrée. L'utilisateur la relira."}),
        tool_call_id="w1", name="propose_file_change", id="m1")

    charge = json.loads(_corriger_les_resultats([origine], "applied")[0].content)
    assert charge["status"] == "applied"
    assert "relira" not in charge["message"]
    assert "écrit sur le disque" in charge["message"]


def test_reproposer_le_contenu_deja_sur_le_disque_est_refuse(tmp_path):
    """Un panneau de revue au diff VIDE — vécu deux fois de suite, à la fin d'une
    boucle où le modèle ne savait plus si son fichier avait été écrit."""
    from src.agents.coding.pending import pending_changes
    from src.agents.coding.tools import propose_file_change

    cible = tmp_path / "tri.py"
    cible.write_text("print(1)\n", encoding="utf-8")
    pending_changes.clear()

    reponse = propose_file_change.invoke({"path": str(cible), "content": "print(1)\n"})

    assert reponse["status"] == "unchanged"
    assert not pending_changes.items, "rien ne doit partir en revue"

    autre = propose_file_change.invoke({"path": str(cible), "content": "print(2)\n"})
    pending_changes.clear()
    assert autre["status"] == "proposed", "un vrai changement passe toujours"


def test_la_note_de_precision_interdit_de_recommencer(tmp_path, monkeypatch):
    """« ajoute des commentaires » faisait replanifier : le modèle allait vérifier
    le disque, n'y trouvait rien — normal, aucune application n'avait eu lieu —
    et repartait de l'analyse en jetant deux tours de raffinement.

    Replanifier reste permis ailleurs, quand un vrai obstacle apparaît."""
    from src.agents.coding.pending import FileChange, pending_changes
    from src.orchestrator import revision

    pending_changes.clear()
    pending_changes.add(FileChange(path=str(tmp_path / "tri.py"), original="",
                                   proposed="print(1)\n", description="création"))
    monkeypatch.setattr(revision, "demander",
                        lambda demande: ["Préciser", "ajoute des commentaires"])

    note = revision.reviser({"messages": []})["messages"][-1].content
    pending_changes.clear()

    assert "ajoute des commentaires" in note
    for consigne in ("RIEN n'a été écrit", "replanifie", "revérifie pas le disque",
                     "Tu as déjà le contenu"):
        assert consigne in note, consigne
