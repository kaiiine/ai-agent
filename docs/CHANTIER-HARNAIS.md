# Chantier « harnais » — rendre les mesures rejouables

Rédigé le 2 septembre 2026, après une journée passée à réfuter des affirmations
chiffrées du dépôt — dont trois écrites le matin même.

**Statut :** les quatre lots sont faits (2–7 septembre). A, B et D concluent
« ça reste » — mesuré, pas par prudence. **C trouve un vrai défaut** : le
routage de l'agent de code sert 60 % de ce qu'il faut, et un serveur MCP double
les manques. B ouvre un arbitrage rendu à
l'utilisateur (§0, point 6). Deux harnais servent de gabarit :
`outils/mesure_routage.py` et `outils/mesure_filet.py`.

---

## 0. En attente de Quentin — cinq points, aucun ne dépend du chantier

Consolidés ici parce qu'ils sont apparus à des moments différents d'une longue
session et qu'aucun ne ressortira tout seul au bon moment.

| # | Point | Pourquoi c'est bloqué |
|---|---|---|
| 1 | **Six étiquettes de groupe** sur les tours elliptiques de `mesure_filet.py` | demande la mémoire des conversations passées ; l'inventer fabriquerait une vérité terrain |
| 7 | **Deux tâches non étiquetées** dans `CORPUS-CODING.md`, et `seb` corrigé en `web` d'autorité sur la tâche Next.js | à confirmer ou corriger |
| ~~1bis~~ | ~~`CORPUS-CODING.md`~~ | **étiqueté le 7 septembre** — 60 tâches sur 62 |
| ~~2~~ | ~~`Settings().coding_model`~~ | **corrigé le 7 septembre** — la suite est entièrement verte |
| 3 | **Le commit** | tranché : Quentin committe lui-même, messages préparés, aucun trailer d'attribution |
| 4 | **`CORPUS-ROUTAGE.md` est public sur GitHub** avec un email et un nom réels, 3× chacun | indexable ; le nettoyer demande une seconde réécriture d'historique |
| 5 | **Clés fuitées** (Gmail, Slack, OpenAI) | rotation à faire côté fournisseurs |
| 6 | **Alias indexés pour les skills** : les retirer gagne 6,2 pts de rappel agrégé sur le jeu tenu à l'écart, mais sort `a11y-architect` et `seo-specialist` du budget quand la requête les DÉSIGNE | arbitrage entre rappel moyen et garantie ciblée — pas tranchable par la mesure ; détail dans `skills/retriever._document` |

Le point 1 conditionne une mesure — « le a priori du tour précédent bat-il le
recollage » — qui restera un fait catégorique sur six cas, jamais un taux. Les
quatre autres ne conditionnent rien de technique.

---

## 1. Le problème, en trois chiffres

```
130   affirmations chiffrées, figées dans les commentaires de 38 fichiers source
  2   harnais capables de rejouer une mesure
  2/2 sondages sur des affirmations existantes : la mesure ne tient plus
```

AXON mesure déjà beaucoup — c'est ce qui rend son code lisible. Le défaut n'est
pas l'absence de mesure, c'est que **les mesures meurent dans les docstrings**.

### Les deux sondages

Tous deux dans `src/skills/retriever.py`, choisis parce que ce fichier venait
d'être touché — pas parce qu'il était suspect.

**Sondage 1 — `pertinentes`.** La docstring affirmait :

```
dense seul                  rappel@1 55 %
lexical puis dense          rappel@1 75 %   ← justifiait l'ordre du code
```

Rejoué sur `tests/corpus_routage_skills.py`, l'ordre **s'inverse** :

```
lexical d'abord   rang 1  11/22        top 5  21/22
dense d'abord     rang 1  18/22        top 5  21/22
```

Le mécanisme que ce chiffre justifiait coûtait 32 points de rang 1 et ne rendait
rien au top 5 — la seule métrique que voit le modèle, puisque le catalogue en
montre cinq. Corrigé le 2 septembre.

**Sondage 2 — `_document`.** La docstring affirme :

```
description seule       4/10
+ nom + alias          10/10      ← justifie d'indexer les alias
```

