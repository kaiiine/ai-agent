# 000 — Vision & architecture d'ensemble
## Axon, domaine paris sportifs

**Dernière mise à jour :** 24 juillet 2026
**Point d'entrée de la documentation** — à lire avant les PRD individuels.

---

## 1. Mission

> Axon observe en continu l'univers des événements et marchés proposés par les bookmakers supportés, rattache chaque événement à des données sportives point-in-time, applique uniquement des modèles certifiés pour le sport et le marché concernés, puis classe les opportunités selon leur valeur espérée ajustée de l'incertitude. **Il s'abstient lorsqu'aucun avantage robuste n'est démontré.**

La dernière phrase n'est pas une clause de style : c'est la propriété centrale du système. Un moteur qui produit un pronostic sur tout est facile ; un moteur qui sait précisément sur quoi il n'a rien à dire est ce qui peut réellement avoir un avantage.

### Ce qui distingue ce système d'un LLM généraliste

Un modèle de langage, même très performant, ne possède pas structurellement ces cinq propriétés :

1. **Données propriétaires point-in-time** — l'état exact du monde avant chaque événement est conservé, donc les backtests sont honnêtes.
2. **Modèles calibrés par sport et par marché** — chaque probabilité est mesurable contre un historique.
3. **Suivi des cotes dans le temps** — ouverture, mouvements, clôture.
4. **Mesure systématique de la performance** — Brier score, log loss, calibration, closing-line value. Pas seulement le ROI.
5. **Abstention disciplinée** — pas de recommandation quand la qualité ou l'avantage sont insuffisants.

La mesure de réussite n'est pas « Axon a trouvé trois paris gagnants », mais : *sur N décisions historiques, celles annoncées à 60 % gagnent environ 60 % du temps, l'avantage persiste après marge et incertitude, et le système bat régulièrement la cote de clôture*.

---

## 2. Vue d'ensemble

```
                            ┌──────────────────────────┐
                            │   Bookmakers (Winamax)   │
                            └────────────┬─────────────┘
                                         │ catalogue : événements, marchés, cotes
                                         ▼
┌────────────────────────────────────────────────────────────────────────────┐
│                          axon-betting-engine                                │
│                                                                             │
│   bookmakers/          scan catalogue · normalisation marchés · odds history│
│         │                                                                   │
│         ▼                                                                   │
│   canonical_event_registry     événements pariables, indépendants du bookie │
│         │                                                                   │
│         │  ┌──────────────────────────────────────────────────────────┐    │
│         ├─►│           axon-sports-data-gateway  (dépendance)          │    │
│         │  │                                                            │    │
│         │  │   providers/ → normalizers/ → canonical facts              │    │
│         │  │   → derived datasets                                       │    │
│         │  │                                                            │    │
│         │  │   core/ : fallback · identity · quality · point-in-time    │    │
│         │  │   registries/ : compétitions · couverture provider          │    │
│         │  │   sports/<sport>/ : SportModule (schéma, normalizers, dérivés)│  │
│         │  └──────────────────────────────────────────────────────────┘    │
│         ▼                                                                   │
│   sports/<sport>/feature_engineering    → EventFeatureSet                   │
│         │                                                                   │
│         ▼                                                                   │
│   sports/<sport>/market_models          → MarketPrediction + explication    │
│         │                                                                   │
│         ▼                                                                   │
│   calibration/     walk-forward · calibration · drift · experiment registry │
│         │                                                                   │
│         ▼                                                                   │
│   value_engine/    retrait marge · EV · incertitude · abstention            │
│         │                                                                   │
│         ▼                                                                   │
│   portfolio/       exposition · corrélation entre sélections                │
│         │                                                                   │
│         ▼                                                                   │
│   bet_ranking      →   BET / WATCH / ABSTAIN, classés                       │
└────────────────────────────────────────────────────────────────────────────┘
                                         │
                                         ▼
                              HITL — validation par Kaine
```

**Direction de dépendance, sans exception** : `axon-betting-engine` → `axon-sports-data-gateway`. La gateway ignore l'existence du betting-engine et reste utilisable par n'importe quel autre consommateur (`ADR-001`).

---

## 3. Les modules

### 3.1 Vocabulaire de statut

Pour éviter toute ambiguïté sur ce qui existe réellement, les statuts utilisent un vocabulaire fermé — « en production » ne veut rien dire de précis sur un projet personnel :

| Statut | Signification exacte |
|---|---|
| `SPECIFIED` | Document écrit, aucun code |
| `IMPLEMENTED` | Code écrit, tests unitaires passants |
| `VALIDATED_ON_REAL_DATA` | Vérifié de bout en bout contre des données réelles de providers |
| `DEPLOYED` | Tourne ailleurs que sur la machine de dev (service, conteneur, VPS) |
| `OPERATED` | Exécuté régulièrement, avec supervision et alerting |

