# PRD — `axon-advisor`

**Statut :** Accepted for implementation  
**Dépend de :** `axon-betting-engine` et `axon-sports-data-gateway`  
**Position dans la chaîne :** couche produit au-dessus de `axon-betting-engine`  
**Auteur :** Kaine  
**Dernière mise à jour :** 28 juillet 2026

---

## 1. Correction de direction produit

Le projet a historiquement été conçu comme un moteur de prédiction et de détection de valeur :

```text
Bookmaker
→ identité
→ données sportives
→ features
→ MarketModel
→ calibration
→ ValueEngine
→ BET / WATCH / ABSTAIN
```

Cette chaîne est nécessaire mais ne répond pas entièrement au besoin utilisateur initial :

> « J'ai 5 €, quels sont aujourd'hui les meilleurs paris ou combinés pour viser environ x2 ou x3 ? »

La différence est structurelle.

Le `BettingEngine` répond à une question d'estimation :

> Quelle est la probabilité de cette sélection et quelle valeur présente sa cote ?

Le produit attendu doit répondre à une question de décision sous contraintes :

> Parmi toutes les opportunités disponibles, que proposer à cet utilisateur, avec cette bankroll, cet objectif, ce niveau de risque et ces exclusions ?

`axon-advisor` est introduit pour porter cette responsabilité sans contaminer le moteur probabiliste avec des préférences utilisateur, de la logique de portefeuille ou des considérations d'interface.

### 1.1 Nouvelle architecture produit

```text
Bookmakers
    │
    ▼
axon-betting-engine
    │
    ├── Catalogue
    ├── Canonicalisation
    ├── Feature Engineering
    ├── Market Models
    ├── Calibration
    └── Value Engine
    │
    ▼
axon-advisor
    ├── Candidate Generator
    ├── Eligibility & Policy
    ├── Ranking Engine
    ├── Portfolio Optimizer
    ├── Combo Builder
    ├── Recommendation Engine
    └── Presentation Adapters
    │
    ▼
CLI / API / UI / Agent Axon
```

### 1.2 Règle de dépendance

`axon-advisor` dépend de l'API publique de `axon-betting-engine`.

Aucun composant d'Advisor :

- ne recalcule une probabilité sportive ;
- ne crée des features sportives ;
- ne retire la marge d'un bookmaker ;
- ne remplace la calibration d'un modèle ;
- ne modifie un connecteur bookmaker ;
- ne modifie `axon-sports-data-gateway`.

Toute évolution nécessaire dans une dépendance est portée par son propre PRD et son propre commit.

---

## 2. Vision

Axon Advisor est un moteur universel de recommandation de paris sportifs.

Il doit pouvoir produire, pour une demande donnée :

1. aucune recommandation ;
2. une recommandation simple ;
3. plusieurs paris simples répartissant la bankroll ;
4. un combiné ;
5. plusieurs portefeuilles alternatifs ;
6. une liste de candidats à examiner lorsque les modèles sont encore expérimentaux.

Le système doit rester indépendant :

- du sport ;
- de la ligue ;
- du bookmaker ;
- du type de marché ;
- de la méthode statistique ;
- de l'interface utilisateur.

L'ajout ultérieur d'une nouvelle ligue ou d'un nouveau sport ne doit jamais nécessiter de modifier le moteur de recommandation, tant que le `BettingEngine` expose les contrats canoniques attendus.

---

## 3. Objectifs

1. Transformer les évaluations du Betting Engine en candidats comparables.
2. Classer les opportunités de sports, ligues et marchés différents.
3. Construire un portefeuille cohérent avec une bankroll et des contraintes utilisateur.
4. Supporter les paris simples et les combinés.
5. Refuser les combinaisons incohérentes, interdites ou insuffisamment modélisées.
6. Expliquer chaque proposition et chaque refus.
7. Permettre un mode expérimental qui expose des candidats sans les présenter comme certifiés.
8. Fournir des interfaces stables pour le CLI, l'API et l'agent Axon.
9. Préserver l'auditabilité complète d'une recommandation.
10. Permettre l'ajout de sports, ligues, bookmakers et stratégies sans réécriture du cœur.

---

## 4. Non-objectifs

- Placer automatiquement un pari.
- Garantir un gain.
- Chercher à atteindre coûte que coûte une cote cible.
- Transformer une cote cible en promesse de rendement.
- Autoriser un marché sans modèle ou politique explicite.
- Utiliser un modèle `EXPERIMENTAL` comme s'il était `SUPPORTED`.
- Inventer une corrélation lorsqu'aucune donnée ou règle structurelle n'existe.
- Multiplier naïvement des probabilités dépendantes.
- Mélanger la bankroll utilisateur avec les paramètres du MarketModel.
- Optimiser uniquement le rendement théorique sans contrainte de risque.
- Construire le live avant qu'un marché pré-match équivalent soit validé.
- Contourner les limites, règles ou conditions d'un bookmaker.

---

## 5. Terminologie

