# ADR-BE-003 — Money-path `SUPPORTED → BET` (BE-FR-012)

**Statut :** accepté. Détail : `axon-betting-engine-gateway-current-state.md`.
**Contexte :** BE-FR-011/012/014, PRD-BE §8.5 (value engine), §Q3 (« seuils non
fixés, à calibrer »), §ligne 500 (« value_engine ne gère pas la bankroll ni le
sizing »), ADR-ADV-007 (sizing Advisor).

## Fork tranché : Option A (BE décide, Advisor size)
Le `NotImplementedError` du chemin SUPPORTED est remplacé par une **décision
BET/ABSTAIN + exposition économique**, **sans sizing**. Preuve architecturale :
PRD-BE ligne 500 exclut explicitement bankroll/sizing du value_engine ; le Kelly
canonique vit déjà dans Advisor (`recommendation/simple.py`, « jamais une 2ᵉ
formule », ADR-ADV-007). Choisir Option B/C dupliquerait le Kelly — rejeté.

### Carte de responsabilité
| Responsabilité | Propriétaire |
|---|---|
| BET / ABSTAIN | **Betting Engine** (`value_engine.evaluate_selection`) |
| Sizing / Kelly | **Advisor** (`recommendation/simple.py`, ADR-ADV-007) — inchangé |
| Cap single-décision (`per_line_cap_fraction`, `max_stake`, `max_payout`) | **Advisor** (Lot 6) |
| Caps portfolio (event/participant/competition/bookmaker) | **Advisor** (Lot 8) |
| Valeur de `model_reliability` | **BE** l'expose ; **Advisor** la consomme |

Le BE ne devient **pas** un Portfolio Optimizer bis : `single-decision risk ≠
portfolio allocation`.

## Séquence (money-path)
```
maturité (calibration_status == SUPPORTED, sinon MODEL_NOT_SUPPORTED)
→ gates data/fraîcheur (evaluate_live_event : DATA_TOO_STALE / INSUFFICIENT_FEATURES / …, en AMONT)
→ source de probabilité (fair_probability + probability_low du modèle, jamais recalculée)
→ gate intervalle ESTIMÉ (sinon pas de vraie borne basse)
→ gate data_quality ≥ min_data_quality
→ gate model_reliability ≥ min_model_reliability
→ gate valeur PRUDENTE : worst_case_ev = probability_low·odds − 1 ≥ min_bet_ev  (BE-FR-012)
→ BET (proposition, BE-FR-014) | ABSTAIN (reason code)
```
Le BET **n'inclut aucune mise** : il expose `worst_case_ev`, `expected_value`
(moyen), `edge`, `no_vig`, `model_reliability`, `data_quality` — le sizing Advisor
consomme ces champs.

## EV : pourquoi la borne basse
BE-FR-012 : l'EV déclenchant un BET est calculée à la **borne basse** de
l'intervalle (`probability_low`), jamais à la moyenne — « un edge qui disparaît à
la borne basse ne doit jamais produire BET » (PRD §8.5). Invariant testé :
`expected_value(moyen) > 0` mais `worst_case_ev ≤ seuil` → **ABSTAIN**. La moyenne
ne sauve jamais une borne basse insuffisante. Un intervalle NON estimé
(`probability_low == fair`) → ABSTAIN (`UNCERTAINTY_NOT_ESTIMATED`) : pas de fausse
borne basse.

## `model_reliability` : définition et rôle
- **Sémantique** (PRD ligne 471) : confiance exploitable, propre au `(sport,
  market_type)`, dans `[0,1]`. Distincte de `SUPPORTED` (maturité globale) :
  `SUPPORTED ≠ reliability = 1`.
- **Rôle en BE** : **gate** (`≥ min_model_reliability`) + **exposition** pour le
  sizing Advisor (qui la multiplie dans le Kelly fractionné → monotone : reliability
  plus basse ⇒ mise ≤, propriété du Lot 6 **inchangée**, caractérisée par test).
- **V1** : aucune définition canonique par-modèle n'existe encore (nécessite un
  historique de calibration réel — dette de données, comme la CLV). V1 assigne une
  **reliability EXPLICITE par politique** (`bet_decision_policy.supported_model_reliability`),
  conservatrice et versionnée — **jamais** une formule fabriquée type `1 − ECE`
  (§7). C'est exactement la stratégie permise « SUPPORTED → reliability déterminée
  par une politique explicite ». Une vraie reliability par-modèle remplacera cette
  valeur via le même seam, sans nouveau fork.

## Kelly : formule canonique unique
Le Kelly `f* = (p·odds − 1)/(odds − 1)` sur `probability_low` vit **uniquement**
dans Advisor (`recommendation/simple.kelly_fraction`, ADR-ADV-007). Ce lot n'en
crée **aucune seconde** : le BE n'appelle jamais Kelly. Test de non-duplication :
caractérisation read-only de `compute_single_stake` (monotonie reliability,
bankroll 0 → mise 0), Lot 6 non modifié.

## Seuils = policy V1
`configs/betting_engine/bet_decision_policy.json` (checksum) : `min_bet_ev=0.02`,
`min_data_quality=0.70`, `min_model_reliability=0.60`, `supported_model_reliability=0.75`.
**Non fixés par le PRD** (§Q3 : « à calibrer une fois qu'il y a un historique réel
de décisions ») → décisions V1 à recalibrer, jamais ajustées rétrospectivement pour
faire parier un modèle précis. Valeurs `float` : le contrat économique BE
(cotes/proba/EV) est en float et **aucune somme monétaire n'est calculée dans le
BE** (Option A) → aucun float monétaire ici ; la sécurité Decimal vit à la frontière
de sizing Advisor.

## Advisor : aucun contrat cassé
`AdaptedEvaluation.calibration_score = model_reliability` (adaptateur inchangé). Le
modèle réel restant EXPERIMENTAL, le BE émet toujours `model_reliability=None` pour
lui → Advisor inchangé en pratique (baseline `supported_baseline`). Aucun fichier
Advisor (Lots 0→10) modifié.

## Scope
Le sizing **COMBO** reste différé (fork Advisor/Combo distinct). Ce lot ne place
aucun pari réel (BE-FR-014).
