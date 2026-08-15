"""Les sources historiques CONNUES, et ce qui a été vérifié de chacune.

Chaque entrée porte la preuve qui l'a établie : code HTTP relevé, fichier de
licence lu, fuseau recoupé, identités ancrées. Une source dont un axe n'a pas été
mesuré reste `UNKNOWN`, donc non routable — ce registre n'est pas un catalogue
d'intentions.

CE QUI A ÉTÉ RETIRÉ COMPTE AUTANT. Trois sources largement recommandées sont ici
classées inutilisables, et pour des raisons qu'aucune documentation ne donnait :
les dépôts tennis de Jeff Sackmann ont DISPARU (HTTP 404), la NHL interdit
explicitement le moissonnage, MLBAM restreint à un usage non commercial et non
massif. Les garder visibles évite de les redécouvrir avec enthousiasme au
prochain manque de données.

Vérifications datées du 2026-08-13, par sondage réel.
"""

from __future__ import annotations

from .capability import CapabilityRegistry, HistoricalProviderCapability
from .classification import Axe, AxeMesure, SourceClassification

OUI = Axe.OUI
NON = Axe.NON


def _m(valeur: Axe, preuve: str) -> AxeMesure:
    return AxeMesure(valeur, preuve)


# ── football : openfootball ─────────────────────────────────────────────────
OPENFOOTBALL = SourceClassification(
    source="openfootball",
    reachable=_m(OUI, "HTTP 200 sur 15 saisons de champions-league/, 2011-12 -> 2025-26"),
    licence=_m(OUI, "LICENSE.md lu : CC0 1.0 Universal (domaine public, usage commercial libre)"),
    licence_id="CC0-1.0",
    provenance=_m(OUI, "organisation GitHub openfootball, dépôts versionnés, fichiers datés"),
    structured=_m(OUI, "Football.TXT : 1997 rencontres analysées, 0 ligne non reconnue"),
    identity_compatible=_m(OUI, "81 clubs ancrés + 14 alias par instant, 0 contradiction"),
    point_in_time_capable=_m(OUI, "fuseau Europe/Zurich recoupé contre football-data.org : "
                                  "503/503 concordants, écart max 0 min"),
    notes="Distingue tirs au but / prolongation / temps réglementaire — d'où le "
          "score 90 minutes exact, que football-data.org ne donne que via regularTime.")

# ── american_football : nflverse ────────────────────────────────────────────
NFLVERSE = SourceClassification(
    source="nflverse",
    reachable=_m(OUI, "HTTP 200, games.csv 2 175 363 octets, 7 548 lignes"),
    licence=_m(OUI, "endpoint /license : LICENSE.md = CC-BY-4.0 (attribution requise)"),
    licence_id="CC-BY-4.0",
    provenance=_m(OUI, "release `schedules` du dépôt nflverse/nflverse-data"),
    structured=_m(OUI, "CSV, 7 548 lignes analysées, 0 non reconnue"),
    identity_compatible=_m(OUI, "32 franchises sur 32 ancrées par instant, 0 contradiction"),
    point_in_time_capable=_m(OUI, "fuseau America/New_York recoupé : 852/854 concordants"),
    notes="Attribution obligatoire à la redistribution. `nflverse/nfldata` — où vit "
          "aussi un games.csv — n'a AUCUNE licence et reste donc exclu.")

# ── american_football : nflverse, release JOUEUR ────────────────────────────
#
# La MÊME organisation et la MÊME licence que la release `schedules` déjà
# enregistrée, mais une release DIFFÉRENTE et une entité différente : ce n'est pas
# le même besoin, et le confondre aurait laissé croire que les props étaient
# couvertes depuis le début.
NFLVERSE_JOUEUR = SourceClassification(
    source="nflverse (release `player_stats`)",
    reachable=_m(OUI, "HTTP 200, player_stats.csv 33 447 747 octets, "
                      "134 470 lignes joueur-semaine, 53 colonnes"),
    licence=_m(OUI, "LICENSE.md du dépôt lu : Attribution 4.0 International (CC-BY-4.0)"),
    licence_id="CC-BY-4.0",
    provenance=_m(OUI, "release `player_stats` du dépôt nflverse/nflverse-data"),
    structured=_m(OUI, "CSV, 134 470 lignes analysées, 0 non reconnue ; colonnes "
                       "completions/attempts/passing_yards/passing_tds/interceptions/"
                       "carries/rushing_yards/rushing_tds/receptions/targets/"
                       "receiving_yards/receiving_tds/target_share"),
    identity_compatible=_m(Axe.UNKNOWN,
                           "identifiants `player_id` nflverse ; AUCUN pont vers un "
                           "nom Winamax n'a pu être mesuré — le catalogue n'expose "
                           "aucune prop NFL à ce jour"),
    point_in_time_capable=_m(OUI, "granularité SEMAINE avec `season`/`week`/`season_type` : "
                                  "l'ordre chronologique est reconstructible sans ambiguïté, "
                                  "playoffs compris"),
    notes="Attribution obligatoire à la redistribution. 26 saisons (1999-2024) ; "
          "s'arrête une saison avant le présent, ce qui est une contrainte de "
          "domaine à surveiller au moment de pricer.")

