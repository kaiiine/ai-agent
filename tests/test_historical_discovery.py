"""Découverte et backfill d'historique — les garanties, pas les fonctions.

Chaque test nomme une panne qu'on refuse : une donnée future qui entre dans un
apprentissage, une source sans licence qui alimente le dataset, un forfait 3-0
appris comme une victoire, deux clubs fondus en un.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from src.agents.quant.historical_discovery.adapters import nflverse, openfootball
from src.agents.quant.historical_discovery.capability import (
    CapabilityRegistry, HistoricalProviderCapability)
from src.agents.quant.historical_discovery.classification import (
    Axe, AxeMesure, SourceClassification)
from src.agents.quant.historical_discovery.dedup import (
    TOLERANCE_PAR_DEFAUT, dedupliquer, tolerance_pour)
from src.agents.quant.historical_discovery.evidence import HistoricalMatchEvidence
from src.agents.quant.historical_discovery.identity_bridge import ancrer_par_instant
from src.agents.quant.historical_discovery.leakage import (
    LeakageError, filtrer_admissibles, verifier_admissibilite)
from src.agents.quant.historical_discovery.needs import HistoricalDataNeed
from src.agents.quant.historical_discovery.priority import (
    HistoricalBackfillPriority, PriorityBand, classer, probabilite_de_recuperation)
from src.agents.quant.historical_discovery.registry import registre_par_defaut
from src.agents.quant.historical_discovery.staging import (
    JsonlStagingStore, StagedObservation, StagingState, TransitionInterdite,
    transition_permise)

UTC = timezone.utc
T0 = datetime(2024, 3, 1, 20, 0, tzinfo=UTC)


def _ev(**kw):
    base = dict(
        sport="football", source="s1", source_event_id="1",
        competition="competition:football:eur:champions_league", season="2024",
        participants=("a", "b"), scheduled_at=T0, status="FINISHED",
        outcome="home", score="2-1", provenance="https://exemple/1",
        license="CC0-1.0", retrieved_at=T0)
    base.update(kw)
    return HistoricalMatchEvidence(**base)


# ── §6 : une observation sans provenance est inexploitable ──────────────────

def test_une_observation_sans_licence_est_refusee_a_la_construction():
    """Une donnée vraie mais sans droit d'usage n'est pas une donnée utilisable :
    rien ne permettrait de dire si on pouvait s'en servir."""
    with pytest.raises(ValueError):
        _ev(license="")


def test_un_horodatage_sans_fuseau_est_refuse():
    """Sans fuseau, l'ordre entre deux rencontres n'est pas défini — et tout le
    point-in-time repose sur cet ordre."""
    with pytest.raises(ValueError):
        _ev(scheduled_at=datetime(2024, 3, 1, 20, 0))


def test_une_rencontre_terminee_sans_issue_est_refusee():
    with pytest.raises(ValueError):
        _ev(outcome=None)


def test_seule_une_rencontre_terminee_est_apprenable():
    assert _ev().is_learnable
    assert not _ev(status="SCHEDULED", outcome=None).is_learnable
    assert not _ev(status="WALKOVER", outcome=None).is_learnable


# ── §9 : la fuite temporelle ────────────────────────────────────────────────

def test_un_evenement_simultane_a_la_decision_n_est_pas_admissible():
    """STRICTEMENT antérieur : deux rencontres au même instant sont simultanées,
    et l'une ne peut pas informer l'autre. Même règle que PointInTimeGateway."""
    v = verifier_admissibilite(prediction_time=T0, historical_event_time=T0,
                               data_type="results")
    assert not v.admissible and v.raison == "FUTURE_EVENT"


def test_un_evenement_anterieur_est_admissible():
    v = verifier_admissibilite(prediction_time=T0,
                               historical_event_time=T0 - timedelta(seconds=1),
                               data_type="results")
    assert v.admissible


def test_un_classement_sans_date_de_publication_est_refuse():
    """Un classement de fin de saison est antérieur à aucune des journées qu'il
    résume : sa date d'événement ne suffit pas à prouver l'absence de fuite."""
    v = verifier_admissibilite(prediction_time=T0,
                               historical_event_time=T0 - timedelta(days=30),
                               data_type="rankings")
    assert not v.admissible and v.raison == "SOURCE_TIMESTAMP_REQUIRED"


def test_un_classement_publie_apres_la_decision_est_refuse():
    v = verifier_admissibilite(
        prediction_time=T0, historical_event_time=T0 - timedelta(days=30),
        data_type="rankings", observed_source_timestamp=T0 + timedelta(days=1))
    assert not v.admissible and v.raison == "SOURCE_PUBLISHED_AFTER_DECISION"


def test_une_nature_de_donnee_inconnue_est_refusee_jamais_devinee():
    """La seule réponse qui ne peut pas laisser passer une fuite non qualifiée."""
    v = verifier_admissibilite(prediction_time=T0,
                               historical_event_time=T0 - timedelta(days=1),
                               data_type="inventé")
    assert not v.admissible and v.raison == "UNKNOWN_DATA_TYPE"


def test_une_comparaison_sans_fuseau_leve_plutot_que_de_repondre():
    with pytest.raises(LeakageError):
        verifier_admissibilite(prediction_time=datetime(2024, 3, 1),
                               historical_event_time=T0, data_type="results")


def test_le_filtre_compte_ce_qu_il_ecarte():
    """Un filtre silencieux masquerait un corpus vide derrière un run réussi."""
    retenues, rejets = filtrer_admissibles(
        [_ev(scheduled_at=T0 - timedelta(days=1)), _ev(scheduled_at=T0 + timedelta(days=1))],
        prediction_time=T0, data_type="results")
    assert len(retenues) == 1
    assert rejets == {"FUTURE_EVENT": 1}


# ── §5 : la classification est une conjonction ──────────────────────────────

def _classif(**kw):
    ok = AxeMesure(Axe.OUI, "mesuré")
    base = dict(source="x", reachable=ok, licence=ok, provenance=ok,
                structured=ok, identity_compatible=ok, point_in_time_capable=ok)
    base.update(kw)
    return SourceClassification(**base)


def test_une_source_complete_est_utilisable():
    assert _classif().is_usable


@pytest.mark.parametrize("axe", ["reachable", "licence", "provenance", "structured",
                                 "identity_compatible", "point_in_time_capable"])
def test_un_seul_axe_manquant_suffit_a_rendre_une_source_inutilisable(axe):
    """Une archive parfaite dont la licence est muette n'alimente rien. Un score
    moyennerait les axes et rendrait un chiffre honorable pour une source
    inexploitable."""
    c = _classif(**{axe: AxeMesure(Axe.UNKNOWN, "")})
    assert not c.is_usable and c.blockers


def test_un_axe_non_mesure_ne_vaut_jamais_oui():
    assert not _classif(licence=AxeMesure(Axe.UNKNOWN, "")).is_usable


def test_un_refus_mesure_et_une_mesure_absente_ne_portent_pas_le_meme_nom():
    """`NON` est un refus établi, `UNKNOWN` une mesure jamais faite : les
    confondre ferait chercher au mauvais endroit."""
    assert "LICENSE_INCOMPATIBLE" in _classif(licence=AxeMesure(Axe.NON, "CGU")).blockers
    assert "LICENSE_UNCLEAR" in _classif(licence=AxeMesure(Axe.UNKNOWN, "")).blockers


def test_un_paiement_requis_bloque_meme_si_tout_le_reste_passe():
    """§20 : jamais d'achat automatique."""
    c = _classif(paid_required=True)
    assert not c.is_usable and "PAID_REQUIRED" in c.blockers


