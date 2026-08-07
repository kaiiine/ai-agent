"""Collecte CLV automatique — la phase se déduit du coup d'envoi.

`record-odds` demandait la phase en argument. C'était juste tant qu'un humain la
choisissait ; ça ne l'est plus dès qu'on collecte en continu, car la bonne phase
n'est pas la même pour deux rencontres du même scan — l'une part dans dix
minutes, l'autre demain. Résultat mesuré sur l'historique réel : 113 décisions,
zéro clôture.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.agents.quant.betting_engine.bookmakers.bookmaker_registry import BookmakerEventResolver
from src.agents.quant.betting_engine.bookmakers.winamax.record_replay import (
    replay,
    synthetic_capture,
)
from src.agents.quant.betting_engine.clv.collect import (
    FENETRE_CLOTURE,
    collect,
    phase_pour,
)
from src.agents.quant.betting_engine.clv.observation import ObservationPhase
from src.agents.quant.betting_engine.clv.store import JsonlOddsHistoryStore
from src.agents.quant.betting_engine.clv.clv import MEASURABLE, clv_readiness
from src.agents.quant.gateway.core.identity_resolver import CanonicalEntity, IdentityResolver
from tests.test_clv_recorder import _fl1_state

_COUP_ENVOI = datetime(2026, 3, 1, 10, 0, tzinfo=timezone.utc)


def _resolveur():
    identity = IdentityResolver([
        CanonicalEntity("team:football:fra:psg", "Paris Saint Germain",
                        ["PSG", "Paris SG", "Paris Saint-Germain"], {}),
        CanonicalEntity("team:football:fra:marseille", "Marseille",
                        ["OM", "Olympique de Marseille"], {})])
    comp = lambda ev: (("competition:football:fra:ligue1", "RESOLVED", "competition_table")
                       if ev.raw_tournament_id == "4" else (None, "UNRESOLVED", "none"))
    return BookmakerEventResolver(identity, competition_resolver=comp)


def _evenements(cote, quand):
    return replay(synthetic_capture(_fl1_state(home_odds=cote), "football"), now=quand)


def _passe(store, cote, quand):
    return collect(_evenements(cote, quand), event_resolver=_resolveur(),
                   store=store, source="synthetic", now=quand)


# ══ La phase se DÉDUIT, elle ne se choisit pas ══════════════════════════════
@pytest.mark.parametrize("ecart,attendue", [
    (timedelta(days=1), ObservationPhase.DECISION),
    (timedelta(hours=3), ObservationPhase.DECISION),
    (timedelta(minutes=31), ObservationPhase.DECISION),
    (timedelta(minutes=29), ObservationPhase.CLOSING),
    (timedelta(minutes=1), ObservationPhase.CLOSING),
])
def test_la_phase_suit_la_distance_au_coup_d_envoi(ecart, attendue):
    assert phase_pour(_COUP_ENVOI, _COUP_ENVOI - ecart) is attendue


def test_une_rencontre_commencee_ne_merite_aucune_phase():
    """Ni décision ni clôture : après le coup d'envoi, la cote est du direct."""
    assert phase_pour(_COUP_ENVOI, _COUP_ENVOI + timedelta(minutes=1)) is None
    assert phase_pour(_COUP_ENVOI, _COUP_ENVOI) is None          # pile à l'heure


def test_une_rencontre_trop_lointaine_est_ecartee():
    """Les marchés bougent encore beaucoup ; la cote observée ne ressemble pas à
    celle qu'on prendrait."""
    assert phase_pour(_COUP_ENVOI, _COUP_ENVOI - timedelta(days=5)) is None


def test_une_rencontre_sans_horaire_est_ecartee():
    """Sans horaire, elle ne peut pas être située — et la ranger par défaut dans
    la phase la moins gênante reviendrait à deviner."""
    assert phase_pour(None, _COUP_ENVOI) is None


