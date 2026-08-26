# Chantiers en cours

État au 26 août 2026, branche `feat/updateGraph`.
Six chantiers livrés dans la journée, **aucun éprouvé en session réelle**.

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

## 2. Unifier les graphes

`src/cron_daemon.py:174` utilise `create_react_agent` — un second graphe qui n'a
**aucun** des huit nœuds construits. Pas de policy, pas de routage (liste fixe de
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

## 5. Trace de décision

Le meilleur rapport effort/gain pour la suite, parce qu'elle compose : elle
n'améliore pas AXON, elle améliore la capacité à l'améliorer. Quatre fois cette
semaine, des mesures de routage ont été refaites à la main.

**Une ligne par ACTION, `run_id` comme clé de regroupement.** Un tour fait N
appels d'outils dans une boucle ; un enregistrement plat par tour perdrait
l'information utile — lequel des N a fait quoi.

```
run_id · intent · context_used · decision · policy · confirmation
       · action · result · verification · learnable_signal
```

`learnable_signal` alimente directement la liste blanche apprenante : « tu as
autorisé `docker compose up` cinq fois, je l'ajoute ? »

**À corriger au passage** : `/debug` affiche `tools sélectionnés : —` parce
qu'il lit l'état du tour **précédent**.

---

## 6. Plus petit, plus tard

- **Liste blanche apprenante** — dépend de la trace (§5).
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

**Migrer le specialist en sous-graphe — pas maintenant.** ~600 lignes réglées
(swap VRAM, abandon de phase, plafonds), aucun bug actuel ne l'exige. Le signal
pour s'y mettre : le premier moment où « j'aurais aimé qu'il me demande ça au
milieu du build ».

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