# ── baseball : Retrosheet ───────────────────────────────────────────────────
RETROSHEET = SourceClassification(
    source="retrosheet",
    reachable=_m(OUI, "HTTP 200, gl2024.zip 465 881 octets"),
    licence=_m(OUI, "notice.txt : « any desired use […] including selling it » — "
                    "usage commercial explicitement autorisé, attribution imposée"),
    licence_id="Retrosheet-notice (commercial autorisé, attribution obligatoire)",
    provenance=_m(OUI, "retrosheet.org, game logs 1871-2024"),
    structured=_m(OUI, "game logs à format fixe, documenté"),
    identity_compatible=AxeMesure(Axe.UNKNOWN, "aucun ancrage tenté : le besoin baseball "
                                               "n'est pas ouvert (couverture MLB 0.9845)"),
    point_in_time_capable=AxeMesure(Axe.UNKNOWN, "fuseau non recoupé, faute de besoin"),
    notes="Prête à l'emploi côté licence ; l'identité et le fuseau restent à vérifier "
          "le jour où un manque baseball s'ouvrira.")

# ── tennis : les deux impasses ──────────────────────────────────────────────
SACKMANN_AMONT = SourceClassification(
    source="JeffSackmann/tennis_atp + tennis_wta (amont)",
    reachable=_m(NON, "HTTP 404 sur les deux dépôts le 2026-08-13 ; la liste publique "
                      "de l'auteur ne contient plus que tennis_MatchChartingProject"),
    licence=AxeMesure(Axe.UNKNOWN, "sans objet : la source n'existe plus"),
    provenance=_m(OUI, "auteur identifié, historiquement la référence du domaine"),
    structured=_m(OUI, "CSV par saison"),
    identity_compatible=AxeMesure(Axe.UNKNOWN, ""),
    point_in_time_capable=AxeMesure(Axe.UNKNOWN, ""),
    notes="Dépôt d'origine supprimé. tennisabstract.com y renvoie toujours — le lien "
          "est mort. Les données survivent dans des forks (ci-dessous).")

SACKMANN_ATP_FORK = SourceClassification(
    source="stakah/tennis_atp (fork Sackmann, ATP)",
    reachable=_m(OUI, "HTTP 200 ; tour 1968-2018, qual_chall 1991-2018 (28 fichiers), "
                      "futures 1991-2018 (28 fichiers) ; 122 Mo récupérés"),
    licence=_m(OUI, "README.md : bloc CC BY-NC-SA 4.0 explicite, « Tennis databases, "
                    "files, and algorithms by Jeff Sackmann / Tennis Abstract ». "
                    "Compatible avec un usage PERSONNEL non commercial ; l'attribution "
                    "et la clause ShareAlike accompagnent toute redistribution"),
    licence_id="CC-BY-NC-SA-4.0",
    provenance=_m(OUI, "fork identifié d'un dépôt d'auteur connu, texte de licence conservé"),
    structured=_m(OUI, "557 633 rencontres analysées, 0 ligne non reconnue"),
    identity_compatible=_m(OUI, "1 715 joueurs rapprochés de tennis-data.co.uk par clé "
                                "exacte (patronyme, initiale), 18 358 identités frappées "
                                "dans la même convention, 11 refus pour ambiguïté réelle"),
    point_in_time_capable=_m(OUI, "date de TOURNOI décalée à sa fin présumée (+7 j) : "
                                  "aucune rencontre ne peut informer une décision "
                                  "antérieure à la fin de son épreuve"),
    notes="USAGE PERSONNEL NON COMMERCIAL UNIQUEMENT. Le miroir n'est plus alimenté "
          "depuis 2018 : c'est la borne du backfill, pas un choix.")

