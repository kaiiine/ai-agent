# Glossaire — Axon (domaine paris sportifs)

Vocabulaire partagé par `PRD-axon-sports-data-gateway-v1-HISTORICAL.md`, `PRD-axon-sports-data-gateway-v2.md`, `PRD-axon-betting-engine.md` et les ADR. Un terme employé dans un de ces documents a **exactement** le sens défini ici.

---

## Données et niveaux de traitement

**Canonical fact** — Ce qu'un provider affirme, normalisé au schéma du sport, sans transformation : un match a eu lieu à telle date, tel score, telle surface ; un joueur était classé Nᵉ à telle date. Produit par `axon-sports-data-gateway`, stocké dans le point-in-time store. *Ne pas confondre avec un dérivé.*

**Derived dataset** — Agrégat **déterministe** calculé à partir de faits canoniques et d'une fenêtre temporelle : forme sur les 10 derniers matchs, head-to-head, pourcentage de jeux de service tenus. Critère : une fonction pure des faits, sans aucun paramètre appris. Produit par `axon-sports-data-gateway` (`sports/<sport>/derived.py`). Voir `ADR-003`.

**Model feature** — Variable d'entrée d'un modèle : Elo par surface, indicateur de fatigue, différentiel encodé. Dès qu'un paramètre entraîné ou une pondération apprise intervient, on est ici et plus dans un dérivé. Produit par `axon-betting-engine` (`sports/<sport>/feature_engineering/`). Voir `ADR-003`.

**Raw provider response** — Réponse JSON brute d'un provider, non transformée. Transportée par les providers, jamais exposée aux consommateurs.

**Normalizer** — Composant qui convertit un raw provider response en faits canoniques. Un par couple (sport, provider). Vit **uniquement** dans `axon-sports-data-gateway`.

---

## Enveloppes et horodatages

**CanonicalEnvelope** — Structure de transport de la gateway. Contient le payload (faits canoniques), sa provenance, ses horodatages, sa qualité, sa fraîcheur, son `schema_version`. Évolution de `DataEnvelope` (v1).

**event_time** — Heure réelle de l'événement décrit (coup d'envoi, début du match).

**published_time** — Heure à laquelle le provider a publié ou mis à jour l'information, quand il la fournit.

**available_to_model_time** — **Le champ de référence du walk-forward.** Heure à partir de laquelle cette information était réellement utilisable par un modèle. Toute prédiction backtestée à un instant T ne doit utiliser que des données dont `available_to_model_time ≤ T`. Voir `ADR-004`.

**fetched_at** — Instant de l'appel réseau côté Axon. Mesure l'âge du **cache**, pas l'âge de l'information.

**ingested_at** — Instant d'écriture dans le point-in-time store.

**data_quality** — 0.0–1.0. Confiance dans l'**exactitude et la complétude** de la donnée pour ce couple (provider, data_type). *Ne mesure pas* la confiance dans un résultat sportif.

**freshness_score** — 0.0–1.0. Calculé à partir de `reference_time − effective_data_time`, où `effective_data_time` = `published_time` si disponible, sinon `event_time`. **Jamais depuis `fetched_at`** : une donnée récupérée à l'instant peut décrire un classement vieux de trois jours.

**stale** — Booléen. La donnée provient du dernier snapshot connu, aucun provider n'ayant pu répondre. Le consommateur décide quoi en faire (typiquement : `ABSTAIN`). Voir `ADR-011`.

**schema_version** — Version du schéma canonique d'un sport (ex. `"tennis/1.2"`). Une lecture sous version incompatible échoue explicitement. Voir `ADR-009`.

---

## Stockage

**Point-in-time store** — Stockage append-only, jamais purgé, source de vérité historique. Permet de rejouer l'état des données tel qu'il était à une date T. Clé de partition incluant `provider` et `fetched_at`.

**Operational cache** — Couche d'accès rapide **devant** les providers, avec TTL par type de donnée et purge possible. Ne génère jamais de donnée. **Purger le cache ne supprime jamais un snapshot du point-in-time store** — cycles de vie indépendants.

**fetch_event** — Trace de *chaque* appel provider (paramètres, `content_hash` obtenu, horodatage), écrite systématiquement. Permet l'audit et le suivi de quota.

**data_snapshot** — Payload canonique réel, écrit **uniquement** si son `content_hash` diffère du dernier connu. Évite d'accumuler des milliers de copies identiques.

---

## Providers et couverture

**Provider** — Source externe de données sportives (API-Sports, football-data.org…). Ne produit que du brut.

