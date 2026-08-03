# Plan de test v2 — Recette Blender MCP

Complète le **PRD v2** (§11, §12). Les tests sont **ordonnés par valeur architecturale décroissante**, pas par difficulté croissante : l'itération et la boucle de feedback prouvent l'architecture, la génération de logo prouve seulement une capacité Blender.

---

## Phase 0 — Spike hors Axon (bloquant)

Avant d'écrire une seule ligne du package `axon/mcp/`.

Script isolé (~40 lignes) utilisant directement le SDK MCP officiel :

```
stdio_client(StdioServerParameters(command="uvx", args=[...], env=...))
  → ClientSession
  → initialize()
  → list_tools()          → afficher les noms
  → call_tool("get_scene_info", {})
```

**Critère de sortie :** un `call_tool` réussi contre une session Blender ouverte, sans Axon, sans Chroma, sans LangGraph.

**Pourquoi bloquant :** si le protocole ou la chaîne Blender ne fonctionne pas, on ne veut pas le découvrir après avoir écrit le manager, le registry et le CLI.

---

## Prérequis (une fois Phase 0 validée)

- [ ] Blender 3.0+ installé
- [ ] Python 3.10+ disponible
- [ ] `uv` installé via **l'installeur officiel** : `curl -LsSf https://astral.sh/uv/install.sh | sh` (atterrit dans `~/.local/bin`, ouvrir un nouveau shell). **Ne pas utiliser `pip install uv`** : le README de blender-mcp indique que cette méthode peut ne pas créer la commande `uvx`.
- [ ] `which uvx` retourne un chemin — le noter, il servira en fallback de config
- [ ] `addon.py` téléchargé depuis le repo, installé via Edit > Preferences > Add-ons > Install
- [ ] Addon activé (case "Interface: Blender MCP")
- [ ] Dans la vue 3D : `N` → onglet "BlenderMCP" → bouton de connexion cliqué
- [ ] Package `axon/mcp/` implémenté jusqu'à la Phase 3 du PRD

---

## Test 1 — Diagnostic de connexion

```
/mcp add blender
/mcp test blender
```

**Attendu :**

```
✓ command resolved     /home/kaine/.local/bin/uvx
✓ subprocess started   pid <n>
✓ MCP initialize       ok
✓ protocol version     <négociée>
✓ tools/list           <n> tools
✓ ping                 ok
⚠ backend health       non exposé explicitement par ce serveur
```

Puis `/mcp list` doit afficher `blender | ready | <n> | -`.

**Debug si échec :**
- `command resolved` vide → PATH d'Axon ≠ PATH du terminal → mettre le chemin absolu de `uvx` dans `command`
- `initialize` en timeout → vérifier le pin `--python 3.11` et `UV_PYTHON_PREFERENCE=only-managed` (conda/pyenv peut fournir un interpréteur incompatible) ; nettoyer le cache : `uv cache clean blender-mcp && uvx --refresh blender-mcp`
- `tools/list` OK mais tout appel échoue → l'addon Blender n'est pas connecté, pas un problème MCP

---

## Test 2 — Milestone n°1 : la boucle complète (test le plus important)

**Prompt :** "Crée un cube rouge au centre de la scène Blender, puis dis-moi ce qu'il y a dans la scène."

**Chaîne à vérifier dans les logs, étape par étape :**

| # | Étape | Vérification |
|---|---|---|
| 1 | Découverte | Le tool a été indexé au démarrage, pas déclaré en dur |
| 2 | Retrieval | Chroma remonte le tool Blender pertinent en tête sur cette requête |
| 3 | Routing étage 1 | Le scoring serveur classe `blender` largement devant les autres |
| 4 | Sélection | LangGraph choisit le tool et produit des arguments valides |
| 5 | Exécution | `MCPClientManager.call_tool` invoqué (pas de closure de connexion) |
| 6 | Effet réel | Le cube existe dans Blender, matériau rouge |
| 7 | Read-back | Axon appelle le tool d'inspection de scène |
| 8 | Provenance | Log complet : `blender.<tool>`, durée, `success`, `risk_level` |

