# Routing des tools Axon — spec v5

Révision de la v4. Deux changements de fond :

- une partie de l'arbitrage group-bind / search-as-tool **est déjà tranchée par
  l'arithmétique**, sans rien construire ;
- ce qui reste ouvert n'est pas surtout la latence, mais une question de
  **justesse** que la v4 classait en alarme de performance.

Et une inversion d'ordre : le gain mesuré de BM25 ne passe pas derrière une
question d'architecture encore ouverte.

---

## 1. La discipline, non négociable

> **Le held-out est écrit avant de toucher aux documents de groupe, et n'est
> jamais relu pendant le réglage.**

Mesuré deux fois cette semaine : un mécanisme à **8/8 en réglage** tombait à
**3/8 en held-out**.

> **Aucune conclusion n'entre dans cette spec sans mesure sur le dépôt réel.**

La v2.2 tranchait par revue théorique. La v3 a corrigé ça pour BM25/dense, puis a
elle-même affirmé sans mesure que `search_tools` valait mieux que `routing_miss`
et que group-bind était plus rapide. La v4 a relevé ces deux trous — à juste
titre. La v5 en ferme un par le calcul et instrumente l'autre.

---

## 2. Ce qui est mesuré et acquis

| Constat | Mesure | Conséquence |
|---|---|---|
| Le dense est surajusté au corpus de référence | 17/22 rang 1 sur référence, **3/10 hors corpus** | BM25 devient le signal principal |
| BM25 seul généralise | **21/22** sur référence, **8/10** hors corpus | Étape livrable seule, sans prototypes ni fusion |
| L'étage 1 ne discrimine pas les requêtes courtes | 7 groupes dans un écart de **0.04** ; `calendar` 5e sur sa propre requête | C'est le défaut à corriger, pas une impression |
| Le stemming manque | `rappelle` ne matche pas `rappeler` — seule régression BM25 mesurée | Snowball FR obligatoire |
| Le plancher de schémas dépasse Groq | **30 outils, 12 731 tokens** sur une requête réelle, + 1 862 de prompt système | Budget par backend, et §4 ci-dessous |
| Portes déterministes et mots-clés fonctionnent | `_RECURRENCE_INTENT`, `_money_intent`, `_coding_intent`, liste `slack` | Conservés, jamais remplacés par du scoring |

Le chiffre du plancher corrige celui de la v3 (23 outils / 8 345 tokens, mesuré
sur une requête plus étroite). **Le plancher est pire que ce qu'on croyait.**

---

## 3. Les deux architectures

**Group-bind** — portes / mots-clés / BM25 → groupe → bind de tous ses tools
éligibles → un appel LLM. Zéro aller-retour, mais le schema de tout un groupe est
transmis même si un seul tool sert.

**Search-as-tool** — un seul tool exposé (`search_tools`) → le modèle décide s'il
cherche → recherche sur le catalogue complet → 2-5 tools bindés → second appel.
Un aller-retour de plus, uniquement quand une recherche est nécessaire.

Les portes déterministes et les mots-clés s'appliquent **en amont des deux**, à
l'identique. Ce n'est pas ce qui est comparé.

---

## 4. Ce que l'arithmétique tranche déjà

Requête réelle, « envoie un mail à Paul pour décaler la réunion » :

```
group-bind          30 outils    12 731 tokens de schémas
search, 1er appel    1 outil        307
search, 2e appel     3 outils     1 589
prompt système                    1 862   (dans les deux cas)
```

Confrontés au plafond de **8 000 TPM** de Groq :

| | total | verdict |
|---|---|---|
| group-bind | 14 593 | **impossible** |
| search, 1er appel | 2 169 | passe |
| search, 2e appel | 3 451 | passe |

**Conclusion, sans rien construire :** sur Groq, group-bind ne peut pas
fonctionner. La question n'y est pas « lequel est plus rapide » mais « lequel est
possible ».

