"""Désambiguïsation DÉTERMINISTE d'une compétition Winamax par CHEVAUCHEMENT DE ROSTER.

Winamax expose des noms de compétitions AMBIGUS — au moins DEUX « Bundesliga »
(Allemagne vs Autriche), plusieurs « Primera División ». Résoudre un `tid` vers une
compétition canonique par le NOM est interdit (§9 : misresolution silencieuse
money-sensitive). On résout par la PREUVE : les équipes réellement observées chez
Winamax pour ce `tid` doivent recouvrir le roster provider de la compétition candidate.

Fail-safe :
- plusieurs candidats restent plausibles  -> `COMPETITION_IDENTITY_AMBIGUOUS`
- aucun candidat suffisamment recouvrant   -> `COMPETITION_IDENTITY_UNRESOLVED`
Jamais de fuzzy silencieux, jamais de fallback sur le nom. Cet outil sert à JUSTIFIER
un mapping vérifié (verification_method="roster_overlap") — il ne devine rien seul.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import Mapping, Sequence

COMPETITION_IDENTITY_RESOLVED = "RESOLVED"
COMPETITION_IDENTITY_AMBIGUOUS = "COMPETITION_IDENTITY_AMBIGUOUS"
COMPETITION_IDENTITY_UNRESOLVED = "COMPETITION_IDENTITY_UNRESOLVED"

# Jetons non distinctifs (formes juridiques / génériques club) : ignorés pour éviter
# qu'un « FC » commun ne crée un faux chevauchement entre compétitions disjointes.
_STOPWORDS = frozenset({
    "fc", "cf", "ac", "sc", "us", "ss", "cd", "rc", "as", "sv", "vfb", "vfl", "tsg",
    "club", "calcio", "futbol", "football", "de", "the", "and", "und",
})
_MIN_TOKEN_LEN = 4              # écarte fc/ac/… et le bruit court


def _significant_tokens(name: str) -> frozenset[str]:
    """Jetons distinctifs d'un nom d'équipe : sans accents, casefold, sans forme
    juridique ni jeton court/numérique. Ex. « FC Bayern München » -> {bayern, munchen}."""
    folded = unicodedata.normalize("NFKD", name)
    folded = "".join(c for c in folded if not unicodedata.combining(c)).casefold()
    raw = "".join(c if c.isalnum() else " " for c in folded).split()
    return frozenset(
        t for t in raw
        if len(t) >= _MIN_TOKEN_LEN and not t.isdigit() and t not in _STOPWORDS
    )


def _team_matches_roster(observed: str, roster_tokens: list[frozenset[str]]) -> bool:
    """Une équipe observée « matche » le roster si elle partage >=1 jeton distinctif
    avec une équipe du roster (recouvrement, jamais une égalité de nom exigée)."""
    obs = _significant_tokens(observed)
    if not obs:
        return False
    return any(obs & rt for rt in roster_tokens)


def roster_overlap(observed_names: Sequence[str], roster_names: Sequence[str]) -> float:
    """Fraction [0,1] des équipes observées chez Winamax qui recouvrent le roster
    provider. Compétitions disjointes (Bundesliga DE vs AT) -> scores très écartés."""
    observed = [n for n in observed_names if _significant_tokens(n)]
    if not observed:
        return 0.0
    roster_tokens = [_significant_tokens(n) for n in roster_names]
    hits = sum(1 for n in observed if _team_matches_roster(n, roster_tokens))
    return hits / len(observed)


@dataclass(frozen=True)
class CompetitionResolution:
    status: str                              # RESOLVED | ..._AMBIGUOUS | ..._UNRESOLVED
    competition_id: str | None               # non nul seulement si RESOLVED
    scores: dict[str, float]                 # competition_id candidate -> score de chevauchement


def disambiguate(
    observed_names: Sequence[str],
    candidates: Mapping[str, Sequence[str]],
    *,
    min_overlap: float = 0.5,
    min_margin: float = 0.25,
) -> CompetitionResolution:
    """Résout un `tid` (via ses équipes observées) vers UNE compétition candidate.

    RESOLVED seulement si le meilleur candidat recouvre une MAJORITÉ des équipes
    observées (`min_overlap`) ET devance le 2e d'au moins `min_margin` (univocité).
    Le seuil de MAJORITÉ (0.5) et non 1.0 : les exonymes cross-langue (Cologne/Köln,
    Fribourg/Freiburg…) réduisent le recouvrement même pour la BONNE compétition ; la
    marge dominante sur des rosters disjoints (Bundesliga DE 0.56 vs AT 0.0) reste la
    garantie d'univocité. Sinon AMBIGUOUS (2 plausibles) ou UNRESOLVED (aucun assez
    recouvrant). Déterministe, sans effet de bord."""
    scores = {cid: round(roster_overlap(observed_names, roster), 4)
              for cid, roster in candidates.items()}
    if not scores:
        return CompetitionResolution(COMPETITION_IDENTITY_UNRESOLVED, None, scores)

    ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
    best_id, best = ranked[0]
    second = ranked[1][1] if len(ranked) > 1 else 0.0

    if best < min_overlap:
        return CompetitionResolution(COMPETITION_IDENTITY_UNRESOLVED, None, scores)
    if (best - second) < min_margin:
        return CompetitionResolution(COMPETITION_IDENTITY_AMBIGUOUS, None, scores)
    return CompetitionResolution(COMPETITION_IDENTITY_RESOLVED, best_id, scores)
