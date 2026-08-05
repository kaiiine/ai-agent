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
