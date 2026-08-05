"""Double appartenance : une équipe joue dans plusieurs compétitions à la fois.

Le défaut corrigé ici était silencieux et money-sensitive. `gateway.recent_form`
choisissait le dataset en cherchant la PREMIÈRE ligue contenant l'équipe
(`_team_league`). Conséquences, sans erreur ni trace :

  - un événement de Ligue des Champions était servi avec la forme de Ligue 1 —
    le modèle voyait la bonne équipe, la mauvaise population ;
  - une équipe hors des 8 ligues onboardées était déclarée introuvable alors que
    son historique européen existait.

La chaîne est désormais : événement -> compétition canonique -> couverture
provider -> historique du participant. Ces tests verrouillent le fait qu'aucun
maillon ne repart de l'équipe.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.agents.quant.betting_engine.core.canonical_event import (
    CanonicalEvent,
    CanonicalParticipant,
)
from src.agents.quant.betting_engine.sports.football.feature_engineering.event_features import (
    build_event_feature_set,
)

L1 = "competition:football:fra:ligue1"
UCL = "competition:football:eur:champions_league"
PSG = "team:football:fra:psg"
LYON = "team:football:fra:lyon"

_KICKOFF = datetime(2025, 9, 20, 19, 0, tzinfo=timezone.utc)


def _match(cid: str, *, date: str, gf: int, ga: int, home: bool = True) -> dict:
    return {"date": date, "is_home": home, "goals_home": gf if home else ga,
            "goals_away": ga if home else gf, "league_id": cid, "season": "2025",
            "opponent_id": "team:football:xxx:other"}


class _CompetitionScopedGateway:
    """Deux datasets DISJOINTS, un par compétition. Toute fuite d'un dataset vers
    l'autre se voit dans les features : les valeurs n'ont rien en commun."""

    def __init__(self):
        self.calls: list[tuple[str, str]] = []          # (team, competition) demandés
        self._data = {
            # Domestique : 5 matchs, 2 buts marqués par match.
            (PSG, L1): [_match(L1, date=f"2025-09-0{i}", gf=2, ga=0) for i in range(1, 6)],
            (LYON, L1): [_match(L1, date=f"2025-09-0{i}", gf=1, ga=1) for i in range(1, 6)],
            # UEFA : 6 matchs, 0 but marqué — volontairement incompatible.
            (PSG, UCL): [_match(UCL, date=f"2025-09-1{i}", gf=0, ga=3) for i in range(0, 6)],
            (LYON, UCL): [_match(UCL, date=f"2025-09-1{i}", gf=0, ga=1) for i in range(0, 6)],
        }

    def recent_form(self, canonical_team_id, *, competition_id, last, season):
        self.calls.append((canonical_team_id, competition_id))
        return self._data.get((canonical_team_id, competition_id), [])[:last]

    def standings_strength(self, league_canonical_id, season):
        self.calls.append(("__standings__", league_canonical_id))
        return {}


def _event(competition_id: str) -> CanonicalEvent:
    return CanonicalEvent(
        event_id=f"evt:{competition_id}",
        sport="football",
        competition_id=competition_id,
        scheduled_at=_KICKOFF,
        participants=(
            CanonicalParticipant(canonical_id=PSG, role="home"),
            CanonicalParticipant(canonical_id=LYON, role="away"),
        ),
    )


@pytest.fixture
def gw():
    return _CompetitionScopedGateway()


# ── la compétition demandée est celle de l'événement ────────────────────────────
@pytest.mark.parametrize("competition", [L1, UCL])
def test_les_features_sont_demandees_pour_la_competition_de_l_evenement(gw, competition):
    build_event_feature_set(_event(competition), gw, as_of=_KICKOFF)

    demandes = {comp for team, comp in gw.calls if team != "__standings__"}
    assert demandes == {competition}, (
        f"dataset demandé pour {demandes}, alors que l'événement est de {competition}")


def test_la_meme_equipe_joue_dans_deux_competitions_le_meme_jour(gw):
    """PSG en Ligue 1 ET en C1 : deux événements, deux datasets, aucune redirection."""
    dom = build_event_feature_set(_event(L1), gw, as_of=_KICKOFF)
    eur = build_event_feature_set(_event(UCL), gw, as_of=_KICKOFF)

    dom_psg = dom.participant_features[PSG]
    eur_psg = eur.participant_features[PSG]

    assert dom_psg["form_matches"] == 5 and eur_psg["form_matches"] == 6
    assert dom_psg["form_goals_for_avg"] == 2.0    # dataset domestique
    assert eur_psg["form_goals_for_avg"] == 0.0    # dataset européen
    assert dom_psg["form_win_rate"] != eur_psg["form_win_rate"]


def test_aucune_feature_uefa_ne_vient_du_dataset_domestique(gw):
    eur = build_event_feature_set(_event(UCL), gw, as_of=_KICKOFF)

    assert (LYON, L1) not in gw.calls and (PSG, L1) not in gw.calls
    # signature du dataset domestique (2 buts/match) absente des features UEFA
    for cid in (PSG, LYON):
        assert eur.participant_features[cid]["form_goals_for_avg"] == 0.0


def test_aucune_feature_domestique_ne_vient_du_dataset_uefa(gw):
    dom = build_event_feature_set(_event(L1), gw, as_of=_KICKOFF)

    assert (PSG, UCL) not in gw.calls and (LYON, UCL) not in gw.calls
    assert dom.participant_features[PSG]["form_matches"] == 5   # 6 = signature UEFA


def test_le_classement_est_lui_aussi_scope_a_la_competition(gw):
    build_event_feature_set(_event(UCL), gw, as_of=_KICKOFF)
    standings = [comp for team, comp in gw.calls if team == "__standings__"]
    assert standings == [UCL]


# ── la fonction fautive ne doit pas revenir ─────────────────────────────────────
def test_la_gateway_n_expose_plus_de_resolution_ligue_par_equipe():
    """`_team_league(team)` supposait une appartenance unique. Toute fonction qui
    déduit une compétition à partir d'une équipe seule réintroduit le défaut."""
    from src.agents.quant.gateway import gateway as gw_mod

    assert not hasattr(gw_mod, "_team_league")


