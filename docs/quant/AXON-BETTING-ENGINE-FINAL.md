# AXON — Betting Engine — état final

**Source de vérité.** Ce document décrit ce qui EST, mesuré, à la clôture du
développement. Il ne contient pas de feuille de route. Quand un chiffre y
figure, il vient d'une exécution réelle ; quand une capacité manque, le motif est
nommé et classé.

Dernières mesures : **16 août 2026**. Suite de tests : **2 791 passés, 6 ignorés,
0 échec**.

Une distinction gouverne tout le document, et rien n'y déroge :

```
CANONICALIZED  ≠  MODEL_AVAILABLE  ≠  VALIDATED  ≠  ACTIONABLE
```

Savoir lire un contrat n'est pas savoir le pricer ; savoir le pricer n'est pas
avoir démontré qu'on a raison ; avoir raison en moyenne n'autorise pas encore une
mise.

---

## ARCHITECTURE

Le chemin complet, du catalogue à la réponse, est câblé et exercé par le produit
réel — pas seulement par des tests.

| Étage | Rôle | Où |
|---|---|---|
| Scan bookmaker | catalogue multisport, puis page par événement (jusqu'à 252 marchés) | `betting_engine/bookmakers/winamax/` |
| Observation | marché brut → `RawMarketObservation` (betType, template, paramètres typés, codes) | `markets/observation.py` |
| Canonicalisation | observation → famille + paramètres de règlement, **par conjonction structurelle** | `markets/families.py` |
| Capacité | quelles familles un sport sait pricer | `markets/capability.py` |
| Pricing | famille + modèle → probabilités, no-vig **si le marché partitionne** | `markets/pricing.py`, `sports/*/` |
| Incertitude | borne basse par capacité (Wilson, `MIN_ECHANTILLON=30`) | `markets/uncertainty.py` |
| Politique | éligibilité money : qualité, fraîcheur, maturité | `value_engine/bet_policy.py` |
| Classement | REVIEW ordonné, best-market-per-event | `markets/review_ranking.py` |
| Produit | ACTIONABLE / REVIEW, préférences utilisateur, combinés | `conversation/` |
| Boucle retour | règlement des sélections, calibration | `betting_engine/outcomes/` |
| CLV | collecte décision/clôture, verdict par capacité | `betting_engine/clv/` |

**Gateway de données** : registre de couverture par (provider × compétition ×
saison × type), chaîne de fallback, snapshots point-in-time, `stale` explicite.

**Ce qui est terminé** : les onze étages ci-dessus, le scan multisport et
multi-marché, la canonicalisation, le routage de capacité, le produit
conversationnel, l'audit rejouable, et la collecte CLV autonome.

---

## SPORTS

Sept sports ont un module enregistré et sont ATTEIGNABLES depuis le produit
standard (`axon recommend` → scan → résolveur → modèle), pas seulement via des
seams de test.

| Sport | Modèle rencontre | Marchés dérivés | Données |
|---|---|---|---|
| football | Dixon-Coles (matrice de score) | 1X2, double chance, DNB, score exact, totals | football-data.org, 8 championnats + 3 compétitions |
| tennis | Elo par paire + modèle jeu→set→match | vainqueur, sets | corpus embarqué (fixture figée, péremption mesurée) |
| basketball | Elo + ratings offense/défense séquentiels | écart, total, total d'équipe | api-sports (NBA/WNBA) |
| american_football | idem basketball | écart, total | api-sports (NFL) |
| baseball | Elo | vainqueur | api-sports (MLB) |
| hockey | Elo | vainqueur | api-sports (NHL) |
| volleyball | Elo | vainqueur | api-sports |

**Report de saison (football)** : la forme prend les `last` derniers matchs de la
même compétition, saison précédente comprise, et N-1 disparaît mécaniquement dès
que la fenêtre se remplit. Aucun paramètre, aucun calendrier, aucune décroissance
— candidat B du benchmark cold-start, retenu comme la solution minimale
démontrée. La couverture N-1 est déclarée pour les huit championnats.

---

## MARKET FAMILIES

Mesuré sur un balayage réel : **6 716 marchés, 73 pages d'événement, 7 sports**.

| Famille | Canonicalisée | Modèle | Validé | Live |
|---|---|---|---|---|
| `TOTALS` | ✅ 28,3 % | ✅ football, basket, NFL | ✅ walk-forward | REVIEW |
| `HANDICAP` | ✅ 18,4 % | ✅ basket, NFL, tennis | ✅ | REVIEW |
| `MATCH_WINNER` | ✅ 10,6 % | ✅ 7 sports | ✅ | REVIEW |
| `TEAM_TOTALS` | ✅ 2,4 % | ✅ basket, NFL | ✅ | REVIEW |
| `DRAW_NO_BET` | ✅ 0,9 % | ✅ football | ✅ | REVIEW |
| `EXACT_SCORE` | ✅ 0,9 % | ✅ football | ✅ | REVIEW |
| `DOUBLE_CHANCE` | ✅ 0,3 % | ✅ football | ✅ | REVIEW |
| `PLAYER_PROP` | ✅ 13,2 % | ❌ `MODEL_NOT_AVAILABLE` | — | — |
| `PLAYER_COMBO_PROP` | ✅ 11,8 % | ❌ `MODEL_NOT_AVAILABLE` | — | — |
| `OUTRIGHT_WINNER` | ✅ | ❌ | — | — |
| longue traîne | ❌ 13,2 % | — | — | `STOP_LONG_TAIL` |

**Canonicalisation : 86,8 %.** Mesurée avant/après sur le même échantillon :
**61,8 % → 86,8 %**.

### Ce qui a rendu `PLAYER_PROP` lisible

`betType 3361` (6,1 % du catalogue) portait `variant=pre:playerprops:X:Y`, sans
joueur, sans statistique, sans seuil apparents. Il se résout **entièrement dans
le code d'issue**, et la mesure le démontre — 84 issues, 12 événements, trois
égalités vérifiées **84/84** :

- segment 1 = identifiant d'ÉVÉNEMENT du bookmaker ;
- segment 2 = identifiant JOUEUR Sportradar, **contre-vérifié par le champ typé
  `srPlayerId`** de la même issue ;
- segment 3 = SEUIL.

Le libellé n'a servi qu'à vérifier l'hypothèse après coup. Une issue dissidente
invalide le marché entier.

### Identité de règlement

L'identité canonique porte tout ce qui change le payoff : famille, joueur(s),
statistique, ligne ou paliers, portée, période, nombre de joueurs, **mode de
règlement**. Ce dernier n'est pas décoratif : `Duo marqueurs` (5595) règle sur
une SOMME et `Double chance marqueurs` (5594) sur une DISJONCTION, avec la même
signature structurelle et des payoffs opposés.

**Deux marchés économiquement différents ne partagent jamais une identité CLV.**

---

## PRODUCT

### ACTIONABLE vs REVIEW

`ACTIONABLE` exige la maturité au ledger CLV. `REVIEW / EXPERIMENTAL` désigne une
vraie probabilité produite par un modèle, dont la maturité n'autorise pas la
mise. **Un candidat REVIEW reste VISIBLE** : `ACTIONABLE = 0` n'est jamais
« aucun pari » tant que des REVIEW existent.

Chaque candidat affiche : cote, `fair_probability`, `probability_low`,
`vig_adjusted_probability`, edge, edge prudent, EV settlement-aware, EV prudente,
`data_quality`, `freshness`, modèle/capacité, `probability_origin`, maturité, et
**la raison exacte qui empêche ACTIONABLE**. Une grandeur non mesurée s'écrit
`NON MESURÉ` — jamais un zéro.

### Best market per event

Le classement produit un meilleur marché par rencontre. Mesure produit du
chantier multi-marché : sur un run réel, **8 rencontres sur 38** ont un meilleur
marché qui n'est PAS le vainqueur.

### Préférences utilisateur

**Probabilité** (« environ 90 % de chances ») se compare à `probability_low` et
**jamais** à `fair_probability` : qui demande 90 % demande une garantie, une
estimation ponctuelle n'en est pas une. Une borne basse absente n'atteint aucun
seuil et n'échoue pas — elle n'est pas comparable.

**Cote / multiplicateur** (`TargetOddsPreference` : « x2 », « entre 1,8 et 2,2 »,
« doubler ma mise ») porte cible, tolérance (±15 % par défaut, **affichée**) et
bornes. Un montant n'est jamais confondu avec une cote.

La cote est **subordonnée** à la probabilité. Trois sections disjointes, jamais
un score unique où le prix rattraperait la prudence :

1. respecte le seuil ET la cote visée ;
2. respecte le seuil, cote hors objectif ;
3. proche de la cote, **sous** le seuil — montrés, jamais en substitut.

Quand aucun candidat ne satisfait les deux, le produit le **dit**.

### Combinés exploratoires

Construits uniquement sur des candidats REVIEW réellement évalués, après filtres
de sécurité (`probability_low`, qualité et fraîcheur mesurées, aucun REJECTED),
et seulement ensuite ordonnés par proximité à la cote visée.

Le garde de corrélation est **celui du chemin argent**, réutilisé et non
réécrit, plus une règle propre : deux jambes partageant `probability_origin`
sortent de la même loi jointe → `CORRELATED_SAME_ORIGIN`, probabilité jointe
`NOT_ESTIMATED`. **Aucune multiplication arbitraire.** La cote combinée reste
calculable — c'est une donnée observée. Un combiné REVIEW ne devient jamais
ACTIONABLE ; `ComboExploratoire` ne porte aucun champ de mise.

### Langage interdit

Le garde refuse « pari sûr », « garanti », « sûr à 90 % », « 90 % certain », et
les promesses sur le fonctionnement du produit (`UNFOUNDED_PROCESS_CLAIM`) :
modèles prétendument réentraînés chaque jour, fenêtre plus courte censée faire
apparaître des paris validés. Le vocabulaire retenu est **« probabilité prudente
estimée »**.

---

## MODEL MATURITY

La maturité est **automatique** : dérivée du ledger CLV, jamais déclarée. Critères
versionnés dans `configs/betting_engine/model_maturity_policy.json` —
30 rencontres indépendantes **et** borne de confiance inférieure strictement
positive.

Aucune capacité n'est mature à ce jour. Toutes les familles livrées sont
`EXPERIMENTAL`.

Les props NFL font exception d'un autre genre : **33 lignes validées en
walk-forward** (Brier < baseline, ECE sous seuil) sur données nflverse, mais
aucun marché compatible n'est observé. Le routage reste **dormant** — jamais
`MODEL_AVAILABLE` sans marché.

---

## CLV

Collecte autonome, verdict par capacité. Le verdict répond à « qu'a-t-on
mesuré » ; le compteur « il manque » à « attendre peut-il aider ».

| Capacité | Indép. | CLV moyenne | Borne basse | Verdict |
|---|---|---|---|---|
| `baseball.match_winner` | 71 | −2,59 % | −2,86 % | `MEASURED_NEGATIVE` |
| `tennis.match_winner` | 44 | −0,28 % | −0,79 % | `MEASURED_NEGATIVE` |
| `football.match_winner` | 15 | −2,39 % | −3,93 % | `DATA_ACCUMULATION` |
| `hockey.match_winner` | 0 | — | — | `NOT_MEASURABLE` |

**Baseball et tennis ont leur échantillon.** Leur signe négatif est un
**résultat**, pas un manque de données : aucune attente ne le retournera. Les
familles multi-marché (TOTALS, HANDICAP, DOUBLE_CHANCE, DRAW_NO_BET,
EXACT_SCORE, TEAM_TOTALS) sont en début de collecte.

Le timer continue après la clôture du développement.

---

## OPERATIONS

### Timer CLV

```
systemd --user : axon-clv-collect.timer   (active, enabled)
OnUnitActiveSec=5min · Persistent=true
```

`Persistent=true` rattrape la passe manquée après une veille ou un redémarrage.
Aucune action n'est requise après reboot : le timer est `enabled`.

```bash
systemctl --user status  axon-clv-collect.timer
systemctl --user restart axon-clv-collect.timer
journalctl --user -u axon-clv-collect.service -n 50
```

### Stores

| Chemin | Contenu |
|---|---|
| `var/betting_engine/odds_history.jsonl` | observations décision/clôture (CLV) |
| `var/betting_engine/coverage.jsonl` | couverture catalogue par run |
| `~/.axon/sports_provider_coverage.db` | registre de couverture provider |
| point-in-time store | snapshots de données par (compétition, saison, type) |

**Aucune suite de tests n'écrit dans ces stores** : deux gardes le vérifient, un
dynamique (le dossier ne grossit pas) et un statique (tout appel de scan dans les
tests neutralise capture, audit et coverage).

### Diagnostic

```bash
axon recommend            # produit réel
axon clv-status           # état CLV par sport, puis par capacité
axon outcomes             # justesse réelle des modèles (règlements)
axon catalog-coverage     # part du catalogue réellement évaluable
axon readiness            # validation walk-forward par modèle
axon coverage             # couverture provider
axon tennis-inventory     # fraîcheur du corpus tennis
axon record-odds          # capture manuelle d'une observation
axon providers-discover   # sondage de couverture provider
axon sports-seed          # amorçage du registre
```

### Diagnostic provider

Cinq causes d'échec sont distinguables dans le journal de décision :

| Cause | Signature |
|---|---|
| `RATE_LIMITED` | `quota local épuisé — N/M` dans les motifs |
| `AUTH_FAILED` | `<PROVIDER>_KEY manquant dans .env` |
| `NOT_COVERED` | « Providers essayés : aucun éligible » |
| `DATA_UNAVAILABLE` | `unexpected_empty (couverture FULL)` |
| `STALE` | `STALE_FALLBACK`, `stale=True` sur l'enveloppe |

---

## KNOWN STOP

### DATA

- **Props joueur football** — marché offert (737 marchés, 18,7 % du catalogue
  football), aucune donnée de statistique par joueur et par match qui permette de
  construire une distribution. `STOP DATA / IDENTITY`.
- **Corpus tennis** — fixture figée, sans rafraîchissement automatique. La
  péremption est **mesurée** (`PEREMPTION_JOURS = 21`) et dite, pas masquée.
- **Hockey** — 4 522 rencontres du corpus portent zéro but. Le modèle de score
  n'y est pas construisible. `STOP DATA`.

### STATISTICAL

- **CLV baseball et tennis** — échantillon atteint, signe négatif mesuré. Les
  modèles ne battent pas la ligne de clôture. `MEASURED_NEGATIVE`.
- **Baseball, distribution de runs** — la loi candidate ne bat pas sa baseline ;
  le pricer s'abstient avec le motif du STOP plutôt que d'être omis, pour que le
  refus reste VISIBLE dans l'entonnoir.
- **Familles tennis rejetées** — les verdicts par famille sont enregistrés avec
  toutes les lignes mesurées, pas seulement les flatteuses.
- **Cold-start football, candidat C** — `STATISTICALLY PROMISING / PARAMETER NOT
  IDENTIFIED` : meilleur au benchmark, demi-vie non identifiée. Non retenu.

### EXTERNAL

- **Props joueur basketball** — le marché est là (1 521 marchés, 45,9 % du
  catalogue basket), les données `Game Player Stats` ne sont pas dans le tier
  gratuit de balldontlie. `EXTERNAL / PAID_REQUIRED`.
- **Props NFL** — modèles validés, **zéro marché observé** sur 900 marchés NFL
  relus. Winamax ouvre ces marchés à l'approche de la saison. `STOP EXTERNAL`.
- **Sources hockey automatisables** — techniquement accessibles, usage
  automatisé interdit par leurs conditions. `FORBIDDEN`.

### IDENTITY

- **Longue traîne du catalogue** — 13,2 % des marchés, **324 signatures**
  distinctes dont la plus grosse pèse 0,6 %. Marchés composites (« Résultat et
  nombre de buts »), variantes de portée, formes exotiques. Chacun demanderait sa
  propre démonstration ; aucun ne domine. `STOP_LONG_TAIL`.
- **`validateur_pour_resolveur`** (`gateway/core/event_validation.py`) — un
  contrôle d'appartenance saisonnière écrit, testé, et **jamais branché**. La
  garantie existe sans protéger aucune rencontre. Conservé et signalé plutôt que
  supprimé en silence.

### FORBIDDEN

- Scraping automatisé des sources hockey (conditions d'utilisation).
- Toute normalisation sans vig sur un marché qui ne partitionne pas.

---

## DO NOT REOPEN

Verdicts mesurés et tranchés. Les rouvrir sans donnée nouvelle referait le même
travail pour le même résultat.

| Sujet | Verdict | Preuve |
|---|---|---|
| balldontlie tier gratuit | `Game Player Stats = No` | vérification live |
| Props NFL au catalogue | 0 sur 900 marchés, deux relevés le même jour | scan réel |
| Serve/return tennis | absents du corpus | inspection du jeu de données |
| Hockey, buts du corpus | 4 522 rencontres à zéro but | comptage |
| Cold-start football | `USE_RAW_CARRY_OVER` (candidat B) | benchmark A/B/C/D + holdout |
| `DATA_TOO_STALE` football | **artefact de sonde** (`.env` non chargé) | production en `LIVE_FETCH`, `stale=False` |
| betTypes de total d'équipe | désignent le SLOT, pas l'équipe | 40/40, 3 sports |
| Grammaire du handicap | `hcp` s'applique au slot 1 ; `yes` = handicap négatif | 548/548 |
| `betType 3361` | joueur + seuil résolus par le code d'issue | 84/84 |
| Props à sélection unique | 2 193 / 2 436 sans complément → pas de no-vig | comptage catalogue |
| CLV baseball / tennis | négative, échantillon atteint | ledger |

**Le seuil de fraîcheur reste `2 days`.** Il n'a jamais été en cause.

---

## OPTIONAL V2

Extensions **facultatives**. Aucune n'est une dette : le système est complet sans
elles.

- **Providers payants** — un abonnement donnant `Game Player Stats` débloquerait
  la modélisation des props basket, dont le marché est déjà canonicalisé.
- **Props joueur basket** — le contrat est lisible et la collecte CLV possible
  dès aujourd'hui ; seul le modèle manque.
- **Props joueur football** — mêmes conditions, avec en plus une question
  d'identité de joueur à résoudre.
- **Méthode inter-paliers** — la monotonie de l'échelle des seuils d'un même
  joueur contraint les probabilités et pourrait rendre la marge mesurable sur un
  marché sans partition. Concevable, non démontrée.
- **Longue traîne** — chaque famille composite peut être démontrée
  individuellement si son volume le justifie un jour.
- **Nouveaux modèles** — lois jointes corrélées pour `PLAYER_COMBO_PROP`,
  modèles de score pour les sports où ils manquent.
