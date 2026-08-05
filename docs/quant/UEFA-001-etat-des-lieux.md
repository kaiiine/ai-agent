# UEFA-001 — État des lieux : couverture des compétitions européennes de clubs

**Date** : 2026-08-05 · **Statut** : investigation close, implémentation en cours
**Périmètre** : Champions League, Europa League, Conference League, toutes phases.

Ce document est le résultat de vérifications **live** contre Winamax, football-data.org
et api-sports.io. Aucune ligne n'y est déduite d'un nom ou d'une date : chaque cellule
vient d'un payload réel. Ce qui n'a pas été vérifié est marqué comme tel.

---

## 1. Le blocage n'est pas là où on le croyait

Trois portes indépendantes conditionnent l'évaluation d'un événement. Onboarder une
ligue n'en franchit qu'une, et **la troisième est vide pour presque tout le catalogue** :

| Porte | Emplacement | UEFA | Domestique |
|---|---|---|---|
| Identité **équipe** | `gateway/core/identity_data.py` | 61 / 350 clubs | 156 clubs, 8 ligues |
| Identité **compétition** | `bookmakers/winamax/competition_mapping.py` | aucun tid UEFA | 8 ligues |
| **Couverture** provider | `registries/provider_coverage_registry.py` | aucune | **Ligue 1 seule** |

Conséquence mesurée le 2026-08-05, sur des événements réels du catalogue :

```
Lyon – Sparta Prague      (C1, tid 151665)  → IDENTITY_UNRESOLVED  (équipe : Sparta Prague)
Paris SG – Aston Villa    (Supercoupe, 680) → IDENTITY_UNRESOLVED  (compétition : tid inconnu)
Toulouse – Lyon           (Ligue 1, tid 4)  → MODEL_UNAVAILABLE    (couverture 2026 absente)
```

Le troisième cas est le plus important : **il ne concerne pas l'UEFA**. La baseline de
couverture (`known_coverage()`, vérifiée le 2026-07-25) ne contient que Ligue 1 et une
partie de Premier League. Serie A, LaLiga, Bundesliga, Championship, Eredivisie et
Primeira Liga ont une identité complète et **aucune couverture vérifiée** : elles ne
peuvent produire aucune décision. L'engine est aujourd'hui muet sur la saison 2026.

---

## 2. Catalogue Winamax — ce qui existe réellement (§3)

606 événements football live au 2026-08-05. Compétitions UEFA de clubs :

| Compétition | tid Winamax | `sr_tournament_id` | Événements | Fenêtre |
|---|---|---|---|---|
| Ligue des Champions (M) | `151665` | `sr:tournament:7` | 8 | 05 → 11 août |
| Ligue Europa | `10909` | `sr:tournament:679` | 15 | 04 → 13 août |
| Ligue Conférence | `151677` | `sr:tournament:34480` | 30 | 05 → 13 août |
| Supercoupe d'Europe | `680` | `sr:tournament:465` | 1 | 12 août |
| Ligue des Champions **(F)** | `172011` | `sr:tournament:696` | 14 | 05 août |
| Ligue des Champions **(F)** | `104744` | `sr:tournament:696` | 1 | 05 août |

### Deux pièges de nommage, de la même famille que le piège « 2 Bundesliga »

1. **« Ligue des Champions (F) » est la compétition féminine.** Un mapping par nom
   ferait tourner un modèle masculin sur des matchs féminins — misresolution
   silencieuse, money-sensitive. La désambiguïsation doit passer par `roster_overlap`,
   jamais par la chaîne de caractères.
2. **Une compétition porte plusieurs tid.** La C1 féminine en a deux (`172011`,
   `104744`) pour un même `sr_tournament_id`. Et `151665` / `151677` sont des tid de
   **phase préliminaire** : la phase de ligue portera d'autres tid en septembre.

> **Conséquence de conception** : le tid bookmaker n'est pas une clé stable de
> compétition. Le mapping doit être `(tid, sr_tournament_id, fenêtre)` → identité
> canonique, avec la phase comme attribut de l'événement — pas comme compétition
> distincte.

---

## 3. Providers — matrice vérifiée (§4)

### 3.1 football-data.org (clé présente, tier gratuit)

| Compétition | Code | Saisons exposées | Phases | Verdict |
|---|---|---|---|---|
| UEFA Champions League | `CL` | 2014 → 2025 (12) | **phase de ligue seule** | qualifs absentes |
| Europa League | — | — | — | **hors plan** |
| Conference League | — | — | — | **hors plan** |

