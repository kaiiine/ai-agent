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

COVERAGE_DB = Path.home() / ".axon" / "sports_provider_coverage.db"

_VERIFICATION_METHODS = {"live_call", "provider_docs", "manual"}


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
    return conn


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


def known_coverage() -> list[ProviderCompetitionCoverage]:
    """Baseline de couverture — reflète des vérifications live_call réelles (voir
    coverage_verification pour re-vérifier). Honnête sur ce qui N'A PAS été
    vérifié : ces combos restent UNVERIFIED, donc inutilisables."""
    verified = datetime(2026, 7, 25, tzinfo=timezone.utc)
    verified_0805 = datetime(2026, 8, 5, tzinfo=timezone.utc)
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
    # PL matchs 2025 : non vérifiés en direct -> UNVERIFIED (jamais servis tant que non vérifiés)
    add("football_data_org", _PL, "PL", "2025", ["FIXTURES", "RESULTS"], CoverageStatus.UNVERIFIED, "manual")

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

    # API-Sports — tier gratuit : 2022-2024 servies, 2025+ refusée (bug fondateur)
    add("api_sports", _L1, "61", "2024", ["FIXTURES", "RESULTS", "STANDINGS"], CoverageStatus.FULL, "live_call")
    add("api_sports", _L1, "61", "2025", ["FIXTURES", "RESULTS", "STANDINGS"],
        CoverageStatus.ABSENT, "live_call", notes="tier gratuit bloque 2025+")

    return entries


def seed(db_path: Path | None = None) -> int:
    """Matérialise la baseline known_coverage() dans le stockage SQLite. Idempotent."""
    entries = known_coverage()
    for entry in entries:
        record_coverage(entry, db_path)
    return len(entries)
