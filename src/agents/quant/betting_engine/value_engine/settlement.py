"""L'espérance, écrite une seule fois, pour TOUS les règlements.

Le moteur ne connaissait que deux issues : gagné ou perdu. C'est exact pour un
1X2 et faux dès qu'un marché rembourse — « remboursé si match nul » est
littéralement nommé d'après son PUSH. Avec la formule binaire, la mise rendue est
comptée comme une perte, et l'espérance sort trop basse sans que rien ne le dise.

UNE SEULE PRIMITIVE, ET ELLE EST GÉNÉRIQUE :

    EV = Σ  P(issue) × rendement_net(issue)

`rendement_net` est un tableau, pas une cascade de `if` : ajouter un règlement se
fait en ajoutant une ligne, jamais en écrivant une formule d'EV pour DNB ou pour
les totaux. Une formule par marché, c'est la garantie que deux d'entre elles
divergeront un jour.

RENDEMENTS NETS, POUR UNE MISE UNITAIRE

    WIN            cote − 1     le gain net
    LOSS           −1           la mise
    PUSH / VOID     0           la mise est rendue : ni gain ni perte
    PARTIAL_WIN    (cote−1)/2   moitié gagnante, moitié rendue (lignes quart)
    PARTIAL_LOSS   −0.5         moitié perdante, moitié rendue

Les deux derniers existent pour les handicaps asiatiques à quart de but. Ils sont
DÉCLARÉS mais aucun marché ne les utilise aujourd'hui : le règlement des lignes
quart n'est pas démontré par la source, et les inventer serait exactement ce que
le reste du chantier refuse.

COMPATIBILITÉ STRICTE. Sur un marché à deux issues WIN/LOSS, cette primitive rend
EXACTEMENT `p × cote − 1`, l'ancienne formule — c'est une identité algébrique, et
un test golden l'ancre.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum


class Settlement(str, Enum):
    """Comment une issue se règle, du point de vue du parieur."""

    WIN = "WIN"
    LOSS = "LOSS"
    PUSH = "PUSH"            # mise rendue par la règle du marché (total = ligne)
    VOID = "VOID"            # pari annulé (événement reporté, marché retiré)
    PARTIAL_WIN = "PARTIAL_WIN"
    PARTIAL_LOSS = "PARTIAL_LOSS"


#: Rendement net d'une mise UNITAIRE, par règlement. Un tableau, pas des `if`.
#: `PUSH` et `VOID` partagent le même rendement (0) et restent DISTINCTS : l'un
#: est une règle du marché, l'autre un incident. Les fusionner ferait disparaître
#: la différence des rapports, où elle se lit.
RENDEMENT_NET = {
    Settlement.WIN: lambda cote: cote - 1.0,
    Settlement.LOSS: lambda _cote: -1.0,
    Settlement.PUSH: lambda _cote: 0.0,
    Settlement.VOID: lambda _cote: 0.0,
    Settlement.PARTIAL_WIN: lambda cote: (cote - 1.0) / 2.0,
    Settlement.PARTIAL_LOSS: lambda _cote: -0.5,
}


@dataclass(frozen=True)
class OutcomeShare:
    """Une part de probabilité et le règlement qu'elle produit.

    Les parts d'un pari doivent sommer à 1 : elles décrivent une partition de
    l'univers vu depuis CE pari. `expected_value` le vérifie plutôt que de le
    supposer — une partition incomplète produit une espérance silencieusement
    fausse, et c'est la seule erreur de ce module qui ne se verrait pas.
    """

    probability: float
    settlement: Settlement


def net_return(settlement: Settlement, decimal_odds: float) -> float:
    return RENDEMENT_NET[settlement](decimal_odds)


def expected_value(shares: Sequence[OutcomeShare], decimal_odds: float,
                   *, tolerance: float = 1e-6) -> float:
    """`EV = Σ P(issue) × rendement_net(issue)`. La seule formule du moteur."""
    if decimal_odds is None or decimal_odds <= 1.0:
        raise ValueError(f"cote décimale invalide : {decimal_odds!r}")
    total = sum(s.probability for s in shares)
    if abs(total - 1.0) > tolerance:
        raise ValueError(
            f"les parts de probabilité somment à {total:.6f} et non 1 — "
            "partition incomplète : l'espérance serait fausse sans le dire")
    return sum(s.probability * net_return(s.settlement, decimal_odds) for s in shares)


def binary_shares(win_probability: float) -> tuple[OutcomeShare, ...]:
    """Le cas historique : on gagne ou on perd, rien d'autre."""
    return (OutcomeShare(win_probability, Settlement.WIN),
            OutcomeShare(1.0 - win_probability, Settlement.LOSS))


def push_shares(win: float, push: float, loss: float) -> tuple[OutcomeShare, ...]:
    """Un marché qui REMBOURSE une partie du temps.

    Les trois probabilités sont INCONDITIONNELLES. C'est le point délicat : sur un
    « remboursé si match nul », la probabilité affichée par le modèle et par le
    bookmaker est CONDITIONNELLE au non-nul (elle somme à 1 sur deux issues).
    L'utiliser telle quelle dans la formule binaire compterait le remboursement
    comme une perte. Ici, la partition rend le nul à sa vraie place : rendement
    nul, ni gain ni perte.
    """
    return (OutcomeShare(win, Settlement.WIN),
            OutcomeShare(push, Settlement.PUSH),
            OutcomeShare(loss, Settlement.LOSS))