| Terme | Définition |
|---|---|
| Evaluation | Sortie du Betting Engine pour une sélection et une cote données |
| Candidate | Evaluation normalisée et éligible au classement |
| Opportunity | Candidate suffisamment qualifié pour être montré |
| Portfolio | Ensemble cohérent de lignes de mise |
| Line | Une mise proposée sur un pari simple ou combiné |
| Recommendation | Réponse finale exposée à l'utilisateur |
| Target odds | Intervalle souhaité, jamais une obligation |
| Model maturity | Statut de validation du modèle |
| Policy | Règle de produit déterminant l'éligibilité |
| Strategy | Manière configurable de classer et d'allouer |
| Exposure | Risque partagé par événement, participant, ligue ou facteur |
| Combo | Pari composé de plusieurs legs |
| Leg | Une sélection composant un combiné |

---

## 6. Principes architecturaux

### 6.1 Estimation ≠ recommandation

Le Betting Engine estime.

Advisor décide sous contraintes.

Aucune méthode de `axon-advisor` ne doit avoir besoin de connaître Dixon-Coles, Elo, Poisson, xG, ERA, surface de tennis ou tout autre détail spécifique à un sport.

### 6.2 Une cote cible est une préférence, pas une contrainte absolue

Si l'utilisateur demande une cote entre 2,00 et 3,00, le moteur :

- privilégie les portefeuilles respectant cet intervalle ;
- peut proposer une alternative hors intervalle si elle est sensiblement meilleure ;
- peut ne rien proposer si l'intervalle force des choix de mauvaise qualité.

### 6.3 L'abstention reste valide

Le système doit pouvoir répondre :

> Aucune proposition n'atteint les seuils minimaux aujourd'hui.

Cette réponse n'est ni une erreur ni une absence de résultat.

### 6.4 Les stratégies sont configurables, pas codées dans les sports

Une stratégie conservatrice s'applique de la même manière à un pari football, tennis ou NBA.

### 6.5 Tout résultat est reproductible

À demande, catalogue, cotes, versions de modèles, politiques et configuration identiques, la recommandation doit être identique.

### 6.6 Les modèles expérimentaux restent visibles sans devenir certifiés

Un modèle `EXPERIMENTAL` peut produire un `REVIEW_CANDIDATE`.

Il ne peut produire une recommandation labellisée `SUPPORTED_RECOMMENDATION`.

---

## 7. Architecture

```text
axon-betting-engine
    │
    ▼
input_adapter/
    └── betting_engine_adapter.py
    │
    ▼
candidate_generation/
    ├── generator.py
    ├── normalization.py
    └── quality.py
    │
    ▼
policy/
    ├── eligibility.py
    ├── maturity.py
    ├── market_policy.py
    └── user_constraints.py
    │
    ▼
ranking/
    ├── scorer.py
    ├── ranking_profile.py
    ├── diversification.py
    └── explanations.py
    │
    ▼
portfolio/
    ├── optimizer.py
    ├── bankroll.py
    ├── exposure.py
    ├── constraints.py
    └── allocation.py
    │
    ▼
combos/
    ├── builder.py
    ├── dependency.py
    ├── compatibility.py
    ├── pricing.py
    └── pruning.py
    │
    ▼
recommendation/
    ├── engine.py
    ├── alternatives.py
    ├── explanation.py
    └── audit.py
    │
    ▼
interfaces/
    ├── cli.py
    ├── api.py
    └── serializers.py
```

---

## 8. Contrats canoniques

### 8.1 RecommendationRequest

```python
@dataclass(frozen=True)
class RecommendationRequest:
    request_id: str
    decision_time: datetime
    bankroll: Decimal
    currency: str

    allowed_sports: frozenset[str] | None
    allowed_competitions: frozenset[str] | None
    allowed_bookmakers: frozenset[str] | None
    allowed_market_types: frozenset[str] | None

    target_total_odds: OddsRange | None
    max_total_stake: Decimal | None
    max_selections: int
    max_portfolios: int

    allow_singles: bool
    allow_combos: bool
    max_combo_legs: int

    risk_profile: RiskProfile
    maturity_policy: MaturityPolicy
    ranking_profile: str

    excluded_event_ids: frozenset[str]
    excluded_participant_ids: frozenset[str]
    excluded_market_types: frozenset[str]
```

#### Invariants

- `bankroll > 0`
- `max_total_stake <= bankroll`
- `max_selections >= 1`
- `max_combo_legs >= 2` lorsque `allow_combos=True`
- `target_total_odds.min <= target_total_odds.max`
- `decision_time` est explicite et propagé à toutes les dépendances
- les montants utilisent `Decimal`, jamais `float`

### 8.2 OddsRange

```python
@dataclass(frozen=True)
class OddsRange:
    minimum: Decimal
    maximum: Decimal
```

### 8.3 RiskProfile

```python
class RiskProfile(Enum):
    CONSERVATIVE = "CONSERVATIVE"
    BALANCED = "BALANCED"
    AGGRESSIVE = "AGGRESSIVE"
    CUSTOM = "CUSTOM"
```

### 8.4 MaturityPolicy

```python
class MaturityPolicy(Enum):
    SUPPORTED_ONLY = "SUPPORTED_ONLY"
    INCLUDE_EXPERIMENTAL_FOR_REVIEW = "INCLUDE_EXPERIMENTAL_FOR_REVIEW"
```

### 8.5 CandidateBet

