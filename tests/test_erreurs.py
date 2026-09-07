"""Le compteur de signaux d'erreur — rang 1 de la boucle d'apprentissage.

Ce qui est vérifié ici, c'est surtout ce que le compteur REFUSE de faire :
fondre deux projets, fondre deux motifs de refus, ou compter une ligne qui n'est
pas un signal.
"""
from __future__ import annotations

from src.infra import erreurs, trace


def _ligne(**kw) -> dict:
    base = {"run_id": "r1", "seq": 1, "at": "2026-09-06T10:00:00+00:00",
            "source": "tui", "projet": "axon", "genre": "", "intent": "",
            "outil": "", "cible": "", "confirmation": "", "resultat": "",
            "erreur": "", "extra": {}}
    base.update(kw)
    return base


def _rattrapage(outil: str, **kw) -> dict:
    return _ligne(genre=trace.RATTRAPAGE, outil=outil, **kw)


def _refus(cible: str, motif: str = "refuser", **kw) -> dict:
    return _ligne(genre=trace.VERIFICATION, cible=cible, confirmation="refus",
                  resultat=trace.BLOQUE, erreur=motif, **kw)


def test_les_rattrapages_se_comptent_par_outil():
    lignes = [_rattrapage("jira_create_issue"), _rattrapage("jira_create_issue"),
              _rattrapage("gmail_send_email")]
    comptes = erreurs.rattrapages(lignes)
    assert [(c.quoi, c.n) for c in comptes] == [
        ("jira_create_issue", 2), ("gmail_send_email", 1)]


def test_un_meme_outil_dans_deux_projets_ne_fond_pas():
    """Le catalogue d'un dépôt n'est pas celui d'un autre.

    Fondre les deux produirait un compte qui ne correspond à aucune sélection
    réelle — et une règle durcie dessus s'appliquerait là où elle n'a pas lieu
    d'être. C'est la raison d'être de la colonne `projet`.
    """
    lignes = [_rattrapage("shell_run", projet="axon"),
              _rattrapage("shell_run", projet="autre")]
    comptes = erreurs.rattrapages(lignes)
    assert len(comptes) == 2
    assert {c.projet for c in comptes} == {"axon", "autre"}
    assert all(c.n == 1 for c in comptes)


def test_une_ligne_sans_projet_est_dite_hors_repo():
    """Écrit honnêtement plutôt que laissé vide : un vide se confondrait à la
    relecture avec « colonne pas encore écrite »."""
    comptes = erreurs.rattrapages([_rattrapage("shell_run", projet="")])
    assert comptes[0].projet == trace.HORS_REPO


def test_le_tri_met_le_recurrent_en_tete_pas_le_recent():
    lignes = [_rattrapage("vieux", at="2026-01-01T00:00:00+00:00"),
              _rattrapage("vieux", at="2026-01-02T00:00:00+00:00"),
              _rattrapage("recent", at="2026-09-06T00:00:00+00:00")]
    assert [c.quoi for c in erreurs.rattrapages(lignes)] == ["vieux", "recent"]


def test_les_exemples_gardent_la_requete_sans_la_grouper():
    """La requête entière ne se groupe pas — deux formulations de la même erreur
    donneraient deux lignes et le total se perdrait. Elle est gardée à côté."""
    lignes = [_rattrapage("meteo", intent="quel temps à Lyon"),
              _rattrapage("meteo", intent="il pleut à Paris ?")]
    compte = erreurs.rattrapages(lignes)[0]
    assert compte.n == 2
    assert "quel temps à Lyon" in compte.exemples
    assert len(compte.exemples) == 2


def test_les_exemples_sont_bornes():
    lignes = [_rattrapage("x", intent=f"requête {i}") for i in range(10)]
    assert len(erreurs.rattrapages(lignes)[0].exemples) == erreurs._EXEMPLES


def test_refuser_et_preciser_sont_deux_erreurs_distinctes():
    """« Refusé net » ne dit que le rejet ; « refusé avec consigne » porte la
    correction. Les compter ensemble effacerait la distinction qui sert."""
    lignes = [_refus("/p/tri.py", "refuser"), _refus("/p/tri.py", "preciser")]
    comptes = erreurs.refus(lignes)
    assert len(comptes) == 2
    assert {c.motif for c in comptes} == {"refuser", "preciser"}


def test_le_refus_remonte_la_consigne_de_l_utilisateur():
    lignes = [_refus("/p/tri.py", "preciser",
                     extra={"precision": "garde les type hints"})]
    assert erreurs.refus(lignes)[0].exemples == ["garde les type hints"]


def test_une_verification_acceptee_n_est_pas_un_refus():
    """Seul le couple confirmation=refus ET resultat=bloqué compte. Une revue
    appliquée porte la même genre de ligne et ne doit pas y entrer."""
    acceptee = _ligne(genre=trace.VERIFICATION, cible="/p/tri.py",
                      confirmation="accord", resultat=trace.OK)
    assert erreurs.refus([acceptee]) == []


def test_la_couverture_donne_le_denominateur():
    """Sans lui, « trois rattrapages » ne veut rien dire : sur trois tours c'est
    un routeur cassé, sur trois cents c'est du bruit."""
    lignes = [_ligne(run_id="a", genre=trace.ROUTE),
              _rattrapage("x", run_id="a"),
              _ligne(run_id="b", genre=trace.ROUTE),
              _ligne(run_id="c", genre=trace.ROUTE)]
    vue = erreurs.couverture(lignes)
    assert vue["runs"] == 3
    assert vue["avec_signal"] == 1
    assert vue["projets"] == ["axon"]


def test_deux_signaux_dans_le_meme_tour_ne_comptent_qu_un_tour():
    lignes = [_rattrapage("x", run_id="a", seq=1),
              _rattrapage("y", run_id="a", seq=2)]
    assert erreurs.couverture(lignes)["avec_signal"] == 1


def test_un_journal_vide_ne_casse_rien():
    assert erreurs.rattrapages([]) == []
    assert erreurs.refus([]) == []
    assert erreurs.couverture([]) == {"runs": 0, "avec_signal": 0, "projets": []}
