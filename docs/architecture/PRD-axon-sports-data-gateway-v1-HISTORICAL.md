# PRD — `axon-sports-data-gateway` v1 — **DOCUMENT HISTORIQUE**

> ## ⛔ Ne pas utiliser ce document pour définir l'architecture cible.
> **Il décrit uniquement l'état effectivement livré en v1.** Certaines règles, structures et responsabilités décrites ici ont été explicitement remplacées.
>
> Pour l'architecture cible : `000-vision.md`, puis `PRD-axon-sports-data-gateway-v2.md` et `PRD-axon-betting-engine.md`.

**Module parent :** Axon (`/home/kaine/Documents/projets-perso/ai-agent/`)
**Statut :** `IMPLEMENTED` + `VALIDATED_ON_REAL_DATA`
**Auteur :** Kaine
**Dernière mise à jour :** 24 juillet 2026

### Ce qui a changé depuis ce document

| Dans ce document (v1) | Remplacé par | Référence |
|---|---|---|
| `CanonicalPayload` | Contenu d'une `CanonicalEnvelope` versionnée (`schema_version`) | PRD v2 §5.1, `ADR-009` |
| Consommateur `axon-quant` / `axon-quant-calibration` | `axon-betting-engine` (modèles par marché, pas par sport) | `ADR-001`, `ADR-002` |
| Couche par sport informelle | `SportModule` formalisé (protocole + registre) | PRD v2 §6, `ADR-005` |
| `odds_provider.py` **dans** la gateway (Phase 5, jamais implémentée) | `bookmakers/` **dans** `axon-betting-engine` — les cotes ne sont plus une responsabilité de la gateway | `ADR-001`, `ADR-012` |
| Couverture provider binaire (saison disponible ou non) | Couverture par `(provider, compétition, saison, data_type)` | PRD v2 §7.2, `ADR-007` |
| `canonical_id` plat (`team:psg`) | Namespace typé `{entity_type}:{sport}:{scope}:{slug}` | PRD v2 §9.1, `ADR-008` |
| Numérotation d'exigences `F1`–`F13` | `GW-FR-001`… (convention unifiée) | `000-vision.md` §9 |

**Ce qui reste valable et sert de base à la v2** : le protocole provider (`RawProviderResponse`), la séparation normalizer / identity / quality, le point-in-time store append-only avec ses cinq horodatages, la séparation cache opérationnel / store historique, et la sélection hiérarchique de provider.

---

## 1. Contexte et problème

`axon-quant` a besoin de données sportives fraîches (forme récente, classements, confrontations) pour alimenter son moteur de probabilité Dixon-Coles. Le fournisseur actuel (API-Football, tier gratuit) bloque l'accès à la saison en cours (`season=2025`), la limitant aux saisons 2022-2024 — inutilisable pour du pari sportif en temps réel où la forme des équipes doit être récente.

Aucun fournisseur gratuit unique ne couvre à la fois : saison en cours + multi-sport + profondeur statistique suffisante + volume de requêtes confortable. La stratégie retenue est donc de **ne pas dépendre d'une seule source**, mais de construire une couche d'abstraction (`sports_data_gateway`) qui interroge plusieurs fournisseurs interchangeables, avec fallback automatique et traçabilité stricte de la provenance de chaque donnée.

### Pourquoi maintenant
- Bloque directement `recent_form()` et `standings_strength()`, donc bloque tout le moteur Dixon-Coles sur données réelles.
- Le PRD `axon-quant-calibration` prévoit un point-in-time data store avec traçabilité par source — cette gateway est le prérequis technique pour l'alimenter proprement.
- Risque de dérive si on code `axon-quant` directement contre un provider précis : migration coûteuse plus tard.

---

## 2. Objectifs

