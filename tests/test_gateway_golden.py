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

# C3 : canonical_id typés. Les CLÉS d'identité ont changé (team:psg ->
# team:football:fra:psg, league:ligue1 -> competition:football:fra:ligue1),
# mais les VALEURS factuelles (buts, is_home, forces, ordre) sont identiques.
L1 = "competition:football:fra:ligue1"
_F = "team:football:fra:"   # préfixe équipes Ligue 1
_E = "team:football:eng:"   # préfixe équipes Premier League

# --- GOLDEN 1 : forme récente PSG, saison 2025 (10 derniers matchs joués) ---
EXPECTED_PSG_FORM = [
    {"date": "2026-05-17", "opponent_id": _F + "paris_fc", "goals_home": 2, "goals_away": 1, "is_home": False, "league_id": L1, "season": "2025"},
    {"date": "2026-05-13", "opponent_id": _F + "lens", "goals_home": 0, "goals_away": 2, "is_home": False, "league_id": L1, "season": "2025"},
    {"date": "2026-05-10", "opponent_id": _F + "brest", "goals_home": 1, "goals_away": 0, "is_home": True, "league_id": L1, "season": "2025"},
    {"date": "2026-05-02", "opponent_id": _F + "lorient", "goals_home": 2, "goals_away": 2, "is_home": True, "league_id": L1, "season": "2025"},
    {"date": "2026-04-25", "opponent_id": _F + "angers", "goals_home": 0, "goals_away": 3, "is_home": False, "league_id": L1, "season": "2025"},
    {"date": "2026-04-22", "opponent_id": _F + "nantes", "goals_home": 3, "goals_away": 0, "is_home": True, "league_id": L1, "season": "2025"},
    {"date": "2026-04-19", "opponent_id": _F + "lyon", "goals_home": 1, "goals_away": 2, "is_home": True, "league_id": L1, "season": "2025"},
    {"date": "2026-04-03", "opponent_id": _F + "toulouse", "goals_home": 3, "goals_away": 1, "is_home": True, "league_id": L1, "season": "2025"},
    {"date": "2026-03-21", "opponent_id": _F + "nice", "goals_home": 0, "goals_away": 4, "is_home": False, "league_id": L1, "season": "2025"},
    {"date": "2026-03-06", "opponent_id": _F + "monaco", "goals_home": 1, "goals_away": 3, "is_home": True, "league_id": L1, "season": "2025"},
]

# --- GOLDEN 2 : force par équipe depuis le classement Ligue 1 2025 (1er=1.3, dernier=0.7) ---
EXPECTED_LIGUE1_STRENGTH = {
    _F + "psg": 1.3, _F + "lens": 1.265, _F + "lille": 1.229, _F + "lyon": 1.194,
    _F + "marseille": 1.159, _F + "rennes": 1.124, _F + "monaco": 1.088, _F + "strasbourg": 1.053,
    _F + "lorient": 1.018, _F + "toulouse": 0.982, _F + "paris_fc": 0.947, _F + "brest": 0.912,
    _F + "angers": 0.876, _F + "le_havre": 0.841, _F + "auxerre": 0.806, _F + "nice": 0.771,
    _F + "nantes": 0.735, _F + "metz": 0.7,
}

# --- GOLDEN 3 : force par équipe depuis le classement Premier League 2025 ---
EXPECTED_PL_STRENGTH = {
    _E + "arsenal": 1.3, _E + "man_city": 1.268, _E + "man_united": 1.237, _E + "aston_villa": 1.205,
    _E + "liverpool": 1.174, _E + "bournemouth": 1.142, _E + "sunderland": 1.111, _E + "brighton": 1.079,
    _E + "brentford": 1.047, _E + "chelsea": 1.016, _E + "fulham": 0.984, _E + "newcastle": 0.953,
    _E + "everton": 0.921, _E + "leeds_united": 0.889, _E + "crystal_palace": 0.858,
    _E + "nottingham_forest": 0.826, _E + "tottenham": 0.795, _E + "west_ham": 0.763,
    _E + "burnley": 0.732, _E + "wolves": 0.7,
}


def test_recent_form_psg_golden(offline_gateway):
    from src.agents.quant.gateway import gateway
    form = gateway.recent_form("team:football:fra:psg", last=10, season="2025")
    assert form == EXPECTED_PSG_FORM


def test_standings_strength_ligue1_golden(offline_gateway):
    from src.agents.quant.gateway import gateway
    strength = gateway.standings_strength("competition:football:fra:ligue1", season="2025")
    assert strength == EXPECTED_LIGUE1_STRENGTH


def test_standings_strength_premier_league_golden(offline_gateway):
    from src.agents.quant.gateway import gateway
    strength = gateway.standings_strength("competition:football:eng:premier_league", season="2025")
    assert strength == EXPECTED_PL_STRENGTH


def test_opponent_ratings_uses_league_standings(offline_gateway):
    """opponent_ratings_for_form dérive du classement de la ligue de la forme."""
    from src.agents.quant.gateway import gateway
    form = gateway.recent_form("team:football:fra:psg", last=10, season="2025")
    ratings = gateway.opponent_ratings_for_form(form)
    assert ratings == EXPECTED_LIGUE1_STRENGTH
