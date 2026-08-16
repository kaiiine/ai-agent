"""Le CONTRAT d'une prop de joueur : ce qui change le payoff entre dans l'identité.

Canonicaliser une famille, c'est promettre deux choses : qu'on sait régler le
pari, et que deux paris économiquement différents ne se confondront jamais. La
seconde est la plus facile à rater — deux marchés de signature structurelle
identique peuvent avoir des règlements opposés, et une identité CLV partagée
apparierait alors une cote avec la clôture d'un autre contrat.

Deux cas mesurés portent ce risque :

- `betType 5595` (« Duo marqueurs ») règle sur une SOMME, `5594` (« Double
  chance marqueurs ») sur une DISJONCTION. Même template, mêmes clés typées,
  même arité. Seul le betType les sépare ;
- `betType 3361` livre ses paliers dans le CODE d'issue
  (`pre:playerprops:event:joueur:seuil`), pas dans le specialBetValue. Un marché
  « 1+/2+ » et un marché « 3+ » du même joueur sont deux contrats distincts.

S'y ajoute l'interdit du §4 : ces marchés ne partitionnent rien, donc la marge
du bookmaker n'y est pas mesurable et `vig_adjusted_probability` reste None.
"""

from __future__ import annotations

import pytest

from src.agents.quant.betting_engine.markets.families import (
    ClassificationStatus, MarketFamily, classify,
)
from src.agents.quant.betting_engine.markets.observation import (
    RawMarketObservation, RawSelectionObservation,
)


def _sel(code, label=None, sr=None):
    s = RawSelectionObservation(source_selection_id=None, code=code, label=label,
                                decimal_odds=None)
    if sr is not None:
        object.__setattr__(s, "sr_player_id", sr)
    return s


def _obs(**kw) -> RawMarketObservation:
    base = dict(
        bookmaker="winamax", sport="football", sport_id=None, competition=None,
        competition_source_id=None, source_event_id="66299348", event_label=None,
        start_time=None, is_outright=False, market_source_id=None,
        bet_type=3361, bet_type_name="Nombre de passes décisives",
        bet_title=None, template="dynamic",
        special_bet_value="variant=pre:playerprops:66299348:1412183",
        selections=(_sel("pre:playerprops:66299348:1412183:1", "Jon Gallagher 1+"),
                    _sel("pre:playerprops:66299348:1412183:2", "Jon Gallagher 2+")))
    base.update(kw)
    return RawMarketObservation(**base)


def _prop_typee(bet_type, sbv, sport="basketball", nom="x"):
    return _obs(sport=sport, bet_type=bet_type, bet_type_name=nom,
                special_bet_value=sbv, selections=(_sel("over", "Plus de 9,5"),))


# ══ 1 · L'identité porte tout ce qui change le payoff ══════════════════════
def test_le_palier_porte_joueur_statistique_et_seuils():
    c = classify(_obs())

    assert c.family is MarketFamily.PLAYER_PROP
    assert c.status is ClassificationStatus.CANONICALIZED
    assert c.parameters["player"] == "sr:player:1412183"
    assert c.parameters["statistic"] == "ASSISTS"
    assert c.parameters["thresholds"] == "1,2"
    assert c.parameters["n_players"] == 1
    assert c.parameters["threshold_form"] == "CUMULATIVE"


def test_deux_jeux_de_paliers_du_meme_joueur_ne_partagent_pas_d_identite():
    """« 1+/2+ » et « 3+ » sont deux contrats : le second ne se règle pas comme
    le premier, et une identité commune apparierait deux clôtures étrangères."""
    a = classify(_obs())
    b = classify(_obs(selections=(_sel("pre:playerprops:66299348:1412183:3",
                                       "Jon Gallagher 3+"),)))

    assert a.parameters["thresholds"] != b.parameters["thresholds"]


