# Multisport — matrice de faisabilité (vérifiée en direct, 2026-07-31)

Classement HONNÊTE de chaque sport selon la séparation stricte
**catalogue ≠ données ≠ modèle ≠ maturité ≠ décision ≠ sizing**. Aucun sport n'est
`model_capable` par réutilisation d'une hypothèse football (interdit, §0). Tout ce
tableau dérive de probes réseau réels et du code du dépôt — jamais d'une supposition.

## Providers réellement disponibles (credentials présents)

| provider | clé (.env) | sports | historique | limite |
|---|---|---|---|---|
| football-data.org | `FOOTBALL_DATA_ORG_KEY` | football | ~12 compétitions (saison courante + précédentes) | 10 req/min |
| api-sports.io | `API_FOOTBALL_KEY` (clé de dashboard **partagée**) | football, **basketball, baseball, hockey, rugby, volleyball, handball, F1, AFL, NFL, MMA** | oui (games avec scores) | Free 100 req/jour/sport |
| — tennis — | *(aucune)* | — | — | api-sports.io **n'a PAS de produit tennis** |

Vérifié en direct : `GET v1.basketball.api-sports.io/status` … `v1.mma…/status` → HTTP 200, plan Free actif. `v3.football` idem. Aucune clé tennis / RapidAPI / Sportradar / TheOdds.

## Matrice sport × faisabilité

| sport | catalogue Winamax | données provider | modèle | maturité | live câblé | classe | raison exacte |
|---|---|---|---|---|---|---|---|
| **football** | oui (61 comp / 527 ev) | oui (8 ligues data-capable) | Dixon-Coles 1X2 | **EXPERIMENTAL** | **oui** | `EXPERIMENTAL` | bloqué SUPPORTED par CLV + sample (cf. readiness) |
| **basketball** | oui (sportId 2) | **oui** (API-Basketball, NBA 1386 games réels) | **Elo moneyline v0** | **EXPERIMENTAL** | **oui** (chemin technique complet, hermétique) | `EXPERIMENTAL` | bat baseline ; ABSTAIN (EXPERIMENTAL) ; mapping Winamax NBA en attente (hors-saison) |
| **baseball** | oui (sportId 3) | **oui** (API-Baseball, MLB 2715 games réels) | **Elo moneyline v0** (harness générique, K=4/HE=24) | **EXPERIMENTAL** | non | `EXPERIMENTAL (modèle)` | skill validé (Brier 0.485<0.499) ; live à câbler (identité Winamax MLB) |
| **NFL** (sportId 16) | oui (marché « Vainqueur » **2-way**, vérifié payload) | oui (API-Am.Football) | **Elo moneyline v0** (K=20/HE=48) | **EXPERIMENTAL** | non | `EXPERIMENTAL (modèle)` | skill validé (Brier 0.468<0.492, 533 OOS≥500) ; live à câbler |
| **hockey** (sportId 4) | « Résultat » **3-way** réglementaire (nul) | oui (API-Hockey) | **Davidson 3-way** (Elo+ν) | **EXPERIMENTAL** | non | `EXPERIMENTAL` | résultat réglementaire reconstruit (periods 1-3 ; AOT/AP=nul) ; Brier3 0.628<0.649 & logloss 1.043<1.070 ; **bloqué SEULEMENT par CLV/freshness** (proche SUPPORTED) |
| **volleyball** (23) | « Vainqueur » **2-way** (vérifié) | oui (API-Volley) | **Elo moneyline** (HE=33 dérivé) | **EXPERIMENTAL** | non | `EXPERIMENTAL` | skill FORT (Brier 0.363≪0.499) ; bloqué sample<500 + calibration + CLV |
| rugby XV (sportId 12) | « Résultat » **3-way** (nul rare) | oui (API-Rugby) | — | — | non | `IMPLEMENTABLE_NOW (3-way)` | harness Davidson prêt ; shape api-sports à intégrer ; nuls rares (~3%) |
| AFL (13) | « Vainqueur » 2-way | api-sports AFL | — | — | non | `INSUFFICIENT_DATA` | /games renvoie 0 pour 2022-23 (couverture/shape) |
| handball (sportId 6) | **0 event live** (intersaison) | oui (API-Handball) | — | — | non | `INSUFFICIENT_DATA (live)` | + nul réglementaire probable (3-way) à vérifier en saison |
| MMA (sportId 117) | oui | oui (API-MMA) | — | — | non | `IMPLEMENTABLE_NOW*` | pairwise ; faible fréquence/identité combattants — prudence |
| **tennis** (sportId 5) | oui | **candidats DÉCOUVERTS** (Tavily) mais non confirmés accessibles ici | — | — | non | `EXTERNAL_PROVIDER_REQUIRED` | candidats : tennisabstract / Kaggle ATP-WTA / tennis-api / bigdataball ; aucun provenance+auth-free confirmé en env — STOP §9 |
| F1 / golf / courses | oui | (F1 : api-sports) | — | — | non | `ARCHITECTURAL` | **non pairwise** (outright multi-participant) ; les contrats canoniques actuels sont A-vs-B — ne pas déformer (§10), fork architectural |
| MMA / combat | oui | oui (API-MMA, Free) | — | — | non | `IMPLEMENTABLE_NOW*` | pairwise mais méthodologie combat propre à définir |

