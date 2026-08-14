"""L'identité ÉCONOMIQUE d'un contrat pariable — ce qui peut s'apparier avec quoi.

Une paire CLV compare la cote prise à la décision et celle de la clôture DU MÊME
PARI. Tant que le seul marché collecté était « qui gagne », l'identité tenait en
`(événement, market_type, sélection, bookmaker)`. Avec les Plus/Moins, la ligne
entre dans le contrat : « plus de 2,5 buts » et « plus de 3,5 buts » ne sont pas
le même pari, et apparier leurs cotes mesurerait un mouvement de LIGNE en le
présentant comme une variation de PRIX.

FORME RETENUE, ET POURQUOI ELLE NE MIGRE RIEN. L'identité est une CHAÎNE
canonique rangée dans le champ `market_type` existant :

    MATCH_WINNER                 (aucun paramètre — identique à l'existant)
    TOTALS(line=2.5)
    DOUBLE_CHANCE
    DRAW_NO_BET
    EXACT_SCORE

Un marché sans paramètre rend EXACTEMENT la chaîne d'avant. Les observations déjà
écrites restent donc lisibles, appariables et comptées comme elles l'étaient : il
n'y a ni réécriture du store, ni ré-horodatage, ni suppression. C'est la
propriété la plus importante de ce module, et elle est testée.

Les paramètres sont TRIÉS et NORMALISÉS : `2.5` et `2.50` produisent la même
identité, sans quoi deux captures du même contrat cesseraient de s'apparier pour
une différence de formatage.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Clés qui n'appartiennent pas au CONTRAT : elles décrivent d'où vient le
#: marché, pas ce qu'il paie. Les inclure ferait dépendre l'identité économique
#: d'un identifiant de bookmaker, et deux captures du même pari cesseraient de
#: s'apparier si la source renumérotait ses types.
_HORS_CONTRAT = frozenset({"source_family_id"})


def _valeur(v) -> str:
    """Normalise une valeur de paramètre. `2.5`, `2.50` et `"2.5"` coïncident."""
    if isinstance(v, bool):
        return str(v).lower()
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    return str(int(f)) if f.is_integer() else repr(round(f, 6))


def identite_contrat(family, parameters=None, context=None) -> str:
    """`(famille, paramètres, contexte)` -> identité canonique du contrat.

    Sans paramètre ni contexte, rend le nom de la famille seul — donc la valeur
    historique pour `MATCH_WINNER`.
    """
    nom = getattr(family, "value", None) or str(family)
    couples = []
    for source in (parameters or {}, context or {}):
        for cle, valeur in source.items():
            if cle in _HORS_CONTRAT or valeur is None:
                continue
            couples.append((str(cle), _valeur(valeur)))
    if not couples:
        return nom
    corps = ", ".join(f"{k}={v}" for k, v in sorted(set(couples)))
    return f"{nom}({corps})"


def famille_de(identite: str) -> str:
    """La famille d'une identité de contrat, sans ses paramètres."""
    return identite.split("(", 1)[0]


def parametres_de(identite: str) -> dict[str, str]:
    if "(" not in identite:
        return {}
    corps = identite[identite.index("(") + 1: identite.rindex(")")]
    return dict(p.split("=", 1) for p in corps.split(", ") if "=" in p)


#: Deux observations du même événement, de la même famille et de la même
#: sélection, mais de PARAMÈTRES différents : le bookmaker a déplacé sa ligne.
LINE_MOVEMENT = "LINE_MOVEMENT"
#: Même contrat, cote différente : c'est ce que la CLV mesure.
SAME_LINE_PRICE_MOVEMENT = "SAME_LINE_PRICE_MOVEMENT"


@dataclass(frozen=True)
class Movement:
    kind: str
    depuis: str
    vers: str
    detail: str = ""


def classer_mouvement(avant: str, apres: str) -> Movement | None:
    """Que s'est-il passé entre deux identités de contrat observées ?

    Un déplacement de ligne est une information réelle et utile — mais ce n'est
    PAS une CLV, et le transformer en paire mesurerait la décision du bookmaker
    de changer de produit, pas la qualité de notre prix.
    """
    if avant == apres:
        return Movement(SAME_LINE_PRICE_MOVEMENT, avant, apres,
                        "même contrat : la CLV est mesurable")
    if famille_de(avant) != famille_de(apres):
        return None                      # familles différentes : rien de comparable
    a, b = parametres_de(avant), parametres_de(apres)
    bouges = sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))
    return Movement(
        LINE_MOVEMENT, avant, apres,
        f"paramètre(s) déplacé(s) : {', '.join(bouges)} — "
        "contrat différent, aucune paire CLV")