Cela valide le `routing_mechanism` **par backend** de la v4 : ce n'est pas de la
sur-ingénierie, c'est une contrainte arithmétique. Sur Gemini ou `ollama_cloud`,
où les deux tiennent, le choix reste ouvert.

---

## 5. Ce qui reste ouvert — et ce n'est pas d'abord la latence

Search-as-tool ne change pas seulement le coût : il change le **mode d'échec**.

| | si le routage se trompe |
|---|---|
| group-bind | le modèle a les **mauvais** tools — il improvise, mais il a quelque chose |
| search-as-tool | l'état par défaut est **aucun tool** — s'il ne cherche pas, il répond de mémoire |

Le problème déclaré d'Axon est « les tools ne remontent pas ». Search-as-tool
échange *parfois les mauvais tools* contre *aucun tool si le modèle ne remarque
rien*. Pour un agent qui envoie des mails et lance des commandes, répondre de
mémoire est le pire des deux.

La v4 classe la fréquence de recherche en alarme de latence. C'est d'abord une
**métrique de justesse** :

> sur les requêtes qui nécessitaient un tool, combien de fois le modèle a-t-il
> effectivement cherché ?

Si c'est 70 %, search-as-tool perd 30 % des actions — quel que soit son avantage
en tokens. Et c'est précisément l'hypothèse que la v3 avait avancée sans mesure
(« un modèle cherche bien une capacité »).

---

## 6. Plan de mesure

### 6.0 Held-out — préalable absolu

Écrit avant toute modification de code ou de document. Couvre : requêtes simples,
requêtes sans tool nécessaire, multi-intentions, noms de tools cités, tours
elliptiques, tools proches, opérations sensibles, formulations bilingues, hors
distribution. Jamais relu pendant le réglage.

### 6.1 Budget par backend — indépendant, urgent

Bug bloquant réel aujourd'hui, sans rapport avec le choix d'architecture.

```python
BUDGET_SCHEMAS: dict[str, int] = {
    "groq":         4_000,
    "gemini":      40_000,
    "ollama_cloud": 40_000,
    "mistral":     20_000,
    "nvidia":      20_000,
}
```

Sélection incrémentale, sur les tools éligibles et non encore sélectionnés :

```python
selected_tool_ids = set(TOOLS_TOUJOURS_BINDES)
budget = sum(cout[t] for t in selected_tool_ids)

for groupe, _ in classement:
    nouveaux = tools_eligibles[groupe] - selected_tool_ids
    if not nouveaux:
        continue
    cout_ajout = sum(cout[t] for t in nouveaux)
    if budget + cout_ajout > BUDGET_SCHEMAS[backend]:
        continue          # pas `break` : un groupe plus petit peut tenir après
    selected_tool_ids |= nouveaux
    budget += cout_ajout
```

`continue` et non `break` : le classement porte sur la pertinence, pas sur le
coût. Coût réservé dès le départ pour les tools toujours bindés. Si aucun groupe
ne tient : comportement explicite (§9), jamais une sélection vide silencieuse.

### 6.2 BM25 + stemming — le gain acquis, livré sans attendre

```python
def normaliser(texte: str) -> list[str]:
    texte = unicodedata.normalize("NFD", texte.lower())
    texte = "".join(c for c in texte if unicodedata.category(c) != "Mn")
    return [raciniser(m) for m in re.findall(r"[a-z0-9]+", texte)]
```

BM25 standard, `k1 = 1.5`, `b = 0.75` — défauts éprouvés, à ne pas toucher sans
mesure séparée. Document de groupe inchangé : `covers` + noms de tools +
mots-clés + `extend()`.

Ordre des sources, inchangé pour les deux premières :

```
1. portes déterministes   → forcent un groupe
2. mots-clés littéraux    → conservés
3. BM25 sur les groupes   → remplace le dense comme signal principal
4. dense                  → conservé, fusionné plus tard si nécessaire (§6.5)
```

