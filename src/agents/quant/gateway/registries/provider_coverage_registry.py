"""Provider Coverage Registry — couverture par (provider, competition, season, data_type).

PRD v2 §7.2, ADR-007, GW-FR-003/005. SQLite (volumineux, généré par script —
arbitrage Vague 0). Le `provider_competition_id` (ID natif de la compétition
chez le provider) vit ICI, jamais dans l'identité de compétition (GW-FR-002).

Règle dure (GW-FR-005) : une entrée UNVERIFIED n'est JAMAIS utilisable en
production. `usable_providers` ne renvoie que des couvertures FULL/PARTIAL —
jamais UNVERIFIED, jamais ABSENT.
"""

from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
import sqlite3
from src.infra import chemins as _chemins

COVERAGE_DB = _chemins.couverture_fournisseurs()

# `fixture_checksum` : dataset EMBARQUÉ dans le dépôt, vérifié par son empreinte au
# chargement. Ce n'est pas un appel réseau — le décrire comme tel serait faux — mais
# c'est une vérification plus forte : la donnée servie est exactement celle mesurée.
_VERIFICATION_METHODS = {"live_call", "provider_docs", "manual", "fixture_checksum"}

# Version de la baseline `known_coverage()`. À INCRÉMENTER dès qu'une entrée y est
# ajoutée, retirée ou corrigée : c'est ce numéro qui déclenche la ré-application
# sur une base déjà initialisée. Sans lui, une correction de couverture ne serait
# jamais reprise sur les installations existantes.
BASELINE_VERSION = 6


class CoverageStatus(str, Enum):
    FULL = "FULL"
    PARTIAL = "PARTIAL"
    ABSENT = "ABSENT"
    UNVERIFIED = "UNVERIFIED"


# Seuls ces statuts autorisent l'usage en production (GW-FR-005).
USABLE_STATUSES = (CoverageStatus.FULL, CoverageStatus.PARTIAL)


@dataclass(frozen=True)
class ProviderCompetitionCoverage:
    provider: str
    competition_id: str
    provider_competition_id: str         # ID natif de la compétition chez ce provider
    season: str
    data_type: str
    status: CoverageStatus
    verified_at: datetime
    verification_method: str             # live_call | provider_docs | manual
    historical_depth_years: int | None = None
    notes: str | None = None

    def __post_init__(self) -> None:
        if self.verification_method not in _VERIFICATION_METHODS:
            raise ValueError(f"verification_method invalide : {self.verification_method!r}")


