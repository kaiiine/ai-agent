"""Registre manuel d'identités — Ligue 1 et Premier League (v1, cf. PRD §3).

IDs vérifiés en direct contre les deux APIs (juillet 2026) :
- football_data_org : compétitions PL/FL1 + endpoint standings saison 2025-2026
- api_sports : endpoint teams (saison 2024, seule saison couverte par le tier
  gratuit) + recherches par nom pour les équipes promues depuis

Ne couvre que le roster ACTUEL des deux ligues (v1 se concentre sur la saison
en cours, pas l'archive historique complète) — une équipe reléguée avant la
saison 2025-2026 (ex. Southampton, Leicester, Ipswich, Montpellier, Reims,
Saint-Étienne) n'est plus dans ce registre et renverra "hors des ligues
couvertes" plutôt qu'une donnée obsolète.
"""

from __future__ import annotations
from src.agents.quant.gateway.core.identity_resolver import CanonicalEntity

LEAGUES: list[CanonicalEntity] = [
    CanonicalEntity(
        canonical_id="league:ligue1",
        canonical_name="Ligue 1",
        aliases=["Ligue 1", "L1", "Ligue 1 France"],
        identities={"api_sports": "61", "football_data_org": "FL1"},
    ),
    CanonicalEntity(
        canonical_id="league:premier_league",
        canonical_name="Premier League",
        aliases=["Premier League", "EPL", "PL"],
        identities={"api_sports": "39", "football_data_org": "PL"},
    ),
]

