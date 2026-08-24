"""Le journal d'actions : une action, une ligne, et rien qui s'empile.

L'affichage conversationnel n'annonçait qu'un `thinking` générique, réaffiché en
boucle. Le modèle retenu sépare deux choses que l'ancien confondait :

    l'action EN COURS   vit dans la zone Live, se redessine sur place,
                        ne laisse aucune trace en défilant
    l'action TERMINÉE   est imprimée une fois, au-dessus, et reste

C'est cette séparation qui supprime la répétition. Les tests ci-dessous la
vérifient sur la sortie réelle d'une console, pas sur l'intention.
"""
import io

import pytest
from rich.console import Console
from rich.live import Live
from rich.text import Text

from src.ui.journal import (
    Action, Etat, Journal, SortieDirecte, bilan, inscrire_resultat, verbe,
)


def _console() -> Console:
    return Console(file=io.StringIO(), width=100, force_terminal=True)


def _sortie(console: Console) -> str:
    return console.file.getvalue()


def _ecran(console: Console) -> str:
    """Ce qui reste VISIBLE — cf. tests/emulateur_terminal.py pour le pourquoi."""
    from tests.emulateur_terminal import _ecran as _e
    return _e(console)


# ── Une action, une ligne ─────────────────────────────────────────────────────
def test_une_action_terminee_est_imprimee_une_seule_fois():
    """Le cœur du correctif : ce qui est fini s'inscrit, et ne se repeint plus."""
    console = _console()
    with Live(Text(""), console=console, refresh_per_second=4):
        j = Journal(SortieDirecte(console))
        j.commencer("local_read_file", "src/app/page.tsx")
        for _ in range(10):
            j.avancer()                      # dix images d'animation
        j.terminer(reussi=True)

    assert _sortie(console).count("page.tsx") == 1


def test_l_action_en_cours_ne_laisse_aucune_trace():
    """Elle ne vit que dans la zone : si elle n'aboutit pas, rien ne reste."""
    console = _console()
    with Live(Text(""), console=console, refresh_per_second=4):
        j = Journal(SortieDirecte(console))
        j.commencer("web_research_report", "axon browser")
        for _ in range(5):
            j.avancer()

    assert "axon browser" not in _ecran(console)


def test_dix_actions_donnent_dix_lignes():
    console = _console()
    with Live(Text(""), console=console, refresh_per_second=4):
        j = Journal(SortieDirecte(console))
        for i in range(10):
            j.commencer("local_read_file", f"fichier-{i}.ts")
            j.terminer()

    sortie = _sortie(console)
    for i in range(10):
        assert sortie.count(f"fichier-{i}.ts") == 1


def test_l_attente_ne_s_empile_jamais():
    """Le symptôme d'origine : `thinking` imprimé à chaque image."""
    console = _console()
    with Live(Text(""), console=console, refresh_per_second=4):
        j = Journal(SortieDirecte(console), attente="réfléchit")
        for _ in range(20):
            j.avancer()

    assert _sortie(console).count("réfléchit") <= 1


# ── Ce qu'une ligne dit ───────────────────────────────────────────────────────
def test_le_nom_affiche_est_un_verbe_pas_un_outil():
    """C'est l'utilisateur qu'on informe, pas le développeur : « reading » se
    comprend sans savoir qu'il existe un `local_read_file`."""
    assert verbe("local_read_file") == "reading"
    assert verbe("web_research_report") == "searching"


def test_les_verbes_parlent_la_langue_de_l_attente():
    """L'attente générique s'appelle `thinking` : un verbe français à côté
    donnait deux langues sur deux lignes voisines. Le participe présent dit en
    plus l'action EN COURS, ce que la ligne vivante décrit."""
    from src.ui.journal import VERBES

    assert all(v.split()[0].endswith("ing") for v in VERBES.values()), VERBES


def test_un_outil_inconnu_garde_son_nom():
    """Mieux vaut un nom technique qu'une traduction inventée."""
    assert verbe("outil_jamais_vu") == "outil_jamais_vu"


def test_un_echec_montre_sa_raison():
    action = Action(nom="cherche", cible="axon", etat=Etat.ECHOUE,
                    detail="délai dépassé", fin=0.0, debut=0.0)

    rendu = action.rendu().plain
    assert "✗" in rendu and "délai dépassé" in rendu


def test_une_cible_trop_longue_est_coupee_par_le_debut():
    """La FIN d'un chemin l'identifie ; son préfixe est commun à tout le projet."""
    long = "/home/kaine/Documents/projets-perso/axon-landing/src/components/sections/Hero.tsx"
    action = Action(nom="lit", cible=long, etat=Etat.REUSSI, fin=0.0, debut=0.0)

    rendu = action.rendu().plain
    assert "Hero.tsx" in rendu
    assert "/home/kaine/Documents" not in rendu


@pytest.mark.parametrize("duree, attendu", [(0.05, False), (3.0, True)])
def test_la_duree_ne_s_affiche_qu_au_dela_du_seuil(duree, attendu):
    """Écrire « 0.0s » sur chaque lecture remplirait la colonne sans rien
    apprendre : presque toutes les actions locales sont instantanées."""
    action = Action(nom="lit", cible="x.ts", etat=Etat.REUSSI,
                    debut=0.0, fin=duree)

    assert ("s" in action.rendu().plain.split("x.ts")[-1]) is attendu


