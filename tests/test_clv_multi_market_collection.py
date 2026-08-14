"""Collecte CLV sur TOUS les marchés d'un événement — un passage, N observations.

Ce que ces tests protègent :

1. le chemin `MATCH_WINNER` historique ne change pas d'un iota ;
2. rien n'est jeté en silence — chaque marché non retenu est compté sous son motif ;
3. l'idempotence porte sur le CONTRAT complet, pas sur la famille ;
4. deux lignes, deux côtés, deux sens du DNB restent des contrats distincts.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from src.agents.quant.betting_engine.bookmakers.protocol import (
    MarketType, RawBookmakerEvent, RawMarket, RawSelection,
)
from src.agents.quant.betting_engine.clv.multi_market import record_all_markets
from src.agents.quant.betting_engine.clv.observation import ObservationPhase

T = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)
COUP_ENVOI = T + timedelta(hours=6)


def _sel(code, cote):
    from src.agents.quant.betting_engine.bookmakers.winamax.market_mapping import map_selection_code
    return RawSelection(code=code, label=f"lbl:{code}", decimal_odds=cote,
                        canonical_selection=map_selection_code(code))


def _marche(bet_type, libelle, template, codes, *, sbv=None, mtype=MarketType.UNMAPPED):
    return RawMarket(market_type=mtype, raw_bet_type=bet_type, raw_label=libelle,
                     template=template, is_live=False, special_bet_value=sbv,
                     selections=[_sel(c, o) for c, o in codes])


#: Un événement réel dans sa forme : le marché principal, plusieurs Plus/Moins,
#: une double chance, un remboursé-si-nul, et des marchés de mi-temps qui doivent
#: être écartés pour incompatibilité de portée.
def _evenement():
    return RawBookmakerEvent(
        bookmaker="winamax", bookmaker_event_id="99", sport="football",
        competition="Serie A", slot_1_name="Genoa", slot_2_name="Napoli",
        slot_1_id="1", slot_2_id="2", start_time=COUP_ENVOI, status="PREMATCH",
        is_outright=False, fetched_at=T, sr_tournament_id=None,
        raw_tournament_id="23",
        markets=[
            _marche(3178, "Résultat", "3way", [("1", 2.5), ("x", 3.2), ("2", 2.8)],
                    mtype=MarketType.MATCH_WINNER),
            _marche(2749, "Nombre de buts", "OverUnder", [("over", 1.9), ("under", 1.95)],
                    sbv="total=2.5"),
            _marche(2749, "Nombre de buts", "OverUnder", [("over", 3.1), ("under", 1.35)],
                    sbv="total=3.5"),
            _marche(3072, "Double chance", "List",
                    [("9", 1.35), ("10", 1.30), ("11", 1.55)]),
            _marche(3535, "Vainqueur (remboursé si match nul)", "2way",
                    [("1", 1.75), ("2", 2.05)]),
            # Portée incompatible : la mi-temps ne porte AUCUN paramètre.
            _marche(3439, "Mi-temps - Vainqueur (remboursé si match nul)", "2way",
                    [("1", 1.9), ("2", 1.9)]),
            _marche(2531, "Mi-temps - Nombre de buts", "OverUnder",
                    [("over", 2.1), ("under", 1.7)], sbv="total=1.5"),
            # Un total de CORNERS : structurellement un `TOTALS` (template
            # OverUnder + seuil + 2 issues), et la règle démontrée le reconnaît
            # comme tel. C'est le `betType` qui le refuse — le modèle de buts
            # n'a rien à dire des corners.
            _marche(5555, "Nombre de corners", "OverUnder", [("over", 1.8), ("under", 1.9)],
                    sbv="total=9.5"),
        ])


class _Store:
    def __init__(self):
        self.observations = []

    def append(self, obs):
        self.observations.append(obs)

    def all(self):
        return list(self.observations)


class _Resolveur:
    """Résolveur d'événement minimal, dans la forme du vrai."""

    class _Mapping:
        bookmaker = "winamax"
        bookmaker_event_id = "99"
        sport = "football"
        canonical_event_id = "event:football:serie_a:2026-08-22T18:00:00Z:away=napoli|home=genoa"
        competition_id = "competition:football:ita:serie_a"
        identity_status = "RESOLVED"
        eligibility_status = "ELIGIBLE"
        confirmed_at = None
        is_usable = True

        class _E:
            def __init__(self, subject, cid):
                self.subject, self.canonical_id = subject, cid

        evidence = (_E("slot_1", "team:football:ita:genoa"),
                    _E("slot_2", "team:football:ita:napoli"))

    def resolve_event(self, raw_event):
        return self._Mapping()