1. Fournir à `axon-quant` une API unique et stable pour récupérer fixtures, forme récente, classements et cotes, indépendamment du fournisseur réel derrière.
2. Permettre un fallback automatique entre providers quand l'un est indisponible, limité, ou ne couvre pas la saison demandée.
3. Garantir que chaque donnée retournée porte son `provider`, ses horodatages canoniques (`event_time`, `published_time`, `available_to_model_time`, `fetched_at`, `ingested_at`), ainsi qu'un `data_quality` et un `freshness_score` distincts, pour ne jamais fusionner silencieusement des sources hétérogènes.
4. Rester quasi-gratuit en phase de validation (stack de démarrage 100% free tier), avec un chemin clair vers un upgrade payant ciblé (un seul provider) si besoin, sans réécriture de `axon-quant`.

## 3. Non-objectifs

- Ne pas implémenter de scraping de sources non officielles dans la v1 (risque de fragilité + zone grise ToS) — seulement des APIs publiques documentées.
- Ne pas gérer le staking / la logique EV / Kelly (reste dans `axon-quant`).
- Ne pas construire d'UI de monitoring dans cette v1 (juste des logs structurés + un état interrogeable en CLI).
- Pas de support temps réel (live odds / live score) en v1 — uniquement pré-match et données de forme.
- **Précision de périmètre** : l'architecture (protocole, fallback, normalizers, identity_resolver) est conçue multi-sport dès la v1, mais l'implémentation et la certification effectives de la v1 se limitent au football (Ligue 1, Premier League en priorité). Les modèles canoniques pour d'autres sports (périodes NBA, sets de volley, manches de tennis, marchés spécifiques) ne sont pas construits tant qu'Axon ne s'étend pas réellement au-delà du football.

---

## 4. Architecture

### 4.1 Vue d'ensemble

```
axon-quant
   │  (ne manipule que des canonical_id)
   ▼
sports_data_gateway (API unique, stable)
   │
   ├── cache/
   │     └── operational_cache.py    (TTL, dédup, purge possible — PAS un provider)
   │
   ├── providers/
   │     ├── api_sports_provider.py        (payant à terme, principal)
   │     ├── thesportsdb_provider.py       (gratuit permanent, fallback)
   │     ├── football_data_org_provider.py (gratuit, saison en cours, football only)
   │     └── odds_provider.py              (séparé — Winamax + comparaison bookmakers)
   │
   ├── normalizers/
   │     ├── protocol.py
   │     ├── api_sports.py
   │     ├── football_data_org.py
   │     ├── thesportsdb.py
   │     └── canonical_models.py
   │
   └── core/
         ├── provider_protocol.py    (interface commune : RawProviderResponse, Capabilities)
         ├── provider_registry.py    (métadonnées : sports, endpoints, coût, quotas, doc)
         ├── identity_resolver.py    (mapping ID canonique ↔ ID par provider)
         ├── fallback_chain.py       (orchestration, provider_score, retry)
         ├── quality.py              (data_quality + freshness_score)
         └── point_in_time_store.py  (persistance horodatée, append-only, jamais purgée)
```

**Flux de données par requête :**

```
canonical_id → identity_resolver.resolve() → provider_id
    → Cache (hit ?) → si miss → Provider.fetch_*(provider_id) → RawProviderResponse
    → Normalizer (provider-spécifique) → CanonicalPayload
    → identity_resolver.canonicalize() (résout les entités reçues vers leur canonical_id)
    → quality.py (data_quality + freshness_score)
    → DataEnvelope → point_in_time_store.write() → Cache.write() → axon-quant
```

`identity_resolver` intervient donc à deux moments : en amont pour traduire le `canonical_id` fourni par `axon-quant` vers l'identifiant attendu par le provider ciblé, puis en aval pour canonicaliser les entités présentes dans la réponse normalisée.

Le cache est interrogé *avant* d'appeler un provider (il peut éviter la requête réseau entièrement), pas après — il ne "fournit" jamais de données lui-même, il accélère et déduplique les appels providers.

### 4.2 Principe directeur

> **Aucune donnée n'est jamais fusionnée silencieusement.** Chaque valeur retournée à `axon-quant` conserve `provider`, ses horodatages canoniques (`event_time`, `published_time`, `available_to_model_time`, `fetched_at`, `ingested_at`), et un `data_quality` distinct de sa fraîcheur. La fusion/arbitrage entre sources concurrentes est une décision explicite du consommateur (ou d'une couche de calibration dédiée), jamais un comportement caché de la gateway.

