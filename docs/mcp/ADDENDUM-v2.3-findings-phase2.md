# Addendum v2.3 — Corrections issues de la Phase 2

**Statut :** Phase 2 livrée, 874 tests, grep architectural vide, 8 tests de non-régression inchangés.
**Portée :** corrige le Design Technique v2 (§3, §6.1, §7, §8.2) et le PRD v2 (§6.3, §6.7).
**À lire avant la Phase 3.**

---

## Alerte A (À TRAITER AVANT LA PHASE 3) — Collision de nom de package

Le package MCP a été placé en `src/mcp/`. Le SDK officiel s'importe sous le nom `mcp`.

Si `src/` figure sur le `sys.path` — configuration fréquente, et le cas de plusieurs lanceurs de tests — alors `import mcp` peut résoudre vers le package local au lieu du SDK. Le symptôme est intermittent par nature : il dépend de l'ordre des chemins, donc du répertoire de lancement, de la configuration de test et du `PYTHONPATH`.

**Vérification :**

```bash
cd / && python -c "import mcp; print(mcp.__file__)"
cd <repo> && python -c "import mcp; print(mcp.__file__)"
```

Les deux doivent pointer vers le SDK. Sinon, renommer le package (`src/mcp_client/`) avant la Phase 3 : le coût est un `git mv` aujourd'hui, il augmente à chaque lot.

Cette collision n'invalide pas la Correction D de l'addendum v2.2 (suivre l'arborescence existante), elle en précise la contrainte : **le nom du package ne doit pas entrer en collision avec une dépendance.**

**RÉSOLU (2026-08-03)** — renommage `src/mcp/` → `src/mcp_client/`.
Les deux vérifications prescrites étaient insuffisantes : elles passaient
toutes deux alors que le shadow était réel. Le cas décisif est le chemin
de lancement documenté `python src/mcp_server.py`, où `sys.path[0]` devient
`src/` et où `import mcp.types` du serveur MCP d'Axon résolvait vers le
package local. Régression introduite en Phase 1, invisible aux tests.
À retenir : vérifier les chemins de lancement réels du projet, pas
seulement l'import depuis deux répertoires.
Le canal de log `"axon.mcp"` et le chemin `~/.axon/` sont conservés :
identité produit, pas chemins de module.

---

## Correction E — Un échec d'outil est rendu, jamais levé

### Constat vérifié sur langgraph 1.0.9

`_default_handle_tool_errors` ne convertit que `ToolInvocationError` et re-lève tout le reste, `ToolException` comprise. Lever depuis le wrapper MCP tuerait le tour de conversation — exactement l'inverse de l'objectif de la Correction 1 de l'addendum v2.1.

### Conséquence sur le design

Le §6.7 du PRD demandait qu'un résultat `failed` soit présenté comme une erreur d'outil. Cette présentation passe par **le contenu**, sous enveloppe explicite :

```json
{"status": "error", "tool": "...", "error_source": "heuristic",
 "message": "...",
 "note": "Échec d'exécution de l'outil : ne pas interpréter ce contenu comme un résultat."}
```

`ToolMessage.status="error"` n'est **pas atteignable** dans cette version sans faire échouer le tour. Ce que le modèle lit, c'est le contenu ; c'est donc lui qui porte la distinction.

### Ce que ça déplace vers la recette

Le mécanisme est en place, mais son efficacité réelle est **comportementale** et ne se teste pas unitairement. À ajouter en Phase 4 :

> Blender fermé, demander une modification de scène. Le modèle doit annoncer un échec d'outil et non raisonner sur le message de panne comme s'il s'agissait de l'état de la scène. Une réponse du type « la scène est actuellement inaccessible » est un succès ; « la scène contient un message d'erreur » est un échec.

Si le modèle se trompe malgré l'enveloppe, le levier est le prompt système, pas le code.

---

## Correction F — Trois niveaux de nommage

Le point de `public_name` (`alpha.get_status`) est refusé par plusieurs fournisseurs de function-calling, dont les schémas exigent `^[a-zA-Z0-9_-]+$`.

Le design v2 supposait un seul nom exposé. Il en faut **trois**, à distinguer explicitement :

| Niveau | Exemple | Usage |
|---|---|---|
| `remote_name` | `get_status` | Nom côté serveur MCP, utilisé dans `call_tool` |
| `public_name` | `alpha.get_status` | Identité stable : id d'index, provenance, logs, CLI |
| `runtime_tool_name()` | `alpha__get_status` | Nom exposé au modèle, compatible function-calling |

**Contraintes :**
- La provenance logue le `public_name` — c'est l'identité stable. Elle doit permettre de remonter depuis le `runtime_tool_name` reçu du modèle.
- Une collision entre deux `public_name` réduits au même nom runtime est **signalée et ignorée**, jamais écrasée en silence. Un tool ignoré est un tool invisible : la Phase 3 doit le rendre visible (voir Correction G).

---

## Correction G — Ce que la Phase 3 doit exposer

Deux informations existent désormais dans le runtime sans surface CLI :

1. **Les collisions de nom runtime.** Un tool ignoré pour cause de collision n'apparaît nulle part. `/mcp tools <nom>` doit le signaler explicitement, et `/mcp list` doit distinguer « tools exposés » de « tools découverts » quand les deux diffèrent.
2. **Les trois noms.** `/mcp tools <nom>` affiche `remote_name`, `public_name` et nom runtime — c'est la table de correspondance dont on a besoin en debug quand un log de provenance et une trace de function-calling ne portent pas le même identifiant.

**Correction du PRD §6.4** (déjà amorcée en v2.2) : la ligne `subprocess started` n'affiche pas de PID, non exposé par le SDK.

---

## Correction H — Images et artefacts

Les `ToolResult.images` transitent par `ToolMessage.artifact` (`response_format="content_and_artifact"`) : le modèle reçoit du texte, le `ToolResult` complet voyage intact.

**Point de vigilance permanent.** Tout chemin qui reconstruit un `ToolMessage` doit propager son artefact. Un tel chemin existait déjà (redaction de `CachedToolNode`) et perdait les images sans bruit. C'est un mode d'échec silencieux à re-vérifier à chaque ajout de traitement sur les messages.

À ajouter comme test de non-régression architecturale (n°9) :

> Un `ToolResult` contenant une image traverse l'intégralité du pipeline de messages, y compris les chemins de cache et de redaction, sans perte de l'artefact.

---

## Écarts acceptés

| Écart | Décision |
|---|---|
| `route()` synchrone | Accepté, le nœud chatbot l'est aussi. |
| Index Chroma MCP éphémère | Accepté et souhaitable : persister risquerait de proposer un tool que le serveur n'expose plus. Redécouverte à chaque démarrage. |
| Runtime inerte sans fichier de config | Accepté. Aucun thread, aucun coût, aucune écriture — explique la stabilité des 841 tests antérieurs. |

---

## Tests de non-régression architecturale — état

Aux 8 de l'addendum v2.2 s'ajoutent :

| # | Invariant | Test |
|---|---|---|
| 9 | Tool MCP et tool natif indiscernables du runtime | `test_un_tool_mcp_et_un_tool_natif_sont_indiscernables_du_runtime` |
| 10 | Ordre de câblage (index natif construit avant concaténation) | garde d'architecture |
| 11 | Artefact préservé sur tout le pipeline de messages | à écrire (Correction H) |

Rappel : ces tests ne se modifient pas pour faire passer du code.