def test_deux_joueurs_ne_partagent_jamais_une_identite():
    a = classify(_obs())
    b = classify(_obs(
        special_bet_value="variant=pre:playerprops:66299348:1957439",
        selections=(_sel("pre:playerprops:66299348:1957439:1"),
                    _sel("pre:playerprops:66299348:1957439:2"))))

    assert a.parameters["player"] != b.parameters["player"]


def test_la_statistique_vient_du_bet_type_pas_du_libelle():
    """Le libellé peut mentir ou changer de formulation ; le betType est le seul
    discriminant structuré de la statistique."""
    c = classify(_obs(bet_type_name="LIBELLÉ COMPLÈTEMENT DIFFÉRENT"))

    assert c.parameters["statistic"] == "ASSISTS"


def test_un_bet_type_sans_statistique_demontree_reste_non_mappe():
    """Lire le code ne suffit pas : si la statistique n'est pas établie pour ce
    betType, on conserve le marché sans le nommer."""
    c = classify(_obs(bet_type=999999))

    assert c.family is MarketFamily.UNMAPPED
    assert c.status is ClassificationStatus.AMBIGUOUS


# ══ 2 · Le règlement sépare des signatures identiques ══════════════════════
@pytest.mark.parametrize("bet_type, mode", [
    (5595, "SUM"),          # Duo marqueurs de points
    (5596, "SUM"),          # Trio marqueurs de points
    (5594, "ANY"),          # Double chance marqueurs — disjonction
    (5702, "SUM"),          # Duo Buteurs
    (5703, "SUM"),          # Trio Buteurs
])
def test_le_mode_de_reglement_entre_dans_l_identite(bet_type, mode):
    c = classify(_prop_typee(
        bet_type, "players=sr:player:1148330-sr:player:2245159|total=24.5"))

    assert c.family is MarketFamily.PLAYER_COMBO_PROP
    assert c.parameters["settlement_mode"] == mode


def test_somme_et_disjonction_ne_partagent_jamais_une_identite():
    """Le cas le plus dangereux du lot : `Duo marqueurs` et `Double chance
    marqueurs` ont la MÊME signature structurelle et des payoffs opposés."""
    sbv = "players=sr:player:1148330-sr:player:2245159|total=24.5"
    somme = classify(_prop_typee(5595, sbv))
    disjonction = classify(_prop_typee(5594, sbv))

    assert somme.parameters != disjonction.parameters
    assert somme.parameters["settlement_mode"] != disjonction.parameters["settlement_mode"]


def test_le_nombre_de_joueurs_entre_dans_l_identite():
    duo = classify(_prop_typee(
        5595, "players=sr:player:1-sr:player:2|total=24.5"))
    trio = classify(_prop_typee(
        5596, "players=sr:player:1-sr:player:2-sr:player:3|total=49.5"))

    assert duo.parameters["n_players"] == 2
    assert trio.parameters["n_players"] == 3


def test_la_ligne_entre_dans_l_identite():
    a = classify(_prop_typee(5598, "player=sr:player:1148330|total=9.5"))
    b = classify(_prop_typee(5598, "player=sr:player:1148330|total=10.5"))

    assert a.parameters["line"] != b.parameters["line"]


def test_la_portee_entre_dans_l_identite():
    """Un total de mi-temps n'est pas le total de la rencontre."""
    entier = classify(_prop_typee(5598, "player=sr:player:1|total=9.5"))
    mi_temps = classify(_prop_typee(5598, "player=sr:player:1|total=9.5|periodnr=1"))

    assert entier.parameters != mi_temps.parameters
    assert mi_temps.parameters.get("periodnr") == "1"


# ══ 3 · Une identité à moitié démontrée est refusée ════════════════════════
def test_des_issues_qui_ne_s_accordent_pas_sur_le_joueur_sont_refusees():
    c = classify(_obs(selections=(_sel("pre:playerprops:66299348:1412183:1"),
                                  _sel("pre:playerprops:66299348:9999999:2"))))

    assert c.family is MarketFamily.UNMAPPED