# ── Enchaînement ──────────────────────────────────────────────────────────────
def test_commencer_ferme_l_action_precedente():
    """Deux actions vivantes ne s'affichent pas : laisser la première ouverte la
    figerait à l'écran dans un état faux."""
    console = _console()
    with Live(Text(""), console=console, refresh_per_second=4):
        j = Journal(SortieDirecte(console))
        j.commencer("local_read_file", "a.ts")
        j.commencer("shell_run", "pnpm build")

        assert len(j.actions) == 1
        assert j.actions[0].etat is Etat.REUSSI
        assert j.en_cours.nom == "running"


def test_terminer_sans_action_en_cours_ne_leve_pas():
    assert Journal().terminer() is None


def test_une_note_reste_a_l_ecran():
    """Une information n'est pas une action : elle n'a ni durée ni issue, mais
    elle doit persister."""
    console = _console()
    with Live(Text(""), console=console, refresh_per_second=4):
        Journal(SortieDirecte(console)).note("bascule de backend")

    assert "bascule de backend" in _sortie(console)


def test_attendre_efface_l_action_en_cours():
    j = Journal()
    j.commencer("local_read_file", "a.ts")
    j.attendre("compresse le contexte")

    assert j.en_cours is None


# ── Bilan ─────────────────────────────────────────────────────────────────────
def test_le_bilan_compte_les_echecs():
    j = Journal()
    for _ in range(3):
        j.commencer("shell_run", "x")
        j.terminer(reussi=True)
    j.commencer("web_research_report", "y")
    j.terminer(reussi=False, detail="429")

    assert j.resume() == "4 action(s) · 1 échec(s)"


def test_une_action_unique_ne_merite_pas_de_bilan():
    """Elle est déjà à l'écran juste au-dessus : la résumer serait du bruit."""
    j = Journal()
    j.commencer("local_read_file", "a.ts")
    j.terminer()

    assert bilan(j).plain == ""


def test_sans_action_le_resume_est_vide():
    assert Journal().resume() == ""


# ── Le journal ne dépend pas d'une sortie ─────────────────────────────────────
def test_le_journal_fonctionne_sans_sortie():
    """Il la REÇOIT, il ne la possède pas : c'est ce qui lui permet de servir la
    conversation comme un build, sans savoir lequel l'utilise."""
    j = Journal()
    j.commencer("local_read_file", "a.ts")
    j.terminer()

    assert len(j.actions) == 1


# ── Inscription d'un résultat d'outil ─────────────────────────────────────────
#
# Le flux de LangGraph ne livre pas « l'outil démarre » : quand un `ToolMessage`
# arrive, l'appel est terminé. `inscrire_resultat` ouvre et clôt dans le même
# geste — mais il doit rester juste si un appelant a DÉJÀ ouvert l'action.

class _Msg:
    def __init__(self, contenu):
        self.content = contenu


def test_un_resultat_donne_une_seule_ligne():
    console = _console()
    with Live(Text(""), console=console, refresh_per_second=4):
        j = Journal(SortieDirecte(console))
        inscrire_resultat(j, "local_read_file", _Msg("/projets/page.tsx"))

    assert _sortie(console).count("page.tsx") == 1


def test_une_action_deja_ouverte_n_est_pas_dedoublee():
    """Vu à l'écran avant correction : l'appelant annonçait le départ, puis le
    résultat, et DEUX lignes sortaient — la première close en « réussi » par
    `commencer`, la seconde par le résultat réel."""
    console = _console()
    with Live(Text(""), console=console, refresh_per_second=4):
        j = Journal(SortieDirecte(console))
        j.commencer("local_read_file", "")
        inscrire_resultat(j, "local_read_file", _Msg("/projets/page.tsx"))

    assert len(j.actions) == 1
    assert _sortie(console).count("reading") == 1


def test_un_outil_different_ferme_bien_le_precedent():
    """Le contrepoids : deux outils distincts restent deux lignes."""
    j = Journal()
    j.commencer("local_read_file", "")
    inscrire_resultat(j, "shell_run", _Msg("exit 0"))

    assert len(j.actions) == 2


@pytest.mark.parametrize("contenu", [
    '{"status": "error", "message": "429 quota dépassé"}',
    '{"status":"error"}',
    '{"status": "TOOL_ERROR", "message": "timeout"}',
])
def test_un_echec_d_outil_est_reconnu(contenu):
    """Un échec se dit, il ne se déduit pas d'un contenu vide. Deux formes
    existent : le `status: error` des outils d'Axon, et le `TOOL_ERROR` dont
    `resilience` enveloppe les exceptions."""
    j = Journal()
    inscrire_resultat(j, "web_research_report", _Msg(contenu))

    assert j.actions[0].etat is Etat.ECHOUE


def test_un_succes_reste_un_succes():
    j = Journal()
    inscrire_resultat(j, "shell_run", _Msg("exit 0"))

    assert j.actions[0].etat is Etat.REUSSI


def test_la_raison_d_un_echec_tient_sur_une_ligne():
    """Jamais la trace entière : elle noierait l'action elle-même."""
    j = Journal()
    inscrire_resultat(j, "shell_run",
                      _Msg('{"status": "error", "message": "boom\\nligne 2\\nligne 3"}'))

    assert j.actions[0].detail == "boom"


def test_une_url_de_resultat_devient_la_cible():
    j = Journal()
    inscrire_resultat(j, "google_docs_write",
                      _Msg("https://docs.google.com/document/d/abc/edit"))

    assert "docs.google.com" in j.actions[0].cible


def test_un_resultat_illisible_ne_leve_pas():
    """Un journal qui casse le tour qu'il raconte serait pire que pas de journal."""
    class Hostile:
        @property
        def content(self):
            raise RuntimeError("non")

    inscrire_resultat(Journal(), "shell_run", Hostile())


def test_sans_journal_l_inscription_est_sans_effet():
    inscrire_resultat(None, "shell_run", _Msg("exit 0"))
