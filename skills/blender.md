---
name: blender
description: Blender scène 3D mesh matériaux lumières caméra animation rendu export GLB bpy
aliases: [bpy, scene3d]
scope: [coding, orchestrator]
anchors: [crée une scène 3D dans blender, modélise un objet en 3D, fais-moi une scène qui bouge pour mon site, ajoute une lumière et une caméra à la scène, exporte la scène en GLB, anime un objet dans blender, fais un rendu 3D, mets ce logo en 3D]
---

# Skill — Blender via MCP

Règles de travail quand des tools Blender sont disponibles. Écrites d'après des échecs observés en session réelle : chacune corrige une erreur qui a réellement coûté du temps.

---

## 1. Règle absolue — jamais de monolithe

**Un appel `execute_blender_code` = une étape courte.** Jamais 130 lignes en un bloc.

Raison : une seule ligne fautive annule tout le bloc. Si ce bloc commence par un nettoyage de scène, chaque échec détruit le travail déjà fait, et l'itération devient une boucle sans progression.

Découpage type :

```
appel 1  →  import / création de la géométrie      →  inspecter
appel 2  →  matériaux                              →  inspecter
appel 3  →  animation                              →  inspecter
appel 4  →  lumières et caméra                     →  screenshot
appel 5  →  export
```

Après chaque appel, vérifier le résultat avant d'enchaîner. Un appel qui échoue ne doit faire perdre que son étape.

## 2. Ne jamais supprimer la scène sans y avoir été invité

```python
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete()          # ❌ jamais par réflexe
```

L'utilisateur peut avoir du travail en cours. Le nettoyage se demande, ou se limite à ce qu'on a soi-même créé.

En cas d'échec au milieu d'une construction : **reprendre à l'étape ratée**, pas repartir de zéro. Inspecter la scène pour savoir ce qui existe déjà.

## 3. Read-before-write

Avant toute modification d'un objet existant, **inspecter la scène** pour obtenir les noms réels.

```
❌  "j'ai créé un cube, il doit s'appeler Cube"
✅  inspection de scène → l'objet s'appelle "MonCube" → le modifier
```

Blender conserve l'état du monde ; la conversation ne conserve qu'une intention. L'utilisateur a pu renommer, supprimer, dupliquer entre deux messages. La mémoire conversationnelle n'est jamais une source fiable sur l'état de la scène.

## 4. Ne pas supposer l'API — l'interroger

L'API `bpy` change beaucoup entre versions majeures. Une valeur d'enum ou un attribut mémorisé peut ne plus exister.

**Devant une erreur d'enum ou d'attribut, interroger l'API plutôt que deviner :**

```python
# valeurs valides d'un enum
print(bpy.context.scene.render.bl_rna.properties['engine'].enum_items.keys())

# attributs réellement disponibles
print([a for a in dir(bpy.context.scene.eevee) if not a.startswith('_')])

# version en cours
print(bpy.app.version_string)
```

Le message d'erreur de Blender liste souvent les valeurs valides — les lire avant de proposer autre chose.

**Une correction apprise dans la conversation ne se ré-oublie pas.** Si un premier essai révèle que `BLENDER_EEVEE` n'existe pas et que la bonne valeur est `BLENDER_EEVEE_NEXT`, tous les appels suivants utilisent la bonne valeur. Régresser vers une valeur déjà invalidée est l'erreur la plus coûteuse : elle transforme l'itération en boucle.

## 5. Jamais de `try/except` qui avale une erreur

```python
try:
    bpy.ops.import_curve.svg(filepath=path)
except Exception as e:
    print('Import error:', e)      # ❌ le script continue sur une scène vide
```

Le script poursuit alors sur des données absentes et échoue vingt lignes plus loin, avec un message sans rapport. Laisser l'erreur remonter : elle sera renvoyée telle quelle et permettra un diagnostic direct.

## 6. Export GLB — ce qui compte et ce qui ne compte pas

Un GLB transporte **géométrie, matériaux, animations**. Rien d'autre.

| À faire | Sans effet sur le GLB |
|---|---|
| Géométrie et modificateurs appliqués | Moteur de rendu (`scene.render.engine`) |
| Matériaux (préférer Principled BSDF) | Résolution de rendu |
| Animations sur keyframes | Bloom, glare, post-traitement |
| Échelle et transformations appliquées | Paramètres d'échantillonnage |

