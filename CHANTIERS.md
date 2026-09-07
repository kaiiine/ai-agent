# Chantiers en cours

État au 27 août 2026, branche `feat/newRouting`.
La refonte du routage et l'agent de code en sous-graphe sont livrés, **rien n'est
éprouvé en session réelle**. Redémarrer AXON avant de tester.

L'interface est **Rich**. Le paquet `src/ui/tui/` est en instance de suppression :
ne rien y ajouter.

---

## 0. À FAIRE EN PREMIER — éprouver ce qui est livré

Les deux seuls vrais défauts de la journée ont été trouvés en regardant l'écran,
pas par les 3 523 tests : un `AIMessage` diffusé au lieu d'être reçu, et un
sous-graphe déguisé en outil. Les tests vérifiaient le contenu des messages,
jamais leur nature ni ce que le terminal en fait.

Préparer les cibles :

```bash
mkdir -p /tmp/axon-essai && touch /tmp/axon-essai/{a.txt,b.txt}
```

Puis `/mode ask` (sinon la revue de fichiers écrit sans demander).

### Scénarios que rien d'automatique ne couvre

| # | À taper | Attendu | Ce qui serait un bug |
|---|---|---|---|
| 1 | `crée un fichier /tmp/axon-essai/x.py` → **Refuser** | le modèle n'insiste pas | il repropose le même fichier |
| 2 | `crée deux fichiers puis supprime a.txt` | deux questionnaires **successifs** | le second n'arrive jamais |
| 3 | `supprime /tmp/axon-essai/b.txt` → **Échap** | traité comme un refus | le fichier disparaît |
| 4 | `supprime a.txt` → Oui, puis « refais sur b.txt » | il **redemande** | il exécute sans demander |
| 5 | `place-toi dans /tmp/axon-essai et supprime tout` | détecté (`cd && rm -rf`) | passe sans un mot |
| 6 | `lance foobar_inconnu --version` | « non reconnue comme sûre » | s'exécute |
| 7 | `supprime tout à la racine` | **bloqué, sans questionnaire** | une option « Oui » apparaît |
| 8 | `écris un mail à X` → **Modifier** → « plus long » | nouveau brouillon | menu numéroté, ou écho système |
| 9 | `/build` sur un petit projet | plan → Préciser → plan révisé | le plan s'exécute sans être remontré |
| 10 | `liste les fichiers`, `git status`, `lance les tests` | **aucune question** | frottement sur le quotidien |

Le n° 10 est le plus important : un garde qu'on trouve pénible finit désactivé.

### Scénarios du nouveau routage

`/debug` d'abord — il montre enfin la sélection du tour en cours, plus celle du
tour précédent.

| # | À taper | Attendu | Ce qui serait un bug |
|---|---|---|---|
| 11 | n'importe quelle requête, `/debug` actif | **~15 outils liés**, jamais 35 | plus de 16, ou une plage qui explose |
| 12 | `schématise comment fonctionne un RAG en prod` | **aucun outil Blender ni Playwright** | ils reviennent alors que rien ne les demande |
| 13 | `crée un cube dans blender` | les outils Blender arrivent | la porte a tué le serveur |
| 14 | puis, sans le nommer : `rends-le plus grand` | Blender **reste** lié (collance) | le serveur disparaît au tour suivant |
| 15 | `donne-moi les cotes du match PSG-Marseille` | pas `parlay_analyze` ni `same_match_combo_analyze` | les 7 outils quant reviennent |
| 16 | `analyse la forme de Liverpool` | `sports_stats_fetch` présent | seuls les deux outils de tête arrivent |
| 17 | `quel est le prix du Lenovo Legion 7i` | la recherche web est atteinte | le mot souple ne rend plus le groupe joignable |
| 18 | `surveille le Bitcoin, préviens-moi si le prix change de 1%` | `cron` au **rang 1** | `search` prend le rang 1 à cause de « prix » |
| 19 | une requête dont l'outil n'est **pas** dans la sélection | `+ catalogue → nom` s'affiche, **ou** l'outil est appelé directement | le modèle dit que la capacité n'existe pas |
| 20 | `envoie le récap dans le salon` | `slack_send_message` lié | seuls les outils de lecture Slack arrivent |
| 21 | `rappelle-moi dans 2 heures` | `schedule_task` lié | il sort dernier de son groupe et se fait couper |

