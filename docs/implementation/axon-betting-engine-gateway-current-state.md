# axon-betting-engine + sports-data-gateway — État des lieux (fondation statistique)

**Statut :** fondation statistique BE/Gateway rendue honnête et opérationnelle.
Aucun modèle promu `SUPPORTED` (verdict mécanique = `EXPERIMENTAL`). Infrastructure
de promotion complète : une promotion future est une **conséquence mécanique** de
nouvelles données, pas un nouveau chantier.
**Sources de vérité :** `docs/architecture/PRD-axon-betting-engine.md`,
`PRD-axon-sports-data-gateway-v2.md`, `ADR.md` (git history) — BE-FR-011/012/015/016,
GW-NFR-003, ADR-004/011/014.

---

## 1. État initial trouvé (avant ce chantier)

| Dette | État trouvé | Preuve |
|---|---|---|
| `SUPPORTED` | Littéral codé en dur `EXPERIMENTAL` dans `manifest.py` + plafond `_CEILING` dans le modèle | `GLOBAL_MODEL_STATUS = {"MATCH_WINNER": EXPERIMENTAL}` |
| walk-forward | **Déjà présent et correct** : expanding point-in-time, paramètres figés, baselines, registre d'expériences | `calibration/walk_forward.py`, `test_walk_forward.py::test_first_real_fl1_run` |
| calibration | **Mesure de bins présente**, mais aucune ECE ni calibrateur | `metrics.calibration_bin_counts` seul |
| CLV | **Absente** — aucune structure, aucun odds_history, aucune donnée de cote historique | 0 occurrence `closing`/`decision_odds`/`clv` |
| freshness | **Calcul présent au Gateway** (décroissance exponentielle), mais demi-vies codées en dur + tolérance staleness live « PLACEHOLDER DEVINÉ » | `core/quality.py`, `live_evaluation.py` |
| provenance | **Déjà riche** : 5 horodatages point-in-time, `provider_entity_id`, `content_hash`, `experiment_registry` | `canonical/envelope.py`, `core/point_in_time_store.py` |
| Winamax | Connecteur pur (`parse_catalog`), aucune capture réelle, fixture de test synthétique | `bookmakers/winamax/connector.py` |

Aucune anomalie de `SUPPORTED` fabriqué n'a été trouvée : le socle était déjà
honnête (plafonné `EXPERIMENTAL`), mais **déclaratif**. Ce chantier le rend **dérivé**.

## 2. Données disponibles / manquantes

**Disponible (réel) :** Ligue 1 2025-26, `tests/fixtures/fl1_2025_matches.json`
(fingerprint `sha256:2dc0a2…`), **305 matchs FINISHED**, 305/305 équipes résolues,
2025-08-15 → 2026-05-17. Suffisant pour un walk-forward point-in-time sur l'issue 1X2.

**Manquant :** (a) **cotes historiques** (ouverture/clôture) → CLV non mesurable ;
(b) **2ᵉ saison / 2ᵉ ligue** → pas de stabilité inter-saison, échantillon d'une
seule saison ; (c) **fraîcheur mesurée au point de décision live** (le Gateway la
calcule sur enveloppe, non propagée au modèle live).

## 3. Protocole walk-forward

