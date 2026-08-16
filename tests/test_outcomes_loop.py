"""La boucle de retour : ce que le modèle annonce, puis ce qui arrive vraiment.

Le moteur prédisait sans que rien ne lui revienne. `OddsObservation` enregistre le
mouvement de la cote, jamais l'issue ; l'audit archive la décision, jamais le
résultat ; aucun `settle` n'existait. La seule mesure de justesse venait d'un
walk-forward sur un CSV figé — elle dit comment le modèle se serait comporté sur
le passé, jamais comment il se comporte.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from src.agents.quant.betting_engine.outcomes import (
    Issue,
    JsonlPredictionStore,
    PredictionRecord,
    calibration_reelle,
)
from src.agents.quant.betting_engine.outcomes.calibration import N_MIN_LISIBLE, rendre_texte

KO = datetime(2026, 8, 12, 12, tzinfo=timezone.utc)
AVANT = KO - timedelta(hours=4)
APRES = KO + timedelta(hours=3)


def _record(**extra) -> PredictionRecord:
    base = dict(
        stable_event_id="event:tennis:atp:winamax#42", market_type="MATCH_WINNER",
        selection="player_a", participant_ids=("p:a", "p:b"),
        model_version="tennis.atp.elo.v0", fair_probability=Decimal("0.60"),
        bookmaker_odds=Decimal("1.8"), bookmaker="winamax",
        scheduled_at=KO, decided_at=AVANT)
    return PredictionRecord(**{**base, **extra})


# ── Invariants du record ─────────────────────────────────────────────────────

def test_une_prediction_posterieure_au_coup_d_envoi_est_refusee():
    """Ce ne serait plus une prédiction — et ça gonflerait la justesse mesurée."""
    with pytest.raises(ValueError, match="pas une prédiction"):
        _record(decided_at=APRES)


def test_un_horodatage_naif_est_refuse():
    with pytest.raises(ValueError, match="timezone-aware"):
        _record(decided_at=AVANT.replace(tzinfo=None))


def test_une_probabilite_flottante_est_refusee():
    """Même discipline que la frontière Advisor : jamais de float sur l'argent."""
    with pytest.raises(TypeError, match="Decimal"):
        _record(fair_probability=0.6)


def test_une_issue_ne_se_reecrit_pas():
    reglee = _record().regler(Issue.GAGNEE, at=APRES, source="test")

    with pytest.raises(ValueError, match="déjà réglée"):
        reglee.regler(Issue.PERDUE, at=APRES, source="test")


def test_un_reglement_anterieur_au_match_est_refuse():
    with pytest.raises(ValueError, match="antérieur au coup d'envoi"):
        _record().regler(Issue.GAGNEE, at=AVANT, source="test")


def test_regler_ne_mute_pas_l_original():
    """Le store est append-only : muter en place perdrait l'état antérieur."""
    origine = _record()

    origine.regler(Issue.GAGNEE, at=APRES, source="test")

    assert origine.issue is None


@pytest.mark.parametrize("issue,attendu", [
    (Issue.GAGNEE, Decimal("1")), (Issue.PERDUE, Decimal("0")), (Issue.ANNULEE, None)])
def test_le_realise_suit_l_issue(issue, attendu):
    assert _record().regler(issue, at=APRES, source="t").realise == attendu


def test_une_selection_annulee_ne_compte_pas_dans_la_calibration():
    """Un walkover n'a pas d'issue : le compter comme perdu fabriquerait de la
    surconfiance qui n'a jamais eu lieu."""
    annulee = _record().regler(Issue.ANNULEE, at=APRES, source="t")

    assert annulee.est_reglee
    assert not annulee.compte_pour_la_calibration


# ── Store ────────────────────────────────────────────────────────────────────

@pytest.fixture
def store(tmp_path):
    return JsonlPredictionStore(tmp_path / "p.jsonl")


def test_le_store_relit_ce_qu_il_ecrit(store):
    store.append(_record())

    relu = store.all()[0]

    assert relu.fair_probability == Decimal("0.60")
    assert relu.bookmaker_odds == Decimal("1.8")
    assert relu.scheduled_at == KO


