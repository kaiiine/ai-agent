# Dossier d'exécution Axon Advisor

Ce dossier contient les documents à transmettre à Claude Code.

## Fichiers

- `PRD-axon-advisor.md` — source de vérité produit et architecture.
- `IMPLEMENTATION-axon-advisor.md` — lots d'implémentation et critères de fin.
- `ADR-BACKLOG-axon-advisor.md` — décisions architecturales à formaliser.
- `CLAUDE-CODE-PROMPT.md` — prompt de démarrage.

## Ordre recommandé

1. Copier les fichiers dans `docs/`.
2. Donner `CLAUDE-CODE-PROMPT.md` à Claude Code.
3. Faire exécuter uniquement le Lot 0.
4. Vérifier le current state.
5. Autoriser ensuite les lots un par un.
6. Conserver la règle d'arrêt avant chaque commit.

## Important

Le PRD Betting Engine existant reste valide pour les probabilités, la calibration et la Value Engine.

Le nouveau PRD définit la couche produit de recommandation.
