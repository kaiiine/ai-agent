"""CLV multi-marché — l'identité du CONTRAT décide de ce qui s'apparie.

La règle : une paire compare la cote de décision et celle de clôture DU MÊME
PARI. « Plus de 2,5 buts » et « plus de 3,5 buts » ne sont pas le même pari ; les
apparier mesurerait la décision du bookmaker de déplacer sa ligne, en la
présentant comme la qualité de notre prix.

La propriété la plus importante de ce lot est une NON-régression : un marché sans
paramètre rend exactement l'identité d'avant, donc l'historique déjà écrit reste
lisible, appariable et compté comme il l'était.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from src.agents.quant.betting_engine.clv.clv import clv_readiness
from src.agents.quant.betting_engine.clv.contract import (
    LINE_MOVEMENT,
    SAME_LINE_PRICE_MOVEMENT,
    classer_mouvement,
    famille_de,
    identite_contrat,
    parametres_de,
)
from src.agents.quant.betting_engine.clv.observation import ObservationPhase, OddsObservation
from src.agents.quant.betting_engine.clv.status_cli import capacite_de, collect_par_capacite
from src.agents.quant.betting_engine.markets.families import MarketFamily

T = datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc)


#: Le coup d'envoi vit DANS l'identité d'événement : la porte d'admissibilité le
#: relit pour vérifier qu'une clôture est bien proche du départ réel. Un
#: identifiant sans horaire sort en `KICKOFF_UNREADABLE` — et c'est le bon
#: comportement, mais il rend le test aveugle. Les fixtures utilisent donc la
#: forme réelle produite par le résolveur.
def _event_id(n: int = 1) -> str:
    coup_envoi = (T + timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return f"event:football:serie_a:{coup_envoi}:away=b{n}|home=a{n}"


#: 175 minutes : la clôture doit tomber dans la FENÊTRE réelle qui précède le
#: coup d'envoi (+3 h ici). À +120 min elle sort en `CLOSING_OUTSIDE_WINDOW` —
#: la règle existante, que ce lot ne touche pas.
def _obs(contrat, selection, cote, phase, *, minutes=0, event=None):
    return OddsObservation(
        event_id=event or _event_id(), market_type=contrat, selection=selection,
        bookmaker="winamax", decimal_odds=Decimal(str(cote)),
        observed_at=T + timedelta(minutes=minutes), phase=phase, source="winamax")


# ── L'identité de contrat ────────────────────────────────────────────────────

def test_un_marche_sans_parametre_garde_l_identite_historique():
    """LA non-régression : `MATCH_WINNER` s'écrit exactement comme avant, donc
    l'historique déjà collecté continue de s'apparier."""
    assert identite_contrat(MarketFamily.MATCH_WINNER) == "MATCH_WINNER"
    assert identite_contrat(MarketFamily.MATCH_WINNER, {}, {}) == "MATCH_WINNER"
    assert identite_contrat(MarketFamily.DOUBLE_CHANCE) == "DOUBLE_CHANCE"


def test_la_ligne_entre_dans_l_identite():
    assert identite_contrat(MarketFamily.TOTALS, {"line": 2.5}) == "TOTALS(line=2.5)"
    assert identite_contrat(MarketFamily.TOTALS, {"line": 3.5}) == "TOTALS(line=3.5)"


def test_le_formatage_ne_cree_pas_deux_contrats():
    """`2.5`, `2.50` et « 2.5 » désignent le même pari. Une différence de
    formatage ne doit pas empêcher deux captures de s'apparier."""
    formes = [identite_contrat(MarketFamily.TOTALS, {"line": v})
              for v in (2.5, 2.50, "2.5", Decimal("2.50"))]
    assert len(set(formes)) == 1


def test_l_identifiant_de_source_ne_fait_pas_partie_du_contrat():
    """`source_family_id` dit d'où vient le marché, pas ce qu'il paie. L'inclure
    ferait cesser l'appariement le jour où la source renumérote ses types."""
    avec = identite_contrat(MarketFamily.TOTALS, {"line": 2.5, "source_family_id": 2749})
    sans = identite_contrat(MarketFamily.TOTALS, {"line": 2.5})
    assert avec == sans


def test_l_identite_se_relit():
    assert famille_de("TOTALS(line=2.5)") == "TOTALS"
    assert parametres_de("TOTALS(line=2.5)") == {"line": "2.5"}
    assert parametres_de("MATCH_WINNER") == {}


# ── Mouvement de ligne vs mouvement de prix ─────────────────────────────────

def test_meme_contrat_cote_differente_est_un_mouvement_de_prix():
    m = classer_mouvement("TOTALS(line=2.5)", "TOTALS(line=2.5)")
    assert m.kind == SAME_LINE_PRICE_MOVEMENT


def test_ligne_deplacee_est_un_mouvement_de_ligne_pas_une_clv():
    m = classer_mouvement("TOTALS(line=2.5)", "TOTALS(line=3.5)")
    assert m.kind == LINE_MOVEMENT
    assert "line" in m.detail and "aucune paire" in m.detail


def test_deux_familles_differentes_ne_sont_pas_un_mouvement():
    assert classer_mouvement("TOTALS(line=2.5)", "MATCH_WINNER") is None


# ── L'appariement lui-même ───────────────────────────────────────────────────

