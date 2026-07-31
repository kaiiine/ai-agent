"""Registre manuel d'identités — Ligue 1 et Premier League.

canonical_id typé (ADR-008, GW-FR-008) : {entity_type}:{sport}:{scope}:{slug}.
Le `scope` est un code de zone football 3 lettres (fra, eng...), cf. la note
dans registries/competition_registry.py sur le rejet d'ISO alpha-2.

IDs provider vérifiés en direct contre les deux APIs :
- football_data_org : compétitions PL/FL1 + standings 2025-2026
- api_sports : endpoint teams (saison 2024) + recherches par nom

Ne couvre que le roster ACTUEL des deux ligues — une équipe reléguée avant
2025-2026 (Southampton, Leicester, Montpellier, Reims...) n'y est plus et
renverra "hors des ligues couvertes" plutôt qu'une donnée obsolète.

GW-FR-002 (résorbé à C5) : l'identité des COMPÉTITIONS vit désormais dans
registries/competition_registry.py (sans aucun ID provider), et le mapping
compétition→provider_competition_id dans registries/provider_coverage_registry.py.
Les compétitions ne sont donc PLUS dans ce registre d'identités : il ne contient
que des ENTITÉS résolues par ID provider dans le pipeline (équipes, via
identity_resolver.canonicalize dans les normalizers). Une compétition n'a pas
besoin d'être canonicalisée (son canonical_id est passé directement).

La collision d'ID provider équipe/compétition (ex-bug Wolves/PL id 39) est ainsi
évitée par SÉPARATION de registres — les compétitions ne partagent plus aucun
espace de noms avec les équipes.
"""

from __future__ import annotations
from src.agents.quant.gateway.core.identity_resolver import CanonicalEntity

