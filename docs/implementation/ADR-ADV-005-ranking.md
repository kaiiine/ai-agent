# ADR-ADV-005 — Formule de ranking V1

**Statut** : accepté (revue Lot 4 → prérequis Lot 5).
**Portée** : Ranking Engine V1. Consomme des `CandidateEvaluation` produites par la Policy (Lot 4).

## Contexte

Le Ranking Engine attribue un `ranking_score` (PRD §12). La formule est
multiplicative, donc **un composant à 0 annule le score** — ce qui doit être une
conséquence *intentionnelle et documentée* de la sémantique d'un composant,
jamais évité par un plancher générique (interdit). Le PRD §12.2.1 exige de
trancher, pour chaque composant, son domaine, le sens de `0`, et le traitement
d'une donnée manquante, **avant** de coder.

## Décisions

### D0 — Frontière : on ne classe QUE `ELIGIBLE`

```
ELIGIBLE     -> Ranking Engine -> ranking_score
REVIEW_ONLY  -> RecommendationResponse.review_candidates (pas de ranking_score)
REJECTED     -> hors ranking
```

En V1, tous les modèles réels sont `EXPERIMENTAL` : ils restent `REVIEW_ONLY` et
**ne passent pas** par le Ranking. Le Ranking Engine est donc construit et testé
avec des **fixtures `SUPPORTED`/`ELIGIBLE`** ; il n'aura simplement pas de
candidats réels à classer en production tant qu'aucun modèle n'est `SUPPORTED`.
On ne détourne pas le contrat pour produire un classement visible « tout de
suite ».

### D1 — `policy_component` retiré de la formule

La formule §12.1 liste `policy_component`, absent de §12.2. Résolution : la
Policy (Lot 4) a déjà réalisé **toute** l'éligibilité ; tout candidat classé est
déjà `ELIGIBLE`, donc `policy_component` vaudrait `1` pour tous et n'aurait aucun
rôle discriminant. Il est **retiré**. Formule effective :

```
base_score      = value × reliability × quality × freshness × liquidity − uncertainty_penalty
ranking_score   = base_score − concentration_penalty   (séquentiel, cf. D5)
```

### D2 — REQUIRED vs OPTIONAL, par composant et par profil

Chaque profil déclare, pour chaque composant, `REQUIRED` ou `OPTIONAL` :

- **REQUIRED + donnée absente → candidat NON RANKABLE** : rejet explicite avec
  un reason code stable (jamais un score inventé).
- **OPTIONAL → politique explicite du composant** (définie ci-dessous). Aucun
  comportement générique implicite. Retirer un facteur d'un produit revient à lui
  donner un effet neutre ≈ `1`, ce qui avantagerait indûment un candidat dont
  l'information est *inconnue* face à un candidat dont elle est *mesurée* : donc
  **jamais** `missing → exclu`, **jamais** `missing → 1`, **jamais** `missing → 0`.

### D3 — Sémantique par composant (profils V1)

