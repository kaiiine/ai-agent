"""Tools LangChain du module value betting (axon-quant).

Le LLM orchestre ces tools mais ne calcule JAMAIS une probabilité lui-même.
"""

from __future__ import annotations
import json

from langchain_core.tools import tool


@tool("winamax_odds_fetch")
def winamax_odds_fetch(sport: str = "football", team: str = "") -> str:
    """Récupère les cotes Winamax en temps réel.

    Utilise ce tool quand l'utilisateur veut :
    - connaître les cotes d'un match ou d'un sport
    - analyser un pari sportif (première étape obligatoire)

    Mots-clés : cotes, winamax, pari, match, prono, bookmaker

    Args:
        sport: football, tennis, basketball ou rugby (défaut football)
        team: filtre optionnel sur un nom d'équipe (ex: "PSG")
    Returns:
        JSON des matchs avec cotes 1N2 horodatées
    """
    from src.agents.quant.gateway.providers.odds_provider import WinamaxOddsProvider
    from src.agents.quant.ev_engine import no_vig_probabilities
    try:
        quotes = WinamaxOddsProvider().fetch_matches(sport, team)
        if not quotes:
            return json.dumps({"status": "empty", "message": f"Aucun match trouvé ({sport}, filtre: {team or 'aucun'})"})
        matches = [
            {
                "match_id": q.match_id, "competition": q.competition,
                "home": q.home_team, "away": q.away_team,
                "start_time": q.start_time, "status": q.status,
                "odds": q.odds, "no_vig_probability": no_vig_probabilities(q.odds),
                "bookmaker": q.bookmaker, "fetched_at": q.fetched_at,
            }
            for q in quotes
        ]
        return json.dumps({"status": "ok", "count": len(matches), "matches": matches[:20]}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"status": "error", "error": str(e), "message": "Cotes indisponibles — ne pas inventer de cotes."})


