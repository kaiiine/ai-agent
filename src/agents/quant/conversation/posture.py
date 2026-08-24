"""Extraction DÉTERMINISTE de la posture demandée (sûreté ou valeur).

Le modèle ne choisit pas la posture. Il n'a pas à arbitrer, après coup et à
chaque tour, entre « le plus sûr » et « le plus rentable » : une préférence
exprimée en français doit se lire toujours de la même façon, et se vérifier.

Deux règles, dans cet ordre :

  1. VALUE_FIRST exige une demande EXPLICITE de rendement ou de risque.
  2. Tout le reste — y compris l'absence de demande — reste SAFETY_FIRST.

Et le cas qui décide de la conception : « je veux du sûr mais que ça rapporte »
contient les deux vocabulaires. La sûreté l'emporte, la valeur ne fait que
départager. Un utilisateur qui demande les deux demande d'abord de ne pas
perdre.
"""
from __future__ import annotations

import re

from ..betting_engine.markets.review_ranking import RecommendationPosture

#: Demande de SÉCURITÉ. Volontairement large : c'est le défaut, un faux positif
#: ne coûte rien puisqu'il confirme la posture déjà en place.
_SURETE = re.compile(
    r"(?i)\b("
    r"s[ûu]rs?|s[ûu]re|prudent[es]?|fiables?|s[ée]curisant"
    r"|forte[s]?\s+chances?|quasi[- ]?s[ûu]r|quasi[- ]?certain"
    r"|le\s+plus\s+probable|les\s+plus\s+probables"
    r"|le\s+plus\s+de\s+chances?(?:\s+de\s+passer)?"
    r"|risque\s+faible|faible\s+risque|peu\s+risqu[ée]"
    r"|que\s+[çc]a\s+passe|qui\s+passent?|sans\s+trop\s+de\s+risque"
    r")\b")

#: Demande de VALEUR. Volontairement ÉTROITE : elle fait basculer hors du
#: défaut protecteur, donc elle doit être sans ambiguïté.
_VALEUR = re.compile(
    r"(?i)("
    r"\bvalue\s*bets?\b|\bvalue\b"
    r"|\bmeilleur\s+rendement\b|\bmeilleur\s+edge\b|\bmeilleure?\s+ev\b"
    r"|\bplus\s+rentables?\b|\brentabilit[ée]\s+max"
    r"|\bplus\s+de\s+risques?\s+pour\s+gagner\s+plus\b"
    r"|\bje\s+prends\s+(?:plus\s+de\s+)?risques?\b"
    r"|\bmaximiser?\s+(?:l['’]?)?(?:ev|esp[ée]rance|gain)"
    r")")


def detecter_posture(texte: str | None) -> RecommendationPosture:
    """La posture portée par la demande. SAFETY_FIRST par défaut."""
    if not texte:
        return RecommendationPosture.SAFETY_FIRST
    veut_surete = bool(_SURETE.search(texte))
    veut_valeur = bool(_VALEUR.search(texte))
    # Les deux à la fois : la sûreté prime, la valeur départage. C'est le
    # comportement par défaut, pas une exception.
    if veut_valeur and not veut_surete:
        return RecommendationPosture.VALUE_FIRST
    return RecommendationPosture.SAFETY_FIRST


def posture_lisible(posture: RecommendationPosture) -> str:
    """Ce qu'on affiche à l'utilisateur pour qu'il sache ce qui a été appliqué."""
    if posture is RecommendationPosture.VALUE_FIRST:
        return ("classement orienté RENDEMENT (demandé explicitement) — "
                "la probabilité ne sert que de garde")
    return ("classement orienté SÛRETÉ (par défaut) — l'espérance ne départage "
            "qu'à probabilité, qualité et fraîcheur équivalentes")
