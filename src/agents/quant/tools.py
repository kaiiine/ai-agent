"""Tools LangChain du module value betting (axon-quant).

REROUTE_VERS_STRUCTURE (ADR legacy) : ces tools sont désormais de MINCES wrappers
au-dessus du pipeline STRUCTURÉ (`structured_decision` -> Betting Engine / Advisor).
Ils ne calculent JAMAIS eux-mêmes une probabilité, un EV, un edge, une proba jointe,
un Kelly ni une « value ». Il n'existe plus de seconde pile de décision betting.

Invariants (traversent jusqu'au rendu) :
- ABSTAIN structuré -> ABSTAIN outil. Une cote basse n'est JAMAIS « value » sans
  `fair_probability` d'un modèle. Le cap BE-FR-011 (non-SUPPORTED ⇒ jamais BET) tient.
- Marché sans modèle structuré (over/under, BTTS, …) -> `MARKET_UNAVAILABLE`.
- Aucun import de `dixon_coles` / `ev_engine` / `probability_engine` ici (garde-fou
  testé : `tests/test_legacy_reroute.py`).
"""

from __future__ import annotations
import json

from langchain_core.tools import tool

from src.agents.quant.structured_decision import (
    EVALUATED,
    MARKET_UNAVAILABLE,
    MatchDecision,
    SelectionDecision,
    decide_match,
    decide_single,
)


# ── Rendu (JSON-able) des décisions structurées ───────────────────────────────
def _selection_payload(sd: SelectionDecision) -> dict:
    return {
        "selection": sd.selection,
        "decision": sd.decision,                       # BET | ABSTAIN (jamais BET hors SUPPORTED)
        "bookmaker_odds": sd.bookmaker_odds,
        "fair_probability": sd.fair_probability,
        "confidence_interval": list(sd.probability_interval) if sd.probability_interval else None,
        "expected_value": sd.expected_value,           # audit ; jamais présenté comme « value » sûre
        "worst_case_ev": sd.worst_case_ev,
        "no_vig_probability": sd.no_vig_probability,
        "edge": sd.edge,
        "reasons": list(sd.reasons),
    }


def _match_meta(md: MatchDecision) -> dict:
    return {"home": md.home_team, "away": md.away_team,
            "competition": md.competition, "bookmaker": md.bookmaker}


@tool("winamax_odds_fetch")
def winamax_odds_fetch(sport: str = "football", team: str = "") -> str:
    """Récupère les cotes Winamax en temps réel (PRIMITIVE DATA — aucune décision).

    Passe par l'UNIQUE source canonique (WinamaxConnector -> PRELOADED_STATE -> parser),
    la MÊME que coverage/recommend/record-odds. Cotes SCHEMA-AWARE : 2-way (tennis,
    basket…) ou 3-way (foot, hockey) — jamais un `draw` fabriqué. Retourne les cotes
    brutes + la probabilité IMPLICITE (1/cote, marge INCLUSE — ni no-vig ni edge).

    Args:
        sport: football, tennis, basketball, hockey, rugby, baseball, volleyball… (défaut football)
        team: filtre optionnel sur un nom de participant (ex: "PSG", "Sinner")
    Returns:
        JSON des matchs avec cotes vainqueur horodatées + implied_probability (brute)
    """
    from src.agents.quant.betting_engine.bookmakers.winamax.odds_quotes import fetch_odds_quotes
    from src.agents.quant.betting_engine.value_engine import margin_removal
    try:
        quotes = fetch_odds_quotes(sport, team)
        if not quotes:
            return json.dumps({"status": "empty", "message": f"Aucun match trouvé ({sport}, filtre: {team or 'aucun'})"})
        matches = [
            {
                "match_id": q.match_id, "competition": q.competition,
                "slot_1": q.slot_1_name, "slot_2": q.slot_2_name,
                "start_time": q.start_time, "status": q.status,
                "odds": q.odds,
                # Implicite = 1/cote (marge incluse) via la primitive CANONIQUE, sur les
                # seules sélections PRÉSENTES (aucun None -> plus de TypeError 2-way).
                "implied_probability": {k: round(margin_removal.implied_raw(v), 4) for k, v in q.odds.items()},
                "bookmaker": q.bookmaker, "fetched_at": q.fetched_at,
            }
            for q in quotes
        ]
        return json.dumps({"status": "ok", "count": len(matches), "matches": matches[:20]}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"status": "error", "error": str(e), "message": "Cotes indisponibles — ne pas inventer de cotes."})


