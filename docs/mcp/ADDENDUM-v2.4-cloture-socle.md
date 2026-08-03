# Addendum v2.4 — Phase 3 et clôture du socle

**Statut :** Phase 3 livrée, 909 tests. Socle MCP complet (Phases 0 à 3). Reste la recette Blender (Phase 4).

---

## Invariant n°12 — Aucun tool MCP n'est cacheable

Le cache rejoue un `ToolMessage` reconstruit depuis une chaîne. Un tool MCP mis en cache perdrait son artefact au replay, **sans bruit**.

C'est le **troisième** chemin de perte silencieuse d'artefact identifié, après la reconstruction dans `CachedToolNode` (Correction H) et la redaction. Le motif est constant : tout code qui reconstruit un message depuis son contenu textuel perd ce qui n'est pas textuel.

**Invariant :** aucun tool MCP ne figure dans `CACHEABLE_TOOLS`. Vérifié par assertion dans le test n°11.

**Règle générale à appliquer désormais.** Avant tout ajout d'un traitement sur les messages — cache, redaction, compaction, résumé, persistance, export — vérifier explicitement le devenir de `ToolMessage.artifact`. Trois occurrences du même bug en un lot indiquent que ce n'est pas un accident isolé mais une propriété du pipeline.

---

## Changement de comportement accepté — serveurs désactivés

Un serveur déclaré mais `enabled: false` démarre désormais la boucle MCP, sans lancer de sous-processus. Sans cela, `/mcp list` ne le voyait pas et `/mcp enable` n'avait rien à activer.

Le coût nul est préservé là où il compte : **aucun fichier de config → aucun thread**, ce qui reste le cas par défaut du projet.

Le test `test_serveur_desactive_ne_demarre_rien` est renommé `…_ne_lance_aucun_sous_processus_mais_reste_visible`. Hors des 12 invariants protégés, modification annoncée.

---

## État du socle

| Phase | Contenu | Statut |
|---|---|---|
| 0 | Spike stdio hors Axon | ✅ |
| 1 | MCP core (models, config, connection, manager, adapter) | ✅ |
| 2 | Intégration Axon (registry, Chroma, LangGraph) | ✅ |
| 3 | Surface CLI `/mcp` | ✅ |
| 4 | Recette Blender | à faire — nécessite une session graphique |

**Le socle est agnostique du serveur.** Aucun lot n'a nécessité une seule ligne spécifique à Blender : le grep architectural est vide depuis la Phase 1, sur un périmètre étendu à `uvx`, `9876`, `bpy` et les noms de tools du serveur de référence.

---

## Note de méthode — consolidation à prévoir

La documentation vit désormais sur cinq fichiers : PRD v2, Design v2, et trois addenda correctifs. C'est acceptable pendant l'implémentation, où l'historique des décisions a de la valeur, mais devient coûteux à lire ensuite.

**Après validation de la Phase 4**, fusionner en un PRD v3 et un Design v3 intégrant les corrections, en conservant les addenda en annexe historique. Les corrections qui méritent de survivre dans le corps du texte : health predicate déclaratif (v2.1-C1), tâche porteuse du transport (v2.2-C), trois niveaux de nommage (v2.3-F), échec rendu et non levé (v2.3-E), et la règle sur les artefacts ci-dessus.

---

## Invariants — récapitulatif

| # | Invariant |
|---|---|
| 1 | Aucune closure de connexion capturée par un tool |
| 2 | Lock sur `ensure_connected` |
| 3 | Pas d'aplatissement d'un `CallToolResult` en `str` |
| 4 | Env sans propagation de secrets non déclarés |
| 5 | Timeouts différenciés |
| 6 | `isError=False` trompeur détecté via health predicate |
| 7 | Provenance non menteuse |
| 8 | Zéro connaissance serveur en dur (grep) |
| 9 | Tool MCP et tool natif indiscernables du runtime |
| 10 | Ordre de câblage de l'indexation |
| 11 | Artefact préservé sur tout le pipeline de messages |
| 12 | Aucun tool MCP cacheable |

Ces tests ne se modifient pas pour faire passer du code.