TEAMS: list[CanonicalEntity] = [
    # Ligue 1 (18 équipes, saison 2025-2026)
    CanonicalEntity("team:psg", "Paris Saint Germain", ["PSG", "Paris SG", "Paris Saint-Germain"],
                     {"api_sports": "85", "football_data_org": "524"}),
    CanonicalEntity("team:lens", "Lens", ["Lens", "RC Lens"], {"api_sports": "116", "football_data_org": "546"}),
    CanonicalEntity("team:lille", "Lille", ["Lille", "LOSC"], {"api_sports": "79", "football_data_org": "521"}),
    CanonicalEntity("team:lyon", "Lyon", ["Lyon", "OL", "Olympique Lyonnais"], {"api_sports": "80", "football_data_org": "523"}),
    CanonicalEntity("team:marseille", "Marseille", ["Marseille", "OM", "Olympique Marseille"],
                     {"api_sports": "81", "football_data_org": "516"}),
    CanonicalEntity("team:rennes", "Rennes", ["Rennes", "Stade Rennais"], {"api_sports": "94", "football_data_org": "529"}),
    CanonicalEntity("team:monaco", "Monaco", ["Monaco", "AS Monaco"], {"api_sports": "91", "football_data_org": "548"}),
    CanonicalEntity("team:strasbourg", "Strasbourg", ["Strasbourg", "RC Strasbourg"],
                     {"api_sports": "95", "football_data_org": "576"}),
    CanonicalEntity("team:lorient", "Lorient", ["Lorient", "FC Lorient"], {"api_sports": "97", "football_data_org": "525"}),
    CanonicalEntity("team:toulouse", "Toulouse", ["Toulouse", "Toulouse FC"], {"api_sports": "96", "football_data_org": "511"}),
    CanonicalEntity("team:paris_fc", "Paris FC", ["Paris FC"], {"api_sports": "114", "football_data_org": "1045"}),
    CanonicalEntity("team:brest", "Stade Brestois 29", ["Brest", "Stade Brestois"],
                     {"api_sports": "106", "football_data_org": "512"}),
    CanonicalEntity("team:angers", "Angers", ["Angers", "Angers SCO"], {"api_sports": "77", "football_data_org": "532"}),
    CanonicalEntity("team:le_havre", "Le Havre", ["Le Havre", "HAC"], {"api_sports": "111", "football_data_org": "533"}),
    CanonicalEntity("team:auxerre", "Auxerre", ["Auxerre", "AJ Auxerre"], {"api_sports": "108", "football_data_org": "519"}),
    CanonicalEntity("team:nice", "Nice", ["Nice", "OGC Nice"], {"api_sports": "84", "football_data_org": "522"}),
    CanonicalEntity("team:nantes", "Nantes", ["Nantes", "FC Nantes"], {"api_sports": "83", "football_data_org": "543"}),
    CanonicalEntity("team:metz", "Metz", ["Metz", "FC Metz"], {"api_sports": "112", "football_data_org": "545"}),

    # Premier League (20 équipes, saison 2025-2026)
    CanonicalEntity("team:arsenal", "Arsenal", ["Arsenal"], {"api_sports": "42", "football_data_org": "57"}),
    CanonicalEntity("team:man_city", "Manchester City", ["Manchester City", "Man City"],
                     {"api_sports": "50", "football_data_org": "65"}),
    CanonicalEntity("team:man_united", "Manchester United", ["Manchester United", "Man Utd", "Man United"],
                     {"api_sports": "33", "football_data_org": "66"}),
    CanonicalEntity("team:aston_villa", "Aston Villa", ["Aston Villa"], {"api_sports": "66", "football_data_org": "58"}),
    CanonicalEntity("team:liverpool", "Liverpool", ["Liverpool"], {"api_sports": "40", "football_data_org": "64"}),
    CanonicalEntity("team:bournemouth", "Bournemouth", ["Bournemouth", "AFC Bournemouth"],
                     {"api_sports": "35", "football_data_org": "1044"}),
    CanonicalEntity("team:sunderland", "Sunderland", ["Sunderland", "Sunderland AFC"],
                     {"api_sports": "746", "football_data_org": "71"}),
    CanonicalEntity("team:brighton", "Brighton", ["Brighton", "Brighton & Hove Albion"],
                     {"api_sports": "51", "football_data_org": "397"}),
    CanonicalEntity("team:brentford", "Brentford", ["Brentford"], {"api_sports": "55", "football_data_org": "402"}),
    CanonicalEntity("team:chelsea", "Chelsea", ["Chelsea"], {"api_sports": "49", "football_data_org": "61"}),
    CanonicalEntity("team:fulham", "Fulham", ["Fulham"], {"api_sports": "36", "football_data_org": "63"}),
    CanonicalEntity("team:newcastle", "Newcastle", ["Newcastle", "Newcastle United"],
                     {"api_sports": "34", "football_data_org": "67"}),
    CanonicalEntity("team:everton", "Everton", ["Everton"], {"api_sports": "45", "football_data_org": "62"}),
    CanonicalEntity("team:leeds_united", "Leeds United", ["Leeds", "Leeds United"],
                     {"api_sports": "63", "football_data_org": "341"}),
    CanonicalEntity("team:crystal_palace", "Crystal Palace", ["Crystal Palace"],
                     {"api_sports": "52", "football_data_org": "354"}),
    CanonicalEntity("team:nottingham_forest", "Nottingham Forest", ["Nottingham Forest", "Forest"],
                     {"api_sports": "65", "football_data_org": "351"}),
    CanonicalEntity("team:tottenham", "Tottenham", ["Tottenham", "Spurs"], {"api_sports": "47", "football_data_org": "73"}),
    CanonicalEntity("team:west_ham", "West Ham", ["West Ham", "West Ham United"],
                     {"api_sports": "48", "football_data_org": "563"}),
    CanonicalEntity("team:burnley", "Burnley", ["Burnley"], {"api_sports": "44", "football_data_org": "328"}),
    CanonicalEntity("team:wolves", "Wolves", ["Wolves", "Wolverhampton"], {"api_sports": "39", "football_data_org": "76"}),
]

LEAGUE_TEAMS: dict[str, list[str]] = {
    "league:ligue1": [
        "team:psg", "team:lens", "team:lille", "team:lyon", "team:marseille", "team:rennes",
        "team:monaco", "team:strasbourg", "team:lorient", "team:toulouse", "team:paris_fc",
        "team:brest", "team:angers", "team:le_havre", "team:auxerre", "team:nice",
        "team:nantes", "team:metz",
    ],
    "league:premier_league": [
        "team:arsenal", "team:man_city", "team:man_united", "team:aston_villa", "team:liverpool",
        "team:bournemouth", "team:sunderland", "team:brighton", "team:brentford", "team:chelsea",
        "team:fulham", "team:newcastle", "team:everton", "team:leeds_united", "team:crystal_palace",
        "team:nottingham_forest", "team:tottenham", "team:west_ham", "team:burnley", "team:wolves",
    ],
}