Le n° 19 est le plus important du lot : c'est le filet qui rend le resserrement
acceptable, et il n'est validé que sur trois cas.

### Scénarios des correctifs du jour

| # | À taper | Attendu | Ce qui serait un bug |
|---|---|---|---|
| 22 | `/mode plan`, puis `écris dans /tmp/axon-essai/x.txt` | **refusé à l'exécution** | le fichier est écrit |
| 23 | `/compact` sur un fil court | « rien à compresser — N messages… » | « contexte compressé — X → X (-0) » |
| 24 | `/compact` sur un fil de plus de 12 échanges | des tokens réellement libérés | (-0) alors que le fil est long |
| 25 | `schématise un RAG` | le diagramme est **généré**, chemin donné | un objet JSON rendu en texte |

Le n° 25 rejoue le bug qui a mangé un diagramme : le modèle écrivait les
arguments de `mermaid_diagram` au lieu de l'appeler.

### Scénarios de l'agent de code en nœud

| # | À taper | Attendu | Ce qui serait un bug |
|---|---|---|---|
| 26 | `va dans <projet> et supprime le fichier X` | l'agent **demande** avant de supprimer | il annonce qu'il ne peut pas |
| 27 | sur cette question : **Oui** | reprend où il en était | il refait ce qu'il avait déjà fait |
| 28 | sur cette question : **Non** | il change de voie | il repose la même commande |
| 29 | `crée un plan pour <tâche>` puis **Préciser** | plan révisé soumis à nouveau | le plan s'exécute sans être remontré |
| 30 | `explore ce dépôt et dis-moi comment il est organisé` | **un** rapport, pas vingt lectures | le contexte se remplit de fichiers |
| 31 | `coucou`, puis `aide-moi` | questionnaire posé **une fois** | il boucle, ou répond en texte libre |

Le n° 26 est le cœur du chantier : il était impossible avant, parce que demander
aurait tout rejoué. Le n° 31 vérifie la clarification, qui bouclait six fois.

### Sur la veille

```bash
axon cron-test              # liste les tâches
axon cron-test <id>         # en essaie une, sans effet
```

Créer une veille en langage naturel — « surveille le prix de X et préviens-moi
s'il baisse » — puis `cron-test` deux fois : le premier passage établit la
référence sans alerter, le second compare.

---

## 1. Routage — étage 1 (chantier en cours)

**Le problème, mesuré.** Sur « quels sont mes rendez-vous de demain » :

```
0.9035 memory · 0.9087 slack · 0.9150 news · 0.9239 process · 0.9320 calendar
└──────────────── 7 groupes dans un écart de 0.04 ────────────────┘
```

`calendar` sort **cinquième sur sa propre requête**. `memory` idem sur
« souviens-toi de cette préférence ». Ils ne survivent que parce que la coupure
est à cinq places (`_TOP_GROUPS = 5`).

Vérifié sur l'arbre committé **avant** toute modification : ce n'est pas une
régression, c'est l'état de départ.

**Conséquence.** Toute intention ajoutée éjecte un groupe qui tenait par un fil.
Deux tentatives cette semaine l'ont montré, avec des contenus sans rapport :

- groupe `commerce` → `calendar` et `memory` cassés
- groupe `veille` → les deux mêmes, plus `git_status` et `news` selon la
  formulation du `covers`

**Piste.** Les documents de groupe sont de longs paragraphes descriptifs, les
requêtes de courtes questions familières — asymétrie classique requête/document.
`tests/test_tool_routing.py` mentionne **298 phrases d'ancrage** qui servaient à
l'indexation avant une refonte ; elles ont été retirées. À regarder.

**Ce qui attend ce chantier.**

- Le groupe `veille` dédié : **5/5 en réglage ET 5/5 en held-out**, contre 4/5 et
  1/5 avec `surveiller` rangé dans `cron` (version livrée). Rebasculer dès que
  l'étage 1 discrimine. Mesure laissée en commentaire dans `tool_retriever.py`.
- `/deep` route sur **2 formulations sur 4**. « Monte-moi un dossier complet » et
  « compare en profondeur » ne trouvent pas `search` dans les 4 premiers groupes.
