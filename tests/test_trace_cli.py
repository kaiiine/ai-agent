"""`axon trace` : les trois vues rendent, et la commande est bien câblée.

Un journal que personne ne sait relire ne remplace pas la mesure manuelle, il
s'y ajoute. Ces tests vérifient que chaque vue produit le chiffre pour lequel
elle existe — en particulier le taux de rattrapage au catalogue, que `graph.py`
réclamait en commentaire et qui décidera du resserrement de la sélection.
"""

from pathlib import Path

import pytest

from src.infra import trace, trace_cli


@pytest.fixture
def journal(tmp_path, monkeypatch):
    """Une trace synthétique : deux tours, dont un avec rattrapage et refus."""
    chemin = tmp_path / "decisions.jsonl"
    monkeypatch.setattr(trace, "FICHIER", chemin)

    trace.nouveau_run("tui")
    trace.inscrire(trace.Action(
        genre=trace.ROUTE, intent="supprime le fichier b.txt",
        groupes=(("filesystem", 1), ("coding", 2)),
        outils_lies=("local_read_file", "propose_file_delete"),
        backend="groq"), fichier=chemin)
    trace.inscrire(trace.Action(
        genre=trace.APPEL_LLM, resultat=trace.OK, backend="groq",
        modele="gpt-oss-20b", tokens_entree=12_731, tokens_sortie=90,
        latence_ms=1_200), fichier=chemin)
    trace.inscrire(trace.Action(
        genre=trace.OUTIL, outil="shell_run", cible="rm b.txt",
        policy=trace.REFUSE, resultat=trace.BLOQUE, erreur="blocked"),
        fichier=chemin)

    trace.nouveau_run("cron")
    trace.inscrire(trace.Action(
        genre=trace.ROUTE, intent="les cotes du jour",
        groupes=(("quant", 1),), outils_lies=("winamax_odds_fetch",),
        backend="gemini"), fichier=chemin)
    trace.inscrire(trace.Action(
        genre=trace.RATTRAPAGE, intent="les cotes du jour",
        outil="ev_analyze"), fichier=chemin)
    trace.inscrire(trace.Action(
        genre=trace.OUTIL, outil="winamax_odds_fetch", resultat=trace.OK,
        policy=trace.AUTORISE, latence_ms=800,
        verification=trace.NON_VERIFIE), fichier=chemin)
    return chemin


def _sortie(capsys) -> str:
    return capsys.readouterr().out


def test_la_vue_par_defaut_montre_les_deux_tours(journal, capsys):
    assert trace_cli.main([]) == 0
    ecran = _sortie(capsys)
    assert "supprime le fichier b.txt" in ecran
    assert "les cotes du jour" in ecran
    assert "shell_run" in ecran


def test_la_vue_route_donne_le_taux_de_rattrapage(journal, capsys):
    """LE chiffre qui dira jusqu'où la sélection peut être resserrée."""
    assert trace_cli.main(["--route"]) == 0
    ecran = _sortie(capsys)
    assert "filesystem" in ecran and "quant" in ecran
    # Un tour sur deux a eu besoin du filet.
    assert "1 réclamation(s) sur 1 tour(s) — 50 % des tours" in ecran
    assert "ev_analyze×1" in ecran
    assert "2 tour(s)" in ecran


def test_la_vue_outils_compte_les_refus_et_la_couverture(journal, capsys):
    assert trace_cli.main(["--outils"]) == 0
    ecran = _sortie(capsys)
    assert "shell_run" in ecran and "winamax_odds_fetch" in ecran
    # Aucune des deux actions n'a de contrôle déterministe : c'est le trou de
    # VERIFY, et il doit se compter au lieu de se deviner.
    assert "vérifié : 0 action(s) sur 2" in ecran


def test_une_tache_planifiee_n_est_pas_comptee_comme_un_outil(journal, capsys):
    """Son identifiant n'est pas un nom d'outil : mélanger les deux rendrait la
    colonne illisible pour les deux."""
    trace.nouveau_run("cron")
    trace.inscrire(trace.Action(genre=trace.TACHE, outil="3f2a",
                                cible="veille Bitcoin", resultat=trace.ERREUR),
                   fichier=journal)
    assert trace_cli.main(["--outils"]) == 0
    ecran = _sortie(capsys)
    assert "tâches planifiées : 1 exécution(s), 1 en erreur" in ecran
    assert "3f2a" not in ecran.split("tâches planifiées")[0]


def test_un_fichier_casse_ne_s_affiche_pas_en_ok(journal, capsys):
    """Peindre en vert ce qui n'a pas eu lieu — le défaut qu'un commit entier a
    corrigé ailleurs. L'écriture a réussi ET le fichier ne tient pas debout."""
    trace.nouveau_run("tui")
    trace.inscrire(trace.Action(
        genre=trace.VERIFICATION, outil="revision", cible="/tmp/tri.py",
        resultat=trace.OK, verification="casse"), fichier=journal)
    assert trace_cli.main([]) == 0
    ligne = [l for l in _sortie(capsys).splitlines() if "tri.py" in l][0]
    assert "casse" in ligne
    assert " ok " not in ligne


def test_la_vue_llm_montre_le_pic_de_tokens(journal, capsys):
    assert trace_cli.main(["--llm"]) == 0
    ecran = _sortie(capsys)
    assert "groq" in ecran
    assert "12 731" in ecran


def test_le_filtre_par_source_isole_le_chemin_sans_temoin(journal, capsys):
    assert trace_cli.main(["--source", "cron"]) == 0
    ecran = _sortie(capsys)
    assert "les cotes du jour" in ecran
    assert "supprime le fichier b.txt" not in ecran


def test_un_run_precis_se_retrouve_par_son_prefixe(journal, capsys):
    run = trace.lire()[0]["run_id"]
    assert trace_cli.main([run[:6]]) == 0
    assert "supprime le fichier b.txt" in _sortie(capsys)


def test_un_run_inconnu_rend_un_code_d_erreur(journal, capsys):
    assert trace_cli.main(["zzzzzz"]) == 1
    assert "aucun run" in _sortie(capsys)


def test_une_trace_vide_le_dit_et_rappelle_l_interrupteur(tmp_path, monkeypatch,
                                                          capsys):
    """Une trace vide vient presque toujours d'un `AXON_TRACE=0` oublié."""
    monkeypatch.setattr(trace, "FICHIER", tmp_path / "rien.jsonl")
    assert trace_cli.main([]) == 0
    assert "AXON_TRACE=0" in _sortie(capsys)


def test_la_commande_est_cablee_dans_le_point_d_entree():
    """Câblée AVANT le boot loader : relire un journal n'a besoin ni du loader
    ni du graphe, et les charger coûterait des secondes pour lire un fichier."""
    source = (Path(__file__).resolve().parents[1] / "src" / "ui" / "main.py"
              ).read_text(encoding="utf-8")
    assert '"trace"' in source
    assert "from src.infra.trace_cli import main" in source
    assert source.index("from src.infra.trace_cli import main") < source.index(
        "from src.ui.boot import BootLoader")
