# axon-advisor — État des lieux (Lot 0, Reconnaissance)

**Statut :** reconnaissance uniquement — aucun code métier produit.
**Source de vérité produit :** `docs/new-docs/PRD-axon-advisor.md` (+ IMPLEMENTATION, ADR-BACKLOG).
**Dépendance amont :** `axon-betting-engine` (à `src/agents/quant/betting_engine/`), consommé via son API publique, **jamais modifié depuis Advisor** (règle de dépendance PRD §1.2).

Ce document répond aux exigences du Lot 0 : arborescence, contrats réels, points de branchement, écarts avec le PRD, fichiers à créer/modifier, ordre des commits, risques, questions bloquantes.

---

## 1. Arborescence actuelle pertinente

```
src/agents/quant/
  betting_engine/                 ← DÉPENDANCE (ne pas modifier depuis Advisor)
    live_evaluation.py            evaluate_live_event -> LiveEvaluationResult
    cli.py                        run_live (batch), render_human/json, main
    core/
      market_model.py             DataReadiness, MarketPrediction, PredictionExplanation, UncertaintyStatus, MarketModel
      odds.py                     OddsSnapshot
      canonical_event.py          CanonicalEvent, CanonicalParticipant, CanonicalMarket
      feature_set.py, errors.py
    value_engine/
      decision.py                 BettingDecision, EvaluationStatus, evaluate_selection
      margin_removal.py, expected_value.py, market_coherence.py
    bookmakers/                   WinamaxConnector, bookmaker_registry, market_canonicalizer, participant_role_resolver, winamax/{catalogue,competition_mapping,connector}
    sports/football/              feature_engineering, market_models/one_x_two, manifest ; sports/registry.py (SPORT_MODULES)
    calibration/                  walk_forward, metrics, experiment_registry, point_in_time_gateway  (NON consommé par Advisor)
  gateway/                        axon-sports-data-gateway (ne pas modifier)
configs/                          base.yaml + config.py + downloads.py   (⚠ pluriel ; le PRD écrit `config/advisor/`)
tests/                            238 tests + `test/` (16 échecs pré-existants hors périmètre)
docs/architecture/, docs/new-docs/ (PRD advisor)
```

**Advisor n'existe pas encore.** Aucun dossier `advisor/`.

---

## 2. Contrats source réels (sortie publique du Betting Engine)

Ce que le Betting Engine produit réellement aujourd'hui (types exacts, **tous en `float`**, pas `Decimal`) :

### `LiveEvaluationResult` (`live_evaluation.py`) — sortie par ÉVÉNEMENT
`status` (LiveEvaluationStatus), `reason`, `decision_time`, `bookmaker_event_id`, `canonical_event: CanonicalEvent|None`, `feature_set`, `predictions: dict[str, MarketPrediction]`, `decisions: tuple[BettingDecision,...]`, `warnings: list[str]`, `error_context: dict`. Propriétés : `is_evaluated`, **`has_actionable_evaluation`** (= une vraie prédiction existe).
→ Les `decisions`/`predictions` ne sont peuplées **que** si `status == EVALUATED`. Un refus (COMPETITION_NOT_COVERED, EVENT_NOT_RESOLVED, INSUFFICIENT_FEATURES…) ne porte **aucun** candidat.

### `BettingDecision` (`value_engine/decision.py`)
`selection`, `bookmaker`, `bookmaker_odds: float`, `market_type`, `model_probability: float`, `probability_interval: (float,float)`, `uncertainty_status: str`, `data_quality: float`, `calibration_status: str`, `model_reliability: float|None`, `implied_probability_raw: float|None`, `no_vig_probability: float|None`, `edge: float|None`, `expected_value: float|None`, `evaluation_status`, `decision: str`, `reasons: list[str]`.

### `MarketPrediction` (`core/market_model.py`)
`sport`, `market_type`, `selection`, `fair_probability: float`, `probability_low: float`, `probability_high: float`, `uncertainty_status`, `model_version`, `data_quality: float`, `calibration_status: DataReadiness`, `point_in_time`, `explanation: PredictionExplanation`.

