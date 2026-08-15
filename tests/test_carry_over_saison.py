"""Le report de saison : ce qu'il rend possible, et ce qu'il ne doit jamais faire.

La frontière de saison remettait la forme à zéro. Mesuré sur un rejeu de sept
championnats et deux ouvertures : à la première journée, ZÉRO rencontre sur 47
était évaluable, et `data_quality` restait à 0,500 pendant deux mois.

Le report retenu est le candidat B du benchmark — le minimal démontré : la forme
prend les `last` derniers matchs de LA MÊME COMPÉTITION, saison précédente
comprise, et la saison précédente disparaît d'elle-même dès que la saison en
cours remplit la fenêtre. Aucun paramètre, aucun calendrier, aucune décroissance.

Ces tests portent surtout sur les quatre choses qu'il ne doit PAS faire :
fabriquer un historique à un promu, traverser une compétition, lire un match
postérieur à la décision, ou continuer d'agir une fois la fenêtre pleine.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.agents.quant.gateway import gateway as gw
from src.agents.quant.gateway.sports.football.canonical_facts import CanonicalMatch

_LIGUE = "competition:football:fra:ligue1"
_A, _B, _PROMU = "team:football:fra:a", "team:football:fra:b", "team:football:fra:promu"


def _match(jour: str, dom: str, ext: str, bd=1, be=0) -> CanonicalMatch:
    return CanonicalMatch(
        canonical_match_id=f"m:{jour}:{dom}:{ext}",
        league_id=_LIGUE, season="x",
        kickoff=datetime.fromisoformat(f"{jour}T20:00:00+00:00"),
        status="FINISHED", home_team_id=dom, away_team_id=ext,
        goals_home=bd, goals_away=be)


@pytest.fixture
def pools(monkeypatch):
    """Deux saisons servies par la gateway, sans réseau."""
    contenu: dict[str, list] = {"2026": [], "2025": []}
    appels: list[tuple[str, str]] = []

    def faux_resultats(competition_id: str, saison: str):
        appels.append((competition_id, saison))
        return list(contenu.get(saison, []))

    monkeypatch.setattr(gw, "_resultats", faux_resultats)
    return contenu, appels


# ══ Ce que le report rend possible ══════════════════════════════════════════
def test_la_frontiere_de_saison_ne_remet_plus_la_forme_a_zero(pools):
    """Le cas mesuré en production : Angers-Lille, pool 2026 vide, pool 2025 à
    306 matchs. Avant, la rencontre s'abstenait faute de forme ; après, elle a
    dix matchs."""
    contenu, _ = pools
    contenu["2025"] = [_match(f"2025-1{i % 2}-0{i % 9 + 1}", _A, _B) for i in range(20)]

    forme = gw.recent_form(_A, competition_id=_LIGUE, last=10, season="2026")

    assert len(forme) == 10
    assert {f["season"] for f in forme} == {"2025"}


def test_chaque_entree_porte_la_saison_dont_elle_vient(pools):
    """Estampiller un match de N-1 avec la saison N enverrait chercher le
    classement de la mauvaise année — silencieusement."""
    contenu, _ = pools
    contenu["2026"] = [_match("2026-08-10", _A, _B)]
    contenu["2025"] = [_match("2025-05-0" + str(i + 1), _A, _B) for i in range(9)]

    forme = gw.recent_form(_A, competition_id=_LIGUE, last=10, season="2026")

    assert len(forme) == 10
    assert forme[0]["season"] == "2026"                 # le plus récent
    assert [f["season"] for f in forme[1:]] == ["2025"] * 9


def test_la_fusion_respecte_l_ordre_du_temps(pools):
    """La fenêtre reste « les dix derniers matchs ». Aucun code ne décide combien
    viennent de quelle saison — c'est la date qui tranche."""
    contenu, _ = pools
    contenu["2026"] = [_match("2026-08-05", _A, _B), _match("2026-08-12", _A, _B)]
    contenu["2025"] = [_match("2025-05-20", _A, _B)]

    forme = gw.recent_form(_A, competition_id=_LIGUE, last=10, season="2026")

    dates = [f["date"] for f in forme]
    assert dates == sorted(dates, reverse=True)
    assert dates[0] == "2026-08-12"