### 4.3 Contrat provider (`provider_protocol.py`)

Le provider transporte des données **brutes**, il ne construit jamais lui-même un `DataEnvelope` — cette responsabilité appartient à la gateway, après normalisation, résolution d'identité et scoring qualité :

```python
from typing import Protocol, runtime_checkable
from dataclasses import dataclass
from datetime import datetime

@dataclass(frozen=True)
class RawProviderResponse:
    payload: dict            # JSON brut du provider, non transformé
    provider: str
    fetched_at: datetime     # instant de l'appel réseau côté Axon
    request_metadata: dict   # endpoint appelé, paramètres, id de requête provider si dispo

@dataclass(frozen=True)
class ProviderCapabilities:
    fixtures: bool = False
    standings: bool = False
    recent_form: bool = False
    injuries: bool = False
    lineups: bool = False
    live: bool = False
    historical: bool = False

@runtime_checkable
class SportsDataProvider(Protocol):
    name: str
    supported_sports: list[str]
    query_cost: float  # coût estimé par requête (0.0 si gratuit) — un des facteurs du provider_score

    def capabilities(self, sport: str) -> ProviderCapabilities:
        """Ce que ce provider sait vraiment servir pour ce sport — le fallback peut
        arbitrer par endpoint, pas seulement par provider entier."""
        ...

    def is_available(self, sport: str, season: str) -> bool:
        """Vérifie sans requête coûteuse si ce provider peut répondre."""
        ...

    def fetch_league_fixtures(
        self, sport: str, provider_league_id: str, season: str,
        date_from: str | None = None, date_to: str | None = None,
    ) -> RawProviderResponse:
        """Récupération batch d'une compétition entière — voir §4.3quater,
        c'est l'appel privilégié plutôt que des requêtes équipe par équipe.
        provider_league_id est déjà résolu par identity_resolver.resolve() en amont
        (dans fallback_chain) — un provider ne reçoit jamais de canonical_id."""
        ...

    def fetch_standings(self, sport: str, provider_league_id: str, season: str) -> RawProviderResponse:
        ...

    def get_rate_limit_status(self) -> dict:
        """Requêtes restantes / reset time, pour arbitrer le fallback."""
        ...
```

Nommage explicite : `provider_league_id` (et `provider_team_id`, etc.) désigne toujours un identifiant spécifique à un provider, jamais un `canonical_id`. Seul le `fallback_chain` (via `identity_resolver.resolve()`) construit ces valeurs avant d'appeler un provider — aucun code applicatif d'`axon-quant` ne manipule jamais un identifiant provider directement, il ne connaît que des `canonical_id`.

Les providers de cotes (`odds_provider.py`) implémentent un contrat séparé (`OddsProvider`) car leur granularité (bookmaker, mouvement de ligne, boosts Winamax) diffère structurellement des stats sportives.

### 4.3bis DataEnvelope — timestamps canoniques

Un simple `fetched_at` ne suffit pas pour un backtest rigoureux : une donnée récupérée à l'instant peut décrire un classement vieux de trois jours, ou une composition republiée trois jours après le match. La gateway distingue donc plusieurs horodatages, alignés sur les mêmes concepts que `axon-quant-calibration` :

```python
@dataclass(frozen=True)
class DataEnvelope:
    payload: "CanonicalPayload"     # modèle canonique, déjà passé par le Normalizer + identity_resolver
    provider: str

    event_time: datetime | None          # heure réelle de l'événement décrit (coup d'envoi, etc.)
    published_time: datetime | None      # heure de publication/mise à jour par le provider (si fournie)
    available_to_model_time: datetime    # heure à partir de laquelle cette donnée était utilisable
                                          # par le moteur — LE champ de référence pour le walk-forward
    fetched_at: datetime                 # instant de l'appel réseau côté Axon (âge du cache, pas de l'info)
    ingested_at: datetime                # instant d'écriture dans le point_in_time_store

    data_quality: float      # 0.0–1.0 — confiance dans l'exactitude/complétude du provider pour cet endpoint
    freshness_score: float   # 0.0–1.0 — calculé à partir de (reference_time - effective_data_time),
                              # où effective_data_time = published_time si dispo, sinon event_time,
                              # PAS fetched_at (une donnée récupérée à l'instant peut décrire un
                              # classement vieux de 3 jours)
    stale: bool = False
```