### Autres
- `CanonicalEvent` : `event_id`, `sport`, `competition_id`, `participants: tuple[CanonicalParticipant]` (`canonical_id`, `role`), `scheduled_at`, `context`.
- `OddsSnapshot` : `event_id`, `market_type`, `selection`, `decimal_odds: float`, `observed_at`, `bookmaker`, `is_boosted`, `boost_reference_odds`, `max_stake`, `max_payout`.
- `DataReadiness` : `SUPPORTED | EXPERIMENTAL | INSUFFICIENT_DATA | UNSUPPORTED` — **pas de `DEPRECATED`**.
- `market_id` : produit **uniquement** par `market_canonicalizer.build_market_id(bookmaker, canonical_event_id, market_type)` (déterministe, importable) — **jamais propagé** dans `BettingDecision`/`LiveEvaluationResult`.
- Batch : `betting_engine/cli.run_live(connector, ...) -> LiveRun(decision_time, results: list[(RawBookmakerEvent, LiveEvaluationResult)])`. C'est le seul « batch pour un decision_time » existant, mais il vit dans `cli.py` (couche adaptateur), pas dans une API de domaine.

---

## 3. Points de branchement (frontière Advisor ↔ Betting Engine)

- **Entrée principale d'Advisor = les `BettingDecision` + `MarketPrediction` des événements `EVALUATED`**, pour un `decision_time` donné, obtenues via `run_live` (ou une future fonction de domaine batch — cf. Q4).
- `betting_engine_adapter.py` (Advisor, Lot 2) est **l'unique** frontière : il aplatit `LiveRun → list[CandidateSource]` puis vers `CandidateBet`, convertit `float → Decimal`, propage identité/warnings/traçabilité, vérifie la version de schéma.
- `decision_time` : déjà capturé une seule fois par `run_live` (après le scan) et présent sur `LiveEvaluationResult.decision_time` → Advisor le réutilise, ne le recapture pas.
- Maturité : `MarketPrediction.calibration_status` (`DataReadiness`) → `model_maturity` d'Advisor. Aujourd'hui **toujours `EXPERIMENTAL`** (BE-FR-011) → en `MaturityPolicy` par défaut, tout candidat est `REVIEW_ONLY` ou `REJECTED`, **jamais de mise** — cohérent avec ADV-FR-006/007.
- `has_actionable_evaluation` distingue déjà « vraie prédiction » de « refus », ce qui alimente `NO_EVALUABLE_EVENTS` vs `NO_OPPORTUNITY`.

---

## 4. Écarts avec le PRD (le cœur du Lot 0)

### 4.1 Champs `CandidateBet` (PRD §8.5) vs source réelle

| Champ CandidateBet | Source réelle | Écart |
|---|---|---|
| event_id, sport, competition_id, scheduled_at | `CanonicalEvent` | OK |
| bookmaker, market_type, selection | `BettingDecision`/`OddsSnapshot` | OK |
| **market_id** | `build_market_id(...)` (canonicalizer) | **non propagé** ; l'adaptateur doit le **reconstruire** (fonction importable, déterministe) — cf. Q5 |
| bookmaker_odds | `BettingDecision.bookmaker_odds` (float) | **float → Decimal** (adaptateur) |
| fair_probability, probability_low, probability_high | `MarketPrediction` | OK ; mais `NOT_ESTIMATED` ⇒ **low=high=fair** aujourd'hui |
| fair_odds | dérivé `1/fair_probability` | dérivé autorisé (générateur) |
| implied_probability | `BettingDecision.implied_probability_raw` | OK (renommage) |
| expected_value_mean, edge_mean | `expected_value`, `edge` | OK (renommage) |
| **expected_value_low, edge_low** | — | **non calculés séparément** ; `low==mean` tant que l'incertitude est `NOT_ESTIMATED` (BE-FR-012 différé). L'adaptateur les dérive de `probability_low` (= fair actuellement). Le `value_component` du ranking porte donc sur le **point**, pas sur une borne basse prudente. À documenter. |
| model_version, model_maturity | `model_version`, `calibration_status` | OK (voir DEPRECATED §4.2) |
| **calibration_score** | `model_reliability` = **None** | **toujours None** (calibration non branchée). `Decimal|None` accepté → None, jamais inventé. |
| data_quality | `data_quality` | OK (float → Decimal) |
| **freshness_score** | **rien** | **ÉCART MAJEUR** : le gateway masque la fraîcheur (API publique) ; l'orchestrateur n'émet qu'un warning `freshness_unavailable`. Or `CandidateBet.freshness_score` est **non-optionnel**. On ne peut pas inventer une valeur (ADV-FR-041). → **Q1 (bloquante)**. Lié au todo gateway-side existant. |
| **liquidity_score** | **rien** | non produit ; `Decimal|None` → None. |
| max_stake, max_payout | `OddsSnapshot` | OK (Vague 2 : None actuellement) |
| is_boosted | `OddsSnapshot.is_boosted` | une offre boostée est **refusée** en amont (`value_engine` NOT_EVALUATED) → **jamais** dans un candidat EVALUATED en V1. ADV-FR-038 sans objet jusqu'à Vague 2. |
| participant_ids | `CanonicalEvent.participants[*].canonical_id` | OK |
| exposure_keys | **calculées par Advisor** (ADR-ADV-008) | dérivé autorisé (générateur) |
| warnings | `BettingDecision.reasons` + `explanation.warnings` + `LiveEvaluationResult.warnings` | à **agréger** ; ne rien supprimer (adaptateur) |
| **explanation_ref** | `PredictionExplanation` **inline** (pas de ref/id) | Advisor stocke/pointe l'explication ; pas de référence stable côté source |
| **source_decision_id** | **rien** (`BettingDecision` n'a pas d'id) | à **synthétiser** (event_id+market_id+selection+decision_time) — cf. Q5 |

