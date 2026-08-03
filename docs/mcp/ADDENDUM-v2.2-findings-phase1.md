# Addendum v2.2 — Corrections issues de la Phase 1

**Statut :** Phase 1 livrée, 841 tests, `grep -ri "blender" axon/mcp/` vide.
**Portée :** corrige l'ADDENDUM v2.1 (Correction 3), le PRD v2 (§6.4) et le Design Technique v2 (§5.1, §6, §8).
**À lire avant la Phase 2.**

---

## Correction A — Rectification de l'Addendum v2.1, Correction 3

### Ce qui était faux

L'addendum v2.1 affirmait :

> `env` dans `StdioServerParameters` **remplace** l'environnement, il ne le fusionne pas. Passer le bloc `env` de la §10.2 tel quel prive le sous-processus de `PATH`.

**C'est inexact.** Le SDK 1.26 fait déjà le merge lui-même :

```python
env=({**get_default_environment(), **server.env}
     if server.env is not None else get_default_environment())
```

L'affirmation avait été posée sans vérification, le spike ayant fusionné par prudence sans jamais tester le cas non fusionné.

### Ce qui reste vrai

**La conclusion et le code sont inchangés.** `build_subprocess_env()` reste :

```python
return {**get_default_environment(), **resolve_env(cfg.env)}
```

Mais pour la seule raison valable, celle que l'addendum v2.1 donnait lui-même en « nuance » : `os.environ` déverserait l'intégralité de l'environnement d'Axon — tokens compris — dans chaque serveur MCP tiers. `get_default_environment()` renvoie un sous-ensemble assaini.

La phrase sur la perte du `PATH` est **retirée**. Elle survivrait comme une justification fausse d'une décision juste, ce qui est la pire forme de dette documentaire : personne ne la rediscute, et elle induit en erreur au premier serveur qui pose problème.

---

## Correction B — `runtime.pid` n'est pas récupérable

`stdio_client` ne publie pas l'objet processus. Il n'existe pas de moyen propre d'obtenir le PID sans aller chercher dans l'interne du SDK, ce qui créerait un couplage à une API privée.

**PRD §6.4 — ligne corrigée :**

```
✗  ✓ subprocess started   pid 48213
✓  ✓ subprocess started   transport stdio ouvert (pid non exposé par le SDK)
```

`MCPServerRuntime.pid` est conservé dans le modèle (il redeviendra renseignable si le SDK l'expose, ou avec un transport futur), mais reste `None` en v1. Aucun code ne doit en dépendre.

**Impact sur le test 4.4 du plan de test.** Le critère « vérifier qu'un seul subprocess `uvx` a été respawné avec `ps aux | grep` » reste valable — il se vérifie côté OS, pas côté Axon. Mais le test unitaire correspondant doit compter les `restart()` sur la connexion, pas les PID. C'est ce que fait `test_le_lock_empeche_les_redemarrages_concurrents`.

---

## Correction C (STRUCTURANTE) — Propriété du transport par une tâche dédiée

### Le problème, absent du design v2

`stdio_client` et `ClientSession` sont des **scopes anyio**. Les ouvrir dans une tâche et les fermer dans une autre lève :

```
RuntimeError: attempted to exit cancel scope in a different task
```

Or c'est exactement ce que produit le §5.1 tel qu'écrit : un `restart()` déclenché depuis un appel de tool ferme, depuis la tâche de l'appel, un scope ouvert par la tâche de démarrage. **Le design v2 casse au premier redémarrage déclenché par un échec de tool** — c'est-à-dire dans le scénario nominal de reconnexion, pas dans un cas limite.

### Correction — tâche porteuse du transport

Une tâche dédiée ouvre **et** ferme l'`AsyncExitStack` elle-même :

```
open()        →  démarre la tâche porteuse, attend son signal "prêt"
tâche porteuse:  async with stdio_client(...) as (r, w):
                     async with ClientSession(r, w) as session:
                         initialize()
                         publier la session
                         attendre l'événement d'arrêt        ← ne rend jamais la main
                     # sortie du scope DANS la tâche qui l'a ouvert
close()       →  positionne l'événement d'arrêt, attend la fin de la tâche
```

La `ClientSession` ainsi obtenue reste utilisable depuis n'importe quelle tâche : seule l'entrée/sortie de scope est contrainte, pas l'usage.

**§5.1 du design est remplacé par ce modèle.** Le diagramme `close() → open()` reste valide fonctionnellement, mais l'implémentation passe obligatoirement par la tâche porteuse.

### Pourquoi le noter explicitement

Ce n'est pas un détail d'implémentation : c'est une contrainte du modèle de concurrence qui remonte jusqu'à l'interface publique de `MCPConnection`. Tout transport futur (SSE, HTTP) devra être évalué sous cet angle. À réécrire dans le design plutôt qu'à laisser vivre dans le seul code.

---

## Correction D — Emplacement du package

Les documents écrivaient `axon/mcp/` de façon générique, sans connaissance de l'arborescence réelle du dépôt. Le code existant vivant sous `src/`, un second package racine `axon/` crée deux racines pour un projet unique.

**Décision : le package MCP suit l'arborescence existante du dépôt.** Le déplacement se fait **avant** la Phase 2, tant qu'il ne concerne que 5 fichiers et aucun import externe. Après l'indexation, le REPL et le registry, il touchera l'ensemble du projet.

Toute occurrence de `axon/mcp/` dans le PRD, le design et les addenda se lit comme « le package MCP », à l'emplacement retenu.

---

## Écarts acceptés (aucune correction requise)

| Écart | Décision |
|---|---|
| `diff_server_tools` dans `manager.py` plutôt que `registry.py` | Accepté. `refresh()` doit renvoyer un `ToolDiff`, la fonction appartient au manager. Le §8 du design est ajusté : `registry.py` importe le diff, ne le produit pas. |
| Chargement de config strict (rejet des clés inconnues) | Accepté et souhaitable. Une faute de frappe sur `capabilities_hint` dégraderait silencieusement le retrieval — un échec bruyant vaut mieux. |
| Test d'intégration stdio avec serveur FastMCP inline | Accepté. Exercer la vraie chaîne stdio sans dépendre d'un serveur tiers est le bon compromis, et le serveur inline renvoyant un `isError=False` trompeur teste la Correction 1 de bout en bout. |

---

## État des invariants après Phase 1

| Invariant | Test |
|---|---|
| Aucune closure de connexion | `test_call_tool_resout_la_connexion_courante_et_ne_capture_rien` |
| Lock sur `ensure_connected` | `test_le_lock_empeche_les_redemarrages_concurrents` |
| Pas d'aplatissement en `str` | `test_normalize_result_range_les_blocs_par_type_sans_aplatir` |
| Env sans propagation de secrets | `test_build_subprocess_env_ne_propage_pas_les_secrets_non_declares` |
| Timeouts différenciés | `test_timeout_par_tool_prioritaire_sur_le_timeout_global` |
| `isError=False` trompeur détecté | `test_echec_backend_avec_is_error_false_est_detecte` |
| Provenance non menteuse | `test_provenance_ne_ment_pas_sur_un_echec_a_is_error_false` |
| Zéro connaissance serveur en dur | `grep -ri "blender\|uvx\|9876\|bpy" <package>/mcp/` vide |

Ces tests sont des **tests de non-régression architecturale**. Ils ne doivent pas être modifiés pour faire passer du code : s'ils cassent, c'est le code qui a dérivé.