**Aucun module n'est aujourd'hui `DEPLOYED` ni `OPERATED`.** Il n'y a ni Docker, ni CI/CD, ni monitoring sur ce domaine — tout tourne localement, lancé à la main.

### 3.2 État réel

| Module | Rôle | Statut | Document |
|---|---|---|---|
| **axon-sports-data-gateway v1** | Providers, normalisation, identité, fallback, point-in-time. Football, Ligue 1 + Premier League | `IMPLEMENTED` + `VALIDATED_ON_REAL_DATA` | `PRD-axon-sports-data-gateway-v1-HISTORICAL.md` |
| **axon-sports-data-gateway v2** | Socle multi-sport : `SportModule`, schémas versionnés, registres séparés, couverture par saison × data_type | `SPECIFIED` | `PRD-axon-sports-data-gateway-v2.md` |
| **axon-betting-engine** | Catalogue bookmaker, feature engineering, market models, calibration, valeur, portefeuille, classement | `SPECIFIED` | `PRD-axon-betting-engine.md` |
| **Décisions d'architecture** | 14 ADR documentant les choix structurants et leurs compromis | — | `ADR.md` |
| **Vocabulaire** | Glossaire partagé par tous les documents | — | `GLOSSARY.md` |

Seule la v1 de la gateway existe en code : football, deux compétitions, pipeline vérifié sur données réelles (forme récente, classements, fallback multi-provider, point-in-time store). Tout le reste est spécifié, pas construit. Cette distinction doit rester lisible — c'est ce qui évite de raisonner sur un système imaginaire.

---

## 4. Les trois frontières qui structurent tout

L'essentiel de l'architecture tient dans trois séparations. Si elles s'érodent, le système redevient un monolithe difficile à faire évoluer.

### 4.1 Données ≠ décision

```
axon-sports-data-gateway  │  axon-betting-engine
  ce qui est vrai         │    ce qu'on en déduit
```

La gateway ne produit jamais de probabilité, de valeur ou de recommandation. Le betting-engine ne parle jamais directement à un provider. → `ADR-001`

### 4.2 Faits ≠ dérivés ≠ features

```
Canonical facts  →  Derived datasets  │  →  Model features
────── gateway ──────────────────────  │  ─── betting-engine ───
```

Critère de tri opérationnel : **un dérivé est une fonction pure et déterministe des faits**. Dès qu'un paramètre appris intervient, c'est une feature, et elle change de projet. → `ADR-003`

### 4.3 Sport ≠ marché

Un sport n'est pas une unité de prédiction. Un modèle « vainqueur du match » et un modèle « total de jeux » du même sport ont des variables, des historiques et des fiabilités différents. L'unité est le couple `(sport, market_type)`. → `ADR-002`

---

## 5. Principes non négociables

Ces règles s'appliquent à tous les modules. Une exception à l'une d'elles justifie un nouvel ADR, pas un contournement local.

**Point-in-time strict.** Aucune donnée postérieure à l'instant de décision n'entre dans une prédiction ou un backtest. `available_to_model_time` est la référence, jamais `fetched_at`. → `ADR-004`

**Pas de donnée inventée.** Trois issues seulement : donnée fraîche, donnée `stale=True` explicite, ou échec typé. Jamais de valeur par défaut, jamais d'extrapolation silencieuse. → `ADR-011`

**Pas de fusion silencieuse.** Chaque valeur conserve sa provenance, ses horodatages et sa qualité. Arbitrer entre deux sources est une décision explicite, jamais un comportement caché.

**Abstention légitime.** `ABSTAIN` et `UNSUPPORTED` sont des sorties normales. Un marché sans modèle validé n'est jamais soumis à prédiction.

**Explicabilité obligatoire.** Toute prédiction porte son explication (features contributives, données manquantes, warnings). Non optionnel. → `ADR-013`

**Versioning explicite.** Schémas canoniques, contextes d'événement, versions de modèles et de feature sets sont versionnés. Une incompatibilité échoue bruyamment. → `ADR-009`

**Identité typée et unique.** Un `canonical_id` par entité dans tout Axon, au format `{entity_type}:{sport}:{scope}:{slug}`. Jamais de rattachement automatique par proximité de nom. → `ADR-008`

**Humain dans la boucle.** Aucun pari placé automatiquement. → `ADR-014`

---

## 6. Trajectoire

Une seule tranche verticale à la fois, complète de bout en bout, plutôt que plusieurs chantiers larges en parallèle.