# ── §4 : une capacité non routable n'est jamais servie ──────────────────────

def _cap(classif, **kw):
    base = dict(provider="p", sport="football", competitions=("*",),
                historical_depth_years=5, entity_types=("team",),
                data_kinds=("results",), access_type="OPEN", classification=classif)
    base.update(kw)
    return HistoricalProviderCapability(**base)


def _besoin(**kw):
    base = dict(sport="football", entity_type="team", entity_ids=("t1",),
                data_type="matches", reason="INSUFFICIENT_DATA_no_prior_form",
                minimum_required_evidence=10)
    base.update(kw)
    return HistoricalDataNeed(**base)


def test_une_source_inutilisable_n_est_jamais_proposee_pour_un_besoin():
    """Servir une capacité dont la licence bloque serait une fuite de licence
    déguisée en détail de routage."""
    r = CapabilityRegistry([_cap(_classif(licence=AxeMesure(Axe.NON, "CGU")))])
    assert r.candidates(_besoin()) == ()
    assert len(r.blocked("football")) == 1


def test_les_sources_les_plus_profondes_sont_proposees_d_abord():
    """Une archive courte ne comblera pas un cold-start ancien."""
    r = CapabilityRegistry([
        _cap(_classif(), provider="courte", historical_depth_years=2),
        _cap(_classif(), provider="longue", historical_depth_years=20)])
    assert [c.provider for c in r.candidates(_besoin())] == ["longue", "courte"]


def test_un_besoin_d_un_autre_sport_n_est_pas_route():
    r = CapabilityRegistry([_cap(_classif())])
    assert r.candidates(_besoin(sport="tennis", entity_type="player")) == ()


def test_un_data_type_inconnu_est_refuse_a_la_construction():
    with pytest.raises(ValueError):
        _besoin(data_type="rumeurs")


# ── §10 : le sas ────────────────────────────────────────────────────────────

def _obs():
    return StagedObservation(evidence=_ev(), state=StagingState.DISCOVERED, batch_id="b1")


def test_une_etape_sautee_est_refusee():
    """Vérifier l'identité APRÈS le dédoublonnage apparierait des identifiants de
    sources différentes ; l'ordre est une garantie, pas une convention."""
    with pytest.raises(TransitionInterdite):
        _obs().avancer(StagingState.STAGED, "raccourci")


def test_le_rejet_est_atteignable_depuis_n_importe_quelle_etape():
    o = _obs().avancer(StagingState.FETCHED, "ok")
    assert o.rejeter("licence").state is StagingState.REJECTED


def test_rien_ne_sort_d_un_etat_terminal():
    """Une donnée refusée ne se réhabilite pas en silence."""
    o = _obs().rejeter("licence")
    assert not transition_permise(StagingState.REJECTED, StagingState.STAGED)
    with pytest.raises(TransitionInterdite):
        o.avancer(StagingState.FETCHED, "retour")


def test_l_historique_conserve_le_chemin_parcouru():
    """Sans lui, impossible de dire POURQUOI une donnée est en production."""
    o = _obs().avancer(StagingState.FETCHED, "http 200")
    o = o.avancer(StagingState.NORMALIZED, "parsé")
    assert [h[0] for h in o.history] == ["FETCHED", "NORMALIZED"]
    assert o.history[0][1] == "http 200"


def test_le_store_refuse_le_chemin_axon_maison(tmp_path):
    with pytest.raises(ValueError):
        JsonlStagingStore("~/.axon/staging.jsonl")


def test_le_store_ecrit_les_rejets_comme_les_acceptations(tmp_path):
    """Un rejet déductible d'une absence n'est pas auditable."""
    store = JsonlStagingStore(tmp_path / "s.jsonl")
    store.append(_obs().rejeter("LICENSE_UNCLEAR"))
    rejets = store.par_etat(StagingState.REJECTED)
    assert len(rejets) == 1
    assert rejets[0]["rejection_reason"] == "LICENSE_UNCLEAR"


# ── §11 : déduplication multisport ──────────────────────────────────────────

def test_la_meme_rencontre_vue_par_deux_sources_ne_compte_qu_une_fois():
    r = dedupliquer([_ev(source="s1", source_event_id="1"),
                     _ev(source="s2", source_event_id="9")], sport="football")
    assert r.resume["unique"] == 1 and r.resume["duplicates"] == 1


def test_l_inversion_des_roles_n_empeche_pas_l_appariement():
    r = dedupliquer([_ev(source="s1", participants=("a", "b")),
                     _ev(source="s2", source_event_id="9", participants=("b", "a"))],
                    sport="football")
    assert r.resume["unique"] == 1


def test_un_doubleheader_de_baseball_reste_deux_rencontres():
    """Cinq heures séparent les deux manches d'un même après-midi. La tolérance
    football les fondrait en une, et une observation réelle disparaîtrait."""
    r = dedupliquer([_ev(sport="baseball", source="s1"),
                     _ev(sport="baseball", source="s2", source_event_id="9",
                         scheduled_at=T0 + timedelta(hours=5))], sport="baseball")
    assert r.resume["unique"] == 2


def test_un_match_de_tennis_reporte_par_la_pluie_reste_la_meme_rencontre():
    r = dedupliquer([_ev(sport="tennis", source="s1"),
                     _ev(sport="tennis", source="s2", source_event_id="9",
                         scheduled_at=T0 + timedelta(days=1))], sport="tennis")
    assert r.resume["unique"] == 1


def test_un_sport_inconnu_recoit_la_tolerance_la_plus_prudente():
    """Fusionner à tort détruit une observation ; séparer à tort se voit."""
    assert tolerance_pour("curling") == TOLERANCE_PAR_DEFAUT
    assert tolerance_pour("football") > TOLERANCE_PAR_DEFAUT


def test_deux_issues_divergentes_produisent_un_conflit_pas_un_choix():
    r = dedupliquer([_ev(source="s1", outcome="home"),
                     _ev(source="s2", source_event_id="9", outcome="draw")],
                    sport="football")
    assert r.resume["conflicts"] == 1 and r.resume["unique"] == 0


def test_un_conflit_rapporte_toutes_les_versions():
    r = dedupliquer([_ev(source="s1", outcome="home", score="2-1"),
                     _ev(source="s2", source_event_id="9", outcome="draw", score="1-1")],
                    sport="football")
    assert set(r.conflicts[0].versions) == {("s1", "home", "2-1"), ("s2", "draw", "1-1")}


def test_une_identite_non_resolue_part_en_unresolved_jamais_en_doublon():
    """Apparier sur des identifiants de sources différentes n'apparierait jamais
    rien, tout en ayant l'air de fonctionner."""
    r = dedupliquer([_ev(source="s1"), _ev(source="s2", source_event_id="9")],
                    sport="football",
                    participants_de=lambda e: None if e.source == "s2" else ("a", "b"))
    assert r.resume["unresolved"] == 1 and r.resume["unique"] == 1


def test_le_meme_identifiant_de_source_vu_deux_fois_est_un_doublon_certain():
    r = dedupliquer([_ev(source="s1", source_event_id="7"),
                     _ev(source="s1", source_event_id="7",
                         scheduled_at=T0 + timedelta(days=90))], sport="football")
    assert r.resume["unique"] == 1 and r.resume["duplicates"] == 1