def _collecter(phase=ObservationPhase.DECISION, store=None):
    magasin = store if store is not None else _Store()
    resume = record_all_markets(
        [_evenement()], event_resolver=_Resolveur(), store=magasin,
        phase=phase, source="winamax", run_id="r1")
    return resume, magasin


# ── Ce qui est collecté ──────────────────────────────────────────────────────

def test_plusieurs_familles_sont_collectees_en_un_passage():
    resume, store = _collecter()
    assert resume.events_seen == 1 and resume.events_recorded == 1
    contrats = set(resume.contracts)
    assert contrats == {"MATCH_WINNER", "TOTALS(line=2.5)", "TOTALS(line=3.5)",
                        "DOUBLE_CHANCE", "DRAW_NO_BET"}
    assert resume.selections_written == len(store.observations)


def test_deux_lignes_produisent_deux_contrats_distincts():
    resume, _ = _collecter()
    assert resume.contracts["TOTALS(line=2.5)"] == 2      # over + under
    assert resume.contracts["TOTALS(line=3.5)"] == 2
    assert "TOTALS" not in resume.contracts               # jamais la famille nue


def test_les_deux_cotes_et_les_deux_sens_sont_distincts():
    _, store = _collecter()
    par_contrat = {}
    for o in store.observations:
        par_contrat.setdefault(o.market_type, set()).add(o.selection)
    assert par_contrat["TOTALS(line=2.5)"] == {"over", "under"}
    assert par_contrat["DRAW_NO_BET"] == {"home", "away"}
    assert par_contrat["MATCH_WINNER"] == {"home", "draw", "away"}
    assert par_contrat["DOUBLE_CHANCE"] == {"home_or_draw", "home_or_away", "draw_or_away"}


def test_la_cote_ecrite_est_celle_reellement_observee():
    _, store = _collecter()
    over25 = next(o for o in store.observations
                  if o.market_type == "TOTALS(line=2.5)" and o.selection == "over")
    assert over25.decimal_odds == Decimal("1.9")
    assert isinstance(over25.decimal_odds, Decimal)
    assert over25.observed_at == T and over25.phase is ObservationPhase.DECISION


# ── Rien n'est jeté en silence ───────────────────────────────────────────────

def test_chaque_marche_ecarte_porte_son_motif():
    resume, _ = _collecter()
    assert resume.markets_seen == 8
    # Trois écarts de PORTÉE, tous par le betType : deux mi-temps (qui ne portent
    # aucun paramètre de période) et le total de corners (qui est bien un
    # `TOTALS`, mais pas celui des buts). Aucun marché n'échappe au classement.
    assert resume.markets_skipped_context == 3
    assert resume.markets_rule_unknown == 0
    assert resume.markets_recorded == 5
    somme = (resume.markets_recorded + resume.markets_skipped_context
             + resume.markets_skipped_model + resume.markets_selection_failed
             + resume.markets_rule_unknown + resume.markets_no_odds)
    assert somme == resume.markets_seen, "un marché a disparu sans motif"


def test_un_marche_sans_cote_est_compte_et_non_ecrit():
    from src.agents.quant.betting_engine.clv.multi_market import record_all_markets

    evenement = _evenement()
    evenement.markets.append(
        _marche(2749, "Nombre de buts", "OverUnder", [("over", 0.0), ("under", 0.0)],
                sbv="total=4.5"))
    store = _Store()
    resume = record_all_markets([evenement], event_resolver=_Resolveur(), store=store,
                                phase=ObservationPhase.DECISION, source="winamax")
    assert resume.markets_no_odds == 1
    assert "TOTALS(line=4.5)" not in resume.contracts