**Critère d'arrêt** — si les trois sont atteints sur le held-out, s'arrêter là et
mesurer en usage réel avant d'ajouter quoi que ce soit :

- rang 1 ≥ 17/22 (le dense actuel sur le corpus de référence)
- aucun groupe ne perd sa requête canonique
- aucun frottement sur le quotidien (`ls`, `git status`, lancer les tests)

### 6.3 Sonde de comportement — avant tout A/B

Bien moins chère que cinq backends × deux architectures : **un backend, une
demi-journée.**

Binder **uniquement** `search_tools`, passer le held-out, et compter deux nombres :

1. sur les requêtes qui **nécessitent** un tool → combien de fois le modèle
   cherche
2. sur celles qui n'en nécessitent **aucun** → combien de fois il cherche quand
   même

Le premier est un **taux de rappel d'action**. S'il est bas, search-as-tool est
disqualifié avant qu'on ait construit quoi que ce soit, et le §6.4 n'a pas lieu.
S'il est haut, l'A/B complet devient justifié.

À mesurer sur au moins deux modèles de familles différentes : c'est un
comportement de modèle, pas une propriété du code.

**Si le taux est limite** — ni clairement haut, ni clairement bas — essayer une
ou deux reformulations de la description de `search_tools` avant de conclure. Le
taux auquel un modèle décide de chercher dépend beaucoup de la façon dont l'outil
est décrit, pas seulement du modèle.

Constaté aujourd'hui sur un autre cas : le skill `browser-driving` gagnait ou
perdait toutes les requêtes françaises selon sa description et sa portée
déclarée. Disqualifier une architecture sur une seule formulation malchanceuse
serait la même erreur.

### 6.4 A/B group-bind vs search-as-tool — si la sonde le justifie

Sur le held-out, par backend :

| Métrique | group-bind | search-as-tool |
|---|---|---|
| bon tool trouvé | | |
| **cherche quand il le fallait** | n/a | |
| tokens totaux (schémas + réponses) | | |
| latence p50 / p95 | | |
| appels LLM par tour | | |
| dépassement de budget | | |

Décision **par backend** :

- Groq : tranché par le §4, search-as-tool par défaut.
- Ailleurs : group-bind reste par défaut sauf si search-as-tool réduit les tokens
  **sans** dégrader le rappel d'action ni la latence perçue.
- Cas mixte attendu : porte déterministe ou mot-clé → group-bind direct, le
  groupe est déjà connu, aucune recherche nécessaire.

### 6.5 Fusion dense + BM25 — si des trous subsistent

Le cas qui la justifie est mesuré : « compare en profondeur Postgres et
MongoDB » n'a **aucun terme lexical** commun avec le document de `search`. BM25
le classe 12e. C'est là que le dense rattrape.

```python
def rrf_pondere(sources: list[tuple[list[str], float]], k: int = 60):
    scores: dict[str, float] = {}
    for classement, poids in sources:
        for rang, groupe in enumerate(classement):
            scores[groupe] = scores.get(groupe, 0.0) + poids / (k + rang + 1)
    return sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
```

- **Collapse avant fusion** : un vote par groupe et par générateur. Un groupe ne
  doit jamais recevoir un nombre de votes proportionnel à son nombre de
  prototypes ou de tools.
- Poids BM25 / dense à parité au départ, à recalibrer sur mesure.
- `k = 60` en config. Sur 26 groupes, se comporte presque comme un vote pondéré
  direct — à vérifier, pas à supposer.
- Portes et mots-clés entrent en `mandatory_include`, **hors** fusion : ce ne sont
  pas des votes de plus.

---

## 7. `search_tools` — règles

- Un seul usage par tour utilisateur ; le second est refusé.
- Les groupes ou tools déjà proposés sont **exclus** du second périmètre : sans
  ça on resélectionne ce qui vient d'être jugé insuffisant.
- Ne peut ni élargir les permissions, ni faire apparaître un tool inéligible. Le
  filtrage s'applique **avant** que les résultats soient rendus, pas après.
