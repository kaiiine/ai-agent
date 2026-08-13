"""`probability_low` mesuré PAR CAPACITÉ — jamais emprunté à une autre.

Une borne basse est ce que le sizing traite comme prudent. Servir à un
« Plus de 4,5 buts » la borne mesurée sur un 1X2, ou à la ligne 1.5 celle de la
ligne 4.5, revient à présenter comme prudente une quantité mesurée sur un autre
marché — avec d'autres fréquences de base et une autre calibration.

Ces tests vérifient trois choses, dans cet ordre d'importance :

1. l'invariant `0 ≤ probability_low ≤ fair_probability ≤ 1`, toujours ;
2. l'absence de borne se dit `NOT_ESTIMATED` (`None`), jamais
   `probability_low = fair_probability` — le faux substitut prudent ;
3. deux capacités différentes rendent des bornes différentes, ce qui prouve
   qu'aucune n'est empruntée.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.agents.quant.betting_engine.markets.capability import identite_capacite
from src.agents.quant.betting_engine.markets.families import MarketFamily
from src.agents.quant.betting_engine.sports.football.market_models.derived import (
    FootballDerivedPricer,
)
from src.agents.quant.betting_engine.uncertainty import (
    MIN_ECHANTILLON,
    N_TRANCHES,
    bins_for_capability,
)

CAPACITES = (
    "football.one_x_two.dixon_coles.v0",
    "football.double_chance.dixon_coles.v0",
    "football.draw_no_bet.dixon_coles.v0",
    "football.exact_score.dixon_coles.v0",
    *[f"football.totals_line_{str(l).replace('.', '_')}.dixon_coles.v0"
      for l in (1.5, 2.5, 3.5, 4.5, 5.5)],
)

SUPPORT_SCORE = tuple(
    f"{x}:{y}" for y in range(6) for x in range(6) if (x, y) != (5, 5)) + ("other",)

MARCHES = [
    (MarketFamily.MATCH_WINNER, {}),
    (MarketFamily.DOUBLE_CHANCE, {"source_family_id": 3072}),
    (MarketFamily.DRAW_NO_BET, {"source_family_id": 3535}),
    (MarketFamily.EXACT_SCORE, {"source_family_id": 2643}),
    *[(MarketFamily.TOTALS, {"line": l, "source_family_id": 2749})
      for l in (1.5, 2.5, 3.5, 4.5, 5.5)],
]


class _Participant:
    def __init__(self, role, cid):
        self.role, self.canonical_id = role, cid


class _Event:
    event_id = "event:football:borne"
    participants = (_Participant("home", "team:h"), _Participant("away", "team:a"))


class _Features:
    def __init__(self, attaque=1.25, defense=0.88):
        self.participant_features = {
            "team:h": {"attack_strength": attaque, "defense_strength": defense},
            "team:a": {"attack_strength": 0.92, "defense_strength": 1.12}}
        self.missing_features = set()
        self.as_of = datetime(2026, 8, 1, tzinfo=timezone.utc)


def _contexte(features=None):
    return {"features": features or _Features(),
            "point_in_time": datetime(2026, 8, 2, tzinfo=timezone.utc),
            "offered_selections": SUPPORT_SCORE}


# ── Les tables existent, par capacité ────────────────────────────────────────

@pytest.mark.parametrize("version", CAPACITES)
def test_chaque_capacite_a_sa_propre_table(version):
    tables = bins_for_capability(version)
    assert tables is not None, version
    assert sum(tables.total) > 0


def test_les_lignes_ne_partagent_pas_leur_table():
    """Une borne de TOTALS 1.5 servie à un TOTALS 4.5 serait mesurée sur un autre
    marché : ni la même fréquence de base, ni la même calibration."""
    tables = {l: bins_for_capability(
        f"football.totals_line_{str(l).replace('.', '_')}.dixon_coles.v0")
        for l in (1.5, 2.5, 3.5, 4.5, 5.5)}
    empreintes = {l: t.total for l, t in tables.items()}
    assert len(set(empreintes.values())) == len(empreintes), (
        "deux lignes partagent la même distribution de tranches")


def test_une_capacite_inconnue_ne_fabrique_pas_de_table():
    assert bins_for_capability("football.inexistant.v0") is None
    assert bins_for_capability("football.totals_line_0_5.dixon_coles.v0") is None


# ── L'invariant, sur des marchés réellement pricés ───────────────────────────

@pytest.mark.parametrize("famille,params", MARCHES)
def test_invariant_borne_inferieure_ou_egale_a_la_probabilite(famille, params):
    prix = FootballDerivedPricer().price(
        event=_Event(), family=famille, parameters=params, context=_contexte())
    assert prix.priced
    for s in prix.selections:
        assert 0.0 <= s.fair_probability <= 1.0
        if s.probability_low is not None:
            assert 0.0 <= s.probability_low <= s.fair_probability <= 1.0, s.selection


@pytest.mark.parametrize("profil", [(1.25, 0.88), (0.8, 1.3), (1.7, 0.6), (1.0, 1.0)])
def test_l_invariant_tient_sur_des_profils_de_match_varies(profil):
    contexte = _contexte(_Features(*profil))
    for famille, params in MARCHES:
        prix = FootballDerivedPricer().price(
            event=_Event(), family=famille, parameters=params, context=contexte)
        for s in prix.selections:
            if s.probability_low is not None:
                assert 0.0 <= s.probability_low <= s.fair_probability <= 1.0


# ── L'absence se dit, elle ne se remplace pas ────────────────────────────────

@pytest.mark.parametrize("version", CAPACITES)
def test_une_tranche_sous_le_seuil_rend_non_estimee_et_non_le_point(version):
    """Le faux substitut prudent : rendre `fair_probability` comme borne. Une
    tranche sans effectif suffisant ne mesure rien, et une absence n'est pas une
    mesure — qu'elle soit vide ou simplement trop maigre."""
    tables = bins_for_capability(version)
    sous_le_seuil = [i for i in range(N_TRANCHES) if tables.total[i] < MIN_ECHANTILLON]
    assert sous_le_seuil, f"{version} : toutes les tranches sont peuplées"
    for indice in sous_le_seuil:
        centre = (indice + 0.5) / N_TRANCHES
        assert tables.borne_basse(centre) is None, (version, indice, tables.total[indice])


