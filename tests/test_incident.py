"""Le journal d'incidents — rang 2 de la boucle d'apprentissage.

Deux propriétés portent tout le reste : la capture est IDEMPOTENTE (sinon le
compte des récidives compterait des passes au lieu d'erreurs) et elle porte la
PORTÉE (sinon un fichier global mélange des leçons qui ne se transposent pas).
"""
from __future__ import annotations

from src.infra import incident, trace


def _ligne(**kw) -> dict:
    base = {"run_id": "r1", "seq": 1, "at": "2026-09-06T10:00:00+00:00",
            "source": "tui", "projet": "axon", "genre": "", "intent": "",
            "outil": "", "cible": "", "confirmation": "", "resultat": "",
            "erreur": "", "extra": {}}
    base.update(kw)
    return base


# ── Déduction ────────────────────────────────────────────────────────────────
def test_un_rattrapage_devient_un_incident_de_routing():
    lignes = [_ligne(genre=trace.RATTRAPAGE, outil="jira_create_issue",
                     intent="ouvre un ticket")]
    (inc,) = incident.depuis_la_trace(lignes)
    assert inc.categorie == incident.ROUTING
    assert inc.signal_source == incident.RATTRAPAGE
    assert inc.intention_reformulee == "ouvre un ticket"
    assert inc.correction == "lier jira_create_issue"


def test_un_refus_devient_un_incident_d_execution_avec_la_consigne():
    """C'est la seule fois où l'utilisateur DIT ce qu'il aurait fallu faire.

    Elle partait au modèle et nulle part ailleurs : le refus se comptait, sa
    raison mourait avec la session.
    """
    lignes = [_ligne(run_id="r1", seq=1, genre=trace.ROUTE, intent="trie ce fichier"),
              _ligne(run_id="r1", seq=2, genre=trace.VERIFICATION, cible="/p/tri.py",
                     confirmation="refus", resultat=trace.BLOQUE, erreur="preciser",
                     extra={"precision": "garde les type hints"})]
    incidents = incident.depuis_la_trace(lignes)
    assert len(incidents) == 1
    inc = incidents[0]
    assert inc.categorie == incident.EXECUTION
    assert inc.correction == "garde les type hints"
    assert inc.resultat_reel == "refusé avec consigne"
    # La demande d'origine est reportée depuis la ligne de route du même run :
    # sans elle, l'incident dirait CE qui a été refusé sans dire à quoi ça
    # répondait, et la relecture serait aveugle.
    assert inc.intention_reformulee == "trie ce fichier"


def test_un_refus_net_n_a_pas_de_correction():
    """Un incident sans correction ne deviendra jamais une règle. Écrit vide
    plutôt que comblé — c'est une information, pas un trou à boucher."""
    lignes = [_ligne(genre=trace.VERIFICATION, cible="/p/tri.py",
                     confirmation="refus", resultat=trace.BLOQUE, erreur="refuser")]
    (inc,) = incident.depuis_la_trace(lignes)
    assert inc.correction == ""
    assert inc.resultat_reel == "refusé"


def test_une_ligne_ordinaire_ne_produit_aucun_incident():
    lignes = [_ligne(genre=trace.ROUTE, intent="salut"),
              _ligne(genre=trace.OUTIL, outil="get_weather", resultat=trace.OK),
              _ligne(genre=trace.APPEL_LLM, resultat=trace.OK)]
    assert incident.depuis_la_trace(lignes) == []


def test_le_contrat_d_etat_reste_vide_et_present():
    """Le niveau 1 du contrat n'existe pas encore. La colonne est écrite vide
    plutôt qu'omise, pour que le trou se compte au lieu de se deviner."""
    (inc,) = incident.depuis_la_trace([_ligne(genre=trace.RATTRAPAGE, outil="x")])
    assert inc.contrat_etat == ""


# ── Portée ───────────────────────────────────────────────────────────────────
def test_l_incident_porte_le_projet_de_la_ligne():
    lignes = [_ligne(genre=trace.RATTRAPAGE, outil="x", projet="autre-repo")]
    assert incident.depuis_la_trace(lignes)[0].projet == "autre-repo"


