# TENNIS-001 — Sources, périmètre et pièges d'identité

**Date** : 2026-08-05 · **Statut** : sources acquises et profilées, aucun modèle construit
**Verdict courant** : `TENNIS MODEL UNAVAILABLE` — faute de modèle, pas faute de données.

Chaque ligne vient d'un appel réel. Ce qui n'a pas été vérifié est marqué comme tel.

---

## 1. Catalogue Winamax (sportId=5)

50 événements live, **2 tournois** :

| Libellé Winamax | tid | `sr_tournament_id` | Événements | Tour réel |
|---|---|---|---|---|
| Montréal | `176503` | `sr:tournament:8285` | 26 | **ATP** |
| Toronto | `179030` | `sr:tournament:8279` | 24 | **WTA** |

Marchés : `MATCH_WINNER` en template `2way`, cotes décimales par sélection.

**Le libellé ne porte ni le tour ni le niveau** — juste une ville. Le tour se déduit
des joueurs (Musetti, Tsitsipas, Fils côté Montréal ; Pegula, Rybakina, Bencic côté
Toronto), jamais du nom.

---

## 2. Sources évaluées

### 2.1 Jeff Sackmann — **INDISPONIBLE**

`JeffSackmann/tennis_atp` et `tennis_wta` renvoient **404**. L'API GitHub confirme :
le compte ne publie plus qu'**un seul** dépôt, `tennis_MatchChartingProject`. Testé
sur les branches `main` et `master` ; le réseau fonctionne (contrôle sur
`pandas-dev/pandas` : 200).

Le dépôt subsistant contient du **point-par-point charté** (56 Mo pour les seuls
points masculins 2020s) : riche, mais c'est un sous-ensemble de matchs chartés par
des volontaires, pas une base de résultats de tournée. Non retenu comme source
primaire.

> Conséquence : la source ouverte de référence du tennis n'existe plus. Toute
> documentation qui la recommande est périmée.

### 2.2 Tennis-Data.co.uk — **RETENUE**

URL réelle : `http://www.tennis-data.co.uk/{année}{w}/{année}.xlsx` — **`.xlsx`, pas
`.zip`** (le serveur répond 300 avec le bon nom).

**41 569 matchs**, ATP + WTA, 2015 → 2026 (saison en cours incluse).

| Propriété | Couverture |
|---|---|
| Rankings pré-match (`WRank`/`LRank`/`WPts`/`LPts`) | **100 %** |
| Cotes Pinnacle (`PSW`/`PSL`) | **90,9 %** |
| Cotes B365 / Max / Avg | présentes |
| Surface | Hard 24 330 · Clay 12 299 · Grass 4 940 |
| Best of, Round, Court | présents |
| Statut | Completed 40 032 · **Retired 1 237** · **Walkover 292** |

**Les cotes changent tout** : le no-vig bookmaker — le plafond de référence dont
l'absence bloque le modèle UEFA — est ici disponible sur 9 matchs sur 10.

### 2.3 Providers déjà configurés

api-sports expose le tennis, mais le tier gratuit est limité à 2022-2024 (constat
identique à celui du chantier UEFA). Non nécessaire tant que Tennis-Data suffit.

Tavily n'a pas été sollicité : la source 2 couvre le périmètre principal.

---

## 3. Périmètre réel vs périmètre visé

| Niveau visé | Couvert | Volume |
|---|---|---|
| Grand Slam | ✅ | 8 636 |
| Masters 1000 | ✅ | 4 930 |
| ATP 500 / 250 | ✅ | 3 485 / 8 638 |
| WTA 1000 / 500 / 250 | ✅ | 3 616 / 2 624 / 4 697 |
| WTA International / Premier (ancien nommage) | ✅ | 2 402 / 2 245 |
| Tour Championships / Masters Cup | ✅ | 150 / 120 |
| **Qualifications** | ❌ | absentes |
| **Challenger** | ❌ | absent |
| **WTA 125** | ❌ | absent |
| **ITF** | ❌ | absent |

