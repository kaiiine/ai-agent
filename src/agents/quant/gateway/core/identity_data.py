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

    # LaLiga (20 équipes, saison 2025-2026) — scope esp. IDs football_data_org VÉRIFIÉS
    # EN DIRECT (competitions/PD/matches, 2026-07-31). tid Winamax 36 confirmé LaLiga par
    # chevauchement de roster (0.75 vs PD ; competition_identity.disambiguate). Aliases =
    # nom EXACT Winamax (scan tid 36) ; un absent -> UNRESOLVED (isolé), jamais mal résolu.
    CanonicalEntity("team:football:esp:athletic_bilbao", "Athletic Club", ["Athletic Bilbao", "Bilbao"], {"football_data_org": "77"}),
    CanonicalEntity("team:football:esp:atletico_madrid", "Club Atlético de Madrid", ["Atletico Madrid", "Atlético Madrid"], {"football_data_org": "78"}),
    CanonicalEntity("team:football:esp:osasuna", "CA Osasuna", ["Osasuna"], {"football_data_org": "79"}),
    CanonicalEntity("team:football:esp:espanyol", "RCD Espanyol de Barcelona", ["Espanyol Barcelone", "Espanyol"], {"football_data_org": "80"}),
    CanonicalEntity("team:football:esp:barcelona", "FC Barcelona", ["FC Barcelone", "Barcelone", "Barcelona"], {"football_data_org": "81"}),
    CanonicalEntity("team:football:esp:getafe", "Getafe CF", ["Getafe"], {"football_data_org": "82"}),
    CanonicalEntity("team:football:esp:real_madrid", "Real Madrid CF", ["Real Madrid"], {"football_data_org": "86"}),
    CanonicalEntity("team:football:esp:rayo_vallecano", "Rayo Vallecano de Madrid", ["Rayo Vallecano"], {"football_data_org": "87"}),
    CanonicalEntity("team:football:esp:levante", "Levante UD", ["Levante"], {"football_data_org": "88"}),
    CanonicalEntity("team:football:esp:mallorca", "RCD Mallorca", ["Mallorca"], {"football_data_org": "89"}),
    CanonicalEntity("team:football:esp:real_betis", "Real Betis Balompié", ["Betis Séville", "Real Betis", "Betis"], {"football_data_org": "90"}),
    CanonicalEntity("team:football:esp:real_sociedad", "Real Sociedad de Fútbol", ["Real Sociedad"], {"football_data_org": "92"}),
    CanonicalEntity("team:football:esp:villarreal", "Villarreal CF", ["Villarreal"], {"football_data_org": "94"}),
    CanonicalEntity("team:football:esp:valencia", "Valencia CF", ["Valence", "Valencia"], {"football_data_org": "95"}),
    CanonicalEntity("team:football:esp:alaves", "Deportivo Alavés", ["Alaves", "Alavés"], {"football_data_org": "263"}),
    CanonicalEntity("team:football:esp:elche", "Elche CF", ["Elche"], {"football_data_org": "285"}),
    CanonicalEntity("team:football:esp:girona", "Girona FC", ["Girona"], {"football_data_org": "298"}),
    CanonicalEntity("team:football:esp:celta_vigo", "RC Celta de Vigo", ["Celta Vigo", "Celta"], {"football_data_org": "558"}),
    CanonicalEntity("team:football:esp:sevilla", "Sevilla FC", ["FC Séville", "Sevilla"], {"football_data_org": "559"}),
    CanonicalEntity("team:football:esp:oviedo", "Real Oviedo", ["Real Oviedo", "Oviedo"], {"football_data_org": "1048"}),

    # Bundesliga (18 équipes, saison 2025-2026) — scope deu. IDs football_data_org VÉRIFIÉS
    # EN DIRECT (competitions/BL1/matches, 2026-07-31). tid Winamax 42 DÉSAMBIGUÏSÉ par roster
    # (0.556 vs BL1 allemand ; tid 29 = 0.0 = Bundesliga AUTRICHIENNE, non onboardée).
    CanonicalEntity("team:football:deu:koln", "1. FC Köln", ["FC Cologne", "Cologne", "Köln"], {"football_data_org": "1"}),
    CanonicalEntity("team:football:deu:hoffenheim", "TSG 1899 Hoffenheim", ["TSG Hoffenheim", "Hoffenheim"], {"football_data_org": "2"}),
    CanonicalEntity("team:football:deu:leverkusen", "Bayer 04 Leverkusen", ["Bayer Leverkusen", "Leverkusen"], {"football_data_org": "3"}),
    CanonicalEntity("team:football:deu:dortmund", "Borussia Dortmund", ["Dortmund"], {"football_data_org": "4"}),
    CanonicalEntity("team:football:deu:bayern", "FC Bayern München", ["Bayern Munich", "Bayern München", "Bayern"], {"football_data_org": "5"}),
    CanonicalEntity("team:football:deu:hamburger", "Hamburger SV", ["Hambourg", "Hamburg"], {"football_data_org": "7"}),
    CanonicalEntity("team:football:deu:stuttgart", "VfB Stuttgart", ["Stuttgart"], {"football_data_org": "10"}),
    CanonicalEntity("team:football:deu:wolfsburg", "VfL Wolfsburg", ["Wolfsburg", "Wolfsbourg"], {"football_data_org": "11"}),
    CanonicalEntity("team:football:deu:werder_bremen", "SV Werder Bremen", ["Werder Brême", "Werder Bremen"], {"football_data_org": "12"}),
    CanonicalEntity("team:football:deu:mainz", "1. FSV Mainz 05", ["Mayence", "Mainz"], {"football_data_org": "15"}),
    CanonicalEntity("team:football:deu:augsburg", "FC Augsburg", ["Augsbourg", "Augsburg"], {"football_data_org": "16"}),
    CanonicalEntity("team:football:deu:freiburg", "SC Freiburg", ["Fribourg", "Freiburg"], {"football_data_org": "17"}),
    CanonicalEntity("team:football:deu:monchengladbach", "Borussia Mönchengladbach", ["Borussia Mönchengladbach", "Mönchengladbach", "Gladbach"], {"football_data_org": "18"}),
    CanonicalEntity("team:football:deu:frankfurt", "Eintracht Frankfurt", ["Eintracht Francfort", "Frankfurt", "Francfort"], {"football_data_org": "19"}),
    CanonicalEntity("team:football:deu:st_pauli", "FC St. Pauli 1910", ["St. Pauli", "St Pauli"], {"football_data_org": "20"}),
    CanonicalEntity("team:football:deu:union_berlin", "1. FC Union Berlin", ["Union Berlin"], {"football_data_org": "28"}),
    CanonicalEntity("team:football:deu:heidenheim", "1. FC Heidenheim 1846", ["Heidenheim"], {"football_data_org": "44"}),
    CanonicalEntity("team:football:deu:leipzig", "RB Leipzig", ["RB Leipzig", "Leipzig"], {"football_data_org": "721"}),

    # Championship anglaise (24 équipes, 2025-2026) — scope eng (distinct des slugs PL).
    # IDs football_data_org vérifiés en direct (ELC/matches) ; tid Winamax 2 confirmé (0.83).
    CanonicalEntity("team:football:eng:blackburn", "Blackburn Rovers FC", ["Blackburn", "Blackburn Rovers"], {"football_data_org": "59"}),
    CanonicalEntity("team:football:eng:norwich", "Norwich City FC", ["Norwich", "Norwich City"], {"football_data_org": "68"}),
    CanonicalEntity("team:football:eng:qpr", "Queens Park Rangers FC", ["Queens Park Rangers", "QPR"], {"football_data_org": "69"}),
    CanonicalEntity("team:football:eng:stoke", "Stoke City FC", ["Stoke City", "Stoke"], {"football_data_org": "70"}),
    CanonicalEntity("team:football:eng:swansea", "Swansea City AFC", ["Swansea", "Swansea City"], {"football_data_org": "72"}),
    CanonicalEntity("team:football:eng:west_brom", "West Bromwich Albion FC", ["West Bromwich", "West Brom", "West Bromwich Albion"], {"football_data_org": "74"}),
    CanonicalEntity("team:football:eng:hull", "Hull City AFC", ["Hull City", "Hull"], {"football_data_org": "322"}),
    CanonicalEntity("team:football:eng:portsmouth", "Portsmouth FC", ["Portsmouth"], {"football_data_org": "325"}),
    CanonicalEntity("team:football:eng:birmingham", "Birmingham City FC", ["Birmingham", "Birmingham City"], {"football_data_org": "332"}),
    CanonicalEntity("team:football:eng:leicester", "Leicester City FC", ["Leicester", "Leicester City"], {"football_data_org": "338"}),
    CanonicalEntity("team:football:eng:southampton", "Southampton FC", ["Southampton"], {"football_data_org": "340"}),
    CanonicalEntity("team:football:eng:derby", "Derby County FC", ["Derby County", "Derby"], {"football_data_org": "342"}),
    CanonicalEntity("team:football:eng:middlesbrough", "Middlesbrough FC", ["Middlesbrough"], {"football_data_org": "343"}),
    CanonicalEntity("team:football:eng:sheffield_wed", "Sheffield Wednesday FC", ["Sheffield Wednesday", "Sheffield Wed"], {"football_data_org": "345"}),
    CanonicalEntity("team:football:eng:watford", "Watford FC", ["Watford"], {"football_data_org": "346"}),
    CanonicalEntity("team:football:eng:charlton", "Charlton Athletic FC", ["Charlton", "Charlton Athletic"], {"football_data_org": "348"}),
    CanonicalEntity("team:football:eng:ipswich", "Ipswich Town FC", ["Ipswich", "Ipswich Town"], {"football_data_org": "349"}),
    CanonicalEntity("team:football:eng:sheffield_utd", "Sheffield United FC", ["Sheffield United"], {"football_data_org": "356"}),
    CanonicalEntity("team:football:eng:millwall", "Millwall FC", ["Millwall"], {"football_data_org": "384"}),
    CanonicalEntity("team:football:eng:bristol_city", "Bristol City FC", ["Bristol City"], {"football_data_org": "387"}),
    CanonicalEntity("team:football:eng:wrexham", "Wrexham AFC", ["Wrexham"], {"football_data_org": "404"}),
    CanonicalEntity("team:football:eng:coventry", "Coventry City FC", ["Coventry", "Coventry City"], {"football_data_org": "1076"}),
    CanonicalEntity("team:football:eng:preston", "Preston North End FC", ["Preston North End", "Preston"], {"football_data_org": "1081"}),
    CanonicalEntity("team:football:eng:oxford", "Oxford United FC", ["Oxford United", "Oxford"], {"football_data_org": "1082"}),

    # Eredivisie (18 équipes, 2025-2026) — scope nld. IDs football_data_org vérifiés (DED) ; tid 39 (0.61).
    CanonicalEntity("team:football:nld:twente", "FC Twente '65", ["Twente", "FC Twente"], {"football_data_org": "666"}),
    CanonicalEntity("team:football:nld:excelsior", "SBV Excelsior", ["Excelsior Rotterdam", "Excelsior"], {"football_data_org": "670"}),
    CanonicalEntity("team:football:nld:heracles", "Heracles Almelo", ["Heracles", "Heracles Almelo"], {"football_data_org": "671"}),
    CanonicalEntity("team:football:nld:heerenveen", "SC Heerenveen", ["Heerenveen"], {"football_data_org": "673"}),
    CanonicalEntity("team:football:nld:psv", "PSV", ["PSV Eindhoven", "PSV"], {"football_data_org": "674"}),
    CanonicalEntity("team:football:nld:feyenoord", "Feyenoord Rotterdam", ["Feyenoord"], {"football_data_org": "675"}),
    CanonicalEntity("team:football:nld:utrecht", "FC Utrecht", ["Utrecht", "FC Utrecht"], {"football_data_org": "676"}),
    CanonicalEntity("team:football:nld:groningen", "FC Groningen", ["Groningue", "Groningen"], {"football_data_org": "677"}),
    CanonicalEntity("team:football:nld:ajax", "AFC Ajax", ["Ajax Amsterdam", "Ajax"], {"football_data_org": "678"}),
    CanonicalEntity("team:football:nld:nac_breda", "NAC Breda", ["NAC Breda", "NAC"], {"football_data_org": "681"}),
    CanonicalEntity("team:football:nld:az", "AZ", ["AZ Alkmaar", "AZ"], {"football_data_org": "682"}),
    CanonicalEntity("team:football:nld:zwolle", "PEC Zwolle", ["Zwolle", "PEC Zwolle"], {"football_data_org": "684"}),
    CanonicalEntity("team:football:nld:go_ahead_eagles", "Go Ahead Eagles", ["GO Ahead Eagles", "Go Ahead Eagles"], {"football_data_org": "718"}),
    CanonicalEntity("team:football:nld:telstar", "Telstar 1963", ["Telstar"], {"football_data_org": "1912"}),
    CanonicalEntity("team:football:nld:nec", "NEC", ["NEC Nijmegen", "NEC"], {"football_data_org": "1915"}),
    CanonicalEntity("team:football:nld:volendam", "FC Volendam", ["Volendam", "FC Volendam"], {"football_data_org": "1919"}),
    CanonicalEntity("team:football:nld:fortuna_sittard", "Fortuna Sittard", ["Fortuna Sittard"], {"football_data_org": "1920"}),
    CanonicalEntity("team:football:nld:sparta_rotterdam", "Sparta Rotterdam", ["Sparta Rotterdam"], {"football_data_org": "6806"}),

    # Primeira Liga (18 équipes, 2025-2026) — scope prt. IDs football_data_org vérifiés (PPL) ; tid 52 (0.88).
    CanonicalEntity("team:football:prt:rio_ave", "Rio Ave FC", ["Rio Ave"], {"football_data_org": "496"}),
    CanonicalEntity("team:football:prt:sporting", "Sporting Clube de Portugal", ["Sporting Portugal", "Sporting CP"], {"football_data_org": "498"}),
    CanonicalEntity("team:football:prt:porto", "FC Porto", ["FC Porto", "Porto"], {"football_data_org": "503"}),
    CanonicalEntity("team:football:prt:estoril", "GD Estoril Praia", ["Estoril"], {"football_data_org": "582"}),
    CanonicalEntity("team:football:prt:moreirense", "Moreirense FC", ["Moreirense"], {"football_data_org": "583"}),
    CanonicalEntity("team:football:prt:arouca", "FC Arouca", ["FC Arouca", "Arouca"], {"football_data_org": "712"}),
    CanonicalEntity("team:football:prt:tondela", "CD Tondela", ["Tondela", "CD Tondela"], {"football_data_org": "1049"}),
    CanonicalEntity("team:football:prt:benfica", "Sport Lisboa e Benfica", ["Benfica"], {"football_data_org": "1903"}),
    CanonicalEntity("team:football:prt:nacional", "CD Nacional", ["Nacional Madeira", "Nacional"], {"football_data_org": "5529"}),
    CanonicalEntity("team:football:prt:santa_clara", "CD Santa Clara", ["Santa Clara"], {"football_data_org": "5530"}),
    CanonicalEntity("team:football:prt:famalicao", "FC Famalicão", ["Famalicao", "Famalicão"], {"football_data_org": "5531"}),
    CanonicalEntity("team:football:prt:gil_vicente", "Gil Vicente FC", ["Gil Vicente"], {"football_data_org": "5533"}),
    CanonicalEntity("team:football:prt:vitoria_guimaraes", "Vitória SC", ["Vitoria Guimaraes", "Vitória SC", "Vitoria SC"], {"football_data_org": "5543"}),
    CanonicalEntity("team:football:prt:braga", "Sporting Clube de Braga", ["Braga", "SC Braga"], {"football_data_org": "5613"}),
    CanonicalEntity("team:football:prt:casa_pia", "Casa Pia AC", ["Casa Pia AC", "Casa Pia"], {"football_data_org": "6618"}),
    CanonicalEntity("team:football:prt:alverca", "FC Alverca", ["Alverca FC", "Alverca"], {"football_data_org": "7822"}),
    CanonicalEntity("team:football:prt:estrela_amadora", "CF Estrela da Amadora", ["CF Estrela Amadora", "Estrela Amadora"], {"football_data_org": "9136"}),
    CanonicalEntity("team:football:prt:avs", "AVS", ["AVS"], {"football_data_org": "10340"}),
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
    "competition:football:esp:laliga": [
        "team:football:esp:athletic_bilbao", "team:football:esp:atletico_madrid", "team:football:esp:osasuna",
        "team:football:esp:espanyol", "team:football:esp:barcelona", "team:football:esp:getafe",
        "team:football:esp:real_madrid", "team:football:esp:rayo_vallecano", "team:football:esp:levante",
        "team:football:esp:mallorca", "team:football:esp:real_betis", "team:football:esp:real_sociedad",
        "team:football:esp:villarreal", "team:football:esp:valencia", "team:football:esp:alaves",
        "team:football:esp:elche", "team:football:esp:girona", "team:football:esp:celta_vigo",
        "team:football:esp:sevilla", "team:football:esp:oviedo",
    ],
    "competition:football:deu:bundesliga": [
        "team:football:deu:koln", "team:football:deu:hoffenheim", "team:football:deu:leverkusen",
        "team:football:deu:dortmund", "team:football:deu:bayern", "team:football:deu:hamburger",
        "team:football:deu:stuttgart", "team:football:deu:wolfsburg", "team:football:deu:werder_bremen",
        "team:football:deu:mainz", "team:football:deu:augsburg", "team:football:deu:freiburg",
        "team:football:deu:monchengladbach", "team:football:deu:frankfurt", "team:football:deu:st_pauli",
        "team:football:deu:union_berlin", "team:football:deu:heidenheim", "team:football:deu:leipzig",
    ],
    "competition:football:eng:championship": [
        "team:football:eng:blackburn", "team:football:eng:norwich", "team:football:eng:qpr",
        "team:football:eng:stoke", "team:football:eng:swansea", "team:football:eng:west_brom",
        "team:football:eng:hull", "team:football:eng:portsmouth", "team:football:eng:birmingham",
        "team:football:eng:leicester", "team:football:eng:southampton", "team:football:eng:derby",
        "team:football:eng:middlesbrough", "team:football:eng:sheffield_wed", "team:football:eng:watford",
        "team:football:eng:charlton", "team:football:eng:ipswich", "team:football:eng:sheffield_utd",
        "team:football:eng:millwall", "team:football:eng:bristol_city", "team:football:eng:wrexham",
        "team:football:eng:coventry", "team:football:eng:preston", "team:football:eng:oxford",
    ],
    "competition:football:nld:eredivisie": [
        "team:football:nld:twente", "team:football:nld:excelsior", "team:football:nld:heracles",
        "team:football:nld:heerenveen", "team:football:nld:psv", "team:football:nld:feyenoord",
        "team:football:nld:utrecht", "team:football:nld:groningen", "team:football:nld:ajax",
        "team:football:nld:nac_breda", "team:football:nld:az", "team:football:nld:zwolle",
        "team:football:nld:go_ahead_eagles", "team:football:nld:telstar", "team:football:nld:nec",
        "team:football:nld:volendam", "team:football:nld:fortuna_sittard", "team:football:nld:sparta_rotterdam",
    ],
    "competition:football:prt:primeira_liga": [
        "team:football:prt:rio_ave", "team:football:prt:sporting", "team:football:prt:porto",
        "team:football:prt:estoril", "team:football:prt:moreirense", "team:football:prt:arouca",
        "team:football:prt:tondela", "team:football:prt:benfica", "team:football:prt:nacional",
        "team:football:prt:santa_clara", "team:football:prt:famalicao", "team:football:prt:gil_vicente",
        "team:football:prt:vitoria_guimaraes", "team:football:prt:braga", "team:football:prt:casa_pia",
        "team:football:prt:alverca", "team:football:prt:estrela_amadora", "team:football:prt:avs",
    ],
}
