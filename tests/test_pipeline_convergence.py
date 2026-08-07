"""Une seule chaîne de vérité entre le chemin unitaire et le chemin batch.

`decide_match()` évaluait 28 matchs de tennis ; `evaluate_live_batch()` en
évaluait 0 sur les MÊMES événements. Divergence localisée à la résolution de
compétition :

    unitaire   identity=RESOLVED    comp=competition:tennis:atp:tour
    batch      identity=UNRESOLVED  comp=None

`BookmakerEventResolver` accepte un `competition_resolver` INJECTABLE, et son
défaut résout par identifiant de tournoi bookmaker — la table des sports de
ligue. Le chemin unitaire injectait celui du sport demandé ; le batch prenait le
défaut par omission. Deux constructions, deux verdicts sur le même événement.

Le tennis ne peut pas résoudre par identifiant : chez Winamax un
`raw_tournament_id` désigne une ÉDITION (176503 = Montréal 2026), pas une
compétition. Il résout par recouvrement de plateau. Et un batch mélange les
sports par nature — le dispatch doit donc se faire par ÉVÉNEMENT, pas par appel.
"""

from __future__ import annotations

import pytest

from src.agents.quant.betting_engine.sports.registry import (
    SPORT_MODULES,
    all_known_entities,
    resolve_competition_any_sport,
)

SPORTS = sorted(SPORT_MODULES)


# ── la fabrique est unique ──────────────────────────────────────────────────────
def test_un_seul_site_construit_le_resolveur_dans_tout_le_code():
    """Le test qui aurait attrapé la divergence.

    `BookmakerEventResolver` a DEUX dépendances injectables au défaut football-only.
    Quatre sites le construisaient ; deux oubliaient le résolveur de compétition, et
    le même événement recevait deux verdicts selon le chemin d'appel. Vérifier que
    chaque site passe le bon argument ne suffit pas — il faut qu'il n'y ait plus
    qu'un site, sinon le cinquième réintroduira l'oubli.
    """
    import pathlib
    import re

    racine = pathlib.Path(__file__).resolve().parents[1] / "src"
    motif = re.compile(r"BookmakerEventResolver\s*\(")
    sites = [
        f"{chemin.relative_to(racine)}:{n}"
        for chemin in racine.rglob("*.py")
        for n, ligne in enumerate(chemin.read_text(encoding="utf-8").splitlines(), 1)
        if motif.search(ligne)
    ]
    assert sites == ["agents/quant/betting_engine/sports/registry.py:92"], (
        f"le résolveur est construit hors de sa fabrique : {sites}")


@pytest.mark.parametrize("module_name", [
    "src.agents.quant.betting_engine.cli",
    "src.agents.quant.structured_decision",
    "src.agents.quant.advisor.cli",
    "src.agents.quant.betting_engine.clv.cli",
    "src.agents.quant.conversation.recommend",
])
def test_chaque_chemin_produit_passe_par_la_fabrique(module_name):
    """Les cinq chemins qui scannent du live — unitaire, batch, `axon recommend`,
    collecte CLV, conversationnel — doivent citer la fabrique, jamais la classe."""
    import importlib
    import inspect

    source = inspect.getsource(importlib.import_module(module_name))
    assert "build_event_resolver()" in source, (
        f"{module_name} construit son résolveur autrement")


def test_les_deux_agregateurs_d_identite_donnent_le_meme_ensemble():
    """`all_sport_teams` énumérait les référentiels à la main. Il produisait le
    même ensemble que le registre — jusqu'au jour où un sport s'ajoute d'un seul
    côté."""
    from src.agents.quant.betting_engine.sports.identity_aggregate import all_sport_teams

    assert ({e.canonical_id for e in all_sport_teams()}
            == {e.canonical_id for e in all_known_entities()})


def test_le_batch_scanne_tous_les_sports_enregistres():
    """Le catalogue par DÉFAUT couvre les sept sports enregistrés.

    Il valait `supported_events`, dont le `sport` valait lui-même « football » :
    six sports restaient invisibles au run live alors que leurs modèles étaient
    prêts. Le CLI corrigeait le tir à la main — donc tout autre appelant héritait
    du trou.

    Ce test observe le SCAN plutôt que le texte du CLI : une vérification par
    `inspect.getsource` passe encore quand la logique déménage, et échoue quand
    elle est seulement réécrite.
    """
    from src.agents.quant.betting_engine.live_batch import evaluate_live_batch
    from src.agents.quant.betting_engine.sports.registry import SPORT_MODULES

    demandes = []

    class _Connecteur:
        def scan_catalog(self, sport):
            demandes.append(sport)
            return []

    evaluate_live_batch(_Connecteur(), sports_gateway=object(),
                        event_resolver=object())

    assert set(demandes) == set(SPORT_MODULES)