Tennis-Data couvre le **tableau principal de la tournée**, rien en dessous. Les
qualifications, Challenger, WTA 125 et ITF exigeraient une autre source — celle qui
les portait (Sackmann) a disparu.

**Défaut de qualité repéré** : 26 lignes portent un `Series` corrompu incrémenté
(`WTA251`, `WTA252`, … `WTA276`, une occurrence chacun). À normaliser au chargement,
et à ne jamais traiter comme des niveaux distincts.

---

## 4. Pièges d'identité — à traiter avant toute modélisation

### 4.1 Le Canadian Open alterne les villes entre ATP et WTA

Tennis-Data nomme le tournoi `Location=Toronto, Tournament=Canadian Open` en 2025
côté ATP. En 2026, Winamax place l'**ATP à Montréal** et la **WTA à Toronto**.

> Un mapping ville → tournoi **inverserait les deux tours** une année sur deux, et
> ferait tourner un modèle masculin sur des matchs féminins. C'est exactement le
> piège « Ligue des Champions (F) » du chantier UEFA. La résolution doit passer par
> le recouvrement des joueurs, jamais par la chaîne de caractères.

### 4.2 Deux formats de nom, deux niveaux d'abréviation

| Source | Format |
|---|---|
| Winamax `slot_N_name` | `Nicolas Mejia` (prénom complet) |
| Winamax label de sélection | `N. Mejia` (initiale) |
| Tennis-Data | `Popyrin A.` (**nom d'abord**, puis initiale) |

**1 625 joueurs distincts.** Trois collisions détectées, toutes de pure casse
(`McDonald M.` / `Mcdonald M.`) — normalisables sans ambiguïté.

**Limite de cette mesure, à ne pas surinterpréter** : elle détecte deux
*orthographes* menant au même couple (nom, initiale). Elle ne peut PAS détecter deux
joueurs réellement différents partageant nom et initiale — ils produisent la même
chaîne et sont indiscernables dans la source. Le risque résiduel existe et impose
`PLAYER_IDENTITY_UNRESOLVED` en cas de doute, jamais un rapprochement flou.

### 4.3 Schémas ATP et WTA différents

Le fichier ATP porte une colonne `Series`, le fichier WTA porte `Tier` (36 vs 32
colonnes selon les années). Le loader doit normaliser, pas supposer.

---

## 5. Abandons et walkovers

1 237 abandons et 292 walkovers, soit **3,7 %** des matchs. Ils ne sont pas des
victoires ordinaires :

- un **walkover** n'a pas eu lieu — il n'informe en rien sur la force relative et
  doit être exclu de l'entraînement ;
- un **abandon** a un vainqueur réel mais un score partiel ; l'inclure tel quel
  biaise toute statistique dérivée du score.

Le traitement doit être explicite et testé, pas implicite.

---

## 6. Blockers restants

| Sujet | Blocker |
|---|---|
| Qualifications / Challenger / WTA 125 / ITF | `provider` — aucune source ouverte identifiée depuis la disparition de Sackmann |
| Modèle | aucun candidat construit à ce stade |
| Live wiring | non câblé |
| CLV collector | non évalué |

Le périmètre principal (Grand Slam, Masters, ATP/WTA 500/250) est en revanche
entièrement couvert, avec cotes et rankings — de quoi construire ET arbitrer un
modèle contre le marché, ce qui n'était pas possible côté UEFA.

---

## 7. Benchmark — 8 modèles, walk-forward point-in-time

Le module `model_comparison.py` rejoue la chronologie UNE fois en maintenant tous
les systèmes : chaque système prédit le MÊME match éligible à partir de son seul
état antérieur. `market` = no-vig Pinnacle, **plafond de référence, jamais un
candidat**.

**ATP : 54 709 matchs éligibles / 70 688** · **WTA : 34 954 / 46 769** (2000→2026)

| Modèle | Brier ATP | Brier WTA | ECE ATP | ECE WTA |
|---|---|---|---|---|
| *market (no-vig Pinnacle)* | *0,1987* | *0,2050* | *0,0111* | *0,0077* |
| elo_surface | 0,2110 | 0,2160 | 0,0178 | 0,0212 |
| elo | 0,2130 | 0,2162 | 0,0172 | 0,0142 |
| glicko2 | 0,2131 | 0,2164 | 0,0213 | 0,0251 |
| elo_538 | 0,2144 | 0,2172 | 0,0338 | 0,0362 |
| glicko | 0,2169 | 0,2206 | 0,0098 | 0,0209 |
| rank_logistic | 0,2185 | 0,2231 | 0,0051 | 0,0190 |
| rank_favorite | 0,2292 | 0,2315 | 0,0055 | 0,0200 |

### Le classement global ne suffit pas à choisir

Sur le **holdout 2023+**, l'ordre s'inverse : `elo` (0,2190 ATP / 0,2166 WTA) passe
devant `elo_surface` (0,2196 / 0,2175). Choisir sur le Brier全-période aurait
retenu le mauvais modèle.

### Brier apparié, holdout 2023+ (delta < 0 = le premier est meilleur)

| Comparaison | ATP | WTA | Verdict |
|---|---|---|---|
| elo − elo_surface | −0,00055 · IC [−0,00202, +0,00102] | −0,00090 · IC [−0,00222, +0,00049] | **non démontré** |
| elo − glicko2 | −0,00035 · IC [−0,00102, +0,00037] | +0,00005 · IC [−0,00063, +0,00072] | **non démontré** |
| elo − elo_538 | −0,00274 · IC [−0,00373, −0,00174] | −0,00181 · IC [−0,00283, −0,00083] | elo meilleur |
| elo − rank_favorite | −0,01248 · IC [−0,01545, −0,00929] | −0,01843 · IC [−0,02159, −0,01511] | elo meilleur |
| **elo − market** | **+0,01460 · IC [+0,01242, +0,01683]** | **+0,00995 · IC [+0,00783, +0,01198]** | **le marché est meilleur** |

### Modèle retenu : `elo`

`elo`, `elo_surface` et `glicko2` sont **statistiquement indiscernables** sur le
holdout — leurs intervalles de confiance contiennent zéro. Départager sur les
estimations ponctuelles reviendrait à choisir sur du bruit. À performance non
distinguable, le modèle **le plus simple** est retenu : `elo` n'a pas de mélange de
surface à calibrer, donc pas de paramètre supplémentaire à faire dériver.

Les trois battent significativement la baseline de classement : le modèle a une
valeur réelle au-dessus du naïf.

### Ce que le benchmark démontre aussi, et qui est bloquant

**Le marché bat significativement tous les candidats**, sur les deux tours et hors
échantillon : +0,0146 de Brier ATP, +0,0099 WTA, intervalles entièrement positifs.

Un modèle démontré en dessous du marché ne peut pas produire d'edge réel contre les
prix de ce marché. Toute « value » qu'il calculerait serait du bruit. C'est un
STOP money-sensitive objectif, pas une prudence de principe.

## 8. Maturité mécanique

| | ATP | WTA |
|---|---|---|
| `model_version` | `tennis.atp.elo.v0` | `tennis.wta.elo.v0` |
| **status** | **EXPERIMENTAL** | **EXPERIMENTAL** |
| n_evaluated | 54 709 | 34 954 |
| folds temporels | 27 | 20 |
| calibration_error | 0,0172 | 0,0142 |
| min_sample_size | PASS (seuil 500) | PASS |
| min_data_coverage | **FAIL** | **FAIL** |
| positive_clv | **NOT_MEASURABLE** | **NOT_MEASURABLE** |

`policy_checksum 410fd3c5…`, `policy_version 2` — verdict mécanique, aucun seuil
abaissé. EXPERIMENTAL ⇒ jamais BET (BE-FR-011).
