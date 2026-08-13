"""Moteur économique settlement-aware — une seule primitive, zéro régression.

Le test qui compte est le GOLDEN : sur un marché WIN/LOSS, la nouvelle primitive
doit rendre EXACTEMENT ce que rendait l'ancienne. Toute la valeur du refactor
tient là — si les deux divergent d'un centième, chaque décision économique déjà
prise devient suspecte.

Le reste vérifie ce que l'ancienne formule ne SAVAIT PAS dire : un marché qui
rembourse. « Remboursé si match nul » est nommé d'après son PUSH, et la formule
binaire le comptait en perte.
"""

from __future__ import annotations

import pytest

from src.agents.quant.betting_engine.value_engine.expected_value import ev as ev_historique
from src.agents.quant.betting_engine.value_engine.settlement import (
    OutcomeShare,
    Settlement,
    binary_shares,
    expected_value,
    net_return,
    push_shares,
)


# ── GOLDEN : l'ancien comportement est intact ────────────────────────────────

@pytest.mark.parametrize("p", [0.01, 0.1, 0.25, 0.3333333, 0.5, 0.66, 0.9, 0.99])
@pytest.mark.parametrize("cote", [1.01, 1.5, 1.91, 2.0, 2.75, 3.4, 10.0, 51.0])
def test_golden_ev_binaire_identique_a_l_ancienne_formule(p, cote):
    """`Σ P × rendement` == `p × cote − 1`, à la précision de la machine.

    Ce n'est pas une approximation : c'est une identité algébrique
    (p(c−1) + (1−p)(−1) = pc − 1). Le test l'ancre pour que personne ne
    « simplifie » l'un des deux côtés un jour."""
    nouveau = expected_value(binary_shares(p), cote)
    assert nouveau == pytest.approx(ev_historique(p, cote), abs=1e-12)


def test_golden_sur_les_valeurs_du_seuil_de_decision():
    """Aux abords du seuil, une dérive d'arrondi changerait des décisions."""
    from src.agents.quant.betting_engine.value_engine.expected_value import (
        EV_THRESHOLD,
        minimum_odds_for_value,
    )

    for p in (0.2, 0.35, 0.5, 0.75):
        cote = minimum_odds_for_value(p)
        assert expected_value(binary_shares(p), cote) == pytest.approx(
            ev_historique(p, cote), abs=1e-12)
        # …et la cote minimale atteint bien le seuil, des deux côtés.
        assert expected_value(binary_shares(p), cote) >= EV_THRESHOLD - 1e-3


# ── Ce que la formule binaire ne savait pas dire ──────────────────────────────

def test_le_push_ne_coute_ni_ne_rapporte():
    assert net_return(Settlement.PUSH, 2.0) == 0.0
    assert net_return(Settlement.VOID, 7.5) == 0.0
    assert net_return(Settlement.WIN, 2.0) == 1.0
    assert net_return(Settlement.LOSS, 2.0) == -1.0


def test_un_marche_qui_rembourse_n_est_pas_un_marche_binaire():
    """Le cas réel du « remboursé si match nul », chiffré — et il fait basculer
    une décision.

    Modèle : P(home)=0,45, P(nul)=0,27, P(away)=0,28, inconditionnelles. La
    probabilité AFFICHÉE d'un DNB est CONDITIONNELLE au non-nul : 0,45/0,73 =
    0,6164. Passée telle quelle dans la formule binaire, elle décrit une espérance
    par unité EXPOSÉE, pas par unité MISÉE — elle oublie que 27 % du temps la mise
    revient sans gain, alors qu'elle a bien été immobilisée.

    Le rapport exact est `EV_misée = (1 − P(push)) × EV_exposée`. Ici 0,0440 contre
    0,0602 : le traitement naïf SURESTIME de 37 %. Et comme `EV_THRESHOLD` vaut
    0,06, il fait passer pour misable un pari qui ne l'est pas.
    """
    from src.agents.quant.betting_engine.value_engine.expected_value import EV_THRESHOLD

    p_home, p_nul, p_away = 0.45, 0.27, 0.28
    conditionnelle = p_home / (p_home + p_away)
    cote = 1.72

    juste = expected_value(push_shares(p_home, p_nul, p_away), cote)
    naif = ev_historique(conditionnelle, cote)

    assert juste == pytest.approx(0.45 * 0.72 + 0.27 * 0.0 + 0.28 * -1.0, abs=1e-12)
    assert juste == pytest.approx((1 - p_nul) * naif, abs=1e-12)   # la relation exacte
    assert naif > juste, "la conditionnelle surestime l'espérance par unité misée"
    # La bascule de décision, mesurée : au-dessus du seuil d'un côté, en dessous
    # de l'autre. C'est ce que la formule binaire aurait laissé passer.
    assert naif > EV_THRESHOLD > juste


def test_une_partition_incomplete_est_refusee_et_non_devinee():
    """Une somme de probabilités ≠ 1 produirait une espérance silencieusement
    fausse : c'est la seule erreur de ce module qui ne se verrait pas."""
    with pytest.raises(ValueError, match="partition incomplète"):
        expected_value((OutcomeShare(0.4, Settlement.WIN),
                        OutcomeShare(0.4, Settlement.LOSS)), 2.0)


def test_une_cote_invalide_est_refusee():
    for cote in (None, 1.0, 0.5, -2.0):
        with pytest.raises(ValueError):
            expected_value(binary_shares(0.5), cote)


def test_les_reglements_partiels_sont_declares_mais_inutilises():
    """Déclarés pour les lignes quart, dont le règlement n'est PAS démontré par
    la source. Les exposer sans les utiliser vaut mieux que de les inventer le
    jour où un marché en aura besoin."""
    assert net_return(Settlement.PARTIAL_WIN, 3.0) == 1.0      # (3−1)/2
    assert net_return(Settlement.PARTIAL_LOSS, 3.0) == -0.5

    from src.agents.quant.betting_engine.sports.football.market_models import derived

    source = __import__("pathlib").Path(derived.__file__).read_text(encoding="utf-8")
    assert "PARTIAL_WIN" not in source, "aucun marché ne doit s'en servir aujourd'hui"


# ── Une seule formule dans tout le moteur ────────────────────────────────────

def test_aucune_formule_d_ev_specifique_a_un_marche():
    """`EV = Σ P × rendement` doit rester la SEULE. Une formule par famille est
    la garantie que deux d'entre elles divergeront."""
    import pathlib
    import re

    racine = pathlib.Path(__file__).resolve().parent.parent / "src" / "agents" / "quant"
    autorises = {"ev_engine.py", "expected_value.py", "settlement.py"}
    suspects = []
    # Une multiplication proba × cote suivie d'un « − 1 » : la formule binaire
    # réécrite à la main quelque part.
    motif = re.compile(r"\*\s*(?:decimal_)?odds?\s*(?:\)\s*)?-\s*1\b")
    for fichier in racine.rglob("*.py"):
        if fichier.name in autorises:
            continue
        for i, ligne in enumerate(fichier.read_text(encoding="utf-8").splitlines(), 1):
            if motif.search(ligne) and not ligne.strip().startswith("#"):
                suspects.append(f"{fichier.name}:{i}")
    assert not suspects, "formule d'EV réécrite hors du moteur :\n" + "\n".join(suspects)