**ProviderCapabilities** — Ce qu'un provider sait servir pour un sport donné (fixtures, standings, lineups…), déclaré sans appel réseau.

**data_type** — Vocabulaire fermé des types de données : `FIXTURES`, `RESULTS`, `STANDINGS`, `TEAM_STATS`, `PLAYER_STATS`, `LINEUPS`, `INJURIES`, `RANKINGS`, `HEAD_TO_HEAD_RAW`, `SQUAD`.

**CoverageStatus** — `FULL` / `PARTIAL` / `ABSENT` / `UNVERIFIED`, pour une combinaison (provider, compétition, saison, data_type). Seuls `FULL` et `PARTIAL` sont utilisables en production. Voir `ADR-007`.

**verification_method** — `live_call` / `provider_docs` / `manual`. Seul `live_call` autorise l'activation d'une couverture : la documentation d'un provider ne suffit pas.

**Fallback chain** — Cascade de sélection de provider : critères d'éligibilité, puis départage hiérarchique. Déterministe et auditable. Voir `ADR-006`.

---

## Identité

**canonical_id** — Identifiant unique d'une entité dans tout Axon, au format `{entity_type}:{sport}:{scope}:{slug}` — ex. `player:tennis:atp:carlos_alcaraz`, `team:football:fra:psg`. Voir `ADR-008`.

**entity_type** — `team`, `player`, `pair` (double), `competition`, `venue`, et selon les sports `fighter`, `driver`. Deux types ne partagent jamais un espace de noms.

**identity_status** — `RESOLVED` / `UNRESOLVED` / `AMBIGUOUS` / `CONFLICT`. Une entité non résolue n'est **jamais** rattachée automatiquement par proximité de nom : elle part en file de revue manuelle.

**Identity resolver** — Traduit un `canonical_id` vers l'identifiant d'un provider (`resolve`) et inversement (`canonicalize`). `axon-betting-engine` et `axon-sports-data-gateway` partagent le même espace d'identités.

---

## Compétitions et événements

**Competition** — Identité d'une compétition (sport, pays, type, tier, statut). **Ne contient aucun identifiant provider** — la couverture est modélisée séparément. Voir `ADR-007`.

**competition_type** — `league`, `cup`, `continental_cup`, `tour_event`, `series`.

**CanonicalEvent** — Un événement pariable précis (un match, une rencontre, un combat), identifié indépendamment de tout bookmaker. Porte ses participants (avec rôles) et son `context`.

**EventContext** — Objet **typé et versionné** décrivant les conditions de l'événement, spécifique au sport : surface/best_of/indoor en tennis, innings/probable_pitchers en baseball. Remplace un champ `dict` libre.

**EventParticipant** — Un participant et son **rôle** dans l'événement : `home`/`away`, `player_a`/`player_b`, `starting_pitcher`. Le rôle est déclaré par le module sportif.

---

## Bookmaker

**BookmakerConnector** — Contrat d'accès au catalogue d'un bookmaker. Seul `winamax` est implémenté ; la structure `bookmakers/<nom>/` est multi-bookmaker dès le départ. Voir `ADR-012`.

**Bookmaker Registry** — Mapping `bookmaker_event_id ↔ canonical_event_id ↔ sport`. **Distinct** du Competition Registry, qui répond à une autre question (quel provider de stats couvre quoi).

**CanonicalMarket** — Un marché sur un événement : `market_type` + sélections possibles.

**market_type** — Vocabulaire canonique de marchés : `MATCH_WINNER`, `OVER_UNDER_2_5`, `BTTS`, `TOTAL_GAMES`, `SET_HANDICAP`, `RUN_LINE`, `MONEYLINE`…

**OddsSnapshot** — Une cote observée à un instant donné, pour une sélection d'un marché chez un bookmaker.

**Odds history** — Historique des cotes d'une sélection, de l'ouverture à la clôture. Le mouvement porte de l'information, pas seulement la cote courante.

**Closing line** — Dernière cote avant le début de l'événement. Référence de marché la plus efficiente disponible.

**Bookmaker margin (vig)** — Sur-round du bookmaker : la somme des probabilités implicites d'un marché dépasse 100 %. Doit être retirée avant tout calcul de valeur.

---

## Modèles et prédiction

**SportModule** — Module métier par sport, regroupant schéma canonique, normalizers, dérivés, validateurs (côté gateway) ou contexte, feature engineering, market models (côté betting-engine). Pas un adaptateur au sens GoF. Voir `ADR-005`.

**MarketModel** — Modèle de prédiction pour **un** couple `(sport, market_type)`. Un marché = un modèle, avec sa propre calibration et sa propre fiabilité. Voir `ADR-002`.