def test_chaque_ligne_brute_se_retrouve_quelque_part():
    """Une observation perdue en route ressemble à un dédoublonnage réussi."""
    r = dedupliquer([_ev(source="s1"), _ev(source="s2", source_event_id="9"),
                     _ev(source="s3", source_event_id="8", outcome="away"),
                     _ev(source="s4", source_event_id="7",
                         scheduled_at=T0 + timedelta(days=30))], sport="football")
    assert r.conservation_ok


def test_aucun_rapprochement_flou_n_est_tente():
    import inspect

    from src.agents.quant.historical_discovery import dedup, identity_bridge

    for module in (dedup, identity_bridge):
        source = inspect.getsource(module).lower()
        for interdit in ("difflib", "sequencematcher", "levenshtein", "fuzz"):
            assert interdit not in source, module.__name__


# ── §7 : l'ancrage ne lit aucun nom ─────────────────────────────────────────

class _Ref:
    def __init__(self, quand, participants, saison="2024"):
        self.competition = "competition:football:eur:champions_league"
        self.scheduled_at = quand
        self.participants = participants
        self.season = saison


def test_un_instant_partage_par_une_seule_rencontre_identifie_les_deux_camps():
    a = ancrer_par_instant([_ev(participants=("Ajax", "Roma"))],
                           [_Ref(T0, ("team:nld:ajax", "team:ita:roma"))])
    assert a.paires == {"Ajax": "team:nld:ajax", "Roma": "team:ita:roma"}


def test_la_propagation_leve_l_ambiguite_d_une_soiree_entiere():
    """Huit rencontres à 21 h : l'instant seul ne dit plus laquelle est laquelle.
    Un camp connu désigne SA rencontre, ce qui livre son adversaire."""
    t1 = T0 + timedelta(days=7)
    gauche = [_ev(participants=("Ajax", "Roma"), source_event_id="1"),
              _ev(participants=("Ajax", "Lyon"), scheduled_at=t1, source_event_id="2"),
              _ev(participants=("Porto", "Bale"), scheduled_at=t1, source_event_id="3")]
    droite = [_Ref(T0, ("nld:ajax", "ita:roma")),
              _Ref(t1, ("nld:ajax", "fra:lyon")),
              _Ref(t1, ("prt:porto", "sui:bale"))]
    a = ancrer_par_instant(gauche, droite)
    assert a.paires["Lyon"] == "fra:lyon"
    assert a.paires["Porto"] == "prt:porto" and a.paires["Bale"] == "sui:bale"


def test_une_contradiction_gele_le_rapprochement_au_lieu_de_trancher():
    """Une majorité masquerait exactement l'erreur qu'on cherche."""
    t1 = T0 + timedelta(days=7)
    a = ancrer_par_instant(
        [_ev(participants=("X", "Roma"), source_event_id="1"),
         _ev(participants=("X", "Roma"), scheduled_at=t1, source_event_id="2")],
        [_Ref(T0, ("club:a", "ita:roma")), _Ref(t1, ("club:b", "ita:roma"))])
    assert "X" not in a.paires and "X" in a.contradictions


def test_deux_ecritures_d_un_meme_club_sont_admises_si_les_saisons_sont_disjointes():
    """Une source qui renomme un club d'une saison à l'autre est le cas réel
    d'openfootball (`AS Monaco` puis `AS Monaco FC`)."""
    t1 = T0 + timedelta(days=400)
    a = ancrer_par_instant(
        [_ev(participants=("Monaco", "Roma"), season="2024", source_event_id="1"),
         _ev(participants=("AS Monaco FC", "Roma"), season="2025",
             scheduled_at=t1, source_event_id="2")],
        [_Ref(T0, ("fra:monaco", "ita:roma"), "2024"),
         _Ref(t1, ("fra:monaco", "ita:roma"), "2025")])
    # Les deux libellés désignent le même club : c'est le contrat qui compte.
    assert a.paires["Monaco"] == a.paires["AS Monaco FC"] == "fra:monaco"
    # Le plus récent est signalé comme alias — l'ancienneté, pas l'alphabet.
    assert a.alias_acceptes == {"AS Monaco FC": "fra:monaco"}
    assert a.non_unique == ()


def test_deux_clubs_coexistant_dans_une_saison_ne_sont_jamais_fondus():
    """Deux clubs réellement distincts se croisent ; deux écritures d'un même
    club, jamais. C'est la donnée qui tranche, pas la chaîne."""
    t1 = T0 + timedelta(days=7)
    a = ancrer_par_instant(
        [_ev(participants=("X", "Roma"), season="2024", source_event_id="1"),
         _ev(participants=("Y", "Roma"), season="2024", scheduled_at=t1,
             source_event_id="2")],
        [_Ref(T0, ("club:c", "ita:roma"), "2024"),
         _Ref(t1, ("club:c", "ita:roma"), "2024")])
    assert "X" not in a.paires and "Y" not in a.paires
    assert set(a.non_unique) == {"X", "Y"}


def test_l_ancrage_ne_contient_aucune_reference_a_un_nom():
    """La preuve doit ignorer les conventions d'écriture : c'est ce qui la rend
    plus forte qu'une ressemblance."""
    import inspect

    from src.agents.quant.historical_discovery import identity_bridge

    corps = inspect.getsource(identity_bridge.ancrer_par_instant)
    for interdit in ("name", ".nom", "nom_canonique", "lower()"):
        assert interdit not in corps


# ── Adapter openfootball ────────────────────────────────────────────────────

_CL = """= UEFA Champions League 2023/24

# Teams      32

▪ Group, Matchday 1
  Tue Sep 19 2023
    18:45  AC Milan (ITA)          v Newcastle United FC (ENG)  0-0
           BSC Young Boys (SUI)    v RB Leipzig (GER)         1-3 (1-1)
  Wed Sep 20
    21:00  Real Madrid CF (ESP)    v 1. FC Union Berlin (GER)  1-0 (0-0)

▪ Finals, Final
  Sat Jun 1 2024
    21:00  Borussia Dortmund (GER) v Real Madrid CF (ESP)     2-3 a.e.t. (1-3, 0-1)
"""

#: Cas RÉEL (Ligue des Champions 2024-25) : le domicile mène 1-0 après 90 minutes
#: et perd la qualification aux tirs au but. Lire le score final apprendrait
#: « victoire extérieure » d'une rencontre que le marché a réglée sur 1-0.
_PENALTIES = """= X 2024/25

▪ Finals, Quarterfinals
  Wed Apr 16 2025
    21:00  Club Atlético de Madrid (ESP) v Real Madrid CF (ESP)  2-4 pen. 1-0 a.e.t. (1-0, 1-0)
"""

_NON_JOUE = """= X 2020/21

▪ Group, Matchday 6
  Thu Dec 10 2020
           Villarreal CF (ESP)     v Qarabağ FK (AZE)         3-0    [awarded]
    21:00  Sivasspor (TUR)         v Maccabi Tel Aviv (ISR)   1-0 (0-0)
  Thu Mar 10 2021
           RB Leipzig (GER)        v Spartak Moskva (RUS)     [cancelled]
"""


def _parse(texte, **kw):
    base = dict(competition_id="competition:football:eur:champions_league",
                season="2023-24", tz="Europe/Zurich", provenance="https://exemple")
    base.update(kw)
    return openfootball.parser(texte, **base)


def test_le_parseur_lit_tout_le_fichier_sans_ligne_perdue():
    r = _parse(_CL)
    assert len(r.evidences) == 4 and r.unparsed == ()


