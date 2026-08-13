"""Inventaire multi-marché — sur une capture RÉELLE, jamais sur un payload inventé.

La fixture `winamax_market_inventory.json` est un EXTRAIT d'une capture réseau
réelle (29 sports, 98 événements, 5 964 marchés), pas une reconstitution : elle
porte sa provenance et sa date. Un inventaire testé sur des marchés fabriqués ne
prouverait que la cohérence de nos propres suppositions — exactement ce que
l'ordre « observer avant de canonicaliser » sert à empêcher.

Ce que ces tests protègent, dans l'ordre d'importance :

1. le chemin `MATCH_WINNER` existant ne change pas de sens (§11) ;
2. un marché reconnu n'est jamais confondu avec un marché prédictible ;
3. rien n'est jeté — les marchés se partitionnent, les paramètres inconnus se
   voient ;
4. la ligne est un PARAMÈTRE, pas un type (§6).
"""

from __future__ import annotations

import json
import pathlib

import pytest

from src.agents.quant.betting_engine.markets import (
    CapabilityStatus,
    ClassificationStatus,
    MarketFamily,
    RawMarketObservation,
    RawSelectionObservation,
    build_inventory,
    classify,
    measure,
    parser_parametres,
    resolve_model,
)

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "winamax_market_inventory.json"


def _observation(ligne: dict) -> RawMarketObservation:
    return RawMarketObservation(
        bookmaker="winamax", sport=ligne["sport"], sport_id=ligne["sport_id"],
        competition=ligne["competition"],
        competition_source_id=str(ligne["tournament_id"]),
        source_event_id=str(ligne["source_event_id"]),
        event_label=ligne["event_title"], start_time=None,
        is_outright=ligne["is_outright"],
        market_source_id=str(ligne["market_source_id"]),
        bet_type=ligne["bet_type"], bet_type_name=ligne["bet_type_name"],
        bet_title=ligne["bet_title"], template=ligne["template"],
        special_bet_value=ligne["special_bet_value"],
        category_id=ligne["category_id"], category=ligne["category"],
        is_live=ligne["is_live"],
        selections=tuple(
            RawSelectionObservation(
                str(s["outcome_id"]), s["code"], s["label"], s["odds"],
                str(s["competitor_id"]) if s.get("competitor_id") else None,
                s.get("available"))
            for s in ligne["selections"]))


@pytest.fixture(scope="module")
def capture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def observations(capture) -> list[RawMarketObservation]:
    return [_observation(l) for l in capture["marches"]]


@pytest.fixture(scope="module")
def inventaire(observations):
    return build_inventory(observations)


# ── La fixture est une capture, et le dit ─────────────────────────────────────

def test_la_fixture_porte_sa_provenance(capture):
    """Une fixture qui ne dit pas d'où elle vient finit par être prise pour la
    réalité. Celle-ci porte sa source, sa date et sa nature d'extrait."""
    p = capture["provenance"]
    assert "winamax.fr" in p["source"]
    assert p["captured_at"]
    assert "RÉELLE" in p["nature"] and "fabriqué" in p["nature"]
    assert p["population_totale"]["marches"] > len(capture["marches"])


# ── §11 : la généralisation ne doit RIEN changer à MATCH_WINNER ───────────────

def test_le_sens_de_match_winner_est_inchange(observations):
    """Le contrat de non-régression le plus important du chantier.

    `map_market` est l'autorité en production. Tout marché qu'elle reconnaît
    comme « qui gagne » doit rester `MATCH_WINNER` ici — et la réciproque, sans
    quoi la généralisation aurait élargi le marché principal en silence.
    """
    from src.agents.quant.betting_engine.bookmakers.protocol import MarketType
    from src.agents.quant.betting_engine.bookmakers.winamax.market_mapping import map_market

    desaccords = []
    for obs in observations:
        historique = map_market(obs.bet_type_name or "", obs.template or "",
                                is_outright=obs.is_outright)
        nouveau = classify(obs).family
        avant = historique is MarketType.MATCH_WINNER
        apres = nouveau is MarketFamily.MATCH_WINNER
        if avant != apres:
            desaccords.append((obs.bet_type_name, obs.template, obs.nb_selections,
                               historique.value, nouveau.value))
    assert not desaccords, f"le sens de MATCH_WINNER a bougé : {desaccords[:5]}"