**EventFeatureSet** — Features au niveau de l'événement, structurées en trois groupes : `event_features` (surface, tour…), `participant_features` (par participant), `matchup_features` (ce qui n'existe qu'en relation : head-to-head, différentiel). Plus `missing_features`.

**MarketPrediction** — Sortie d'un `MarketModel` : `fair_probability`, intervalle `[low, high]`, `model_version`, `data_quality`, `calibration_status`, et `explanation` (non optionnel).

**PredictionExplanation** — Top features contributives, features manquantes, warnings, facteurs d'incertitude. Obligatoire. Voir `ADR-013`.

**DataReadiness** — Statut d'un marché : `SUPPORTED` (modèle validé et calibré) / `EXPERIMENTAL` (modèle existant, jamais en `BET`) / `INSUFFICIENT_DATA` (données manquantes pour cet événement précis) / `UNSUPPORTED` (aucun modèle).

**model_version** — Identifiant de version d'un modèle (`tennis_match_winner_v7`). Toute mise en production a une entrée dans l'experiment registry.

---

## Calibration et évaluation

**Walk-forward** — Backtest où chaque prédiction n'utilise que les données disponibles à son `point_in_time`. Rendu structurellement correct par `ADR-004`.

**Calibration** — Un modèle est calibré si, parmi les événements auxquels il attribue 60 %, environ 60 % se réalisent. Indépendant de la rentabilité.

**Brier score** — Erreur quadratique moyenne des probabilités prédites. Plus bas = meilleur.

**Log loss** — Pénalise fortement les prédictions confiantes et fausses.

**Calibration curve** — Probabilité prédite vs fréquence observée. La diagonale est l'idéal.

**Closing-line value (CLV)** — Écart entre la cote obtenue et la cote de clôture. Un CLV positif en moyenne est le signal le plus robuste qu'un modèle bat réellement le marché — plus fiable que le ROI à court terme.

**Drift detection** — Détection d'une dégradation de calibration dans le temps (le sport, les équipes ou le marché ont changé).

**Experiment Registry** — Historique de tous les modèles testés : version, parent, hypothèse, métriques, fenêtre d'évaluation, statut (`candidate`/`promoted`/`rejected`/`superseded`) et `decision_rationale`. Les modèles **rejetés** y restent : c'est souvent la trace la plus utile plus tard.

**model_reliability** — Fiabilité historique d'un `MarketModel`, issue de sa calibration. Un des seuils d'entrée pour émettre un `BET`.

---

## Décision et portefeuille

**Fair probability** — Probabilité estimée par le modèle, avant toute comparaison à une cote.

**Fair odds** — `1 / fair_probability`.

**Implied probability** — Probabilité implicite d'une cote, `1 / cote`, **avant** retrait de la marge bookmaker.

**Expected value (EV)** — `probabilité × cote − 1`. Calculée à la **borne basse** de l'intervalle de probabilité, jamais à la moyenne : un edge qui disparaît à la borne basse ne justifie pas un `BET`.

**Edge** — Avantage estimé sur le bookmaker, après retrait de la marge et prise en compte de l'incertitude.

**BET / WATCH / ABSTAIN** — Les trois décisions possibles. `ABSTAIN` est un résultat **valide**, pas un échec : ne pas recommander quand l'avantage n'est pas démontré est le comportement attendu. Voir `ADR-011`.

**Exposure** — Risque réel porté, agrégé par événement et par participant. Trois sélections sur le même match ne sont pas trois risques indépendants.

**Market correlation** — Corrélation entre sélections. Les corrélations **structurelles** (« 3-0 » implique « victoire ») sont déclarées par le module sportif ; les corrélations statistiques sont estimées sur l'historique.

**Bet ranking** — Classement final des opportunités, après application des contraintes d'exposition. Sortie visible de l'utilisateur.

---

## Conventions transverses

**Point-in-time discipline** — Aucune donnée postérieure à l'instant de décision ne doit entrer dans une prédiction ou un backtest. Voir `ADR-004`.

**Pas de fusion silencieuse** — Deux sources ne sont jamais fusionnées automatiquement. Chaque valeur conserve sa provenance, ses horodatages et sa qualité ; l'arbitrage est une décision explicite.

**Pas de donnée inventée** — Trois issues seulement : donnée fraîche, donnée `stale=True` explicite, ou échec typé. Jamais de valeur par défaut ni d'extrapolation. Voir `ADR-011`.

**HITL (Human In The Loop)** — Toute action à conséquence reste soumise à validation humaine. Pas de placement automatique de pari. Voir `ADR-014`.
