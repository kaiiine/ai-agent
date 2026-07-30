# ADR-BE-001 — Maturité modèle dérivée & critères `SUPPORTED` mécaniques

**Statut :** accepté. Détail complet : `axon-betting-engine-gateway-current-state.md`.
**Contexte :** PRD-BE §7.1 (« aucun `MarketModel` SUPPORTED sans calibration
walk-forward documentée »), BE-FR-011, Definition of Done (« CLV positif en
moyenne »), §Q3 (« seuils non fixés ici, à calibrer »).

## Décision
`SUPPORTED` cesse d'être **déclaratif**. Il devient la sortie **mécanique** d'un
verdict versionné sur des preuves hors échantillon.

- **Politique versionnée** `configs/betting_engine/model_maturity_policy.json`
  (`config_version`/`effective_from`/`checksum`).
- **Verdict** (`maturity.evaluate_maturity`), pur et déterministe.
- **Statut dérivé** : `support_status.py` (ledger append-only). `manifest.
  GLOBAL_MODEL_STATUS` et le plafond de readiness du modèle lisent la **même
  source** ; promotion = un `ModelSupportDecision` SUPPORTED persisté.
- **Outil** `assessment.py` : exécute le walk-forward réel et émet le verdict.

## Sémantique de `NOT_MEASURABLE` — option C (configurable par critère)
Deux notions **strictement séparées** :

| Notion | Valeurs | Porté par |
|---|---|---|
| **État de mesure** | `PASS` / `FAIL` / `NOT_MEASURABLE` | résultat du critère |
| **Caractère bloquant** | `required_for_support: true/false` | `configs/…/model_maturity_policy.json` |

Règle de verdict : **`SUPPORTED` ssi tout critère `required_for_support=true` est
`PASS`.** Un critère requis en `FAIL` **ou** `NOT_MEASURABLE` → `EXPERIMENTAL`. Un
critère `required_for_support=false` est du **monitoring** : reporté, jamais
bloquant, même `NOT_MEASURABLE` ou `FAIL`. Défaut fail-safe : un critère absent du
mapping est **requis** (on ne rend jamais un critère optionnel par omission).

Rejeté : (A) ignorer `NOT_MEASURABLE` du calcul — masquerait une preuve absente ;
(B) toujours bloquant en dur — non configurable, empêche le monitoring légitime.

### Décisions V1 par critère
| Critère | `required_for_support` | Justification |
|---|---|---|
| min_sample_size, min_temporal_folds, max_calibration_error, must_beat_baselines, min_data_coverage, min_data_quality | **true** | validité statistique de base |
| **positive_clv** | **true** | Definition of Done PRD-BE (« CLV positif en moyenne ») |
| **measurable_live_freshness** | **true** | le chemin live doit exposer une fraîcheur mesurée avant promotion (désormais câblé, ADR-BE-002) |
| **max_fold_brier_spread** | **false** (monitoring) | stabilité inter-folds sur **une seule saison** = informative, pas une preuve |

### CLV : requise, absence ≠ succès
`positive_clv` est **requise** en V1. Tant qu'aucun `odds_history` décision→clôture
n'existe, elle est `NOT_MEASURABLE` et **bloque** la promotion. Le système ne
prétend **jamais** que le critère « passe » : **absence de CLV mesurée ≠ CLV
positive**. Collecter des cotes historiques réelles est un **prérequis réel** à un
premier `SUPPORTED` (infra prête, `clv/`). Un modèle ne peut donc pas devenir
`SUPPORTED` sans avoir eu de CLV mesurée positive — choix assumé, cohérent avec la
DoD, **non** retenu pour « faire passer le modèle plus tôt » (c'est le choix strict).

## Seuils V1 = *policy thresholds*, pas des vérités statistiques
Le PRD ne fixe pas les nombres (« à calibrer »). Ces seuils sont des **choix de
politique V1 à recalibrer avec davantage de données**, jamais des constantes
statistiques universelles.

| Seuil | Origine |
|---|---|
| `min_sample_size = 500` | **policy V1**, PAS démontré à partir des 296 observations : « strictement > une saison de 1ʳᵉ division » (~380 matchs, ~300 évaluables), contre la sur-confiance sur une saison unique |
| `min_temporal_folds = 3` | policy V1 : ≥ 3 segments mensuels distincts |
| `max_calibration_error = 0.05` | policy V1 sur l'ECE mutualisée |
| `max_fold_brier_spread = 0.15` | policy V1 (monitoring) |
| `must_beat_baselines` | **benchmark relatif** (model Brier < min baseline Brier), pas un Brier absolu arbitraire |

**Interdiction explicite** : ne jamais ajuster ces seuils **rétrospectivement** pour
promouvoir un modèle précis. Toute révision = nouvelle `config_version` documentée.

## Limite des « 10 folds » : une seule saison / une seule ligue
Les 10 folds temporels du run FL1 proviennent d'**une seule trajectoire** : Ligue 1
2025-2026. Le protocole garantit l'**absence de fuite temporelle**, mais **pas**
encore une forte diversité de régimes, de saisons, de ligues ou de populations. Le
critère `min_temporal_folds` est satisfait **au sens du protocole walk-forward V1**,
sans constituer à lui seul une preuve de robustesse inter-saisons ou inter-ligues.
Cette note n'abaisse pas le `PASS` ; elle empêche une lecture trop forte du chiffre.
(C'est aussi pourquoi `max_fold_brier_spread` est du monitoring, non bloquant.)

## Verdict réel (FL1 2025-26)
`EXPERIMENTAL` : `min_sample_size` **FAIL** (296<500) et `positive_clv`
**NOT_MEASURABLE** (requis). `measurable_live_freshness` **PASS** (câblée) ; 6 autres
critères PASS (le modèle bat les baselines, ECE 0.028). **Aucun `SUPPORTED` fabriqué.**

## Conséquences
Promotion future = conséquence mécanique de nouvelles données (2ᵉ saison/ligue +
odds_history réel), pas un nouveau chantier. Le chemin **`SUPPORTED → BET`**
(money-sensitive, BE-FR-012) reste une **frontière différée distincte** : ce lot livre
la *fondation statistique de promotion*, **pas** le money-path BET.