### Causes séparées (jamais confondues)
1. **absence de données** — aucune (sports pairwise couverts par api-sports).
2. **absence de provider** — **tennis** (EXTERNAL).
3. **absence de méthodologie** — baseball/hockey/volley/… (modèle à écrire ; données présentes).
4. **architecture manquante** — F1/golf/outrights (contrat non pairwise, §10).
5. **implémentation manquante** — basketball LIVE (maturité faite, orchestration live 2-way à câbler).
6. **validation/maturité insuffisante** — football + basketball restent EXPERIMENTAL (bloqueurs mécaniques réels).

## Architecture — ce qui est neutre au sport (prouvé)

| couche | neutre ? | preuve |
|---|---|---|
| contrats économiques (`CandidateBet`, `MarketPrediction`, `OddsSnapshot`, `BettingDecision`) | oui | champ `sport` porté, jamais lu par la décision |
| **frontière de décision** `evaluate_selection` | **oui** | `test_sport_neutral_decision` : marché 2-way + SUPPORTED synthétique → BET sans bypass ; EXPERIMENTAL → ABSTAIN tout sport |
| ranking Advisor | oui | `test_ranking_is_sport_neutral` : même économie → même score ; aucun bonus football |
| framework de maturité (`evaluate_maturity`) | oui | réutilisé par basket + baseball (observations propres) |
| harness Elo pairwise (`pairwise_elo`) | oui | générique, params par sport ; basket-live + baseball |
| **orchestration live** `evaluate_live_event` | **oui (schema-driven)** | piloté par `MarketSchema` déclaré par le modèle (2-way/3-way) ; `test_live_evaluation_multisport` + `test_basketball_live` |

→ AXON est multisport **de bout en bout** : le chemin live est neutre au marché (basket
2-way réel y transite). Câbler un nouveau sport pairwise = données + identité Winamax +
harness (déterminable, sans refactor du money-path).

## Procédure d'onboarding d'un nouveau sport (pairwise)

1. Vérifier le provider en direct (`/status`) — ne jamais supposer.
2. Récupérer une saison réelle (games + scores + dates) → fixture avec provenance.
3. Choisir le marché V1 le plus simple modélisable (moneyline).
4. Modèle propre au sport (jamais Dixon-Coles) ; **Elo séquentiel** = sans fuite par construction, minimal, validable ; paramètres fixes (non fités sur l'éval).
5. Walk-forward point-in-time + baseline + Brier/ECE hors échantillon.
6. Maturité mécanique via `evaluate_maturity` → EXPERIMENTAL (jamais SUPPORTED sans critères).
7. Test anti-fuite OBLIGATOIRE (§17) + déterminisme + « pas de réutilisation football ».
8. `axon readiness --competition <slug>`.
9. (live) généraliser `evaluate_live_event` + identité Winamax↔provider.

## Dettes

- **DATA** : CLV (toutes maturités) ; sample/calibration par modèle.
- **EXTERNAL** : provider **tennis** (aucun configuré) ; tiers payant pour ligues football hors free tier.
- **STATISTICAL** : méthodologie de marché pour hockey/volley/handball/rugby/NFL/AFL/MMA (données présentes ; harness Elo prêt, à VALIDER par sport — peut rejeter). baseball + basketball = FAITS (skill validé). F1/golf = famille outright (non pairwise).
- **ARCHITECTURAL** : ~~`evaluate_live_event` 1X2-only~~ **RÉSOLU** (schema-driven, 2/3-way). Reste : contrats **outright** pour sports non pairwise (F1/golf, §10) ; hockey/rugby = 3-way (reg.) vs 2-way (OT) à trancher par marché réel (§8/§10).
- **CODE** : aucune sur le chemin structuré.
- **OPERATIONS** : collecte odds/CLV, seed coverage DB, monitoring.
