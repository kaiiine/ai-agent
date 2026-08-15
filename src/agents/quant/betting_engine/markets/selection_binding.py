"""Code de sélection bookmaker -> sélection canonique. Par les CODES, jamais les libellés.

Le chemin doit être unique : ce module est celui que le produit ET le banc de
mesure appellent. Deux implémentations parallèles feraient d'une preuve « ça
marche sur les vrais marchés » une propriété du harness.

LES LIBELLÉS NE SONT PAS UNE SOURCE DE VÉRITÉ, et le chantier l'a déjà payé une
fois : « Mi-temps - Vainqueur (remboursé si match nul) » ne porte AUCUN paramètre
de période — la mi-temps n'existe que dans son nom. Ici le principe est le même,
appliqué aux issues : on lit `outcome.code` (« 1 », « x », « 9 », « over »,
« 2:1 »), jamais `outcome.label` (« Cruz Azul », « Plus de 2,5 »). Un libellé
change de langue, d'orthographe et de casse ; un code, non.

LE RÔLE VIENT DU RÉSOLVEUR, PAS DE L'ORDRE D'AFFICHAGE. `slot_1` n'est pas
« l'équipe à domicile » : c'est le premier compétiteur tel que le bookmaker
l'affiche. La traduction slot -> rôle est la seule autorité du
`ParticipantRoleResolver`, et elle est passée ici en argument. Conséquence non
évidente : un score exact « 2:1 » signifie « 2 pour slot_1 », donc doit être
RETOURNÉ quand slot_1 est l'équipe extérieure — sans quoi on price 2-1 pour 1-2.

Une issue non résoluble ne reçoit aucune probabilité : `SELECTION_CANONICALIZATION_FAILED`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..bookmakers.winamax.market_mapping import map_selection_code
from .families import MarketFamily

ECHEC = "SELECTION_CANONICALIZATION_FAILED"

#: Codes de la double chance, mesurés IDENTIQUES sur les 23 marchés observés
#: (4 sports). Chaque code désigne une UNION de deux issues du 1X2, exprimée en
#: SLOTS — la conversion en rôles se fait juste après.
_UNIONS_DOUBLE_CHANCE = {
    "9": ("slot_1", "draw"),
    "10": ("slot_1", "slot_2"),
    "11": ("slot_2", "draw"),
}

#: Nom canonique d'une union, par paire de rôles TRIÉE — l'ordre d'affichage du
#: bookmaker n'entre jamais dans le nom.
_NOM_UNION = {
    ("draw", "home"): "home_or_draw",
    ("away", "home"): "home_or_away",
    ("away", "draw"): "draw_or_away",
}

_CODE_SCORE = re.compile(r"^(\d+):(\d+)$")

#: GRAMMAIRE DU HANDICAP, MESURÉE sur 548 marchés réels (basket 282, football
#: américain 248, baseball 18) :
#:
#:     `hcp` est le handicap appliqué à SLOT_1.
#:     `yes` désigne le compétiteur dont le handicap est NÉGATIF.
#:     `no`  désigne celui dont le handicap est POSITIF.
#:
#: Vérifié contre les libellés : 548/548 sur la VALEUR et le CAMP. Les 31 écarts
#: constatés ne portaient que sur l'orthographe du nom (« L.A. Sparks » pour
#: « Los Angeles Sparks ») — c'est-à-dire exactement la raison pour laquelle un
#: libellé ne peut pas servir de source de vérité.
#:
#: Sans cette règle, le sujet du handicap n'existait que dans le libellé, et un
#: handicap attribué au mauvais camp est une prédiction exactement inversée.
_CODES_HANDICAP = ("yes", "no")


def slot_du_handicap(handicap: float, code: str) -> str | None:
    """Le SLOT que désigne cette issue, d'après le seul signe du handicap.

    `None` sur un handicap NUL : « slot_1 +0 » et « slot_2 −0 » ne se distinguent
    plus, et le signe ne désigne alors plus personne. C'est aussi le cas où le
    règlement d'une égalité exacte serait à deviner — deux raisons de refuser.
    """
    if code not in _CODES_HANDICAP or handicap == 0:
        return None
    if handicap < 0:
        return "slot_1" if code == "yes" else "slot_2"
    return "slot_2" if code == "yes" else "slot_1"


@dataclass(frozen=True)
class SelectionBinding:
    """La liaison code -> sélection canonique, et ce qui n'a pas pu être lié."""

    par_code: dict[str, str] = field(default_factory=dict)
    non_resolus: tuple[str, ...] = ()
    reason: str = ""

    @property
    def complete(self) -> bool:
        return not self.non_resolus

    def canonique(self, code: str) -> str | None:
        return self.par_code.get(code)