def test_un_marche_de_periode_n_est_pas_le_marche_de_la_rencontre():
    """Le piège que le contexte existe pour éviter : « Mi-temps - Résultat » a la
    forme EXACTE d'un 1X2. Sans contexte, il recevrait le modèle de fin de match
    et produirait une probabilité fausse que rien ne signalerait."""
    mi_temps = RawMarketObservation(
        bookmaker="winamax", sport="Football", sport_id=1, competition="Ligue 1",
        competition_source_id="1", source_event_id="e1", event_label="A - B",
        start_time=None, is_outright=False, market_source_id="m1",
        bet_type=999, bet_type_name="Résultat", bet_title="Mi-temps - Résultat",
        template="3way", special_bet_value="periodnr=1",
        selections=tuple(RawSelectionObservation(str(i), c, c, 2.0)
                         for i, c in enumerate(("1", "x", "2"))))

    classification = classify(mi_temps)
    assert classification.family is MarketFamily.MATCH_WINNER      # bien lu
    assert classification.parameters == {"periodnr": "1"}          # et restreint

    capacite = resolve_model(winamax_sport_id=1, family=MarketFamily.MATCH_WINNER,
                             context=classification.parameters)
    # `MODEL_CONTEXT_MISMATCH` et non `MODEL_NOT_AVAILABLE` : un modèle existe
    # bien pour (football, MATCH_WINNER) — ce qui manque est une portée, pas un
    # modèle. La distinction dit à qui lit le rapport ce qu'il faudrait construire.
    assert capacite.status is CapabilityStatus.MODEL_CONTEXT_MISMATCH
    assert "periodnr" in capacite.reason
    assert capacite.rejected_by, "le modèle qui refuse doit être nommé"


def test_le_marche_plein_match_reste_evaluable():
    """Le pendant du test précédent : sans restriction, le modèle s'applique."""
    plein = RawMarketObservation(
        bookmaker="winamax", sport="Football", sport_id=1, competition="Ligue 1",
        competition_source_id="1", source_event_id="e1", event_label="A - B",
        start_time=None, is_outright=False, market_source_id="m1",
        bet_type=1, bet_type_name="Résultat", bet_title="Résultat", template="3way",
        special_bet_value=None,
        selections=tuple(RawSelectionObservation(str(i), c, c, 2.0)
                         for i, c in enumerate(("1", "x", "2"))))

    capacite = resolve_model(winamax_sport_id=1, family=MarketFamily.MATCH_WINNER,
                             context=classify(plein).parameters)
    assert capacite.status is CapabilityStatus.MODEL_AVAILABLE
    assert capacite.maturity is not None


# ── §4 : reconnaître ≠ savoir prédire ─────────────────────────────────────────

def test_reconnaitre_n_est_pas_savoir_predire(inventaire):
    """Sur la capture réelle, l'écart est massif et c'est l'intérêt du test :
    beaucoup de marchés canonicalisés, très peu d'évaluables."""
    canonicalises = [r for r in inventaire if r.classification.canonical]
    evaluables = [r for r in inventaire if r.evaluable]

    assert canonicalises, "la capture contient des marchés canonicalisables"
    assert len(evaluables) < len(canonicalises), (
        "un inventaire qui déclare évaluable tout ce qu'il comprend a confondu "
        "les deux axes")
    for ligne in canonicalises:
        if not ligne.evaluable:
            assert ligne.capability.reason, "un refus doit toujours porter son motif"


def test_un_marche_non_canonicalise_n_est_jamais_evaluable(inventaire):
    """`UNMAPPED` -> `UNSUPPORTED` : il n'y a rien à modéliser tant que la
    famille n'est pas établie. C'est la barrière contre « la cote a l'air
    intéressante, donc j'y vais »."""
    for ligne in inventaire:
        if ligne.family is MarketFamily.UNMAPPED:
            assert ligne.capability.status is CapabilityStatus.UNSUPPORTED
            assert not ligne.evaluable


# ── §6 : la ligne est un paramètre, pas un type ───────────────────────────────

def test_les_lignes_partagent_une_seule_famille(inventaire):
    """Over 2.5 et Over 3.5 sont le même marché à deux seuils. S'ils devenaient
    deux types, il en faudrait un par valeur — des centaines."""
    totaux = [r for r in inventaire if r.family is MarketFamily.TOTALS]
    assert len(totaux) > 10
    lignes = {r.classification.parameters.get("line") for r in totaux}
    assert len(lignes) > 3, "la capture doit contenir plusieurs seuils"
    assert all(isinstance(l, float) for l in lignes)
    # Une seule famille, plusieurs paramètres — et la description le montre.
    assert {r.family for r in totaux} == {MarketFamily.TOTALS}
    assert any(r.classification.describe().startswith("TOTALS(line=") for r in totaux)