def test_la_date_et_l_heure_se_reportent_d_une_ligne_a_l_autre():
    """Un lecteur laxiste rattacherait silencieusement des rencontres au mauvais
    jour ou à la mauvaise heure."""
    r = _parse(_CL)
    milan, berne = r.evidences[0], r.evidences[1]
    assert berne.scheduled_at == milan.scheduled_at        # heure héritée
    assert r.evidences[2].scheduled_at.date().day == 20    # jour suivant


def test_une_nouvelle_journee_ne_conserve_pas_l_heure_de_la_veille():
    r = _parse(_CL)
    assert r.evidences[2].scheduled_at.hour == 21


def test_le_score_retenu_est_celui_des_90_minutes_pas_de_la_prolongation():
    """`2-3 a.e.t. (1-3, 0-1)` : un 1X2 se règle au temps réglementaire."""
    finale = _parse(_CL).evidences[3]
    assert finale.sport_specific["goals_home"] == 1
    assert finale.sport_specific["goals_away"] == 3
    assert finale.outcome == "away"


def test_les_tirs_au_but_ne_deviennent_jamais_une_victoire():
    """Le score final `2-4` est celui des tirs au but ; la rencontre s'est jouée
    1-0. Lire le premier apprendrait au modèle une victoire extérieure là où le
    marché a coté — et réglé — une victoire à domicile."""
    m = _parse(_PENALTIES, season="2024-25").evidences[0]
    assert m.outcome == "home"
    assert (m.sport_specific["goals_home"], m.sport_specific["goals_away"]) == (1, 0)


def test_un_forfait_sur_tapis_vert_n_est_pas_une_issue_apprenable():
    """Un 3-0 administratif que personne n'a construit sur le terrain."""
    r = _parse(_NON_JOUE, season="2020-21")
    forfait = next(e for e in r.evidences if "Villarreal" in e.participants[0])
    assert forfait.status == "WALKOVER" and not forfait.is_learnable


def test_une_rencontre_annulee_est_nommee_pas_ignoree():
    r = _parse(_NON_JOUE, season="2020-21")
    annule = next(e for e in r.evidences if "Leipzig" in e.participants[0])
    assert annule.status == "CANCELLED" and not annule.is_learnable
    assert r.unparsed == ()


def test_le_suffixe_pays_est_conserve_a_part_jamais_dans_le_nom():
    """Un signal d'identité ancré au pays vaut mieux qu'une ressemblance de nom."""
    m = _parse(_CL).evidences[0]
    assert m.participants[0] == "AC Milan"
    assert m.sport_specific["country_home"] == "ITA"


def test_le_fuseau_n_est_jamais_suppose_utc():
    """Une heure locale lue comme UTC décale tout de deux heures — assez pour
    faire basculer une rencontre de l'autre côté d'un cutoff."""
    zurich = _parse(_CL).evidences[0].scheduled_at
    assert zurich.utcoffset().total_seconds() == 7200      # CEST en septembre
    assert not _parse(_CL).evidences[0].timezone_verified


def test_une_rencontre_sans_date_connue_n_est_jamais_rattachee_au_hasard():
    r = _parse("▪ Group\n    18:45  A (ESP) v B (ITA)  1-0\n")
    assert r.evidences == () and len(r.unparsed) == 1


def test_le_recoupement_de_fuseau_rejette_un_decalage_constant():
    """Un fuseau faux décale TOUT ; quelques rencontres décalées sont des reports."""
    r = _parse(_CL)
    refs = [(e.scheduled_at + timedelta(hours=3), "", "") for e in r.evidences]
    v = openfootball.verifier_fuseau(r.evidences, refs, minimum=2)
    assert v.verdict == "INCONSISTENT"


def test_un_recouvrement_insuffisant_ne_vaut_pas_une_verification():
    r = _parse(_CL)
    v = openfootball.verifier_fuseau(
        r.evidences, [(r.evidences[0].scheduled_at, "", "")], minimum=20)
    assert v.verdict == "INSUFFICIENT_OVERLAP" and not v.est_verifie


# ── Adapter nflverse ────────────────────────────────────────────────────────

_NFL = (
    "game_id,season,game_type,week,gameday,gametime,away_team,away_score,"
    "home_team,home_score,overtime\n"
    "2023_01_KC_DET,2023,REG,1,2023-09-07,20:20,DET,21,KC,20,0\n"
    "2023_01_TIE_XX,2023,REG,1,2023-09-10,13:00,NYG,17,DAL,17,1\n"
    "2026_01_FUT_YY,2026,REG,1,2026-09-10,13:00,NYG,,DAL,,0\n")


def test_l_adapter_nfl_lit_le_csv_sans_ligne_perdue():
    r = nflverse.parser(_NFL, competition_id="competition:american_football:usa:nfl")
    assert len(r.evidences) == 3 and r.unparsed == ()


def test_un_nul_nfl_reste_un_nul():
    """Rare mais réel : l'écraser en victoire domicile fausserait une issue."""
    r = nflverse.parser(_NFL, competition_id="c")
    assert r.evidences[1].outcome == "draw"


def test_la_prolongation_nfl_fait_partie_du_resultat():
    """Contraire au 1X2 football : un moneyline se règle sur le score final."""
    r = nflverse.parser(_NFL, competition_id="c")
    assert r.evidences[1].sport_specific["overtime"] is True
    assert r.evidences[1].score == "17-17"


def test_une_rencontre_a_venir_n_est_pas_apprenable():
    r = nflverse.parser(_NFL, competition_id="c")
    assert r.evidences[2].status == "SCHEDULED" and not r.evidences[2].is_learnable


def test_le_filtre_de_saison_restreint_sans_perdre_le_compte():
    r = nflverse.parser(_NFL, competition_id="c", saisons=["2023"])
    assert len(r.evidences) == 2 and r.n_lignes == 3


def test_les_deux_adapters_produisent_le_meme_contrat():
    """Le noyau commun est le CONTRAT, pas l'implémentation — deux sports, deux
    formats, un seul type d'observation en sortie."""
    a = _parse(_CL).evidences[0]
    b = nflverse.parser(_NFL, competition_id="c").evidences[0]
    assert type(a) is type(b) is HistoricalMatchEvidence
    assert a.sport != b.sport and a.license != b.license


# ── §14 : la priorisation ───────────────────────────────────────────────────

def _prio(**kw):
    base = dict(need=_besoin(), predictions_perdues=100, coverage_gap=Decimal("0.01"),
                sample_size_gap=10, entites_affectees=5, source_gratuite=True,
                cout_reseau_estime=10, recovery_probability=Decimal("1"),
                ferme_un_critere_de_maturite=False)
    base.update(kw)
    return HistoricalBackfillPriority(**base)


def test_un_gain_inatteignable_ne_remonte_jamais_en_tete():
    """Autrement le classement recommanderait en premier ce que §20 interdit."""
    bloque = _prio(predictions_perdues=100000, recovery_probability=Decimal("0"))
    assert bloque.score == 0 and bloque.band is PriorityBand.BLOQUEE


def test_un_besoin_bloque_reste_dans_la_liste_au_lieu_de_disparaitre():
    """C'est l'inventaire de ce qu'il faudrait débloquer."""
    ordre = classer([_prio(recovery_probability=Decimal("0"),
                           predictions_perdues=99999), _prio()])
    assert ordre[-1].band is PriorityBand.BLOQUEE and len(ordre) == 2


def test_fermer_un_critere_de_maturite_domine_le_classement():
    """Débloquer un modèle entier vaut mieux que gagner quelques évaluations."""
    a = _prio(ferme_un_critere_de_maturite=True, predictions_perdues=10)
    b = _prio(predictions_perdues=200)
    assert a.score > b.score and a.band is PriorityBand.HAUTE