def _role(slot: str, roles) -> str | None:
    return "draw" if slot == "draw" else roles.get(slot)


def canonicaliser_selections(*, family: MarketFamily, codes, roles,
                             parameters=None) -> SelectionBinding:
    """`(famille, codes bruts, rôles par slot)` -> sélections canoniques.

    `roles` vient du `ParticipantRoleResolver` : `{"slot_1": "home", "slot_2":
    "away"}` — ou l'inverse. Rien ici ne suppose l'un plutôt que l'autre.

    `parameters` porte les paramètres canoniques du marché. Une seule famille
    s'en sert aujourd'hui — le handicap, dont le camp se lit dans le SIGNE de
    `hcp` et nulle part ailleurs.
    """
    parametres = dict(parameters or {})
    par_code: dict[str, str] = {}
    non_resolus: list[str] = []

    for code in codes:
        brut = (code or "").strip()
        canonique: str | None = None

        if family in (MarketFamily.MATCH_WINNER, MarketFamily.DRAW_NO_BET):
            slot = map_selection_code(brut)
            canonique = _role(slot, roles) if slot != "UNMAPPED" else None

        elif family is MarketFamily.DOUBLE_CHANCE:
            union = _UNIONS_DOUBLE_CHANCE.get(brut)
            if union:
                paire = tuple(sorted(filter(None, (_role(s, roles) for s in union))))
                canonique = _NOM_UNION.get(paire) if len(paire) == 2 else None

        elif family is MarketFamily.EXACT_SCORE:
            if brut == "other":
                canonique = "other"
            else:
                trouve = _CODE_SCORE.match(brut)
                if trouve and roles.get("slot_1") in ("home", "away"):
                    a, b = trouve.groups()
                    # « a:b » compte pour slot_1:slot_2. La forme canonique est
                    # TOUJOURS domicile:extérieur.
                    canonique = f"{a}:{b}" if roles["slot_1"] == "home" else f"{b}:{a}"

        elif family in (MarketFamily.TOTALS, MarketFamily.TEAM_TOTALS):
            # `over` / `under` sont déjà canoniques : ils ne désignent aucun
            # compétiteur, donc aucun rôle à résoudre. Le SUJET d'un total
            # d'équipe, lui, vit dans les paramètres (`side`), pas dans l'issue.
            canonique = brut if brut in ("over", "under") else None

        elif family is MarketFamily.HANDICAP:
            # Le camp vient du SIGNE de `hcp`, jamais du libellé. Sans handicap
            # numérique, aucune issue n'est attribuable — et une issue attribuée
            # au mauvais camp est une prédiction exactement inversée.
            handicap = parametres.get("handicap")
            if isinstance(handicap, (int, float)):
                slot = slot_du_handicap(float(handicap), brut)
                canonique = _role(slot, roles) if slot else None

        if canonique is None:
            non_resolus.append(brut)
        else:
            par_code[brut] = canonique

    if non_resolus:
        return SelectionBinding(
            par_code, tuple(non_resolus),
            f"{ECHEC} : codes non résolus pour {family.value} -> {sorted(set(non_resolus))}. "
            "Aucune probabilité ne peut être attribuée à une issue dont on ignore "
            "ce qu'elle désigne.")
    return SelectionBinding(par_code, (), "")