def test_regler_ecrit_une_ligne_de_plus_sans_effacer(store):
    """Append-only jusqu'au règlement : l'historique reste lisible."""
    store.append(_record())
    store.append(store.all()[0].regler(Issue.GAGNEE, at=APRES, source="t"))

    assert len(list(store.iter_raw())) == 2
    assert len(store.all()) == 1, "l'état courant garde une seule entrée par clé"
    assert store.all()[0].issue is Issue.GAGNEE


def test_une_prediction_reglee_n_est_comptee_qu_une_fois(store):
    """Sans réduction par clé, la calibration verrait deux fois la même
    prédiction — une non réglée, une réglée."""
    store.append(_record())
    store.append(store.all()[0].regler(Issue.GAGNEE, at=APRES, source="t"))

    assert calibration_reelle(store.all()).n_reglees == 1


def test_le_chemin_home_axon_est_refuse(tmp_path):
    with pytest.raises(ValueError, match="interdit"):
        JsonlPredictionStore("~/.axon/predictions.jsonl")


def test_un_store_absent_ne_leve_pas(tmp_path):
    assert JsonlPredictionStore(tmp_path / "jamais-ecrit.jsonl").all() == []


# ── Calibration ──────────────────────────────────────────────────────────────

def _regle(p: str, issue: Issue, i: int = 0) -> PredictionRecord:
    return _record(fair_probability=Decimal(p),
                   stable_event_id=f"e{i}").regler(issue, at=APRES, source="t")


def test_sans_prediction_reglee_rien_n_est_fabrique():
    """Un Brier de 0 serait un score PARFAIT — le pire mensonge possible ici."""
    c = calibration_reelle([_record()])

    assert c.n_reglees == 0
    assert c.brier is None and c.ece is None and c.taux_reussite is None


def test_un_modele_parfait_a_un_brier_nul():
    records = [_regle("1.0", Issue.GAGNEE, 1), _regle("0.0", Issue.PERDUE, 2)]

    assert calibration_reelle(records).brier == Decimal("0")


def test_la_surconfiance_est_detectee():
    """Annoncer 90 % et sortir une fois sur deux, c'est +40 pts de biais."""
    records = [_regle("0.9", Issue.GAGNEE, 1), _regle("0.9", Issue.PERDUE, 2)]

    c = calibration_reelle(records)

    assert c.probabilite_moyenne == Decimal("0.9")
    assert c.taux_reussite == Decimal("0.5")
    assert c.biais == Decimal("0.4")


def test_les_annulees_sont_comptees_a_part():
    records = [_regle("0.6", Issue.GAGNEE, 1), _regle("0.6", Issue.ANNULEE, 2)]

    c = calibration_reelle(records)

    assert c.n_reglees == 1 and c.n_annulees == 1


def test_un_echantillon_trop_petit_est_annonce_comme_tel():
    c = calibration_reelle([_regle("0.6", Issue.GAGNEE, 1)])

    assert not c.lisible
    assert any("bruit" in l for l in rendre_texte(c))


def test_un_echantillon_suffisant_ne_porte_pas_l_avertissement():
    records = [_regle("0.6", Issue.GAGNEE, i) for i in range(N_MIN_LISIBLE)]

    assert calibration_reelle(records).lisible
    assert not any("bruit" in l for l in rendre_texte(calibration_reelle(records)))


def test_le_filtre_par_version_isole_les_modeles():
    """ATP et WTA sont deux modèles : les mélanger masquerait celui qui dérive."""
    records = [_regle("0.6", Issue.GAGNEE, 1),
               _record(fair_probability=Decimal("0.6"), stable_event_id="e2",
                       model_version="tennis.wta.elo.v0").regler(
                           Issue.PERDUE, at=APRES, source="t")]

    assert calibration_reelle(records, model_version="tennis.atp.elo.v0").n_reglees == 1


def test_les_tranches_couvrent_toutes_les_predictions():
    records = [_regle(p, Issue.GAGNEE, i)
               for i, p in enumerate(["0.05", "0.35", "0.55", "0.75", "0.95", "1.0"])]

    c = calibration_reelle(records)

    assert sum(t.n for t in c.tranches) == c.n_reglees, "une probabilité perdue en route"