TEAMS: list[CanonicalEntity] = [
    # Ligue 1 (18 équipes, saison 2025-2026) — scope fra
    CanonicalEntity("team:football:fra:psg", "Paris Saint Germain", ["PSG", "Paris SG", "Paris Saint-Germain"],
                     {"api_sports": "85", "football_data_org": "524"}),
    CanonicalEntity("team:football:fra:lens", "Lens", ["Lens", "RC Lens"], {"api_sports": "116", "football_data_org": "546"}),
    CanonicalEntity("team:football:fra:lille", "Lille", ["Lille", "LOSC"], {"api_sports": "79", "football_data_org": "521"}),
    CanonicalEntity("team:football:fra:lyon", "Lyon", ["Lyon", "OL", "Olympique Lyonnais"], {"api_sports": "80", "football_data_org": "523"}),
    CanonicalEntity("team:football:fra:marseille", "Marseille", ["Marseille", "OM", "Olympique Marseille"],
                     {"api_sports": "81", "football_data_org": "516"}),
    CanonicalEntity("team:football:fra:rennes", "Rennes", ["Rennes", "Stade Rennais"], {"api_sports": "94", "football_data_org": "529"}),
    CanonicalEntity("team:football:fra:monaco", "Monaco", ["Monaco", "AS Monaco"], {"api_sports": "91", "football_data_org": "548"}),
    CanonicalEntity("team:football:fra:strasbourg", "Strasbourg", ["Strasbourg", "RC Strasbourg"],
                     {"api_sports": "95", "football_data_org": "576"}),
    CanonicalEntity("team:football:fra:lorient", "Lorient", ["Lorient", "FC Lorient"], {"api_sports": "97", "football_data_org": "525"}),
    CanonicalEntity("team:football:fra:toulouse", "Toulouse", ["Toulouse", "Toulouse FC"], {"api_sports": "96", "football_data_org": "511"}),
    CanonicalEntity("team:football:fra:paris_fc", "Paris FC", ["Paris FC"], {"api_sports": "114", "football_data_org": "1045"}),
    CanonicalEntity("team:football:fra:brest", "Stade Brestois 29", ["Brest", "Stade Brestois"],
                     {"api_sports": "106", "football_data_org": "512"}),
    CanonicalEntity("team:football:fra:angers", "Angers", ["Angers", "Angers SCO"], {"api_sports": "77", "football_data_org": "532"}),
    CanonicalEntity("team:football:fra:le_havre", "Le Havre", ["Le Havre", "HAC"], {"api_sports": "111", "football_data_org": "533"}),
    CanonicalEntity("team:football:fra:auxerre", "Auxerre", ["Auxerre", "AJ Auxerre"], {"api_sports": "108", "football_data_org": "519"}),
    CanonicalEntity("team:football:fra:nice", "Nice", ["Nice", "OGC Nice"], {"api_sports": "84", "football_data_org": "522"}),
    CanonicalEntity("team:football:fra:nantes", "Nantes", ["Nantes", "FC Nantes"], {"api_sports": "83", "football_data_org": "543"}),
    CanonicalEntity("team:football:fra:metz", "Metz", ["Metz", "FC Metz"], {"api_sports": "112", "football_data_org": "545"}),

    # Premier League (20 équipes, saison 2025-2026) — scope eng
    CanonicalEntity("team:football:eng:arsenal", "Arsenal", ["Arsenal"], {"api_sports": "42", "football_data_org": "57"}),
    CanonicalEntity("team:football:eng:man_city", "Manchester City", ["Manchester City", "Man City"],
                     {"api_sports": "50", "football_data_org": "65"}),
    CanonicalEntity("team:football:eng:man_united", "Manchester United", ["Manchester United", "Man Utd", "Man United"],
                     {"api_sports": "33", "football_data_org": "66"}),
    CanonicalEntity("team:football:eng:aston_villa", "Aston Villa", ["Aston Villa"], {"api_sports": "66", "football_data_org": "58"}),
    CanonicalEntity("team:football:eng:liverpool", "Liverpool", ["Liverpool"], {"api_sports": "40", "football_data_org": "64"}),
    CanonicalEntity("team:football:eng:bournemouth", "Bournemouth", ["Bournemouth", "AFC Bournemouth"],
                     {"api_sports": "35", "football_data_org": "1044"}),
    CanonicalEntity("team:football:eng:sunderland", "Sunderland", ["Sunderland", "Sunderland AFC"],
                     {"api_sports": "746", "football_data_org": "71"}),
    CanonicalEntity("team:football:eng:brighton", "Brighton", ["Brighton", "Brighton & Hove Albion"],
                     {"api_sports": "51", "football_data_org": "397"}),
    CanonicalEntity("team:football:eng:brentford", "Brentford", ["Brentford"], {"api_sports": "55", "football_data_org": "402"}),
    CanonicalEntity("team:football:eng:chelsea", "Chelsea", ["Chelsea"], {"api_sports": "49", "football_data_org": "61"}),
    CanonicalEntity("team:football:eng:fulham", "Fulham", ["Fulham"], {"api_sports": "36", "football_data_org": "63"}),
    CanonicalEntity("team:football:eng:newcastle", "Newcastle", ["Newcastle", "Newcastle United"],
                     {"api_sports": "34", "football_data_org": "67"}),
    CanonicalEntity("team:football:eng:everton", "Everton", ["Everton"], {"api_sports": "45", "football_data_org": "62"}),
    CanonicalEntity("team:football:eng:leeds_united", "Leeds United", ["Leeds", "Leeds United"],
                     {"api_sports": "63", "football_data_org": "341"}),
    CanonicalEntity("team:football:eng:crystal_palace", "Crystal Palace", ["Crystal Palace"],
                     {"api_sports": "52", "football_data_org": "354"}),
    CanonicalEntity("team:football:eng:nottingham_forest", "Nottingham Forest", ["Nottingham Forest", "Forest"],
                     {"api_sports": "65", "football_data_org": "351"}),
    CanonicalEntity("team:football:eng:tottenham", "Tottenham", ["Tottenham", "Spurs"], {"api_sports": "47", "football_data_org": "73"}),
    CanonicalEntity("team:football:eng:west_ham", "West Ham", ["West Ham", "West Ham United"],
                     {"api_sports": "48", "football_data_org": "563"}),
    CanonicalEntity("team:football:eng:burnley", "Burnley", ["Burnley"], {"api_sports": "44", "football_data_org": "328"}),
    CanonicalEntity("team:football:eng:wolves", "Wolves", ["Wolves", "Wolverhampton"], {"api_sports": "39", "football_data_org": "76"}),

    # Serie A (20 équipes, saison 2025-2026) — scope ita.
    # IDs football_data_org VÉRIFIÉS EN DIRECT (endpoint competitions/SA/matches, 2026-07-31,
    # 380 matchs FINISHED) : chaque ID voyage avec son nom provider (autoritatif). Les alias
    # incluent le nom EXACT affiché par Winamax (scan live tid 33) pour la résolution live —
    # un alias absent -> UNRESOLVED (isolé), jamais une mauvaise résolution (résolution EXACTE).
    CanonicalEntity("team:football:ita:milan", "AC Milan", ["Milan AC", "AC Milan", "Milan"], {"football_data_org": "98"}),
    CanonicalEntity("team:football:ita:fiorentina", "ACF Fiorentina", ["Fiorentina"], {"football_data_org": "99"}),
    CanonicalEntity("team:football:ita:roma", "AS Roma", ["AS Rome", "AS Roma", "Roma", "Rome"], {"football_data_org": "100"}),
    CanonicalEntity("team:football:ita:atalanta", "Atalanta BC", ["Atalanta Bergame", "Atalanta"], {"football_data_org": "102"}),
    CanonicalEntity("team:football:ita:bologna", "Bologna FC 1909", ["Bologne", "Bologna"], {"football_data_org": "103"}),
    CanonicalEntity("team:football:ita:cagliari", "Cagliari Calcio", ["Cagliari"], {"football_data_org": "104"}),
    CanonicalEntity("team:football:ita:genoa", "Genoa CFC", ["Genoa"], {"football_data_org": "107"}),
    CanonicalEntity("team:football:ita:inter", "FC Internazionale Milano", ["Inter Milan", "Inter"], {"football_data_org": "108"}),
    CanonicalEntity("team:football:ita:juventus", "Juventus FC", ["Juventus Turin", "Juventus"], {"football_data_org": "109"}),
    CanonicalEntity("team:football:ita:lazio", "SS Lazio", ["Lazio Rome", "Lazio"], {"football_data_org": "110"}),
    CanonicalEntity("team:football:ita:parma", "Parma Calcio 1913", ["Parme", "Parma"], {"football_data_org": "112"}),
    CanonicalEntity("team:football:ita:napoli", "SSC Napoli", ["Naples", "Napoli"], {"football_data_org": "113"}),
    CanonicalEntity("team:football:ita:udinese", "Udinese Calcio", ["Udinese"], {"football_data_org": "115"}),
    CanonicalEntity("team:football:ita:hellas_verona", "Hellas Verona FC", ["Hellas Verona", "Verona", "Vérone"], {"football_data_org": "450"}),
    CanonicalEntity("team:football:ita:cremonese", "US Cremonese", ["Cremonese"], {"football_data_org": "457"}),
    CanonicalEntity("team:football:ita:sassuolo", "US Sassuolo Calcio", ["Sassuolo"], {"football_data_org": "471"}),
    CanonicalEntity("team:football:ita:pisa", "AC Pisa 1909", ["Pisa", "Pise"], {"football_data_org": "487"}),
    CanonicalEntity("team:football:ita:torino", "Torino FC", ["Torino"], {"football_data_org": "586"}),
    CanonicalEntity("team:football:ita:lecce", "US Lecce", ["Lecce"], {"football_data_org": "5890"}),
    CanonicalEntity("team:football:ita:como", "Como 1907", ["Côme", "Como"], {"football_data_org": "7397"}),
]

