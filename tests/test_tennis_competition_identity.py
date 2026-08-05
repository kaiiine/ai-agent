"""Identité de compétition du tennis — déduite du plateau, jamais du tid ni du nom.

Deux pièges rendent le mapping par libellé dangereux, pas seulement imprécis :

- le `raw_tournament_id` Winamax identifie une ÉDITION (176503 = Montréal 2026).
  Une table statique serait à réécrire chaque semaine, et fausse entre-temps ;
- le Canadian Open ALTERNE les villes entre circuits. En 2026 Winamax place l'ATP à
  Montréal et la WTA à Toronto, l'inverse de l'édition précédente. Résoudre par la
  ville ferait tourner un modèle masculin sur des matchs féminins une année sur deux.

Ce qui est stable, c'est le plateau. On résout donc par recouvrement de roster, avec
la MÊME primitive que le football (`competition_identity.disambiguate`).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.agents.quant.betting_engine.sports.tennis.competition import (
    COMPETITION_IDS,
    resolve_tennis_competition,
)


def _event(a: str, b: str, tid: str = "999", competition: str = "Peu importe"):
    return SimpleNamespace(slot_1_name=a, slot_2_name=b, raw_tournament_id=tid,
                           competition=competition, is_outright=False)


# ── résolution par preuve ───────────────────────────────────────────────────────
def test_un_plateau_masculin_resout_vers_l_atp():
    cid, statut, methode = resolve_tennis_competition(
        _event("Musetti L.", "Tsitsipas S."))
    assert (cid, statut, methode) == (COMPETITION_IDS["atp"], "RESOLVED", "roster_overlap")


def test_un_plateau_feminin_resout_vers_la_wta():
    cid, statut, _ = resolve_tennis_competition(_event("Pegula J.", "Rybakina E."))
    assert (cid, statut) == (COMPETITION_IDS["wta"], "RESOLVED")


def test_le_libelle_du_tournoi_n_influence_pas_la_resolution():
    """LE test du piège Canadian Open : le même plateau masculin doit donner l'ATP,
    que Winamax l'annonce sous « Montréal », « Toronto » ou n'importe quoi d'autre."""
    resultats = {
        resolve_tennis_competition(_event("Musetti L.", "Tsitsipas S.", competition=ville))[0]
        for ville in ("Montréal", "Toronto", "Cincinnati", "")
    }
    assert resultats == {COMPETITION_IDS["atp"]}


def test_le_tid_n_influence_pas_la_resolution():
    """Un tid change à chaque édition : s'en servir rendrait le mapping périmé une
    semaine plus tard."""
    resultats = {
        resolve_tennis_competition(_event("Pegula J.", "Rybakina E.", tid=tid))[0]
        for tid in ("176503", "179030", "000", "")
    }
    assert resultats == {COMPETITION_IDS["wta"]}


# ── refus plutôt que devinette ──────────────────────────────────────────────────
def test_un_joueur_inconnu_laisse_la_competition_non_resolue():
    """Un seul joueur reconnu ne suffit pas : l'adversaire pourrait venir d'un autre
    circuit, et sa note Elo serait alors prise dans le mauvais pool."""
    cid, statut, _ = resolve_tennis_competition(
        _event("Musetti L.", "Joueur Totalement Inexistant"))
    assert cid is None and statut == "UNRESOLVED"


def test_un_plateau_mixte_ne_resout_pas():
    """Aucune inférence sur un croisement de circuits — c'est le cas où se tromper
    coûte le plus cher."""
    cid, statut, _ = resolve_tennis_competition(_event("Musetti L.", "Rybakina E."))
    assert cid is None and statut == "UNRESOLVED"


@pytest.mark.parametrize("a,b", [("", "Rybakina E."), ("Musetti L.", ""), ("", "")])
def test_un_evenement_incomplet_ne_resout_pas(a, b):
    assert resolve_tennis_competition(_event(a, b))[0] is None


# ── ce que le résolveur ne doit PAS être ────────────────────────────────────────
def test_aucune_regle_par_tournoi_ni_whitelist():
    """Une liste de tournois connus serait à maintenir et silencieusement incomplète.
    Le module ne doit contenir aucun nom de tournoi ni de ville."""
    import ast
    import inspect

    from src.agents.quant.betting_engine.sports.tennis import competition

    # Les commentaires et docstrings CITENT ces noms pour expliquer le piège ;
    # seul le code exécuté ne doit pas les contenir. On compare donc sur l'AST
    # débarrassé de ses docstrings, pas sur le texte source.
    arbre = ast.parse(inspect.getsource(competition))
    for noeud in ast.walk(arbre):
        if isinstance(noeud, (ast.Module, ast.FunctionDef, ast.ClassDef)):
            corps = noeud.body
            if corps and isinstance(corps[0], ast.Expr) and isinstance(corps[0].value, ast.Constant):
                corps.pop(0)
    code = ast.unparse(arbre)

    for interdit in ("Montréal", "Montreal", "Toronto", "Cincinnati", "Wimbledon", "Roland"):
        assert interdit not in code, f"nom de lieu en dur dans le code : {interdit}"


def test_la_primitive_de_desambiguisation_est_partagee_avec_le_football():
    """Une seconde implémentation divergerait de la première sans que rien ne le
    signale — et les deux décident d'argent."""
    import inspect

    from src.agents.quant.betting_engine.sports.tennis import competition

    assert "from ...competition_identity import" in inspect.getsource(competition)


def test_les_deux_circuits_ont_une_identite_canonique_distincte():
    assert COMPETITION_IDS["atp"] != COMPETITION_IDS["wta"]
    for tour, cid in COMPETITION_IDS.items():
        assert cid.startswith("competition:tennis:"), cid
        assert tour in cid
