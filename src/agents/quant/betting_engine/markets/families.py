"""Deuxième étape : **canonicaliser** — nommer une famille SEULEMENT si la
capture le démontre.

Une famille n'est pas un nom trouvé dans un libellé. C'est une conjonction
vérifiable dans le payload : la forme déclarée par la source (`template`), le
nombre de sélections, et la présence d'un paramètre typé. Chaque règle ci-dessous
a été mesurée sur une capture réelle (29 sports, 98 événements, 5 964 marchés) et
porte son décompte. Ce qui ne se démontre pas reste `UNMAPPED`, avec son
`betType`, son libellé et ses sélections d'origine — visible, jamais deviné.

CE QUE LA MESURE A ÉTABLI

    OverUnder            1 349 marchés, TOUS avec `total` numérique, TOUS à 2 issues
    asian_handicap*        617 marchés, TOUS avec `hcp` numérique, TOUS à 2 issues
    `hcp`                  n'apparaît sur AUCUN autre template
    `total`                apparaît AUSSI sur dynamic/ListOdd/List (2 297 fois) —
                           mais en listes de 1 à 6 issues : ce ne sont pas des
                           Plus/Moins. La ligne seule ne prouve donc rien ; c'est
                           la CONJONCTION (template + 2 issues + ligne) qui prouve.

CE QUE LA MESURE A INFIRMÉ

`map_market` (chemin historique) renvoie `OUTRIGHT_WINNER` pour TOUT template
`ListOdd`. Sur la capture, cela couvre 1 263 marchés dont 624 portent
`players|total` : des totaux de joueurs, pas des vainqueurs d'épreuve. La règle
est inerte aujourd'hui (aucun OUTRIGHT n'atteint l'évaluation), mais la reprendre
ici salirait l'inventaire. Ce module ne la reprend pas — et ne touche pas au
chemin `MATCH_WINNER` existant, qui garde ses trois couples observés.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum

from .observation import RawMarketObservation

#: Couples (betTypeName, template) démontrés « qui gagne la rencontre ». Repris
#: VERBATIM de `winamax/market_mapping.py` : le chemin MATCH_WINNER en production
#: ne doit pas changer de sens parce qu'on a généralisé autour de lui (§11).
_MATCH_WINNER_OBSERVE = frozenset({
    ("Résultat", "3way"),
    ("Résultat", "2way"),
    ("Vainqueur", "2way"),
})

_TEMPLATES_HANDICAP = frozenset({"asian_handicap", "asiantext_handicap"})

#: `betType` -> CAMP dont le total est coté. MESURÉ sur 40 marchés de trois
#: sports, et le résultat corrige une conclusion antérieure : ces identifiants
#: désignent le SLOT, pas l'équipe.
#:
#:     football           2615 = slot_1   2680 = slot_2   (20 marchés, 4 affiches)
#:     basketball         2474 = slot_1   2877 = slot_2   (20 marchés, 4 affiches)
#:     american_football  2475 = slot_1   2878 = slot_2   ( 2 marchés, 1 affiche)
#:
#: L'erreur d'origine venait d'une lecture trop rapide : sur une seule affiche,
#: « 2877 = Dallas Wings » et « 2474 = Indiana Fever » se lisent comme deux
#: identifiants d'ÉQUIPE. Il fallait une deuxième affiche pour voir que 2877
#: suivait le second compétiteur et non les Wings. Une table construite sur un
#: seul exemple aurait attribué chaque total d'équipe au hasard — et une
#: probabilité donnée au mauvais camp est une prédiction inversée.
CAMP_DU_TOTAL_D_EQUIPE: dict[int, str] = {
    2615: "slot_1", 2680: "slot_2",      # football
    2474: "slot_1", 2877: "slot_2",      # basketball
    2475: "slot_1", 2878: "slot_2",      # football américain
}

#: Codes de sélection d'une double chance. Mesurés IDENTIQUES sur les 23 marchés
#: « Double chance » de la capture, dans quatre sports (football, hockey, rugby à
#: XIII, rugby à XV). Trois issues, trois codes, toujours les mêmes.
_CODES_DOUBLE_CHANCE = ("9", "10", "11")

#: Un score exact se reconnaît à ses codes : « 2:1 ». La source ajoute une issue
#: `other` pour tout ce qui sort de la grille affichée — c'est un vrai résultat
#: pariable, pas un résidu.
_CODE_SCORE = re.compile(r"^\d+:\d+$")

#: « Remboursé si match nul », dans les deux orthographes observées (parenthèses
#: en football, tiret en hockey). Le libellé identifie la FAMILLE ; il ne décide
#: JAMAIS si le marché est priceable — cela, c'est le `betType` qui le dit, et le
#: registre de capacité qui le tranche.
_LIBELLE_REMBOURSE = re.compile(r"(?i)rembours[ée]\s+si\s+match\s+nul")


class MarketFamily(str, Enum):
    """Familles CANONIQUES. Une famille ne porte aucune ligne : la ligne est un
    paramètre (§6). `TOTALS(2.5)` et `TOTALS(3.5)` sont la même famille."""

    MATCH_WINNER = "MATCH_WINNER"
    TOTALS = "TOTALS"
    #: Total d'UN camp. Distinct de `TOTALS` parce que ce n'est pas le même pari :
    #: « plus de 110,5 points pour le domicile » et « plus de 220,5 points dans le
    #: match » ont la même forme et des issues différentes. Les fondre sous une
    #: seule famille leur donnerait la MÊME identité de contrat, donc la même
    #: exposition et la même paire CLV — pour deux marchés qui n'ont rien à voir.
    TEAM_TOTALS = "TEAM_TOTALS"
    HANDICAP = "HANDICAP"
    OUTRIGHT_WINNER = "OUTRIGHT_WINNER"
    DOUBLE_CHANCE = "DOUBLE_CHANCE"
    DRAW_NO_BET = "DRAW_NO_BET"
    EXACT_SCORE = "EXACT_SCORE"
    #: Reconnu comme marché, sens non démontré. N'est PAS un échec de lecture :
    #: c'est un marché parfaitement conservé dont on refuse de nommer la famille.
    UNMAPPED = "UNMAPPED"


class ClassificationStatus(str, Enum):
    """Où en est CE marché dans la chaîne — distinct de « sait-on le prédire »."""

    OBSERVED = "OBSERVED"                # reçu, conservé, famille non démontrée
    CANONICALIZED = "CANONICALIZED"      # famille + paramètres établis
    AMBIGUOUS = "AMBIGUOUS"              # la source se contredit (forme vs contenu)


@dataclass(frozen=True)
class MarketClassification:
    family: MarketFamily
    status: ClassificationStatus
    #: Paramètres CANONIQUES de la famille : `line`, `handicap`, portée, sujet.
    parameters: dict = field(default_factory=dict)
    #: Pourquoi cette famille — la règle qui a produit la décision, nommée.
    evidence: str = ""
    #: `betType` de la source. Une famille canonique ne suffit PAS à identifier ce
    #: qu'un modèle peut traiter : « Nombre de buts » (betType 2749) et « Nombre de
    #: buts de Chicago Fire » (2680) sont tous deux `TOTALS(line=…)`, avec les mêmes
    #: paramètres structurés — le sujet n'existe que dans le libellé. Seul le
    #: `betType` les sépare de façon déterministe, et confondre les deux ferait
    #: pricer un total d'équipe avec la loi du total du match.
    source_family_id: int | None = None

    @property
    def canonical(self) -> bool:
        return self.status is ClassificationStatus.CANONICALIZED

    def describe(self) -> str:
        """`TOTALS(line=2.5, quarternr=1)` — la forme demandée au §6."""
        if not self.parameters:
            return self.family.value
        corps = ", ".join(f"{k}={v}" for k, v in sorted(self.parameters.items()))
        return f"{self.family.value}({corps})"


def _parametres_canoniques(obs: RawMarketObservation, **explicites) -> dict:
    """La ligne, puis la portée, puis le sujet. Le sujet et la portée sont repris
    tels quels : leur valeur est un identifiant de la source, pas une donnée à
    normaliser ici."""
    parametres = dict(explicites)
    parametres.update(obs.portee)
    parametres.update(obs.sujet)
    return parametres


def classify(obs: RawMarketObservation) -> MarketClassification:
    """Un marché observé -> sa famille, avec l'identifiant de famille de la source.

    Le `betType` est attaché ici, en un seul endroit, plutôt que recopié dans
    chacune des règles : c'est une propriété de l'observation, pas une conclusion
    de la classification.
    """
    from dataclasses import replace

    return replace(_classify(obs), source_family_id=obs.bet_type)


def _classify(obs: RawMarketObservation) -> MarketClassification:
    """Un marché observé -> sa famille, si et seulement si elle se démontre.

    L'ordre des règles suit la force de la preuve : d'abord les conjonctions
    structurelles (forme + arité + paramètre typé), ensuite les couples
    (libellé, forme) déjà validés en production. Aucune règle ne repose sur un
    mot trouvé dans un libellé libre.
    """
    template = (obs.template or "").strip()
    n = obs.nb_selections

    # 1) Plus/Moins : forme déclarée, deux issues, seuil numérique. Les trois
    #    ensemble — la ligne seule se retrouve sur des listes de joueurs.
    if template == "OverUnder":
        ligne = obs.ligne
        if ligne is None:
            return MarketClassification(
                MarketFamily.UNMAPPED, ClassificationStatus.AMBIGUOUS,
                {}, "template OverUnder sans seuil numérique — forme et contenu se contredisent")
        if n != 2:
            return MarketClassification(
                MarketFamily.UNMAPPED, ClassificationStatus.AMBIGUOUS,
                {"line": ligne}, f"template OverUnder à {n} issues (2 attendues)")
        # Total d'un CAMP : le `betType` le dit, et lui seul. Le libellé
        # (« Nombre de points de Dallas Wings ») nomme l'équipe et non le camp,
        # donc il ne peut pas servir — mais le betType est stable et mesuré.
        camp = CAMP_DU_TOTAL_D_EQUIPE.get(obs.bet_type)
        if camp is not None:
            return MarketClassification(
                MarketFamily.TEAM_TOTALS, ClassificationStatus.CANONICALIZED,
                _parametres_canoniques(obs, line=ligne, side=camp),
                f"template OverUnder + seuil + betType {obs.bet_type} = total du {camp}")
        return MarketClassification(
            MarketFamily.TOTALS, ClassificationStatus.CANONICALIZED,
            _parametres_canoniques(obs, line=ligne),
            "template OverUnder + seuil numérique + 2 issues")

    # 2) Handicap : même conjonction, avec `hcp`. Sur la capture, `hcp`
    #    n'apparaît sur aucun autre template — la réciproque est donc sûre.
    if template in _TEMPLATES_HANDICAP:
        handicap = obs.handicap
        if handicap is None:
            return MarketClassification(
                MarketFamily.UNMAPPED, ClassificationStatus.AMBIGUOUS,
                {}, "template handicap sans valeur numérique")
        if n != 2:
            return MarketClassification(
                MarketFamily.UNMAPPED, ClassificationStatus.AMBIGUOUS,
                {"handicap": handicap}, f"template handicap à {n} issues (2 attendues)")
        return MarketClassification(
            MarketFamily.HANDICAP, ClassificationStatus.CANONICALIZED,
            _parametres_canoniques(obs, handicap=handicap),
            "template handicap + valeur numérique + 2 issues")

    # 3) « Qui gagne » : les trois couples déjà démontrés en production. On exige
    #    en plus l'arité de la forme — un 3way à deux issues n'est pas un 1X2.
    if (obs.bet_type_name, template) in _MATCH_WINNER_OBSERVE:
        attendu = 3 if template == "3way" else 2
        if n != attendu:
            return MarketClassification(
                MarketFamily.UNMAPPED, ClassificationStatus.AMBIGUOUS,
                {}, f"template {template} à {n} issues ({attendu} attendues)")
        # Un marché « qui gagne » restreint à une période N'EST PAS le marché de
        # la rencontre : la portée entre dans les paramètres, et c'est au
        # registre de capacité de dire s'il sait la traiter.
        return MarketClassification(
            MarketFamily.MATCH_WINNER, ClassificationStatus.CANONICALIZED,
            _parametres_canoniques(obs),
            f"couple observé ({obs.bet_type_name}, {template}) + {attendu} issues")

    # 4) Double chance : trois issues, trois codes stables. Le nom ne sert pas —
    #    « Mi-temps - Double chance » porte les MÊMES codes, et c'est correct :
    #    c'est bien la même famille, à une autre portée. La portée se tranche au
    #    registre de capacité, pas ici.
    codes = tuple(s.code for s in obs.selections)
    if codes == _CODES_DOUBLE_CHANCE:
        return MarketClassification(
            MarketFamily.DOUBLE_CHANCE, ClassificationStatus.CANONICALIZED,
            _parametres_canoniques(obs),
            "codes de sélection (9, 10, 11) — observés identiques sur 23 marchés et 4 sports")

    # 5) Score exact : les codes SONT les scores.
    if codes and all(_CODE_SCORE.match(c or "") or c == "other" for c in codes) \
            and any(_CODE_SCORE.match(c or "") for c in codes):
        return MarketClassification(
            MarketFamily.EXACT_SCORE, ClassificationStatus.CANONICALIZED,
            _parametres_canoniques(obs),
            "codes de sélection de la forme « x:y » (+ « other »)")

    # 6) Remboursé si match nul : deux compétiteurs, mise rendue sur le nul. Seul
    #    marché de cette liste dont les codes (1, 2) ne suffisent pas à
    #    l'identifier — un moneyline tennis les porte aussi. Le libellé départage
    #    la famille ; il ne départagera pas la portée.
    if (template == "2way" and n == 2 and codes == ("1", "2")
            and _LIBELLE_REMBOURSE.search(obs.bet_type_name or "")):
        return MarketClassification(
            MarketFamily.DRAW_NO_BET, ClassificationStatus.CANONICALIZED,
            _parametres_canoniques(obs),
            "template 2way + codes (1, 2) + libellé « remboursé si match nul »")

    # 7) Vainqueur d'épreuve : liste de compétiteurs SUR un événement que la
    #    SOURCE déclare outright. Le drapeau vient du bookmaker — c'est ce qui
    #    distingue les 33 vrais vainqueurs d'épreuve des 1 230 autres `ListOdd`
    #    (marqueurs, mi-temps/fin de match, props) que le template seul confondait.
    if obs.is_outright and (obs.bet_type_name, template) == ("Vainqueur", "ListOdd"):
        if n < 2:
            return MarketClassification(
                MarketFamily.UNMAPPED, ClassificationStatus.AMBIGUOUS, {},
                f"vainqueur d'épreuve à {n} issue(s) — il en faut au moins deux")
        return MarketClassification(
            MarketFamily.OUTRIGHT_WINNER, ClassificationStatus.CANONICALIZED,
            _parametres_canoniques(obs),
            "événement déclaré outright par la source + liste « Vainqueur »")

    # 8) Tout le reste est CONSERVÉ sans être nommé. C'est le cas majoritaire, et
    #    c'est le comportement voulu : un inventaire honnête montre son ignorance.
    return MarketClassification(
        MarketFamily.UNMAPPED, ClassificationStatus.OBSERVED,
        _parametres_canoniques(obs),
        f"aucune règle démontrée pour (betType={obs.bet_type}, template={template or '∅'})")