Expanding, **par événement** (granularité maximale) : à chaque match, cutoff =
kickoff, le `PointInTimeGateway` ne voit que les matchs `kickoff < cutoff` (STRICT).
Paramètres du modèle **figés** (rejeu, pas d'entraînement). Résultats **hors
échantillon uniquement**. Exposé : `n_predictions` (296/305, 9 exclus J1),
`n_folds` temporels (10 mois), Brier/log-loss, ECE, baselines, coverage, data_quality.

## 4. Règles anti-leakage (invariants + tests)

| Invariant | Empêché par | Test |
|---|---|---|
| Aucune donnée `kickoff ≥ cutoff` dans les features | filtre STRICT `< cutoff` | `test_point_in_time_gateway.py`, `test_anti_leakage.py` |
| Calibrateur ajusté sur le passé autorisé seulement | paires `kickoff < cutoff` uniquement | `test_anti_leakage::test_flipping_a_future_outcome…` |
| Donnée future très informative (20-0) jamais utilisée | gate structurel | `test_anti_leakage::test_future_informative_match…` |
| Clôture jamais utilisée pour une prédiction | CLV séparée du chemin de prédiction ; `decision < closing` strict | `test_clv_odds_history` |

## 5. Méthode de calibration

**Histogram binning mutualisé sur les 3 issues** (`calibration/calibrator.py`) — le
calibrateur le plus simple et auditable (PRD §7.1 cite isotonic/Platt ; on reste
délibérément plus simple, données rares). Ajusté **point-in-time** (paires
strictement antérieures), identité sous `min_samples`, bin vide → proba brute
(jamais 0). **Mesure** : ECE mutualisée (`expected_calibration_error`), distincte de
l'accuracy. Résultat réel : ECE brute **0.028** (déjà bien calibré) ; la
re-calibration histogram ne l'améliore pas sur cette taille (ECE 0.032) — **constat
honnête**, le modèle est évalué sur ses probabilités brutes. La sélection brut/calibré
suit une **règle explicite** (`select_probability_source` : n'adopte le calibré que si
l'ECE est strictement meilleure) — jamais `calibrated == better` par défaut ; sur FL1,
recommandation = `raw`.

## 6. Baseline

Deux baselines **sans fuite**, sur les mêmes folds : uniforme (1/3) et fréquences
point-in-time (issues des matchs antérieurs). Critère de promotion = **benchmark
relatif** (`must_beat_baselines`), jamais un seuil de Brier absolu arbitraire.
Réel : Brier modèle **0.621** < prior-freq **0.648** < uniforme **0.667** → bat les deux.

## 7. Métriques hors échantillon (réel, FL1 2025-26)

| Métrique | Valeur | Baseline |
|---|---|---|
| n évalués | 296 | — |
| folds temporels | 10 mois | — |
| Brier | 0.6211 | uniforme 0.6667 · prior 0.6485 |
| log-loss | 1.0327 | uniforme 1.0986 |
| ECE (brute) | 0.0280 | — |
| coverage | 0.9705 | — |
| data_quality moyenne | 0.9392 | — |
| spread Brier / fold | 0.1371 | — |

## 8. Politique `SUPPORTED` (versionnée, mécanique)

`configs/betting_engine/model_maturity_policy.json` (checksum) + `maturity.py`.
**Sémantique explicite** : l'ÉTAT de mesure (`PASS`/`FAIL`/`NOT_MEASURABLE`) est
distinct du BLOCAGE (`required_for_support` par critère). Verdict = **SUPPORTED ssi
tout critère `required_for_support=true` est PASS** ; un requis `FAIL` ou
`NOT_MEASURABLE` → `EXPERIMENTAL`. Un critère non requis est du **monitoring** (jamais
bloquant). Verdict réel :

| Critère | requis | Seuil | Observé | État |
|---|---|---|---|---|
| min_sample_size | oui | ≥ 500 | 296 | **FAIL** |
| min_temporal_folds | oui | ≥ 3 | 10 | PASS |
| max_calibration_error | oui | ≤ 0.05 | 0.028 | PASS |
| must_beat_baselines | oui | model < baseline | 0.621 < 0.648 | PASS |
| min_data_coverage | oui | ≥ 0.90 | 0.970 | PASS |
| min_data_quality | oui | ≥ 0.80 | 0.939 | PASS |
| max_fold_brier_spread | **non** (monitoring) | ≤ 0.15 | 0.137 | PASS |
| positive_clv | oui | > 0 | non mesurable | **NOT_MEASURABLE** |
| measurable_live_freshness | oui | MEASURABLE | câblée Gateway→BE | **PASS** |

**Verdict mécanique : `EXPERIMENTAL`** — bloqué par `min_sample_size` (FAIL) et
`positive_clv` (NOT_MEASURABLE requis). Le statut est **dérivé** d'un ledger
append-only (`support_status.py`) : `manifest.GLOBAL_MODEL_STATUS` et le plafond du
modèle lisent la même source ; `SUPPORTED` exige un `ModelSupportDecision` persisté.

**Seuils = policy V1, pas des vérités statistiques** (cf. ADR-BE-001) : `500` n'est
PAS dérivé des 296 observations (« strictement > une saison ») ; interdiction de les
ajuster rétrospectivement pour promouvoir un modèle. **CLV requise** (absence ≠ CLV
positive). **10 folds = une seule saison/ligue** : absence de fuite garantie, mais
pas une preuve de robustesse inter-saisons (d'où `max_fold_brier_spread` = monitoring).

## 9. CLV — `NOT_YET_MEASURABLE`

Aucune paire décision/clôture n'existe (aucun odds_history). Structure de collecte
posée (`clv/` : `OddsObservation` Decimal, `JsonlOddsHistoryStore` append-only,
`compute_clv` point-in-time, `clv_readiness`). Absence **jamais convertie en 0**
(`mean_clv=None`). Câble BE-FR-015.

## 10. Freshness — mesurée au Gateway ET propagée au point de décision

Gateway (bon endroit). Demi-vies + tolérance staleness live dans
`configs/gateway/freshness_policy.json` (checksum), valeurs inchangées.
`freshness_score = 0.5 ** (age/half_life)` sur l'horodatage **effectif**
(`published > event > fetched`, `resolve_freshness_basis`) ; timestamp manquant →
`degraded=True`, jamais une fraîcheur favorable inventée. Frontières testées.

**Câblage Gateway → BE fermé** : `gateway.data_freshness(...)` (accesseur additif,
même fetch/enveloppe — la Gateway calcule) est consommé par
`live_evaluation.gateway_staleness_probe` (le BE lit l'horodatage effectif, calcule
l'âge, ne recalcule **pas** la fraîcheur). `evaluate_live_event` : sonde injectée >
sonde Gateway > indisponible ; base dégradée (`fetched_at`) → staleness
`NOT_MEASURABLE` (jamais « frais » inventé) ; trop vieux → `DATA_TOO_STALE`. Aucun
contrat gelé modifié, aucune dépendance Advisor. → critère de maturité
`measurable_live_freshness` = **MEASURABLE/PASS**.

## 11. Provenance

Inchangée et déjà riche : `CanonicalEnvelope` (5 horodatages, `provider_entity_id`,
`freshness_basis/degraded`), `point_in_time_store` (`content_hash`, `schema_version`),
`experiment_registry` (`code_revision`, `dataset_fingerprint`, `parameters`),
`OddsObservation` (source, source_event_id, run_id).

## 12. Winamax

**Run réel : impossible dans cet environnement** (pas d'accès réseau
autorisé/approprié à winamax.fr ; anti-bot ; aucun pari réel). Aucun payload réel
capturé n'existe. **Préparé :** `record_replay.py` (capture LIVE via réseau injecté
+ replay hors-ligne, provenance `SOURCE_LIVE`/`SOURCE_SYNTHETIC` **jamais
confondues**). Test de **fidélité** sur état synthétique fidèle : identité,
marché, sélections, cotes (préservées exactement, aucune recomputation), horodatage,
provenance. **Decimal :** les cotes BE sont `float` (contrat gelé antérieur) ; la
sécurité Decimal est imposée en aval (Advisor input_adapter). Aucune fixture
synthétique n'est présentée comme réelle.

## 13. Intégration `evaluate_live_batch` / sélection

Le statut dérivé gouverne la sélection. Modèle `EXPERIMENTAL` → décisions
`ABSTAIN`/`MODEL_NOT_SUPPORTED` (BE-FR-011), métriques calculées pour l'audit,
**jamais de BET, jamais de fallback silencieux**. Un modèle `SUPPORTED` atteint
réellement la branche supportée — laquelle reste la **frontière money-sensitive
différée** (borne basse EV / model_reliability, BE-FR-012), qui échoue **bruyamment**
(`NotImplementedError`), jamais par un fallback qui inventerait un BET.

## 14. Limitations connues / conditions exactes d'un premier `SUPPORTED`

Ce lot livre la **fondation statistique de promotion**, **pas** le money-path BET.
Il ne reste que **2 critères bloquants** pour un premier `SUPPORTED` mécanique
(la freshness live a été câblée dans ce lot et passe déjà) :
1. **min_sample_size** : ajouter ≥ ~1 saison (2ᵉ saison FL1 ou 2ᵉ ligue) → ≥ 500
   prédictions hors échantillon ;
2. **positive_clv** : collecter un odds_history décision→clôture réel (infra prête)
   et obtenir CLV moyenne > 0.
Alors `assess_one_x_two_maturity` émet `SUPPORTED`, `append_support_decision` le
persiste, et le modèle est sélectionnable.

Restent **hors de ce chantier**, forks distincts explicites :
- **`SUPPORTED → BET`** (money-sensitive, BE-FR-012) : borne basse EV +
  `model_reliability`. Aujourd'hui la branche supportée est atteinte mais lève
  `NotImplementedError` (jamais une mise inventée). ADR/lot dédié.
- **sizing COMBO** (déjà différé côté Advisor).
Le Betting Engine n'est donc **pas** « entièrement terminé » : sa fondation
statistique de promotion l'est, son money-path BET ne l'est pas.
