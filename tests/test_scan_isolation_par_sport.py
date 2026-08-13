"""UNIVERSAL MARKET ENGINE — un STOP reste local à la branche qui le provoque.

Le scan multisport lançait sept appels réseau indépendants et propageait la
première erreur : une coupure sur le tennis rendait `DATA_UNAVAILABLE` pour le
football, le basket et les cinq autres. Sept branches indépendantes s'arrêtaient
pour une panne qui n'en concernait qu'une.

L'inverse — avaler l'erreur — serait pire : un sport injoignable se lirait
« aucune opportunité aujourd'hui ». La panne devient donc une DONNÉE typée,
portée par le scan puis par la télémétrie, et lisible dans le rendu.

Reste inchangé : si AUCUN sport ne répond, il n'y a pas de scan partiel, il n'y a
pas de scan — le run échoue comme avant.
"""

from __future__ import annotations

import pytest

from src.agents.quant.betting_engine.bookmakers.winamax.catalogue import (
    multisport_events,
    multisport_scan,
)


class _Event:
    def __init__(self, sport: str, ident: str):
        self.sport = sport
        self.bookmaker_event_id = ident


class _Connector:
    """Scanne certains sports, tombe sur d'autres — comme une source réelle."""

    def __init__(self, par_sport: dict[str, object]):
        self._par_sport = par_sport
        self.appels: list[str] = []

    def scan_catalog(self, sport: str):
        self.appels.append(sport)
        valeur = self._par_sport[sport]
        if isinstance(valeur, Exception):
            raise valeur
        return valeur


def test_une_panne_n_arrete_pas_les_autres_sports():
    connector = _Connector({
        "football": [_Event("football", "f1"), _Event("football", "f2")],
        "tennis": ConnectionError("winamax injoignable"),
        "basketball": [_Event("basketball", "b1")],
    })

    scan = multisport_scan(connector, ["football", "tennis", "basketball"])

    assert [e.bookmaker_event_id for e in scan.events] == ["f1", "f2", "b1"]
    assert scan.scanned == ("football", "basketball")
    assert set(scan.failures) == {"tennis"}
    assert "winamax injoignable" in scan.failures["tennis"]
    assert not scan.total_failure


def test_la_panne_n_est_jamais_avalee():
    """Un sport en panne ne doit JAMAIS ressembler à un sport sans événement."""
    connector = _Connector({"tennis": TimeoutError("délai dépassé"),
                            "football": []})

    scan = multisport_scan(connector, ["tennis", "football"])

    assert scan.events == ()
    assert "tennis" in scan.failures          # panne
    assert "football" in scan.scanned         # vide, mais interrogé
    assert "football" not in scan.failures


def test_aucun_sport_joignable_reste_un_echec_total():
    connector = _Connector({"tennis": ConnectionError("ko"),
                            "football": ConnectionError("ko")})

    scan = multisport_scan(connector, ["tennis", "football"])

    assert scan.total_failure, "sans aucune source, il n'y a pas de scan partiel"
    assert scan.scanned == ()


def test_l_ordre_reste_celui_des_sports_demandes():
    """Deux runs identiques doivent produire le même catalogue, dans le même ordre —
    les scans partent pourtant de front."""
    connector = _Connector({
        "football": [_Event("football", "f1")],
        "tennis": [_Event("tennis", "t1")],
        "basketball": [_Event("basketball", "b1")],
        "hockey": [_Event("hockey", "h1")],
    })
    demande = ["hockey", "football", "basketball", "tennis"]

    ids = [e.bookmaker_event_id for e in multisport_scan(connector, demande).events]
    assert ids == ["h1", "f1", "b1", "t1"]


def test_la_variante_stricte_propage_l_exception_d_origine():
    """`multisport_events` garde son contrat tout-ou-rien — et son TYPE d'erreur.

    La collecte CLV attrape `ConnectionError` pour séparer une coupure réseau
    d'une panne de programme. Enveloppée dans un `RuntimeError`, sa propre panne
    lui passait sous le nez.
    """
    connector = _Connector({"tennis": ConnectionError("ko"), "football": []})

    with pytest.raises(ConnectionError, match="ko"):
        multisport_events(connector, ["tennis", "football"])


# ── La panne remonte jusqu'au rendu ───────────────────────────────────────────

def test_la_telemetrie_distingue_demande_et_interroge():
    from src.agents.quant.conversation.observability import ScanTelemetry

    tel = ScanTelemetry(
        scanned_sports=("football", "tennis", "basketball"),
        scan_failures={"tennis": "ConnectionError: ko"})

    assert tel.sports_effectivement_scannes == ("football", "basketball")


def test_le_rendu_nomme_les_sports_non_interroges():
    """Muette, une branche absente se lit « aucune opportunité »."""
    from src.agents.quant.conversation.observability import ScanTelemetry
    from src.agents.quant.conversation.renderer import _render_couverture

    class _Obs:
        telemetry = ScanTelemetry(
            scanned_sports=("football", "tennis"),
            scan_failures={"tennis": "ConnectionError: winamax injoignable"})
        model_capable_sports = ("football", "tennis")
        sports_in_window = ("football",)
        sports_evaluated = ("football",)
        competitions_in_window: dict = {}
        competitions_resolved: tuple = ()
        competitions_evaluated: tuple = ()

    texte = "\n".join(_render_couverture(_Obs(), evidence=None))

    assert "Sports scannés dans ce run : **1**" in texte     # 2 demandés, 1 interrogé
    assert "tennis" in texte and "panne de source" in texte
    assert "aucune opportunité" in texte                      # la phrase qui désamorce