Vérifié : `currentSeason` = 2025-09-16 → 2026-05-30. Saison 2026 → **HTTP 404**.
Saison 2025 : 189 matchs, 36 équipes — c'est la phase de ligue, pas les préliminaires.
Compétitions du plan : `BSA, ELC, PL, CL, EC, FL1, BL1, SA, DED, PPL, CLI, PD, WC`.

### 3.2 api-sports.io (clé présente, tier **Free**, 100 req/jour)

| Compétition | `league` | Saisons exposées | Saisons **servies** |
|---|---|---|---|
| UEFA Champions League | `2` | 2011 → 2026 | **2022-2024 seulement** |
| UEFA Europa League | `3` | idem | **2022-2024 seulement** |
| UEFA Conference League | `848` | idem | **2022-2024 seulement** |

Message exact du provider sur 2026 :
`Free plans do not have access to this season, try from 2022 to 2024.`

**Mais les saisons servies contiennent les qualifications**, ce que football-data.org
n'a pas :

| Compétition | Saison | Matchs | Clubs | dont qualifs/barrages | joués |
|---|---|---|---|---|---|
| CL | 2022 | 214 | 78 | 89 | 203 |
| CL | 2023 | 214 | 78 | 89 | 202 |
| CL | 2024 | 279 | 81 | 106 | 269 |
| EL | 2022 | 175 | 57 | 50 | 165 |
| EL | 2023 | 175 | 57 | 50 | 171 |
| EL | 2024 | 269 | 76 | 96 | 256 |
| UECL | 2022 | 415 | 177 | 290 | 384 |
| UECL | 2023 | 417 | 178 | 292 | 386 |
| UECL | 2024 | 409 | 164 | 272 | 379 |
| **Total** | | **2 567** | **350 distincts** | **1 334** | **2 415** |

Fenêtre temporelle : 2022-06-21 → 2025-05-31.

### 3.3 Matrice complète — vérifiée par appel HTTP le 2026-08-05

Une ligne par compétition, une cellule par provider. `prof.` = nombre de saisons
listées par le provider. Aucune cellule n'est déduite d'une autre.

| Compétition | `canonical_id` | fd.org : saison courante | prof. | api-sports : saison cour. | prof. | servi en free |
|---|---|---|---|---|---|---|
| Ligue 1 | `…fra:ligue1` | 2026-08-22 → 2027-05-29 | 83 | 2026 | 17 | 2022-24 |
| Premier League | `…eng:premier_league` | 2026-08-21 → 2027-05-30 | 128 | 2026 | 17 | 2022-24 |
| Serie A | `…ita:serie_a` | 2026-08-23 → 2027-05-30 | 95 | 2026 | 17 | 2022-24 |
| LaLiga | `…esp:laliga` | 2026-08-16 → 2027-05-30 | 95 | 2026 | 17 | 2022-24 |
| Bundesliga | `…deu:bundesliga` | 2026-08-28 → 2027-05-22 | 64 | 2026 | 17 | 2022-24 |
| Championship | `…eng:championship` | 2026-08-14 → 2027-05-01 | 10 | 2026 | 16 | 2022-24 |
| Eredivisie | `…nld:eredivisie` | 2026-08-07 → 2027-05-23 | 71 | 2026 | 17 | 2022-24 |
| Primeira Liga | `…prt:primeira_liga` | 2026-08-08 → 2027-05-16 | 78 | 2026 | 17 | 2022-24 |
| **Champions League** | `…eur:champions_league` | **2025-09-16 → 2026-05-30** | 46 | 2026 | 16 | 2022-24 |
| **Europa League** | `…eur:europa_league` | **hors plan** | — | 2026 | 13 | 2022-24 |
| **Conference League** | `…eur:conference_league` | **hors plan** | — | 2026 | 6 | 2022-24 |
| Chance Liga (CZ) | `…cze:chance_liga` | **hors plan** | — | 2026 | 9 | 2022-24 |

**Point-in-time** : les deux providers exposent date + statut par match, donc le
filtrage strict `kickoff < T` est possible partout. En revanche les **classements
publiés ne sont jamais point-in-time** : ils reflètent l'instant de l'appel. Toute
force dérivée d'un classement doit être reconstruite depuis les résultats
antérieurs à T (`PointInTimeGateway._reconstruct_table`), jamais lue telle quelle.