# ── Règlement depuis le jeu de données réel ─────────────────────────────────

@pytest.fixture(scope="module")
def vrais_matchs():
    from src.agents.quant.betting_engine.sports.tennis.identity import tennis_players
    from src.agents.quant.betting_engine.sports.tennis.tennis_data_loader import (
        load_tennis_data,
    )

    _e, dataset_of = tennis_players("atp")
    inverse = {v: k for k, v in dataset_of.items()}
    matchs = [m for m in load_tennis_data("atp").matches[-3000:]
              if m.p1_name in inverse and m.p2_name in inverse]
    if len(matchs) < 5:
        pytest.skip("jeu de données tennis indisponible")
    return matchs[:5], inverse


def _prediction_sur(match, inverse, *, sur_le_vainqueur: bool, i: int = 0):
    ids = ((inverse[match.p1_name], inverse[match.p2_name]) if sur_le_vainqueur
           else (inverse[match.p2_name], inverse[match.p1_name]))
    ko = datetime(match.tourney_date.year, match.tourney_date.month,
                  match.tourney_date.day, 12, tzinfo=timezone.utc)
    return _record(stable_event_id=f"e{i}", participant_ids=ids,
                   scheduled_at=ko, decided_at=ko - timedelta(hours=2))


def test_une_selection_sur_le_vainqueur_est_reglee_gagnee(vrais_matchs):
    from src.agents.quant.betting_engine.outcomes import regler_tennis

    matchs, inverse = vrais_matchs
    predictions = [_prediction_sur(m, inverse, sur_le_vainqueur=True, i=i)
                   for i, m in enumerate(matchs)]

    reglement = regler_tennis(predictions, "atp")

    assert len(reglement.reglees) == len(matchs)
    assert all(r.issue is Issue.GAGNEE for r in reglement.reglees)


def test_une_selection_sur_le_perdant_est_reglee_perdue(vrais_matchs):
    """Référence NÉGATIVE : sans elle, un règlement qui rendrait toujours GAGNEE
    passerait le test précédent."""
    from src.agents.quant.betting_engine.outcomes import regler_tennis

    matchs, inverse = vrais_matchs
    predictions = [_prediction_sur(m, inverse, sur_le_vainqueur=False, i=i)
                   for i, m in enumerate(matchs)]

    reglement = regler_tennis(predictions, "atp")

    assert all(r.issue is Issue.PERDUE for r in reglement.reglees)


def test_le_reglement_est_idempotent(vrais_matchs):
    from src.agents.quant.betting_engine.outcomes import regler_tennis

    matchs, inverse = vrais_matchs
    reglees = regler_tennis(
        [_prediction_sur(matchs[0], inverse, sur_le_vainqueur=True)], "atp").reglees

    assert regler_tennis(reglees, "atp").reglees == ()


def test_un_match_non_encore_joue_reste_en_attente(vrais_matchs):
    """Le déclarer introuvable le sortirait de la file pour toujours — alors qu'il
    se réglera tout seul au prochain rafraîchissement du jeu de données.
    De VRAIS joueurs : avec des identités fictives, c'est le contrôle de périmètre
    qui répondrait, et la logique de date ne serait jamais exercée."""
    from src.agents.quant.betting_engine.outcomes import RaisonNonReglee, regler_tennis

    matchs, inverse = vrais_matchs
    futur = datetime(2027, 6, 1, 12, tzinfo=timezone.utc)
    prediction = _prediction_sur(matchs[0], inverse, sur_le_vainqueur=True)
    prediction = _record(stable_event_id="futur",
                         participant_ids=prediction.participant_ids,
                         scheduled_at=futur, decided_at=futur - timedelta(hours=1))

    _, raison = regler_tennis([prediction], "atp").non_reglees[0]

    assert raison is RaisonNonReglee.PAS_ENCORE_JOUE


# ── Capture au scan — sans elle, la boucle n'est jamais alimentée ───────────

