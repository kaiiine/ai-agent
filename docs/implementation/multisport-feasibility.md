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
| **basketball** | oui (sportId 2) | **oui** (API-Basketball, NBA 1386 games réels) | **Elo moneyline v0** | **EXPERIMENTAL** | non | `EXPERIMENTAL (modèle) / live à câbler` | modèle réel validé (bat baseline) ; live nécessite `evaluate_live_event` 2-way |
| baseball | oui (sportId 3) | oui (API-Baseball, Free) | — | — | non | `IMPLEMENTABLE_NOW` | données ok ; méthodologie moneyline (Elo/pairwise) à implémenter |
| hockey | oui | oui (API-Hockey, Free) | — | — | non | `IMPLEMENTABLE_NOW` | idem baseball |
| volleyball / handball / rugby / NFL / AFL | oui | oui (api-sports, Free) | — | — | non | `IMPLEMENTABLE_NOW` | pairwise team-vs-team ; recette Elo transférable, à valider par sport |
| **tennis** | oui (sportId 5) | **non** | — | — | non | `EXTERNAL_PROVIDER_REQUIRED` | **aucun provider tennis configuré** (api-sports.io n'en propose pas) — STOP |
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
| framework de maturité (`evaluate_maturity`) | oui | réutilisé tel quel par le basket (observations propres) |
| **orchestration live** `evaluate_live_event` | **NON** | verrouillé 1X2/3-way (`_first_1x2_market`, `_SELECTIONS=home/draw/away`, `_EXPECTED_SELECTIONS[MATCH_WINNER]`) — football-spécifique |

→ AXON est multisport **au niveau modèle + maturité + décision**, mais l'orchestration
LIVE reste football-1X2. Câbler le live d'un sport 2-way = généraliser
`evaluate_live_event` + `_EXPECTED_SELECTIONS` (unité déterminable, non faite ici).

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
- **STATISTICAL** : méthodologie de marché pour baseball/hockey/volley/handball/rugby/NFL/AFL/MMA (données présentes ; modèle à écrire + valider) ; F1/golf = famille de contrats outright (non pairwise).
- **ARCHITECTURAL** : `evaluate_live_event` 1X2-only (bloque le LIVE non-football) ; contrats outright pour sports non pairwise (§10).
- **CODE** : aucune sur le chemin structuré.
- **OPERATIONS** : collecte odds/CLV, seed coverage DB, monitoring.
