# Addendum v2.5 — Indexation : bug bloquant, arbitrages, invariant n°13

**Statut :** correctif appliqué, 924 tests. Découvert en préparant la Phase 4, sur la première configuration réelle (`blender`).
**Portée :** corrige le Design Technique v2 (§8) et l'addendum v2.4. Précise une attente erronée sur les états serveur.

---

## Le bug

Première écriture d'un `~/.axon/mcp_servers.json` réel. `/mcp list` :

```
NAME     STATE  TOOLS  LAST ERROR
blender  ready  0/22   -
```

**Zéro tool exposé sur 22 découverts.** MCP était entièrement mort, alors qu'Axon démarrait normalement et qu'aucun test ne le voyait — les tests utilisaient des serveurs de 1 à 3 tools aux descriptions courtes.

### Cause exacte

`build_server_document` construisait le document de l'étage 1 en concaténant les **descriptions** des tools du serveur :

```python
f"Descriptions: {' | '.join(t.description for t in tools if t.description)}"
```

Pour 22 tools : **9 931 caractères, ~2 480 tokens** — au-dessus du contexte de `nomic-embed-text` (2 048).

```
_upsert_server → Chroma.add_texts → OllamaEmbeddings.embed_documents
ollama._types.ResponseError: the input length exceeds the context length (400)
```

Les 22 documents de l'étage 2 passaient (le plus gros : 1 249 caractères). Seul l'**agrégat** de l'étage 1 dépassait. L'exception remontait de `_apply` jusqu'à `start()`, où `mcp_runtime()` la réduisait à une ligne `mcp_runtime_start_failed` dont le détail voyageait dans `extra=` — non rendu.

### Ce que le bug révèle sur la forme du défaut

Trois propriétés indépendantes ont concouru :

| Propriété | Effet isolé | Effet combiné |
|---|---|---|
| Document d'étage 1 croissant avec le nombre de tools | Passe à 22, casse à 100 | Panne dépendante du serveur |
| Exception fatale au niveau `start()` | Interrompt l'indexation de TOUS les serveurs | Zéro tool |
| Exception avalée sans surface | Aucune trace visible | Panne silencieuse |

**Avalé ET fatal** est la combinaison la pire : le système perd sa capacité principale et affirme aller bien.

---

## Arbitrage 1 — Document d'étage 1 borné par construction

Le document ne contient plus que **nom du serveur + `capabilities_hint` + noms des tools**, avec un plafond dur configurable (`SERVER_DOC_MAX_CHARS`, défaut 4 000) et une troncature annoncée (`… (+N autres)`).

**Justification.** Les descriptions vivent déjà dans les documents de l'étage 2 : les répéter dans l'agrégat n'apporte aucune information au routing serveur, et fait dépendre la taille du document du nombre de tools. 22 tools passaient de justesse ; c'était de la chance, pas une propriété. La taille doit être bornée **indépendamment** du nombre de tools.

Le plafond est dur, pas indicatif : le document est tronqué en dernier recours même si la construction incrémentale a échoué à le contenir. Le `capabilities_hint` est lui aussi borné — un hint géant ne doit pas suffire à faire déborder.

---

## Arbitrage 2 — Une panne d'indexation ne fait jamais disparaître de tools

L'exception est capturée **au niveau du serveur**, dans `_apply`, pas au niveau de `start()`. Les enveloppes LangChain sont construites quoi qu'il arrive.

Conséquence en cas d'échec de l'étage 1 :

```
tools exposés          ✅  inchangés, exécutables
routing étage 2        ✅  documents de tools indexés
routing étage 1        ❌  le serveur ne peut pas être élu
repli                  →  le serveur est joint d'office au filtre de l'étage 2
```

`route()` reçoit `unrouted_servers` : les serveurs sans document d'étage 1 sont ajoutés au filtre `where`, ce qui les rend joignables par le seul étage 2. Un serveur en panne d'indexation ne peut pas empêcher les autres de s'indexer.