@tool("sports_stats_fetch")
def sports_stats_fetch(home_team: str, away_team: str) -> str:
    """Récupère la forme récente de deux équipes (Ligue 1, Premier League en v1).

    Utilise ce tool pour obtenir les données nécessaires au calcul de probabilité.
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
def probability_compute(home_team: str, away_team: str, model: str = "dixon_coles") -> str:
    """Calcule les probabilités d'un match (modèle statistique, PAS le LLM).

    Modèle par défaut : Dixon-Coles (Poisson bivarié) — donne 1N2, over/under
    1.5/2.5/3.5, BTTS et les 5 scores exacts les plus probables.
    Fallback : "elo" — 1N2 uniquement, plus simple.

    Retourne les probas avec intervalle de confiance à 90%.
    TOUJOURS restituer l'intervalle, jamais un chiffre sec.

    Args:
        home_team: équipe à domicile
        away_team: équipe à l'extérieur
        model: "dixon_coles" (défaut) ou "elo"
    Returns:
        JSON {probabilities, confidence_90, strengths, sample_size}
    """
    from src.agents.quant.gateway import gateway
    try:
        home = gateway.search_team(home_team)
        away = gateway.search_team(away_team)
        if not home or not away:
            missing = home_team if not home else away_team
            return json.dumps({"status": "error", "message": f"Équipe introuvable (v1 : Ligue 1, Premier League) : {missing}"})

        home_form = gateway.recent_form(home["canonical_id"])
        away_form = gateway.recent_form(away["canonical_id"])

        if model == "elo":
            from src.agents.quant.probability_engine import probabilities_with_confidence
            result = probabilities_with_confidence(home_form, away_form)
            result["model"] = "elo_dynamique"
        else:
            from src.agents.quant.dixon_coles import dixon_coles_probabilities
            ratings = gateway.opponent_ratings_for_form(home_form + away_form)
            result = dixon_coles_probabilities(home_form, away_form, opponent_ratings=ratings or None)
            result["model"] = "poisson_dc"  # Poisson forme + correction DC, pas le MLE ligue complet

        result["status"] = "ok"
        result["caveat"] = (
            "Le modèle ne capture pas : blessures de dernière minute, météo, "
            "enjeu psychologique, compos. À rappeler à l'utilisateur."
        )
        return json.dumps(result, ensure_ascii=False)
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
    """Calcule la probabilité (Poisson-DC) d'un marché et décide BET/WATCH/ABSTAIN.

    Le calcul de probabilité se fait ENTIÈREMENT ici — ne jamais lui donner une
    probabilité devinée ou recopiée d'un autre message.
    Marchés : home, draw, away, over_1_5/2_5/3_5, under_1_5/2_5/3_5, btts_yes, btts_no.

    Args:
        home_team: équipe à domicile
        away_team: équipe à l'extérieur
        market: marché à analyser (ex: "home", "over_2_5")
        odds: cote Winamax de ce marché
        bankroll: bankroll de l'utilisateur en euros (défaut 100)
    Returns:
        JSON avec probabilité, incertitude, décision (BET/WATCH/ABSTAIN) et mise recommandée
    """
    from src.agents.quant.gateway import gateway
    from src.agents.quant.dixon_coles import market_probability
    from src.agents.quant.ev_engine import analyze_bet
    try:
        home = gateway.search_team(home_team)
        away = gateway.search_team(away_team)
        if not home or not away:
            missing = home_team if not home else away_team
            return json.dumps({"status": "error", "message": f"Équipe introuvable (v1 : Ligue 1, Premier League) : {missing}"})

        home_form = gateway.recent_form(home["canonical_id"])
        away_form = gateway.recent_form(away["canonical_id"])
        ratings = gateway.opponent_ratings_for_form(home_form + away_form)

        proba = market_probability(home_form, away_form, market, opponent_ratings=ratings or None)
        result = analyze_bet(proba["probability"], proba["confidence_90"], proba["samples"], odds, bankroll)
        result["status"] = "ok"
        result["market"] = market
        if result["decision"] != "BET":
            result["message"] = "Pas d'edge confirmé — ne pas recommander ce pari."
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"status": "error", "error": str(e)})


@tool("same_match_combo_analyze")
def same_match_combo_analyze(
    home_team: str,
    away_team: str,
    markets_json: str,
    odds: float,
    bankroll: float = 100.0,
) -> str:
    """Analyse un combiné INTRA-match avec la probabilité jointe EXACTE.

    Contrairement à parlay_analyze (matchs différents), ce tool calcule la
    proba jointe depuis la matrice de scores — le produit des probas
    marginales est faux quand les événements sont corrélés (ex: "victoire
    domicile" et "over 2.5" se renforcent).

    Marchés supportés : home, draw, away, over_1_5, over_2_5, over_3_5,
    under_1_5, under_2_5, under_3_5, btts_yes, btts_no.

    Args:
        home_team: équipe à domicile
        away_team: équipe à l'extérieur
        markets_json: JSON d'une liste de marchés, ex: '["home", "over_2_5"]'
        odds: cote Winamax du combiné
        bankroll: bankroll en euros (défaut 100)
    Returns:
        JSON avec proba jointe, effet de corrélation, décision et mise recommandée
    """
    from src.agents.quant.gateway import gateway
    from src.agents.quant.dixon_coles import same_match_combo
    from src.agents.quant.ev_engine import analyze_bet
    try:
        markets = json.loads(markets_json)
        home = gateway.search_team(home_team)
        away = gateway.search_team(away_team)
        if not home or not away:
            missing = home_team if not home else away_team
            return json.dumps({"status": "error", "message": f"Équipe introuvable (v1 : Ligue 1, Premier League) : {missing}"})

        home_form = gateway.recent_form(home["canonical_id"])
        away_form = gateway.recent_form(away["canonical_id"])
        ratings = gateway.opponent_ratings_for_form(home_form + away_form)

        combo = same_match_combo(home_form, away_form, markets, opponent_ratings=ratings or None)
        result = analyze_bet(combo["joint_probability"], combo["confidence_90"], combo["samples"], odds, bankroll)
        result["markets"] = combo["markets"]
        result["naive_product"] = combo["naive_product"]
        result["correlation_effect"] = combo["correlation_effect"]
        result["status"] = "ok"
        if result["decision"] != "BET":
            result["message"] = "Pas d'edge confirmé — ne pas recommander ce combiné."
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"status": "error", "error": str(e)})


def _match_key(home_team: str, away_team: str) -> str:
    return f"{home_team.strip().lower()}|{away_team.strip().lower()}"


def _resolve_parlay_legs(raw_legs: list[dict]) -> tuple[list[dict], list[dict]]:
    """Regroupe les legs de parlay par match et calcule leur probabilité.

    Chaque leg brut porte {home_team, away_team, market, odds} — jamais une
    probabilité toute faite. Les legs partageant un match sont fusionnés en
    probabilité jointe exacte (via same_match_combo), les autres passent par
    market_probability individuellement.

    Retourne (legs_prêts_pour_analyze_parlay, détails_des_fusions_intra_match).
    """
    from src.agents.quant.gateway import gateway
    from src.agents.quant.dixon_coles import market_probability, same_match_combo

    groups: dict[str, list[dict]] = {}
    for leg in raw_legs:
        key = _match_key(leg["home_team"], leg["away_team"])
        groups.setdefault(key, []).append(leg)

    resolved_legs: list[dict] = []
    merges: list[dict] = []

    for match_id, group in groups.items():
        home = gateway.search_team(group[0]["home_team"])
        away = gateway.search_team(group[0]["away_team"])
        if not home or not away:
            missing = group[0]["home_team"] if not home else group[0]["away_team"]
            raise ValueError(f"Équipe introuvable (v1 : Ligue 1, Premier League) : {missing}")

        home_form = gateway.recent_form(home["canonical_id"])
        away_form = gateway.recent_form(away["canonical_id"])
        ratings = gateway.opponent_ratings_for_form(home_form + away_form)

        combined_odds = 1.0
        for leg in group:
            combined_odds *= leg["odds"]

        if len(group) >= 2:
            markets = [leg["market"] for leg in group]
            combo = same_match_combo(home_form, away_form, markets, opponent_ratings=ratings or None)
            resolved_legs.append({
                "model_prob": combo["joint_probability"],
                "confidence_90": combo["confidence_90"],
                "samples": combo["samples"],
                "odds": combined_odds,
                "match_id": match_id,
            })
            merges.append({
                "match_id": match_id,
                "markets": markets,
                "joint_probability": combo["joint_probability"],
                "naive_product": combo["naive_product"],
                "correlation_effect": combo["correlation_effect"],
            })
        else:
            leg = group[0]
            proba = market_probability(home_form, away_form, leg["market"], opponent_ratings=ratings or None)
            resolved_legs.append({
                "model_prob": proba["probability"],
                "confidence_90": proba["confidence_90"],
                "samples": proba["samples"],
                "odds": leg["odds"],
                "match_id": match_id,
            })

    return resolved_legs, merges


@tool("parlay_analyze")
def parlay_analyze(legs_json: str, bankroll: float = 100.0) -> str:
    """Analyse un combiné (parlay) multi-matchs : décision, EV, corrélation.

    Chaque leg référence une équipe et un marché — jamais une probabilité
    toute faite (le calcul se fait ici). Les legs partageant le même match
    sont automatiquement fusionnés en probabilité jointe exacte.

    Args:
        legs_json: JSON d'une liste de legs :
            [{"home_team": "PSG", "away_team": "Lyon", "market": "home", "odds": 1.8},
             {"home_team": "PSG", "away_team": "Lyon", "market": "over_2_5", "odds": 1.9},
             {"home_team": "Real Madrid", "away_team": "Barcelone", "market": "away", "odds": 2.4}]
        bankroll: bankroll en euros (défaut 100)
    Returns:
        JSON avec décision, EV du combiné et détail des fusions intra-match
    """
    from src.agents.quant.ev_engine import analyze_bet, analyze_parlay
    try:
        raw_legs = json.loads(legs_json)
        if len(raw_legs) < 2:
            return json.dumps({"status": "error", "message": "Un combiné doit avoir au moins 2 sélections"})

        resolved_legs, merges = _resolve_parlay_legs(raw_legs)

        if len(resolved_legs) == 1:
            # Toutes les legs portaient sur le même match → pari simple à proba jointe
            leg = resolved_legs[0]
            result = analyze_bet(leg["model_prob"], leg["confidence_90"], leg["samples"], leg["odds"], bankroll)
            result["note"] = "Combiné entièrement intra-match — analysé via la probabilité jointe exacte."
        else:
            result = analyze_parlay(resolved_legs, bankroll)

        result["same_match_merges"] = merges
        result["status"] = "ok"
        if result["decision"] != "BET":
            result["message"] = "Pas d'edge confirmé — ne pas recommander ce combiné."
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"status": "error", "error": str(e)})