- `calendar` et `memory` : leurs propres requêtes doivent gagner. Des mots-clés
  (`rendez-vous`, `rdv`, `souviens`, `mémorise`) corrigent `memory` mais pas
  `calendar` — « rendez vous » sans trait d'union se tokenise en deux mots, et
  ajouter `rendez` seul casse `test_le_lexical_n_ecrase_pas_le_semantique`.

**Pièges connus.**

- Ne pas mettre `dossier` en mot-clé : en français c'est aussi un répertoire.
- Un `covers` qui énumère des exemples courts se loge près du centroïde et sort
  au rang 1 sur tout — documenté pour `memory`, revécu avec `veille`.
- Un outil ne peut appartenir qu'à **un** groupe : l'index inverse en écrase un
  en silence (`test_tool_names_in_groups_all_exist`).

---

## 2. Unifier les graphes — il n'en reste qu'un à rejoindre

L'agent de code a rejoint le graphe principal (voir plus bas). Reste
`src/cron_daemon.py:174`, qui utilise `create_react_agent` — un second graphe qui
n'a **aucun** des dix nœuds construits. Pas de policy, pas de routage (liste fixe de
dix outils), et demain pas de trace ni de verify.

C'est pour ça que `commandes_autorisees` existe : un contournement du fait que le
démon ne peut pas demander.

**L'obstacle.** Un `interrupt()` figerait la tâche indéfiniment — vérifié :
relancer un graphe interrompu sans réponse laisse l'interruption en attente.

**Le remède est déjà à moitié écrit.** `commandes_autorisees` est une réponse
déclarée d'avance ; `cron-test` sait dire « aurait envoyé ». Généralisé, ça donne
un mode « personne n'est là » : `hitl.demander()` regarde si un client peut
répondre, sinon rend le **refus** — jamais l'accord — et journalise « aurait
demandé X ». La tâche échoue proprement au lieu de se figer.

Le démon gagne alors tout, là où on en a le plus besoin : quand personne ne
regarde.

---

## 3. VERIFY — vérifier l'effet, pas le jugement

Distinct d'un nœud de réflexion : pas « ai-je bien travaillé ? » mais « l'état
réel correspond-il à l'objectif ? ». Déterministe, donc gratuit en tokens.

```
écriture   → Path(...).is_dir() / read_text()
mail       → message_id rendu par le fournisseur
shell      → exit_code + effet observable
calendrier → calendar.get(event_id)
```

**Instance mesurée du bug qu'il attrape** : une tâche cron loguait
`status: "ok"` alors que **toutes** ses commandes avaient été bloquées. L'outil
rendait un statut de refus, personne ne le lisait. Corrigé pour cron, mais la
classe entière reste ouverte ailleurs.

Devient nécessaire maintenant que la veille tourne sans surveillance : une veille
qui échoue en silence est pire que pas de veille.

---

## 4. `action_policy` généralisée

`classification.py` + `autorisation.py` font 90 % du travail, mais **de forme
shell** : `est_destructive(commande: str)`. Généraliser en
`evaluate(action) -> allow | confirm | deny` change l'entrée en
`(nom_outil, args)` — la logique shell ne se transfère pas, elle devient **un
évaluateur parmi plusieurs**.

Ce n'est donc pas « extraire et généraliser » mais « définir un registre
d'évaluateurs par outil ». Deux appelants aujourd'hui : shell et mail.

---

## 5. ~~Trace de décision~~ FAIT — branche `feat/monitoring`

Le meilleur rapport effort/gain pour la suite, parce qu'elle compose : elle
n'améliore pas AXON, elle améliore la capacité à l'améliorer. Quatre fois cette
semaine, des mesures de routage ont été refaites à la main.

**Une ligne par ACTION, `run_id` comme clé de regroupement.** Un tour fait N
appels d'outils dans une boucle ; un enregistrement plat par tour perdrait
l'information utile — lequel des N a fait quoi.

Livré dans `src/infra/trace.py`, relu par `axon trace`, documenté dans
[`docs/monitoring.md`](docs/monitoring.md). Le schéma retenu :

```
run_id · seq · at · source · axon_sha
genre · intent · groupes · outils_lies · outil · cible
policy · confirmation · resultat · verification · erreur
tokens_entree · tokens_sortie · latence_ms · backend · modele · extra
```