def test_recent_form_exige_la_competition():
    """Sans paramètre obligatoire, un appelant distrait retombe sur une déduction
    implicite — c'est exactement ainsi que le défaut était né."""
    import inspect
    from src.agents.quant.gateway import gateway as gw_mod

    params = inspect.signature(gw_mod.recent_form).parameters
    assert "competition_id" in params
    assert params["competition_id"].kind is inspect.Parameter.KEYWORD_ONLY
    assert params["competition_id"].default is inspect.Parameter.empty


def test_la_gateway_point_in_time_refuse_une_autre_competition():
    """Un backtest construit pour une compétition qui sert un événement d'une autre
    mélange deux populations, et le résultat a l'air normal."""
    from src.agents.quant.betting_engine.calibration.point_in_time_gateway import (
        PointInTimeGateway,
    )

    pit = PointInTimeGateway([], datetime(2025, 9, 1, tzinfo=timezone.utc), L1, "2025")

    assert pit.recent_form(PSG, competition_id=L1, last=5, season="2025") == []
    with pytest.raises(ValueError, match="non interchangeables"):
        pit.recent_form(PSG, competition_id=UCL, last=5, season="2025")


# ── non-régression des ligues déjà supportées ───────────────────────────────────
def test_les_ligues_domestiques_gardent_leur_capability():
    """La capability se choisit sur `event.competition_id` : un événement domestique
    doit rester servi par sa compétition historique, sans détour par l'UEFA."""
    from src.agents.quant.gateway.registries.competition_registry import active_competitions

    domestiques = {c.canonical_id for c in active_competitions("football")}
    for attendu in (L1, "competition:football:eng:premier_league",
                    "competition:football:ita:serie_a"):
        assert attendu in domestiques

    gw = _CompetitionScopedGateway()
    features = build_event_feature_set(_event(L1), gw, as_of=_KICKOFF)
    assert features.participant_features[PSG]["form_matches"] == 5
    assert all(comp == L1 for _, comp in gw.calls)