@tool("sports_stats_fetch")
def sports_stats_fetch(home_team: str, away_team: str) -> str:
    """Récupère la forme récente de deux équipes (PRIMITIVE DATA — aucune décision).

    Ne recalcule AUCUNE décision betting : sert uniquement à exposer la donnée de
    forme. La décision passe par `ev_analyze` (pipeline structuré).
    Nécessite FOOTBALL_DATA_ORG_KEY et/ou API_FOOTBALL_KEY dans .env.

    Args:
        home_team: équipe à domicile (ex: "PSG")
        away_team: équipe à l'extérieur (ex: "Marseille")
    Returns:
        JSON {home_form, away_form}
    """
    from src.agents.quant.gateway import gateway
    try:
        home = gateway.search_team(home_team)
        away = gateway.search_team(away_team)
        if not home or not away:
            missing = home_team if not home else away_team
            return json.dumps({"status": "error", "message": f"Équipe introuvable (v1 : Ligue 1, Premier League) : {missing}"})
        return json.dumps({
            "status": "ok",
            "home": home,
            "away": away,
            "home_form": gateway.recent_form(home["canonical_id"]),
            "away_form": gateway.recent_form(away["canonical_id"]),
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"status": "error", "error": str(e), "message": "Stats indisponibles — ne pas inventer de stats."})


@tool("probability_compute")
def probability_compute(home_team: str, away_team: str, model: str = "structured") -> str:
    """Probabilités 1X2 d'un match — via le MODÈLE STRUCTURÉ du Betting Engine.

    Ne possède plus de moteur probabiliste parallèle : délègue à `decide_match`
    (evaluate_live_event). Si aucun modèle/données ne s'applique -> statut explicite
    (MODEL_UNAVAILABLE / IDENTITY_UNRESOLVED / …), JAMAIS un fallback legacy.
    Le paramètre `model` est ignoré (un seul modèle structuré fait foi).

    Args:
        home_team: équipe à domicile
        away_team: équipe à l'extérieur
        model: ignoré (conservé pour compat) — le modèle structuré fait foi
    Returns:
        JSON {status, probabilities par sélection (fair + intervalle), source}
    """
    try:
        md = decide_match(home_team, away_team)
        meta = _match_meta(md)
        if not md.evaluated:
            return json.dumps({"status": md.status, "message": md.detail, "source": "betting_engine", **meta},
                              ensure_ascii=False)
        probs = {sel: {"fair_probability": sd.fair_probability,
                       "confidence_interval": list(sd.probability_interval) if sd.probability_interval else None}
                 for sel, sd in md.selections.items()}
        return json.dumps({"status": "ok", "source": "betting_engine", "model": "one_x_two.dixon_coles.v0 (EXPERIMENTAL)",
                           "probabilities": probs,
                           "caveat": "Modèle EXPERIMENTAL — aucune mise réelle. Intervalle à toujours restituer.",
                           **meta}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"status": "error", "error": str(e)})


@tool("ev_analyze")
def ev_analyze(
    home_team: str,
    away_team: str,
    market: str,
    odds: float,
    bankroll: float = 100.0,
) -> str:
    """Décision BET/ABSTAIN d'un marché — 100 % via le pipeline STRUCTURÉ.

    Ne recalcule PLUS indépendamment fair_probability / edge / EV / Kelly / mise :
    délègue à `decide_single` (Betting Engine). La décision utilise les VRAIES cotes
    du catalogue (jamais une cote saisie). Si le structuré dit ABSTAIN -> ABSTAIN ;
    marché hors modèle -> MARKET_UNAVAILABLE. Aucune « value » sur cote seule.
    Marchés modélisés : home, draw, away (MATCH_WINNER). over/under/BTTS -> non modélisés.

    Args:
        home_team: équipe à domicile
        away_team: équipe à l'extérieur
        market: marché (home/draw/away ; autres -> MARKET_UNAVAILABLE)
        odds: cote observée par l'utilisateur (INDICATIVE — la décision utilise la cote du catalogue)
        bankroll: bankroll en euros (le sizing réel vit dans l'Advisor, sur modèle SUPPORTED)
    Returns:
        JSON {status, decision, structured metrics, reasons}
    """
    try:
        md, sd = decide_single(home_team, away_team, market)
        meta = _match_meta(md)
        if sd is None:
            # Marché non modélisé, identité non résolue, événement absent, modèle indispo…
            return json.dumps({"status": md.status, "decision": "ABSTAIN", "market": market,
                               "message": md.detail, "requested_odds": odds, "source": "betting_engine",
                               **meta}, ensure_ascii=False)
        payload = {"status": EVALUATED, "market": market, "requested_odds": odds,
                   "source": "betting_engine", **meta, **_selection_payload(sd)}
        if sd.decision != "BET":
            payload["message"] = "Pas de BET structuré — ne pas recommander ce pari (modèle EXPERIMENTAL / edge non confirmé)."
        return json.dumps(payload, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"status": "error", "error": str(e)})