### 4.2 Écarts structurels

1. **`float` partout côté source** ; Advisor impose `Decimal` (ADV-FR-004, ADR-ADV-002). L'adaptateur est **la** frontière de conversion — aucune conversion implicite ailleurs (ADV-NFR-010).
2. **`DataReadiness` n'a pas `DEPRECATED`** ; la table de maturité PRD §11.2 l'attend (toujours REJECTED). Advisor gère `DEPRECATED` défensivement dans son mapping ; la source ne l'émet jamais.
3. **Pas d'API publique unique** : `betting_engine/__init__.py` ne réexporte rien. L'adaptateur importe des modules précis (`live_evaluation`, `core.market_model`, `value_engine.decision`, `market_canonicalizer.build_market_id`). ADR-ADV-001 fige cette frontière.
4. **Source batch = `cli.run_live`** (dans `cli.py`), pas une fonction de domaine. Q4.
5. **`configs/` (pluriel)** existe ; le PRD écrit `config/advisor/`. Décision de convention (Q3).
6. **Pas d'entry-point `axon`** (ni pyproject scripts) ; le CLI existant est `python -m …betting_engine.cli` (argparse, sans framework — conforme PRD §18.4). Advisor suivra le même pattern (`interfaces/cli.py`, `python -m …advisor.interfaces.cli`).
7. **Incertitude `NOT_ESTIMATED`** partout (modèle EXPERIMENTAL) : `probability_low==high==fair`. Donc `uncertainty_penalty`, `expected_value_low`, `edge_low` sont dégénérés en V1. À documenter, pas à masquer.

---

## 5. Emplacement proposé + fichiers à créer

**Racine Advisor proposée : `src/agents/quant/advisor/`** (frère de `betting_engine/`, domaine quant, dépend de son API publique). Cohérent avec l'existant et la règle de dépendance.