| Composant | R/O | Domaine | `0` signifie | Donnée manquante |
|---|---|---|---|---|
| `value_component` | REQUIRED | `[0,1]`, monotone ↗ de `expected_value_low` (linéaire bornée entre `ev_floor` et `ev_cap` de config) | `ev_low ≤ ev_floor` : **valeur pire-cas mesurée au minimum** (annulation intentionnelle) | jamais absent (dérivé) pour un ELIGIBLE |
| `quality_component` | REQUIRED | `[0,1]` = `data_quality` | qualité **mesurée** nulle | jamais absent (`Decimal` non-optionnel) |
| `freshness_component` | REQUIRED | `[0,1]` = `freshness_score` | fraîcheur **mesurée** au minimum | `None` ne doit jamais atteindre le ranking (Policy dégrade/rejette). Défensif : `None` sur un ELIGIBLE → NON RANKABLE (`RANKING_MISSING_FRESHNESS`) |
| `reliability_component` | REQUIRED | `[0,1]`, fonction de `model_maturity` (+ `calibration_score` si présent) | calibration **mesurée** nulle | seul `SUPPORTED` atteint le ranking ; `reliability = calibration_score` si présent, sinon **`supported_baseline`** (config, ∈(0,1)) — valeur *fondée sur la maturité*, explicitement documentée, **ni 0 (jamais mesuré) ni 1 (parfait)** ; on ne prétend pas utiliser une calibration absente |
| `liquidity_component` | **OPTIONAL** (V1) | `[0,1]` = `liquidity_score` si présent | liquidité **mesurée** nulle | `None` → **`liquidity_unknown_default`** (config, ∈(0,1)) : escompte **conservateur** documenté, délibérément `< 1` (un candidat à liquidité inconnue ne doit pas dépasser un candidat à liquidité mesurée-haute) et `> 0` (n'annule pas). Uniforme en V1 (tous `None`) → sans distorsion relative. Jamais retiré silencieusement |
| `uncertainty_penalty` | structurel (input toujours présent) | pénalité `≥ 0` = `uncertainty_weight × (probability_high − probability_low)` | **estimation serrée** (intervalle nul, ESTIMATED) : aucune pénalité — jamais « inconnu » | `CandidateBet` ne porte pas `uncertainty_status`. Politique explicite : `NOT_ESTIMATED ⟹ EXPERIMENTAL ⟹ jamais ELIGIBLE` (SUPPORTED exige une incertitude estimée, BE-FR-012) → le cas est **exclu en amont** par la frontière d'éligibilité, pas re-vérifié ici. La largeur au ranking est donc toujours un intervalle **ESTIMATED réel**. On ne fabrique jamais de largeur. (Si un jour le ranking doit re-vérifier le statut, ajouter `uncertainty_status` à `CandidateBet`.) |
| `concentration_penalty` | structurel | pénalité `≥ 0` = `concentration_weight × redondance(c, retenus)` ; `redondance = |c.exposure ∩ (∪ retenus.exposure)| / |c.exposure| ∈ [0,1]` | **aucune redondance** avec les déjà-retenus (le rang 1 vaut toujours 0) | `exposure_keys` toujours présent (dérivé) |

### D4 — Bornes du score & sémantique de `0`

`base_score ∈ [−uncertainty_max, 1]` (produit de facteurs `[0,1]` moins une
pénalité). `ranking_score = base_score − concentration_penalty`. Plus grand =
meilleur. Un composant à `0` annule le produit **uniquement** quand sa sémantique
l'autorise (cf. D3). **Aucun floor générique** n'est appliqué.

### D5 — Concentration séquentielle/gloutonne (limitation V1)

`concentration_penalty` dépend des candidats **déjà retenus** : le classement est
une heuristique **séquentielle/gloutonne**, jamais un optimum global (ADV-NFR-012).
Documenté dans le code ET dans l'explication de sortie.

Algorithme : (1) `base_score` par candidat (indépendant de l'ordre d'entrée) ;
(2) construction gloutonne : à chaque étape, sélectionner le candidat maximisant
`base_score − concentration_penalty(vs déjà-retenus)`, départage §12.4.

### D6 — Déterminisme, tie-breakers, indépendance à l'ordre (§12.4, §12.6)

Départage : (1) meilleure `expected_value_low` ; (2) meilleure calibration
(`reliability_component`) ; (3) meilleure fraîcheur ; (4) plus faible
concentration ; (5) `candidate_id` lexical. Le dernier critère garantit un ordre
**total** → classement **strictement identique quel que soit l'ordre d'entrée**.
Test `shuffle` obligatoire.

### D7 — Profils (config versionnée)

`configs/advisor/ranking_profiles.json` : `conservative_v1` / `balanced_v1` /
`aggressive_v1`. Chaque profil = données (déclarations R/O + paramètres :
`ev_floor`/`ev_cap`, `supported_baseline`, `liquidity_unknown_default`,
`uncertainty_weight`, `concentration_weight`), aucune logique. Valeurs
**placeholders documentées à calibrer**. Conservateur pénalise davantage
incertitude/concentration et exige plus d'EV (`ev_floor` plus haut) ; agressif
l'inverse.

## Conséquences

- V1 : aucun candidat `ELIGIBLE` réel (modèles `EXPERIMENTAL`) → ranking exercé
  par fixtures. Le moteur est correct et prêt, non contourné.
- `liquidity_component` OPTIONAL est le seul composant à politique de fallback en
  V1 ; explicite et conservateur, jamais neutre.
- Un candidat `ELIGIBLE` mais sans input REQUIRED (ex. `freshness_score=None`,
  ou `model_maturity ≠ SUPPORTED`) est **rejeté au ranking** avec un code stable
  (`RANKING_MISSING_FRESHNESS`, `RANKING_MODEL_NOT_SUPPORTED`), pas rendu au
  hasard. En pratique la Policy (Lot 4) garantit déjà ces inputs pour tout
  ELIGIBLE : ces gardes sont défensives (et testées sur candidats forgés).
