"""Chargement de datasets RÉELS football-data.org -> list[CanonicalMatch].

Source : fixtures football-data.org enregistrées (`fl1_2025_matches.json`,
`sa_2025_matches.json`…), données réelles (mêmes payloads que les endpoints live,
provenance football_data_org). Chaque équipe est résolue en `canonical_id` via
l'identity_resolver de la gateway ; le `dataset_fingerprint` (sha256 du fichier
brut) ancre la reproductibilité.

Aucune donnée synthétique ici. Le chargeur est GÉNÉRIQUE (compétition-agnostique) :
onboarder une compétition = fournir sa fixture + son `league_id` canonique + saison
(mêmes IDs football_data_org, même walk-forward, aucune adaptation ad hoc — §6/§10).
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from src.agents.quant.gateway.core.identity_resolver import IdentityResolver
from src.agents.quant.gateway.sports.football.canonical_facts import CanonicalMatch
from src.agents.quant.betting_engine.calibration.experiment_registry import dataset_fingerprint

_FIXTURES = Path(__file__).resolve().parents[5] / "tests" / "fixtures"

FL1_LEAGUE_ID = "competition:football:fra:ligue1"
FL1_SEASON = "2025"
DEFAULT_FL1_FIXTURE = _FIXTURES / "fl1_2025_matches.json"

SA_LEAGUE_ID = "competition:football:ita:serie_a"
SA_SEASON = "2025"
DEFAULT_SA_FIXTURE = _FIXTURES / "sa_2025_matches.json"

PD_LEAGUE_ID = "competition:football:esp:laliga"
PD_SEASON = "2025"
DEFAULT_PD_FIXTURE = _FIXTURES / "pd_2025_matches.json"

BL1_LEAGUE_ID = "competition:football:deu:bundesliga"
BL1_SEASON = "2025"
DEFAULT_BL1_FIXTURE = _FIXTURES / "bl1_2025_matches.json"

ELC_LEAGUE_ID = "competition:football:eng:championship"
ELC_SEASON = "2025"
DEFAULT_ELC_FIXTURE = _FIXTURES / "elc_2025_matches.json"

DED_LEAGUE_ID = "competition:football:nld:eredivisie"
DED_SEASON = "2025"
DEFAULT_DED_FIXTURE = _FIXTURES / "ded_2025_matches.json"

PPL_LEAGUE_ID = "competition:football:prt:primeira_liga"
PPL_SEASON = "2025"
DEFAULT_PPL_FIXTURE = _FIXTURES / "ppl_2025_matches.json"


def load_competition_season(
    resolver: IdentityResolver, path: Path, league_id: str, season: str,
):
    """GÉNÉRIQUE — `(matches, dataset_fingerprint, n_total_finished)`.

    Ne garde que les matchs FINISHED avec score ET dont les deux équipes résolvent
    en canonical_id (comptés dans `n_total_finished` mais écartés sinon : une équipe
    non résolue reste explicitement absente, jamais devinée)."""
    raw = path.read_bytes()
    data = json.loads(raw)

    matches: list[CanonicalMatch] = []
    n_finished = 0
    for m in data["matches"]:
        if m.get("status") != "FINISHED":
            continue
        full = m.get("score", {}).get("fullTime", {})
        gh, ga = full.get("home"), full.get("away")
        if gh is None or ga is None:
            continue
        n_finished += 1
        home_id, home_status = resolver.canonicalize("football_data_org", str(m["homeTeam"]["id"]), "team")
        away_id, away_status = resolver.canonicalize("football_data_org", str(m["awayTeam"]["id"]), "team")
        if home_status != "RESOLVED" or away_status != "RESOLVED":
            continue
        matches.append(CanonicalMatch(
            canonical_match_id=str(m["id"]),
            league_id=league_id,
            season=season,
            home_team_id=home_id,
            away_team_id=away_id,
            kickoff=datetime.fromisoformat(m["utcDate"].replace("Z", "+00:00")),
            status="FINISHED",
            goals_home=int(gh),
            goals_away=int(ga),
        ))
    return matches, dataset_fingerprint(raw), n_finished


CL_LEAGUE_ID = "competition:football:eur:champions_league"
DEFAULT_CL_FIXTURE = _FIXTURES / "cl_backfilled_matches.json"

EL_LEAGUE_ID = "competition:football:eur:europa_league"
DEFAULT_EL_FIXTURE = _FIXTURES / "el_backfilled_matches.json"

CONF_LEAGUE_ID = "competition:football:eur:conference_league"
DEFAULT_CONF_FIXTURE = _FIXTURES / "conf_backfilled_matches.json"


def load_canonical_corpus(path: Path, league_id: str):
    """Corpus DÉJÀ canonique — `(matches, fingerprint, n_total)`.

    Les chargeurs ci-dessus partent d'un payload football-data.org et résolvent
    chaque équipe via l'`IdentityResolver`, dont le référentiel ne contient que
    les clubs des championnats onboardés. Une coupe d'Europe y perdrait presque
    tout : ses clubs viennent de cinquante pays, et les inscrire à la main
    reviendrait à tenir une liste qui se périme chaque saison.

    Ici la résolution d'identité a DÉJÀ eu lieu, en amont, dans
    `historical_discovery` — rapprochement inter-provider prouvé, dédoublonnage
    et conflits compris. Le fichier porte sa provenance ; ce chargeur ne fait
    que la relire, sans rien réinterpréter.

    C'est aussi le format qu'utilisera la PROCHAINE compétition backfillée :
    aucun code par compétition, juste une fixture et un `league_id`.
    """
    raw = path.read_bytes()
    data = json.loads(raw)
    matches = [
        CanonicalMatch(
            canonical_match_id=m["canonical_match_id"], league_id=m["league_id"],
            season=m["season"], home_team_id=m["home_team_id"],
            away_team_id=m["away_team_id"],
            kickoff=datetime.fromisoformat(m["kickoff"]), status="FINISHED",
            goals_home=int(m["goals_home"]), goals_away=int(m["goals_away"]))
        for m in data["matches"]
        if m.get("status") == "FINISHED"
        and m.get("goals_home") is not None and m.get("goals_away") is not None
        and m.get("league_id") == league_id
    ]
    matches.sort(key=lambda m: m.kickoff)
    return matches, dataset_fingerprint(raw), len(data["matches"])


def load_cl(path: Path | None = None):
    """Ligue des Champions — fdo + api-sports + openfootball (15 saisons)."""
    return load_canonical_corpus(path or DEFAULT_CL_FIXTURE, CL_LEAGUE_ID)


def load_el(path: Path | None = None):
    """Ligue Europa — openfootball seul (aucun provider gratuit ne la sert)."""
    return load_canonical_corpus(path or DEFAULT_EL_FIXTURE, EL_LEAGUE_ID)


def load_conf(path: Path | None = None):
    """Conference League — openfootball seul, compétition créée en 2021."""
    return load_canonical_corpus(path or DEFAULT_CONF_FIXTURE, CONF_LEAGUE_ID)


#: Saisons historiques acquises (football-data.org, free tier). 2022 et
#: antérieures répondent 403 : hors fenêtre gratuite, pas hors existence.
HISTORICAL_SEASONS = ("2023", "2024")


def load_competition_history(
    resolver: IdentityResolver, prefixe: str, league_id: str, season: str,
    path: Path | None = None,
):
    """Toutes les saisons disponibles d'une compétition, dans l'ordre chronologique.

    Une seule saison laisse presque toutes les équipes sans historique au début du
    corpus : le cold-start y est mécaniquement maximal, et l'échantillon plafonne
    à ~300 matchs. Empiler les saisons antérieures ne change ni le modèle ni ses
    paramètres — cela donne simplement au walk-forward un passé à lire avant de
    prédire.

    L'ordre chronologique n'est pas cosmétique : le rejeu walk-forward suppose que
    les matchs arrivent dans le temps, et mélanger les saisons ferait prédire 2023
    avec des notes acquises en 2025. `path` force une saison unique (tests).
    """
    if path is not None:
        return load_competition_season(resolver, path, league_id, season)

    tous: list[CanonicalMatch] = []
    empreintes: list[str] = []
    n_finished = 0
    for saison in (*HISTORICAL_SEASONS, season):
        fichier = _FIXTURES / f"{prefixe}_{saison}_matches.json"
        if not fichier.exists():
            continue
        matchs, empreinte, n = load_competition_season(
            resolver, fichier, league_id, saison)
        tous.extend(matchs)
        empreintes.append(empreinte)
        n_finished += n

    tous.sort(key=lambda m: m.kickoff)
    return tous, dataset_fingerprint("|".join(empreintes).encode()), n_finished


def load_fl1_2025(resolver: IdentityResolver, path: Path = None):
    """Ligue 1 — toutes saisons acquises."""
    return load_competition_history(resolver, "fl1", FL1_LEAGUE_ID, FL1_SEASON, path)


def load_sa_2025(resolver: IdentityResolver, path: Path = None):
    """Serie A 2025-26 (wrapper du chargeur générique) — onboardée le 2026-07-31."""
    return load_competition_history(resolver, "sa", SA_LEAGUE_ID, SA_SEASON, path)


def load_pd_2025(resolver: IdentityResolver, path: Path = None):
    """LaLiga 2025-26 (wrapper du chargeur générique)."""
    return load_competition_history(resolver, "pd", PD_LEAGUE_ID, PD_SEASON, path)


def load_bl1_2025(resolver: IdentityResolver, path: Path = None):
    """Bundesliga (Allemagne) 2025-26 (wrapper du chargeur générique)."""
    return load_competition_history(resolver, "bl1", BL1_LEAGUE_ID, BL1_SEASON, path)


def load_elc_2025(resolver: IdentityResolver, path: Path = None):
    """Championship anglaise 2025-26 (wrapper du chargeur générique)."""
    return load_competition_history(resolver, "elc", ELC_LEAGUE_ID, ELC_SEASON, path)


def load_ded_2025(resolver: IdentityResolver, path: Path = None):
    """Eredivisie 2025-26 (wrapper du chargeur générique)."""
    return load_competition_history(resolver, "ded", DED_LEAGUE_ID, DED_SEASON, path)


def load_ppl_2025(resolver: IdentityResolver, path: Path = None):
    """Primeira Liga 2025-26 (wrapper du chargeur générique)."""
    return load_competition_history(resolver, "ppl", PPL_LEAGUE_ID, PPL_SEASON, path)