# ── Combos : refus de toute math combinée locale (pricing/sizing = Combo Builder) ─
def _combo_verdict(legs: list[dict]) -> dict:
    """Évalue chaque jambe via le pipeline STRUCTURÉ. Ne calcule JAMAIS de proba
    jointe, d'EV combiné ni de Kelly combiné (ce serait la seconde formule bannie).

    Un combiné n'est « BET » que si TOUTES les jambes sont un BET structuré ; sinon
    ABSTAIN. Le pricing/sizing d'un combiné admissible appartient exclusivement au
    Combo Builder structuré (`axon recommend --allow-combos`, ADR-ADV-014) — ce tool
    ne price rien.
    """
    leg_results = []
    all_bet = True
    for leg in legs:
        md, sd = decide_single(leg["home_team"], leg["away_team"], leg["market"])
        if sd is None:
            all_bet = False
            leg_results.append({"leg": leg, "status": md.status, "decision": "ABSTAIN", "message": md.detail,
                                **_match_meta(md)})
        else:
            all_bet = all_bet and (sd.decision == "BET")
            leg_results.append({"leg": leg, "status": EVALUATED, **_match_meta(md), **_selection_payload(sd)})

    if all_bet and leg_results:
        return {"status": "ok", "combo_decision": "ALL_LEGS_BET", "legs": leg_results,
                "message": ("Toutes les jambes sont un BET structuré. Le pricing et le sizing du combiné "
                            "sont délégués au Combo Builder structuré : `axon recommend --allow-combos` "
                            "(ADR-ADV-014). Ce tool ne price aucun combiné.")}
    return {"status": "ok", "combo_decision": "ABSTAIN", "legs": leg_results,
            "message": "Au moins une jambe n'est pas un BET structuré — ne pas recommander ce combiné."}


@tool("same_match_combo_analyze")
def same_match_combo_analyze(
    home_team: str,
    away_team: str,
    markets_json: str,
    odds: float,
    bankroll: float = 100.0,
) -> str:
    """Combiné INTRA-match — via le pipeline STRUCTURÉ (aucune proba jointe locale).

    Ne calcule plus la matrice de scores ni la proba jointe : chaque marché est
    évalué structurellement, et le combiné est refusé tant que toutes les jambes ne
    sont pas un BET structuré. Le pricing/sizing appartient au Combo Builder.

    Args:
        home_team, away_team: équipes
        markets_json: JSON d'une liste de marchés, ex: '["home", "away"]'
        odds: cote observée du combiné (indicative)
        bankroll: bankroll (sizing = Advisor/Combo Builder, pas ce tool)
    Returns:
        JSON {combo_decision, legs (décisions structurées)}
    """
    try:
        markets = json.loads(markets_json)
        legs = [{"home_team": home_team, "away_team": away_team, "market": m} for m in markets]
        out = _combo_verdict(legs)
        out["requested_combo_odds"] = odds
        return json.dumps(out, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"status": "error", "error": str(e)})


@tool("parlay_analyze")
def parlay_analyze(legs_json: str, bankroll: float = 100.0) -> str:
    """Combiné multi-matchs (parlay) — via le pipeline STRUCTURÉ.

    Ne calcule plus d'EV/Kelly de combiné ni de fusion intra-match maison : chaque
    jambe passe par `decide_single` (Betting Engine). Le combiné n'est « BET » que si
    toutes les jambes le sont ; le pricing/sizing appartient au Combo Builder
    structuré (`axon recommend --allow-combos`, ADR-ADV-014).

    Args:
        legs_json: JSON d'une liste de legs :
            [{"home_team": "PSG", "away_team": "Lyon", "market": "home"},
             {"home_team": "Arsenal", "away_team": "Chelsea", "market": "away"}]
        bankroll: bankroll (sizing = Advisor/Combo Builder)
    Returns:
        JSON {combo_decision, legs (décisions structurées)}
    """
    try:
        raw_legs = json.loads(legs_json)
        if len(raw_legs) < 2:
            return json.dumps({"status": "error", "message": "Un combiné doit avoir au moins 2 sélections"})
        out = _combo_verdict(raw_legs)
        return json.dumps(out, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"status": "error", "error": str(e)})
