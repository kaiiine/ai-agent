"""Couverture produit : ce qui n'a pas été mesuré ne vaut pas zéro.

« Tous sports, toutes compétitions » voulait dire « les compétitions codées au
départ », et rien ne mesurait l'écart. Le piège de cette mesure-là est qu'un sport
non atteint par le scan et un sport sans aucune rencontre évaluable produisent le
même `0` — l'un est un trou d'instrumentation, l'autre un trou de modèle, et ils
se réparent à des endroits différents.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.agents.quant.betting_engine.catalog_coverage import (
    JsonlCoverageStore,
    mesurer,
    rendre_texte,
)
from src.agents.quant.conversation.observability import (
    EventTrace,
    RunObservability,
    ScanTelemetry,
)

KO = datetime(2026, 8, 13, 19, tzinfo=timezone.utc)


def _trace(sport="football", status="EVALUATED", competition_id="competition:football:fra:ligue1",
           event_id="e1", selections=2):
    return EventTrace(bookmaker_event_id="w1", sport=sport, competition_label="L1",
                      kickoff=KO, status=status, reason="", event_id=event_id,
                      competition_id=competition_id, selections=selections)


def _obs(traces, vus=None):
    return RunObservability(
        telemetry=ScanTelemetry(events_seen_by_sport=vus or {}),
        traces=tuple(traces), model_capable_sports=("football",))


# ── NOT_MEASURED ≠ 0 ────────────────────────────────────────────────────────

def test_un_sport_sans_compte_catalogue_n_affiche_pas_zero():
    """Le scan n'a rien rapporté pour ce sport : dire « 0 au catalogue » serait
    affirmer que le bookmaker n'en propose aucun."""
    c = mesurer(_obs([_trace()]))

    assert c.par_sport[0].catalog_events_seen is not None   # replié sur les traces
    assert mesurer(_obs([])).total_catalog_events is None


def test_un_ratio_sans_denominateur_vaut_none_pas_zero():
    sport = mesurer(_obs([])).par_sport
    assert sport == ()
    vide = mesurer(_obs([], vus={}))

    assert vide.global_coverage is None
    assert vide.total_catalog_events is None


def test_un_catalogue_inatteignable_est_dit_et_ne_publie_aucun_pourcentage():
    texte = "\n".join(rendre_texte(mesurer(_obs([]))))

    assert "NOT_MEASURED" in texte
    assert "%" not in texte, "un pourcentage extrapolé sur un catalogue non lu"


def test_zero_evaluable_sur_un_catalogue_mesure_reste_un_vrai_zero():
    """L'inverse doit rester lisible : catalogue vu, rien d'évaluable."""
    c = mesurer(_obs([_trace(status="COMPETITION_NOT_RESOLVED", competition_id=None)],
                     vus={"football": 52}))

    assert c.par_sport[0].catalog_events_seen == 52
    assert c.par_sport[0].evaluated == 0
    assert c.global_coverage == 0.0, "0 mesuré doit rester 0, pas None"


# ── Le dénominateur est le CATALOGUE, pas les survivants ────────────────────

def test_le_taux_se_calcule_sur_le_catalogue_pas_sur_les_evalues():
    """Prendre les traces comme dénominateur exclurait précisément ce qu'on
    cherche à mesurer — un taux flatteur par construction."""
    c = mesurer(_obs([_trace(event_id="e1"), _trace(event_id="e2")],
                     vus={"football": 10}))

    assert c.par_sport[0].evaluation_rate == 0.2   # 2 / 10, jamais 2 / 2


def test_les_compteurs_distinguent_les_couches_de_blocage():
    traces = [_trace(status="COMPETITION_NOT_RESOLVED", competition_id=None, event_id=None),
              _trace(status="SPORT_NOT_SUPPORTED", event_id="e2"),
              _trace(event_id="e3")]

    s = mesurer(_obs(traces, vus={"football": 3})).par_sport[0]

    assert s.competition_unresolved == 1
    assert s.evaluated == 1
    assert s.unsupported == 2
    assert s.blockers == {"COMPETITION_NOT_RESOLVED": 1, "SPORT_NOT_SUPPORTED": 1}


def test_chaque_sport_est_compte_separement():
    c = mesurer(_obs([_trace(sport="football"), _trace(sport="tennis", event_id="e2")],
                     vus={"football": 5, "tennis": 3}))

    assert [s.sport for s in c.par_sport] == ["football", "tennis"]
    assert c.total_catalog_events == 8


# ── Persistance ─────────────────────────────────────────────────────────────

def test_la_mesure_se_relit_apres_ecriture(tmp_path):
    store = JsonlCoverageStore(tmp_path / "c.jsonl")
    store.append(mesurer(_obs([_trace()], vus={"football": 4})))

    relu = store.derniere()

    assert relu["sports"][0]["catalog_events_seen"] == 4
    assert relu["total_evaluated"] == 1


def test_une_mesure_non_faite_reste_null_en_json(tmp_path):
    """`None` doit survivre à la sérialisation : un 0 en base serait indiscernable
    d'une couverture nulle réellement observée."""
    store = JsonlCoverageStore(tmp_path / "c.jsonl")
    store.append(mesurer(_obs([])))

    assert store.derniere()["total_catalog_events"] is None
    assert store.derniere()["global_coverage"] is None


def test_le_chemin_home_axon_est_refuse():
    with pytest.raises(ValueError, match="interdit"):
        JsonlCoverageStore("~/.axon/coverage.jsonl")


# ── Branchement dans le vrai chemin de scan ─────────────────────────────────

def test_la_mesure_est_branchee_dans_le_scan_et_neutralisable():
    """Elle doit produire les métriques dès qu'un run réel atteint le catalogue,
    sans qu'on ait à la déclencher à la main — et sans polluer depuis les tests."""
    import inspect

    from src.agents.quant.conversation import recommend

    signature = inspect.signature(recommend.run_recommendation)
    source = inspect.getsource(recommend.run_recommendation)

    assert signature.parameters["coverage"].default is recommend._default_coverage
    assert "if coverage is not None" in source


def test_le_scan_compte_les_rencontres_par_sport():
    """Sans ce compte, le dénominateur de la couverture n'existe pas."""
    import inspect

    from src.agents.quant.conversation import recommend

    source = inspect.getsource(recommend._default_scan)

    assert "vus_par_sport" in source
    assert "events_seen_by_sport=" in source