SACKMANN_WTA_FORK = SourceClassification(
    source="ppaulojr/tennis_wta (fork Sackmann, WTA)",
    reachable=_m(OUI, "HTTP 200 ; wta_matches 1968-2015, wta_matches_qual_itf 1969-2015 "
                      "(46 fichiers) — exactement le manque WTA mesuré"),
    licence=_m(NON, "AUCUNE licence : ni LICENSE, ni LICENSE.md, ni COPYING (HTTP 404), "
                    "et le README ne porte pas le bloc CC de l'amont. Le fork date de "
                    "2015, probablement d'avant son ajout"),
    licence_id="",
    provenance=_m(OUI, "contenu identique à la base Sackmann, auteur d'origine identifiable"),
    structured=_m(OUI, "CSV annuels, même format que l'ATP"),
    identity_compatible=AxeMesure(Axe.UNKNOWN, "non tenté : la licence bloque en amont"),
    point_in_time_capable=AxeMesure(Axe.UNKNOWN, ""),
    notes="STOP §7 — licence ambiguë. Fermerait une grande part des 11 815 prédictions "
          "WTA perdues, et c'est précisément pourquoi l'absence de licence doit bloquer "
          "plutôt que se négocier. Recherché sur quatre requêtes : aucun miroir WTA "
          "portant la licence en clair n'existe.")

KAGGLE_ATP_WTA = SourceClassification(
    source="kaggle taylorbrownlow/atpwta-tennis-data",
    reachable=_m(OUI, "jeton API fourni, HTTP 200 ; archive 16 Mo -> 88 Mo, "
                      "KaggleMatches.csv (373 436 lignes) + KagglePlayers.csv"),
    licence=_m(OUI, "`licenseName` rendu par l'API : CC BY-NC-SA 4.0 — CONFORME à "
                    "l'annonce. Usage personnel non commercial ; attribution et "
                    "ShareAlike accompagnent toute redistribution"),
    licence_id="CC-BY-NC-SA-4.0",
    provenance=_m(OUI, "dataset v1 de Taylor Brownlow, maj 2021-03-08, dérivé des "
                       "bases Sackmann"),
    structured=_m(OUI, "CSV format Sackmann + colonne `league` ; 195 452 rencontres "
                       "WTA analysées, 0 ligne non reconnue"),
    identity_compatible=_m(OUI, "identifiant joueur STABLE + genre : 1 591 rencontres "
                                "écartées sur 195 452, 46 refus de genre, homonymes "
                                "séparés par identifiant plutôt que fusionnés"),
    point_in_time_capable=_m(OUI, "date de TOURNOI décalée à sa fin présumée (+7 j), "
                                  "même règle conservatrice que Sackmann"),
    auth_required=True,
    notes="CE QU'IL CONTIENT VRAIMENT, mesuré : WTA 195 498 (1949-2021), ATP 177 938 "
          "(1968-2021). NI qualifications (1 seul tour `Q` sur 195 498) NI Challenger "
          "côté ATP (niveaux A/G/M/D/F). L'« archive ITF de 220 000 rencontres » lue "
          "ailleurs ne concerne PAS ce jeu : `C` et `CC` n'en donnent que 3 664. Son "
          "apport réel est la PROFONDEUR WTA — tennis-data ne remonte qu'à 2007.")

TML_DATABASE = SourceClassification(
    source="Tennismylife/TML-Database",
    reachable=_m(OUI, "HTTP 200, CSV annuels 1968-2025"),
    licence=_m(NON, "aucun fichier de licence, API GitHub : license = null"),
    licence_id="",
    provenance=_m(OUI, "dépôt GitHub actif, se déclare successeur de tennis_atp"),
    structured=_m(OUI, "CSV annuels"),
    identity_compatible=AxeMesure(Axe.UNKNOWN, ""),
    point_in_time_capable=AxeMesure(Axe.UNKNOWN, ""),
    notes="STOP §20 : LICENSE_UNCLEAR. Le contenu conviendrait exactement au manque "
          "tennis mesuré (22,6 % ATP / 25,3 % WTA) — c'est précisément pourquoi "
          "l'absence de licence doit bloquer plutôt que se négocier.")

