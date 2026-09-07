# Apprendre de ses erreurs — rangs 1 et 2

Branche `feat/memory`, posée sur `feat/monitoring`. Elle ne peut pas exister sans
elle : tout ce qui suit **lit** `~/.axon/decisions.jsonl`.

## Ce que ça n'est pas

Aucun poids ne bouge. « Apprendre » veut dire ici une seule chose : ce qu'on
écrit quelque part et qu'on relit ensuite. La boucle complète est
**détecter → attribuer → mémoriser → généraliser → contraindre** ; cette branche
livre les deux premiers rangs, qui sont ceux de la mesure. Les rangs qui
*décident* — consolidation, durcissement — ne sont pas ici, et c'est délibéré :
on ne durcit pas une règle sur des chiffres que personne n'a encore regardés.

## Rang 1 — compter ce qui est déjà écrit

`src/infra/erreurs.py`, relu par `axon trace --erreurs`.

Deux signaux étaient inscrits dans la trace depuis `feat/monitoring` sans que
personne ne les lise comme des erreurs :

| Signal | Où | Ce qu'il atteste |
|---|---|---|
| `genre = rattrapage` | `graph.py:371` | le routeur n'a pas lié l'outil que le modèle a dû réclamer au catalogue |
| `confirmation = refus` | `revision.py:260` | l'utilisateur a vu l'action proposée et a dit non |

Ils ont ceci de rare qu'ils ne demandent **aucun jugement de modèle**. Distinguer
« correction » et « nouvelle requête » en conversation libre est un problème
ouvert ; ces deux-là sont tranchés à l'écriture.

**Des comptes, pas des taux.** À volume mono-utilisateur un ratio ne veut rien
dire — « trois rattrapages sur `gmail_send_email` ce mois-ci » se lit, « 4,2 % »
ne se lit pas. C'est l'arbitrage qui a déjà fait reporter Prometheus.

### Ce que le compteur ne dit pas

Un rattrapage atteste que la sélection n'a pas proposé l'outil réclamé — **pas
que l'outil réclamé était le bon**. Le modèle a pu se tromper de nom. Compter
reste juste ; durcir une porte sur ce compte sans relire un échantillon
apprendrait l'erreur du modèle à la porte, et la règle encoderait une erreur de
second ordre. L'avertissement est imprimé sous le tableau à chaque affichage,
parce que c'est au moment de lire le chiffre qu'on est tenté d'en tirer une règle.

## Rang 2 — le journal d'incidents

`src/infra/incident.py`, relu par `axon incidents`.

Un incident **n'est pas une colonne de plus** dans `decisions.jsonl`. La trace
enregistre des actions au moment où elles ont lieu ; un incident est une lecture
de plusieurs actions, produite après coup. Les mélanger obligerait à écrire
pendant le tour une conclusion qu'on ne tire qu'ensuite.

```
run_id                → clé de jointure vers decisions.jsonl
horodatage
projet                repo git d'où vient l'incident, « — » hors repo
intention_reformulee  la demande à laquelle ça répondait
contrat_etat          niveau 1 du contrat — vide, faute de postconditions
action_tentee         les groupes que le routeur a élus, ou la cible refusée
categorie             routing | plan | execution | etat_perime
resultat_reel
correction            ce qui aurait dû être fait
signal_source         rattrapage | refus | verify | echec_dur
origine               <run_id>:<seq> de la ligne source
```

`origine` n'est pas dans le schéma d'origine du PRD. Il est ajouté pour une
raison opératoire : sans clé de la ligne source, une seconde passe de capture
réécrirait tout, et le compte des récidives compterait des passes au lieu
d'erreurs. `axon incidents --capturer` est donc **idempotente** — elle peut
tourner sans qu'on se demande quand elle a tourné la dernière fois. Une passe qui
exige qu'on tienne le compte de ses exécutions finit par ne plus être lancée.

### `projet` — la portée, écrite dès la première ligne

Le fichier est global (`~/.axon/`), et non `{git_root}/.axon/` comme la mémoire
de session : c'est la condition littérale pour qu'une leçon serve d'une
conversation à l'autre. Mais un fichier global **sans provenance** mélange des
leçons qui ne se transposent pas — le catalogue d'outils d'un dépôt n'est pas
celui d'un autre, et une règle de routage apprise ici peut ne rien vouloir dire
là-bas, voire nuire.

D'où une colonne `projet` ajoutée **à la trace elle-même**, résolue une fois par
run comme `source` l'est. Deux conséquences qui ont décidé de sa place :

- Elle **ne se rattrape pas après coup.** `decisions.jsonl` ne la portait pas :
  l'information n'existerait nulle part à reconstruire, et l'ajouter plus tard
  ne migrerait pas un fichier, elle en perdrait le contenu.
- Elle est résolue **à chaque run**, pas une fois par processus. L'agent shell
  déplace le `cwd` en cours de session ; une valeur figée à l'import
  étiquetterait tous les tours suivants du nom du premier projet ouvert.

Hors dépôt, la valeur est `—` et non une chaîne vide : un vide se confondrait à
la relecture avec « colonne pas encore écrite ».

### La consigne de l'utilisateur atteint enfin la trace

`revision.py` demandait déjà « Que faut-il ajuster ? » sur un refus `Préciser`.
La réponse partait au modèle et **nulle part ailleurs** : le refus se comptait,
sa raison mourait avec la session. Elle est maintenant écrite dans
`extra.precision`, et devient le champ `correction` d'un incident.

C'est la seule fois où l'utilisateur *dit* ce qu'il aurait fallu faire. Sans
elle, la boucle n'archive que des rejets sans jamais savoir vers quoi corriger.

## Ce qui n'est pas couvert

- **Les corrections en conversation libre.** Le signal structuré ne voit que ce
  qui passe par un interrupt.
- **Les erreurs de plan.** Aucune instance ne les attribue sans jugement. La
  catégorie `plan` existe dans le schéma et reste vide — y mettre un classifieur
  LLM réintroduirait, un cran plus loin, le juge écarté à la détection.
- **La consolidation (rang 3).** Elle décidera des promotions ; elle n'est pas
  écrite. Son premier critère est déjà connu : relire un échantillon de
  `rattrapage` avant de croire un compte, et ne jamais promouvoir vers une règle
  globale un motif vu dans un seul `projet`.
- **Le durcissement (rang 5).** Quand il viendra, il rendra un **diff à valider**,
  jamais un commit. Les portes déterministes du routeur portent chacune le bug
  vécu qui la justifie ; une règle ajoutée automatiquement arriverait sans ce
  commentaire, et personne ne saurait six mois plus tard si elle peut sauter.

## Commandes

```
axon trace --erreurs          ce qui a raté, compté par outil et par cible
axon incidents --capturer     relire la trace et en déduire les incidents
axon incidents                les incidents capturés
axon incidents --projet X     ne garder qu'un dépôt
axon incidents --categorie routing
```

`AXON_TRACE=0` éteint la trace **et** la capture : sans quoi le journal
d'incidents continuerait d'écrire alors que l'utilisateur a demandé le silence.