```python
@dataclass(frozen=True)
class CandidateBet:
    candidate_id: str

    event_id: str
    sport: str
    competition_id: str
    scheduled_at: datetime

    bookmaker: str
    market_id: str
    market_type: str
    selection: str

    bookmaker_odds: Decimal
    fair_probability: Decimal
    probability_low: Decimal
    probability_high: Decimal
    fair_odds: Decimal
    implied_probability: Decimal

    expected_value_mean: Decimal
    expected_value_low: Decimal
    edge_mean: Decimal
    edge_low: Decimal

    model_version: str
    model_maturity: str
    calibration_score: Decimal | None
    data_quality: Decimal
    freshness_score: Decimal | None    # divergence assumée v1 (cf. §8.5.1) : le Betting Engine n'expose pas la fraîcheur
    liquidity_score: Decimal | None

    max_stake: Decimal | None
    max_payout: Decimal | None
    is_boosted: bool

    participant_ids: tuple[str, ...]
    exposure_keys: frozenset[str]

    warnings: tuple[str, ...]
    explanation_ref: str
    source_decision_id: str
```

#### Invariants

- `0 <= fair_probability <= 1`
- `0 <= probability_low <= fair_probability <= probability_high <= 1`
- `bookmaker_odds > 1`
- `fair_odds = 1 / fair_probability` dans la précision définie
- `expected_value_low` utilise `probability_low`
- `candidate_id` est stable pour une même évaluation
- tous les scores normalisés sont compris entre 0 et 1
- aucune métrique absente n'est remplacée par une valeur favorable inventée

#### 8.5.1 Divergence assumée v1 — `freshness_score` optionnel (frontière Gateway / Betting Engine)

**Constat (Lot 0)** : le Betting Engine n'expose pas la fraîcheur des cotes/features via son API publique — le `CanonicalEnvelope` de la gateway porte `stale`/`freshness_score`, mais `recent_form`/`standings_strength` les jettent, et l'orchestrateur n'émet qu'un warning `freshness_unavailable`. Aucune valeur de fraîcheur mesurable n'atteint donc Advisor aujourd'hui.

**Décision** : `freshness_score` devient `Decimal | None`. Une fraîcheur inconnue n'est **jamais** assimilée à `0` ni traitée silencieusement comme neutre (ADV-FR-041). Deux raisons distinctes existent :

- `FRESHNESS_UNKNOWN` — fraîcheur **non mesurable** (le champ est `None`) ;
- `STALE_ODDS` — fraîcheur **mesurée et insuffisante**.

**Politique de maturité × fraîcheur inconnue** :

| Maturity policy | freshness_score = None |
|---|---|
| `SUPPORTED_ONLY` | `REJECTED` (`FRESHNESS_UNKNOWN`) — jamais `ELIGIBLE` |
| `INCLUDE_EXPERIMENTAL_FOR_REVIEW` | peut rester `REVIEW_ONLY` |

Le warning `freshness_unavailable` reste **visible dans les warnings jusqu'à la sortie finale**.