# ── hockey / baseball officiels : interdits par leurs conditions ────────────
NHL_API = SourceClassification(
    source="api-web.nhle.com",
    reachable=_m(OUI, "HTTP 200 sans clé, historique annoncé depuis 1917"),
    licence=_m(NON, "CGU §2 : « unauthorized spidering, scraping, or harvesting » "
                    "prohibé ; §7 : usage « non-commercial, informational, personal » "
                    "uniquement"),
    licence_id="NHL Terms of Service (usage automatisé interdit)",
    provenance=_m(OUI, "source officielle de la ligue"),
    structured=_m(OUI, "JSON"),
    identity_compatible=AxeMesure(Axe.UNKNOWN, ""),
    point_in_time_capable=AxeMesure(Axe.UNKNOWN, ""),
    notes="Techniquement ouverte, contractuellement fermée. L'accessibilité n'est "
          "pas une permission.")

MLB_STATSAPI = SourceClassification(
    source="statsapi.mlb.com",
    reachable=_m(OUI, "HTTP 200 sans clé"),
    licence=_m(NON, "copyright.txt : « Only individual, non-commercial, non-bulk use "
                    "of the Materials is permitted »"),
    licence_id="MLBAM copyright notice (non commercial, non massif)",
    provenance=_m(OUI, "source officielle de la ligue"),
    structured=_m(OUI, "JSON"),
    identity_compatible=AxeMesure(Axe.UNKNOWN, ""),
    point_in_time_capable=AxeMesure(Axe.UNKNOWN, ""),
    notes="Un backfill est par définition un usage massif : la restriction vise "
          "exactement ce qu'on voudrait en faire.")

BALLDONTLIE = SourceClassification(
    source="api.balldontlie.io",
    reachable=_m(NON, "HTTP 401 sans clé"),
    licence=AxeMesure(Axe.UNKNOWN, "non lue : l'accès requiert une inscription"),
    provenance=_m(OUI, "API basket tierce établie"),
    structured=_m(OUI, "JSON"),
    identity_compatible=AxeMesure(Axe.UNKNOWN, ""),
    point_in_time_capable=AxeMesure(Axe.UNKNOWN, ""),
    auth_required=True,
    notes="TIER GRATUIT INSUFFISANT, mesuré le 2026-08-15 sur la documentation "
          "publique. Le tableau des tiers donne, endpoint par endpoint : Teams / "
          "Players / Games = « Yes » en gratuit, mais « Game Player Stats » = "
          "« No » — c'est-à-dire exactement la seule chose dont un modèle de prop "
          "a besoin. Le box score par joueur est au tier ALL-STAR, 9,99 $/mois et "
          "PAR SPORT ; le gratuit est en outre limité à 5 requêtes/minute. Une clé "
          "gratuite ne débloquerait donc rien : il n'y a pas de credential à "
          "demander, il y a un abonnement à refuser.")

BEACH_VOLLEY = SourceClassification(
    source="BigTimeStats/beach-volleyball",
    reachable=_m(OUI, "HTTP 200"),
    licence=AxeMesure(Axe.UNKNOWN, "non déclarée"),
    provenance=_m(OUI, "dépôt GitHub identifié"),
    structured=_m(OUI, "CSV"),
    identity_compatible=_m(NON, "volley de PLAGE — discipline différente du volley en "
                                "salle modélisé par AXON (Italie A1)"),
    point_in_time_capable=AxeMesure(Axe.UNKNOWN, ""),
    notes="Mauvais sport, et arrêtée en janvier 2022. Aucune source d'historique "
          "de volley EN SALLE, libre et structurée, n'a été trouvée.")


