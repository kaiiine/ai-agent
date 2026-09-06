"""L'alerting du chemin sans témoin.

Le TUI n'en a pas besoin : l'utilisateur voit l'écran. Le démon cron tourne sans
personne, et c'est là qu'une tâche a logué « ok » avec toutes ses commandes
bloquées. Ce qui est testé ici, c'est qu'une anomalie de ce genre produit une
raison — et qu'une exécution normale n'en produit AUCUNE, faute de quoi
l'alerting devient un bruit qu'on finit par couper.
"""

from src.infra import alerte, trace


def _ligne(**champs) -> dict:
    base = {"run_id": "r1", "seq": 1, "genre": trace.OUTIL, "outil": "shell_run",
            "resultat": trace.OK, "policy": trace.AUTORISE, "verification": "",
            "cible": "", "erreur": "", "tokens_entree": 0}
    return {**base, **champs}


def test_une_execution_normale_n_alerte_pas():
    """La propriété la plus importante du module : un garde qu'on trouve pénible
    finit désactivé."""
    assert alerte.evaluer([
        _ligne(),
        _ligne(seq=2, genre=trace.APPEL_LLM, tokens_entree=3_000),
        _ligne(seq=3, genre=trace.TACHE, outil="tache-1"),
    ]) == []


def test_une_commande_bloquee_alerte_et_dit_le_remede():
    raisons = alerte.evaluer([_ligne(
        policy=trace.REFUSE, resultat=trace.BLOQUE, cible="systemctl restart nginx")])
    assert len(raisons) == 1
    assert "systemctl restart nginx" in raisons[0]
    # Une alerte qui n'indique pas quoi faire se relit deux fois et s'ignore.
    assert "commandes_autorisees" in raisons[0]


def test_une_erreur_alerte_avec_son_code():
    raisons = alerte.evaluer([_ligne(resultat=trace.ERREUR, erreur="tool_error")])
    assert raisons and "tool_error" in raisons[0]


def test_un_fichier_ecrit_mais_casse_alerte():
    raisons = alerte.evaluer([_ligne(
        genre=trace.VERIFICATION, verification="casse", cible="/tmp/tri.py")])
    assert any("CASSÉ" in r and "tri.py" in r for r in raisons)


def test_le_depassement_de_tokens_alerte():
    """Le plancher de schémas d'outils atteignait 12 731 tokens sur une requête
    réelle, au-dessus de ce que Groq accepte, sans que rien ne le signale."""
    raisons = alerte.evaluer([_ligne(genre=trace.APPEL_LLM, tokens_entree=12_731)])
    assert raisons and "12 731" in raisons[0]


def test_le_seuil_de_tokens_est_reglable(monkeypatch):
    """Le plafond dépend du backend : un seuil figé serait faux quelque part."""
    monkeypatch.setenv("AXON_ALERTE_TOKENS", "50000")
    assert alerte.evaluer([_ligne(genre=trace.APPEL_LLM, tokens_entree=12_731)]) == []
    monkeypatch.setenv("AXON_ALERTE_TOKENS", "1000")
    assert alerte.evaluer([_ligne(genre=trace.APPEL_LLM, tokens_entree=12_731)])


def test_un_seuil_illisible_retombe_sur_le_defaut(monkeypatch):
    monkeypatch.setenv("AXON_ALERTE_TOKENS", "beaucoup")
    assert alerte.seuil_tokens() == alerte.SEUIL_TOKENS_DEFAUT


def test_dix_refus_identiques_font_une_alerte():
    """Une notification bavarde finit coupée, et c'est le jour d'après qu'elle
    aurait servi."""
    lignes = [_ligne(seq=i, policy=trace.REFUSE, resultat=trace.BLOQUE,
                     cible="rm -rf /tmp/x") for i in range(10)]
    assert len(alerte.evaluer(lignes)) == 1


def test_du_run_ne_lit_que_le_run_demande(tmp_path, monkeypatch):
    chemin = tmp_path / "decisions.jsonl"
    monkeypatch.setattr(trace, "FICHIER", chemin)

    trace.nouveau_run("cron")
    trace.inscrire(trace.Action(genre=trace.OUTIL, outil="ok"), fichier=chemin)
    coupable = trace.nouveau_run("cron")
    trace.inscrire(trace.Action(
        genre=trace.OUTIL, outil="shell_run", cible="rm -rf /",
        policy=trace.REFUSE, resultat=trace.BLOQUE), fichier=chemin)

    raisons = alerte.du_run(coupable)
    assert len(raisons) == 1 and "rm -rf /" in raisons[0]
    assert alerte.du_run("") == []