`available_to_model_time` est le champ que `axon-quant-calibration` doit utiliser pour tout walk-forward : c'est la garantie qu'aucune donnée "du futur" (par rapport à un match backtesté) ne fuite dans le moteur.

### 4.3ter Normalizers — un adaptateur par provider

Pas un fichier unique `normalizer.py` (qui deviendrait vite un empilement de `if provider == ...`), mais un sous-package dédié :

```
normalizers/
├── protocol.py          (interface ProviderNormalizer commune)
├── api_sports.py
├── football_data_org.py
├── thesportsdb.py
└── canonical_models.py  (CanonicalPayload, structures partagées)
```

Chaque normalizer convertit un `RawProviderResponse` vers le modèle canonique (mêmes noms de champs, mêmes unités, mêmes formats de date), et fixe `event_time` / `published_time` à partir de ce que le provider fournit réellement. La responsabilité de normalisation reste centralisée dans la couche `normalizers/`, mais chaque provider a son propre adaptateur testable indépendamment.

### 4.3quater Identity Resolver — le chaînon manquant du fallback

API-Sports, TheSportsDB et football-data.org n'utilisent pas les mêmes identifiants pour les équipes, ligues, saisons ou matchs. Sans résolution d'identité, le fallback échoue silencieusement : un `team_id` valide pour le premier provider n'a aucune raison d'être valide pour le second — le système *a l'air* d'un fallback multi-provider mais n'en est pas vraiment un.

```python
@dataclass(frozen=True)
class CanonicalEntity:
    canonical_id: str                  # ex. "team:psg"
    canonical_name: str
    aliases: list[str]
    identities: dict[str, str]         # {"api_sports": "85", "football_data_org": "524", "thesportsdb": "133714"}
    valid_from: datetime | None = None

IdentityStatus = Literal["RESOLVED", "UNRESOLVED", "AMBIGUOUS", "CONFLICT"]
```

`identity_resolver.py` (dans `core/`) expose :

```python
class IdentityResolver(Protocol):
    def resolve(self, canonical_id: str, target_provider: str) -> str | None:
        """Traduit un ID canonique vers l'ID spécifique d'un provider."""
        ...

    def canonicalize(self, provider: str, provider_id: str, entity_type: str) -> tuple[str | None, IdentityStatus]:
        """Traduit un ID provider vers l'ID canonique Axon, avec un statut explicite
        plutôt qu'un simple None sans contexte."""
        ...
```

**Comportement sur entité non résolue** : une entité reçue d'un provider mais absente du registre (`UNRESOLVED`), ou correspondant à plusieurs candidats (`AMBIGUOUS`), ou en conflit avec un mapping existant (`CONFLICT`) ne produit **jamais** de rattachement automatique par proximité de nom. Elle doit :
- être écartée de la donnée servie à `axon-quant` (jamais associée automatiquement au nom le plus proche) ;
- être placée dans une file de revue manuelle (`identity_review_queue`) ;
- produire un log structuré (provider, ID brut, type d'entité, statut) pour investigation.

`axon-quant` ne manipule jamais que des `canonical_id`. C'est le rôle de la gateway (via l'`identity_resolver`) de traduire vers l'ID attendu par chaque provider avant l'appel, et de canonicaliser les entités reçues dans les réponses. Le registre d'identités est alimenté manuellement au démarrage pour les ligues/équipes suivies (Ligue 1, Premier League, etc.), avec un mécanisme d'ajout progressif — pas de résolution automatique par nom en v1 (trop fragile, ex. "PSG" vs "Paris SG").

