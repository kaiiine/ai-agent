"""Baseball MLB — marchés de SCORE : STOP STATISTIQUE, et voici pourquoi.

Ce module existe pour que le refus soit REPRODUCTIBLE. Un « on a essayé, ça ne
marchait pas » se perd ; une mesure qu'on peut rejouer se conteste, se corrige et
se refait le jour où les données changent.

MESURÉ (walk-forward strict, 8 495 rencontres 2022-2024, 8 169 évaluées), sur les
mêmes cibles et la même mécanique que le basket et le NFL :

    loi NORMAL   10 cibles sur 22 battent leur baseline point-in-time.
                 Les gains vont de −0,010 à +0,006 de Brier — c'est-à-dire du
                 bruit. Les cibles gagnantes ne forment aucune famille cohérente :
                 quatre `TEAM_TOTALS(away)`, deux `SPREAD` proches de zéro.
    loi POISSON   0/22. La surdispersion mesurée du total vaut 2,29.
    loi NEGBIN   10/22, sur 1 914 rencontres seulement.

    MAE marge 3,44 runs pour un écart-type observé de 4,47 : le modèle explique
    à peine plus que la moyenne. MAE total 3,58 pour un écart-type de 4,55.

POURQUOI CE N'EST PAS UNE SURPRISE, ET CE QU'IL FAUDRAIT. Le résultat d'un match
de baseball dépend au premier ordre du LANCEUR PARTANT, qui change à chaque
rencontre, et du parc, qui change à chaque déplacement. Des notes d'équipe
agrégées ne peuvent pas porter cette information : elles décrivent une moyenne
sur des configurations qui ne se reproduisent pas. Le corpus embarqué ne contient
ni composition, ni identité du lanceur, ni identifiant de stade.

CE QUI LÈVERAIT LE STOP : un corpus avec lanceur partant, parc et éventuellement
météo. Tant qu'il n'existe pas, aucune probabilité de `RUN_LINE` ou de
`TOTAL_RUNS` ne doit sortir d'AXON — et surtout pas une probabilité « pas trop
mauvaise » qu'un marché à forte marge transformerait en edge apparent.

Le moneyline MLB, lui, reste inchangé : il n'est ni concerné ni remis en cause
par ce refus.
"""

from __future__ import annotations

from src.agents.quant.betting_engine.sports.score_distribution import ScoreGame, ScoreParams
from src.agents.quant.betting_engine.sports.score_markets import ScoreMarketConfig

MODEL_NAME = "baseball_score"
MODEL_VERSION = "baseball.score.v0"
MLB_LEAGUE_ID = "competition:baseball:usa:mlb"

#: Motif du refus, en un seul endroit. Repris tel quel par le rapport et par les
#: tests : un verdict cité de mémoire finit par être cité de travers.
STOP_STATISTIQUE = (
    "STOP STATISTICAL — aucune des trois lois candidates ne bat honnêtement la "
    "fréquence historique point-in-time (NORMAL 10/22 avec des gains de l'ordre "
    "du bruit, POISSON 0/22, NEGBIN 10/22 sur un quart du corpus). La marge de "
    "runs dépend du lanceur partant et du parc, que le corpus embarqué ne "
    "contient pas."
)

MLB_SCORE_PARAMS = ScoreParams(
    baseline_points=4.5, k=0.05, home_edge=0.2,
    min_prior_games=20, min_prior_residuals=200,
    notes="MLB : ~4,5 runs/équipe, avantage domicile ~0,2 run, K=0,05")


def _identites_mlb() -> dict:
    from .live_model import _API_OF
    return dict(_API_OF)


def load_mlb_score_games() -> list[ScoreGame]:
    from .moneyline import load_mlb_games
    jeux, _ = load_mlb_games()
    return [ScoreGame(g.game_id, g.tipoff, g.home_id, g.away_id,
                      g.home_score, g.away_score) for g in jeux]


#: `law=None` : AUCUNE loi retenue. Ce n'est pas une configuration incomplète,
#: c'est le résultat. Un pricer qui lirait ce config s'abstiendrait.
MLB_SCORE_CONFIG = ScoreMarketConfig(
    sport="baseball", competition_id=MLB_LEAGUE_ID,
    model_name=MODEL_NAME, model_version=MODEL_VERSION,
    params=MLB_SCORE_PARAMS, load=load_mlb_score_games,
    law=None, team_id_of=_identites_mlb)
