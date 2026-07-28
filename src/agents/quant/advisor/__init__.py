"""axon-advisor — couche de recommandation au-dessus d'axon-betting-engine.

Décide sous contraintes (bankroll, cote cible, risque, exclusions) à partir des
évaluations du Betting Engine. Ne recalcule aucune probabilité sportive, ne
connaît aucun détail de sport/modèle (PRD §6.1).

CŒUR PUR DOMAINE : aucun module de `domain/`, `input_adapter/`,
`candidate_generation/`, `policy/`, `ranking/`, `recommendation/` n'importe de
framework (langgraph/langchain), d'orchestration ou de couche d'interface.
L'intégration Axon est une glue séparée (cf. test de pureté des imports).
"""