Trois écarts avec le schéma esquissé ici, chacun pour une raison :

- `context_used` est remplacé par `tokens_entree`. « Ce qui a servi de contexte »
  n'a pas de définition stable ; sa TAILLE en a une, et c'est elle qui a manqué
  le jour où le plancher de schémas a dépassé Groq.
- `source` s'ajoute (`tui`/`cron`/`api`/`mcp`). Sans elle, les lignes du démon et
  celles de la conversation se mélangent — et c'est le démon, celui que personne
  ne regarde, qu'on veut isoler d'un coup.
- `learnable_signal` n'est pas écrit. Il n'a pas encore de consommateur : la
  liste blanche apprenante se déduira de `policy` + `confirmation`, déjà là. Une
  colonne sans lecteur diverge en silence.

**Ce que ça débloque tout de suite** : `axon trace --route` donne le taux de
rattrapage au catalogue, que `graph.py` réclamait en commentaire — c'est lui qui
dira jusqu'où la sélection peut être resserrée. Et `--outils` compte la
couverture réelle de VERIFY (§3) au lieu de la supposer.

**Reste ouvert** : `/debug` affiche toujours `tools sélectionnés : —` parce qu'il
lit l'état du tour **précédent**. La trace, elle, écrit le tour courant.

---

## 6. Boucle d'apprentissage — rangs 1 et 2 FAITS, branche `feat/memory`

`détecter → attribuer → mémoriser → généraliser → contraindre`. Les deux
premiers rangs sont livrés — ceux qui MESURENT. Documenté dans
[`docs/apprentissage.md`](docs/apprentissage.md).

**Livré.** `src/infra/erreurs.py` compte les deux signaux que la trace écrivait
déjà sans que personne ne les lise comme des erreurs (`rattrapage`,
`confirmation=refus`), relu par `axon trace --erreurs`.
`src/infra/incident.py` en déduit un journal d'incidents global, relu par
`axon incidents`. Trois écarts avec le PRD, chacun pour une raison :

- **`projet` est ajouté à la TRACE**, pas seulement au schéma d'incident. Le PRD
  disait « pas de nouvelle colonne dans la trace » ; c'était intenable, parce
  qu'un incident est déduit après coup et que la provenance ne se reconstitue
  pas. Résolue une fois par run, comme `source`.
- **`origine` s'ajoute au schéma d'incident** (`<run_id>:<seq>`). Sans clé de la
  ligne source, une seconde passe de capture réécrirait tout et le compte des
  récidives compterait des passes.
- **`extra.precision` s'ajoute au refus** dans `revision.py`. « Que faut-il
  ajuster ? » partait au modèle et nulle part ailleurs : le refus se comptait, sa
  raison mourait avec la session. C'est le champ `correction` d'un incident.