def test_la_portee_reste_un_parametre(inventaire):
    """Un total de 1er quart-temps n'est pas une famille de plus."""
    avec_portee = [r for r in inventaire
                   if r.family is MarketFamily.TOTALS and
                   any(c in r.classification.parameters
                       for c in ("quarternr", "setnr", "periodnr", "inningnr"))]
    if not avec_portee:
        pytest.skip("aucun total restreint à une période dans cet extrait")
    for ligne in avec_portee:
        assert ligne.family is MarketFamily.TOTALS
        assert "line" in ligne.classification.parameters


def test_la_grammaire_des_parametres_est_celle_observee():
    """`clé=valeur` joints par `|` — la forme mesurée sur 5 964 marchés."""
    assert parser_parametres("total=2.5") == {"total": "2.5"}
    assert parser_parametres("from=1|to=10") == {"from": "1", "to": "10"}
    assert parser_parametres("player=sr:player:1152468|total=9.5") == {
        "player": "sr:player:1152468", "total": "9.5"}
    assert parser_parametres(None) == {}
    # Un fragment sans « = » reste VISIBLE plutôt que d'être écarté en silence.
    assert parser_parametres("bizarre") == {"": "bizarre"}


# ── §2 et §8 : rien n'est jeté, tout se compte ────────────────────────────────

def test_les_marches_se_partitionnent(inventaire):
    """Un marché tombé entre deux statuts est un marché perdu."""
    couverture = measure(inventaire)
    coherent, detail = couverture.counters_balance()
    assert coherent, detail
    assert couverture.markets == len(inventaire)
    assert couverture.selections > couverture.markets


def test_un_taux_sans_denominateur_n_est_pas_zero():
    """`NOT_MEASURED` doit rester distinct de 0 — un catalogue non parcouru n'a
    pas 0 % de couverture, il n'en a pas."""
    from src.agents.quant.betting_engine.markets import NOT_MEASURED

    vide = measure([])
    assert vide.canonicalization_rate == NOT_MEASURED
    assert vide.model_coverage_rate == NOT_MEASURED
    assert vide.markets == 0


def test_les_parametres_inconnus_sont_signales(inventaire):
    """La sentinelle : une clé jamais cartographiée est le premier signe qu'un
    marché a changé de sens sous nos pieds."""
    couverture = measure(inventaire)
    assert isinstance(couverture.unknown_parameters, dict)
    for ligne in inventaire:
        for cle in ligne.observation.cles_inconnues:
            assert cle in couverture.unknown_parameters


def test_le_vainqueur_d_epreuve_s_accorde_avec_le_mapping_historique(observations):
    """Même exigence que pour MATCH_WINNER, sur la famille qu'on vient de corriger :
    les deux chemins doivent nommer les mêmes marchés."""
    from src.agents.quant.betting_engine.bookmakers.protocol import MarketType
    from src.agents.quant.betting_engine.bookmakers.winamax.market_mapping import map_market

    for obs in observations:
        historique = map_market(obs.bet_type_name or "", obs.template or "",
                                is_outright=obs.is_outright)
        attendu = historique is MarketType.OUTRIGHT_WINNER
        obtenu = classify(obs).family is MarketFamily.OUTRIGHT_WINNER
        assert attendu == obtenu, (obs.bet_type_name, obs.template, obs.is_outright)


def test_les_outrights_restent_a_l_inventaire(observations):
    """`parse_catalog` les écarte faute de rôle opposé ; l'inventaire, lui, ne
    doit jamais les faire disparaître du catalogue."""
    inventaire = build_inventory(observations)
    assert len(inventaire) == len(observations), "aucune observation ne se perd"
    outrights = [r for r in inventaire if r.observation.is_outright]
    for ligne in outrights:
        assert ligne.capability.status in {
            CapabilityStatus.UNSUPPORTED, CapabilityStatus.MODEL_NOT_AVAILABLE}


def test_l_ambiguite_est_un_statut_pas_une_exception():
    """Une source qui se contredit — forme `OverUnder`, pas de seuil — ne doit ni
    lever, ni être devinée : elle est signalée."""
    incoherent = RawMarketObservation(
        bookmaker="winamax", sport="Football", sport_id=1, competition=None,
        competition_source_id=None, source_event_id="e", event_label=None,
        start_time=None, is_outright=False, market_source_id="m",
        bet_type=1, bet_type_name="Plus/Moins", bet_title="", template="OverUnder",
        special_bet_value="variant=1",
        selections=(RawSelectionObservation("1", "over", "Plus", 1.9),
                    RawSelectionObservation("2", "under", "Moins", 1.9)))

    classification = classify(incoherent)
    assert classification.status is ClassificationStatus.AMBIGUOUS
    assert classification.family is MarketFamily.UNMAPPED
    assert "seuil" in classification.evidence
