# PRD v2 — Axon MCP Client

**Feature :** `axon-mcp-client`
**Auteur :** Kaine
**Statut :** Draft v2 (intègre la review architecturale)
**Date :** 2026-07-30
**Remplace :** PRD v1 du 2026-07-30

---

## 1. Contexte

Axon expose déjà un **serveur** MCP (`mcp_server.py`, consommé par Zed). Ce PRD concerne la direction inverse : faire d'Axon un **client** MCP capable de consommer des serveurs MCP tiers (Blender, filesystem, GitHub, browser…).

| | Axon serveur MCP (existant) | Axon client MCP (ce PRD) |
|---|---|---|
| Sens | Zed → Axon | Axon → Blender / filesystem / … |
| Fichier | `mcp_server.py` | nouveau package `axon/mcp/` |
| Rôle | Axon est un outil | Axon consomme des outils |

## 2. Problème à résoudre

Ajouter une capacité à Axon nécessite aujourd'hui d'écrire un tool custom en dur. L'écosystème MCP fournit déjà des serveurs prêts à l'emploi. L'objectif est de transformer "ajouter une capacité" en "ajouter une ligne de config", **sans qu'aucune connaissance spécifique au serveur ne soit codée en dur dans Axon**.

## 3. Objectif architectural (le vrai critère de réussite)

> Le reste d'Axon (LangGraph, retrieval, REPL) ne doit **jamais** savoir si un tool provient d'un `@tool` natif, d'un MCP Blender ou d'un MCP GitHub.

Frontière visée :

```
LangGraph
   │
   ▼
Axon Tool Registry ── NativeToolRef
   │                └─ MCPToolRef
   ▼
Tool Runtime
   │
   ▼
MCPClientManager  ← seule source de vérité du runtime MCP
   │
MCPConnection ── SDK MCP Python officiel
   │
Blender / filesystem / GitHub
```

Propriété à préserver : **Chroma ne connaît pas les connexions, LangGraph ne connaît pas MCP, MCP ne connaît pas Chroma.**

## 4. Objectifs fonctionnels

1. Connexion à N serveurs MCP externes déclarés en config.
2. Interface `/mcp` dans le REPL : `list`, `add`, `remove`, `enable`, `disable`, `test`, `tools`, `restart`, `refresh`.
3. Découverte automatique des tools et indexation dans le retrieval sémantique existant (ChromaDB), avec **routing en deux étages** (serveur puis tool).
4. Normalisation des résultats MCP en un format **multimodal** interne (texte / structuré / images / resources), pas uniquement du texte.
5. Traçabilité complète des invocations (provenance).
6. Classification de risque par tool, avec possibilité d'exiger une confirmation utilisateur.
7. Validation par Blender MCP, choisi comme stress test le plus exigeant.

## 5. Non-objectifs (v1)