def test_un_cout_reseau_eleve_tempere_sans_annuler():
    cher = _prio(cout_reseau_estime=10_000)
    assert 0 < cher.score < _prio().score


def test_la_probabilite_de_recuperation_vient_de_la_classification_pas_d_une_intuition():
    proba, source, _ = probabilite_de_recuperation([_cap(_classif(), provider="ok")])
    assert proba == Decimal("1") and source == "ok"
    proba, source, blocages = probabilite_de_recuperation(
        [_cap(_classif(licence=AxeMesure(Axe.NON, "CGU")))])
    assert proba == Decimal("0") and not source and "LICENSE_INCOMPATIBLE" in blocages


def test_sans_aucune_source_connue_le_blocage_est_nomme():
    proba, _s, blocages = probabilite_de_recuperation([])
    assert proba == Decimal("0") and blocages == ("NO_SOURCE_KNOWN",)


# ── Le registre : aucune source utilisable sans preuve ──────────────────────

def test_toute_source_routable_porte_une_licence_lue_et_un_fuseau_recoupe():
    """Une entrée sans preuve serait une déclaration d'intention déguisée."""
    for c in registre_par_defaut().all():
        if not c.is_routable:
            continue
        assert c.classification.licence_id, c.provider
        assert c.classification.licence.evidence, c.provider
        assert c.classification.point_in_time_capable.evidence, c.provider


def test_les_sources_ecartees_restent_visibles_avec_leur_motif():
    """Les garder évite de les redécouvrir avec enthousiasme au prochain manque."""
    bloquees = {c.provider: c.classification.blockers
                for c in registre_par_defaut().all() if not c.is_routable}
    assert "NOT_REACHABLE" in bloquees["tennis_abstract_amont"]
    assert "LICENSE_INCOMPATIBLE" in bloquees["nhl_official"]
    assert "LICENSE_INCOMPATIBLE" in bloquees["mlb_statsapi"]
    assert "LICENSE_INCOMPATIBLE" in bloquees["tml_database"]
    # Le fork WTA a EXACTEMENT les données manquantes et reste bloqué : c'est la
    # licence qui décide, pas l'utilité.
    assert "LICENSE_INCOMPATIBLE" in bloquees["sackmann_wta_fork"]


def test_la_seule_source_tennis_utilisable_est_celle_dont_la_licence_est_lue():
    """CC BY-NC-SA convient à un usage personnel non commercial ; une licence
    absente ne convient à rien, quelle que soit la valeur des données."""
    tennis = {c.provider: c for c in registre_par_defaut().for_sport("tennis")}
    # Deux sources utilisables, TOUTES DEUX sous licence lue et non commerciale.
    for nom in ("sackmann_atp_fork", "kaggle_atp_wta"):
        assert tennis[nom].is_routable, nom
        assert tennis[nom].classification.licence_id == "CC-BY-NC-SA-4.0", nom
    # Le compte Kaggle est requis, et cela reste dit — un accès obtenu n'efface
    # pas la contrainte pour qui reprendrait le pipeline.
    assert tennis["kaggle_atp_wta"].classification.auth_required
    # Le fork WTA a EXACTEMENT les données manquantes et reste refusé : c'est la
    # licence qui décide, pas l'utilité.
    assert not tennis["sackmann_wta_fork"].is_routable


def test_aucune_source_non_commerciale_n_est_declaree_utilisable():
    """§20 : accessible n'est pas permis."""
    for c in registre_par_defaut().all():
        if c.is_routable:
            assert "non commercial" not in c.classification.licence_id.lower()
            assert "interdit" not in c.classification.licence_id.lower()


# ── §9 : le référentiel saisonnier est-il BRANCHÉ, pas seulement testé ? ─────

def test_le_backfill_alimente_le_referentiel_saisonnier():
    """Une garantie qu'aucun appelant n'alimente protège zéro rencontre."""
    from src.agents.quant.gateway.core.seasonal_membership import (
        MembershipStatus, SeasonalMembershipRegistry)
    from src.agents.quant.historical_discovery.membership import alimenter

    registre = SeasonalMembershipRegistry()
    resume = alimenter(registre, [_ev(participants=("a", "b"))],
                       participants_de=lambda e: ("team:x", "team:y"))

    assert resume["ingerees"] == 1
    assert registre.membership(
        "team:x", "competition:football:eur:champions_league",
        "2024") is MembershipStatus.ACTIVE


def test_une_rencontre_non_jouee_n_etablit_aucune_appartenance():
    from src.agents.quant.gateway.core.seasonal_membership import SeasonalMembershipRegistry
    from src.agents.quant.historical_discovery.membership import alimenter

    registre = SeasonalMembershipRegistry()
    resume = alimenter(registre, [_ev(status="CANCELLED", outcome=None)],
                       participants_de=lambda e: ("team:x", "team:y"))

    assert resume["ingerees"] == 0 and resume["ignorees"] == 1 and len(registre) == 0


def test_l_effectif_complet_ne_se_declare_que_sur_demande_explicite():
    """C'est la seule porte vers un démenti : elle ne s'ouvre pas par volume."""
    from src.agents.quant.gateway.core.seasonal_membership import SeasonalMembershipRegistry
    from src.agents.quant.historical_discovery.membership import alimenter

    registre = SeasonalMembershipRegistry()
    cl = "competition:football:eur:champions_league"
    alimenter(registre, [_ev()], participants_de=lambda e: ("team:x", "team:y"))
    assert not registre.roster_is_complete(cl, "2024")

    alimenter(registre, [_ev()], participants_de=lambda e: ("team:x", "team:y"),
              saisons_completes=[(cl, "2024")])
    assert registre.roster_is_complete(cl, "2024")


def test_la_saison_europeenne_ne_se_coupe_pas_au_1er_janvier():
    """Prendre l'année civile ferait changer un club d'appartenance au milieu
    de sa campagne."""
    from datetime import datetime as _dt

    from src.agents.quant.historical_discovery.membership import (
        saison_annee_civile, saison_football_europeenne)

    assert saison_football_europeenne(_dt(2025, 9, 17)) == "2025"
    assert saison_football_europeenne(_dt(2026, 5, 30)) == "2025"
    assert saison_annee_civile(_dt(2026, 5, 30)) == "2026"


def test_le_resolveur_live_refuse_un_assemblage_impossible():
    """Chaque morceau existe, l'assemblage est faux : `premier_league` + PSG.
    Aucun contrôle structurel ne pouvait le dire avant le branchement."""
    from src.agents.quant.gateway.core.event_validation import (
        ValidationResult, ValidationStatus)
    from src.agents.quant.betting_engine.bookmakers.bookmaker_registry import (
        BookmakerEventResolver)

    impossible = ValidationResult(
        ValidationStatus.COMPETITION_MEMBERSHIP_MISMATCH,
        "competition:football:eng:premier_league", "2025",
        offending=("team:football:fra:psg",))
    resolveur = BookmakerEventResolver(
        _IDENTITE_MINIMALE(), competition_resolver=_COMP_RESOLUE,
        membership_validator=lambda ev, comp, ids: impossible)

    mapping = resolveur.resolve_event(_EVENEMENT_BRUT())

    assert mapping.identity_status == "CONFLICT"
    assert not mapping.is_usable
    assert any(e.subject == "membership" for e in mapping.evidence)


