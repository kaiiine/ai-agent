"""`axon clv-status` — l'avancement de la collecte, lisible sans ouvrir le code.

La CLV est le dernier bloqueur commun aux quatorze modèles, et le seul que rien
d'autre que le temps ne lève. Son avancement n'était visible nulle part : le
rapport de maturité dit « NOT_YET_MEASURABLE » sans distinguer « aucune décision
capturée » de « des décisions mais aucune clôture ». Les deux se corrigent
différemment — l'une en lançant la collecte, l'autre en la lançant plus tôt.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from src.agents.quant.betting_engine.clv.observation import (
    ObservationPhase,
    OddsObservation,
)
from src.agents.quant.betting_engine.clv.status_cli import collect, render

_T = datetime(2026, 3, 1, 10, 0, tzinfo=timezone.utc)


def _obs(event_id, phase, cote, *, decalage=0, selection="home"):
    return OddsObservation(
        event_id=event_id, market_type="MATCH_WINNER", selection=selection,
        bookmaker="winamax", decimal_odds=Decimal(str(cote)),
        observed_at=_T + timedelta(minutes=decalage), phase=phase,
        source="synthetic", source_event_id="x", run_id=None)


def _ligne(lignes, sport):
    return next(l for l in lignes if l["sport"] == sport)


def test_un_historique_vide_dit_comment_commencer():
    lignes = collect([], min_events=30)
    texte = "\n".join(render(lignes, min_events=30))

    assert lignes == []
    assert "vide" in texte
    # Les DEUX phases sont nommées : capturer des décisions sans jamais capturer
    # de clôture est exactement l'état dans lequel le produit se trouvait.
    assert "decision" in texte and "closing" in texte


def test_le_sport_est_lu_sur_l_identite_de_l_evenement():
    """L'identité d'événement porte déjà son sport ; le redemander ailleurs
    ouvrirait un second chemin de vérité."""
    lignes = collect([
        _obs("event:tennis:tour:2026:a", ObservationPhase.DECISION, 2.0),
        _obs("event:hockey:nhl:2026:b", ObservationPhase.DECISION, 1.8),
    ], min_events=30)

    assert {l["sport"] for l in lignes} == {"tennis", "hockey", "TOTAL"}


def test_des_decisions_sans_cloture_sont_nommees_comme_telles():
    """Le cas réel : 113 décisions collectées, zéro clôture. Dire seulement
    « non mesurable » enverrait relancer une collecte qui tourne déjà."""
    lignes = collect([_obs("event:tennis:tour:2026:a", ObservationPhase.DECISION, 2.0)],
                     min_events=30)

    ligne = _ligne(lignes, "tennis")
    assert ligne["decisions"] == 1 and ligne["clotures"] == 0
    assert "aucune clôture" in ligne["manque"]


def test_une_paire_complete_affiche_le_reste_a_parcourir():
    lignes = collect([
        _obs("event:tennis:tour:2026:a", ObservationPhase.DECISION, 2.0),
        _obs("event:tennis:tour:2026:a", ObservationPhase.CLOSING, 1.8, decalage=60),
    ], min_events=30)

    ligne = _ligne(lignes, "tennis")
    assert ligne["paires"] == 1 and ligne["independants"] == 1
    assert "29" in ligne["manque"]          # 30 requis, 1 acquis


def test_plusieurs_selections_d_un_meme_match_ne_comptent_que_pour_une():
    """L'échantillon EFFECTIF est l'événement : home et away du même match bougent
    ensemble, les compter séparément gonflerait la progression affichée."""
    obs = []
    for selection in ("home", "away"):
        obs.append(_obs("event:football:fra:2026:a", ObservationPhase.DECISION,
                        2.0, selection=selection))
        obs.append(_obs("event:football:fra:2026:a", ObservationPhase.CLOSING,
                        1.8, decalage=60, selection=selection))

    ligne = _ligne(collect(obs, min_events=30), "football")

    assert ligne["paires"] == 2          # deux marchés appariés
    assert ligne["independants"] == 1    # une seule rencontre


def test_le_total_agrege_sans_masquer_les_sports():
    obs = [
        _obs("event:tennis:tour:2026:a", ObservationPhase.DECISION, 2.0),
        _obs("event:hockey:nhl:2026:b", ObservationPhase.DECISION, 1.8),
    ]
    lignes = collect(obs, min_events=30)

    assert _ligne(lignes, "TOTAL")["decisions"] == 2
    assert _ligne(lignes, "tennis")["decisions"] == 1


def test_le_rendu_signale_qu_aucune_cloture_n_a_jamais_ete_prise():
    """Le message qui compte : la collecte n'est pas cassée, elle est incomplète."""
    texte = "\n".join(render(
        collect([_obs("event:tennis:tour:2026:a", ObservationPhase.DECISION, 2.0)],
                min_events=30),
        min_events=30))

    assert "Aucune clôture" in texte
    assert "AVANT le coup d'envoi" in texte