# ── Idempotence sur le contrat complet ───────────────────────────────────────

def test_relancer_le_meme_snapshot_n_ecrit_rien_de_plus():
    """L'idempotence est une propriété de la COLLECTE répétée. Le filtre du
    collecteur la porte ; ici on vérifie que la CLÉ est bien le contrat complet."""
    from src.agents.quant.betting_engine.clv.collect import _StoreFiltrant

    store = _Store()
    connues = set()
    for _ in range(3):
        filtre = _StoreFiltrant(store, connues)
        record_all_markets([_evenement()], event_resolver=_Resolveur(), store=filtre,
                           phase=ObservationPhase.DECISION, source="winamax")
    assert len({(o.market_type, o.selection) for o in store.observations}) == len(store.observations)
    assert len(store.observations) == 12       # 3 + 2 + 2 + 3 + 2


def test_deux_lignes_ne_se_dedupliquent_pas_l_une_l_autre():
    from src.agents.quant.betting_engine.clv.collect import _StoreFiltrant

    store, connues = _Store(), set()
    filtre = _StoreFiltrant(store, connues)
    record_all_markets([_evenement()], event_resolver=_Resolveur(), store=filtre,
                       phase=ObservationPhase.DECISION, source="winamax")
    lignes = {o.market_type for o in store.observations if o.market_type.startswith("TOTALS")}
    assert lignes == {"TOTALS(line=2.5)", "TOTALS(line=3.5)"}


# ── Non-régression du chemin historique ──────────────────────────────────────

def test_match_winner_identique_au_chemin_historique():
    """Le marché principal doit sortir EXACTEMENT comme le collecteur d'origine
    l'écrivait : même identité, mêmes sélections, mêmes cotes."""
    from src.agents.quant.betting_engine.clv.recorder import record_odds

    ancien, nouveau = _Store(), _Store()
    record_odds([_evenement()], event_resolver=_Resolveur(), store=ancien,
                phase=ObservationPhase.DECISION, source="winamax")
    record_all_markets([_evenement()], event_resolver=_Resolveur(), store=nouveau,
                       phase=ObservationPhase.DECISION, source="winamax")

    def _cle(obs):
        return (obs.event_id, obs.market_type, obs.selection, obs.bookmaker,
                obs.decimal_odds, obs.phase)

    anciennes = {_cle(o) for o in ancien.observations}
    assert anciennes, "le chemin historique doit produire quelque chose"
    assert anciennes <= {_cle(o) for o in nouveau.observations}


def test_le_recorder_historique_n_est_pas_modifie():
    """Aucun appel du nouveau chemin ne doit avoir été ajouté dans l'ancien."""
    import inspect

    from src.agents.quant.betting_engine.clv import recorder

    source = inspect.getsource(recorder)
    for interdit in ("record_all_markets", "identite_contrat", "canonicaliser_selections"):
        assert interdit not in source, interdit


# ── Garde de clôture ─────────────────────────────────────────────────────────

def test_une_cloture_apres_le_coup_d_envoi_est_refusee_pour_tous_les_marches():
    """Une cote de direct n'est une ligne de clôture pour AUCUN marché."""
    evenement = _evenement()
    evenement = RawBookmakerEvent(
        **{**evenement.__dict__, "fetched_at": COUP_ENVOI + timedelta(minutes=5)})
    store = _Store()
    resume = record_all_markets([evenement], event_resolver=_Resolveur(), store=store,
                                phase=ObservationPhase.CLOSING, source="winamax")
    assert resume.events_started == 1
    assert not store.observations


# ── DECISION -> CLOSING : la paire se forme sur le contrat, pas sur la famille ──

def _evenement_a(instant, *, ligne=2.5, cote_over=1.90):
    """Le même événement, observé à un autre instant et à une autre cote."""
    base = _evenement()
    marches = [m for m in base.markets if m.raw_bet_type != 2749 or "total=3.5" == m.special_bet_value]
    marches = [m for m in base.markets if not (m.raw_bet_type == 2749 and m.special_bet_value == "total=2.5")]
    marches.append(_marche(2749, "Nombre de buts", "OverUnder",
                           [("over", cote_over), ("under", 1.95)], sbv=f"total={ligne}"))
    return RawBookmakerEvent(**{**base.__dict__, "fetched_at": instant, "markets": marches})