def test_le_champ_type_srplayerid_sert_de_contre_preuve():
    """Deux sources structurées en désaccord ne se départagent pas au libellé."""
    c = classify(_obs(selections=(
        _sel("pre:playerprops:66299348:1412183:1", sr="sr:player:1412183"),
        _sel("pre:playerprops:66299348:1412183:2", sr="sr:player:AUTRE"))))

    assert c.family is MarketFamily.UNMAPPED


def test_une_issue_hors_forme_invalide_le_marche_entier():
    c = classify(_obs(selections=(_sel("pre:playerprops:66299348:1412183:1"),
                                  _sel("autre_chose"))))

    assert c.family is MarketFamily.UNMAPPED


# ══ 4 · Aucun no-vig sans partition ════════════════════════════════════════
@pytest.mark.parametrize("famille", [
    MarketFamily.PLAYER_PROP, MarketFamily.PLAYER_COMBO_PROP])
def test_une_prop_n_a_pas_de_masse_attendue(famille):
    """Sans masse connue vers laquelle normaliser, la marge n'est pas mesurable
    depuis l'intérieur du marché."""
    from src.agents.quant.betting_engine.markets.pricing import MarketPricing

    pricing = MarketPricing(event_id='e', sport='football', family=famille)

    assert pricing.masse_attendue is None


def test_deux_paliers_emboites_ne_produisent_jamais_de_no_vig():
    """« 1+ » et « 2+ » ne sont pas complémentaires : le second IMPLIQUE le
    premier. Les normaliser vers 1 fabriquerait un prix sans marge qui ne
    correspond à rien, puis un edge, puis une EV."""
    from src.agents.quant.betting_engine.markets.pricing import (
        MarketPricing, PricedSelection,
    )

    pricing = MarketPricing(
        family=MarketFamily.PLAYER_PROP,
        event_id="e", sport="football",
        selections=(PricedSelection("1", 0.5, 0.5), PricedSelection("2", 0.3, 0.3)))

    price = pricing.with_market_odds({"1": 1.5, "2": 3.0})

    for s in price.selections:
        assert s.vig_adjusted_probability is None, "aucune marge retirée sans partition"


def test_un_marche_qui_partitionne_garde_son_no_vig():
    """Non-régression : le garde du §4 ne doit toucher aucune famille qui
    partitionne réellement."""
    from src.agents.quant.betting_engine.markets.pricing import (
        MarketPricing, PricedSelection,
    )

    pricing = MarketPricing(
        family=MarketFamily.TOTALS,
        event_id="e", sport="football",
        selections=(PricedSelection("over", 0.5, 0.5),
                    PricedSelection("under", 0.5, 0.5)))

    price = pricing.with_market_odds({"over": 2.0, "under": 2.0})

    assert all(s.vig_adjusted_probability is not None for s in price.selections)


def test_aucun_complement_n_est_fabrique():
    """Ni cote opposée, ni issue `under` inventée, ni masse normalisée fictive."""
    from src.agents.quant.betting_engine.markets.pricing import (
        MarketPricing, PricedSelection,
    )

    pricing = MarketPricing(
        family=MarketFamily.PLAYER_PROP,
        event_id="e", sport="football",
        selections=(PricedSelection("over", 0.5, 0.5),))

    price = pricing.with_market_odds({"over": 1.9})

    assert len(price.selections) == 1, "aucune issue n'est ajoutée"
    assert price.selections[0].vig_adjusted_probability is None


# ══ 5 · Canonicalisé n'est pas modélisable ════════════════════════════════
def test_canonicaliser_ne_rend_aucune_probabilite_disponible():
    """CANONICALIZED != MODEL_AVAILABLE. Aucun modèle de statistique de joueur
    n'est validé pour le football ni pour le basket : le contrat est lisible, la
    probabilité ne l'est pas."""
    from src.agents.quant.betting_engine.markets import capability

    source = __import__("inspect").getsource(capability)
    for famille in ("PLAYER_PROP", "PLAYER_COMBO_PROP"):
        assert f"MarketFamily.{famille}" not in source, (
            f"{famille} ne doit déclarer AUCUNE capacité de modèle")
