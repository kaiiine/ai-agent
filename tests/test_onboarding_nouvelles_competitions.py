"""Ouvrir la couverture sans ouvrir la porte à de la fausse couverture.

« Toutes les compétitions » voulait dire « les 8 championnats codés au départ ».
Trois compétitions sont accessibles gratuitement (football-data.org, sondé le
2026-08-13) et sont désormais enregistrées :

    BSA  Campeonato Brasileiro Série A   ligue domestique     1 355 rencontres
    CL   UEFA Champions League           INTER-LIGUES           503 rencontres
    CLI  Copa Libertadores               INTER-LIGUES           591 rencontres

Enregistrer une identité N'EST PAS rendre une compétition évaluable. Les deux
compétitions inter-ligues restent sans modèle applicable : le 1X2 domestique est
calibré PAR championnat, et lui servir un PSG–Aston Villa comparerait deux
échelles sans preuve qu'elles le soient.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.agents.quant.betting_engine.acquisition.football_data_org import (
    COMPETITIONS,
    identite_equipe,
    parse_matches,
    vers_canonique,
)

_BRUT = [{
    "id": 1, "utcDate": "2026-08-09T20:00:00Z", "status": "FINISHED",
    "season": {"startDate": "2026-01-28"},
    "homeTeam": {"id": 10, "name": "CR Flamengo"},
    "awayTeam": {"id": 20, "name": "São Paulo FC"},
    "score": {"fullTime": {"home": 2, "away": 1}},
}]


# ── Conversion provider → canonique ─────────────────────────────────────────

def test_une_rencontre_terminee_devient_canonique():
    canon = vers_canonique(parse_matches(_BRUT, "BSA"), scope="bra")

    assert len(canon) == 1
    assert canon[0].league_id == "competition:football:bra:serie_a"
    assert canon[0].goals_home == 2 and canon[0].goals_away == 1


def test_une_rencontre_sans_score_est_ecartee():
    """La garder avec des buts à `None` ferait entrer un 0-0 fantôme dans le
    premier calcul qui somme des buts."""
    prevu = [{**_BRUT[0], "status": "SCHEDULED",
              "score": {"fullTime": {"home": None, "away": None}}}]

    assert vers_canonique(parse_matches(prevu, "BSA"), scope="bra") == []


def test_une_rencontre_sans_les_deux_camps_est_ecartee():
    incomplet = [{**_BRUT[0], "awayTeam": {}}]

    assert parse_matches(incomplet, "BSA") == []


def test_l_identite_d_equipe_ne_depend_pas_du_provider():
    """Un slug bâti sur l'identifiant provider créerait un doublon d'équipe au
    premier changement de source."""
    assert identite_equipe("bra", "São Paulo FC") == "team:football:bra:sao_paulo_fc"
    assert identite_equipe("bra", "CR Flamengo") == "team:football:bra:cr_flamengo"


def test_les_accents_ne_produisent_pas_deux_identites():
    assert identite_equipe("bra", "Grêmio FBPA") == identite_equipe("bra", "Gremio FBPA")


def test_le_point_in_time_est_preserve_par_la_conversion():
    """Le walk-forward trie par coup d'envoi : un horodatage naïf y casserait la
    comparaison, donc la garantie de non-fuite."""
    canon = vers_canonique(parse_matches(_BRUT, "BSA"), scope="bra")

    assert canon[0].kickoff.tzinfo is not None
    assert canon[0].kickoff == datetime(2026, 8, 9, 20, tzinfo=timezone.utc)


# ── Identité enregistrée ≠ modèle disponible ───────────────────────────────

@pytest.mark.parametrize("canonical_id", [
    "competition:football:bra:serie_a",
    "competition:football:eur:champions_league",
    "competition:football:sam:libertadores",
])
def test_les_trois_competitions_sont_resolvables(canonical_id):
    from src.agents.quant.gateway.registries.competition_registry import COMPETITIONS as REG

    assert canonical_id in REG


@pytest.mark.parametrize("canonical_id", [
    "competition:football:eur:champions_league",
    "competition:football:sam:libertadores",
])
def test_une_competition_inter_ligues_est_typee_coupe_pas_championnat(canonical_id):
    """Le type porte l'information qui interdit d'y appliquer le modèle domestique
    par simple ressemblance."""
    from src.agents.quant.gateway.registries.competition_registry import COMPETITIONS as REG

    assert REG[canonical_id].competition_type == "cup"


def test_resolver_une_competition_ne_cree_aucun_modele():
    """`COMPETITION_RESOLVED` et `MODEL_AVAILABLE` sont deux axes. Les confondre
    servirait un modèle Ligue 1 à une rencontre de Ligue des Champions — le bug
    exact que `test_competition_scoped_features` documente."""
    from src.agents.quant.betting_engine.sports.football.manifest import is_market_supported

    # Le manifeste football ne connaît QUE des types de marché, jamais des
    # compétitions : rien n'y devient évaluable parce qu'une identité est née.
    import inspect

    source = inspect.getsource(is_market_supported)

    assert "competition" not in source.lower()


def test_le_code_provider_pointe_vers_le_canonique_pas_l_inverse():
    assert COMPETITIONS["BSA"] == "competition:football:bra:serie_a"
    assert COMPETITIONS["CL"] == "competition:football:eur:champions_league"
    assert COMPETITIONS["CLI"] == "competition:football:sam:libertadores"


def test_aucune_cle_api_n_est_requise_pour_convertir():
    """La conversion doit rester testable hors ligne : mêler réseau et parsing
    rendrait le benchmark dépendant d'un quota."""
    import inspect

    from src.agents.quant.betting_engine.acquisition import football_data_org

    for fonction in (football_data_org.parse_matches, football_data_org.vers_canonique):
        assert "requests" not in inspect.getsource(fonction)