def test_deux_lignes_differentes_ne_forment_jamais_une_paire():
    """Décision sur 2.5, clôture sur 3.5 : le collecteur voit deux contrats, donc
    aucune paire — et surtout pas une CLV flatteuse."""
    lecture = clv_readiness([
        _obs("TOTALS(line=2.5)", "over", "1.90", ObservationPhase.DECISION),
        _obs("TOTALS(line=3.5)", "over", "2.60", ObservationPhase.CLOSING, minutes=175),
    ])
    assert lecture.n_complete_pairs == 0
    assert lecture.status == "NOT_YET_MEASURABLE"


def test_la_meme_ligne_forme_bien_une_paire():
    lecture = clv_readiness([
        _obs("TOTALS(line=2.5)", "over", "1.90", ObservationPhase.DECISION),
        _obs("TOTALS(line=2.5)", "over", "1.78", ObservationPhase.CLOSING, minutes=175),
    ])
    assert lecture.n_complete_pairs == 1
    assert lecture.mean_clv is not None and lecture.mean_clv > 0


def test_deux_selections_du_meme_marche_restent_distinctes():
    """OVER et UNDER sont deux contrats : leurs cotes bougent en sens inverse, et
    les mélanger annulerait le signal."""
    lecture = clv_readiness([
        _obs("TOTALS(line=2.5)", "over", "1.90", ObservationPhase.DECISION),
        _obs("TOTALS(line=2.5)", "under", "1.95", ObservationPhase.CLOSING, minutes=175),
    ])
    assert lecture.n_complete_pairs == 0


# ── Isolation par capacité ───────────────────────────────────────────────────

def test_la_capacite_se_derive_du_contrat():
    assert capacite_de("football", "MATCH_WINNER") == "football.match_winner"
    assert capacite_de("football", "TOTALS(line=2.5)") == "football.totals.line_2_5"
    assert capacite_de("football", "TOTALS(line=1.5)") == "football.totals.line_1_5"


def test_trente_paires_1x2_ne_font_pas_progresser_totals():
    """L'exigence centrale de §9 : la maturité se lit par capacité. Sans cette
    isolation, un marché validé en tirerait un autre qui n'a rien démontré."""
    observations = []
    for i in range(30):
        ev = _event_id(i)
        observations += [
            _obs("MATCH_WINNER", "home", "2.00", ObservationPhase.DECISION, event=ev),
            _obs("MATCH_WINNER", "home", "1.85", ObservationPhase.CLOSING,
                 minutes=175, event=ev)]
    observations += [
        _obs("TOTALS(line=2.5)", "over", "1.90", ObservationPhase.DECISION),
        _obs("TOTALS(line=2.5)", "over", "1.80", ObservationPhase.CLOSING, minutes=175)]

    lignes = {l["capacite"]: l for l in collect_par_capacite(observations, min_events=30)}
    assert lignes["football.match_winner"]["independants"] == 30
    assert lignes["football.totals.line_2_5"]["independants"] == 1
    assert lignes["football.match_winner"]["manque"] == "—"
    assert "de plus" in lignes["football.totals.line_2_5"]["manque"]


def test_le_statut_par_capacite_expose_ce_qui_manque():
    lignes = collect_par_capacite([
        _obs("TOTALS(line=2.5)", "over", "1.90", ObservationPhase.DECISION)],
        min_events=30)
    assert len(lignes) == 1
    ligne = lignes[0]
    for champ in ("capacite", "market_family", "parametres", "decisions", "clotures",
                  "paires", "eligibles", "independants", "mean_clv", "borne_basse",
                  "exclues_par_motif", "statut"):
        assert champ in ligne, champ
    assert ligne["market_family"] == "TOTALS" and ligne["parametres"] == "line=2.5"
    assert ligne["mean_clv"] is None          # jamais 0 en l'absence de mesure


# ── Non-régression du chemin historique ──────────────────────────────────────

def test_le_chemin_match_winner_est_numeriquement_inchange():
    """Mêmes observations qu'avant ce lot, même lecture."""
    observations = [
        _obs("MATCH_WINNER", "home", "2.10", ObservationPhase.DECISION),
        _obs("MATCH_WINNER", "home", "1.95", ObservationPhase.CLOSING, minutes=175)]
    lecture = clv_readiness(observations)
    assert lecture.n_complete_pairs == 1
    assert float(lecture.mean_clv) == pytest.approx(
        float(Decimal("2.10") / Decimal("1.95")) - 1, abs=1e-9)


def test_aucune_ecriture_ni_migration_dans_le_module_de_contrat():
    """Le module ne fait que NOMMER : il ne touche à aucun store."""
    import ast
    import inspect

    from src.agents.quant.betting_engine.clv import contract

    source = inspect.getsource(contract)
    arbre = ast.parse(source)
    # Les IMPORTS disent tout : un module qui ne connaît ni le store, ni le
    # système de fichiers, ne peut rien réécrire. (`append` sur une liste locale
    # n'est pas une écriture — contrôler les appels de méthode serait grossier.)
    importes = {n.module for n in ast.walk(arbre) if isinstance(n, ast.ImportFrom)}
    importes |= {a.name for n in ast.walk(arbre) if isinstance(n, ast.Import)
                 for a in n.names}
    for interdit in ("pathlib", "json", "os", "shutil", ".store", "store"):
        assert interdit not in (importes or set()), interdit
    assert "open(" not in source