def test_le_pricer_expose_l_absence_sans_la_combler():
    """Sur un marché réel, certaines issues n'ont pas de borne mesurable. Elles
    doivent sortir à `None`, pas au point."""
    vues = []
    for famille, params in MARCHES:
        prix = FootballDerivedPricer().price(
            event=_Event(), family=famille, parameters=params, context=_contexte())
        vues += [(s.probability_low, s.fair_probability) for s in prix.selections]

    assert any(low is None for low, _ in vues), "aucune absence : le test ne prouve rien"
    for low, fair in vues:
        if low is not None:
            # Une borne ÉGALE au point est permise (l'historique bat la prédiction),
            # mais elle doit alors venir d'une tranche réellement mesurée.
            assert low <= fair


# ── La borne est honnête : mesurée, pas décorative ───────────────────────────

@pytest.mark.parametrize("version", CAPACITES)
def test_la_borne_est_couverte_par_la_frequence_observee(version):
    """Dans chaque tranche assez peuplée, la fréquence réellement observée doit
    atteindre la borne annoncée. C'est la définition d'une borne honnête."""
    tables = bins_for_capability(version)
    mesurees = [i for i in range(N_TRANCHES) if tables.total[i] >= MIN_ECHANTILLON]
    assert mesurees, version
    for indice in mesurees:
        centre = (indice + 0.5) / N_TRANCHES
        borne = tables.borne_basse(centre)
        empirique = tables.succes[indice] / tables.total[indice]
        assert empirique >= borne - 1e-9, (version, indice, empirique, borne)


def test_aucune_constante_de_prudence_dans_le_calcul():
    """La borne ne doit pas être `fair − constante` : ce serait une pénalité
    forfaitaire déguisée en mesure. On le vérifie sur l'écart, qui doit VARIER
    d'une tranche à l'autre."""
    tables = bins_for_capability("football.double_chance.dixon_coles.v0")
    ecarts = []
    for indice in range(N_TRANCHES):
        if tables.total[indice] < MIN_ECHANTILLON:
            continue
        centre = (indice + 0.5) / N_TRANCHES
        ecarts.append(round(centre - tables.borne_basse(centre), 4))
    assert len(set(ecarts)) > 1, f"écart constant = pénalité forfaitaire : {ecarts}"