# ══ Le cycle complet, sans intervention humaine ════════════════════════════
def test_deux_passes_espacees_produisent_une_paire(tmp_path):
    """Le scénario qui manquait : la même commande, lancée deux fois à des
    moments différents, traverse la rencontre de la décision à la clôture."""
    store = JsonlOddsHistoryStore(tmp_path / "odds.jsonl")

    veille = _passe(store, 2.10, _COUP_ENVOI - timedelta(hours=6))
    assert veille.decisions_ecrites == 3 and veille.clotures_ecrites == 0

    juste_avant = _passe(store, 1.90, _COUP_ENVOI - timedelta(minutes=10))
    assert juste_avant.decisions_ecrites == 0 and juste_avant.clotures_ecrites == 3

    lecture = clv_readiness(store.all())
    assert lecture.status == MEASURABLE
    assert lecture.n_complete_pairs == 3 and lecture.n_events == 1


def test_relancer_la_collecte_n_ecrit_rien_de_neuf(tmp_path):
    """Un planificateur qui tourne toutes les cinq minutes ne doit pas écrire
    cinq cents décisions pour un même match."""
    store = JsonlOddsHistoryStore(tmp_path / "odds.jsonl")
    quand = _COUP_ENVOI - timedelta(hours=6)

    premiere = _passe(store, 2.10, quand)
    for _ in range(4):
        suivante = _passe(store, 2.10, quand + timedelta(minutes=5))

    assert premiere.decisions_ecrites == 3
    assert suivante.decisions_ecrites == 0 and suivante.deja_connues == 3
    assert len(store.all()) == 3


def test_une_cote_qui_bouge_ne_cree_pas_une_seconde_decision(tmp_path):
    """L'appariement retient UNE clôture par marché : une seconde observation de
    la même phase serait au mieux ignorée, au pire trompeuse sur la taille réelle
    de l'échantillon."""
    store = JsonlOddsHistoryStore(tmp_path / "odds.jsonl")
    quand = _COUP_ENVOI - timedelta(hours=6)

    _passe(store, 2.10, quand)
    seconde = _passe(store, 2.55, quand + timedelta(minutes=5))    # la cote a bougé

    assert seconde.decisions_ecrites == 0
    assert len(store.all()) == 3


def test_la_cloture_n_est_jamais_prise_apres_le_coup_d_envoi(tmp_path):
    """Le garde du recorder reste actif : la collecte automatique ne le contourne
    pas, elle s'appuie dessus."""
    store = JsonlOddsHistoryStore(tmp_path / "odds.jsonl")

    _passe(store, 2.10, _COUP_ENVOI - timedelta(hours=6))
    apres = _passe(store, 1.50, _COUP_ENVOI + timedelta(minutes=5))

    assert apres.clotures_ecrites == 0
    assert apres.deja_commencees >= 1
    assert clv_readiness(store.all()).status != MEASURABLE


def test_la_fenetre_de_cloture_est_reglable(tmp_path):
    """Elle doit se marier avec la période du planificateur : trop étroite, elle
    rate les rencontres ; trop large, elle capture une cote encore loin."""
    store = JsonlOddsHistoryStore(tmp_path / "odds.jsonl")
    quand = _COUP_ENVOI - timedelta(minutes=45)

    resume = collect(_evenements(1.90, quand), event_resolver=_resolveur(),
                     store=store, source="synthetic", now=quand,
                     fenetre=timedelta(minutes=60))

    assert resume.clotures_ecrites == 3 and resume.decisions_ecrites == 0


def test_la_fenetre_par_defaut_convient_a_un_declenchement_frequent():
    """Trente minutes se marient avec un déclenchement toutes les cinq à dix
    minutes : la clôture est prise au plus tôt à W du coup d'envoi."""
    assert timedelta(minutes=10) <= FENETRE_CLOTURE <= timedelta(hours=1)


# ══ Le compte rendu dit ce qui s'est passé ═════════════════════════════════
def test_le_resume_distingue_chaque_motif(tmp_path):
    """« rien écrit » peut vouloir dire quatre choses, qui se corrigent
    différemment : déjà connu, trop lointain, déjà commencé, illisible."""
    store = JsonlOddsHistoryStore(tmp_path / "odds.jsonl")
    resume = _passe(store, 2.10, _COUP_ENVOI - timedelta(days=9))

    assert resume.trop_lointaines == 1
    assert resume.decisions_ecrites == 0
    assert "trop lointaine" in resume.describe()


