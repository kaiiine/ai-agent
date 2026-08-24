"""Un tour qui a agi doit dire ce qu'il a fait.

Reproche de l'utilisateur, et il est juste : « il ne me dit pas que c'est fait,
je ne sais pas s'il l'a fait au final ». Vécu sur une suppression de VM et
d'images Android — dix commandes, quatre en échec, puis :

    Le modèle n'a rien rédigé pour ce tour.

VirtualBox était-il supprimé ? Quelles images Android étaient parties ? Rien ne
le disait. Deux causes distinctes, corrigées séparément :

  1. le prompt n'exigeait NULLE PART de rendre compte APRÈS avoir agi. Le seul
     « confirm » portait sur l'AVANT d'une action destructive ;
  2. quand le modèle ne rédige rien, Axon renonçait aussi — alors que le journal
     sait exactement ce que les outils ont fait.

Le filet ne conclut pas à la place du modèle : il dit « le modèle n'a pas conclu »
puis énumère les faits. Sans cette précaution, « rien n'a échoué » se lirait comme
« tout est terminé », ce qui est précisément l'erreur qu'on corrige.
"""
from datetime import date

import pytest

from src.llm.prompts import build_system_prompt
from src.ui.journal import Journal, compte_rendu_de_secours


def _prompt(outils=("shell_run",)) -> str:
    return build_system_prompt(list(outils), date.today().isoformat(), "kaine", lang="fr")


def _journal_de_l_incident() -> Journal:
    """Le tour réel : VM supprimée, sdkmanager introuvable, une image effacée."""
    j = Journal()
    j.commencer("shell_run", "VBoxManage unregistervm nas --delete"); j.terminer(True)
    j.commencer("shell_run", "sdkmanager --list"); j.terminer(False, "commande introuvable")
    j.commencer("shell_run", "rm -rf ~/Android/Sdk/system-images/android-34"); j.terminer(True)
    return j


# ── La règle ──────────────────────────────────────────────────────────────────
def test_le_prompt_exige_de_conclure_apres_avoir_agi():
    p = _prompt()

    assert "CLOSING THE LOOP" in p
    assert "only your text tells them what happened" in p


def test_le_compte_rendu_est_proportionne_au_travail():
    """Première version trop mécanique : « il me reste combien de stockage ? »,
    un seul `df -h`, produisait « DONE – … / LEFT – Aucun autre besoin exprimé ».
    Un formulaire là où une phrase suffisait.

    Mesuré après correction, sur `gpt-oss:120b-cloud` : réponse d'une ligne 3/3,
    aucune étiquette 3/3 — « Il te reste environ 25 Go d'espace disponible ».
    """
    p = _prompt()

    assert "in PROPORTION to the work" in p
    assert "the answer IS the report" in p


def test_le_prompt_interdit_les_etiquettes_en_titre():
    """Elles sont des choses à transmettre, pas un formulaire à remplir."""
    p = _prompt()

    assert "Never print DONE / FAILED / LEFT as literal headings" in p


def test_rien_a_signaler_se_dit_en_se_taisant():
    """« Aucun autre besoin exprimé » est du bruit : l'absence de reste se
    signale en n'en parlant pas."""
    p = _prompt()

    assert "say nothing about it" in p


def test_le_prompt_distingue_l_echec_bloquant_du_contourne():
    """Nuance venue d'une mesure : sur une tâche où `sdkmanager` échoue mais où
    les suppressions aboutissent par un autre chemin, Gemini n'a pas mentionné
    l'échec — et il avait raison. Le but était atteint ; nommer le détour est du
    bruit. Seul un échec qui LAISSE QUELQUE CHOSE À FAIRE doit être dit."""
    p = _prompt()

    assert "LEFT SOMETHING UNDONE" in p
    assert "not worth a line" in p


def test_le_prompt_interdit_de_faire_passer_un_resultat_partiel_pour_fini():
    p = _prompt()

    assert "three out of five" in p


def test_le_prompt_exige_une_preuve_par_les_outils():
    """« Ton propre texte n'est pas une preuve » existait déjà côté specialist ;
    l'orchestrateur agit aussi, et n'avait pas la règle."""
    p = _prompt()

    assert "Your own text is not evidence" in p


def test_la_regle_est_inconditionnelle():
    """Elle vit dans `_CORE` : un tour peut agir avec n'importe quel outil."""
    nu = build_system_prompt([], date.today().isoformat(), "kaine", lang="fr")

    assert "CLOSING THE LOOP" in nu


# ── Le filet ──────────────────────────────────────────────────────────────────
def test_le_filet_dit_ce_qui_a_ete_fait():
    rendu = compte_rendu_de_secours(_journal_de_l_incident())

    assert "VBoxManage unregistervm nas --delete" in rendu
    assert "android-34" in rendu


def test_le_filet_dit_ce_qui_a_echoue_et_pourquoi():
    rendu = compte_rendu_de_secours(_journal_de_l_incident())

    assert "sdkmanager" in rendu
    assert "commande introuvable" in rendu


def test_le_filet_separe_le_fait_de_l_echoue():
    rendu = compte_rendu_de_secours(_journal_de_l_incident())

    assert rendu.index("**Fait**") < rendu.index("**Échoué**")


def test_le_filet_ne_conclut_pas_a_la_place_du_modele():
    """Le point qui compte : sans cette phrase, un compte rendu sans échec se
    lirait comme « c'est terminé » — alors qu'on n'en sait rien."""
    rendu = compte_rendu_de_secours(_journal_de_l_incident())

    assert "n'a pas conclu" in rendu
    assert "peut-être pas terminée" in rendu


def test_le_filet_compte_les_actions():
    rendu = compte_rendu_de_secours(_journal_de_l_incident())

    assert "3 action(s) · 1 échec(s)" in rendu


@pytest.mark.parametrize("journal", [None, Journal()])
def test_sans_action_le_filet_se_tait(journal):
    """Un tour qui n'a rien fait n'a rien à rapporter — le message générique
    d'origine reprend la main."""
    assert compte_rendu_de_secours(journal) == ""


def test_un_journal_sans_echec_reste_prudent():
    j = Journal()
    j.commencer("shell_run", "ls"); j.terminer(True)
    rendu = compte_rendu_de_secours(j)

    assert "**Échoué**" not in rendu
    assert "peut-être pas terminée" in rendu, "l'absence d'échec ne prouve pas la fin"


# ── Le branchement ────────────────────────────────────────────────────────────
def test_le_filet_remplace_le_message_generique():
    import inspect

    from src.ui.streaming import stream_once

    source = inspect.getsource(stream_once)

    assert "compte_rendu_de_secours(journal)" in source
    # Le message générique reste en dernier recours, quand rien n'a tourné.
    assert "n'a rien rédigé pour ce tour" in source
