# ADR-ADV-007 (tranche minimale) — Sizing d'une ligne SINGLE

**Statut** : accepté (tranche V1 pour le Lot 6). Le Lot 8 **réutilise/étend** cette
primitive, jamais une 2ᵉ formule.
**Portée stricte** : mise d'**une** ligne SINGLE sur le meilleur candidat
`ELIGIBLE/SUPPORTED`. Hors périmètre (Lot 8) : caps multi-lignes par
événement/participant/compétition, corrélation, allocation entre lignes,
alternatives, optimisation globale, granularité de mise.

## Décisions

### Probabilité alimentant Kelly — borne basse (imposée par le contrat)
Les décisions **monétaires** utilisent la probabilité **prudente** : `probability_low`.
Ce n'est pas un choix nouveau — le PRD l'impose déjà (§8.5 : « `expected_value_low`
utilise `probability_low` » ; BE-FR-012 : chemin SUPPORTED exige un EV à la borne
basse). On ne réinvente pas ce choix.

### Formule Kelly
Kelly simple : `f* = (p·odds − 1) / (odds − 1)` avec `p = probability_low`,
`odds = bookmaker_odds` (`> 1`, garanti). Numérateur `= probability_low·odds − 1
= expected_value_low` (déjà calculé, cohérent).

### Kelly brut ≤ 0 → aucune mise
Si `f* ≤ 0` (aucun edge à la borne basse) → **`stake = 0`** (pas de mise ; jamais
une petite mise « de compensation », §13.2). En pratique un `ELIGIBLE` a
`expected_value_low > 0` (porte Policy) donc `f* > 0` ; la garde reste défensive.

### Fraction & atténuation (PRD §13.3)
```
raw_fraction  = configured_fractional_kelly × f* × reliability × data_quality
proposed      = bankroll × raw_fraction
```
- `configured_fractional_kelly` : **par profil de risque**, en config
  (`configs/advisor/sizing_policy.json`), placeholders à calibrer (conservateur
  = fraction plus faible).
- `reliability` : le `reliability_component` déjà calculé au ranking (calibration
  si présente, sinon baseline maturité) — pas de 2ᵉ définition.
- `data_quality` : `candidate.data_quality`.

### Caps (min sur les seuls présents)
```
stake = min(
    proposed,
    bankroll,                              # une ligne ne dépasse jamais la bankroll
    request.max_total_stake   si présent,
    per_line_cap = per_line_cap_fraction × bankroll,   # config par profil
    candidate.max_stake       si présent,
    candidate.max_payout / odds  si présent,   # garantit stake·odds ≤ max_payout
)
puis stake = max(stake, 0)
```
- **`None` = plafond inconnu/non exposé**, jamais `Decimal(0)` : un cap `None`
  n'entre **pas** dans le `min()` (il ne devient jamais une borne à 0).
- `max_payout` connu → borne la mise à `max_payout / odds` (le gain `stake·odds`
  ne dépasse pas `max_payout`).

### Bankroll non saturée
`unallocated_bankroll = bankroll − total_stake` peut être **strictement positif**.
On n'augmente **jamais** la mise pour utiliser toute la bankroll.

### Garde-fous
- **Aucune mise** si `model_maturity ≠ SUPPORTED` (BE-FR-011, ADV-FR-007) : le
  sizing retourne `0` avant tout calcul.
- **Decimal** partout ; division (Kelly, payout/odds) à précision de calcul fixe
  (28 chiffres), **pas** un arrondi métier (granularité → Lot 8 / ADR-ADV-002).
- Déterminisme : même entrée/config → même mise (aucun `now()` ; `generated_at =
  request.decision_time`).