Rejoué : **21/22 dans les deux cas**. L'ajout ne contribue plus rien au top 5.

### Ce que ces deux cas ont en commun

Aucun des deux n'est un bug. Ce sont des décisions de conception dont l'unique
argument est un chiffre qui n'est plus vérifiable dans ses propres termes : jeu
de référence disparu, métrique non précisée, corpus changé depuis. Une décision
justifiée par un chiffre mort est une décision justifiée par rien — et rien ne
le signale.

---

## 2. Ce qu'un harnais achète, et ce qu'il n'achète pas

Contre l'intuition « des harnais rendront AXON plus puissant ». Bilan factuel des
trois chantiers menés le 2 septembre, chacun ouvert par une mesure :

| Chantier | Ce que la mesure a produit |
|---|---|
| filet de rattrapage | a **empêché** d'écrire un empaquetage de schémas dans le catalogue |
| ellipse | a fait **retirer** un correctif sur `schedule_task` qui corrigeait un artefact |
| skills | a fait **supprimer** une couche de classement au lieu d'en ajouter une |

Bilan net : **du code en moins**. Un harnais ne produit pas de la puissance, il
produit deux choses :

- **il refuse ce qui ne servirait à rien**, avant que ce soit écrit ;
- **il avertit quand ce qui marchait cesse de marcher**, sans quoi la régression
  est silencieuse jusqu'à ce qu'un humain la voie à l'écran.

### Non-objectifs — ce que ce chantier ne résout pas

1. **L'écart de 20,5 points sur les skills.** Ce n'est pas un problème de
   classement : les 49 documents sont en anglais et nomment la *solution*, quand
   les requêtes sont en français et décrivent le *symptôme* (« tsc refuse de
   compiler » contre « TypeScript error resolution »). Cinq mécanismes de
   désambiguïsation ont déjà été mesurés sans qu'aucun ne gagne. Le combler
   demande d'écrire dans les skills, pas de mesurer.
2. **Le comportement du modèle.** `obtenir_outil` réclamé 1 fois sur 10, des
   arguments en `projectKey` inventés sur un schéma non devinable, la
   clarification préférée même quand l'alternative est déliée. Ces trois-là
   dépendent du modèle et de la forme de la surface d'outils, pas du routage.
3. **Un taux d'erreur sous 1 %.** Aucun harnais de cette taille ne l'établit. Ils
   établissent des faits catégoriques ; un taux demande quelques centaines de
   cas.

---

## 3. La règle de conception

> **Un chiffre dans un commentaire doit nommer le harnais qui le rejoue.
> Sinon c'est une anecdote.**

C'est la seule règle du chantier. Elle est plus importante que le nombre de
harnais écrits : elle transforme chaque futur commentaire chiffré en dette
visible plutôt qu'en autorité muette.

Corollaire opérationnel — trois catégories, trois traitements :

| Catégorie | Traitement |
|---|---|
| chiffre qui **justifie une décision de code** | harnais obligatoire |
| chiffre qui **raconte un incident vécu** (« vécu : … ») | rien à faire, c'est un fait daté |
| chiffre **invérifiable** (jeu perdu, métrique floue) | le dire, ou le supprimer |

La deuxième ligne compte autant que la première : ce chantier ne demande pas de
mesurer les récits, seulement les arguments.

---

## 4. Périmètre

Pas 130 harnais. **Un harnais par décision dont un chiffre est le seul argument,
et qui est sur le chemin chaud.** Par rayon d'impact décroissant :

| # | Fichier | Chiffres | État | Effort |
|---|---|---|---|---|
| A | `src/orchestrator/tool_retriever.py` | 24 | **FAIT** — 5 constantes balayées, corpus séparé en deux jeux | — |
| B | `src/skills/retriever.py` | ~6 | **FAIT** — 3 affirmations rejouées, 3 périmées | — |
| C | `src/agents/coding/tool_retriever.py` | 10 | **FAIT** — 62 tâches étiquetées, défaut trouvé | — |
| D | `src/infra/pont_fr_en.py` | 7 | **FAIT** — mesuré par ablation, il reste | — |