**Reste ouvert — rang 3, la consolidation.** Deux critères déjà connus : relire
un échantillon de `rattrapage` avant de croire un compte (le signal atteste que
la sélection n'a pas lié l'outil réclamé, pas que l'outil réclamé était le bon),
et ne jamais promouvoir vers une règle globale un motif vu dans un seul `projet`.
Elle rendra un **diff à valider**, jamais un commit : une porte ajoutée sans le
bug vécu qui la justifie est indéboulonnable.

**Hors périmètre.** Les corrections dites en conversation libre — le signal
structuré ne voit que ce qui passe par un interrupt. Les erreurs de plan : la
catégorie existe et reste vide, y mettre un classifieur LLM réintroduirait un
cran plus loin le juge écarté à la détection.

---

## 7. Plus petit, plus tard

- **Liste blanche apprenante** — dépend maintenant de la consolidation (§6),
  pas de la trace : les deux signaux qu'elle demandait sont comptés.
- **`/undo` élargi** : les écritures sont centralisées dans
  `revision.appliquer`, un journal des applications le rendrait trivial et il
  couvrirait tout, pas seulement le coding agent.
- **Corpus held-out en CI** : la discipline existe, l'automatiser évite qu'elle
  dépende de qui relit.
- **Digest du matin** : `gmail` + `calendar` + `weather` + `news` + `cron`, cinq
  groupes qui ne se croisent jamais. Assemblage, pas construction.
- **Sessions navigateur** : `--isolated` dans `~/.axon/mcp_servers.json` signifie
  aucune session persistante — « connecte-toi à mon espace client » redemande à
  chaque fois.
- **`USER_NAME`** : un mail de test était signé « Alex » au lieu de « Kaine ».

---

## Ce qu'on a décidé de NE PAS faire

**Nœud de réflexion / auto-critique.** Tous les défauts corrigés cette semaine
ont la même forme : on a demandé au modèle de faire quelque chose, il ne l'a pas
fait. Un LLM qui juge un LLM ajoute exactement cette classe d'échec, plus un
appel. `guard.enforce` est le bon modèle — il n'a pas d'opinion.

**Arêtes à score de confiance.** Un seuil est une pondération déguisée. Deux
pondérations ont déjà été rejetées faute de preuve.

**Routeur automatique entre backends.** Le bug NVIDIA était « je crois tourner
sur X, je tourne sur Y ». Automatiser ce choix reprend la seule chose qui a
permis de le voir.

**Prometheus et Grafana — pas maintenant, et on sait à quelle condition.**
Prometheus TIRE sur un endpoint HTTP ; le processus où se prennent presque toutes
nos décisions est le TUI, interactif et sans serveur. Et ses labels doivent
rester à basse cardinalité quand toutes nos questions sont à haute cardinalité :
il sait dire « 4 % de refus », jamais lequel — or le diagnostic est toujours dans
le lequel. Déclencheur pour reprendre : un processus long à trafic continu
(`api_server` à plusieurs clients, ou le démon à haute fréquence). Argumentaire
complet dans [`docs/monitoring.md`](docs/monitoring.md).

**Sentry.** Même raison, moins tranchée : `failure_log.py` couvre déjà les pannes
de backend avec leur stratégie de récupération, et sur une application locale une
exception se voit tout de suite. Le seul vrai trou était le démon — l'alerting de
`feat/monitoring` le couvre sans service tiers.

**Un juge de qualité DANS le graphe.** Inchangé. En revanche un juge **hors
ligne**, en batch, sur un échantillon de traces, n'est pas la même chose : il ne
bloque aucun tour et n'ajoute aucun appel au chemin critique. Pas écrit, mais la
trace lui donne déjà son entrée.

**~~Migrer le specialist en sous-graphe — pas maintenant.~~ FAIT.** Le signal
qu'on attendait est arrivé : le specialist a écrit « à toi de valider la commande
ci-dessus » pour un questionnaire qui ne pouvait pas s'afficher.

La mesure qui a décidé de la forme, avant d'écrire une ligne :

    boucle ordinaire dans un nœud   étape déjà faite exécutée 2×  ← REJEU
    sous-graphe compilé             exécutée 1×                   ← pas de rejeu

Il ne demandait rien parce que demander aurait réécrit les fichiers et relancé
les commandes déjà passées. Les ~600 lignes réglées n'ont pas bougé : elles sont
extraites en `SessionModele` et `executer_un_outil`, appelées par les nœuds.
`graphe_agent.py` ne porte que la structure.

Et il est maintenant un **nœud du graphe principal**, pas un outil :
`run_coding_agent` pose un marqueur, `apres_les_outils` route vers `coder`.
Motif de `deep_research` → `approfondir`. Un outil est atomique — son enveloppe
était ré-entrée à chaque reprise.

---

## Règles apprises cette semaine

À relire avant d'ajouter quoi que ce soit au graphe.

1. **Avant `interrupt()` s'exécute deux fois, après une seule.** Les effets se
   placent après.
2. **On interrompt depuis un nœud, jamais depuis un outil** — un outil est
   atomique, tout son travail serait rejoué.
3. **Un sous-graphe compilé sans checkpointer hérite de celui du parent** : ses
   étapes sont checkpointées et il peut interrompre.
4. **Une décision d'utilisateur revient en `HumanMessage`**, avec une consigne et
   pas un constat. Un `AIMessage` est diffusé à l'écran et relu par le modèle
   comme son propre tour.
5. **Un groupe porte une intention**, pas un fournisseur commun. Un document
   multi-sujets rend son sujet minoritaire indistinct.
6. **Mesurer sur un corpus held-out**, systématiquement. Un réglage qui ne passe
   que sur ses propres exemples est un dictionnaire déguisé en intention.