class _Cand:
    event_id = "event:tennis:wta:2026-08-12T12:00:00Z:a"
    market_id = "m1"
    market_type = "MATCH_WINNER"
    selection = "player_b"
    bookmaker = "winamax"
    competition_id = "competition:tennis:wta:tour"
    model_version = "tennis.wta.elo.v0"
    fair_probability = Decimal("0.5895")
    bookmaker_odds = Decimal("1.9")
    participant_ids = ("p:osaka", "p:rybakina")
    scheduled_at = KO


class _Eval:
    def __init__(self, candidat=None):
        self.candidate = candidat or _Cand()


def test_la_capture_ecrit_une_prediction_par_candidat(store):
    from src.agents.quant.betting_engine.outcomes.capture import capturer_predictions

    assert capturer_predictions([_Eval(), _Eval()], decided_at=AVANT, store=store) == 2


def test_un_candidat_bancal_n_interrompt_pas_la_capture(store):
    """Une comptabilité ne doit jamais casser un scan : le candidat fautif est
    sauté, les autres passent."""
    from src.agents.quant.betting_engine.outcomes.capture import capturer_predictions

    class _Apres(_Cand):
        scheduled_at = AVANT - timedelta(days=5)     # décision après le match

    ecrites = capturer_predictions([_Eval(_Apres()), _Eval()],
                                   decided_at=AVANT, store=store)

    assert ecrites == 1


def test_la_capture_conserve_la_probabilite_exacte(store):
    """Un arrondi ici fausserait tout Brier calculé plus tard."""
    from src.agents.quant.betting_engine.outcomes.capture import capturer_predictions

    capturer_predictions([_Eval()], decided_at=AVANT, store=store)

    assert store.all()[0].fair_probability == Decimal("0.5895")


def test_la_capture_est_branchee_dans_le_scan():
    """Le store peut exister et rester vide pour toujours si rien ne l'alimente."""
    import inspect

    from src.agents.quant.conversation import recommend

    source = inspect.getsource(recommend.run_recommendation)
    appel = source.index("capture(result.trace.policy_evaluations")

    assert "policy_evaluations" in source[appel:][:400], (
        "l'échantillon doit être TOUS les candidats évalués, pas les seuls affichés")
    assert "noqa: BLE001" in source[appel:][:600], (
        "un échec de comptabilité ne doit jamais casser un scan")
    assert "capturer_predictions" in inspect.getsource(recommend._default_capture)


def test_des_participants_inconnus_ne_sont_jamais_devines():
    from src.agents.quant.betting_engine.outcomes import RaisonNonReglee, regler_tennis

    prediction = _record(participant_ids=("inconnu:1", "inconnu:2"),
                         scheduled_at=datetime(2026, 1, 15, 12, tzinfo=timezone.utc),
                         decided_at=datetime(2026, 1, 15, 8, tzinfo=timezone.utc))

    _, raison = regler_tennis([prediction], "atp").non_reglees[0]

    assert raison is RaisonNonReglee.HORS_PERIMETRE


def test_la_capture_est_injectee_donc_neutralisable(monkeypatch):
    """Appelée en dur, elle écrivait dans le store RÉEL depuis la suite de tests :
    515 prédictions synthétiques y ont atterri avant que ça se voie. Injectée
    comme `persist_audit`, un test la neutralise avec `capture=None`."""
    import inspect

    from src.agents.quant.conversation import recommend

    signature = inspect.signature(recommend.run_recommendation)

    assert "capture" in signature.parameters
    assert signature.parameters["capture"].default is recommend._default_capture
    assert "if capture is not None" in inspect.getsource(recommend.run_recommendation)


def test_aucun_test_n_ecrit_dans_le_store_de_production():
    """Tout appel à `run_recommendation` dans les tests doit passer capture=None."""
    import pathlib
    import re

    fautifs = []
    for fichier in sorted(pathlib.Path("tests").glob("*.py")):
        texte = fichier.read_text(encoding="utf-8")
        for appel in re.finditer(r"run_recommendation\((?:[^()]|\([^()]*\))*\)", texte):
            if any(n not in appel.group() for n in ("capture=None", "coverage=None")):
                fautifs.append(f"{fichier.name}: {appel.group()[:70]}")

    assert not fautifs, "écrit dans var/betting_engine/predictions.jsonl :\n" + "\n".join(fautifs)