Hors périmètre : les 24 fichiers restants, dont l'essentiel des chiffres relève
du moteur de paris (`src/agents/quant/**`). Ils ont leur propre suite et ne sont
pas sur le chemin du routage.

---

## 5. Les lots

### A — `tool_retriever.py` : compléter le harnais existant

**Avant.** `mesure_routage.py --outils` rejoue trois affirmations : rang 1
(56,1 %), rappel étage 1, rappel réel (93,9 %). Vingt et une autres ne sont
rejouées par rien — notamment celles qui justifient `_MARGE_CLAUSE = 0.20`,
`_MAX_GROUPES_UNION = 8`, `_BUDGET_OUTILS = 16` et le découpage par clauses
(« 85,9 % → 86,6 % global, 73,9 % → 82,6 % multi-clauses »).

**Après.** Un mode `--constantes` qui, pour chaque constante réglable, rejoue le
balayage qui l'a fixée et signale si la valeur retenue est encore le maximum.

**Piège connu, à ne pas répéter.** Le balayage doit tourner sur un jeu de réglage
et être *constaté* sur un jeu tenu à l'écart — jamais choisi dessus. Le corpus
outils n'a pas cette séparation aujourd'hui ; la créer fait partie du lot.

**FAIT le 6 septembre.** Le corpus outils a désormais sa séparation, par hachage
de la requête comme pour les ellipses : **57 en réglage, 41 tenues à l'écart**.
Sans elle, toute constante était réglée sur le jeu qui servait aussi à la valider.

`--constantes` balaie les cinq constantes réglables sur le réglage seul, et ne lit
le jeu tenu à l'écart qu'en constat. Résultat :

| constante | verdict |
|---|---|
| `_TOP_GROUPS = 5` | optimale — 3 coûte 1,8 pt, 7 ne rend rien |
| `_MAX_GROUPES_UNION = 8` | optimale — 5 et 6 coûtent 3,5 et 1,8 pt |
| `_FAMILLES_MAX = 1` | optimale — 2 et 3 élargissent sans rien rendre |
| `_MARGE_CLAUSE = 0.20` | **inerte** — 93,0 % de 0,10 à 0,30, largeur identique |
| `_BUDGET_OUTILS = 16` | **12 semblait gratuit, il ne l'est pas** — voir ci-dessous |

**Le résultat qui compte.** Le balayage donnait 12 indiscernable de 16 sur les
DEUX jeux — même rappel, quatre outils de moins par tour. Appliqué, **trois
tests de non-régression tombent**, sur des tournures que `CORPUS-ROUTAGE.md` ne
contient pas (« ou en est ma copie de travail », « balance ca dans le channel
dev »). Les quatre outils achètent une assurance que le corpus réel ne mesure
pas.

C'est la leçon des deux jeux, transposée d'un cran : **un corpus unique ne
suffit pas non plus.** Le message d'alerte de `--constantes` le dit maintenant,
avec la commande à rejouer avant d'appliquer quoi que ce soit.

**Deux défauts d'instrument corrigés au passage** : le rapport signalait
`_MARGE_CLAUSE` « à revoir » pour +0,0 point (un instrument qui remonte du bruit
fait ignorer ses vrais signaux), et sa sortie était bufferisée — un balayage de
plusieurs minutes n'affichait rien avant la fin.

---

### B — `skills/retriever.py` : finir ce que les deux sondages ont ouvert

**Avant.** Deux affirmations vérifiées périmées, quatre autres jamais rejouées —
dont celle qui justifie d'écarter les ancres (« + ancres 9/10 ») et celle qui
sépare `aliases:` de `lexique:` (« sept phrases françaises ont suffi à… »).

**Après.** `mesure_routage.py --skills` couvre déjà rang 1 / top 3 / top 5 sur
les deux jeux. Y ajouter une comparaison des **variantes de document** —
description seule, + nom, + alias, + ancres — de sorte que la question « qu'est-ce
qu'on indexe » se rejoue au lieu de se citer.

**Après aussi.** Supprimer ou corriger la docstring de `_document`, dont le
chiffre est démenti. Ne pas la laisser en l'état : un chiffre faux est pire
qu'aucun chiffre.