**Critère de succès :** aucune ligne de code spécifique à Blender dans Axon. Si c'est vrai, l'objectif architectural est atteint et filesystem/GitHub deviennent triviaux.

**Anti-critère :** si un `if server == "blender"` a été nécessaire quelque part, le test échoue même si le cube apparaît.

---

## Test 3 — Itération sur scène existante (read-before-write)

Enchaîner sur le test 2, **sans redémarrer Axon**.

**Prompt :** "Rends-le bleu et déplace-le de 2 unités vers la droite."

**Attendu :**
1. Axon appelle **d'abord** l'inspection de scène pour récupérer le nom réel de l'objet.
2. Il modifie l'objet identifié, pas un nom deviné depuis l'historique.
3. Il ne recrée pas un nouveau cube.

**Distinction à valider explicitement :** la persistance de Blender conserve l'état du monde (`Cube`, `Material.001`), mais **pas** l'intention d'Axon. Le grounding doit venir de la scène réelle, pas de la mémoire conversationnelle.

**Variante de robustesse :** renommer manuellement l'objet dans Blender entre les deux prompts. Axon doit toujours réussir — s'il échoue, il s'appuyait sur sa mémoire et non sur la scène.

---

## Test 4 — Résilience et cycle de vie

Le test qui valide le lock, le backoff et l'état `DEGRADED`.

| # | Action | Attendu |
|---|---|---|
| 4.1 | Fermer Blender pendant qu'Axon tourne, puis demander une modification | Erreur claire remontée au LLM, session Axon vivante, état → `DEGRADED` puis `ERROR` |
| 4.2 | `/mcp list` | L'état reflète la réalité, `last_error` renseigné |
| 4.3 | Rouvrir Blender + reconnecter l'addon, puis `/mcp restart blender` | Retour à `ready`, tools réindexés, diff affiché |
| 4.4 | Lancer 3 requêtes en parallèle avec Blender fermé | **Un seul** subprocess `uvx` respawné (vérifier avec `ps aux \| grep blender-mcp`) — valide le `asyncio.Lock` |
| 4.5 | Démarrer Axon avec Blender fermé | Axon démarre normalement, autres tools disponibles, blender en `error` |
| 4.6 | `/mcp refresh blender` | Re-list sans redémarrer le process, diff vide si rien n'a changé |

---

## Test 5 — Résultats multimodaux (screenshot feedback loop)

Le test qui valide `ToolResult.images` et débloque la capacité la plus différenciante.

**Prompt :** "Crée une scène simple, prends un screenshot du viewport et dis-moi si le cadrage est correct."

**Attendu :**
1. Le screenshot revient dans `ToolResult.images`, **pas** aplati en string ni perdu.
2. L'image est transmise à un backend vision d'Axon (Gemini par exemple).
3. Axon commente réellement l'image plutôt que de décrire la scène de mémoire.

**Bonus (boucle complète) :** "Le cadrage est mauvais, corrige-le." → Axon modifie la caméra, reprend un screenshot, compare.

**Critère d'échec silencieux à surveiller :** si `normalize_result` concatène tout en texte, ce test "passe" en apparence alors que l'image a été perdue. Vérifier dans les logs que `len(result.images) > 0`.

---

## Test 6 — Export GLB pour R3F

**Prompt :** "Exporte la scène en GLB dans `~/Documents/axon-exports/`."

**Attendu :**
- Fichier `.glb` créé, chargeable via `useGLTF` dans un projet R3F sans erreur.

**Périmètre du GLB — distinction importante :**

```
GLB (Blender)            R3F (runtime web)
├── geometry             ├── camera
├── materials            ├── lighting
└── animations           ├── postprocessing
                         └── interaction
```