LEAGUE_TEAMS: dict[str, list[str]] = {
    "competition:football:fra:ligue1": [
        "team:football:fra:psg", "team:football:fra:lens", "team:football:fra:lille",
        "team:football:fra:lyon", "team:football:fra:marseille", "team:football:fra:rennes",
        "team:football:fra:monaco", "team:football:fra:strasbourg", "team:football:fra:lorient",
        "team:football:fra:toulouse", "team:football:fra:paris_fc", "team:football:fra:brest",
        "team:football:fra:angers", "team:football:fra:le_havre", "team:football:fra:auxerre",
        "team:football:fra:nice", "team:football:fra:nantes", "team:football:fra:metz",
    ],
    "competition:football:eng:premier_league": [
        "team:football:eng:arsenal", "team:football:eng:man_city", "team:football:eng:man_united",
        "team:football:eng:aston_villa", "team:football:eng:liverpool", "team:football:eng:bournemouth",
        "team:football:eng:sunderland", "team:football:eng:brighton", "team:football:eng:brentford",
        "team:football:eng:chelsea", "team:football:eng:fulham", "team:football:eng:newcastle",
        "team:football:eng:everton", "team:football:eng:leeds_united", "team:football:eng:crystal_palace",
        "team:football:eng:nottingham_forest", "team:football:eng:tottenham", "team:football:eng:west_ham",
        "team:football:eng:burnley", "team:football:eng:wolves",
    ],
    "competition:football:ita:serie_a": [
        "team:football:ita:milan", "team:football:ita:fiorentina", "team:football:ita:roma",
        "team:football:ita:atalanta", "team:football:ita:bologna", "team:football:ita:cagliari",
        "team:football:ita:genoa", "team:football:ita:inter", "team:football:ita:juventus",
        "team:football:ita:lazio", "team:football:ita:parma", "team:football:ita:napoli",
        "team:football:ita:udinese", "team:football:ita:hellas_verona", "team:football:ita:cremonese",
        "team:football:ita:sassuolo", "team:football:ita:pisa", "team:football:ita:torino",
        "team:football:ita:lecce", "team:football:ita:como",
    ],
}