**Fait quand** : `--skills --documents` rend le tableau des quatre variantes, et
la docstring de `_document` cite ce mode au lieu d'un chiffre de 2024.

---

### C — `coding/tool_retriever.py` : le routage de l'agent de code

**Avant.** Dix affirmations, aucune rejouable, et **aucun corpus de référence**
pour l'agent de code — contrairement à l'orchestrateur (`CORPUS-ROUTAGE.md`) et
aux skills (`tests/corpus_routage_skills.py`).

**Après.** Un corpus, avant tout harnais. Sans lui il n'y a rien à mesurer.
Source honnête : les requêtes réelles de `~/.axon/memory.db` adressées à l'agent
de code, étiquetées **par l'utilisateur** — l'assistant n'est pas vérité terrain
sur les intentions de l'utilisateur (leçon des 38 ellipses, § 7).

**FAIT le 7 septembre.** Le corpus existe — 62 tâches réelles extraites de
`~/.axon/memory.db`, étiquetées PAR L'UTILISATEUR, séparées par hachage en 36
réglage / 24 tenues à l'écart. `mesure_routage.py --coding` rend rappel,
complétude et **précision** — cette dernière n'existait nulle part ailleurs :
l'utilisateur ayant dit ce qui était NÉCESSAIRE, le superflu devient mesurable.

|  | réglage (36) | tenu à l'écart (24) |
|---|---|---|
| rappel des groupes attendus | 64,6 % | 60,0 % |
| tâches complètement servies | 38,9 % | **29,2 %** |
| précision | 73,6 % | 75,9 % |

Écart de 4,6 points entre les deux jeux : rien n'a été réglé dessus, et ça se voit.

**Le défaut, mesuré.** L'agent de code lie **29 outils en moyenne, jusqu'à 54** —
presque le double de l'orchestrateur (15,8) — et sert quand même 60 % de ce qu'il
faut. Il ne rate pas par ignorance :

| | tâches | outils liés | groupes manqués |
|---|---|---|---|
| un serveur MCP entre | 21 | 40,5 (dont 26,9 MCP) | **2,14** |
| aucun serveur MCP | 39 | 22,9 | 1,21 |

**Un serveur MCP prend 27 places et double les manques.** `graphe` est lié 20 fois
sans être demandé, pendant que `git` manque 24 fois et `filesystem` 21.

**CORRIGÉ le 7 septembre.** La cause n'était pas la taille du serveur mais les
GRAINES : `k=8` prenait les huit outils les plus proches, et un serveur les
raflait tous. Une graine par DOMAINE — `_DOMAINES_MAX = 5`, balayé sur le jeu de
réglage puis constaté sur le jeu tenu à l'écart :

|  | rappel | tâches complètes |
|---|---|---|
| avant, réglage | 64,6 % | 14/36 |
| après, réglage | **76,2 %** | **20/36** |
| avant, tenu à l'écart | 60,0 % | 7/24 |
| après, tenu à l'écart | **71,0 %** | **9/24** |

Ce qui se paie : la précision tombe de 75,9 à 61,2 % et la largeur monte de 31,0
à 35,3 outils. Compromis assumé — un outil en trop coûte des tokens, un outil
manquant coûte la tâche.

**Le contrepoids, imposé par le dépôt.** Élargi sans garde-fou, `shell` remontait
sur « lis le contenu de page.tsx » (rang 9) et
`test_lire_un_fichier_ne_tire_pas_le_shell` tombait. Lire un fichier ne doit pas
mettre `shell_run` à portée : le coût d'un faux positif n'y est pas en tokens.
D'où `_RANG_MAX_SI_AGIT = {"shell": 8}` — c'est `requires_top_rank` de
l'orchestrateur, transposé, pas un mécanisme neuf. Coût mesuré : 0,7 point de
rappel, une tâche complète sur 36.

C'est la leçon du lot A appliquée d'elle-même : le corpus du dépôt a attrapé ce
que les 60 tâches réelles ne voyaient pas.

**Deux défauts de format trouvés pendant l'étiquetage** : `attendu:` ne capturait
qu'UN mot (« notebook, filesystem » devenait « notebook, »), et `**attendu**:` en
gras ne se parsait pas du tout — une étiquette sur 62 perdue sans bruit.
`tests/test_corpus_coding.py` fige les deux.

