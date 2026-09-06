"""La trace de décision : ce qu'elle écrit, et ce qu'elle refuse de casser.

Deux propriétés priment sur le contenu, parce qu'un journal qui les perd devient
nuisible : il ne doit RIEN faire à l'import (DETTE-001 : quatre tests écrivaient
sous `~/` à cause d'imports à effet de bord), et il ne doit JAMAIS lever — un
journal qui casse le tour qu'il observe est le défaut qu'on cherche à voir.
"""

import json
import subprocess
import sys
from pathlib import Path

from src.infra import trace


def _fichier(tmp_path) -> Path:
    return tmp_path / "decisions.jsonl"


def _lignes(chemin: Path) -> list[dict]:
    return [json.loads(l) for l in chemin.read_text(encoding="utf-8").splitlines() if l]


# ── Les deux propriétés non négociables ──────────────────────────────────────
def test_l_import_ne_touche_pas_le_disque(tmp_path):
    """Importer le module ne crée rien, même pas `~/.axon`.

    Mesuré comme dans docs/dette.md : `HOME` détourné vers un répertoire vide,
    import dans un processus neuf, puis inventaire.
    """
    maison = tmp_path / "maison"
    maison.mkdir()
    racine = Path(__file__).resolve().parents[1]
    sortie = subprocess.run(
        [sys.executable, "-c",
         "from src.infra import trace, alerte, langfuse_export; print('ok')"],
        cwd=racine, env={"HOME": str(maison), "PATH": "/usr/bin:/bin",
                         "PYTHONPATH": str(racine)},
        capture_output=True, text=True, timeout=120)
    assert sortie.returncode == 0, sortie.stderr
    assert list(maison.iterdir()) == [], f"l'import a créé {list(maison.iterdir())}"


def test_inscrire_ne_leve_jamais(tmp_path):
    """Un chemin impossible à écrire ne doit pas remonter jusqu'à l'appelant."""
    trace.nouveau_run("test")
    impossible = tmp_path / "fichier"
    impossible.write_text("je ne suis pas un dossier")
    # `impossible/decisions.jsonl` ne peut pas exister : le parent est un fichier.
    trace.inscrire(trace.Action(genre=trace.OUTIL, outil="x"),
                   fichier=impossible / "decisions.jsonl")


# ── Regroupement ─────────────────────────────────────────────────────────────
def test_un_run_regroupe_ses_actions(tmp_path):
    chemin = _fichier(tmp_path)
    run = trace.nouveau_run("tui")
    for nom in ("a", "b", "c"):
        trace.inscrire(trace.Action(genre=trace.OUTIL, outil=nom), fichier=chemin)

    lignes = _lignes(chemin)
    assert [l["run_id"] for l in lignes] == [run] * 3
    assert [l["seq"] for l in lignes] == [1, 2, 3]
    assert {l["source"] for l in lignes} == {"tui"}


def test_un_nouveau_run_repart_a_un(tmp_path):
    chemin = _fichier(tmp_path)
    trace.nouveau_run("tui")
    trace.inscrire(trace.Action(genre=trace.OUTIL, outil="a"), fichier=chemin)
    second = trace.nouveau_run("cron")
    trace.inscrire(trace.Action(genre=trace.OUTIL, outil="b"), fichier=chemin)

    lignes = _lignes(chemin)
    assert lignes[1]["run_id"] == second and lignes[1]["seq"] == 1
    assert lignes[0]["run_id"] != lignes[1]["run_id"]
    # La source distingue le chemin sans témoin de celui de la conversation.
    assert lignes[1]["source"] == "cron"


def test_par_run_ordonne_et_ne_fond_pas_les_orphelines():
    lignes = [
        {"run_id": "b", "seq": 2}, {"run_id": "a", "seq": 1},
        {"run_id": "b", "seq": 1}, {"run_id": "", "seq": 1},
    ]
    groupes = trace.par_run(lignes)
    assert [l["run_id"] for l in groupes[0]] == ["b", "b"], "le run vu en premier"
    assert [l["seq"] for l in groupes[0]] == [1, 2], "trié par seq"
    assert groupes[-1][0]["run_id"] == "", "les orphelines restent à part"
    assert len(groupes) == 3


# ── Rotation et relecture ────────────────────────────────────────────────────
def test_la_rotation_garde_la_generation_precedente(tmp_path, monkeypatch):
    """Au plafond on FAIT TOURNER, on n'efface pas.

    `failure_log` efface — un journal de diagnostic peut oublier. Un substrat de
    mesure qui efface son historique ne peut plus comparer un avant à un après,
    ce qui est sa seule raison d'être.
    """
    chemin = _fichier(tmp_path)
    trace.nouveau_run("tui")
    # Trois lignes sous un plafond hors d'atteinte, puis un plafond juste
    # au-dessous : la rotation se produit UNE fois, ce qui est la propriété à
    # vérifier. Un plafond minuscule en ferait des dizaines et ne dirait rien
    # d'autre que « deux générations », qui est déjà dans le nom.
    for i in range(3):
        trace.inscrire(trace.Action(genre=trace.OUTIL, outil=f"outil{i}"),
                       fichier=chemin)
    monkeypatch.setattr(trace, "_MAX_OCTETS", chemin.stat().st_size - 1)
    trace.inscrire(trace.Action(genre=trace.OUTIL, outil="outil3"), fichier=chemin)

    assert chemin.with_suffix(chemin.suffix + ".1").is_file(), "pas de rotation"
    noms = [l["outil"] for l in trace.lire(fichier=chemin)]
    assert noms == ["outil0", "outil1", "outil2", "outil3"], (
        "l'historique doit survivre à une rotation, et rester chronologique")