# ══ La commande qu'un planificateur appelle ════════════════════════════════
def test_la_commande_ne_demande_aucune_phase(tmp_path, capsys):
    """C'est tout l'objet du module : la phase n'est plus un argument, donc plus
    un oubli possible."""
    from src.agents.quant.betting_engine.clv import collect_cli

    class _Connecteur:
        def scan_catalog(self, sport):
            if sport != "football":
                return []
            return _evenements(2.10, _COUP_ENVOI - timedelta(hours=6))

    store = JsonlOddsHistoryStore(tmp_path / "odds.jsonl")
    code = collect_cli.main(
        ["--sports", "football"], connector=_Connecteur(), store=store,
        now=_COUP_ENVOI - timedelta(hours=6))

    assert code == 0
    assert "décision(s)" in capsys.readouterr().out
    assert {o.phase for o in store.all()} == {ObservationPhase.DECISION}


def test_la_commande_traverse_le_cycle_complet(tmp_path):
    """Deux invocations espacées, exactement comme le ferait une crontab."""
    from src.agents.quant.betting_engine.clv import collect_cli

    class _Connecteur:
        def __init__(self, cote, quand):
            self._cote, self._quand = cote, quand

        def scan_catalog(self, sport):
            return _evenements(self._cote, self._quand) if sport == "football" else []

    store = JsonlOddsHistoryStore(tmp_path / "odds.jsonl")
    for cote, quand in ((2.10, _COUP_ENVOI - timedelta(hours=6)),
                        (1.90, _COUP_ENVOI - timedelta(minutes=10))):
        collect_cli.main(["--sports", "football"], connector=_Connecteur(cote, quand),
                         store=store, now=quand)

    assert clv_readiness(store.all()).status == MEASURABLE


def test_une_panne_de_scan_remonte_au_planificateur(tmp_path):
    """Une source injoignable est une panne, pas un catalogue vide. La taire
    ferait croire à une collecte saine qui n'écrit jamais rien."""
    from src.agents.quant.betting_engine.clv import collect_cli

    class _Casse:
        def scan_catalog(self, sport):
            raise ConnectionError("winamax injoignable")

    with pytest.raises(ConnectionError):
        collect_cli.main(["--sports", "football"], connector=_Casse(),
                         store=JsonlOddsHistoryStore(tmp_path / "odds.jsonl"),
                         now=_COUP_ENVOI)


# ══ Aiguillage : à QUEL modèle appartient une observation ══════════════════
# Sans aiguillage, deux erreurs opposées : ne rien passer — et `positive_clv`
# reste à zéro pendant que l'historique se remplit — ou tout passer, et le modèle
# NHL se voit créditer des paires de baseball.
def _obs(event_id, phase=ObservationPhase.DECISION):
    from decimal import Decimal

    from src.agents.quant.betting_engine.clv.observation import OddsObservation

    return OddsObservation(
        event_id=event_id, market_type="MATCH_WINNER", selection="home",
        bookmaker="winamax", decimal_odds=Decimal("2.0"),
        observed_at=_COUP_ENVOI - timedelta(hours=1), phase=phase,
        source="synthetic", source_event_id="x", run_id=None)


def test_chaque_modele_ne_recoit_que_ses_propres_observations():
    from src.agents.quant.betting_engine.clv.routing import observations_pour

    lot = [
        _obs("event:baseball:mlb:2026-03-01T10:00:00Z:home=a|away=b"),
        _obs("event:hockey:nhl:2026-03-01T10:00:00Z:home=c|away=d"),
        _obs("event:football:eredivisie:2026-03-01T10:00:00Z:home=e|away=f"),
    ]

    assert len(observations_pour("mlb", lot)) == 1
    assert len(observations_pour("nhl", lot)) == 1
    assert len(observations_pour("eredivisie", lot)) == 1
    assert observations_pour("nba", lot) == []


def test_deux_competitions_du_meme_sport_ne_se_melangent_pas():
    """Sept modèles de football coexistent ; leur créditer les paires les uns des
    autres mesurerait autre chose que ce qu'on croit mesurer."""
    from src.agents.quant.betting_engine.clv.routing import observations_pour

    lot = [_obs("event:football:eredivisie:2026-03-01T10:00:00Z:home=a|away=b"),
           _obs("event:football:ligue1:2026-03-01T10:00:00Z:home=c|away=d")]

    assert len(observations_pour("eredivisie", lot)) == 1
    assert len(observations_pour("fl1", lot)) == 1