---

### D — `pont_fr_en.py` : trancher un mécanisme déclaré inutile — **FAIT**

**Le périmètre reposait sur une confusion.** La phrase « n'apporte presque rien »
vient de `skills/retriever.py` et parle de l'index des SKILLS, où le pont n'est
pas utilisé. Elle ne disait rien de ses trois usages réels. Et les sept
« chiffres » du fichier sont des récits d'incident — le bug de sous-chaîne — pas
des arguments de conception.

**Mesuré par ablation**, en remplaçant `pont_linguistique` par l'identité :

| | avec | sans |
|---|---|---|
| étage 2 de l'orchestrateur, 98 requêtes réelles | 92/98 | **92/98** |
| suites de routage, 91 tests | 91 ✓ | **4 échecs réels** (3 MCP, 1 orchestrateur) |

**Verdict : il reste.** Inerte sur le routage natif — dont les documents de
groupe sont déjà en français — et porteur sur le MCP, dont les descriptions
viennent des serveurs en anglais. C'est ce que son intention annonçait ; personne
ne l'avait vérifié.

**Fait** : la mesure et la commande qui la rejoue sont dans la docstring du
module.

---

## 6. Ordre d'implémentation

1. **D d'abord.** Le plus petit, et le seul dont l'issue peut être une
   suppression. Commencer par retirer du code plutôt que par en ajouter donne le
   ton du chantier.
2. **B ensuite.** Le harnais existe déjà à 80 % ; il ne manque que les variantes
   de document. Et une docstring démentie traîne actuellement dans le dépôt.
3. **A ensuite.** Le plus gros rayon d'impact, mais il exige de créer une
   séparation réglage / tenu à l'écart sur le corpus outils — travail réel.
4. **C en dernier.** Bloqué sur un corpus qui n'existe pas et qui demande
   l'utilisateur. Ne pas le commencer avant que le corpus soit étiqueté.

Chaque lot est indépendant : s'arrêter après D, ou après B, laisse le dépôt dans
un état cohérent.

---

## 7. Règles de méthode, apprises à la dure

Elles ne sont pas décoratives : chacune vient d'une erreur commise le 2 septembre.

1. **Deux jeux, séparés avant tout réglage.** Un jeu unique a fait expédier comme
   un succès un mécanisme qui faisait 22/22 en réglage et 7/16 ailleurs.
2. **Le partage se fait par hachage, pas par choix.** `sha1(requête) % 10 < 6` se
   rejoue et ne s'arrange pas après coup.
3. **Déclarer les expositions.** Si on regarde le jeu tenu à l'écart et qu'on
   voit qu'une autre valeur ferait mieux, on l'écrit et on **ne déplace pas** le
   seuil. Exemple consigné dans `src/orchestrator/ellipse.py` : `< 14` battait
   `< 12` sur le jeu de validation, le seuil n'a pas bougé.
4. **L'assistant n'est pas vérité terrain.** Les 38 ellipses de
   `tests/corpus_ellipses.py` sont étiquetées par l'assistant, et le fichier le
   dit en tête. Un corpus d'intentions doit être étiqueté par l'utilisateur.
5. **Vérifier que le détecteur mord.** Un test qui rend « 0 faute » sans qu'on
   ait montré qu'il sait en trouver une ne prouve rien. Voir
   `tests/test_doc_outil_fidele.py::test_le_detecteur_voit_un_parametre_invente`.
6. **Un harnais qui court-circuite le chemin réel mesure autre chose.**
   `mesure_filet.py` a d'abord signalé un bug de JSON brut inexistant : il
   n'appelait pas la réparation que `graph.py` applique. Corrigé, le défaut
   disparaît.
7. **Un instrument peut mentir par son étiquette.** La première version de
   `mesure_filet.py` affichait « RÉCLAMÉ » pour un outil appelé sans passer par
   l'échappatoire, ce qui faisait lire celle-ci comme utilisée alors qu'elle ne
   l'était jamais.