# ══ La transition est mécanique, jamais calendaire ══════════════════════════
def test_la_saison_precedente_disparait_quand_la_fenetre_est_pleine(pools):
    """« dès que 10 matchs de N existent, N-1 disparaît mécaniquement ». Et
    surtout : plus aucun appel à la saison précédente n'est fait."""
    contenu, appels = pools
    contenu["2026"] = [_match(f"2026-09-{i + 10}", _A, _B) for i in range(12)]
    contenu["2025"] = [_match("2025-05-20", _A, _B)]
    appels.clear()

    forme = gw.recent_form(_A, competition_id=_LIGUE, last=10, season="2026")

    assert {f["season"] for f in forme} == {"2026"}
    assert appels == [(_LIGUE, "2026")], "aucun appel à N-1 quand la fenêtre est pleine"


def test_aucun_seuil_de_journee_n_existe(pools):
    """Il n'y a pas de règle « report jusqu'à la cinquième journée ». Le report
    s'arrête exactement quand la fenêtre se remplit, quelle que soit la date."""
    contenu, _ = pools
    contenu["2025"] = [_match(f"2025-05-{i + 1:02d}", _A, _B) for i in range(15)]

    for n_matchs_saison_n in range(0, 12):
        contenu["2026"] = [_match(f"2026-09-{i + 1:02d}", _A, _B)
                           for i in range(n_matchs_saison_n)]
        forme = gw.recent_form(_A, competition_id=_LIGUE, last=10, season="2026")
        depuis_n = sum(1 for f in forme if f["season"] == "2026")
        assert depuis_n == min(n_matchs_saison_n, 10)
        assert len(forme) == 10


# ══ Ce que le report ne doit JAMAIS faire ═══════════════════════════════════
def test_un_promu_ne_recoit_aucun_historique(pools):
    """Mesuré en production : Arsenal reçoit dix matchs de 2025, Coventry — promu
    — en reçoit zéro. Transférer une force d'une division à l'autre supposerait
    un rapport d'échelle entre elles, que rien ne mesure."""
    contenu, _ = pools
    contenu["2025"] = [_match(f"2025-05-{i + 1:02d}", _A, _B) for i in range(15)]

    assert gw.recent_form(_PROMU, competition_id=_LIGUE, last=10, season="2026") == []
    assert len(gw.recent_form(_A, competition_id=_LIGUE, last=10, season="2026")) == 10


def test_le_report_ne_traverse_jamais_une_competition(pools):
    """Un match de Ligue 1 nourrit la Ligue 1, jamais la Ligue des Champions."""
    contenu, appels = pools
    contenu["2025"] = [_match("2025-05-20", _A, _B)]
    appels.clear()

    gw.recent_form(_A, competition_id=_LIGUE, last=10, season="2026")

    assert {comp for comp, _ in appels} == {_LIGUE}


def test_une_etiquette_de_saison_non_numerique_ne_reporte_rien(pools):
    """Sans année lisible, il n'y a pas de « saison précédente » — et on ne la
    devine pas."""
    contenu, _ = pools
    contenu["2025"] = [_match("2025-05-20", _A, _B)]

    assert gw.saison_precedente("2026-27") is None
    assert gw.recent_form(_A, competition_id=_LIGUE, last=10, season="2026-27") == []


def test_une_saison_precedente_indisponible_laisse_le_comportement_inchange(pools):
    """Si le fournisseur n'a pas N-1, on ne fabrique rien : c'est exactement le
    comportement d'avant. Mesuré en production sur l'Eredivisie et la Primeira
    Liga, dont le pool 2025 est vide."""
    contenu, _ = pools
    contenu["2026"] = [_match("2026-08-10", _A, _B)]
    contenu["2025"] = []

    forme = gw.recent_form(_A, competition_id=_LIGUE, last=10, season="2026")

    assert len(forme) == 1 and forme[0]["season"] == "2026"