def test_une_ligne_sans_projet_est_dite_hors_repo():
    lignes = [_ligne(genre=trace.RATTRAPAGE, outil="x", projet="")]
    assert incident.depuis_la_trace(lignes)[0].projet == trace.HORS_REPO


# ── Écriture et idempotence ──────────────────────────────────────────────────
def test_capturer_ecrit_puis_ne_redouble_pas(tmp_path):
    """Sans clé d'origine, une seconde passe réécrirait tout, et le compte des
    récidives compterait des passes au lieu d'erreurs."""
    fichier = tmp_path / "incidents.jsonl"
    lignes = [_ligne(genre=trace.RATTRAPAGE, outil="x", run_id="r1", seq=3)]

    premiers = incident.capturer(lignes, fichier=fichier)
    assert len(premiers) == 1
    assert len(incident.lire(fichier=fichier)) == 1

    seconds = incident.capturer(lignes, fichier=fichier)
    assert seconds == []
    assert len(incident.lire(fichier=fichier)) == 1


def test_capturer_n_ajoute_que_le_nouveau(tmp_path):
    fichier = tmp_path / "incidents.jsonl"
    premier = _ligne(genre=trace.RATTRAPAGE, outil="x", run_id="r1", seq=1)
    incident.capturer([premier], fichier=fichier)

    second = _ligne(genre=trace.RATTRAPAGE, outil="y", run_id="r2", seq=1)
    nouveaux = incident.capturer([premier, second], fichier=fichier)
    assert [i.correction for i in nouveaux] == ["lier y"]
    assert len(incident.lire(fichier=fichier)) == 2


def test_deux_lignes_du_meme_run_ont_des_origines_distinctes(tmp_path):
    """`seq` distingue deux actions d'un même tour. Sans lui, un tour qui
    réclame deux outils n'en enregistrerait qu'un."""
    fichier = tmp_path / "incidents.jsonl"
    lignes = [_ligne(genre=trace.RATTRAPAGE, outil="x", run_id="r1", seq=1),
              _ligne(genre=trace.RATTRAPAGE, outil="y", run_id="r1", seq=2)]
    assert len(incident.capturer(lignes, fichier=fichier)) == 2


def test_une_ligne_sans_run_est_clefee_sur_son_horodatage(tmp_path):
    """Une action écrite avant tout `nouveau_run()` n'a pas de clé stable. Sans
    ce repli, deux passes la dédoubleraient."""
    fichier = tmp_path / "incidents.jsonl"
    orpheline = _ligne(genre=trace.RATTRAPAGE, outil="x", run_id="", seq=1,
                       at="2026-09-06T11:22:33+00:00")
    incident.capturer([orpheline], fichier=fichier)
    assert incident.capturer([orpheline], fichier=fichier) == []


def test_inscrire_ne_leve_jamais(tmp_path):
    """Même règle que la trace : un journal qui casse le tour qu'il observe est
    le défaut que ce chantier existe pour montrer."""
    inc = incident.depuis_la_trace([_ligne(genre=trace.RATTRAPAGE, outil="x")])[0]
    incident.inscrire(inc, fichier=tmp_path / "interdit" / "sous" / "x.jsonl")
    # Un répertoire créable : l'écriture réussit. Le point du test est qu'aucun
    # chemin ne remonte d'exception jusqu'à l'appelant.
    incident.inscrire(inc, fichier=tmp_path)          # un répertoire, pas un fichier


def test_axon_trace_eteint_eteint_aussi_la_capture(tmp_path, monkeypatch):
    """`AXON_TRACE=0` doit tout couper, sinon le journal d'incidents continue
    d'écrire alors que l'utilisateur a demandé le silence."""
    monkeypatch.setenv("AXON_TRACE", "0")
    fichier = tmp_path / "incidents.jsonl"
    incident.capturer([_ligne(genre=trace.RATTRAPAGE, outil="x")], fichier=fichier)
    assert not fichier.exists()


def test_lire_ignore_une_ligne_tronquee(tmp_path):
    fichier = tmp_path / "incidents.jsonl"
    fichier.write_text('{"origine": "a:1"}\n{"orig\n{"origine": "b:1"}\n',
                       encoding="utf-8")
    assert [i["origine"] for i in incident.lire(fichier=fichier)] == ["a:1", "b:1"]