8. **Le harnais doit être suspecté avant le sujet.** Trois fois dans la même
   journée, une mesure a raconté une histoire fausse à cause de l'instrument et
   non du système :

   | ce que la mesure disait | ce qui était vrai |
   |---|---|
   | « bug de JSON brut » | l'instrument court-circuitait la réparation |
   | « `surveiller` confondu avec `schedule_task` » | l'instrument déliait l'outil attendu |
   | « gemini rattrape 0/4 » | 9 appels sur 14 en 429 : tirés **en parallèle** |

   D'où la question réflexe à poser à tout nouveau harnais, avant de lire son
   résultat : **est-ce que je mesure en série ou en parallèle, et est-ce que ça
   change le chiffre ?** Puis : est-ce que je reproduis le chemin réel, et
   est-ce que mon montage crée la condition que je crois observer ?
9. **Chercher le signal avant d'en construire un.** Trois corrections de la
   journée ont réutilisé un signal DÉJÀ calculé plutôt que d'ajouter un
   mécanisme à côté :

   | question posée | signal existant réemployé | ce qu'on n'a pas écrit |
   |---|---|---|
   | ce tour est-il elliptique ? | `keywords` / `soft_keywords` des groupes | une liste de marqueurs de continuation |
   | quelle skill montrer ? | les alias, déjà dans le document indexé | une surcouche lexicale devant le dense |
   | ce tour vise-t-il Slack ? | le rang 1 de l'étage 1, déjà calculé | un détecteur d'intention de plus |

   La question réflexe : **ce signal existe-t-il déjà ailleurs dans le
   pipeline ?** Un mécanisme parallèle diverge du jour où l'un des deux bouge —
   et il faut le régler, donc le surajuster.
10. **Un seuil se balaie, il ne se choisit pas.** Et le balayage s'écrit à côté
    du seuil : `rang ≤ 2` paraissait un compromis raisonnable pour l'exclusion
    Slack ; mesuré, il ne récupérait aucun cas légitime de plus et multipliait
    les exclusions accidentelles par 4,5. Sans le tableau dans le code, un
    lecteur le reproposerait.

---

## 8. Coûts et risques

**Coût en tokens.** Un harnais hors ligne est gratuit et entre dans la suite. Un
harnais qui appelle un modèle coûte des appels, varie d'une exécution à l'autre,
et doit rester **hors** de la suite — c'est pourquoi `mesure_filet.py` vit dans
`outils/` et non dans `tests/`.

**Risque principal : le harnais devient la cible.** Optimiser un chiffre plutôt
que le service rendu. Deux protections : le jeu tenu à l'écart, et le fait de
mesurer *ce que le modèle reçoit* (rappel réel, top 5) plutôt que *ce que le
routeur classe* (rang 1). Mesuré : l'étage 1 donne 84,7 % là où le modèle reçoit
en fait le bon outil 93,9 % du temps — optimiser le premier aurait été optimiser
la mauvaise pièce.

**Risque secondaire : les garde-fous empilés.** Ce chantier n'ajoute pas de
gardes dans le code de production ; il ajoute des instruments dans `outils/` et
des tests déterministes dans `tests/`. Aucun lot ne doit introduire de branche
conditionnelle dans le chemin chaud.

**Estimation.** D : une demi-journée. B : une journée. A : deux jours, dont un
pour le corpus. C : bloqué sur l'étiquetage utilisateur, puis une journée.

---

## 9. Ce qui reste ouvert et n'appartient pas à ce chantier

- Les 20,5 points sur les skills — travail d'écriture dans les 49 documents, et
  les deux jeux existants sont désormais brûlés pour cette question : il en
  faudrait un troisième.
- La relecture par l'utilisateur des 38 étiquettes d'ellipse.
- `mesure_filet.py --backend gemini` et `--backend mistral` : savoir si
  `gpt-oss:120b` est un plafond ou un choix. Gratuit, une commande, et c'est le
  seul levier mesuré qui touche à la puissance plutôt qu'à la non-régression.
- `test_le_modele_de_code_par_defaut_suit_le_yaml` : `Settings().coding_model` ne
  lit pas le YAML. Seul échec de la suite depuis le début, sans rapport avec le
  routage.