def test_une_ligne_tronquee_n_emporte_pas_les_autres(tmp_path):
    """Un processus tué en plein write laisse une ligne coupée."""
    chemin = _fichier(tmp_path)
    trace.nouveau_run("tui")
    trace.inscrire(trace.Action(genre=trace.OUTIL, outil="entier"), fichier=chemin)
    with chemin.open("a", encoding="utf-8") as fh:
        fh.write('{"run_id": "abc", "seq"\n')
    trace.inscrire(trace.Action(genre=trace.OUTIL, outil="suivant"), fichier=chemin)

    noms = [l["outil"] for l in trace.lire(fichier=chemin)]
    assert noms == ["entier", "suivant"]


def test_lire_limite_par_la_fin(tmp_path):
    chemin = _fichier(tmp_path)
    trace.nouveau_run("tui")
    for i in range(5):
        trace.inscrire(trace.Action(genre=trace.OUTIL, outil=str(i)), fichier=chemin)
    assert [l["outil"] for l in trace.lire(fichier=chemin, limite=2)] == ["3", "4"]


# ── Interrupteur ─────────────────────────────────────────────────────────────
def test_axon_trace_0_eteint_tout(tmp_path, monkeypatch):
    chemin = _fichier(tmp_path)
    monkeypatch.setenv("AXON_TRACE", "0")
    trace.nouveau_run("tui")
    trace.inscrire(trace.Action(genre=trace.OUTIL, outil="a"), fichier=chemin)
    assert not chemin.exists()


def test_allume_par_defaut(tmp_path, monkeypatch):
    """Éteinte par défaut, la trace serait toujours absente le jour où la
    question se pose."""
    monkeypatch.delenv("AXON_TRACE", raising=False)
    assert trace.actif()


# ── Schéma ───────────────────────────────────────────────────────────────────
def test_les_tuples_survivent_au_json(tmp_path):
    """Les groupes sont écrits en paires lisibles, pas en objets Python."""
    chemin = _fichier(tmp_path)
    trace.nouveau_run("tui")
    trace.inscrire(trace.Action(
        genre=trace.ROUTE, intent="quels sont mes rendez-vous",
        groupes=(("calendar", 1), ("memory", 3)),
        outils_lies=("calendar_list_events",)), fichier=chemin)

    ligne = _lignes(chemin)[0]
    assert ligne["groupes"] == [["calendar", 1], ["memory", 3]]
    assert ligne["outils_lies"] == ["calendar_list_events"]
    assert ligne["intent"] == "quels sont mes rendez-vous"


def test_une_ligne_sans_run_est_ecrite_quand_meme(tmp_path, monkeypatch):
    """Perdre une action parce que personne n'a ouvert de run serait un trou
    silencieux — la classe de défaut que ce module traque."""
    chemin = _fichier(tmp_path)
    monkeypatch.setattr(trace, "_run", "")
    trace.inscrire(trace.Action(genre=trace.OUTIL, outil="orpheline"), fichier=chemin)
    assert _lignes(chemin)[0]["outil"] == "orpheline"


def test_la_source_vient_du_point_d_entree(tmp_path):
    """Le graphe ne sait pas qui le pilote.

    `graph.chatbot` est le même code pour le terminal, le serveur API et le
    serveur MCP : sans déclaration du point d'entrée, tout serait étiqueté `tui`
    et `axon trace --source` mélangerait deux chemins sur quatre.
    """
    chemin = _fichier(tmp_path)
    try:
        trace.declarer_source("api")
        trace.nouveau_run()
        trace.inscrire(trace.Action(genre=trace.OUTIL, outil="a"), fichier=chemin)
        assert _lignes(chemin)[0]["source"] == "api"

        # Une source explicite l'emporte : le démon la donne lui-même.
        trace.nouveau_run("cron")
        trace.inscrire(trace.Action(genre=trace.OUTIL, outil="b"), fichier=chemin)
        assert _lignes(chemin)[1]["source"] == "cron"
    finally:
        trace.declarer_source("tui")


def test_les_points_d_entree_declarent_bien_leur_source():
    """Une déclaration oubliée ne casse rien — elle ment, ce qui est pire."""
    racine = Path(__file__).resolve().parents[1]
    for fichier, source in (("src/api_server.py", "api"),
                            ("src/mcp_server.py", "mcp")):
        contenu = (racine / fichier).read_text(encoding="utf-8")
        assert f'declarer_source("{source}")' in contenu, fichier
