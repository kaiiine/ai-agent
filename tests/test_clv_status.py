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

_KICKOFF = datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc)
_T = _KICKOFF - timedelta(hours=6)          # décision six heures avant, dans la policy


def _ev(sport, competition="tour"):
    """Identité RÉALISTE : elle porte le coup d'envoi, comme en production. Sans
    lui, toute observation est jugée non datable et n'entre dans aucune preuve."""
    return (f"event:{sport}:{competition}:{_KICKOFF:%Y-%m-%dT%H:%M:%S}Z"
            f":home=a|away=b")


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
    # La commande proposée est celle qui ne demande AUCUNE phase : c'est le choix
    # manuel de la phase qui avait produit 113 décisions et zéro clôture.
    assert "collect_cli" in texte
    assert "--phase" not in texte
    assert "coup d'envoi" in texte


def test_le_sport_est_lu_sur_l_identite_de_l_evenement():
    """L'identité d'événement porte déjà son sport ; le redemander ailleurs
    ouvrirait un second chemin de vérité."""
    lignes = collect([
        _obs(_ev("tennis"), ObservationPhase.DECISION, 2.0),
        _obs(_ev("hockey", "nhl"), ObservationPhase.DECISION, 1.8),
    ], min_events=30)

    assert {l["sport"] for l in lignes} == {"tennis", "hockey", "TOTAL"}


def test_des_decisions_sans_cloture_sont_nommees_comme_telles():
    """Le cas réel : 113 décisions collectées, zéro clôture. Dire seulement
    « non mesurable » enverrait relancer une collecte qui tourne déjà."""
    lignes = collect([_obs(_ev("tennis"), ObservationPhase.DECISION, 2.0)],
                     min_events=30)

    ligne = _ligne(lignes, "tennis")
    assert ligne["decisions"] == 1 and ligne["clotures"] == 0
    assert "aucune clôture" in ligne["manque"]


def test_une_paire_complete_affiche_le_reste_a_parcourir():
    lignes = collect([
        _obs(_ev("tennis"), ObservationPhase.DECISION, 2.0),
        _obs(_ev("tennis"), ObservationPhase.CLOSING, 1.8, decalage=350),
    ], min_events=30)

    ligne = _ligne(lignes, "tennis")
    assert ligne["paires"] == 1 and ligne["independants"] == 1
    assert "29" in ligne["manque"]          # 30 requis, 1 acquis


def test_plusieurs_selections_d_un_meme_match_ne_comptent_que_pour_une():
    """L'échantillon EFFECTIF est l'événement : home et away du même match bougent
    ensemble, les compter séparément gonflerait la progression affichée."""
    obs = []
    for selection in ("home", "away"):
        obs.append(_obs(_ev("football", "fra"), ObservationPhase.DECISION,
                        2.0, selection=selection))
        obs.append(_obs(_ev("football", "fra"), ObservationPhase.CLOSING,
                        1.8, decalage=350, selection=selection))

    ligne = _ligne(collect(obs, min_events=30), "football")

    assert ligne["paires"] == 2          # deux marchés appariés
    assert ligne["independants"] == 1    # une seule rencontre


def test_le_total_agrege_sans_masquer_les_sports():
    obs = [
        _obs(_ev("tennis"), ObservationPhase.DECISION, 2.0),
        _obs(_ev("hockey", "nhl"), ObservationPhase.DECISION, 1.8),
    ]
    lignes = collect(obs, min_events=30)

    assert _ligne(lignes, "TOTAL")["decisions"] == 2
    assert _ligne(lignes, "tennis")["decisions"] == 1


def test_le_rendu_signale_qu_aucune_cloture_n_a_jamais_ete_prise():
    """Le message qui compte : la collecte n'est pas cassée, elle est incomplète."""
    texte = "\n".join(render(
        collect([_obs(_ev("tennis"), ObservationPhase.DECISION, 2.0)],
                min_events=30),
        min_events=30))

    assert "Aucune clôture" in texte
    assert "AVANT le coup d'envoi" in texte


# ══ Vue opérationnelle : la CLV moyenne et le seuil requis ══════════════════
def test_la_vue_expose_la_clv_moyenne_et_le_seuil():
    """Suivre l'accumulation demande de voir où on en est ET où il faut aller."""
    lignes = collect([
        _obs(_ev("tennis"), ObservationPhase.DECISION, 2.0),
        _obs(_ev("tennis"), ObservationPhase.CLOSING, 1.8, decalage=350),
    ], min_events=30)

    ligne = _ligne(lignes, "tennis")
    assert ligne["requises"] == 30
    assert ligne["mean_clv"] is not None
    assert ligne["borne_basse"] is not None


def test_une_clv_absente_ne_s_ecrit_jamais_zero():
    """Écrire 0 ferait passer une absence de mesure pour une CLV nulle — et une
    CLV nulle est une information, pas un vide."""
    lignes = collect([_obs(_ev("tennis"), ObservationPhase.DECISION, 2.0)],
                     min_events=30)
    texte = "\n".join(render(lignes, min_events=30))

    assert _ligne(lignes, "tennis")["mean_clv"] is None
    assert "0.00 %" not in texte


def test_le_seuil_est_annonce_comme_versionne():
    """Un plancher de policy doit se lire comme tel, pas comme une vérité
    statistique — et son fichier doit être nommé."""
    texte = "\n".join(render(
        collect([_obs(_ev("tennis"), ObservationPhase.DECISION, 2.0)],
                min_events=30), min_events=30))

    assert "model_maturity_policy.json" in texte


def test_le_seuil_provient_reellement_de_la_policy_versionnee():
    """Il n'a pas été inventé pour ce lot : il vit dans un fichier versionné,
    avec sa justification et son checksum."""
    import json
    import pathlib

    fichier = (pathlib.Path(__file__).resolve().parent.parent
               / "configs" / "betting_engine" / "model_maturity_policy.json")
    policy = json.loads(fichier.read_text(encoding="utf-8"))

    assert policy["criteria"]["min_clv_events"] == 30
    assert "plancher conservateur" in policy["notes"]