### 4.3quinquies Récupération batch plutôt que endpoint par équipe

Avec des free tiers à 10-100 req/jour, appeler `recent_form(team_id)` équipe par équipe épuise vite le quota. Les providers exposent donc des endpoints batch par compétition (`fetch_league_fixtures`), et `recent_form()` / `standings_strength()` deviennent des **services dérivés internes**, calculés localement à partir du `canonical match store` alimenté par ces fetches batch — pas des endpoints demandés directement à chaque provider :

```
Provider.fetch_league_fixtures() → Normalizer → Canonical match store → recent_form() / standings_strength()
```

Ça réduit la consommation de quota, et garantit que la définition de "forme récente" est identique quel que soit le provider ayant fourni les matchs bruts.

### 4.3sexies Provider Registry

`provider_registry.py` centralise les métadonnées déclaratives de chaque provider (nom, version, sports couverts, endpoints disponibles, `query_cost`, quotas, lien doc). Le `fallback_chain.py` lit ce registre plutôt que de dépendre d'une liste écrite à la main — ajouter un provider revient à l'enregistrer ici, pas à modifier la logique de fallback.

### 4.4 Fallback chain

Ordre de priorité configurable par sport, avec règle explicite de sortie :

```python
FALLBACK_ORDER = {
    "football": ["football_data_org", "api_sports", "thesportsdb"],
    "basketball": ["api_sports", "thesportsdb"],
    # extensible par sport — le recours au dernier snapshot du point-in-time store
    # est une étape finale gérée par fallback_chain, pas une entrée de ce registre
}
```

Règles de fallback :
1. Si `is_available(sport, season)` renvoie `False` (ex: saison bloquée par le tier) → passer au provider suivant sans consommer de requête.
2. Si `capabilities(sport)` indique que l'endpoint demandé n'est pas couvert → passer directement au provider suivant qui le couvre (fallback par endpoint, pas seulement par provider entier).
3. Si rate limit atteint → passer au suivant, logguer un warning.
4. **Sélection v1 — hiérarchique et déterministe**, plutôt qu'un score composite dont les facteurs ne sont pas encore calibrés sur données réelles :

   ```
   1. capability obligatoire présente
   2. saison disponible
   3. data_quality ≥ seuil minimal configuré
   4. freshness_score ≥ seuil minimal configuré
   5. quota disponible
   6. priorité configurée (ordre déclaré dans provider_registry, ex. FALLBACK_ORDER)
   7. query_cost le plus bas
   8. latence historique la plus basse
   ```

   Chaque critère élimine ou départage les candidats restants, dans cet ordre exact — auditable et prévisible. Un `provider_score` composite (`coverage × data_quality × freshness × quota_health − cost − latency_penalty`) reste une évolution envisageable une fois qu'on dispose de données réelles pour calibrer les poids de chaque facteur, mais n'est pas retenu pour la v1.
5. Si tous les providers échouent → lire la dernière entrée connue du `point_in_time_store` via la couche `Cache`, renvoyer avec `stale=True`, jamais une exception silencieuse — `axon-quant` doit pouvoir décider de ne pas parier (ABSTAIN) faute de donnée fraîche.

### 4.5 Point-in-time data store vs Cache — deux couches, deux politiques distinctes