- Écrire ses propres serveurs MCP.
- Transports SSE / HTTP (v1 = **stdio uniquement**).
- OAuth multi-utilisateur.
- UI graphique (CLI `/mcp` uniquement).
- Sandbox système des serveurs tiers (cf. §10, politique de risque à la place).
- Gestion automatique des notifications `tools/list_changed` (l'interface `refresh_tools()` est prévue, le déclenchement reste manuel via `/mcp refresh`).

## 6. Exigences fonctionnelles

### 6.1 Configuration — `.axon/mcp_servers.json`

```json
{
  "servers": {
    "blender": {
      "transport": "stdio",
      "command": "uvx",
      "args": ["--python", "3.11", "blender-mcp"],
      "env": {
        "BLENDER_HOST": "localhost",
        "BLENDER_PORT": "9876",
        "DISABLE_TELEMETRY": "true",
        "UV_PYTHON_PREFERENCE": "only-managed"
      },
      "enabled": true,
      "timeouts": { "connect_s": 15, "list_tools_s": 15, "call_s": 90 },
      "tool_timeouts": { "execute_blender_code": 180 },
      "reconnect": { "max_retries": 5, "backoff_s": 2, "backoff_factor": 2 },
      "capabilities_hint": "3D modeling, mesh, materials, lighting, camera, animation, rendering, export, bpy"
    }
  }
}
```

**Règles de config :**
- `env` ne contient **jamais** de secret en clair. Syntaxe d'interpolation obligatoire pour les secrets : `"GITHUB_TOKEN": "${GITHUB_TOKEN}"`, résolue au lancement par `resolve_env()`.
- `.axon/mcp_servers.json` est ajouté à `.gitignore` par sécurité, même avec l'interpolation.
- L'environnement du sous-processus est `{**os.environ, **resolve_env(server.env)}` — un env vide ne doit pas priver le serveur de son PATH.

### 6.2 Modèle d'état des serveurs

`connected / error / disabled` est insuffisant. Machine à états retenue :

```
DISABLED → DISCONNECTED → CONNECTING → READY
                             ↑            ↓
                           ERROR ←── DEGRADED
```

| État | Signification |
|---|---|
| `DISABLED` | Désactivé en config, aucun process lancé |
| `DISCONNECTED` | Activé mais pas encore connecté |
| `CONNECTING` | Handshake en cours |
| `READY` | `initialize` + `tools/list` OK, `ping` OK |
| `DEGRADED` | Process MCP vivant et tools connus, mais erreurs répétées à l'exécution |
| `ERROR` | Connexion impossible ou process mort |

`DEGRADED` est spécifiquement motivé par Blender : **le process MCP peut être vivant et exposer correctement ses tools alors que la socket vers Blender est cassée**. Autrement dit : `process MCP vivant ≠ backend opérationnel`.

Runtime associé : `state`, `last_error`, `last_connected_at`, `tool_count`, `reconnect_attempts`, `resolved_command`.

### 6.3 Commandes `/mcp`

| Commande | Effet |
|---|---|
| `/mcp list` | Table : nom, état, nb de tools, dernière erreur |
| `/mcp add <nom>` | Assistant interactif → écrit dans la config, propose un `test` immédiat |
| `/mcp remove <nom>` | Retire de la config + désenregistre les tools |
| `/mcp enable <nom>` / `/mcp disable <nom>` | Active/désactive + (dés)enregistre les tools |
| `/mcp test <nom>` | Diagnostic multi-étapes (§6.4), **sans** enregistrement dans l'index |
| `/mcp test <nom> --deep` | Idem + appel d'un tool d'inspection sans effet de bord (opt-in explicite) |
| `/mcp tools <nom>` | Schémas détaillés des tools exposés |
| `/mcp refresh <nom>` | Re-`tools/list` + diff + resync de l'index, sans redémarrer le process |
| `/mcp restart <nom>` | Kill + respawn + initialize + discover + diff + resync |

`restart` et `refresh` sont en v1 et non en v2 : avec stdio et Blender, ils seront utilisés en permanence, et `disable` + `enable` est un contournement pénible.

Rendu attendu de `/mcp list` :

```
NAME         STATE       TOOLS   LAST ERROR
blender      ready       22      -
filesystem   disabled    -       -
github       degraded    14      connection reset
```

### 6.4 `/mcp test` — diagnostic par étapes

Un `tools/list` réussi ne prouve pas grand-chose. Sortie attendue :

```
/mcp test blender

✓ command resolved     /home/kaine/.local/bin/uvx
✓ subprocess started   pid 48213
✓ MCP initialize       ok (312 ms)
✓ protocol version     <négociée>
✓ tools/list           22 tools (188 ms)
✓ ping                 ok (11 ms)
⚠ backend health       non exposé explicitement par ce serveur
```

L'affichage du **chemin résolu de la commande** est délibéré : le README de Blender MCP documente le fait qu'`uvx` peut fonctionner dans un terminal mais rester introuvable depuis un client dont le PATH diffère, et recommande alors un chemin absolu. Voir ce chemin dans `/mcp test` économise beaucoup de temps de debug.

`--deep` est opt-in car `tools/call` peut avoir des effets de bord : on ne l'exécute jamais automatiquement pour tous les serveurs.

### 6.5 Découverte, enregistrement, exécution

**Séparation stricte discovery / execution.** Un tool indexé ne détient **jamais** de référence vers une connexion vivante. Il détient une référence stable :

```
MCPToolRef(server="blender", remote_name="execute_blender_code",
           public_name="blender.execute_blender_code", ...)
```

et l'exécution passe systématiquement par le manager :

```
Chroma → MCPToolRef → MCPClientManager.call_tool(server, tool, args) → connexion actuelle
```

Motif : les connexions vont tomber, être redémarrées, désactivées puis réactivées ; Blender va être relancé. Un tool indexé qui capture une `ClientSession` devient une référence morte à la première coupure.

### 6.6 Retrieval — document enrichi et routing à deux étages

**Problème :** `execute_blender_code` avec sa description brute ("Execute Python code inside Blender") a une similarité médiocre avec "fais-moi un logo 3D depuis ce PNG".

**Document indexé** (pas seulement la description) :

```
Server: blender
Tool: execute_blender_code
Description: Execute Python code inside Blender.
Capabilities: Blender, 3D modeling, mesh manipulation, materials,
geometry, animation, camera, lighting, rendering, scene editing, export, bpy.
Input: code: string
```

soit `retrieval_text = public_name + description + json_schema_summary + server_metadata + capabilities_hint`. Le schéma d'entrée est lui-même une information sémantique.

**Routing à deux étages**, dès la v1 même avec un seul serveur :

```
query → scoring serveurs → 1 à 3 serveurs retenus → retrieval tools filtré sur ces serveurs
```

Implémenté via metadata Chroma (`{"source": "mcp", "server": "blender", "tool": "..."}`) et filtrage `where`. Structure meilleure dès le départ, et absorbe la prolifération de tools quand filesystem/GitHub/browser s'ajouteront.

### 6.7 Résultats multimodaux

Aucune normalisation prématurée en `str`. Un `CallToolResult` MCP peut contenir plusieurs blocs de types différents et du contenu structuré. Format interne :

```python
@dataclass
class ToolResult:
    text: str | None = None
    structured: dict | list | None = None
    images: list[ImageArtifact] = field(default_factory=list)
    resources: list[ResourceRef] = field(default_factory=list)
    is_error: bool = False
    metadata: dict = field(default_factory=dict)
```

C'est ce qui débloque la boucle la plus intéressante avec Blender, qui sait fournir des screenshots de viewport :

```
Axon crée → screenshot viewport → modèle vision inspecte → Axon corrige → nouveau screenshot
```

Cette boucle est à moyen terme **plus importante que l'export `.glb`**.

### 6.8 Provenance et observabilité

Chaque invocation est loguée :

```json
{
  "tool": "blender.execute_blender_code",
  "source": "mcp",
  "server": "blender",
  "remote_tool": "execute_blender_code",
  "request_id": "...",
  "duration_ms": 1240,
  "success": true,
  "risk_level": "execute"
}
```

Secondaire aujourd'hui, indispensable dès qu'Axon aura `filesystem.read`, `github.read_file`, `browser.fetch`, `blender.execute_blender_code` et `native.shell` en parallèle et qu'il faudra répondre à "pourquoi Axon a fait ça ?".

### 6.9 Règle agentique : read-before-write

> Pour toute modification d'un état externe existant (scène Blender, fichier, repo), Axon doit d'abord récupérer/rafraîchir l'état pertinent, sauf s'il possède un identifiant récemment vérifié.

Concrètement sur Blender : avant de modifier un objet, appeler le tool d'inspection de scène et se caler sur les noms réels (`Cube`, `Material.001`) plutôt que sur la mémoire conversationnelle ("l'objet que j'ai créé s'appelle probablement Cube"). La persistance de Blender conserve l'état du monde, mais pas l'intention d'Axon. Règle transposable à filesystem, GitHub, bases de données.

## 7. Timeouts différenciés

Un `timeout_s` unique est un mauvais modèle. Blender l'illustre bien : un `initialize` de 90 s est un problème, un rendu de 90 s est normal.

| Phase | Défaut | Justification |
|---|---|---|
| `connect_s` | 10–15 s | Au-delà, le serveur ne démarre pas |
| `list_tools_s` | 10–15 s | Découverte, doit être rapide |
| `call_s` | 90 s | Opérations métier, potentiellement lentes |
| `tool_timeouts[nom]` | override | ex. `execute_blender_code: 180` |

## 8. Cycle de vie stdio

Reconnexion stdio ≠ `session.reconnect()`. La séquence réelle est :

```
ancien subprocess mort → cleanup streams/session → nouveau subprocess
→ nouvelle ClientSession → initialize() → éventuellement tools/list()
```

Exigences :
- `MCPConnection.restart()` atomique = `close()` puis `open()`.
- **Lock de connexion obligatoire** (`asyncio.Lock`) : sans lui, trois tools échouant simultanément déclenchent trois redémarrages concurrents du serveur.
- `ensure_connected()` acquiert le lock, vérifie la santé, reconnecte si nécessaire.
- Démarrage non bloquant : un serveur down n'empêche pas Axon de démarrer avec les autres tools.

## 9. Sécurité — classification de risque

La formulation v1 ("pas de sandbox, acceptable car serveurs de confiance") est remplacée :

> La v1 ne fournit pas de sandbox système. Certains MCP exposent des capacités à fort impact, notamment l'exécution de code arbitraire — le README de Blender MCP signale explicitement que `execute_blender_code` exécute du Python arbitraire dans Blender, avec les privilèges du process Blender, et recommande de sauvegarder son travail avant usage. Axon conserve donc une **classification de risque par tool** et peut exiger une confirmation utilisateur avant invocation des tools sensibles.

```python
risk_level: Literal["read", "write", "execute", "destructive"]
```

Heuristiques par défaut :
- MCP inconnu → `write`
- `execute_*`, `run_*`, `eval_*` → `execute`
- `delete_*`, `drop_*`, `remove_*` → `destructive`

L'auto-approbation peut rester active en dev, mais **l'architecture doit pouvoir accueillir la politique** dès la v1.

## 10. Roadmap

| Phase | Contenu | Sortie |
|---|---|---|
| **Phase 0 — Spike** | Script isolé : `stdio_client` + `ClientSession` + `initialize` + `list_tools` + 1 `call_tool` sur Blender. Aucune Chroma, aucun Axon. | Le protocole et Blender sont validés avant d'écrire le framework |
| **Phase 1 — MCP core** | `config`, `models`, `connection`, `manager`, normalisation des résultats, appel générique | Client MCP autonome et testable |
| **Phase 2 — Intégration Axon** | `MCPToolRef`, `registry`, indexation Chroma enrichie, exécution via LangGraph | Tools MCP indistinguables des tools natifs |
| **Phase 3 — CLI** | `/mcp list/add/remove/enable/disable/test/tools/restart/refresh` | Gestion complète sans édition manuelle |
| **Phase 4 — Recette Blender** | cube → itération → screenshot feedback loop → GLB → PNG vectorisé → géométrie | Validation fonctionnelle |
| Phase 5 (hors scope) | SSE/HTTP, `tools/list_changed` automatique, sandboxing | — |

## 11. Milestone n°1 — critère de succès réel

Le premier jalon n'est **pas** "Axon crée un hero 3D". C'est la boucle suivante :

```
Axon découvre dynamiquement execute_blender_code
→ Chroma le retrouve sur la requête "crée un cube"
→ LangGraph sélectionne le tool
→ MCPClientManager l'exécute
→ Blender change réellement
→ Axon inspecte la scène
→ réponse utilisateur
```

Si cette boucle fonctionne **sans aucune connaissance Blender codée en dur dans Axon**, l'objectif architectural du §3 est atteint : filesystem, GitHub et browser deviennent alors des plugins de capacités et non des intégrations spécifiques.

## 12. Definition of Done (v1)

- [ ] Phase 0 validée : `call_tool` réussi sur Blender hors d'Axon
- [ ] `/mcp list/add/remove/enable/disable/test/tools/restart/refresh` fonctionnels
- [ ] `/mcp test` affiche les 6 étapes de diagnostic dont le chemin résolu de la commande
- [ ] États `READY` / `DEGRADED` / `ERROR` correctement discriminés sur Blender
- [ ] Aucune closure de connexion capturée dans un tool indexé (audit de code)
- [ ] Résultats multimodaux : au moins un screenshot Blender remonté et exploitable par un modèle vision
- [ ] Milestone n°1 (§11) validé
- [ ] Recette Blender (plan de test v2) validée
- [ ] Ajouter un serveur MCP filesystem prend < 5 min sans toucher au code

## 13. Risques

| Risque | Mitigation |
|---|---|
| Backend Blender dégradé alors que le process MCP est vivant | État `DEGRADED` + `/mcp test` multi-étapes |
| Redémarrages concurrents du subprocess | Lock de connexion (§8) |
| `uvx` introuvable depuis Axon malgré un terminal fonctionnel | Merge `os.environ` + chemin absolu + affichage du chemin résolu dans `/mcp test` |
| Interpréteur Python inattendu choisi par uv (conda/pyenv) | Pin `--python 3.11` + `UV_PYTHON_PREFERENCE=only-managed` |
| Similarité sémantique faible pour les tools génériques | Document de retrieval enrichi (§6.6) |
| Prolifération de tools dégradant le routing | Routing à deux étages dès la v1 |
| Exécution de code arbitraire | Classification de risque + confirmation optionnelle (§9) |
| Secrets versionnés par accident | Interpolation `${VAR}` + `.gitignore` |