### 3.4 Deux conséquences non anticipées

**Les 8 ligues domestiques sont servies pour 2026-27, sans credential
supplémentaire.** football-data.org a basculé : 306 à 552 matchs programmés par
compétition, effectifs corrects. Le `PROVIDER_COVERAGE_MISSING` constaté en §1
n'est donc pas un mur — c'est une baseline de couverture qui n'a jamais été
étendue au-delà de la Ligue 1. Il se ferme par vérification, pas par abonnement.

**Mais `RESULTS` est servi et VIDE** : 0 match joué au 5 août, les saisons
démarrent entre le 7 et le 28. `recent_form(season=2026)` renvoie donc une liste
vide pour toute rencontre d'août, et `_season_of(kickoff)` pointe sur 2026 dès le
1er juillet. L'engine est structurellement aveugle en début de saison tant que la
forme n'est pas reportée depuis la saison précédente. Ce n'est pas un bug — c'est
un vrai manque de données — mais c'est un choix de modélisation à trancher
(report avec décroissance, prior de championnat, ou abstention assumée), pas un
détail de plomberie.

### 3.5 Verdict par usage

| Usage | Faisable aujourd'hui | Blocker |
|---|---|---|
| **Construire + valider** un modèle inter-championnats | ✅ 2 415 matchs joués, qualifs incluses | aucun |
| **Évaluer un match de la saison en cours** | ❌ | tier payant requis |

**Tier exact requis** pour les préliminaires 2026-27 : api-sports.io plan payant
(le premier tier au-dessus de Free lève la restriction 2022-2024). football-data.org
ne résoudra jamais ce besoin : ses qualifs ne sont pas exposées, et EL/UECL sont
hors plan quel que soit le tier gratuit.

---

## 4. Structure du dataset (§6, §7, §9)

### Phases présentes

```
978  qualification      396  phase de ligue
576  phase de groupes   350  barrage
261  knockout             6  tour préliminaire
```

Le dataset couvre l'ancien format (groupes) **et** le nouveau (phase de ligue) — §9 :
le modèle de match ne doit dépendre d'aucun calendrier aller-retour complet.

### Clubs et cold start

350 clubs distincts sur 3 saisons. Recouvrement avec le référentiel actuel :
**61 clubs (17 %)** par nom exact — **289 clubs à identifier**.

| Matchs européens joués | Clubs | Lecture cold start |
|---|---|---|
| 1-2 | 52 | cold start sévère |
| 3-5 | 59 | cold start |
| 6-10 | 81 | mince |
| 11-25 | 90 | exploitable |
| 26+ | 68 | riche |

**111 clubs sur 350 (32 %) ont 5 matchs européens ou moins.** Une politique de cold
start n'est donc pas un cas limite : c'est le régime d'un tiers du catalogue, et
l'essentiel des tours préliminaires — exactement les matchs de la fenêtre d'août.

---

## 5. Ce que ça implique pour l'architecture

- **§1 est déjà à moitié fait.** `evaluate_live_event` résout la compétition depuis
  l'ÉVÉNEMENT (`event_resolver.resolve_event(raw_event).competition_id`), jamais depuis
  l'équipe. La sélection de capability est donc déjà event-based au niveau décision.
- **Le défaut `_team_league` est dans la couche features**, pas dans la décision :
  `gateway.recent_form(team_id)` appelle `_team_league(team_id)` et suppose une ligue
  unique. C'est là que la double appartenance casse, et c'est là que ça se corrige.