def test_sans_referentiel_le_resolveur_ne_fabrique_aucun_dementi():
    """Un rejet par ignorance serait le défaut exact que le référentiel répare."""
    from src.agents.quant.betting_engine.bookmakers.bookmaker_registry import (
        BookmakerEventResolver)

    resolveur = BookmakerEventResolver(_IDENTITE_MINIMALE(),
                                       competition_resolver=_COMP_RESOLUE)

    assert resolveur.resolve_event(_EVENEMENT_BRUT()).identity_status == "RESOLVED"


def test_une_appartenance_inconnue_ne_bloque_pas_l_evenement():
    from src.agents.quant.gateway.core.event_validation import (
        ValidationResult, ValidationStatus)
    from src.agents.quant.betting_engine.bookmakers.bookmaker_registry import (
        BookmakerEventResolver)

    inconnu = ValidationResult(ValidationStatus.MEMBERSHIP_UNKNOWN, "c", "2025")
    resolveur = BookmakerEventResolver(
        _IDENTITE_MINIMALE(), competition_resolver=_COMP_RESOLUE,
        membership_validator=lambda ev, comp, ids: inconnu)

    assert resolveur.resolve_event(_EVENEMENT_BRUT()).identity_status == "RESOLVED"


def _IDENTITE_MINIMALE():
    from src.agents.quant.gateway.core.identity_resolver import (
        CanonicalEntity, IdentityResolver)
    return IdentityResolver([
        CanonicalEntity("team:football:fra:psg", "PSG", ["Paris Saint-Germain"]),
        CanonicalEntity("team:football:eng:arsenal", "Arsenal", ["Arsenal"])])


def _COMP_RESOLUE(_event):
    return "competition:football:eng:premier_league", "RESOLVED", "competition_table"


def _EVENEMENT_BRUT():
    from src.agents.quant.betting_engine.bookmakers.protocol import RawBookmakerEvent
    return RawBookmakerEvent(
        bookmaker="winamax", bookmaker_event_id="1", sport="football",
        competition="Premier League",
        slot_1_name="Paris Saint-Germain", slot_2_name="Arsenal",
        slot_1_id=None, slot_2_id=None,
        start_time=datetime(2025, 9, 17, 19, tzinfo=UTC),
        status="PREMATCH", is_outright=False, markets=[],
        fetched_at=datetime(2025, 9, 17, 12, tzinfo=UTC),
        raw_tournament_id="1")


# ── §6 : le corpus backfillé est-il RÉELLEMENT consommé ? ───────────────────

def test_le_modele_nfl_lit_le_corpus_backfille_et_pas_la_fixture_d_origine():
    """Un backfill validé mais jamais branché produit un rapport flatteur et un
    modèle inchangé."""
    import json

    from src.agents.quant.betting_engine.sports.american_football.moneyline import (
        _FIXTURE, _FIXTURE_AVANT_BACKFILL, load_nfl_games)

    assert _FIXTURE.name == "nfl_backfilled_games.json"
    parties, _fp = load_nfl_games()
    avant = json.loads(_FIXTURE_AVANT_BACKFILL.read_text())["games"]

    assert len(parties) > len(avant), "le corpus doit être strictement plus grand"
    provenance = json.loads(_FIXTURE.read_text())["provenance"]
    assert {s["provider"] for s in provenance["sources"]} == {"api_sports", "nflverse"}
    assert provenance["pipeline"] == "historical_discovery"


def test_chaque_rencontre_backfillee_nomme_sa_source():
    """Sans provenance par rencontre, l'apport de chaque source cesse d'être
    mesurable dès la fusion."""
    import json

    from src.agents.quant.betting_engine.sports.american_football.moneyline import _FIXTURE

    sources = {g["src"] for g in json.loads(_FIXTURE.read_text())["games"]}
    assert sources == {"api_sports", "nflverse"}


def test_les_corpus_europeens_portent_leur_provenance_et_leur_licence():
    import json

    from src.agents.quant.betting_engine.calibration.historical_dataset import (
        DEFAULT_CL_FIXTURE, DEFAULT_CONF_FIXTURE, DEFAULT_EL_FIXTURE)

    for chemin in (DEFAULT_CL_FIXTURE, DEFAULT_EL_FIXTURE, DEFAULT_CONF_FIXTURE):
        provenance = json.loads(chemin.read_text())["provenance"]
        assert provenance["pipeline"] == "historical_discovery"
        assert provenance["sources"], chemin.name
        openfootball = [s for s in provenance["sources"]
                        if s["provider"] == "openfootball"]
        assert openfootball and openfootball[0]["licence"] == "CC0-1.0", chemin.name


def test_les_competitions_backfillees_sont_evaluables_par_le_chemin_produit():
    """Un modèle absent de `_ASSESSORS` est excellent sur le papier et invisible
    de toute décision."""
    from src.agents.quant.betting_engine.readiness_cli import _ASSESSORS, _COMPETITIONS

    for cle in ("champions-league", "europa-league", "conference-league"):
        assert cle in _ASSESSORS, cle
        assert cle in _COMPETITIONS, cle


# ── §10 : une compétition inconnue apparaît-elle sans code supplémentaire ? ──

class _Trace:
    def __init__(self, sport, competition_id, event_id, status, evaluated):
        self.sport, self.competition_id = sport, competition_id
        self.event_id, self.status, self.evaluated = event_id, status, evaluated


class _Observabilite:
    def __init__(self, traces):
        self.traces = traces
        self.telemetry = None


def test_une_competition_jamais_vue_entre_dans_la_couverture_sans_code():
    """L'instrument doit être dérivé des TRACES, pas d'un catalogue tenu à la
    main : une liste figée ferait disparaître du rapport la compétition qu'on
    vient d'onboarder, exactement quand on veut la surveiller."""
    from src.agents.quant.betting_engine.catalog_coverage import mesurer

    inedite = "competition:football:eur:une_coupe_inconnue"
    couverture = mesurer(_Observabilite([
        _Trace("football", inedite, "ev1", "EVALUATED", True),
        _Trace("football", inedite, "ev2", "MODEL_UNAVAILABLE", False)]))

    football = next(s for s in couverture.par_sport if s.sport == "football")
    assert football.catalog_events_seen == 2
    assert football.competition_resolved == 2
    assert football.evaluated == 1


def test_un_sport_jamais_vu_entre_aussi_sans_code():
    from src.agents.quant.betting_engine.catalog_coverage import mesurer

    couverture = mesurer(_Observabilite([
        _Trace("padel", "competition:padel:esp:premier", "e1", "EVALUATED", True)]))

    assert [s.sport for s in couverture.par_sport] == ["padel"]


def test_le_modele_football_couvre_toute_competition_de_football():
    """Le registre est par SPORT : une nouvelle compétition football hérite du
    modèle sans qu'on écrive une ligne. Seul le rattachement du tournoi
    bookmaker reste par compétition — et c'est voulu, un identifiant posé au
    jugé rattacherait silencieusement les rencontres d'un AUTRE tournoi."""
    from src.agents.quant.betting_engine.sports.registry import SPORT_MODULES

    module = SPORT_MODULES["football"]
    assert module.model is not None
    assert module.build_feature_set is not None