def _connection(db_path: Path | None = None) -> sqlite3.Connection:
    """Ouvre la base et garantit qu'elle porte le schéma ET la baseline versionnée.

    Le bootstrap vit ICI, au premier accès, et non à l'import : un import ne doit
    rien écrire sur le disque. Il vit ici plutôt que dans l'entrypoint parce que
    la panne à éviter est silencieuse — une installation neuve renvoyait des
    couvertures vides, donc `PROVIDER_COVERAGE_MISSING` sur des compétitions
    pourtant déclarées et vérifiées, sans que rien ne signale l'étape manquante.
    Un seed manuel qu'on peut oublier n'est pas une garantie.
    """
    path = db_path or COVERAGE_DB
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS coverage (
            provider TEXT, competition_id TEXT, provider_competition_id TEXT,
            season TEXT, data_type TEXT, status TEXT, verified_at TEXT,
            verification_method TEXT, historical_depth_years INTEGER, notes TEXT,
            PRIMARY KEY (provider, competition_id, season, data_type)
        )
    """)
    conn.execute("CREATE TABLE IF NOT EXISTS registry_meta (key TEXT PRIMARY KEY, value TEXT)")
    _apply_baseline(conn)
    return conn


def _apply_baseline(conn: sqlite3.Connection) -> int:
    """Applique `known_coverage()` si la base n'est pas déjà à `BASELINE_VERSION`.

    Idempotent : au-delà du premier appel, coûte un SELECT et rien d'autre.
    ADDITIF : n'écrit que sur les clés de la baseline elle-même. Une couverture
    enregistrée par ailleurs — vérification manuelle, script d'exploitation — n'est
    jamais touchée, et rien n'est jamais supprimé.
    """
    row = conn.execute(
        "SELECT value FROM registry_meta WHERE key = 'baseline_version'").fetchone()
    if row is not None and int(row[0]) >= BASELINE_VERSION:
        return 0

    entries = known_coverage()
    conn.executemany(
        "INSERT OR REPLACE INTO coverage VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [(e.provider, e.competition_id, e.provider_competition_id, e.season,
          e.data_type, e.status.value, e.verified_at.isoformat(),
          e.verification_method, e.historical_depth_years, e.notes) for e in entries],
    )
    conn.execute("INSERT OR REPLACE INTO registry_meta VALUES ('baseline_version', ?)",
                 (str(BASELINE_VERSION),))
    conn.commit()
    return len(entries)


def _row_to_entry(row: tuple) -> ProviderCompetitionCoverage:
    return ProviderCompetitionCoverage(
        provider=row[0],
        competition_id=row[1],
        provider_competition_id=row[2],
        season=row[3],
        data_type=row[4],
        status=CoverageStatus(row[5]),
        verified_at=datetime.fromisoformat(row[6]),
        verification_method=row[7],
        historical_depth_years=row[8],
        notes=row[9],
    )


def record_coverage(entry: ProviderCompetitionCoverage, db_path: Path | None = None) -> None:
    conn = _connection(db_path)
    try:
        conn.execute(
            "INSERT OR REPLACE INTO coverage VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                entry.provider, entry.competition_id, entry.provider_competition_id,
                entry.season, entry.data_type, entry.status.value,
                entry.verified_at.isoformat(), entry.verification_method,
                entry.historical_depth_years, entry.notes,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def get_coverage(
    provider: str, competition_id: str, season: str, data_type: str, db_path: Path | None = None
) -> ProviderCompetitionCoverage | None:
    conn = _connection(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM coverage WHERE provider=? AND competition_id=? AND season=? AND data_type=?",
            (provider, competition_id, season, data_type),
        ).fetchone()
        return _row_to_entry(row) if row else None
    finally:
        conn.close()


def all_coverage(competition_id: str, season: str, db_path: Path | None = None) -> list[ProviderCompetitionCoverage]:
    """Toutes les entrées de couverture connues pour une compétition/saison (diagnostic CLI)."""
    conn = _connection(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM coverage WHERE competition_id=? AND season=? ORDER BY data_type, provider",
            (competition_id, season),
        ).fetchall()
        return [_row_to_entry(r) for r in rows]
    finally:
        conn.close()


def usable_providers(competition_id: str, season: str, data_type: str, db_path: Path | None = None) -> list[str]:
    """Providers dont la couverture est FULL/PARTIAL pour ce couple exact.

    Jamais UNVERIFIED, jamais ABSENT (GW-FR-005). C'est ce que consommera
    l'éligibilité du fallback_chain à C5 (§8.1 points 2-3).
    """
    conn = _connection(db_path)
    try:
        rows = conn.execute(
            "SELECT provider FROM coverage "
            "WHERE competition_id=? AND season=? AND data_type=? AND status IN (?, ?)",
            (competition_id, season, data_type, CoverageStatus.FULL.value, CoverageStatus.PARTIAL.value),
        ).fetchall()
        return [r[0] for r in rows]
    finally:
        conn.close()


# ── Couverture connue (baseline vérifiée) ────────────────────────────────────────

_L1 = "competition:football:fra:ligue1"
_PL = "competition:football:eng:premier_league"

# Les 8 compétitions domestiques onboardées, avec leur code football-data.org.
# Toutes vérifiées par appel réel le 2026-08-05 (cf. notes ci-dessous) : jusque-là
# seule la Ligue 1 figurait ici, si bien que les sept autres avaient une identité
# complète et AUCUNE couverture — donc PROVIDER_COVERAGE_MISSING quoi qu'il arrive.
# Le défaut n'était pas un manque de données, c'était une baseline jamais étendue.
_FDO_DOMESTIQUES = (
    (_L1, "FL1"),
    (_PL, "PL"),
    ("competition:football:ita:serie_a", "SA"),
    ("competition:football:esp:laliga", "PD"),
    ("competition:football:deu:bundesliga", "BL1"),
    ("competition:football:eng:championship", "ELC"),
    ("competition:football:nld:eredivisie", "DED"),
    ("competition:football:prt:primeira_liga", "PPL"),
)


#: (compétition canonique, identifiant de ligue api-sports, rencontres 2024
#: réellement comptées à la sonde). Les identifiants de ligue sont ceux qui ont
#: servi à l'acquisition historique — ce sont donc des valeurs éprouvées.
_API_SPORTS_PAIRWISE = (
    ("competition:basketball:usa:nba", "12", 1387),
    ("competition:baseball:usa:mlb", "1", 2946),
    ("competition:american_football:usa:nfl", "1", 335),
    ("competition:hockey:usa:nhl", "57", 1503),
    ("competition:volleyball:ita:serie_a1", "89", 213),
)


def known_coverage() -> list[ProviderCompetitionCoverage]:
    """Baseline de couverture — reflète des vérifications live_call réelles (voir
    coverage_verification pour re-vérifier). Honnête sur ce qui N'A PAS été
    vérifié : ces combos restent UNVERIFIED, donc inutilisables."""
    verified = datetime(2026, 7, 25, tzinfo=timezone.utc)
    verified_0805 = datetime(2026, 8, 5, tzinfo=timezone.utc)
    verified_0807 = datetime(2026, 8, 7, tzinfo=timezone.utc)
    verified_0813 = datetime(2026, 8, 13, tzinfo=timezone.utc)
    verified_0815 = datetime(2026, 8, 15, tzinfo=timezone.utc)
    entries: list[ProviderCompetitionCoverage] = []

    def add(provider, comp, prov_id, season, data_types, status, method, notes=None,
            at=verified):
        for data_type in data_types:
            entries.append(ProviderCompetitionCoverage(
                provider=provider, competition_id=comp, provider_competition_id=prov_id,
                season=season, data_type=data_type, status=status,
                verified_at=at, verification_method=method, notes=notes,
            ))

    # football-data.org — saison en cours, vérifiée live cette session
    add("football_data_org", _L1, "FL1", "2025",
        ["FIXTURES", "RESULTS", "STANDINGS"], CoverageStatus.FULL, "live_call")
    add("football_data_org", _PL, "PL", "2025", ["STANDINGS"], CoverageStatus.FULL, "live_call")

    # ── Saison 2025-26 des 8 domestiques (vérifiée le 2026-08-15) ───────────────
    # La saison 2026 démarre entre le 21 et le 28 août : au 15 août, RESULTS est
    # servi mais quasi vide (0 rencontre jouée sur six des huit championnats). La
    # seule forme disponible est donc celle de N-1 — et le report de saison ne
    # pouvait PAS aller la chercher, faute de couverture déclarée : seules la
    # Ligue 1 et les classements de Premier League l'étaient, les matchs de PL
    # restant UNVERIFIED. Six compétitions sur huit tombaient sur « aucun provider
    # éligible » à l'instant précis où le report est le seul recours.
    #
    # `/competitions/{code}/matches?season=2025` appelé pour les huit, HTTP 200,
    # rencontres TOUTES terminées : ELC 557, PD 380, SA 380, PL 380, BL1 306,
    # DED 306, PPL 306 (FL1 déjà couverte, 306). C'est le même défaut que celui
    # corrigé le 2026-08-05 sur la saison 2026 : pas un manque de données, une
    # baseline jamais étendue à l'axe SAISON.
    for comp, code, joues in (
        (_PL, "PL", 380),
        ("competition:football:eng:championship", "ELC", 557),
        ("competition:football:esp:laliga", "PD", 380),
        ("competition:football:ita:serie_a", "SA", 380),
        ("competition:football:deu:bundesliga", "BL1", 306),
        ("competition:football:nld:eredivisie", "DED", 306),
        ("competition:football:prt:primeira_liga", "PPL", 306),
    ):
        add("football_data_org", comp, code, "2025",
            ["FIXTURES", "RESULTS"], CoverageStatus.FULL, "live_call",
            notes=f"vérifié 2026-08-15 : /matches?season=2025 en HTTP 200, "
                  f"{joues} rencontres toutes terminées",
            at=verified_0815)

    # ── Saison 2026-27, les 8 domestiques (vérifiées le 2026-08-05) ──────────────
    # Deux endpoints appelés par compétition, tous HTTP 200 :
    #   /competitions/{code}/matches?season=2026   -> 306 à 552 rencontres, effectifs corrects
    #   /competitions/{code}/standings?season=2026 -> 3 tables (général/domicile/extérieur)
    # `/matches` porte le statut de chaque rencontre : il sert donc FIXTURES ET RESULTS.
    #
    # RESULTS est servi mais VIDE : 0 rencontre jouée au 5 août, les saisons démarrent
    # entre le 7 et le 28. C'est un vrai manque de données, pas une absence de
    # couverture — et la distinction est exactement l'objet de ces entrées. Sans
    # elles, l'engine répondait « aucun provider » là où il fallait lire « provider
    # présent, saison pas encore commencée ». FULL décrit la disponibilité de la
    # SOURCE, jamais la richesse de son contenu à un instant donné.
    for comp, code in _FDO_DOMESTIQUES:
        add("football_data_org", comp, code, "2026",
            ["FIXTURES", "RESULTS", "STANDINGS"], CoverageStatus.FULL, "live_call",
            notes="vérifié 2026-08-05 : /matches et /standings en HTTP 200 ; "
                  "RESULTS vide tant que la saison n'a pas démarré",
            at=verified_0805)

    # ── Trois compétitions ouvertes le 2026-08-13 (football-data.org, live_call) ─
    # Comptes RÉELS relevés, `/matches?season=` par saison, HTTP 200 :
    #   BSA 2023-2026 : 380+380+380+380 rencontres, 1 355 terminées
    #   CL  2023-2025 : 125+189+189 rencontres, 503 terminées (2026 -> HTTP 404,
    #                   la saison n'a pas commencé — absence de SAISON, pas de source)
    #   CLI 2023-2026 : 155+155+155+147 rencontres, 591 terminées
    #
    # Enregistrer cette couverture NE REND RIEN MISABLE. C'est l'axe « la source
    # existe » ; l'axe « un modèle validé s'applique » est ailleurs, et pour les
    # deux compétitions INTER-LIGUES il n'est pas franchi (cf. leurs benchmarks).
    # `/standings` sondé séparément le 2026-08-13 : BSA et CLI rendent 3 tables en
    # HTTP 200 pour 2026 ; la CL rend 404 sur les DEUX endpoints — sa saison
    # 2026-27 n'existe pas encore chez le provider. D'où son `status: inactive`
    # au registre : une compétition active sans couverture apparaît au catalogue
    # et refuse tout, ce qui est précisément le défaut qu'on répare.
    for comp, code, saisons, types in (
        ("competition:football:bra:serie_a", "BSA", ("2023", "2024", "2025", "2026"),
         ["FIXTURES", "RESULTS", "STANDINGS"]),
        ("competition:football:eur:champions_league", "CL", ("2023", "2024", "2025"),
         ["FIXTURES", "RESULTS"]),
        ("competition:football:sam:libertadores", "CLI", ("2023", "2024", "2025", "2026"),
         ["FIXTURES", "RESULTS", "STANDINGS"]),
    ):
        for saison in saisons:
            add("football_data_org", comp, code, saison, types,
                CoverageStatus.FULL, "live_call",
                notes="sondé 2026-08-13 : endpoints en HTTP 200, rencontres terminées "
                      "présentes ; couverture de SOURCE, pas de modèle",
                at=verified_0813)
    # Saison CL 2026 : absence de SAISON chez le provider, pas absence de source.
    add("football_data_org", "competition:football:eur:champions_league", "CL", "2026",
        ["FIXTURES", "RESULTS", "STANDINGS"], CoverageStatus.ABSENT, "live_call",
        notes="sondé 2026-08-13 : HTTP 404 sur /matches ET /standings — "
              "la saison 2026-27 n'a pas encore démarré",
        at=verified_0813)

    # ── Tennis : dataset tennis-data.co.uk EMBARQUÉ (ATP+WTA 2000-2026) ─────────
    # Le circuit est la compétition : c'est lui qui définit la population de joueurs
    # et le pool de notes Elo. Le tournoi n'entre dans aucune feature.
    for tour in ("atp", "wta"):
        for season in ("2025", "2026"):
            add("tennis_data", f"competition:tennis:{tour}:tour", tour, season,
                ["RESULTS"], CoverageStatus.FULL, "fixture_checksum",
                notes="fixture tests/fixtures/tennis/tennis_data_{tour}_2000_2026.csv.gz, "
                      "empreinte sha256 vérifiée au chargement",
                at=verified_0805)

    # API-Sports — tier gratuit : 2022-2024 servies, 2025+ refusée (bug fondateur)
    add("api_sports", _L1, "61", "2024", ["FIXTURES", "RESULTS", "STANDINGS"], CoverageStatus.FULL, "live_call")
    add("api_sports", _L1, "61", "2025", ["FIXTURES", "RESULTS", "STANDINGS"],
        CoverageStatus.ABSENT, "live_call", notes="tier gratuit bloque 2025+")

    # ── API-Sports, les cinq autres produits (sondés le 2026-08-07) ─────────────
    # La MÊME clé répond HTTP 200 sur les six produits : `supported_sports` valait
    # `["football"]` par décision de code, pas par limite du credential.
    #
    # La borne réelle est la SAISON, identique à celle du football : le plan
    # gratuit sert 2022-2024 et refuse au-delà avec un message explicite (« Free
    # plans do not have access to this season »). Un refus de plan renvoie
    # HTTP 200 et zéro rencontre — il ressemble à une absence de données, d'où
    # l'intérêt de l'inscrire comme ABSENT plutôt que de le laisser deviner.
    for comp, prov_id, n_2024 in _API_SPORTS_PAIRWISE:
        add("api_sports", comp, prov_id, "2024", ["FIXTURES", "RESULTS"],
            CoverageStatus.FULL, "live_call",
            notes=f"sondé 2026-08-07 : saison 2024 en HTTP 200, {n_2024} rencontres",
            at=verified_0807)
        for saison in ("2025", "2026"):
            add("api_sports", comp, prov_id, saison, ["FIXTURES", "RESULTS"],
                CoverageStatus.ABSENT, "live_call",
                notes="sondé 2026-08-07 : HTTP 200, 0 rencontre — "
                      "« Free plans do not have access to this season »",
                at=verified_0807)

    return entries


def seed(db_path: Path | None = None) -> int:
    """Ré-applique la baseline sans condition de version — commande d'exploitation.

    Le bootstrap automatique (`_apply_baseline`) suffit au cas normal. Celle-ci
    existe pour forcer la reprise après une modification manuelle de la base, et
    reste additive : elle n'efface rien.
    """
    conn = _connection(db_path)
    try:
        conn.execute("DELETE FROM registry_meta WHERE key = 'baseline_version'")
        return _apply_baseline(conn)
    finally:
        conn.close()
