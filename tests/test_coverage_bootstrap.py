"""Bootstrap de la baseline de couverture.

La panne évitée est silencieuse : sur une installation neuve, la base était vide
et `usable_providers` renvoyait `[]`. Le moteur répondait donc
PROVIDER_COVERAGE_MISSING sur des compétitions pourtant déclarées ET vérifiées,
sans que rien ne signale qu'une commande d'initialisation manquait. Un seed
manuel qu'on peut oublier n'est pas une garantie.

Le bootstrap vit au PREMIER ACCÈS, jamais à l'import — un import ne doit rien
écrire sur le disque.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.agents.quant.gateway.registries import provider_coverage_registry as pcr

L1 = "competition:football:fra:ligue1"
SERIE_A = "competition:football:ita:serie_a"


@pytest.fixture
def db(tmp_path):
    """Chemin NEUF : jamais ~/.axon, qui est la base de production de l'utilisateur."""
    return tmp_path / "coverage.db"


def _rows(db):
    conn = sqlite3.connect(db)
    try:
        return conn.execute("SELECT COUNT(*) FROM coverage").fetchone()[0]
    finally:
        conn.close()


def _version(db):
    conn = sqlite3.connect(db)
    try:
        row = conn.execute(
            "SELECT value FROM registry_meta WHERE key='baseline_version'").fetchone()
        return int(row[0]) if row else None
    finally:
        conn.close()


# ── base vide ───────────────────────────────────────────────────────────────────
def test_base_vide_est_amorcee_au_premier_acces(db):
    assert not db.exists()

    providers = pcr.usable_providers(SERIE_A, "2026", "RESULTS", db)

    assert providers == ["football_data_org"], "une base neuve doit servir la baseline"
    assert _rows(db) == len(pcr.known_coverage())
    assert _version(db) == pcr.BASELINE_VERSION


def test_l_import_seul_n_ecrit_rien(tmp_path):
    """Un import qui écrit rend le comportement dépendant de l'ordre des imports et
    pose une I/O disque sur le simple chargement du module.

    Vérifié dans un PROCESSUS NEUF : recharger le module en place recréerait ses
    enums, et les comparaisons d'identité des autres modules cesseraient de
    matcher — le test polluerait la suite au lieu de la protéger.
    """
    import subprocess
    import sys

    cible = tmp_path / "jamais_creee.db"
    code = (
        "from pathlib import Path\n"
        "import src.agents.quant.gateway.registries.provider_coverage_registry as pcr\n"
        f"pcr.COVERAGE_DB = Path({str(cible)!r})\n"
        f"print(Path({str(cible)!r}).exists())\n"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         cwd=str(Path(__file__).resolve().parents[1]))

    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "False"
    assert not cible.exists()


# ── base déjà amorcée ───────────────────────────────────────────────────────────
def test_seconde_ouverture_ne_reecrit_pas(db):
    pcr.usable_providers(L1, "2026", "RESULTS", db)
    apres_premier = _rows(db)

    for _ in range(3):
        pcr.usable_providers(L1, "2026", "RESULTS", db)

    assert _rows(db) == apres_premier, "le bootstrap doit être idempotent"


def test_une_entree_hors_baseline_survit_au_bootstrap(db):
    """Additif, jamais destructif : ce qui a été enregistré ailleurs reste."""
    pcr.usable_providers(L1, "2026", "RESULTS", db)
    perso = pcr.ProviderCompetitionCoverage(
        provider="provider_maison", competition_id="competition:football:zzz:test",
        provider_competition_id="X", season="2026", data_type="RESULTS",
        status=pcr.CoverageStatus.FULL, verified_at=datetime.now(timezone.utc),
        verification_method="manual",
    )
    pcr.record_coverage(perso, db)

    pcr.seed(db)          # ré-application complète de la baseline

    assert pcr.usable_providers("competition:football:zzz:test", "2026", "RESULTS", db) \
        == ["provider_maison"]


# ── montée de version ───────────────────────────────────────────────────────────
def test_une_nouvelle_version_est_reappliquee(db, monkeypatch):
    """Sans versionnage, une correction de couverture ne serait jamais reprise sur
    les installations déjà initialisées."""
    pcr.usable_providers(L1, "2026", "RESULTS", db)
    assert not pcr.usable_providers("competition:football:zzz:nouvelle", "2026", "RESULTS", db)

    ajout = pcr.ProviderCompetitionCoverage(
        provider="football_data_org", competition_id="competition:football:zzz:nouvelle",
        provider_competition_id="NEW", season="2026", data_type="RESULTS",
        status=pcr.CoverageStatus.FULL, verified_at=datetime.now(timezone.utc),
        verification_method="live_call",
    )
    baseline_v3 = pcr.known_coverage() + [ajout]
    monkeypatch.setattr(pcr, "known_coverage", lambda: baseline_v3)
    monkeypatch.setattr(pcr, "BASELINE_VERSION", pcr.BASELINE_VERSION + 1)

    assert pcr.usable_providers("competition:football:zzz:nouvelle", "2026", "RESULTS", db) \
        == ["football_data_org"]
    assert _version(db) == pcr.BASELINE_VERSION


def test_une_version_identique_ne_declenche_rien(db):
    pcr.usable_providers(L1, "2026", "RESULTS", db)
    v = _version(db)
    n = _rows(db)

    pcr.usable_providers(L1, "2026", "RESULTS", db)

    assert (_version(db), _rows(db)) == (v, n)


# ── ce qui n'est pas déclaré reste absent ───────────────────────────────────────
@pytest.mark.parametrize("competition", [
    "competition:football:eur:champions_league",
    "competition:football:eur:europa_league",
    "competition:football:eur:conference_league",
    "competition:football:cze:chance_liga",
])
def test_une_couverture_non_declaree_reste_absente(db, competition):
    """Le bootstrap ne doit RIEN inventer : il matérialise la baseline vérifiée et
    s'arrête là. Déclarer une couverture qu'on n'a pas appelée ferait échouer
    l'évaluation plus loin, en désignant le mauvais maillon."""
    pcr.usable_providers(L1, "2026", "RESULTS", db)       # amorce

    assert pcr.usable_providers(competition, "2026", "RESULTS", db) == []


def test_les_statuts_non_utilisables_ne_sont_pas_servis(db):
    """UNVERIFIED et ABSENT sont stockés — ils tracent ce qui a été constaté — mais
    ne sont jamais servis en production (GW-FR-005)."""
    pcr.usable_providers(L1, "2026", "RESULTS", db)

    non_utilisables = [e for e in pcr.known_coverage()
                       if e.status not in pcr.USABLE_STATUSES]
    assert non_utilisables, "la baseline doit tracer aussi ce qui n'est PAS couvert"
    for e in non_utilisables:
        assert e.provider not in pcr.usable_providers(
            e.competition_id, e.season, e.data_type, db)