def test_les_competitions_sans_tid_winamax_sont_declarees_en_attente():
    """Une absence de mapping doit se LIRE, pas se déduire d'un silence."""
    from src.agents.quant.betting_engine.bookmakers.winamax.competition_mapping import (
        MAPPING_PENDING_LIVE_DISCOVERY, resolve_competition)

    for comp in ("competition:football:eur:champions_league",
                 "competition:football:eur:europa_league",
                 "competition:football:eur:conference_league"):
        assert comp in MAPPING_PENDING_LIVE_DISCOVERY, comp
        assert MAPPING_PENDING_LIVE_DISCOVERY[comp].strip()

    # Et aucun identifiant n'a été posé au jugé pour les faire « passer ».
    assert resolve_competition("999") == (None, "UNRESOLVED", "none")


# ── Adapter Sackmann (CC BY-NC-SA 4.0) ──────────────────────────────────────

_SACK = (
    "tourney_id,tourney_name,surface,tourney_level,tourney_date,winner_id,"
    "winner_name,winner_rank,loser_id,loser_name,loser_rank,score,round,best_of\n"
    "2015-520,Cherbourg CH,Hard,C,20150202,104925,Novak Djokovic,1,105138,"
    "Rafael Nadal,3,6-4 6-3,QF,3\n"
    "2015-520,Cherbourg CH,Hard,C,20150202,,,,,,,,,\n")


def _sack(**kw):
    from src.agents.quant.historical_discovery.adapters import sackmann
    base = dict(tour="atp", circuit="challenger_qualifying",
                competition_id="competition:tennis:atp:tour", provenance="https://exemple")
    base.update(kw)
    return sackmann.parser(_SACK, **base)


def test_l_adapter_sackmann_porte_la_licence_et_l_attribution():
    """CC BY-NC-SA impose l'attribution : la perdre à l'ingestion la rendrait
    impossible à restituer plus tard."""
    from src.agents.quant.historical_discovery.adapters import sackmann

    e = _sack().evidences[0]
    assert e.license == "CC-BY-NC-SA-4.0"
    assert "Jeff Sackmann" in e.sport_specific["attribution"]
    assert "NonCommercial" in sackmann.__doc__ or "NonCommercial" in sackmann.ATTRIBUTION


def test_une_ligne_sans_joueurs_est_comptee_pas_ignoree():
    r = _sack()
    assert len(r.evidences) == 1 and len(r.unparsed) == 1 and r.n_lignes == 2


def test_la_date_est_decalee_a_la_fin_du_tournoi():
    """`tourney_date` vaut pour toute l'épreuve : utilisée telle quelle, la
    finale du dimanche informerait une prédiction du mercredi précédent."""
    from src.agents.quant.historical_discovery.adapters.sackmann import (
        DECALAGE_FIN_TOURNOI)

    e = _sack().evidences[0]
    assert e.scheduled_at.date().isoformat() == "2015-02-09"    # 02-02 + 7 j
    assert e.sport_specific["tourney_date"] == "20150202"
    assert DECALAGE_FIN_TOURNOI.days == 7


def test_le_vainqueur_est_toujours_p1_et_c_est_documente():
    """Un modèle entraîné sans le savoir apprendrait « le premier gagne »."""
    e = _sack().evidences[0]
    assert e.outcome == "p1" and e.participants[0] == "Novak Djokovic"


def test_surface_niveau_et_circuit_sont_conserves():
    ss = _sack().evidences[0].sport_specific
    assert ss["surface"] == "Hard" and ss["tourney_level"] == "C"
    assert ss["circuit"] == "challenger_qualifying" and ss["round"] == "QF"
    assert ss["winner_rank"] == 1 and ss["loser_rank"] == 3


def test_un_encodage_non_utf8_est_lu_au_lieu_d_etre_corrompu(tmp_path):
    """`errors='replace'` remplacerait les accents par des losanges, et deux
    orthographes d'un joueur deviendraient deux joueurs."""
    from src.agents.quant.historical_discovery.adapters import sackmann

    f = tmp_path / "atp_matches_qual_chall_2015.csv"
    f.write_bytes(_SACK.replace("Rafael Nadal", "Rafaël Nadal").encode("cp1252"))
    r = sackmann.lire_repertoire(tmp_path, tour="atp",
                                 competition_id="competition:tennis:atp:tour")
    assert any("Rafaël Nadal" in e.participants[1] for e in r.evidences)


def test_le_circuit_se_lit_dans_le_nom_du_fichier():
    from src.agents.quant.historical_discovery.adapters.sackmann import circuit_du_fichier

    assert circuit_du_fichier("atp_matches_qual_chall_2015.csv") == "challenger_qualifying"
    assert circuit_du_fichier("atp_matches_futures_2015.csv") == "futures"
    assert circuit_du_fichier("atp_matches_2015.csv") == "tour"
    assert circuit_du_fichier("autre.csv") is None


# ── Pont d'identité joueurs ─────────────────────────────────────────────────

def test_toutes_les_decoupes_prenom_patronyme_sont_essayees():
    """« Juan Martin Del Potro » contre « Del Potro J.M. » : une seule découpe
    tombe juste, et il faut les essayer toutes pour la trouver."""
    from src.agents.quant.historical_discovery.tennis_identity import cles_candidates

    cles = cles_candidates("Juan Martin Del Potro")
    assert ("del potro", "j") in cles and ("potro", "j") in cles


def test_plusieurs_orthographes_d_un_joueur_ne_le_rendent_pas_introuvable():
    """« Del Potro J. » / « Del Potro J.M. » sont la même personne : la règle par
    défaut les refusait, et le joueur se scindait en deux identités."""
    from src.agents.quant.historical_discovery.tennis_identity import (
        famille_d_orthographes, index_tennis_data)

    noms = ["Del Potro J.", "Del Potro J. M.", "Del Potro J.M."]
    assert famille_d_orthographes(noms) == "Del Potro J."
    index, ambigues = index_tennis_data(noms, "atp")
    assert index[("del potro", "j")] == "player:tennis:atp:del_potro_j"
    assert not ambigues


def test_une_ecriture_qui_n_est_pas_des_initiales_garde_l_ambiguite():
    """« Wang Y. Jr » peut désigner quelqu'un d'autre : rien ne le prouve."""
    from src.agents.quant.historical_discovery.tennis_identity import (
        famille_d_orthographes, index_tennis_data)

    noms = ["Wang Y.", "Wang Y. Jr", "Wang Y.T."]
    assert famille_d_orthographes(noms) is None
    _index, ambigues = index_tennis_data(noms, "atp")
    assert ("wang", "y") in ambigues


def test_un_joueur_inconnu_recoit_l_identite_qu_il_aurait_sur_le_circuit():
    """Un joueur de Challenger qui monte en ATP doit retrouver SON identité,
    sinon son historique se coupe en deux au pire moment."""
    from src.agents.quant.historical_discovery.tennis_identity import (
        identite_depuis_cle, resoudre_joueurs)

    r = resoudre_joueurs(["Nouveau Joueur"], index_dataset={}, ambigues_dataset=set(),
                         tour="atp")
    assert r.par_nom["Nouveau Joueur"] == "player:tennis:atp:joueur_n"
    assert identite_depuis_cle(("joueur", "n"), "atp") == "player:tennis:atp:joueur_n"
    assert r.frappes == 1 and r.apparies == 0


def test_deux_personnes_sous_une_meme_cle_ne_sont_jamais_fusionnees():
    from src.agents.quant.historical_discovery.tennis_identity import resoudre_joueurs

    r = resoudre_joueurs(["Andrei Dupont", "Anna Dupont"],
                         index_dataset={}, ambigues_dataset=set(), tour="atp",
                         ids_par_nom={"Andrei Dupont": "1", "Anna Dupont": "2"})
    assert r.par_nom == {} and len(r.ambigus) == 2