def registre_par_defaut() -> CapabilityRegistry:
    """Les capacités telles que MESURÉES. Aucune n'est déclarative."""
    return CapabilityRegistry([
        HistoricalProviderCapability(
            provider="openfootball", sport="football", competitions=("*",),
            historical_depth_years=15, entity_types=("team", "competition"),
            data_kinds=("results", "scores", "timestamps"), access_type="OPEN",
            classification=OPENFOOTBALL, earliest_season="2011-12",
            latest_season="2025-26", provenance_quality="COMMUNITY",
            detail={"repos": ["champions-league", "europe", "england", "deutschland",
                              "espana", "italy", "world", "leagues"]}),
        HistoricalProviderCapability(
            provider="nflverse", sport="american_football",
            competitions=("competition:american_football:usa:nfl",),
            historical_depth_years=28, entity_types=("team",),
            data_kinds=("results", "scores", "timestamps"), access_type="OPEN",
            classification=NFLVERSE, earliest_season="1999", latest_season="2026",
            provenance_quality="COMMUNITY"),
        HistoricalProviderCapability(
            provider="nflverse_player_stats", sport="american_football",
            competitions=("competition:american_football:usa:nfl",),
            historical_depth_years=26, entity_types=("player",),
            data_kinds=("results", "scores"), access_type="OPEN",
            classification=NFLVERSE_JOUEUR, earliest_season="1999",
            latest_season="2024", provenance_quality="COMMUNITY",
            detail={"lignes": 134470, "colonnes": 53,
                    "familles_couvertes": ["passing_yards", "attempts", "passing_tds",
                                           "interceptions", "carries", "rushing_yards",
                                           "rushing_tds", "receptions", "targets",
                                           "receiving_yards", "receiving_tds"],
                    "feature_usage": "target_share (disponible AVANT le match)",
                    "marche_winamax": "0 prop observée sur 16 événements NFL "
                                      "(2026-08-15) — la saison ouvre le 10 septembre"}),
        HistoricalProviderCapability(
            provider="retrosheet", sport="baseball", competitions=("*",),
            historical_depth_years=154, entity_types=("team",),
            data_kinds=("results", "scores"), access_type="OPEN",
            classification=RETROSHEET, earliest_season="1871", latest_season="2024",
            provenance_quality="COMMUNITY"),
        HistoricalProviderCapability(
            provider="tennis_abstract_amont", sport="tennis", competitions=("*",),
            historical_depth_years=None, entity_types=("player",),
            data_kinds=("results", "rankings"), access_type="OPEN",
            classification=SACKMANN_AMONT, provenance_quality="COMMUNITY"),
        HistoricalProviderCapability(
            provider="sackmann_atp_fork", sport="tennis",
            competitions=("competition:tennis:atp:tour",),
            historical_depth_years=27, entity_types=("player",),
            data_kinds=("results", "rankings"), access_type="OPEN",
            classification=SACKMANN_ATP_FORK, earliest_season="1991",
            latest_season="2018", provenance_quality="COMMUNITY",
            detail={"circuits": ["challenger_qualifying", "futures", "tour"],
                    "retenus": ["challenger_qualifying", "tour"],
                    "futures_ecartes": "ΔBrier 6× pire pour 2 points de couverture"}),
        HistoricalProviderCapability(
            provider="sackmann_wta_fork", sport="tennis",
            competitions=("competition:tennis:wta:tour",),
            historical_depth_years=47, entity_types=("player",),
            data_kinds=("results",), access_type="OPEN",
            classification=SACKMANN_WTA_FORK, earliest_season="1968",
            latest_season="2015", provenance_quality="COMMUNITY"),
        HistoricalProviderCapability(
            provider="kaggle_atp_wta", sport="tennis", competitions=("*",),
            historical_depth_years=72, entity_types=("player",),
            data_kinds=("results",), access_type="API_KEY",
            classification=KAGGLE_ATP_WTA, earliest_season="1949",
            latest_season="2021", provenance_quality="COMMUNITY",
            detail={"categories": ["tour", "equipes", "itf", "exhibition", "junior"],
                    "retenues": ["tour", "equipes", "itf"],
                    "sans_qualifications": True, "sans_challenger_atp": True}),
        HistoricalProviderCapability(
            provider="tml_database", sport="tennis", competitions=("*",),
            historical_depth_years=57, entity_types=("player",),
            data_kinds=("results",), access_type="OPEN",
            classification=TML_DATABASE, earliest_season="1968",
            latest_season="2025", provenance_quality="COMMUNITY"),
        HistoricalProviderCapability(
            provider="nhl_official", sport="hockey", competitions=("*",),
            historical_depth_years=108, entity_types=("team",),
            data_kinds=("results", "scores", "timestamps"), access_type="OPEN",
            classification=NHL_API, provenance_quality="OFFICIAL"),
        HistoricalProviderCapability(
            provider="mlb_statsapi", sport="baseball", competitions=("*",),
            historical_depth_years=None, entity_types=("team",),
            data_kinds=("results", "scores", "timestamps"), access_type="OPEN",
            classification=MLB_STATSAPI, provenance_quality="OFFICIAL"),
        HistoricalProviderCapability(
            provider="balldontlie", sport="basketball", competitions=("*",),
            historical_depth_years=None, entity_types=("team", "player"),
            data_kinds=("results", "scores"), access_type="API_KEY",
            classification=BALLDONTLIE, provenance_quality="COMMUNITY"),
        HistoricalProviderCapability(
            provider="bigtimestats_beach", sport="volleyball", competitions=("*",),
            historical_depth_years=22, entity_types=("team",),
            data_kinds=("results",), access_type="OPEN",
            classification=BEACH_VOLLEY, provenance_quality="COMMUNITY"),
    ])