- Une équipe de tour préliminaire n'a souvent **aucune** ligue domestique onboardée
  (Sparta Prague joue en Chance Liga, présente chez Winamax, absente d'Axon) : la
  source de features ne peut pas être « sa ligue », elle doit être l'historique
  européen + un prior de championnat.

---

## 6. Blockers par compétition et par phase (§14)

| Compétition | Phase | Blocker précis |
|---|---|---|
| C1 / EL / UECL | qualifications, barrages | `provider` — tier payant api-sports pour la saison courante |
| C1 / EL / UECL | phase de ligue, knockout | `provider` — idem saison courante |
| C1 / EL / UECL | *toutes, historique 2022-24* | `identity` (289 clubs) puis `model` (inter-championnats à construire) |
| Supercoupe d'Europe | finale unique | `identity` (tid 680 non mappé) + `model` |
| C1 féminine | toutes | `model mismatch` — population distincte, hors périmètre déclaré |

Aucune de ces cases n'est un `CUP_UNSUPPORTED` générique.

---

## 7. Journal des vérifications

| Vérification | Méthode | Résultat |
|---|---|---|
| Événement Lyon–Sparta Prague | `WinamaxConnector.scan_catalog` | existe — C1, tid 151665, 2026-08-11 19:00 |
| Compétitions UEFA du catalogue | idem, 606 événements | 6 entrées, 2 pièges de nommage |
| CL football-data.org saison 2026 | HTTP | 404 |
| CL/EL/UECL api-sports 2026 | HTTP | refus tier Free, message cité |
| CL/EL/UECL api-sports 2022-24 | HTTP, 9 appels | 2 567 matchs persistés |
| Couverture provider par saison | `usable_providers()` | Ligue 1 seule, rien en 2026 |

---

## 8. Benchmark inter-championnats — UEFA_CLUB_MATCH / MATCH_WINNER

Walk-forward strict sur les 2 415 matchs joués (warmup 35 %, puis chaque match est
prédit AVANT d'être observé). Aucun paramètre n'est estimé sur un match postérieur.

| Modèle | Brier | log-loss | ECE | coverage |
|---|---|---|---|---|
| baseline : uniforme | 0,6667 | 1,0986 | 0,1667 | 0,500 |
| baseline : fréquence historique | 0,6210 | 1,0308 | 0,0373 | 0,500 |
| A — Elo européen, nul ajusté à l'écart | 0,6059 | 1,0132 | 0,0547 | 0,522 |
| B — Elo + prior pays (cold start) | 0,6059 | 1,0131 | 0,0531 | 0,520 |
| C — Poisson européen (att/déf, shrinkage) | 0,6061 | **1,0127** | **0,0213** | 0,508 |

Le candidat C par phase :

| Phase | n | Brier | log-loss | ECE |
|---|---|---|---|---|
| qualification | 511 | 0,6024 | 1,0090 | 0,0383 |
| barrage | 222 | 0,6399 | 1,0577 | 0,0664 |
| phase de groupes | 288 | 0,5756 | 0,9719 | 0,0869 |
| phase de ligue | 396 | 0,6043 | 1,0085 | 0,0291 |
| knockout | 153 | 0,6317 | 1,0475 | 0,0785 |

### Lecture

**Aucun candidat ne se détache.** L'écart à la fréquence historique est de 1,8 %
en log-loss et 2,4 % en Brier — soit à peine plus que le bruit d'un jeu de 1 570
prédictions. Les trois candidats sont par ailleurs indiscernables entre eux
(1,0127 / 1,0131 / 1,0132) : le prior pays et la forme fonctionnelle du Poisson
ne changent rien de mesurable. C est retenu pour sa calibration (ECE 0,021, deux
fois meilleure que A) et non pour son pouvoir discriminant.

**Les phases se comportent différemment**, et pas dans le sens attendu : la phase
de groupes est la mieux prédite (Brier 0,576) et les barrages/knockout les pires
(0,640 / 0,632). Les confrontations à élimination directe opposent des équipes de
niveau proche — moins d'information exploitable, mécaniquement.

### Une erreur de méthode corrigée en cours de route

Un premier banc annonçait une log-loss de 0,855 pour l'Elo. Ses probabilités
sommaient à 1,17 : la classe « nul » était ajoutée aux deux autres au lieu d'être
prélevée dessus. Une log-loss calculée sur des probabilités non normalisées est
mécaniquement flatteuse. Le tableau ci-dessus est celui du banc corrigé.

### Ce qui manque pour trancher

Le **no-vig bookmaker** est le plafond de référence, et il est absent : les
payloads api-sports du tier gratuit ne portent pas les cotes historiques. Sans
lui, on sait que les candidats battent à peine la fréquence de base, mais pas de
combien ils sont en dessous du marché. Or c'est cette distance-là qui décide de
l'acceptation : un modèle à 1,013 est excellent si le marché est à 1,010, et sans
valeur s'il est à 0,97.

**Conséquence** : le modèle ne peut pas être accepté ni rejeté sur ces seuls
chiffres. Il reste EXPERIMENTAL par défaut, donc jamais BET (BE-FR-011).