def test_le_batch_resout_l_identite_des_sept_sports():
    """Le CLI construisait `IdentityResolver(TEAMS)` — le référentiel football.
    La fabrique unique porte désormais l'union ; on vérifie sur l'objet produit,
    pas sur le texte, pour que le test survive à un renommage."""
    from src.agents.quant.betting_engine.sports.registry import build_event_resolver

    resolveur = build_event_resolver()
    for sport in SPORTS:
        attendues = {e.canonical_id for e in SPORT_MODULES[sport].known_entities()}
        prefixes = {f"{cid.split(':')[0]}:{sport}:" for cid in attendues}
        vues = {e.canonical_id
                for p in prefixes
                for e in resolveur._identity.all_entities(p)}
        assert attendues <= vues, f"{sport} absent du résolveur de la fabrique"


# ── le dispatch se fait par ÉVÉNEMENT ───────────────────────────────────────────
class _Event:
    def __init__(self, sport, tid="X"):
        self.sport = sport
        self.raw_tournament_id = tid


def test_chaque_sport_recoit_son_propre_resolveur():
    """Le tennis a le sien (recouvrement de plateau) ; les sports de ligue
    retombent sur la table de tournois. Un batch mélange les deux."""
    module = SPORT_MODULES["tennis"]
    assert module.resolve_competition is not None, (
        "le tennis doit porter son résolveur : sa table de tid serait fausse "
        "dès la semaine suivante")

    appels = []
    module_original = module.resolve_competition
    try:
        SPORT_MODULES["tennis"] = type(module)(
            module.sport, module.build_feature_set, module.model,
            entities=module.entities,
            resolve_competition=lambda ev: appels.append(ev.sport) or ("c", "RESOLVED", "m"))
        resolve_competition_any_sport(_Event("tennis"))
        assert appels == ["tennis"], "le résolveur du sport n'a pas été appelé"
    finally:
        SPORT_MODULES["tennis"] = module


def test_un_sport_sans_resolveur_retombe_sur_la_table():
    """Sans repli, ajouter un sport casserait la résolution des six autres."""
    resultat = resolve_competition_any_sport(_Event("football", tid="4"))

    assert isinstance(resultat, tuple) and len(resultat) == 3


def test_un_sport_inconnu_ne_leve_pas():
    """Un événement d'un sport non enregistré doit produire un refus typé, pas
    une exception qui ferait tomber tout le batch."""
    resultat = resolve_competition_any_sport(_Event("curling", tid="?"))

    assert isinstance(resultat, tuple) and len(resultat) == 3


# ── non-régression : les sept sports restent atteignables ───────────────────────
@pytest.mark.parametrize("sport", SPORTS)
def test_chaque_sport_reste_resolvable_apres_unification(sport):
    """L'union des référentiels ne doit pas noyer un sport : `_name_matches`
    filtre par préfixe d'identifiant, les espaces restent étanches."""
    from src.agents.quant.gateway.core.identity_resolver import IdentityResolver

    resolveur = IdentityResolver(all_known_entities())
    attendues = {e.canonical_id for e in SPORT_MODULES[sport].known_entities()}
    prefixes = {f"{cid.split(':')[0]}:{sport}:" for cid in attendues}

    vues = {e.canonical_id for p in prefixes for e in resolveur.all_entities(p)}
    assert attendues <= vues, f"{sport} a perdu des entités dans l'union"


def test_aucune_entite_ne_traverse_les_frontieres_de_sport():
    """Le risque money du référentiel unifié : un joueur de tennis résolu contre
    un club de football ferait tourner le mauvais modèle sur le mauvais match."""
    from src.agents.quant.gateway.core.identity_resolver import IdentityResolver

    resolveur = IdentityResolver(all_known_entities())
    for sport in SPORTS:
        for entity in resolveur.all_entities(f"player:{sport}:"):
            assert entity.canonical_id.split(":")[1] == sport
        for entity in resolveur.all_entities(f"team:{sport}:"):
            assert entity.canonical_id.split(":")[1] == sport


def test_aucune_fonction_du_scan_ne_prend_un_sport_par_defaut():
    """Un défaut « football » ne se remarque pas à la lecture.

    `scan_catalog`, `all_events`, `supported_events`, `fetch_odds_quotes` et
    `verify` déclaraient toutes `sport="football"`. Un appelant générique en
    apparence scannait donc un seul sport, et son silence ressemblait à un
    catalogue vide plutôt qu'à une question mal posée. Rendre le paramètre
    obligatoire transforme l'oubli en erreur d'appel — visible tout de suite.
    """
    import ast
    import pathlib

    racine = pathlib.Path(__file__).resolve().parent.parent / "src"
    surveillees = {"scan_catalog", "all_events", "supported_events",
                   "multisport_events", "fetch_odds_quotes", "verify"}
    coupables = []
    for fichier in sorted(racine.rglob("*.py")):
        arbre = ast.parse(fichier.read_text())
        for noeud in ast.walk(arbre):
            if not isinstance(noeud, ast.FunctionDef) or noeud.name not in surveillees:
                continue
            args = noeud.args.args[-len(noeud.args.defaults):] if noeud.args.defaults else []
            for arg, defaut in zip(args, noeud.args.defaults):
                if arg.arg in ("sport", "sports") and isinstance(defaut, ast.Constant):
                    coupables.append(
                        f"{fichier.relative_to(racine)}:{noeud.lineno} "
                        f"{noeud.name}({arg.arg}={defaut.value!r})")

    assert not coupables, "sport avec valeur par défaut :\n" + "\n".join(coupables)
