"""Gateway point-in-time : reconstruit forme + classement + forces à un cutoff T,
en n'utilisant QUE des matchs strictement antérieurs à T.

Implémente l'interface consommée par `build_event_feature_set`
(`recent_form`/`standings_strength`) mais filtrée à `kickoff < cutoff` (STRICT).
Injecté dans le `build_event_feature_set` EXISTANT avec `as_of=cutoff`, il produit
un `EventFeatureSet` sans fuite temporelle — aucune reconstruction de feature
n'est dupliquée, seule la source change (le chemin live utilise le classement
COURANT ; ici, le classement est recalculé sur l'antérieur).

Garanties de non-fuite :
- filtre sur `kickoff` STRICTEMENT `< cutoff` (jamais `<=`, jamais par matchday —
  `CanonicalMatch` ne porte d'ailleurs aucun matchday, donc c'est structurel) ;
- le match évalué (kickoff == cutoff) et tout match postérieur sont exclus ;
- deux matchs du même jour civil sont départagés à la seconde près par `kickoff`.

Réutilise les calculateurs PURS et versionnés du gateway (`derived.recent_form`,
`derived.standings_strength`) — source unique, pas de copie. Seule la
reconstruction de la table (matchs antérieurs -> classement) est neuve.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from src.agents.quant.gateway.sports.football import derived
from src.agents.quant.gateway.sports.football.canonical_facts import (
    CanonicalMatch,
    CanonicalStandingRow,
)


class PointInTimeGateway:
    def __init__(
        self,
        matches: Sequence[CanonicalMatch],
        cutoff: datetime,
        league_id: str,
        season: str,
    ):
        # Filtre STRICT appliqué une fois : uniquement les matchs joués AVANT T.
        self._prior = [
            m for m in matches
            if m.kickoff < cutoff                      # strict : exclut kickoff == cutoff
            and m.status == "FINISHED"
            and m.goals_home is not None
            and m.goals_away is not None
        ]
        self._cutoff = cutoff
        self._league_id = league_id
        self._season = season

    def recent_form(self, canonical_team_id: str, last: int, season: str) -> list[dict]:
        return derived.recent_form(self._prior, canonical_team_id, self._league_id, season, last)

    def standings_strength(self, league_canonical_id: str, season: str) -> dict[str, float]:
        return derived.standings_strength(self._reconstruct_table())

    def _reconstruct_table(self) -> list[CanonicalStandingRow]:
        """Classement recalculé sur les seuls matchs antérieurs à T (3/1/0)."""
        stats: dict[str, list[int]] = {}   # team_id -> [points, played, gf, ga]
        for m in self._prior:
            for tid in (m.home_team_id, m.away_team_id):
                stats.setdefault(tid, [0, 0, 0, 0])
            gh, ga = m.goals_home, m.goals_away
            stats[m.home_team_id][1] += 1
            stats[m.away_team_id][1] += 1
            stats[m.home_team_id][2] += gh
            stats[m.home_team_id][3] += ga
            stats[m.away_team_id][2] += ga
            stats[m.away_team_id][3] += gh
            if gh > ga:
                stats[m.home_team_id][0] += 3
            elif ga > gh:
                stats[m.away_team_id][0] += 3
            else:
                stats[m.home_team_id][0] += 1
                stats[m.away_team_id][0] += 1

        # Tri points desc, diff de buts desc, buts pour desc ; team_id pour un
        # départage déterministe (reproductibilité de l'expérience).
        ranked = sorted(
            stats.items(),
            key=lambda kv: (-kv[1][0], -(kv[1][2] - kv[1][3]), -kv[1][2], kv[0]),
        )
        return [
            CanonicalStandingRow(team_id=tid, rank=i + 1, played=s[1], points=s[0])
            for i, (tid, s) in enumerate(ranked)
        ]