def test_un_modele_inconnu_ne_recoit_rien():
    """Mieux vaut un critère qui n'avance pas qu'un critère nourri au hasard."""
    from src.agents.quant.betting_engine.clv.routing import observations_pour

    assert observations_pour("curling", [_obs("event:curling:x:2026:home=a|away=b")]) == []


def test_le_tennis_est_aiguille_par_le_circuit_de_ses_joueurs():
    """ATP et WTA partagent le slug de compétition `tour` : l'identité de
    l'événement ne suffit pas. Ce qui les sépare est le référentiel des joueurs."""
    from src.agents.quant.betting_engine.clv.routing import observations_pour
    from src.agents.quant.betting_engine.sports.registry import SPORT_MODULES

    par_circuit: dict[str, list[str]] = {}
    for entite in SPORT_MODULES["tennis"].known_entities():
        parties = entite.canonical_id.split(":")
        par_circuit.setdefault(parties[2], []).append(parties[3])
    if not {"atp", "wta"} <= set(par_circuit):
        pytest.skip("référentiel tennis incomplet")

    a1, a2 = par_circuit["atp"][:2]
    w1, w2 = par_circuit["wta"][:2]
    lot = [_obs(f"event:tennis:tour:2026-03-01T10:00:00Z:player_a={a1}|player_b={a2}"),
           _obs(f"event:tennis:tour:2026-03-01T10:00:00Z:player_a={w1}|player_b={w2}")]

    assert len(observations_pour("atp", lot)) == 1
    assert len(observations_pour("wta", lot)) == 1


def test_une_rencontre_tennis_non_resolue_n_est_attribuee_a_personne():
    """Un joueur inconnu du référentiel ne permet pas de trancher, et attribuer
    la rencontre au hasard fausserait l'un des deux modèles."""
    from src.agents.quant.betting_engine.clv.routing import observations_pour

    lot = [_obs("event:tennis:tour:2026-03-01T10:00:00Z:player_a=inconnu|player_b=autre")]

    assert observations_pour("atp", lot) == []
    assert observations_pour("wta", lot) == []


def test_la_readiness_lit_reellement_l_historique_collecte():
    """La boucle complète : les enveloppes acceptaient un argument
    `odds_observations` et le JETAIENT. L'historique pouvait se remplir
    indéfiniment sans que `positive_clv` bouge d'un pouce."""
    import inspect

    from src.agents.quant.betting_engine import readiness_cli

    for nom in ("_assess_mlb", "_assess_nhl", "_assess_atp", "_assess_nba",
                "_assess_nfl", "_assess_volley", "_assess_wta"):
        source = inspect.getsource(getattr(readiness_cli, nom))
        assert "odds_observations=odds" in source or "odds_observations=odds" in source, nom


@pytest.mark.parametrize("cle", ["mlb", "nhl", "nfl", "volley", "nba", "atp", "wta"])
def test_chaque_assesseur_consomme_vraiment_ses_observations(cle):
    """Bout en bout, sans toucher au disque : une paire injectée doit rendre la
    CLV mesurable pour ce modèle."""
    from src.agents.quant.betting_engine.readiness_cli import _ASSESSORS

    event = {"mlb": "event:baseball:mlb", "nhl": "event:hockey:nhl",
             "nfl": "event:american_football:nfl", "volley": "event:volleyball:serie_a1",
             "nba": "event:basketball:nba", "atp": "event:tennis:tour",
             "wta": "event:tennis:tour"}[cle]
    paire = [
        _obs(f"{event}:2026-03-01T10:00:00Z:home=a|away=b", ObservationPhase.DECISION),
        _obs(f"{event}:2026-03-01T10:00:00Z:home=a|away=b", ObservationPhase.CLOSING),
    ]
    # La clôture doit être postérieure à la décision.
    import dataclasses
    paire[1] = dataclasses.replace(paire[1], observed_at=paire[0].observed_at + timedelta(minutes=30))

    observations = _ASSESSORS[cle](paire).observations

    assert observations.clv_n_events == 1, cle
    assert observations.clv_status == MEASURABLE, cle