```
┌─ FAIT ────────────────────────────────────────────────────────┐
│ Gateway v1 · football · Ligue 1 + Premier League               │
│ providers, fallback, identité, point-in-time, cache            │
└───────────────────────────────────────────────────────────────┘
                              ▼
┌─ SOCLE (gateway v2, vague 0) ─────────────────────────────────┐
│ SportModule · schémas versionnés · registres séparés           │
│ migration football, critère de sortie = non-régression         │
└───────────────────────────────────────────────────────────────┘
                              ▼
┌─ TRANCHE VERTICALE 1 ─────────────────────────────────────────┐
│ Scanner Winamax (sans prédiction)                              │
│ → tennis dans la gateway (vague 1)                             │
│ → EventFeatureSet tennis                                       │
│ → UN SEUL MarketModel : tennis / vainqueur du match            │
│ → calibration + experiment registry                            │
│ → value engine + portfolio + ranking                           │
│ Sortie : une recommandation réelle, justifiée, auditable       │
└───────────────────────────────────────────────────────────────┘
                              ▼
┌─ ENSUITE, dans cet ordre ─────────────────────────────────────┐
│ 2e marché tennis (total de jeux) — valide l'extension marché   │
│ 2e sport (baseball MLB) — valide l'extension sport             │
│ football rebranché en MarketModel — sans statut prioritaire    │
│ autres sports selon le catalogue réel et la couverture vérifiée│
└───────────────────────────────────────────────────────────────┘
```

**Pourquoi le tennis d'abord et pas le football** : le football est le sport déjà construit côté données, donc le plus tentant. Mais c'est aussi celui qui validerait le moins l'architecture — il ne prouverait rien sur la généralisation. Le tennis a une structure d'événement franchement différente (deux joueurs, surfaces, sets, pas d'équipes), ce qui teste réellement le socle. Le football sera rebranché ensuite, à peu de frais.

**Pourquoi un seul marché et pas « le tennis »** : parce que la partie difficile n'est pas de produire une probabilité, c'est de démontrer qu'elle est calibrée. Faire cette démonstration une fois, complètement, apprend plus que dix modèles non validés.

---

## 7. Ce qui reste ouvert

Points non tranchés qui bloquent ou conditionnent la suite :

- **Accès au catalogue Winamax** — méthode technique et implications ToS à clarifier **avant** l'étape 1 du betting-engine. C'est le seul préalable réellement bloquant.
- **Seuils de décision** (EV minimal, `data_quality`, `model_reliability` pour émettre un `BET`) — non fixables avant d'avoir un historique réel de décisions.
- **Format de stockage des registres** — SQLite vs YAML versionné, selon le volume et le mode d'édition.
- **Granularité des agents Axon** — un agent `betting_engine/` ou plusieurs, suivant la convention `src/agents/<domaine>/`.
- **README du dépôt** — encore désynchronisé : il ne mentionne aucune fonctionnalité paris, alors que la gateway v1 tourne. À reprendre une fois la première tranche verticale livrée.

---

## 8. Ordre de lecture

1. **Ce document** — vision d'ensemble et frontières.
2. **`GLOSSARY.md`** — vocabulaire, à garder ouvert en lisant les PRD.
3. **`ADR.md`** — pourquoi les choix structurants ont été faits ainsi.
4. **`PRD-axon-sports-data-gateway-v1-HISTORICAL.md`** — ce qui existe en code aujourd'hui. **Document historique : ne définit pas l'architecture cible.**
5. **`PRD-axon-sports-data-gateway-v2.md`** — le socle multi-sport.
6. **`PRD-axon-betting-engine.md`** — le produit.

---

## 9. Ordre de priorité documentaire

En cas de contradiction entre deux documents, l'ordre d'autorité est :

1. **ADR au statut `Accepté`** — les décisions structurantes priment sur toute description qui les contredirait.
2. **PRD du module concerné, dans sa version la plus récente** — la v2 prime sur la v1.
3. **`GLOSSARY.md`** — arbitre le sens des termes.
4. **`000-vision.md`** — ce document ; il synthétise, il n'invente pas.
5. **PRD historiques** (`*-HISTORICAL.md`) — valeur documentaire uniquement, aucune autorité sur la cible.

Une contradiction constatée n'est pas à trancher silencieusement à l'implémentation : elle doit être signalée, et résolue soit par un nouvel ADR, soit par une correction du PRD concerné.

---

## 10. Convention de numérotation des exigences

| Préfixe | Portée |
|---|---|
| `GW-FR-XXX` | Exigence fonctionnelle — `axon-sports-data-gateway` |
| `GW-NFR-XXX` | Exigence non fonctionnelle — `axon-sports-data-gateway` |
| `BE-FR-XXX` | Exigence fonctionnelle — `axon-betting-engine` |
| `BE-NFR-XXX` | Exigence non fonctionnelle — `axon-betting-engine` |
| `ADR-XXX` | Décision d'architecture |

Ces identifiants sont stables : ils servent de référence dans les messages de commit, les tests (`test_gw_fr_008_typed_namespaces`), les tickets et la matrice de traçabilité exigence → fichier → test.

Le PRD v1 historique utilise une ancienne numérotation (`F1`–`F13`) qui n'est pas reprise — ne pas y faire référence dans du code ou des tests nouveaux.