Toute configuration de rendu dans un script destiné à un export GLB est du code mort — et du code mort qui peut faire échouer le script avant l'export. À supprimer.

**Cas particulier des lumières et caméras.** Pour un usage web (React Three Fiber, three.js), elles sont gérées côté runtime, où elles sont bien plus contrôlables. Les créer dans Blender sert à valider visuellement ; elles n'ont pas besoin d'être exportées. En dire un mot à l'utilisateur plutôt que de décider seul.

**Limites d'export à connaître :** les shaders Emission passent mal, préférer Principled BSDF avec émission. Les systèmes de particules ne s'exportent pas — les convertir en géométrie réelle si elles doivent survivre. Les modificateurs procéduraux nécessitent `export_apply=True`.

## 7. Boucle de feedback visuel

Le screenshot de viewport est le principal moyen de vérifier son propre travail.

```
créer / modifier  →  screenshot  →  regarder  →  corriger  →  screenshot
```

À utiliser dès qu'un jugement visuel est en cause : cadrage, composition, éclairage, proportions. Ne pas affirmer qu'une scène est correcte sans l'avoir regardée. Une inspection de scène donne des noms et des coordonnées, pas une apparence.

## 8. Logo 2D vers 3D — deux pipelines distincts

Ne pas confondre. Le choix se fait d'après la source, et se dit à l'utilisateur.

**Source vectorielle (SVG) ou raster à silhouette nette** → vraie géométrie :

```
SVG → import en courbes → extrude/bevel sur la courbe → conversion en mesh
```

Extruder la **courbe** avant conversion, pas après : une fois convertie en mesh, l'extrusion propre est bien plus difficile. Les trous du logo doivent être de vrais trous dans le maillage.

**Source raster complexe** (dégradés, photo, détails fins) → plaque texturée :

```
plan + texture avec alpha + Solidify
```

Résultat honnête, mais **ce n'est pas une silhouette extrudée** : c'est un rectangle avec une image dessus. Le dire explicitement plutôt que de laisser croire au contraire.

Si seul un PNG est disponible et qu'une vraie géométrie est souhaitée, proposer la vectorisation préalable au lieu de produire une plaque en la présentant comme un logo 3D.

## 9. Écueils fréquents

**Contexte des opérateurs.** `bpy.ops.*` dépend du contexte actif. Préférer l'API de données quand elle existe :

```python
# ✅ robuste
mesh = bpy.data.meshes.new("M"); obj = bpy.data.objects.new("O", mesh)
bpy.context.collection.objects.link(obj)

# ⚠️ dépend du contexte, échoue silencieusement ou sur le mauvais objet
bpy.ops.mesh.primitive_cube_add()
```

Quand `bpy.ops` est nécessaire, définir explicitement l'objet actif et la sélection avant l'appel.

**Échelle non appliquée.** Un `obj.scale = (0.5, 0.5, 0.5)` non appliqué produit des surprises à l'export et sur les modificateurs. Appliquer les transformations avant export.

**Chemins de fichiers.** Créer le répertoire de destination avant d'écrire (`os.makedirs(..., exist_ok=True)`). Les chemins contenant des espaces fonctionnent, mais doivent être correctement échappés dans le code généré.

**Indentation.** Le code est transmis sous forme de chaîne : une indentation incohérente produit `unexpected indent` et rien ne s'exécute. Blocs courts et indentation uniforme réduisent fortement ce risque.

## 10. Erreur de connexion

Si un appel renvoie un message du type « impossible de se connecter à Blender » :

**Ce n'est pas un résultat, c'est une panne.** Ne pas raisonner dessus comme sur l'état de la scène. Ne pas relancer en boucle. Signaler à l'utilisateur que Blender semble fermé ou que l'addon n'écoute plus, et attendre.

## 11. Checklist avant export

- [ ] La scène a été inspectée, les noms sont réels
- [ ] Les transformations sont appliquées
- [ ] Les matériaux sont exportables (Principled BSDF)
- [ ] Aucune configuration de moteur de rendu dans le script
- [ ] Le répertoire de destination existe
- [ ] Un screenshot a confirmé le résultat visuel