def test_une_paire_clv_se_forme_sur_le_meme_contrat():
    """Décision puis clôture, même ligne : la paire existe et la CLV se calcule.

    Le temps qui passe est simulé par l'instant d'observation — c'est la seule
    chose que la collecte lise. Les fenêtres d'admissibilité, elles, sont celles
    de production et ne sont pas touchées.
    """
    from src.agents.quant.betting_engine.clv.clv import clv_readiness

    store = _Store()
    decision = _evenement_a(COUP_ENVOI - timedelta(hours=6), cote_over=1.90)
    cloture = _evenement_a(COUP_ENVOI - timedelta(minutes=10), cote_over=1.72)

    record_all_markets([decision], event_resolver=_Resolveur(), store=store,
                       phase=ObservationPhase.DECISION, source="winamax")
    record_all_markets([cloture], event_resolver=_Resolveur(), store=store,
                       phase=ObservationPhase.CLOSING, source="winamax")

    lecture = clv_readiness([o for o in store.observations
                             if o.market_type == "TOTALS(line=2.5)" and o.selection == "over"])
    assert lecture.n_complete_pairs == 1
    assert lecture.mean_clv is not None and lecture.mean_clv > 0     # 1.90 -> 1.72


def test_une_ligne_deplacee_ne_s_apparie_pas():
    """Décision sur 2.5, clôture sur 4.5 : deux contrats, aucune paire. Les deux
    observations restent enregistrées — le mouvement de ligne est une information,
    pas une CLV.

    Les deux lignes choisies sont des demi-lignes VALIDÉES : une ligne entière
    (3.0) serait de toute façon refusée par la capacité, et le test ne prouverait
    alors que cette autre règle."""
    from src.agents.quant.betting_engine.clv.clv import clv_readiness
    from src.agents.quant.betting_engine.clv.contract import LINE_MOVEMENT, classer_mouvement

    store = _Store()
    record_all_markets([_evenement_a(COUP_ENVOI - timedelta(hours=6), ligne=2.5)],
                       event_resolver=_Resolveur(), store=store,
                       phase=ObservationPhase.DECISION, source="winamax")
    record_all_markets([_evenement_a(COUP_ENVOI - timedelta(minutes=10), ligne=4.5)],
                       event_resolver=_Resolveur(), store=store,
                       phase=ObservationPhase.CLOSING, source="winamax")

    contrats = {o.market_type for o in store.observations}
    assert "TOTALS(line=2.5)" in contrats and "TOTALS(line=4.5)" in contrats

    croisement = [o for o in store.observations
                  if o.market_type in ("TOTALS(line=2.5)", "TOTALS(line=4.5)")
                  and o.selection == "over"]
    assert clv_readiness(croisement).n_complete_pairs == 0
    assert classer_mouvement("TOTALS(line=2.5)", "TOTALS(line=4.5)").kind == LINE_MOVEMENT


def test_une_decision_sans_cloture_reste_une_decision():
    """Marché présent à la décision, disparu à la clôture : on garde la décision,
    on ne fabrique aucune clôture."""
    from src.agents.quant.betting_engine.clv.clv import clv_readiness

    store = _Store()
    record_all_markets([_evenement_a(COUP_ENVOI - timedelta(hours=6))],
                       event_resolver=_Resolveur(), store=store,
                       phase=ObservationPhase.DECISION, source="winamax")
    sans_totals = RawBookmakerEvent(**{
        **_evenement().__dict__, "fetched_at": COUP_ENVOI - timedelta(minutes=10),
        "markets": [m for m in _evenement().markets if m.raw_bet_type != 2749]})
    record_all_markets([sans_totals], event_resolver=_Resolveur(), store=store,
                       phase=ObservationPhase.CLOSING, source="winamax")

    totals = [o for o in store.observations if o.market_type.startswith("TOTALS")]
    assert totals and all(o.phase is ObservationPhase.DECISION for o in totals)
    assert clv_readiness(totals).n_complete_pairs == 0