En pipeline web, on ne veut généralement **pas** utiliser les lumières et la caméra exportées : elles sont beaucoup plus contrôlables côté R3F. Le GLB doit porter la géométrie, les matériaux et éventuellement les animations. La composition Blender complète (lumières, caméra) sert à la **validation visuelle** dans Blender, pas au runtime.

**Vérification :** ouvrir le GLB dans un viewer et confirmer que la géométrie et les matériaux sont corrects, sans exiger que l'éclairage exporté soit fidèle.

---

## Test 7 — Scène hero pour un site

**Prompt :** "Compose une scène hero : un objet central avec une rotation lente, éclairage doux, cadrage propre. Montre-moi un screenshot, puis exporte la géométrie et l'animation en GLB."

**Attendu, en deux temps :**

```
1. Composition complète dans Blender (objet + lumières + caméra)
   → screenshot → validation visuelle
2. Export GLB des assets + animations pertinentes
   → intégration R3F avec caméra/lights gérées côté React
```

**Critère :** le GLB s'intègre dans le stack déjà utilisé sur les projets showcase (React Three Fiber, `.glb`, GSAP/Lenis) sans retouche manuelle du fichier.

---

## Test 8 — Logo 3D depuis PNG (deux modes distincts)

⚠️ **Test à ne pas déclarer réussi trop vite.** Un PNG est raster : appliquer un modifier Solidify sur un plan texturé donne

```
┌──────── image ────────┐
│                       │   + épaisseur
└───────────────────────┘
```

et **pas** une vraie silhouette extrudée :

```
    ███
    █ █
```

### Mode A — logo raster complexe (dégradés, photo, détails fins)

**Prompt :** "Fais une plaque 3D avec ce logo en texture."

**Attendu :** plan texturé + épaisseur, matériau avec alpha. Résultat honnête et suffisant pour un usage décoratif.

**À noter dans le rapport :** ce mode ne produit **pas** de géométrie fidèle au contour.

### Mode B — logo simple avec silhouette nette

**Prompt :** "Vectorise ce logo et extrude sa vraie silhouette en 3D."

**Pipeline attendu :**

```
PNG avec alpha
   ↓ vectorisation / détection de contours
SVG / paths
   ↓ import
Blender Curve
   ↓ extrude + bevel
mesh
   ↓
GLB
```

**Attendu :** la géométrie suit réellement les contours du logo — les trous du logo sont des trous dans le mesh, pas des zones transparentes de texture.

**Critère de succès du test 8 :** Axon doit **choisir le bon mode** en fonction du logo fourni, ou au minimum expliquer le compromis avant de générer. Un test 8 "réussi" en ayant simplement extrudé un rectangle texturé compte comme un **échec**.

---

## Récapitulatif

| # | Test | Ce que ça prouve | Statut |
|---|---|---|---|
| 0 | Spike hors Axon | Protocole + chaîne Blender | ☐ |
| 1 | Diagnostic connexion | Config, PATH, lifecycle | ☐ |
| 2 | Boucle complète (cube) | **L'architecture entière** | ☐ |
| 3 | Itération + read-before-write | Grounding sur l'état réel | ☐ |
| 4 | Résilience | Lock, backoff, états | ☐ |
| 5 | Screenshot feedback loop | Multimodalité | ☐ |
| 6 | Export GLB | Pipeline web | ☐ |
| 7 | Scène hero | Cas d'usage réel | ☐ |
| 8 | Logo PNG → 3D (2 modes) | Capacité Blender avancée | ☐ |

**Tests 0 à 5 = Definition of Done du PRD v2.** Les tests 6 à 8 sont des capacités applicatives : utiles, mais leur échec ne remet pas en cause l'architecture.

---

## Test de généralisation (après validation)

Une fois les tests 0 à 5 verts, ajouter un serveur MCP filesystem :

```
/mcp add filesystem
/mcp test filesystem
```

**Critère final :** < 5 minutes, zéro ligne de code modifiée dans Axon, et le routing à deux étages n'envoie pas les requêtes Blender vers filesystem ni l'inverse. Si c'est le cas, le socle MCP est réellement générique.