**Justification.** Une capacité dégradée vaut mieux qu'une capacité muette — mais jamais au prix d'un mensonge sur son état, d'où l'arbitrage 3.

---

## Arbitrage 3 — Aucun message de diagnostic affirmatif ne peut être faux

Le rendu affirmait « L'écart vient d'une collision de nom runtime » **dès que** exposés ≠ découverts. Sur ce bug, `collisions == 0` : le message était faux, affirmatif, et envoyait le debug dans la mauvaise direction.

Trois règles appliquées :

1. La collision n'est nommée que si `collisions > 0`. Sinon : « écart sans cause identifiée sur *serveur* ».
2. L'état d'indexation est **visible**. `/mcp list` gagne une colonne `ROUTING` (`ok` / `étage 2` / `-`) et une note nommant la raison réelle. `/mcp test` gagne une étape `routing index`.
3. Quand la cause n'est pas connue, le rendu le dit au lieu d'en inventer une.

```
NAME     STATE  TOOLS  ROUTING  LAST ERROR
blender  ready  22     ok       -
```

---

## Invariant n°13

> **Aucune exception d'indexation ne peut faire tomber à zéro le nombre de tools MCP exposés.**

Tests : `test_13_une_panne_dindexation_ne_fait_jamais_tomber_les_tools_a_zero` (Chroma réel avec un embedder qui lève systématiquement, message identique à celui d'Ollama) et `test_13_variante_index_qui_leve_a_lupsert`.

Tests associés : repli sur l'étage 2 seul, retour à l'état sain après un succès, document borné à 100 puis 500 tools, plafond configurable, hint géant.

---

## Correction d'une attente erronée sur les états

Le brief de préparation de la Phase 4 attendait `disconnected` ou `error` avec Blender fermé. **C'est `ready` qui est correct**, et c'est le cœur du modèle d'états :

| État | Condition réelle |
|---|---|
| `ready` | `initialize` + `tools/list` + `ping` OK. **Ne dit rien du backend.** |
| `degraded` | `ping` OK mais N résultats consécutifs `failed` — n'apparaît qu'**après des appels de tool**, jamais au démarrage |
| `error` | commande introuvable, handshake KO, process mort |

`uvx blender-mcp` démarre et expose ses 22 tools sans Blender : le process MCP va bien, seul son backend est absent. C'est exactement la distinction « process MCP vivant ≠ backend opérationnel » qui justifie l'existence de `DEGRADED`.

Le seul moyen de voir l'état du backend **sans appeler de tool métier** est `/mcp test --deep`, qui sonde un tool read-only :

```
✓ ping                 ok (1 ms)
✗ backend health       get_scene_info: Error getting scene info: Could not connect
                       to Blender. Make sure the Blender addon is running. (5 ms)
```

Le health predicate déclaratif de l'addendum v2.1 fonctionne ici sur le vrai serveur : le protocole répond `isError=False`, les `failure_patterns` de la config rattrapent l'échec applicatif.

---

## Note de méthode

Ce bug n'était atteignable par aucun test unitaire raisonnable : il demandait un serveur réel, nombreux en tools et bavard en descriptions. Il a été trouvé par la **première mise en configuration réelle**, avant tout usage.

La leçon rejoint celle de l'Alerte A (v2.3) : les vérifications synthétiques valident la logique, pas les ordres de grandeur. Un socle validé par 909 tests était inutilisable sur sa première configuration de production.

À ajouter à la recette : après tout ajout de serveur, vérifier que `TOOLS` en colonne `/mcp list` n'est pas `0/N` et que `ROUTING` vaut `ok`.

---

## Invariants — récapitulatif

| # | Invariant |
|---|---|
| 1–12 | cf. addendum v2.4 |
| 13 | Aucune exception d'indexation ne fait tomber à zéro les tools MCP exposés |
