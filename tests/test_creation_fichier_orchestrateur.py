"""Créer un fichier depuis l'orchestrateur était impossible par le chemin prévu.

Vécu, sur « crée un fichier /tmp/axon-essai/x.py avec un hello world » :

    shell_run            refuse `>`              → « utilise propose_file_change »
    edit_file            refuse un fichier absent → « utilise propose_file_change »
    propose_file_change  → « appelle d'abord dev_plan_create() »

Or `dev_plan_create` n'appartient qu'au specialist. Les trois messages d'erreur
désignaient une porte verrouillée, et le modèle a fini par contourner en shell.
C'est le défaut que `registry.py` documente déjà — « le message le dirigeait vers
une porte qui n'existait pas pour lui » — une couche plus bas.
"""
from __future__ import annotations

from src.agents.coding.pending import dev_plan, pending_changes
from src.agents.coding.tools import propose_file_change, propose_file_delete
from src.agents.shell.classification import est_connue_sure, est_destructive


def _proposer(chemin: str) -> dict:
    pending_changes.clear()
    try:
        return propose_file_change.invoke({"path": chemin, "content": "print(1)\n"})
    finally:
        pending_changes.clear()


def test_lorchestrateur_peut_proposer_un_fichier(tmp_path):
    """Hors specialist, aucun plan n'existe et aucun ne peut être créé."""
    assert not dev_plan.exige_un_plan
    assert _proposer(str(tmp_path / "x.py"))["status"] == "proposed"


def test_le_specialist_exige_un_plan_a_partir_du_DEUXIEME_fichier(tmp_path):
    """« écris un script qui trie une liste » produisait un plan de quatre étapes,
    sa validation, puis une explication — trois cérémonies avant la première ligne
    écrite, pour quinze lignes de Python. Un plan sert à tenir un travail qui se
    déroule ; un seul fichier ne se déroule pas."""
    dev_plan.clear()
    pending_changes.clear()
    with dev_plan.run_specialist():
        premier = propose_file_change.invoke(
            {"path": str(tmp_path / "a.py"), "content": "print(1)\n"})
        second = propose_file_change.invoke(
            {"path": str(tmp_path / "b.py"), "content": "print(2)\n"})
    pending_changes.clear()

    assert premier["status"] == "proposed"
    assert second["status"] == "error"
    assert "dev_plan_create" in second["error"]


def test_un_plan_declare_rouvre_les_fichiers_suivants(tmp_path):
    dev_plan.clear()
    pending_changes.clear()
    with dev_plan.run_specialist():
        propose_file_change.invoke({"path": str(tmp_path / "a.py"), "content": "x"})
        dev_plan.create(["écrire a", "écrire b"])
        second = propose_file_change.invoke(
            {"path": str(tmp_path / "b.py"), "content": "y"})
    pending_changes.clear()
    dev_plan.clear()

    assert second["status"] == "proposed"


def test_le_marqueur_est_rendu_meme_en_cas_derreur():
    dev_plan.exige_un_plan = False
    try:
        with dev_plan.run_specialist():
            raise RuntimeError("boum")
    except RuntimeError:
        pass
    assert not dev_plan.exige_un_plan


def test_la_description_est_derivee_quand_elle_manque(tmp_path):
    """Trois arguments requis pour écrire un fichier, c'est un appel malformé de
    plus à chaque tentative — et le nom du fichier renseigne déjà le libellé."""
    schema = propose_file_change.args_schema.model_json_schema()
    assert set(schema["required"]) == {"path", "content"}
    assert "création de" in _proposer(str(tmp_path / "neuf.py"))["description"]


# ── frottement sur le quotidien ───────────────────────────────────────────────
def test_creer_un_dossier_ne_pose_pas_de_question():
    """Un garde qu'on trouve pénible finit désactivé : `mkdir -p` ouvrait un
    questionnaire « commande non reconnue comme sûre »."""
    for commande in ("mkdir -p /tmp/axon-essai", "touch a.txt b.txt", "mktemp -d"):
        assert est_connue_sure(commande), commande
        assert not est_destructive(commande), commande


def test_creer_puis_detruire_reste_detecte():
    """Le laissez-passer ne doit pas s'étendre à ce qui suit."""
    for commande in ("mkdir -p /tmp/x && rm -rf /tmp/x",
                     "touch a && rm b",
                     "mkdir /tmp/x | rm -rf /tmp/y"):
        assert est_destructive(commande), commande
        assert not est_connue_sure(commande), commande


# ── la porte d'écriture ───────────────────────────────────────────────────────
def test_une_demande_de_modification_met_lecriture_a_portee():
    """`filesystem` mêle cinq lectures et deux écritures, et la similarité dense
    range TOUJOURS les lectures devant — `edit_file` sortait 7e sur 7, sur
    « commente ces deux lignes » comme sur « lis le fichier ». Tant qu'on prenait
    le groupe entier ça ne se voyait pas ; depuis le budget, l'écriture est coupée."""
    from src.orchestrator.registry import build_all_tools
    from src.orchestrator.tool_retriever import ToolRetriever

    retriever = ToolRetriever(build_all_tools())
    for requete in ("commente ces deux lignes dans ~/.config/hypr/keybindings.conf",
                    "change la valeur de timeout dans mon fichier de config",
                    "ajoute une ligne à mon .zshrc"):
        noms = {t.name for t in retriever.get(requete)}
        assert "edit_file" in noms, requete
        assert "propose_file_change" in noms, requete


def test_la_porte_decriture_ne_souvre_pas_sur_une_lecture():
    from src.orchestrator.tool_retriever import _ecriture_intent

    for requete in ("lis le fichier src/main.py",
                    "cherche le mot TODO dans le projet",
                    "liste les fichiers du dossier",
                    "commente ce que tu penses de ça"):
        assert not _ecriture_intent(requete), requete