**Dette de frontière** : rendre la fraîcheur mesurable est un travail **Gateway / Betting Engine** (exposer `stale`/`freshness_score` dans l'API publique), porté par son propre PRD/commit — hors périmètre Advisor. Tant qu'il n'est pas fait, `freshness_score` reste `None` et la politique ci-dessus s'applique. Non bloquant pour la v1 (modèle EXPERIMENTAL ⇒ aucune mise de toute façon).

### 8.6 CandidateStatus

```python
class CandidateStatus(Enum):
    ELIGIBLE = "ELIGIBLE"
    REVIEW_ONLY = "REVIEW_ONLY"
    REJECTED = "REJECTED"
```

### 8.7 CandidateEvaluation

```python
@dataclass(frozen=True)
class CandidateEvaluation:
    candidate: CandidateBet
    status: CandidateStatus
    policy_reasons: tuple[str, ...]
    ranking_score: Decimal | None
    ranking_components: Mapping[str, Decimal]
```

### 8.8 BetLeg

```python
@dataclass(frozen=True)
class BetLeg:
    candidate_id: str
    event_id: str
    market_id: str
    selection: str
    bookmaker: str
    odds: Decimal
```

### 8.9 PortfolioLine

```python
class LineType(Enum):
    SINGLE = "SINGLE"
    COMBO = "COMBO"

@dataclass(frozen=True)
class PortfolioLine:
    line_id: str
    line_type: LineType
    bookmaker: str
    legs: tuple[BetLeg, ...]
    stake: Decimal
    total_odds: Decimal
    estimated_probability: Decimal
    expected_value: Decimal
    worst_case_ev: Decimal
    correlation_warning: str | None
```

### 8.10 RecommendationPortfolio

```python
@dataclass(frozen=True)
class RecommendationPortfolio:
    portfolio_id: str
    request_id: str
    strategy_id: str

    lines: tuple[PortfolioLine, ...]
    total_stake: Decimal
    unallocated_bankroll: Decimal

    expected_return: Decimal
    expected_profit: Decimal
    downside_score: Decimal
    concentration_score: Decimal

    target_odds_match: bool
    quality_score: Decimal
    warnings: tuple[str, ...]
    explanation: "PortfolioExplanation"
```

### 8.11 RecommendationResponse

```python
class RecommendationOutcome(Enum):
    RECOMMENDED = "RECOMMENDED"
    REVIEW_CANDIDATES = "REVIEW_CANDIDATES"
    NO_OPPORTUNITY = "NO_OPPORTUNITY"
    NO_EVALUABLE_EVENTS = "NO_EVALUABLE_EVENTS"
    FAILED = "FAILED"

@dataclass(frozen=True)
class RecommendationResponse:
    request_id: str
    generated_at: datetime
    outcome: RecommendationOutcome
    portfolios: tuple[RecommendationPortfolio, ...]
    review_candidates: tuple[CandidateEvaluation, ...]
    rejection_summary: Mapping[str, int]
    warnings: tuple[str, ...]
    audit_id: str
```

---

## 9. Adaptateur Betting Engine

`betting_engine_adapter.py` est l'unique frontière entre Advisor et le Betting Engine.

Il traduit les sorties publiques du moteur vers un contrat interne d'Advisor.

Cette couche existe pour éviter que les évolutions de noms, d'énums ou de formats dans le Betting Engine se propagent dans le ranking et le portfolio.

### Responsabilités

- charger les évaluations pour `decision_time` ;
- vérifier la version de schéma ;
- convertir les nombres vers `Decimal` ;
- propager l'identité, les avertissements et la traçabilité ;
- échouer explicitement sur une version incompatible.

### Interdictions

- recalculer une EV ;
- recalculer une probabilité implicite ;
- modifier le statut de maturité ;
- supprimer un warning ;
- transformer un `EXPERIMENTAL` en `SUPPORTED`.

---

## 10. Candidate Generator

Le Candidate Generator normalise toutes les évaluations en `CandidateBet`.

Il ne décide pas encore si un candidat doit être recommandé.

### 10.1 Étapes

1. validation du contrat source ;
2. normalisation des identifiants ;
3. calcul des champs dérivés autorisés ;
4. enrichissement avec les clés d'exposition ;
5. construction d'un identifiant stable ;
6. attachement des références d'explication ;
7. émission du candidat.

### 10.2 Champs dérivés autorisés

- `fair_odds` à partir de `fair_probability` ;
- `edge_mean` à partir de probabilités déjà validées ;
- `edge_low` à partir de la borne basse ;
- clés d'exposition structurelles ;
- scores de fraîcheur à partir de timestamps explicites.

Le Candidate Generator ne peut pas créer de nouvelles données sportives.

#### 10.2.1 Définitions canoniques (tranchées au Lot 3)

- **`edge`** : `edge = probabilité_modèle − probabilité_no_vig_marché`, **définition héritée du Betting Engine** (`value_engine/decision.py` : `edge = model_p − no_vig_p`) et non une sémantique nouvelle. `edge_mean = fair_probability − no_vig_probability`, `edge_low = probability_low − no_vig_probability`. Le `no_vig` (marge retirée) est propagé du moteur, jamais recalculé. `implied_probability` reste l'implicite **brute** (`1/cote`) à titre informatif, distincte du seuil d'edge. Cette définition est figée **avant le Lot 5** puisque le ranking consomme `edge`.
- **`candidate_id`** : identité de l'**offre observée** (ADR-ADV-003) — hash de `bookmaker | event_id | market_id | selection | model_version | observed_at`, où `observed_at` = instant d'observation des cotes côté bookmaker (`RawBookmakerEvent.fetched_at`), **jamais** le `decision_time` de la requête Advisor. Deux requêtes observant le même snapshot produisent le même id. Limite V1 : `fetched_at` est l'instant de scan, faute d'un `snapshot_id` / timestamp de mise à jour de cote intrinsèque (dette connecteur, même famille que Q5).

---

## 11. Eligibility & Policy

La couche Policy détermine si un candidat peut entrer dans le ranking.

### 11.1 Ordre de décision

```text
Schema validity
→ user filters
→ bookmaker availability
→ model maturity
→ market policy
→ data quality
→ freshness
→ odds and stake constraints
→ candidate status
```

### 11.2 Règles de maturité

| Statut modèle | SUPPORTED_ONLY | INCLUDE_EXPERIMENTAL_FOR_REVIEW |
|---|---:|---:|
| SUPPORTED | ELIGIBLE | ELIGIBLE |
| EXPERIMENTAL | REJECTED | REVIEW_ONLY |
| INSUFFICIENT_DATA | REJECTED | REJECTED |
| UNSUPPORTED | REJECTED | REJECTED |
| DEPRECATED | REJECTED | REJECTED |

### 11.3 Règles minimales

- `expected_value_low` doit être supérieur au seuil du profil pour devenir `ELIGIBLE`.
- Un candidat avec données trop anciennes est rejeté.
- Une offre boostée n'est éligible que si son marché sous-jacent est `SUPPORTED`.
- `max_stake` et `max_payout` sont propagés jusqu'à l'allocation.
- Un marché interdit par l'utilisateur est rejeté avant ranking.
- Un événement déjà commencé est rejeté en mode pré-match.
- Un conflit identitaire est toujours rejeté.

### 11.4 Raisons structurées

Les raisons sont des codes stables, par exemple :

```text
MODEL_NOT_SUPPORTED
EXPERIMENTAL_REVIEW_ONLY
LOW_WORST_CASE_EV
LOW_DATA_QUALITY
STALE_ODDS
FRESHNESS_UNKNOWN
USER_FILTERED_SPORT
USER_FILTERED_COMPETITION
USER_FILTERED_MARKET
EVENT_ALREADY_STARTED
IDENTITY_CONFLICT
STAKE_LIMIT_TOO_LOW
```

---

## 12. Ranking Engine

Le Ranking Engine compare des candidats hétérogènes sans connaître leur sport.

### 12.1 Score

Le score n'est pas l'EV brute.

```text
ranking_score =
value_component
× reliability_component
× quality_component
× freshness_component
× liquidity_component
× policy_component
− concentration_penalty
− uncertainty_penalty
```

Chaque composant est borné et explicable.

Le produit étant multiplicatif, **un composant à 0 annule le score final**. Ce comportement n'est pas un défaut à corriger par un plancher artificiel (ex. un floor arbitraire type `0.05`) : il doit être une conséquence intentionnelle et documentée de la sémantique du composant concerné. Un floor générique masquerait un vrai signal nul et doit être explicitement rejeté comme solution.

### 12.2 Composants

- `value_component` : fonction monotone de `expected_value_low`
- `reliability_component` : calibration et maturité
- `quality_component` : qualité des données
- `freshness_component` : âge des cotes et features
- `liquidity_component` : profondeur ou limites connues
- `uncertainty_penalty` : largeur de l'intervalle
- `concentration_penalty` : redondance avec les candidats déjà retenus

### 12.2.1 Sémantique et domaine des composants

`ADR-ADV-005` doit, pour chaque composant listé en §12.2, définir explicitement :

- son domaine autorisé (bornes précises, pas seulement "entre 0 et 1") ;
- si la valeur `0` est une valeur métier valide, et dans quel cas ;
- ce que signifie précisément `0` pour ce composant (ex. "0 = calibration jamais mesurée" est différent de "0 = calibration mesurée et mauvaise") ;
- comment une donnée manquante est représentée — **une donnée manquante n'est jamais convertie silencieusement en `0`** ;
- si une donnée manquante entraîne un rejet du candidat, une dégradation explicite du composant, ou un fallback documenté.

Ce travail de définition doit être terminé avant le Lot 5 (Ranking Engine), pas découvert pendant son implémentation.

### 12.3 Profils

- `conservative_v1`
- `balanced_v1`
- `aggressive_v1`

Un profil est une configuration versionnée, pas une classe contenant de la logique arbitraire.

### 12.4 Tie-breakers

En cas d'égalité :

1. meilleure EV basse ;
2. meilleure calibration ;
3. meilleure fraîcheur ;
4. plus faible concentration ;
5. `candidate_id` lexical pour déterminisme.

### 12.5 Nature séquentielle du `concentration_penalty`

Le `concentration_penalty` dépend des candidats déjà retenus au moment de son évaluation (§12.2). Le classement qui en résulte est donc produit par une heuristique **séquentielle/gloutonne**, et non par une optimisation globale du portefeuille.

Cette propriété est acceptable pour la V1, mais :

- elle doit être documentée explicitement comme limitation connue (voir ADV-NFR-012) ;
- le résultat ne doit jamais être présenté, en interne ou à l'utilisateur, comme un optimum global.

### 12.6 Déterminisme et indépendance à l'ordre d'entrée

À entrées identiques (mêmes candidats, mêmes scores, même configuration), le classement final doit être strictement identique **quel que soit l'ordre dans lequel les candidats sont fournis en entrée**, sauf si l'ordre d'entrée fait volontairement partie du contrat — auquel cas cela doit être documenté explicitement et non laissé implicite.

Un test de type « mélanger l'ordre des candidats en entrée → même portefeuille, même ordre de sortie, mêmes allocations » doit exister avant que le Lot 5 soit considéré terminé.

---

## 13. Portfolio Optimizer

Le Portfolio Optimizer transforme les candidats classés en propositions de mise.

### 13.1 Responsabilités

- respecter la bankroll ;
- respecter le maximum de mise ;
- limiter la concentration ;
- appliquer le profil de risque ;
- respecter les plafonds bookmaker ;
- produire jusqu'à `max_portfolios` alternatives ;
- laisser une partie de la bankroll non allouée si nécessaire.

### 13.2 Interdictions

- forcer l'utilisation de toute la bankroll ;
- compenser un mauvais candidat par une mise plus faible ;
- créer un combiné pour atteindre artificiellement une cote cible ;
- supposer l'indépendance sans preuve ;
- dépasser `max_stake` ou `max_payout`.

### 13.3 Allocation initiale

La V1 utilise une approche déterministe et prudente :

```text
raw_fraction = fractional_kelly × reliability × data_quality
stake = min(
    bankroll × raw_fraction,
    candidate.max_stake,
    per_line_cap,
    remaining_budget
)
```

`fractional_kelly` est configurable par profil.

Le Kelly n'est jamais appliqué à une probabilité non `SUPPORTED`.

### 13.4 Contraintes

- exposition maximale par événement ;
- exposition maximale par participant ;
- exposition maximale par compétition ;
- nombre maximal de lignes ;
- nombre maximal de sélections ;
- limite par bookmaker ;
- minimum de mise technique ;
- granularité de mise.

---

## 14. Combo Builder

Le Combo Builder est un sous-système distinct.

Un combiné n'est pas une simple concaténation de candidats bien classés.

### 14.1 Conditions de création

Un combo n'est créé que si :

- `allow_combos=True` ;
- chaque leg est `ELIGIBLE` ;
- chaque marché est autorisé ;
- la combinaison est acceptée par le bookmaker ;
- la dépendance est connue ou raisonnablement bornée ;
- la probabilité combinée peut être estimée ;
- l'EV combinée reste positive selon la politique ;
- le nombre de legs ne dépasse pas `max_combo_legs`.

### 14.2 Classes de dépendance

```python
class DependencyStatus(Enum):
    INDEPENDENT_ENOUGH = "INDEPENDENT_ENOUGH"
    STRUCTURALLY_DEPENDENT = "STRUCTURALLY_DEPENDENT"
    STATISTICALLY_DEPENDENT = "STATISTICALLY_DEPENDENT"
    UNKNOWN = "UNKNOWN"
    INCOMPATIBLE = "INCOMPATIBLE"
```

### 14.3 Règles

- `INCOMPATIBLE` : combinaison interdite.
- `UNKNOWN` : refus en V1.
- `STRUCTURALLY_DEPENDENT` : nécessite une règle sportive explicite.
- `STATISTICALLY_DEPENDENT` : nécessite une estimation de probabilité jointe.
- `INDEPENDENT_ENOUGH` : multiplication autorisée avec marge de sécurité configurable.

### 14.4 Recherche

La V1 utilise :

1. top-K candidats après diversification ;
2. génération de combinaisons de 2 legs ;
3. pruning par contraintes ;
4. estimation ;
5. ranking des combos ;
6. extension à 3 legs uniquement si nécessaire.

Le système ne génère pas toutes les combinaisons possibles du catalogue.

---

## 15. Explicabilité

Chaque portefeuille doit répondre à quatre questions :

1. Pourquoi ces sélections ?
2. Pourquoi ces mises ?
3. Pourquoi cette structure simple/combinée ?
4. Pourquoi les autres candidats ont-ils été écartés ?

### 15.1 PortfolioExplanation

```python
@dataclass(frozen=True)
class PortfolioExplanation:
    summary: str
    selection_reasons: Mapping[str, tuple[str, ...]]
    allocation_reasons: Mapping[str, tuple[str, ...]]
    rejected_alternatives: tuple[str, ...]
    major_risks: tuple[str, ...]
    model_limitations: tuple[str, ...]
```

### 15.2 Règle

L'explication ne doit jamais être générée uniquement par un LLM.

Le contenu factuel vient de codes et métriques structurés.

Un LLM peut reformuler pour l'interface, sans modifier les chiffres ni les décisions.

---

## 16. Multi-sports et multi-ligues

Advisor ne possède aucun registre métier de sport.

Il ne lit que :

- `sport`
- `competition_id`
- `market_type`
- `participant_ids`
- métriques canoniques
- clés d'exposition

### 16.1 Ajouter un sport

Ajouter un sport consiste à :

1. étendre la gateway si nécessaire ;
2. créer les modules et modèles dans le Betting Engine ;
3. exposer les sorties canoniques ;
4. éventuellement ajouter des règles de dépendance pour les combinés.

Aucune modification du ranking, de l'allocation ou du contrat de recommandation n'est requise.

### 16.2 Ajouter une ligue

Une ligue est une nouvelle valeur de `competition_id`.

Elle ne nécessite aucun code dans Advisor, sauf politique explicite de risque ou de disponibilité.

---

## 17. Multi-bookmakers

Advisor peut recevoir plusieurs offres pour une même sélection.

### 17.1 Règles

- le candidat est lié à une offre bookmaker précise ;
- deux offres identiques chez deux bookmakers sont deux candidats techniques ;
- la déduplication sélectionne l'offre la plus pertinente pour un portefeuille ;
- un combo ne mélange pas plusieurs bookmakers ;
- les limites de mise sont propres à chaque offre ;
- la meilleure cote n'est pas automatiquement retenue si la fraîcheur ou la disponibilité est inférieure.

---

## 18. Interfaces

### 18.1 CLI

```bash
axon recommend \
  --bankroll 5 \
  --currency EUR \
  --target-odds-min 2.00 \
  --target-odds-max 3.00 \
  --risk balanced \
  --max-selections 2 \
  --allow-combos \
  --sports football tennis \
  --format human
```

### 18.2 Sorties CLI

- `human`
- `json`

### 18.3 Codes de sortie

| Code | Sens |
|---:|---|
| 0 | recommandation ou candidats de revue produits |
| 1 | échec global |
| 2 | scan réussi mais aucun événement évaluable |
| 3 | événements évalués mais aucune opportunité |
| 4 | demande invalide |

### 18.4 API

```http
POST /v1/recommendations
GET /v1/recommendations/{request_id}
GET /v1/audits/{audit_id}
GET /v1/strategies
```

L'API n'est pas nécessaire pour la première tranche CLI, mais les contrats du cœur ne doivent dépendre ni de Click, ni de FastAPI, ni d'un framework.

---

## 19. Persistance et audit

Chaque exécution conserve :

- la requête ;
- les versions de configuration ;
- les candidats générés ;
- les rejets et leurs raisons ;
- les scores ;
- les portefeuilles explorés ;
- la recommandation finale ;
- les cotes et timestamps ;
- les versions de modèles ;
- l'identifiant de l'exécution Betting Engine.

L'audit est append-only.

---

## 20. Configuration

```text
config/
  advisor/
    policies.yaml
    ranking_profiles.yaml
    risk_profiles.yaml
    portfolio_limits.yaml
    combo_rules.yaml
```

Toute configuration porte :

- `config_version`
- `effective_from`
- `checksum`

Une recommandation archive la version exacte utilisée.

---

## 21. Observabilité

Métriques minimales :

- nombre d'évaluations reçues ;
- nombre de candidats générés ;
- rejets par raison ;
- candidats par maturité ;
- latence par étape ;
- nombre de portfolios explorés ;
- nombre de combos rejetés ;
- concentration moyenne ;
- part de bankroll laissée non allouée ;
- fréquence de `NO_OPPORTUNITY`.

Logs structurés avec :

- `request_id`
- `audit_id`
- `candidate_id`
- `portfolio_id`
- `decision_time`

---

## 22. Exigences fonctionnelles

| # | Exigence | Priorité |
|---|---|---|
| ADV-FR-001 | Advisor consomme uniquement l'API publique du Betting Engine | Must |
| ADV-FR-002 | Advisor ne recalcule aucune probabilité sportive | Must |
| ADV-FR-003 | Une RecommendationRequest valide porte un decision_time explicite | Must |
| ADV-FR-004 | Tous les montants utilisent Decimal | Must |
| ADV-FR-005 | Toute évaluation valide produit au plus un CandidateBet par offre | Must |
| ADV-FR-006 | Un candidat EXPERIMENTAL est REVIEW_ONLY ou REJECTED, jamais ELIGIBLE | Must |
| ADV-FR-007 | Un candidat non SUPPORTED ne reçoit jamais de mise | Must |
| ADV-FR-008 | Le ranking est indépendant du sport et de la ligue | Must |
| ADV-FR-009 | Chaque score expose ses composants | Must |
| ADV-FR-010 | Les tie-breakers sont déterministes | Must |
| ADV-FR-011 | Le portfolio ne dépasse jamais la bankroll | Must |
| ADV-FR-012 | Le portfolio peut laisser de la bankroll non allouée | Must |
| ADV-FR-013 | Les limites max_stake et max_payout sont respectées | Must |
| ADV-FR-014 | L'exposition est limitée par événement et participant | Must |
| ADV-FR-015 | Une cote cible ne force jamais une mauvaise recommandation | Must |
| ADV-FR-016 | Le moteur peut produire NO_OPPORTUNITY | Must |
| ADV-FR-017 | Tout combo utilise un seul bookmaker | Must |
| ADV-FR-018 | Une dépendance UNKNOWN bloque le combo en V1 | Must |
| ADV-FR-019 | Les combos incompatibles sont rejetés avec raison | Must |
| ADV-FR-020 | Un combo ne contient jamais deux fois le même événement sans règle explicite | Must |
| ADV-FR-021 | Le système produit au plus max_portfolios propositions | Must |
| ADV-FR-022 | Chaque portefeuille possède une explication structurée | Must |
| ADV-FR-023 | Chaque rejet possède un code stable | Must |
| ADV-FR-024 | L'ajout d'un sport ne modifie pas le cœur d'Advisor | Must |
| ADV-FR-025 | L'ajout d'une ligue ne modifie pas le cœur d'Advisor | Must |
| ADV-FR-026 | L'ajout d'un bookmaker ne modifie pas le ranking | Must |
| ADV-FR-027 | Les offres multi-bookmakers sont comparées sans perte de traçabilité | Should |
| ADV-FR-028 | Le CLI expose human et json | Must |
| ADV-FR-029 | Les codes de sortie suivent §18.3 | Must |
| ADV-FR-030 | Une exécution archive requête, configuration et résultat | Must |
| ADV-FR-031 | L'audit permet de reconstituer chaque décision | Must |
| ADV-FR-032 | Les stratégies sont versionnées | Must |
| ADV-FR-033 | Les profils de risque sont configurables | Must |
| ADV-FR-034 | Le moteur peut retourner des review_candidates | Must |
| ADV-FR-035 | Les modèles DEPRECATED sont toujours rejetés | Must |
| ADV-FR-036 | Un événement commencé est rejeté en pré-match | Must |
| ADV-FR-037 | La fraîcheur des cotes participe à l'éligibilité | Must |
| ADV-FR-038 | Une offre boostée suit la politique du marché sous-jacent | Must |
| ADV-FR-039 | Une explication LLM ne peut modifier aucune métrique | Must |
| ADV-FR-040 | Toute incompatibilité de schéma échoue explicitement | Must |
| ADV-FR-041 | Une donnée manquante pour un composant de ranking n'est jamais convertie silencieusement en 0 ; son traitement (rejet, dégradation, fallback) est explicite et documenté | Must |
| ADV-FR-042 | Le classement produit par le Ranking Engine est indépendant de l'ordre d'entrée des candidats, sauf contrat documenté explicitement en sens contraire | Must |

---

## 23. Exigences non fonctionnelles

- **ADV-NFR-001 · Déterminisme** — mêmes entrées, mêmes versions, même sortie.
- **ADV-NFR-002 · Auditabilité** — toute décision est reconstructible.
- **ADV-NFR-003 · Reproductibilité** — un replay historique produit le même résultat.
- **ADV-NFR-004 · Isolation** — l'échec d'un candidat n'annule pas les autres.
- **ADV-NFR-005 · Versioning** — contrats, stratégies et configurations sont versionnés.
- **ADV-NFR-006 · Observabilité** — chaque étape expose métriques et latence.
- **ADV-NFR-007 · Performance** — le ranking et l'optimisation V1 restent compatibles avec un catalogue courant sur une seule machine.
- **ADV-NFR-008 · Séparation des responsabilités** — aucune logique sportive dans Advisor.
- **ADV-NFR-009 · Testabilité** — tous les tests unitaires sont hermétiques.
- **ADV-NFR-010 · Sécurité numérique** — aucune conversion implicite float/Decimal dans les montants.
- **ADV-NFR-011 · Compatibilité** — changement de contrat source géré par l'adaptateur.
- **ADV-NFR-012 · Explicabilité** — aucun score opaque sans décomposition ; la nature séquentielle/gloutonne du `concentration_penalty` (§12.5) est documentée comme limitation connue, jamais présentée comme un optimum global.
- **ADV-NFR-013 · Tolérance partielle** — erreurs locales collectées et exposées.
- **ADV-NFR-014 · Configuration explicite** — aucun seuil métier caché dans le code.
- **ADV-NFR-015 · Idempotence** — le même request_id ne crée pas plusieurs audits divergents.

---

## 24. Rollout

### Vague 0 — Garde-fous

- lire l'architecture existante ;
- geler les tests ;
- stopper avant chaque commit ;
- ne pas renommer les contrats existants sans ADR ;
- produire d'abord les tests de contrat.

### Vague 1 — Tranche verticale simple

- adaptateur Betting Engine ;
- contrats Advisor ;
- Candidate Generator ;
- Eligibility Policy ;
- Ranking Engine ;
- recommandation d'un pari simple ;
- CLI `axon recommend`.

Objectif utilisateur :

```text
J'ai 5 €, donne-moi les meilleurs paris simples aujourd'hui.
```

### Vague 2 — Bankroll et plusieurs simples

- profils de risque ;
- allocation ;
- exposition ;
- plusieurs lignes ;
- alternatives ;
- audit complet.

### Vague 3 — Combinés

- compatibilité ;
- dépendance ;
- construction à 2 legs ;
- pricing ;
- combo ranking ;
- refus explicites.

### Vague 4 — Multi-bookmakers

- offres concurrentes ;
- meilleure offre exploitable ;
- limites ;
- déduplication ;
- portefeuilles par bookmaker.

### Vague 5 — API et interface

- API REST ;
- serializers publics ;
- historique ;
- interface utilisateur.

---

## 25. Critères de succès

- La commande avec `--bankroll 5 --target-odds-min 2 --target-odds-max 3` produit une recommandation, des candidats de revue ou `NO_OPPORTUNITY`.
- Aucun modèle expérimental ne reçoit une mise.
- Ajouter une ligue ne modifie aucun fichier sous `ranking/`, `portfolio/` ou `recommendation/`.
- Ajouter un sport ne nécessite que les changements dans Gateway/Betting Engine et éventuellement les règles de dépendance combo.
- Chaque résultat est reproductible avec son audit.
- Une cote cible irréaliste n'entraîne pas une recommandation forcée.
- Les sélections corrélées ne sont pas présentées comme diversification.
- Les plafonds bookmaker sont respectés.
- Le système peut proposer un simple plutôt qu'un combo même lorsque l'utilisateur autorise les combos.
- Le système peut ne pas utiliser toute la bankroll.
- Le CLI JSON est stable et versionné.
- Tous les tests historiques existants restent verts.

---

## 26. Risques

| Risque | Impact | Mitigation |
|---|---|---|
| Confondre probabilité et recommandation | mélange des responsabilités | adaptateur strict + interdiction de recalcul |
| Optimiser pour la cote cible | mauvais paris artificiels | cible comme préférence, non comme obligation |
| Multiplier des probabilités dépendantes | EV combo fausse | dependency status + refus UNKNOWN |
| Sur-allocation sur modèles fragiles | pertes concentrées | SUPPORTED_ONLY pour mises |
| Scores arbitraires | classement opaque | composants versionnés et auditables |
| Explosion combinatoire | latence | top-K + pruning |
| Faux sentiment de diversification | exposition cachée | exposure keys et contraintes |
| Utiliser toute la bankroll | risque inutile | unallocated_bankroll autorisé |
| Cotes périmées | décisions incohérentes | seuil de fraîcheur |
| Différences de schéma | corruption silencieuse | version check explicite |

---

## 27. Décisions ouvertes

1. Formule exacte des profils `conservative_v1`, `balanced_v1`, `aggressive_v1`.
2. Seuil minimal d'EV basse par profil.
3. Fraction de Kelly initiale.
4. Limites d'exposition par événement.
5. Méthode V1 d'estimation de dépendance inter-événements.
6. Stockage de l'audit : SQLite, fichiers append-only ou base existante Axon.
7. Intégration exacte dans l'orchestrateur LangGraph.
8. Format public versionné du JSON CLI/API.
9. Traitement des paris avec minimum de mise bookmaker.
10. Politique d'arrondi des montants.