Structure (créée **au fil des lots**, pas d'avance — cf. règle « pas de dossiers vides ») :
```
advisor/
  domain/            requests, candidates, portfolios, recommendations, enums, money   (Lot 1)
  input_adapter/     betting_engine_adapter, schema, errors                            (Lot 2)
  candidate_generation/ generator, normalization, exposure_keys                        (Lot 3)
  policy/            eligibility, reason_codes, maturity, filters                       (Lot 4)
  ranking/           scorer, components, profiles, sort, explanation                    (Lot 5)
  recommendation/    engine, simple, explanation, audit                                 (Lot 6)
  interfaces/        cli, serializers                                                    (Lot 7)
configs/advisor/     ranking_profiles.yaml, risk_profiles.yaml, policies.yaml…          (au besoin)
tests/               test_advisor_*.py par lot
docs/architecture/   ADR-ADV-00x au fil des décisions (ADR-ADV-005 AVANT Lot 5)
```

**Aucune modification du Betting Engine** n'est prévue dans le périmètre Advisor. Si un écart l'exige (ex. propager `market_id`, exposer `freshness_score`), c'est un **PRD/commit séparé du Betting Engine ou de la Gateway** (cf. §4.1, Q1/Q5), jamais un changement glissé dans un lot Advisor.

---

## 6. Ordre des commits (Vague 1, un lot = un commit, arrêt avant chaque)

0. **Lot 0** (ce document) — reconnaissance, aucun code.
1. **Lot 1** — contrats de domaine (`RecommendationRequest`, `OddsRange`, `CandidateBet`, `CandidateEvaluation`, `BetLeg`, `PortfolioLine`, `RecommendationPortfolio`, `RecommendationResponse`) + invariants + `Money`/Decimal + JSON round-trip. `feat(advisor): add canonical advisor domain contracts`.
2. **Lot 2** — `betting_engine_adapter` + schema + errors (float→Decimal, version check, propagation). `feat(advisor): add betting engine input adapter`.
3. **Lot 3** — Candidate Generator (candidate_id stable, fair_odds/edge, exposure_keys). `feat(advisor): generate canonical betting candidates`.
4. **Lot 4** — Eligibility Policy (maturité, filtres, seuils, codes de rejet). `feat(advisor): add candidate eligibility policies`.
5. **ADR-ADV-005 rempli** (prérequis), puis **Lot 5** — Ranking Engine (composants, profils, tie-breakers, indépendance à l'ordre). `feat(advisor): rank eligible candidates`.
6. **Lot 6** — Recommandation simple (`engine`, `simple`, `explanation`, `audit`). `feat(advisor): produce first simple recommendation`.
7. **Lot 7** — CLI `axon recommend` (human/json, codes 0/1/2/3/4). `feat(cli): add axon recommend command`.

Vagues 2–5 (portfolio, combos, audit/replay, API/UI) hors de cette première tranche.

---

## 7. Risques (migration / conception)

| Risque | Détail | Mitigation |
|---|---|---|
| **Fraîcheur absente** | `freshness_score` non exposé ⇒ `CandidateBet` incomplet / éligibilité fraîcheur (ADV-FR-037) sans signal | Q1 : rendre le champ optionnel côté Advisor **avec traitement explicite du manquant** (ADV-FR-041) OU bloquer sur le todo gateway-side. Ne jamais inventer. |
| **EV basse dégénérée** | incertitude `NOT_ESTIMATED` ⇒ `expected_value_low == mean` ; le ranking « prudent » ne l'est pas encore | documenter comme limitation V1 ; le `value_component` reste honnête (point), à raffiner quand l'incertitude sera calibrée |
| **Conversion float/Decimal** | double représentation, arrondis | frontière unique dans l'adaptateur ; ADR-ADV-002 (arrondi, granularité) ; tests « aucun float monétaire résiduel » |
| **market_id / source_decision_id** | absents de la sortie source | reconstruire via `build_market_id` (déterministe) + synthétiser un id stable ; documenter dans ADR-ADV-001/003 |
| **Source batch dans `cli.py`** | dépendance à une couche adaptateur du Betting Engine | Q4 : consommer `run_live` tel quel OU demander une fonction de domaine batch (commit Betting Engine séparé) |
| **DataReadiness ≠ table PRD** | pas de `DEPRECATED` | mapping défensif ; ne pas ajouter `DEPRECATED` au Betting Engine sans son propre ADR |
| **Ranking ADR non fait avant Lot 5** | floor arbitraire, sémantique du `0` bâclée | ADR-ADV-005 **obligatoire avant Lot 5** (domaine/`0`/manquant par composant), interdiction de floor générique |
| **Ordre d'entrée** | classement dépendant de l'ordre des candidats | test `shuffle → même sortie` exigé avant fin Lot 5 (ADV-FR-042) |
| **Tests existants** | 238 tests à préserver | Advisor est additif (nouveau package) ; rejeu systématique |

---

## 8. Questions strictement bloquantes (à trancher avant de coder)

1. **[BLOQUANTE] `freshness_score`** — la source ne l'expose pas ; `CandidateBet.freshness_score` est non-optionnel dans le PRD. Deux voies :
   - (a) **Assouplir le contrat Advisor** : `freshness_score: Decimal | None`, avec un traitement **explicite** du manquant dans policy/ranking (ADV-FR-041) — recommandé pour ne pas bloquer la Vague 1 (modèle EXPERIMENTAL ⇒ aucune mise de toute façon) ;
   - (b) **Bloquer** jusqu'à ce que le todo gateway-side (exposer la fraîcheur) soit livré via son propre commit.
   Quelle voie ?
2. **Racine Advisor** = `src/agents/quant/advisor/` — confirmes-tu ?
3. **Convention config** : `configs/advisor/` (aligné sur l'existant pluriel) **ou** `config/advisor/` (texte du PRD) ?
4. **Source batch** : l'adaptateur consomme `betting_engine.cli.run_live` tel quel, **ou** on introduit d'abord une fonction de domaine batch côté Betting Engine (commit séparé, hors périmètre Advisor) ?
5. **`market_id` / `source_decision_id`** : l'adaptateur les **reconstruit/synthétise** (via `build_market_id` + hash déterministe des champs ADR-ADV-003) — OK, ou tu préfères une propagation depuis le Betting Engine (commit séparé) ?

---

## 9. Ce que ce lot NE fait pas

Aucun code métier, aucun contrat créé, aucune modification du Betting Engine ni de la Gateway, aucun test ajouté. Les 238 tests existants sont intacts.

---

## 10. Décisions actées (Q1–Q5, validées) et divergences tracées

**Q1 — `freshness_score` : option (a) avec garde-fous.**
`freshness_score: Decimal | None`. Raison distincte `FRESHNESS_UNKNOWN` (non mesurable) ≠ `STALE_ODDS` (mesurée insuffisante). Politique : `SUPPORTED_ONLY`+inconnu → `REJECTED` ; `INCLUDE_EXPERIMENTAL_FOR_REVIEW`+inconnu → `REVIEW_ONLY` ; warning `freshness_unavailable` propagé jusqu'à la sortie. **Divergence tracée** dans `PRD-axon-advisor.md §8.5 + §8.5.1 (nouveau) + §11.4` (source de vérité mise en cohérence). **Dette de frontière** Gateway/BE (exposer la fraîcheur) — commit séparé ultérieur, non bloquant v1.

**Q2 — emplacement : `src/agents/quant/advisor/`** (tranché sur l'arborescence réelle). Preuve : `betting_engine` est du pur domaine (0 dépendance LangGraph/agent), il vit déjà sous `agents/quant/`, et il n'existe aucun autre foyer de domaine. **Garde-fou** : cœur Advisor sans aucun import framework (langgraph/langchain/orchestrator/CLI) ; intégration Axon = glue séparée (analogue `tools.py`). **Test « cœur pur domaine » exigé.**

**Q3 — config : `configs/advisor/`** (convention réelle du dépôt, pluriel) plutôt que `config/advisor/` du PRD. Divergence documentée ici.

**Q4 — source batch : PAS de dépendance à `cli.py`.**
Un **petit commit Betting Engine séparé** (avant le Lot 2) introduit une fonction de domaine batch (`list_evaluations` / `evaluate_batch`), consommée à la fois par le CLI existant et par l'adaptateur Advisor. Sens de dépendance : `CLI → domaine ← Advisor`, jamais `Advisor → CLI`. Unité de commit distincte, minimale, revue à part (PRD §1.2).

**Q5 — `market_id` vs `source_decision_id` : stratégies différentes.**
- `market_id` : reconstruction **temporaire** via le builder canonique `build_market_id` uniquement (aucun algorithme d'ID parallèle dans Advisor) + test « reconstruction == identifiant canonique » ; shim documenté comme temporaire.
- `source_decision_id` : **NON synthétisé** (donnée de provenance/audit). Ordre : (1) propager un id source réellement existant ; (2) sinon l'ajouter dans le petit commit Betting Engine du Q4 ; (3) sinon champ **temporairement optionnel** + dette documentée. Inspection des ids réels à faire au Lot 2. **Aucun id de provenance inventé.**

### 10.1 Ordre d'implémentation révisé

```
Lot 1 (contrats Advisor)
→ petit commit Betting Engine (frontière batch Q4 + provenance Q5 si dispo) — unité séparée
→ Lot 2 (adaptateur) → Lot 3 (générateur) → Lot 4 (éligibilité)
→ ADR-ADV-005 → Lot 5 (ranking) → Lot 6 (reco simple) → Lot 7 (CLI)
```
Un lot = une unité de commit distincte, arrêt avant chaque commit.

### 10.2 Divergences PRD ↔ dépôt, tracées

| Divergence | Décision | Trace |
|---|---|---|
| `freshness_score` non-optionnel vs non exposé | `Decimal \| None` + `FRESHNESS_UNKNOWN` | PRD §8.5.1 (mis à jour) |
| `config/advisor/` vs `configs/` réel | `configs/advisor/` | ce doc §10 (Q3) |
| `market_id`/`source_decision_id` absents de la sortie | shim `build_market_id` + provenance non inventée | ce doc §10 (Q5), ADR-ADV-001/003 à venir |
| `DataReadiness` sans `DEPRECATED` | mapping défensif, source ne l'émet jamais | ce doc §4.2 |
| EV basse dégénérée (`NOT_ESTIMATED`) | `low==mean` documenté comme limite v1 | ce doc §4.1 |

### 10.3 Résolution de l'unité BE frontière (Q4/Q5)

Réalisée après le Lot 1, en unité de commit distincte.

**Q4 — frontière batch : `evaluate_live_batch` (module `betting_engine/live_batch.py`).**
Inspection : `run_live` (ex-`cli.py`) était **déjà du domaine pur** — aucune trace CLI (pas d'`argparse`, pas de rendu, pas de code de sortie) ; ses seuls défauts étaient sa *localisation* et son *nom*. Extraction du plus petit contrat public (`evaluate_live_batch` → `LiveEvaluationBatch`) ; le CLI ne garde QUE l'I/O (`main`, `render_human`, `build_json_record`, `exit_code_for`). Dépendances : `CLI → live_batch ← adaptateur Advisor` ; jamais `Advisor → cli`. Verrous : test AST `live_batch` sans dépendance d'interface, + `betting_engine.cli` ajouté à la liste interdite du test de pureté Advisor.

**Q5 — provenance : `source_decision_id = None` (option 3), dette documentée.**
Inventaire des identifiants réellement disponibles dans la chaîne : `bookmaker_event_id`, `decision_time`, `canonical_event.event_id` (sur `LiveEvaluationResult`) ; **`BettingDecision` et `MarketPrediction` n'en portent aucun** ; **aucun `run_id`/`evaluation_id`/`decision_id`/`snapshot_id` nulle part**. Le Betting Engine est un **évaluateur sans état** : il calcule et retourne, ne persiste ni run ni décision. Conclusion :
- (1) aucun id atomique existant à propager ;
- (2) en introduire un ici (uuid éphémère) ne tracerait **rien** — ce serait exactement l'« id inventé pour remplir le champ » proscrit ; une identité *persistée* suppose une couche d'audit BE = prématuré pour une frontière minimale ;
- (3) → `source_decision_id` reste **`None`** côté Advisor. **Dette** : quand le BE gagnera une frontière de persistance/audit attribuant des ids de décision stables, le champ pourra référencer un id réel et traçable.

**Divergence confirmée (hors périmètre de cette unité)** : `market_id` reste **non propagé** sur `LiveEvaluationResult` (`evaluate_live_event` le calcule en local mais ne le stocke pas). L'adaptateur Advisor (Lot 2) le **reconstruira** via `build_market_id(bookmaker, canonical_event.event_id, market_type)` — décision Q5 inchangée, non traitée ici pour rester minimal.

Prochaine étape : **Lot 2** (adaptateur `betting_engine_adapter` : `LiveEvaluationResult` → `CandidateBet`, `market_id` reconstruit, `source_decision_id=None`) — arrêt avant commit, avec les 3 contrôles.