- Réutilise le moteur BM25 du §6.2, appliqué au catalogue complet plutôt qu'aux
  groupes — pas un second mécanisme à écrire.

---

## 8. Routing et autorisation, séparés

Valable quelle que soit l'architecture :

```
recherche sans résultat   → aucun tool pertinent trouvé
authorization_required    → tool trouvé, permission manquante
authorization_denied      → tool trouvé, action refusée
confirmation_required     → tool trouvé, confirmation nécessaire (shell_run…)
```

Un tool connu mais non autorisé ne déclenche **jamais** une nouvelle recherche —
relancer un retrieval ne résout pas une autorisation. Ces branches routent vers
`authorisation.py` / `confirmation.py`, déjà en place.

---

## 9. Si rien ne tient dans le budget

Jamais de sélection vide silencieuse. Comportement explicite : scinder le groupe,
basculer sur search-as-tool si le backend le permet, ou rendre une réponse
contrôlée signalant l'impossibilité — jamais un appel LLM sans les tools requis.

---

## 10. State

```python
class AxonState(TypedDict):
    messages: list

    routing_mechanism: str          # "group_bind" | "search_as_tool", résolu par backend
    selected_groups: list[str]
    selected_tool_ids: list[str]
    attempted_groups: list[str]

    previous_selected_groups: list[str]
    pending_action_group: str | None
    last_called_tool: str | None

    tool_search_attempts: int
    routing_turn_id: str
```

`routing_turn_id` distingue un retry du même message utilisateur (ne pas
réinitialiser) d'un nouveau tour (réinitialiser `selected_*`, `attempted_groups`,
`tool_search_attempts`). `routing_mechanism` est résolu une fois par backend, pas
recalculé à chaque tour.

Le state ne contient que du sérialisable ; le binding se reconstruit dans le nœud
LLM.

---

## 11. Métriques

- **Rang** du bon groupe, pas seulement sa présence : aujourd'hui `calendar` est
  présent au rang 5 et ça masque le défaut.
- Rappel d'action en mode search-as-tool (§6.3) — la métrique qui décide.
- Tokens par tour, ventilés schémas / réponse, par backend et par mécanisme.
- Latence p50 / p95, par backend et par mécanisme.
- Appels LLM par tour.
- Fréquences distinctes de `authorization_required` / `denied` /
  `confirmation_required`, jamais agrégées avec un échec de routing.

---

## 12. En réserve — reporté, pas rejeté

| Reporté | Ce qui le déclencherait |
|---|---|
| Prototypes multiples par groupe | BM25 + dense laissent une classe de requêtes hors d'atteinte |
| Prototypes issus des logs, curation, versionnement | Les prototypes manuels ont prouvé leur gain |
| Distinction invocation / mention / négation | Un cas réel où charger le mauvais groupe a coûté quelque chose |
| Calibration fine des poids RRF | Le corpus d'éval et la télémétrie existent |
| Prior conversationnel élargi | Un cas mesuré de tour elliptique mal routé |

---

## 13. Ordre d'exécution

1. **Held-out** — avant tout.
2. **Budget par backend** (§6.1) — bug bloquant, indépendant.
3. **BM25 + stemming** (§6.2) — gain mesuré, ne pas le retarder derrière une
   question ouverte. Mesurer, et **s'arrêter si les trois seuils sont atteints**.
4. **Sonde de comportement** (§6.3) — un backend, une demi-journée.
5. **A/B complet** (§6.4) — seulement si la sonde ne disqualifie pas
   search-as-tool.
6. **Fusion RRF** (§6.5) — si des trous subsistent.
7. **Réserve** (§12) — quand un déclencheur se présente.

La différence avec la v4 tient à l'étape 3 : elle plaçait l'A/B avant la
livraison de BM25. Or BM25 est mesuré, faisable en une journée, et corrige le
défaut dont on se plaint. Le retarder derrière une hypothèse d'architecture,
c'est différer un gain acquis.
