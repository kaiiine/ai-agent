# ADR-ADV-014 — Sizing COMBO V1 (fermeture du fork Lot 9)

**Statut :** accepté. Décision produit : **Option B** (le COMBO réutilise le Kelly
canonique, conservatisme explicite versionné). Détail : `axon-advisor-current-state.md`.
**Contexte :** Lot 9 (`ComboSizingRequired`), ADR-ADV-007 (sizing SINGLE), PRD §13.

## Décisions tranchées
| Question | Décision |
|---|---|
| **Kelly owner** | Primitive canonique EXISTANTE `recommendation/simple.compute_single_stake` / `kelly_fraction` — **aucune 2e formule**, aucune copie. |
| **Probabilité de sizing** | `combined_prob_low` (borne basse). **JAMAIS** `combined_prob_mean`. |
| **safety_margin** | Appliquée **UNE fois**, dans le pricing (Lot 9), déjà incorporée à `combined_prob_low`. **Jamais** réappliquée au stake (`stake *= margin` interdit). |
| **combo_fractional_kelly** | Conservatisme de sizing dédié, **par profil de risque**, versionné, invariant `0 < combo_fractional_kelly ≤ single_fractional_kelly`. |
| **bankroll consumption** | Le stake du combo consomme `stake` **une seule fois** du budget total (pas `2·stake`). |
| **exposure / concentration** | Le stake du combo est compté sur **CHAQUE jambe** : `exposure_keys` synthétiques = **UNION** des jambes → un combo `(A,B)` contribue à l'exposition de `A` ET de `B`. |
| **portfolio allocation** | Reste propriété du **Portfolio Optimizer (Lot 8)** : caps/concentration globaux inchangés. Le sizing COMBO produit une **mise candidate plafonnée** (comme un single) ; Lot 8 applique les caps portefeuille. |
| **sizing SINGLE** | **inchangé** (golden non-régression). |

## Mécanique
Le combo est représenté par un `CandidateBet` **synthétique** (`combos/sizing.py`) :
`probability_low=combined_prob_low`, `bookmaker_odds=combined_odds`, `data_quality` et
`reliability` = **min des jambes** (conservateur), `exposure_keys` = union, `maturity`
= `SUPPORTED` **ssi toutes les jambes** le sont (sinon stake 0, BE-FR-011). Il est
passé à `compute_single_stake` avec une `SizingProfile` COMBO (`combo_fractional_kelly`,
`combo_line_cap_fraction`) → réutilise EXACTEMENT le Kelly canonique.

## Conservatisme réparti (jamais dupliqué)
`INDEPENDENT_ENOUGH` reste une **approximation structurelle** (événements/participants
disjoints), pas une preuve d'indépendance. Le conservatisme V1 est réparti sur trois
leviers **distincts**, sans dupliquer la même correction :
1. **pricing prudent** (`safety_margin` sur mean ET low, Lot 9) ;
2. **fractional sizing** (`combo_fractional_kelly ≤ single`) ;
3. **caps d'exposition** sur chaque jambe (`combo_line_cap_fraction ≤ single` + caps Lot 8).

## Zéro stake
Invariant préservé : `stake ≤ 0` (Kelly ≤ 0, bankroll 0, cap 0, arrondi à 0) → **aucune
PortfolioLine COMBO**. Le combo évalué reste dans l'audit/alternatives avec son reason
code, jamais une ligne financée à stake nul.

## Seuils = policy V1
`combo_fractional_kelly` / `combo_line_cap_fraction` dans `sizing_policy.json`
(checksum, per-profil) : **policy V1 conservatrice** (combo = moitié du single), PAS des
optima statistiques ; à recalibrer avec l'expérience réelle ; jamais ajustées a
posteriori pour augmenter les mises.

## Scope
V1 : 2 legs, même bookmaker (compatibilité Lot 9). 3+ legs différé. L'acceptation réelle
du combo par le bookmaker n'est pas vérifiée (donnée non exposée) — note conservée.
