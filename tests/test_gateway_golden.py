"""Golden tests gateway — filet de non-régression de la migration Vague 0 (GW-FR-010).

Valeurs de référence capturées sur le v1 validé (football-data.org, saison
2025-2026 terminée, donc déterministe). Ces tests doivent rester VERTS après
chaque étape C1..C7 de la migration.

Note migration : à l'étape C3 (canonical_id typés), seules les CLÉS d'identité
changent (team:psg -> team:football:fra:psg). Les valeurs factuelles (buts,
is_home, forces, ordre du classement) restent identiques — c'est ce que ces
tests protègent.
"""

from __future__ import annotations

L1 = "league:ligue1"

# --- GOLDEN 1 : forme récente PSG, saison 2025 (10 derniers matchs joués) ---
EXPECTED_PSG_FORM = [
    {"date": "2026-05-17", "opponent_id": "team:paris_fc", "goals_home": 2, "goals_away": 1, "is_home": False, "league_id": L1, "season": "2025"},
    {"date": "2026-05-13", "opponent_id": "team:lens", "goals_home": 0, "goals_away": 2, "is_home": False, "league_id": L1, "season": "2025"},
    {"date": "2026-05-10", "opponent_id": "team:brest", "goals_home": 1, "goals_away": 0, "is_home": True, "league_id": L1, "season": "2025"},
    {"date": "2026-05-02", "opponent_id": "team:lorient", "goals_home": 2, "goals_away": 2, "is_home": True, "league_id": L1, "season": "2025"},
    {"date": "2026-04-25", "opponent_id": "team:angers", "goals_home": 0, "goals_away": 3, "is_home": False, "league_id": L1, "season": "2025"},
    {"date": "2026-04-22", "opponent_id": "team:nantes", "goals_home": 3, "goals_away": 0, "is_home": True, "league_id": L1, "season": "2025"},
    {"date": "2026-04-19", "opponent_id": "team:lyon", "goals_home": 1, "goals_away": 2, "is_home": True, "league_id": L1, "season": "2025"},
    {"date": "2026-04-03", "opponent_id": "team:toulouse", "goals_home": 3, "goals_away": 1, "is_home": True, "league_id": L1, "season": "2025"},
    {"date": "2026-03-21", "opponent_id": "team:nice", "goals_home": 0, "goals_away": 4, "is_home": False, "league_id": L1, "season": "2025"},
    {"date": "2026-03-06", "opponent_id": "team:monaco", "goals_home": 1, "goals_away": 3, "is_home": True, "league_id": L1, "season": "2025"},
]

# --- GOLDEN 2 : force par équipe depuis le classement Ligue 1 2025 (1er=1.3, dernier=0.7) ---
EXPECTED_LIGUE1_STRENGTH = {
    "team:psg": 1.3, "team:lens": 1.265, "team:lille": 1.229, "team:lyon": 1.194,
    "team:marseille": 1.159, "team:rennes": 1.124, "team:monaco": 1.088, "team:strasbourg": 1.053,
    "team:lorient": 1.018, "team:toulouse": 0.982, "team:paris_fc": 0.947, "team:brest": 0.912,
    "team:angers": 0.876, "team:le_havre": 0.841, "team:auxerre": 0.806, "team:nice": 0.771,
    "team:nantes": 0.735, "team:metz": 0.7,
}

# --- GOLDEN 3 : force par équipe depuis le classement Premier League 2025 ---
EXPECTED_PL_STRENGTH = {
    "team:arsenal": 1.3, "team:man_city": 1.268, "team:man_united": 1.237, "team:aston_villa": 1.205,
    "team:liverpool": 1.174, "team:bournemouth": 1.142, "team:sunderland": 1.111, "team:brighton": 1.079,
    "team:brentford": 1.047, "team:chelsea": 1.016, "team:fulham": 0.984, "team:newcastle": 0.953,
    "team:everton": 0.921, "team:leeds_united": 0.889, "team:crystal_palace": 0.858,
    "team:nottingham_forest": 0.826, "team:tottenham": 0.795, "team:west_ham": 0.763,
    "team:burnley": 0.732, "team:wolves": 0.7,
}


def test_recent_form_psg_golden(offline_gateway):
    from src.agents.quant.gateway import gateway
    form = gateway.recent_form("team:psg", last=10, season="2025")
    assert form == EXPECTED_PSG_FORM


def test_standings_strength_ligue1_golden(offline_gateway):
    from src.agents.quant.gateway import gateway
    strength = gateway.standings_strength("league:ligue1", season="2025")
    assert strength == EXPECTED_LIGUE1_STRENGTH


def test_standings_strength_premier_league_golden(offline_gateway):
    from src.agents.quant.gateway import gateway
    strength = gateway.standings_strength("league:premier_league", season="2025")
    assert strength == EXPECTED_PL_STRENGTH


def test_opponent_ratings_uses_league_standings(offline_gateway):
    """opponent_ratings_for_form dérive du classement de la ligue de la forme."""
    from src.agents.quant.gateway import gateway
    form = gateway.recent_form("team:psg", last=10, season="2025")
    ratings = gateway.opponent_ratings_for_form(form)
    assert ratings == EXPECTED_LIGUE1_STRENGTH