# ══ §4 — anti-fuite au passage N-1 -> N ═════════════════════════════════════
def test_le_point_in_time_tient_avec_les_deux_saisons_dans_le_pool():
    """Le rejeu sert les deux saisons à la gateway point-in-time. Le filtre
    `kickoff < cutoff` STRICT doit continuer de valoir — sans quoi le report
    ouvrirait une fenêtre sur l'avenir au moment précis où on croit combler le
    passé."""
    from src.agents.quant.betting_engine.calibration.point_in_time_gateway import (
        PointInTimeGateway,
    )

    precedente = [_match("2025-05-20", _A, _B)]
    courante = [_match("2026-08-10", _A, _B), _match("2026-08-17", _A, _B),
                _match("2026-08-24", _A, _B)]
    cutoff = datetime.fromisoformat("2026-08-17T20:00:00+00:00")

    pit = PointInTimeGateway(precedente + courante, cutoff=cutoff,
                             league_id=_LIGUE, season="2026")
    forme = pit.recent_form(_A, competition_id=_LIGUE, last=10, season="2026")

    dates = {f["date"] for f in forme}
    assert dates == {"2025-05-20", "2026-08-10"}
    assert "2026-08-17" not in dates, "le match évalué ne doit jamais se voir"
    assert "2026-08-24" not in dates, "aucun match postérieur ne doit entrer"


def test_le_report_n_introduit_aucun_match_plus_recent_que_la_saison_en_cours(pools):
    """Une inversion de dates ferait passer un match de N-1 devant un match de N,
    et le classement adverse serait alors cherché sur la mauvaise saison."""
    contenu, _ = pools
    contenu["2026"] = [_match("2026-08-10", _A, _B)]
    contenu["2025"] = [_match("2025-05-20", _A, _B), _match("2025-04-01", _A, _B)]

    forme = gw.recent_form(_A, competition_id=_LIGUE, last=10, season="2026")

    plus_recent_n = max(f["date"] for f in forme if f["season"] == "2026")
    assert all(f["date"] <= plus_recent_n for f in forme)


# ══ §8 — non-régression ═════════════════════════════════════════════════════
def test_aucun_bonus_de_qualite_n_est_fabrique():
    """§5 : la qualité doit rester dérivée des features réellement disponibles.
    Aucun compteur du type `carry_over_present` n'existe."""
    import inspect

    from src.agents.quant.betting_engine.sports.football.market_models import one_x_two

    source = inspect.getsource(one_x_two)
    for interdit in ("carry_over", "carryover", "report_saison"):
        assert interdit not in source
    # Le report ne touche à aucun compteur de qualité : il ne fait que servir
    # une population de matchs plus large au constructeur de features.
    from src.agents.quant.betting_engine.sports.football.feature_engineering import (
        event_features,
    )
    assert "carry" not in inspect.getsource(event_features).lower()


def test_les_autres_sports_ne_passent_pas_par_cette_gateway():
    """Le report est une propriété du football. Les six autres sports lisent
    leurs propres corpus embarqués et ne peuvent pas être touchés."""
    from src.agents.quant.betting_engine.sports.registry import SPORT_MODULES

    for nom, module in SPORT_MODULES.items():
        if nom == "football":
            continue
        source = str(getattr(module.build_feature_set, "__module__", ""))
        assert "gateway.gateway" not in source, nom


def test_aucune_formule_economique_n_est_touchee():
    """Le chantier cold-start ne modifie ni EV, ni Kelly, ni CLV, ni un seuil."""
    import inspect

    from src.agents.quant.betting_engine.value_engine import expected_value
    from src.agents.quant.betting_engine.value_engine.bet_policy import (
        default_bet_decision_policy,
    )
    from src.agents.quant.betting_engine.maturity import load_maturity_policy

    assert "carry" not in inspect.getsource(expected_value).lower()
    politique = default_bet_decision_policy()
    assert politique.min_data_quality == 0.70
    assert load_maturity_policy().criteria["max_calibration_error"] == 0.05
