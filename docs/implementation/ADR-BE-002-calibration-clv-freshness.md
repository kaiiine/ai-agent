# ADR-BE-002 — Calibration mesurable, CLV point-in-time, freshness versionnée

**Statut :** accepté. Détail complet : `axon-betting-engine-gateway-current-state.md`.
**Contexte :** PRD-BE §7.1 (calibration walk-forward, Brier/log-loss/CLV), BE-FR-015
(`odds_history` ouverture→clôture append-only), GW-NFR-003 (freshness_score exposé).

## Calibration
- **Mesure** : ECE mutualisée sur les 3 issues (`metrics.expected_calibration_error`),
  auto-descriptive, distincte de l'accuracy. Mesurée hors échantillon.
- **Calibrateur** : histogram binning (`calibration/calibrator.py`) — délibérément le
  plus **simple et auditable** (le PRD cite isotonic/Platt ; données trop rares pour
  du sophistiqué). **Point-in-time** : ajusté uniquement sur les paires strictement
  antérieures (jamais l'observation qu'il évalue) ; identité sous `min_samples` ; bin
  vide → proba brute (jamais 0).
- **Règle EXPLICITE brut vs calibré** (`walk_forward.select_probability_source`) : on
  n'adopte la re-calibration **que si elle améliore STRICTEMENT l'ECE hors
  échantillon**. Le système ne suppose **jamais** `calibrated == better` : le
  calibrateur existe comme infrastructure, il n'est **pas** appliqué aveuglément.
- **Constat honnête (FL1 2025-26)** : ECE brute 0.0280 (déjà bien calibré) ; ECE
  re-calibrée 0.0323 ≥ brute → **recommandation = `raw`**, probabilités brutes
  conservées. Le calibrateur reste disponible pour des volumes futurs.

## CLV — `NOT_YET_MEASURABLE`
`clv/` : `OddsObservation` (Decimal, jamais float ; provenance source/run),
`JsonlOddsHistoryStore` append-only (var/, jamais ~/.axon), `compute_clv`
(`decision < closing` STRICT), `clv_readiness`. Aucune donnée → `NOT_YET_MEASURABLE`,
`mean_clv=None`. **L'absence n'est jamais convertie en 0.** Câble BE-FR-015.

## Freshness (Gateway, pas Advisor) — **câblée Gateway → BE**
Demi-vies + tolérance staleness live externalisées dans
`configs/gateway/freshness_policy.json` (checksum) — **valeurs inchangées**, formule
inchangée (`quality.freshness_score`). Horodatage effectif `published > event >
fetched` (`resolve_freshness_basis`) ; manquant → `degraded=True`, jamais une
fraîcheur favorable inventée. Frontières temporelles testées ; tolérance live n'est
plus un placeholder codé en dur.

**Propagation au point de décision (dette de câblage fermée)** : la Gateway expose
`gateway.data_freshness(...)` (accesseur ADDITIF réutilisant le même fetch/enveloppe —
la Gateway **calcule**), et le BE la **consomme** via
`live_evaluation.gateway_staleness_probe` (aucune recomputation : simple âge
`decision_time − effective_time`). `evaluate_live_event` priorise : sonde injectée >
sonde dérivée de la Gateway > indisponible. **Base dégradée (repli `fetched_at`) →
staleness `NOT_MEASURABLE`** (note explicite), jamais convertie en « frais ». Aucun
contrat public gelé modifié (`evaluate_live_event` inchangé de signature, seam
`freshness_probe` préexistant) ; aucune dépendance Advisor. Tests :
`test_live_evaluation.py` (récente→EVALUATED, stale→DATA_TOO_STALE,
dégradée/absente→non mesurable, provenance vérifiée). Conséquence : le critère de
maturité `measurable_live_freshness` passe de `NOT_MEASURABLE` à **MEASURABLE/PASS**.

## Alternatives rejetées
- Isotonic/Platt d'emblée : sur-dimensionné pour ~300 événements.
- Calibrer sur l'ensemble d'évaluation : fuite (rejeté par construction point-in-time).
- Fabriquer une CLV ou une freshness pour satisfaire un contrat : falsification.

## Conséquences
Calibration mesurable et anti-fuite (sélection brut/calibré explicite) ; CLV réelle
dès qu'un odds_history existe ; freshness honnête, versionnée **et propagée** au
point de décision live. Dette restante réduite à : **collecter l'odds_history réel**
(CLV) — dépendance de données, pas de câblage.
