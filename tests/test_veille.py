"""Une veille ne prévient que si la valeur a bougé.

Sans cette condition, elle notifierait à chaque passage — vingt-quatre fois par
jour pour un prix inchangé, et on apprendrait à l'ignorer. La comparaison est
donc déterministe ; seule l'extraction de la valeur passe par le modèle, et elle
est structurée.
"""
from __future__ import annotations

import pytest

from src.agents.cron.surveillance import (
    BALISE,
    CONDITIONS,
    consigne,
    decrire,
    doit_alerter,
    extraire,
)


def _veille(condition="change", seuil=None, derniere=None):
    return {"quoi": "le prix", "condition": condition, "seuil": seuil,
            "derniere": derniere}


# ── Extraction ───────────────────────────────────────────────────────────────
@pytest.mark.parametrize("reponse, attendu", [
    (f"Le prix affiché est de 1299 €.\n{BALISE}: 1299 €", "1299 €"),
    (f"{BALISE}: 42", "42"),
    (f"{BALISE}: `1 200,50`", "1 200,50"),
    ("aucune balise ici", None),
    (f"{BALISE}: inconnue", None),
    (f"{BALISE}: n/a", None),
    ("", None),
])
def test_la_valeur_se_lit_dans_une_ligne_dediee(reponse, attendu):
    assert extraire(reponse) == attendu


def test_la_consigne_nomme_la_balise_attendue():
    """Sans elle dans le prompt, la tâche répond en prose et rien n'est
    comparable."""
    assert BALISE in consigne("le prix en euros")
    assert "le prix en euros" in consigne("le prix en euros")


# ── Ce qui n'alerte JAMAIS ───────────────────────────────────────────────────
def test_un_premier_releve_n_alerte_pas():
    """Il n'y a rien à comparer : alerter reviendrait à prévenir d'un changement
    qui n'a pas eu lieu."""
    alerte, raison = doit_alerter(_veille(derniere=None), "1299")
    assert not alerte and "premier" in raison


def test_une_valeur_non_relevee_n_alerte_pas():
    """Une page en panne ferait sinon sonner l'alerte à chaque passage."""
    alerte, _ = doit_alerter(_veille(derniere="1299"), None)
    assert not alerte


def test_une_valeur_identique_n_alerte_pas():
    assert not doit_alerter(_veille(derniere="1299 €"), "1299 €")[0]
    assert not doit_alerter(_veille(derniere="1299 €"), " 1299 €  ")[0], (
        "un espacement différent n'est pas un changement")


# ── Les conditions ───────────────────────────────────────────────────────────
def test_change_alerte_sur_toute_difference():
    alerte, raison = doit_alerter(_veille(derniere="ouvert"), "fermé")
    assert alerte and "ouvert" in raison and "fermé" in raison


@pytest.mark.parametrize("condition, ancien, neuf, attendu", [
    ("baisse", "1299", "1199", True),
    ("baisse", "1299", "1399", False),
    ("baisse", "1299", "1299", False),
    ("hausse", "1299", "1399", True),
    ("hausse", "1299", "1199", False),
])
def test_le_sens_de_variation_est_respecte(condition, ancien, neuf, attendu):
    assert doit_alerter(_veille(condition, derniere=ancien), neuf)[0] is attendu


@pytest.mark.parametrize("ancien, neuf, attendu", [
    ("1299", "1150", True),    # franchit
    ("1150", "1100", False),   # déjà dessous : ne resonne pas
    ("1299", "1250", False),   # toujours au-dessus
    ("1150", "1250", False),   # remonte au-dessus
])
def test_un_seuil_alerte_au_FRANCHISSEMENT_seulement(ancien, neuf, attendu):
    """Un prix durablement bas sonnerait sinon à chaque passage, et l'alerte
    perdrait tout son sens."""
    veille = _veille("sous", seuil=1200.0, derniere=ancien)
    assert doit_alerter(veille, neuf)[0] is attendu


def test_un_seuil_sans_valeur_numerique_n_alerte_pas():
    assert not doit_alerter(_veille("sous", seuil=1200.0, derniere="1299"), "épuisé")[0]


def test_les_nombres_se_lisent_avec_virgule_et_symbole():
    assert doit_alerter(_veille("baisse", derniere="1 299,90 €"), "1 199,50 €")[0]


# ── L'outil ──────────────────────────────────────────────────────────────────
def test_une_condition_inconnue_est_refusee():
    import json

    from src.agents.cron.tools import surveiller

    r = json.loads(surveiller.invoke({
        "description": "x", "quoi_relever": "le prix", "comment_relever": "lis",
        "condition": "quand-ça-me-chante", "interval_sec": 3600,
        "notify_channels": ["desktop"]}))
    assert r["status"] == "error"
    assert all(c in r["error"] for c in ("change", "baisse"))


@pytest.mark.parametrize("condition", ["sous", "sur"])
def test_un_seuil_est_exige_quand_la_condition_en_demande_un(condition):
    """Sans seuil, la veille ne pourrait jamais alerter — et échouerait en
    silence, ce qui est pire que de refuser."""
    import json

    from src.agents.cron.tools import surveiller

    r = json.loads(surveiller.invoke({
        "description": "x", "quoi_relever": "le prix", "comment_relever": "lis",
        "condition": condition, "interval_sec": 3600,
        "notify_channels": ["desktop"], "seuil": 0}))
    assert r["status"] == "error" and "seuil" in r["error"]


def test_la_veille_creee_porte_sa_consigne_et_son_etat():
    import json

    from src.agents.cron.store import deactivate_task, get_tasks
    from src.agents.cron.tools import surveiller

    r = json.loads(surveiller.invoke({
        "description": "Prix test", "quoi_relever": "le prix en euros",
        "comment_relever": "consulte la page", "condition": "baisse",
        "interval_sec": 3600, "notify_channels": ["desktop"]}))
    try:
        assert r["status"] == "surveille"
        tache = next(t for t in get_tasks() if t["id"] == r["id"])
        assert BALISE in tache["prompt"], "sans la consigne, rien n'est comparable"
        assert tache["surveillance"] == {
            "quoi": "le prix en euros", "condition": "baisse",
            "seuil": None, "derniere": None}
    finally:
        deactivate_task(r["id"])


def test_toutes_les_conditions_declarees_sont_gerees():
    """La liste exposée à l'outil et celle que sait comparer `doit_alerter` ne
    doivent pas diverger : une condition acceptée mais jamais évaluée créerait
    une veille qui n'alerte jamais."""
    for condition in CONDITIONS:
        veille = _veille(condition, seuil=100.0, derniere="50")
        doit_alerter(veille, "150")          # ne doit pas lever
        assert decrire(veille)


def test_decrire_dit_l_etat_de_la_veille():
    assert "jamais relevé" in decrire(_veille("baisse"))
    assert "1299" in decrire(_veille("baisse", derniere="1299"))
