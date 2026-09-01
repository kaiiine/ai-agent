"""Une confirmation destructive doit dire OÙ, pas seulement QUOI.

Vécu, sur « place-toi dans /tmp/axon-essai et supprime tout ce qu'il contient » :

    Commande DESTRUCTIVE :
    rm -rf ./*
      ▶ Non, annuler / Oui, exécuter

`./` n'est écrit nulle part. Le même écran vaut pour un dossier d'essai et pour
la racine d'un projet — on ne peut pas accorder ce qu'on ne voit pas. Le
répertoire est résolu au moment du blocage, donc il décrit l'exécution qui
suivrait, pas celle qu'on imagine.

Il n'est montré que sur un chemin RELATIF : sur `rm -rf /tmp/x`, il n'apprend
rien et allongerait la question pour rien.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest
from langchain_core.messages import ToolMessage

from src.agents.shell.tools import set_cwd, shell_run
from src.orchestrator import confirmation


@pytest.fixture
def bloque(monkeypatch):
    """Rend l'intitulé de la question posée pour une commande donnée."""
    def _bloque(commande: str, dans: str | None = None):
        if dans:
            set_cwd(dans)
        resultat = shell_run.invoke({"command": commande})
        assert resultat["status"] == "requires_confirmation", resultat
        charge = confirmation._charge(ToolMessage(
            content=json.dumps(resultat), tool_call_id="s1", name="shell_run"))
        return confirmation._libelle(charge, charge["command"])
    return _bloque


def test_un_chemin_relatif_est_resolu_dans_la_commande(bloque):
    """La commande MONTRÉE est celle qui partira — pas une forme qui dépend
    encore d'un répertoire courant, lequel peut changer entre la question et la
    réponse."""
    dossier = tempfile.mkdtemp()

    libelle = bloque("rm -rf ./*", dans=dossier)

    assert f"rm -rf {dossier}/*" in libelle
    assert "./*" not in libelle


def test_un_chemin_absolu_nalourdit_pas_la_question(bloque):
    libelle = bloque("rm -rf /tmp/axon-essai/*")

    assert "rm -rf /tmp/axon-essai/*" in libelle
    assert "dans" not in libelle


def test_le_motif_reste_annonce(bloque):
    assert "DESTRUCTIVE" in bloque("rm -rf ./*", dans=tempfile.mkdtemp())


@pytest.mark.parametrize("commande, relatif", [
    ("rm -rf ./*", True),
    ("rm -rf x/", True),
    ("rm -rf /tmp/x", False),
    ("rm -rf ~/x", False),
    ("rm -rf -f /tmp/x", False),        # les options ne comptent pas
])
def test_ce_qui_compte_comme_relatif(commande, relatif):
    assert confirmation._porte_un_chemin_relatif(commande) is relatif


# ── l'alias `cmd` ─────────────────────────────────────────────────────────────
# Les modèles écrivent `cmd` au moins aussi souvent que `command`. L'appel
# échouait, le modèle réessayait avec l'autre nom, et ça marchait : deux appels
# pour un, plus une ligne rouge. Relevé trois fois sur une seule demande.
def test_les_deux_noms_darguments_marchent():
    for cle in ("command", "cmd"):
        resultat = shell_run.invoke({cle: "echo bonjour"})
        assert "bonjour" in (resultat.get("stdout") or ""), cle


def test_le_schema_enseigne_toujours_command():
    """L'alias rattrape ; il n'enseigne pas. Annoncer les deux noms inviterait le
    modèle à choisir, et à propager celui qui n'est pas le nôtre."""
    champs = shell_run.args_schema.model_json_schema()["properties"]

    assert "command" in champs
    assert "cmd" not in champs


def test_le_prompt_demande_des_chemins_absolus():
    from src.llm.prompts import orchestrateur

    source = Path(orchestrateur.__file__).read_text(encoding="utf-8")

    assert "Destructive commands take ABSOLUTE paths" in source


# ── la réécriture en absolu ───────────────────────────────────────────────────
from src.agents.shell.chemins_absolus import absolutiser


@pytest.mark.parametrize("commande, attendu", [
    ("rm -rf ./*",            "rm -rf /base/*"),
    ("rm -rf x/",             "rm -rf /base/x/"),
    ("rm -rf .[!.]* ..?*",    "rm -rf /base/.[!.]* /base/..?*"),
    ("rm -rf a b",            "rm -rf /base/a /base/b"),
    ("rm -rf /tmp/x",         "rm -rf /tmp/x"),          # déjà situé
    ("rm -rf ~/x",            "rm -rf ~/x"),             # le shell résout ~
])
def test_les_chemins_deviennent_absolus(commande, attendu):
    assert absolutiser(commande, "/base") == attendu


def test_un_nom_avec_une_espace_reste_un_seul_chemin():
    """Sans guillemets, « mon dossier » deviendrait DEUX chemins — et la
    correction supprimerait plus que ce qu'on lui demande."""
    assert absolutiser('rm -rf "mon dossier"', "/base") == "rm -rf '/base/mon dossier'"


def test_un_glob_reste_nu():
    """Quoté, le shell ne l'étend plus et la commande ne désigne rien."""
    assert "'" not in absolutiser("rm -rf ./*", "/base")


@pytest.mark.parametrize("commande", [
    "rm -rf ./* && echo ok",        # enchaînée : chaque morceau peut tourner ailleurs
    "rm -rf ./* | tee log",
    "git reset --hard HEAD~1",      # l'argument est une référence, pas un chemin
    "git push --force origin main",
    "rm -rf l'ete",                 # guillemet non fermé : on ne devine pas
])
def test_ce_quon_ne_reecrit_pas(commande):
    assert absolutiser(commande, "/base") == commande


def test_la_reecriture_est_idempotente():
    """L'appel est rejoué après l'accord : une seconde passe ne doit rien ajouter."""
    une = absolutiser("rm -rf ./*", "/base")

    assert absolutiser(une, "/base") == une


# ── de bout en bout : ce qui est accordé est ce qui est supprimé ──────────────
def test_seul_le_dossier_vise_est_vide(monkeypatch):
    import json as _json

    from langchain_core.messages import ToolMessage

    from src.orchestrator import confirmation as conf

    racine = Path(tempfile.mkdtemp())
    essai = racine / "axon-essai"
    essai.mkdir()
    (essai / "a.txt").write_text("a")
    voisin = racine / "NE-PAS-TOUCHER.txt"
    voisin.write_text("intact")

    set_cwd(str(essai))
    bloque = shell_run.invoke({"command": "rm -rf ./*"})
    monkeypatch.setattr(conf, "demander", lambda d: ["Oui, exécuter", ""])
    suite = conf.confirmer({"messages": [ToolMessage(
        content=_json.dumps(bloque), tool_call_id="s1", name="shell_run")]})
    appel = suite["messages"][0].tool_calls[0]

    assert appel["args"]["command"] == bloque["command"], "accordé ≠ exécuté"
    shell_run.invoke(appel["args"])

    assert not (essai / "a.txt").exists()
    assert voisin.read_text() == "intact"