def test_un_rapprochement_prime_sur_une_frappe():
    from src.agents.quant.historical_discovery.tennis_identity import resoudre_joueurs

    r = resoudre_joueurs(["Novak Djokovic"],
                         index_dataset={("djokovic", "n"): "player:tennis:atp:djokovic_n"},
                         ambigues_dataset=set(), tour="atp")
    assert r.par_nom["Novak Djokovic"] == "player:tennis:atp:djokovic_n"
    assert r.apparies == 1 and r.frappes == 0


def test_le_pont_ne_contient_aucun_rapprochement_flou():
    import inspect

    from src.agents.quant.historical_discovery import tennis_identity

    source = inspect.getsource(tennis_identity).lower()
    for interdit in ("difflib", "sequencematcher", "levenshtein", "fuzz", "ratio("):
        assert interdit not in source


# ── Adapter Kaggle (CC BY-NC-SA 4.0, WTA) ───────────────────────────────────

_KAGGLE = (
    "tourney_id,tourney_name,surface,tourney_level,tourney_date,match_num,"
    "winner_id,winner_name,loser_id,loser_name,score,round,best_of,league\n"
    "2012-W01,Hobart,Hard,I,2012-01-09,300,201,Anna Dupont,202,Bea Martin,"
    "6-4 6-3,R32,3,wta\n"
    "2012-M01,Brisbane,Hard,A,2012-01-02,300,101,Carl Rossi,102,Dan Weber,"
    "6-2 6-1,R32,3,atp\n"
)
_KAGGLE_JOUEURS = (
    "player_id,name_first,name_last,hand,birthdate,country,gender\n"
    "201,Anna,Dupont,R,19900101.0,FRA,female\n"
    "202,Bea,Martin,R,19910101.0,ITA,female\n"
    "101,Carl,Rossi,R,19900101.0,ITA,male\n"
    "102,Dan,Weber,R,19910101.0,GER,male\n"
)


def _kaggle(tour="wta", **kw):
    from src.agents.quant.historical_discovery.adapters import kaggle_tennis as kt
    joueurs = kt.lire_joueurs(_KAGGLE_JOUEURS)
    return kt.parser(_KAGGLE, tour=tour, competition_id=f"competition:tennis:{tour}:tour",
                     joueurs=joueurs, **kw)


def test_l_adapter_kaggle_ne_retient_que_le_circuit_demande():
    """Le fichier mêle ATP et WTA : les confondre ferait migrer des joueurs
    d'un circuit à l'autre."""
    r = _kaggle("wta")
    assert len(r.evidences) == 1
    assert r.evidences[0].participants == ("Anna Dupont", "Bea Martin")
    assert len(_kaggle("atp").evidences) == 1


def test_une_rencontre_au_mauvais_genre_est_refusee_jamais_corrigee():
    """C'est soit une erreur de la source, soit un rattachement injustifié — les
    deux doivent se voir."""
    from src.agents.quant.historical_discovery.adapters import kaggle_tennis as kt

    joueurs = kt.lire_joueurs(_KAGGLE_JOUEURS.replace(
        "201,Anna,Dupont,R,19900101.0,FRA,female", "201,Anna,Dupont,R,19900101.0,FRA,male"))
    r = kt.parser(_KAGGLE, tour="wta", competition_id="c", joueurs=joueurs)
    assert r.evidences == () and r.genres_refuses == 1


def test_la_provenance_kaggle_porte_version_licence_et_attribution():
    """§4 : aucune observation sans provenance."""
    from src.agents.quant.historical_discovery.adapters import kaggle_tennis as kt

    e = _kaggle().evidences[0]
    ss = e.sport_specific
    assert e.license == "CC-BY-NC-SA-4.0"
    assert ss["dataset"] == kt.DATASET and ss["dataset_version"] == "1"
    assert ss["dataset_maj"] == "2021-03-08"
    assert "CC BY-NC-SA 4.0" in ss["attribution"]
    assert e.provenance.startswith("https://www.kaggle.com/datasets/")
    for champ in ("circuit", "tourney_level", "tourney_name", "surface", "round"):
        assert champ in ss


def test_les_niveaux_sont_regroupes_en_categories_benchmarkables():
    """`W` est le circuit principal historique féminin — pas de l'ITF malgré la
    lettre. Le confondre changerait la décision d'intégration."""
    from src.agents.quant.historical_discovery.adapters.kaggle_tennis import CATEGORIES

    assert CATEGORIES["W"] == "tour" and CATEGORIES["I"] == "tour"
    assert CATEGORIES["D"] == "equipes"
    assert CATEGORIES["C"] == "itf" and CATEGORIES["CC"] == "itf"
    assert CATEGORIES["E"] == "exhibition" and CATEGORIES["J"] == "junior"


def test_la_date_kaggle_est_decalee_comme_celle_de_sackmann():
    """Même source amont, même granularité tournoi, donc même garde."""
    e = _kaggle().evidences[0]
    assert e.scheduled_at.date().isoformat() == "2012-01-16"      # 01-09 + 7 j
    assert e.sport_specific["date_decalee_de_jours"] == 7


def test_un_homonyme_est_separe_par_identifiant_plutot_que_jete():
    """Refuser jette aussi l'historique des ADVERSAIRES, qui n'y sont pour rien."""
    from src.agents.quant.historical_discovery.tennis_identity import (
        identite_desambiguisee, resoudre_joueurs)

    ids = {"Anna Dupont": "201", "Andrea Dupont": "999"}
    sans = resoudre_joueurs(list(ids), index_dataset={}, ambigues_dataset=set(),
                            tour="wta", ids_par_nom=ids)
    avec = resoudre_joueurs(list(ids), index_dataset={}, ambigues_dataset=set(),
                            tour="wta", ids_par_nom=ids, desambiguiser_par_id=True)

    assert sans.par_nom == {} and len(sans.ambigus) == 2
    assert len(avec.par_nom) == 2
    assert avec.par_nom["Anna Dupont"] != avec.par_nom["Andrea Dupont"]
    assert avec.par_nom["Anna Dupont"] == identite_desambiguisee(
        ("dupont", "a"), "wta", "201")


def test_la_desambiguisation_ne_fusionne_jamais_deux_personnes():
    from src.agents.quant.historical_discovery.tennis_identity import identite_desambiguisee

    a = identite_desambiguisee(("dupont", "a"), "wta", "201")
    b = identite_desambiguisee(("dupont", "a"), "wta", "999")
    assert a != b and a.startswith("player:tennis:wta:dupont_a__")


def test_les_circuits_retenus_excluent_exhibitions_et_juniors():
    """Ils n'apportent AUCUNE évaluation supplémentaire (mesuré) : le corpus n'a
    pas à porter ce qui ne change rien."""
    from src.agents.quant.betting_engine.sports.tennis.tennis_data_loader import (
        CIRCUITS_RETENUS)

    assert "exhibition" not in CIRCUITS_RETENUS and "junior" not in CIRCUITS_RETENUS
    assert {"tour", "equipes", "itf", "challenger_qualifying"} <= set(CIRCUITS_RETENUS)


def test_le_backfill_wta_est_charge_et_reste_du_contexte():
    from src.agents.quant.betting_engine.sports.tennis.tennis_data_loader import (
        load_tennis_data)

    ds = load_tennis_data("wta")
    contexte = [m for m in ds.matches if m.circuit is not None]
    assert len(contexte) > 100_000
    assert not any(m.est_cible_d_evaluation for m in contexte)
    assert {m.circuit for m in contexte} == {"tour", "equipes", "itf"}