- **`point_in_time_store`** : la source de vérité persistante. Stockage append-only (jamais d'update en place, jamais de suppression) — chaque fetch crée une nouvelle entrée horodatée, conservée indéfiniment. Clé de partition : `(sport, entity_id, endpoint, provider, fetched_at)`. Permet de rejouer l'état des données "tel qu'il était" à une date T (important pour le futur backtesting de `axon-quant-calibration`).
- **`Cache`** : une couche d'accès rapide opérationnelle devant les providers, avec sa propre politique (TTL par type de donnée : fixtures valides 24h, blessures valides 1h, etc.), dédoublonnage, et purge possible des entrées expirées. Le cache décide *si* un nouvel appel provider est nécessaire — il ne génère jamais de donnée lui-même.
- **Ces deux politiques sont indépendantes** : l'expiration d'une entrée de cache ne doit jamais entraîner la suppression de son snapshot dans le `point_in_time_store`. Le cache peut être vidé/reconstruit sans perte d'historique ; le store, lui, ne perd jamais rien. Cette règle est reprise explicitement en exigence non-fonctionnelle (§7).
- Format initial : SQLite ou fichiers Parquet locaux (à trancher en phase d'implémentation — cf. section 8).

**Idempotence — éviter la duplication de payloads identiques.** Un même fetch peut être répété plusieurs fois sans que la donnée sous-jacente ait changé (ex. polling périodique d'une compétition entre deux journées). Sans mécanisme dédié, le store accumulerait des milliers de snapshots identiques. Le store sépare donc deux notions :

- **`fetch_event`** : trace *chaque* appel provider (audit complet — quand, quel provider, quels paramètres, `content_hash` du payload obtenu), écrit à chaque fetch sans exception.
- **`data_snapshot`** : le payload canonique réel, écrit uniquement si son `content_hash` diffère du dernier snapshot connu pour cette même clé de partition.

```python
@dataclass(frozen=True)
class FetchEvent:
    provider: str
    endpoint: str
    request_fingerprint: str   # hash des paramètres de requête
    content_hash: str          # hash du payload normalisé obtenu
    fetched_at: datetime
    resulted_in_new_snapshot: bool
```

Ça donne une traçabilité complète de chaque appel (utile pour le monitoring de quota et le debug) sans dupliquer les gros payloads identiques dans `data_snapshot`.

---

## 5. Stack de providers (v1)

| Provider | Rôle | Coût | Couverture saison actuelle |
|---|---|---|---|
| API-Sports | Principal, large catalogue multi-sport | Free (100 req/j) → payant si besoin (19$/mois football, ~15$/mois autres sports) | Non garanti en free |
| TheSportsDB | Fallback multi-sport | Free permanent (30 req/min) | Souvent oui, données limitées |
| football-data.org | Fallback football, saison en cours | Free permanent (10 req/min, 12 compétitions) | Oui |
| odds_provider (Winamax) | Cotes, EV, comparaison bookmakers | Séparé de la stack sportive | N/A |

*Le dernier snapshot connu (`point_in_time_store` via `Cache`) n'est pas listé ici : ce n'est pas un provider, c'est le recours final du `fallback_chain` quand aucun provider ne répond (cf. §4.4).*

**Point d'attention validé à corriger dans le code** : un abonnement payant API-Sports est par sport, pas global. Le module de config doit permettre d'activer le payant sport par sport sans redéploiement global.

---

## 6. Exigences fonctionnelles

| # | Exigence | Priorité |
|---|---|---|
| F1 | La gateway expose une seule API pour `axon-quant`, sans exposer les détails internes de fallback | Must |
| F2 | Chaque réponse inclut `provider`, les horodatages canoniques (`event_time`, `published_time`, `available_to_model_time`, `fetched_at`, `ingested_at`), `data_quality`, `freshness_score` | Must |
| F3 | Fallback automatique et transparent en cas d'indisponibilité (saison, rate limit, capability manquante, erreur réseau) | Must |
| F4 | Configuration de l'ordre de fallback par sport (issue du `provider_registry`), éditable sans toucher au code | Must |
| F5 | Persistance point-in-time (append-only, jamais purgée) de toutes les données récupérées, via une couche `Cache` opérationnelle distincte, elle purgeable | Must |
| F6 | CLI/commande de diagnostic (`axon sports-status`) affichant l'état de chaque provider (dispo, capabilities, quota restant, dernière erreur) | Should |
| F7 | Le provider odds reste strictement séparé des providers stats (pas de mélange dans le même appel) | Must |
| F8 | Logging structuré (JSON) de chaque décision de fallback (raison, critère de sélection déclenché, provider choisi), pour audit ultérieur | Should |
| F9 | Possibilité d'ajouter un nouveau provider en implémentant `SportsDataProvider` + son normalizer + une entrée `provider_registry`, sans modifier `axon-quant` | Must |
| F10 | Chaque provider expose `capabilities()` ; le fallback peut arbitrer par endpoint, pas seulement par provider entier | Must |
| F11 | Chaque provider a son propre normalizer dans `normalizers/`, testable indépendamment ; aucune logique `if provider == ...` centralisée | Must |
| F12 | `axon-quant` ne manipule que des `canonical_id` ; l'`identity_resolver` traduit vers/depuis les identifiants spécifiques à chaque provider | Must |
| F13 | Les endpoints de récupération sont batch par compétition (`fetch_league_fixtures`) ; `recent_form()`/`standings_strength()` sont calculés localement depuis le canonical match store, pas requêtés provider par provider | Must |

## 7. Exigences non-fonctionnelles

- **Résilience** : aucune exception non gérée ne doit remonter jusqu'à `axon-quant` — toujours retourner une `DataEnvelope` (éventuellement `stale=True`) ou lever une exception typée explicite (`NoDataAvailableError`).
- **Coût** : stack de démarrage doit rester $0/mois tant que le volume de requêtes le permet.
- **Latence** : le fallback chain ne doit pas ajouter plus de 2-3s de latence perçue en cas de cascade complète (timeouts courts par provider, ex. 3s max).
- **Testabilité** : chaque provider mockable indépendamment pour les tests de `axon-quant` sans dépendre du réseau.
- **Rétention** : l'expiration ou la purge d'une entrée du `Cache` opérationnel ne doit jamais supprimer le snapshot correspondant dans le `point_in_time_store` — les deux couches ont des cycles de vie indépendants.

---

## 8. Décisions techniques ouvertes

1. **Stockage point-in-time** : SQLite local (simple, déjà dans l'écosystème Axon) vs Parquet (meilleur pour l'analytique future / calibration). *Recommandation initiale : SQLite pour la v1, migration Parquet si le volume grossit.*
2. **Scoring de `data_quality`** : statique par (provider, endpoint) au départ, ou dynamique basé sur l'historique de calibration ? *v1 : statique, table de config dans `provider_registry`.*
3. **Calcul du `freshness_score`** : fonction de décroissance basée sur `reference_time - effective_data_time` (où `effective_data_time` = `published_time` si disponible, sinon `event_time` — jamais `fetched_at` seul). Demi-vie à définir par type de donnée (fixtures vs blessures). *v1 : table de demi-vies simples par endpoint, affinable plus tard.*
4. **Rate limiting local** : faut-il un compteur local par provider (pour anticiper le 429 avant qu'il arrive) ou se fier uniquement aux réponses API ? *Recommandé : compteur local + resync périodique via `get_rate_limit_status()`.*
5. **Sources officielles par sport** (NBA/NHL/MLB/NFL) mentionnées comme complément : hors scope v1, à réévaluer si Axon s'étend réellement au-delà du football.
6. **Portée du projet** : cette architecture (protocole, fallback, normalizers, identity_resolver, point-in-time, cache) est suffisamment générique pour devenir un package autonome réutilisable au-delà d'Axon. *Décision : rester un module interne pour la v1 ; réévaluer l'extraction en package séparé une fois validé en usage réel sur `axon-quant`.*
7. **Alimentation initiale de l'`identity_resolver`** : mapping manuel au démarrage pour les ligues/équipes suivies (pas de résolution automatique par nom, trop fragile — ex. "PSG" vs "Paris SG"). À enrichir progressivement à mesure que de nouvelles compétitions sont ajoutées.
8. **`provider_score` composite** : différé après la v1 (sélection hiérarchique déterministe retenue à la place, cf. §4.4). À reconsidérer une fois que des données réelles d'usage permettent de calibrer correctement les poids relatifs de coverage/quality/freshness/coût/latence.

---

## 9. Plan d'implémentation (proposé)

**Point de départ recommandé — tranche verticale étroite, un seul provider de bout en bout :**

```
Ligue 1 → football_data_org_provider → normalizers/football_data_org.py
   → identity_resolver (mapping Ligue 1 uniquement) → point_in_time_store (SQLite)
   → recent_form() calculé localement → consommation par axon-quant
```

Ne pas développer les trois providers en parallèle. Un premier provider fonctionnel de bout en bout valide les contrats (protocole, normalizer, identity_resolver, store) ; le deuxième provider (`api_sports`) prouve ensuite que l'abstraction et le fallback fonctionnent réellement, pas seulement en théorie.

**Phase 1 — Fondations**
- `provider_protocol.py` (interface + `RawProviderResponse` + `ProviderCapabilities`)
- `normalizers/canonical_models.py` (`CanonicalPayload` et structures partagées)
- `identity_resolver.py` (structure + mapping manuel initial pour les ligues/équipes suivies)
- `point_in_time_store.py` (SQLite, append-only) + `cache/operational_cache.py` (TTL par endpoint, purgeable indépendamment)
- `provider_registry.py` (structure vide, prête à être peuplée)

**Phase 2 — Providers réels**
- `football_data_org_provider.py` (débloque immédiatement la saison en cours en gratuit)
- `api_sports_provider.py` (refactor de l'existant pour respecter le protocole + `capabilities()`)
- `thesportsdb_provider.py`
- `normalizers/api_sports.py`, `normalizers/football_data_org.py`, `normalizers/thesportsdb.py` (un adaptateur par provider)
- Endpoints batch (`fetch_league_fixtures`) en priorité sur les endpoints par équipe

**Phase 3 — Orchestration**
- `fallback_chain.py` (sélection hiérarchique v1 : capability → saison → data_quality → freshness → quota → priorité → coût → latence) + config par sport dans `provider_registry`
- `quality.py` (data_quality statique + calcul freshness_score basé sur `effective_data_time`)
- Service dérivé `recent_form()` / `standings_strength()` calculé depuis le canonical match store
- Intégration dans `axon-quant` (remplacement des appels directs à API-Football, migration vers `canonical_id`)

**Phase 4 — Observabilité**
- CLI `axon sports-status`
- Logging structuré des décisions de fallback (raison, provider_score, provider choisi)

**Phase 5 — Cotes (parallèle, indépendant)**
- `odds_provider.py` dédié Winamax + comparaison bookmakers

---

## 10. Critères de succès

- `recent_form()` et `standings_strength()` fonctionnent sur la saison 2025-2026 sans dépendre d'un upgrade payant immédiat.
- Ajout d'un nouveau sport ou provider ne nécessite aucune modification de `axon-quant`.
- Aucune donnée utilisée par le moteur Dixon-Coles n'est utilisée sans que sa provenance et sa fraîcheur soient connues.
- Chemin d'upgrade payant (provider unique, sport par sport) documenté et sans réécriture.

## 11. Risques

| Risque | Impact | Mitigation |
|---|---|---|
| football-data.org limite à 12 compétitions | Manque de couverture ligues mineures | Fallback vers TheSportsDB, ou dernier snapshot du `point_in_time_store`, ou upgrade payant ciblé |
| Rate limits cumulés (10 req/min, 30 req/min, 100 req/j) insuffisants en usage réel | Fallback en cascade trop fréquent, latence | Cache agressif côté gateway (TTL par type de donnée), monitoring F6 |
| Divergence de schéma entre providers (même donnée, format différent) | Bugs silencieux dans `axon-quant` | Normalizer dédié par provider dans `normalizers/`, tests de contrat par provider contre `canonical_models.py` |
| API-Sports change ses règles de tier gratuit sans préavis | Casse `is_available()` | Vérification explicite documentée en §4.4 point 1, alerte si comportement inattendu |
| Un `team_id`/`league_id` mal résolu entre providers | Fallback silencieusement cassé (mauvaise équipe/mauvaise donnée servie) | `identity_resolver` obligatoire, `axon-quant` ne manipule jamais d'ID brut de provider, tests sur les mappings connus |
