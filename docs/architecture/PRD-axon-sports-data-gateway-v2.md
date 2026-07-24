# PRD — `axon-sports-data-gateway` v2
## Socle d'extension multi-sport et registre multi-compétition

**Module parent :** Axon (`/home/kaine/Documents/projets-perso/ai-agent/`)
**Étend :** `axon-sports-data-gateway` v1 (livré et validé — football, Ligue 1 + Premier League)
**Consommé par :** `axon-betting-engine` (cf. `PRD-axon-betting-engine.md`), qui dépend de cette gateway sans jamais la modifier
**Statut :** Draft
**Auteur :** Kaine
**Dernière mise à jour :** 24 juillet 2026

> **Ce que cette v2 livre exactement** : un socle d'extension (contrat `SportModule`, enveloppe versionnée, registres séparés) et un registre déclaratif de compétitions, plus **deux sports supplémentaires** livrés selon le rollout §11. Ce n'est pas un engagement à supporter immédiatement tous les sports cités dans les discussions préparatoires.

---

## 1. Contexte et problème

La v1 est livrée et validée : football uniquement, Ligue 1 + Premier League, 38 équipes mappées, pipeline vérifié bout en bout (`recent_form`, `standings_strength`, fallback, point-in-time store).

**Ce que la v1 permet déjà** : `provider_protocol`, `fallback_chain`, `identity_resolver`, `point_in_time_store` et `operational_cache` ne contiennent aucune logique football-spécifique.

**Ce qui ne tient plus à l'échelle multi-sport** — quatre hypothèses implicites de la v1 :

1. **Un seul modèle canonique.** Un match de tennis (sets, breaks, surface), une rencontre MLB (manches, pitcher partant) et un match de football (buts, cartons) n'ont pas de structure commune exploitable. Forcer un payload universel produirait un modèle qui ne colle correctement à aucun sport.
2. **Un registre de compétitions codé en dur.** `FALLBACK_ORDER` par sport + IDs de ligue en dur ne passe pas à l'échelle sur des dizaines de compétitions, plusieurs pays et plusieurs niveaux.
3. **Une couverture provider binaire.** La v1 raisonne « ce provider couvre-t-il cette saison ? ». En réalité un provider peut couvrir les résultats d'une compétition mais pas ses compositions, ses blessures ou ses statistiques détaillées — et cette couverture peut varier d'une saison à l'autre.
4. **Un espace de noms d'identité plat.** Avec un seul sport et un seul type d'entité (équipe), `team:psg` suffisait. Avec joueurs, paires de double, combattants, pilotes, tournois et lieux, un espace de noms non typé produira des collisions — la v1 en a déjà rencontré une (équipe Wolves et ligue Premier League partageant l'ID API-Sports `39`).

### Frontière avec `axon-betting-engine`

Cette gateway **s'arrête aux faits canoniques et aux datasets dérivés**. Elle ne produit jamais de features de modèle ni de probabilités. La chaîne complète est :

```
Provider data → Canonical facts → Derived datasets  │  → Model features → Market models
        ─────── axon-sports-data-gateway ───────    │   ─── axon-betting-engine ───
```

Sans cette frontière, la gateway deviendrait progressivement un feature engine déguisé (cf. §5.3 et risque §12).

---

## 2. Objectifs

1. Permettre l'ajout d'un sport sans modifier le cœur générique (`core/`, `cache/`, `point_in_time_store`), via un contrat `SportModule` explicite et testable.
2. Versionner les schémas canoniques, pour qu'une évolution du modèle tennis ne casse pas silencieusement les consommateurs ni les historiques déjà stockés.
3. Remplacer le registre de compétitions codé en dur par un registre déclaratif, avec une modélisation de couverture provider **par saison et par type de donnée**.
4. Typer l'identité canonique par sport et par type d'entité, pour rendre les collisions structurellement impossibles.
5. Rendre la sélection de provider et le déclenchement du fallback **déterministes et auditables**, sans décision implicite.
6. Livrer deux sports supplémentaires (tennis, puis baseball) validant que le socle généralise réellement, sans régression sur le football existant.

## 3. Non-objectifs

- Ne pas produire de features de modèle, de probabilités ou de recommandations — c'est le périmètre de `axon-betting-engine`.
- Ne pas viser une couverture exhaustive « tout le sport mondial » dans cette v2. Le socle doit le permettre ; le remplissage est piloté par l'usage réel.
- Ne pas garantir a priori la couverture d'une compétition donnée (Coupe de Lituanie, tournois ATP mineurs, NPB) — toute couverture doit être vérifiée par appel réel avant activation (§7.3).
- Ne pas supporter le temps réel (live scores, live odds) — pré-match uniquement, comme en v1.
- Ne pas construire les calculateurs dérivés de chaque sport dans cette v2 au-delà de ce qu'exigent les sports livrés au rollout (§11).

---

## 4. Architecture

### 4.1 Ce qui ne change pas

```
core/
  ├── provider_protocol.py      (RawProviderResponse, ProviderCapabilities) — inchangé
  ├── provider_registry.py      — inchangé
  ├── fallback_chain.py         — logique de sélection précisée (§8), structure inchangée
  ├── identity_resolver.py      — étendu au typage multi-sport (§9), contrat de base inchangé
  ├── quality.py                — inchangé
  └── point_in_time_store.py    (append-only, fetch_event / data_snapshot) — inchangé
cache/
  └── operational_cache.py      — inchangé
providers/
  ├── api_sports_provider.py
  └── football_data_org_provider.py
```

### 4.2 Ce qui s'ajoute

```
sports_data_gateway/
   ├── core/                          (ci-dessus + extensions §9)
   ├── cache/                         (inchangé)
   ├── providers/                     (inchangé dans leur contrat)
   │
   ├── registries/                    NOUVEAU
   │     ├── competition_registry.py          identité des compétitions (§7.1)
   │     ├── provider_coverage_registry.py    couverture par provider × compétition × saison × data_type (§7.2)
   │     └── coverage_verification.py         procédure de vérification par appel réel (§7.3)
   │
   ├── canonical/                     NOUVEAU
   │     ├── envelope.py                      CanonicalEnvelope versionnée (§5.1)
   │     └── data_types.py                    vocabulaire des data_type (§5.2)
   │
   └── sports/                        NOUVEAU — un dossier par sport
         ├── registry.py                      SPORT_MODULES: dict[str, SportModule] (§6.2)
         ├── football/
         │     ├── module.py                  implémente SportModule
         │     ├── canonical_facts.py         faits canoniques football (§5.3)
         │     ├── derived.py                 datasets dérivés (recent_form, standings_strength)
         │     └── normalizers/               (migrés depuis la v1, déplacement pur)
         ├── tennis/
         │     ├── module.py
         │     ├── canonical_facts.py
         │     ├── derived.py
         │     └── normalizers/
         └── baseball/
               └── ... (même structure)
```

**Contrainte structurelle** : ajouter un sport = ajouter un dossier `sports/<sport>/` + une entrée dans `sports/registry.py`. Aucune modification de `core/` ou `cache/`. C'est la contrainte de non-régression principale (GW-FR-001, §10).

---

## 5. Le contrat de données

### 5.1 `CanonicalEnvelope` — évolution versionnée de `DataEnvelope` (v1)

La v1 a livré `DataEnvelope`, déjà implémenté et validé sur données réelles. La v2 ne crée pas un concept parallèle : elle **étend** cette structure avec les champs rendus nécessaires par le multi-sport. Les champs v1 sont conservés à l'identique, ce qui rend la migration additive.

```python
@dataclass(frozen=True)
class CanonicalEnvelope:
    # --- Identité de la donnée (NOUVEAU en v2) ---
    canonical_id: str                    # entité concernée, typée (§9)
    sport: str
    competition_id: str | None           # référence competition_registry ; None si hors compétition
    season: str | None                   # obligatoire dès qu'une compétition est concernée —
                                          # nécessaire au scoping du fallback stale (§8.4)
    data_type: str                       # vocabulaire fermé, cf. §5.2
    schema_version: str                  # version du schéma canonique du sport (ex. "tennis/1.2")

    # --- Payload (structure propre au sport, opaque pour core/) ---
    payload: object                      # instance d'un canonical_facts.* du sport concerné

    # --- Provenance (v1, conservé ; provider_entity_id NOUVEAU) ---
    provider: str
    provider_entity_id: str | None       # ID natif chez le provider, pour audit/retour arrière

    # --- Horodatages point-in-time (v1, conservés à l'identique) ---
    event_time: datetime | None
    published_time: datetime | None
    available_to_model_time: datetime    # référence du walk-forward
    fetched_at: datetime
    ingested_at: datetime

    # --- Qualité (v1, conservé) ---
    data_quality: float
    freshness_score: float
    stale: bool = False
```

**Pourquoi `schema_version` est critique** : sans lui, faire évoluer le modèle tennis rend les snapshots historiques déjà stockés silencieusement incompatibles avec le code de lecture — ce qui casse précisément le backtesting walk-forward que le `point_in_time_store` existe pour permettre. Toute lecture du store doit vérifier la compatibilité de `schema_version` et refuser explicitement plutôt que d'interpréter un ancien payload avec un nouveau schéma.

**Migration depuis la v1** : les snapshots football existants sont réécrits une fois avec `sport="football"`, `data_type` déduit de l'endpoint d'origine, et `schema_version="football/1.0"`. Migration ponctuelle, scriptée, vérifiée (cf. critères d'acceptation §13).

### 5.2 Vocabulaire fermé des `data_type`

`data_type` n'est pas une chaîne libre — c'est le vocabulaire partagé par le `provider_coverage_registry` (§7.2), le `fallback_chain` (§8) et les consommateurs :

```
FIXTURES · RESULTS · STANDINGS · TEAM_STATS · PLAYER_STATS
LINEUPS · INJURIES · RANKINGS · HEAD_TO_HEAD_RAW · SQUAD
```

Un sport n'a pas à supporter tous les types (`SportModule.supported_data_types()`, §6.1). `RANKINGS` est pertinent en tennis et pas en football de clubs ; `LINEUPS` l'est au football et au baseball (lineup + pitcher partant).

### 5.3 Trois niveaux distincts : faits, dérivés, features

La v1 mélangeait implicitement ces niveaux. Le retour d'architecture l'a relevé à juste titre : `surface` (fait événementiel), `ranking` (snapshot temporel), `head_to_head` (calcul dérivé) et `service_hold_pct` (agrégat sur fenêtre) n'ont pas la même nature et ne peuvent pas vivre au même endroit.

| Niveau | Contenu | Où | Versionné par |
|---|---|---|---|
| **Canonical facts** | Ce que le provider affirme, normalisé, non transformé : un match a eu lieu, tel score, telle surface, tel classement à telle date | `sports/<sport>/canonical_facts.py`, stocké dans le `point_in_time_store` | `schema_version` |
| **Derived datasets** | Agrégats déterministes calculés à partir des faits : forme sur N matchs, head-to-head, hold/break % sur fenêtre, force d'attaque/défense | `sports/<sport>/derived.py`, recalculable à tout instant depuis les faits | version du calculateur, exposée dans la sortie |
| **Model features** | Ce qu'un modèle consomme : Elo par surface, indicateurs de fatigue, features normalisées/encodées | **`axon-betting-engine`** — hors de cette gateway | `feature_set_version` (côté betting-engine) |

**Règle** : un dérivé doit être une fonction pure et déterministe des faits canoniques + une fenêtre temporelle. S'il nécessite un paramètre d'entraînement, un modèle, ou une pondération apprise, ce n'est pas un dérivé — c'est une feature, et il appartient à `axon-betting-engine`. Cette règle est le garde-fou contre la dérive « gateway → feature engine caché ».

---

## 6. `SportModule` — contrat formel

### 6.1 Protocole

La v1 laissait cette couche à l'état de convention de dossier. Elle est ici formalisée, pour que « le sport X est-il installé et utilisable ? » soit une question à réponse programmatique.

```python
from typing import Protocol

class SportModule(Protocol):
    sport: str
    schema_version: str                          # version courante du schéma canonique de ce sport

    def supported_data_types(self) -> set[str]:
        """Sous-ensemble du vocabulaire §5.2 réellement modélisé par ce sport."""
        ...

    def normalizers(self) -> dict[str, "Normalizer"]:
        """{provider_name: normalizer} — quel adaptateur convertit le RawProviderResponse
        de quel provider vers les canonical_facts de ce sport."""
        ...

    def validate_payload(self, payload: object, data_type: str) -> None:
        """Lève une exception typée si le payload ne respecte pas le schéma canonique
        courant du sport. Appelé systématiquement avant écriture dans le store."""
        ...

    def entity_types(self) -> set[str]:
        """Types d'entités que ce sport manipule : {"team"}, {"player", "pair"},
        {"team", "player"}... Utilisé par l'identity_resolver typé (§9)."""
        ...

    def derived_calculators(self) -> dict[str, "DerivedCalculator"]:
        """Datasets dérivés disponibles pour ce sport (§5.3), nommés et versionnés."""
        ...

    def is_schema_compatible(self, stored_schema_version: str) -> bool:
        """Un snapshot stocké sous une ancienne version est-il lisible par le code courant ?
        Permet un refus explicite plutôt qu'une interprétation silencieusement erronée."""
        ...
```

### 6.2 Registre des modules sportifs

```python
# sports/registry.py
SPORT_MODULES: dict[str, SportModule] = {
    "football": FootballModule(),
    "tennis": TennisModule(),
    "baseball": BaseballModule(),
}

def get_sport_module(sport: str) -> SportModule:
    """Lève UnsupportedSportError si le sport n'est pas installé — jamais de None silencieux."""
```

`core/` n'importe jamais un module sportif concret : il passe toujours par `get_sport_module(sport)`. C'est ce qui garantit GW-FR-001 (ajout d'un sport sans toucher au cœur) et la résilience par sport (NFR §10.2 : un module défaillant n'interrompt pas les autres).

---

## 7. Registres — identité, couverture, vérification

### 7.1 `Competition` — identité seule

Le registre v2 initial mélangeait dans un même objet l'identité de la compétition, les IDs externes et la couverture provider. Ces trois choses ont des cycles de vie différents (une compétition existe indépendamment du fait qu'un provider la serve, et sa couverture change d'une saison à l'autre). Elles sont donc séparées.

```python
@dataclass(frozen=True)
class Competition:
    canonical_id: str                    # ex. "competition:tennis:atp:cincinnati"
    sport: str
    name: str
    country_code: str | None             # ISO 3166-1 alpha-2 ; None si international
    competition_type: Literal["league", "cup", "continental_cup", "tour_event", "series"]
    tier: int | None                     # niveau national (1 = élite) quand la notion s'applique
    status: Literal["draft", "active", "deprecated"]
```

Aucun ID provider ici. Aucun score de couverture ici.

### 7.2 `ProviderCompetitionCoverage` — couverture par saison et par type de donnée

```python
class CoverageStatus(Enum):
    FULL = "FULL"
    PARTIAL = "PARTIAL"
    ABSENT = "ABSENT"
    UNVERIFIED = "UNVERIFIED"

@dataclass(frozen=True)
class ProviderCompetitionCoverage:
    provider: str
    competition_id: str
    provider_competition_id: str         # ID natif chez ce provider
    season: str                          # granularité obligatoire (§7.4)
    data_type: str                       # vocabulaire §5.2
    status: CoverageStatus
    verified_at: datetime
    verification_method: Literal["live_call", "provider_docs", "manual"]
    historical_depth_years: int | None
    notes: str | None = None
```

La clé est **(provider, competition_id, season, data_type)**. C'est ce qui permet d'exprimer ce qu'un `providers: dict[str, str]` ne pouvait pas : « API-Sports couvre les résultats de la Ligue 1 en 2025 mais pas ses compositions », ou « football-data.org couvre cette compétition en 2026 mais pas en 2022 ».

**Le score unique `coverage_quality: float` est supprimé.** Il ne répondait à aucune des questions qui comptent (calculé comment ? pour quelle saison ? quel endpoint ? mis à jour quand ?). Un score agrégé peut être dérivé de ces dimensions à la demande, mais n'est jamais la vérité stockée.

### 7.3 Vérification obligatoire avant activation

- Une entrée de couverture en `UNVERIFIED` n'est **jamais** utilisée par `fallback_chain` pour servir une requête de production.
- Le passage à `FULL`/`PARTIAL`/`ABSENT` exige `verification_method = "live_call"` : un appel réel a été effectué et son résultat constaté. La documentation d'un provider ne suffit pas à elle seule (`provider_docs` est un statut intermédiaire de travail, pas une activation).
- `coverage_verification.py` fournit la procédure scriptée : pour un couple (provider, compétition, saison, data_type), effectuer l'appel, constater, écrire l'entrée horodatée.
- Une couverture vérifiée a une **date** : `verified_at`. Une revue périodique est nécessaire car les tiers gratuits changent sans préavis (c'est exactement ce qui a motivé la v1 : API-Football a coupé l'accès à la saison en cours).

### 7.4 Pourquoi la granularité saison est obligatoire

Sans `season` dans la clé, une couverture vérifiée en 2026 serait considérée comme vraie pour 2018 ou 2027. Le cas est réel et déjà rencontré : le plan gratuit API-Football sert 2022–2024 et refuse 2025+. Une modélisation sans saison aurait présenté ce provider comme « couvrant la Ligue 1 », ce qui est faux pour la saison qui compte.

---

## 8. Sélection de provider et fallback — déterministes

### 8.1 Critères d'éligibilité (élimination, dans cet ordre)

Un provider est **candidat** pour une requête `(sport, competition_id, season, data_type, point_in_time)` si et seulement si :

1. Le provider déclare `capabilities()` couvrant ce `data_type`.
2. Une entrée `ProviderCompetitionCoverage` existe pour `(provider, competition_id, season, data_type)`.
3. Cette entrée est en `FULL` ou `PARTIAL` (jamais `ABSENT`, jamais `UNVERIFIED`).
4. La compétition est en `status = "active"` dans le `Competition Registry`.
5. Le `SportModule` du sport déclare un normalizer pour ce provider.
6. Le quota du provider n'est pas épuisé.

### 8.2 Ordre de préférence entre candidats (départage, dans cet ordre)

Sélection hiérarchique déterministe — le score composite reste écarté tant qu'il n'y a pas de données réelles pour calibrer ses poids (décision v1 maintenue) :

1. `CoverageStatus` : `FULL` avant `PARTIAL`
2. `data_quality` du couple (provider, data_type), décroissant
3. Fraîcheur attendue de la donnée pour ce provider
4. Santé du quota (marge restante, décroissant)
5. Priorité configurée dans `provider_registry`
6. `query_cost` croissant
7. Latence historique croissante

À égalité stricte sur tous ces critères, l'ordre de déclaration dans `provider_registry` tranche — pour que la sélection soit reproductible (NFR déterminisme, §10.1).

### 8.3 Déclencheurs de fallback — liste fermée

Le fallback vers le candidat suivant se déclenche sur, et uniquement sur :

| Déclencheur | Comportement |
|---|---|
| Erreur réseau / timeout | Fallback, log `reason="network_error"` |
| Réponse HTTP d'erreur (4xx/5xx hors quota) | Fallback, log `reason="provider_error"` |
| Quota dépassé (429 ou compteur local) | Fallback, log `reason="quota_exhausted"` |
| Réponse invalide au regard du schéma (`validate_payload` lève) | Fallback, log `reason="schema_violation"` |
| Résultat vide alors que la couverture annonce `FULL` | Fallback, log `reason="unexpected_empty"` |
| `data_quality` sous le seuil configuré pour ce `data_type` | Fallback, log `reason="quality_below_threshold"` |
| Donnée disponible mais postérieure au `point_in_time` demandé | **Pas de fallback** — la donnée est écartée, la requête échoue proprement (une autre source ne rendrait pas la donnée légitime) |
| Résultat vide alors que la couverture annonce `PARTIAL` | **Pas de fallback** — résultat vide légitime, retourné tel quel |

### 8.4 Épuisement de la chaîne

Si aucun candidat n'aboutit : lecture du dernier snapshot connu dans le `point_in_time_store`, **restreint à la même saison et au même `schema_version` compatible**, retourné avec `stale=True`. Si aucun snapshot compatible n'existe : `NoDataAvailableError` typée. Jamais de donnée fabriquée, jamais d'exception silencieuse — comportement v1 conservé, avec la restriction de saison qui avait été identifiée comme bug en v1.

---

## 9. Identité multi-sport typée

### 9.1 Espaces de noms typés

Le passage au multi-sport multiplie les types d'entités : équipe, joueur, paire de double, combattant, pilote, lieu, tournoi, saison, tour. Un espace de noms plat produira des collisions — la v1 en a déjà subi une (Wolves / Premier League, ID `39` chez API-Sports).

**Format imposé** : `{entity_type}:{sport}:{scope}:{slug}`

```
player:tennis:atp:carlos_alcaraz
player:tennis:wta:iga_swiatek
pair:tennis:atp:granollers_zeballos
team:football:fra:psg
team:baseball:mlb:dodgers
competition:tennis:atp:cincinnati
venue:tennis:usa:flushing_meadows
```

**GW-FR-008 — Deux entités de types différents ne peuvent jamais partager le même espace de noms.** Le préfixe `entity_type` est structurellement obligatoire dans tout `canonical_id`, validé à l'écriture dans le registre d'identités.

### 9.2 Difficultés spécifiques identifiées

Le tennis concentre plusieurs cas que le football n'avait pas :

- **Changement de nom** (mariage, translittération) → `aliases` + `valid_from` déjà prévus en v1, à utiliser systématiquement.
- **Accents et translittérations** (`Djokovic` / `Đoković`) → normalisation Unicode à l'entrée, mais **jamais de rattachement automatique** sur cette base seule (règle v1 maintenue).
- **Homonymes** (père/fils, joueurs de circuits différents) → résolus par le `scope` dans le namespace, ou `AMBIGUOUS` si indistinguables.
- **Doubles** → type d'entité `pair` distinct, jamais réduit à deux `player`.
- **Joueurs sans classement** (qualifiés, wild cards) → entité valide, absence de ranking traitée comme donnée manquante, pas comme entité inconnue.
- **Circuits multiples** (ATP, WTA, ITF, Challenger) → portés par le `scope`, car un même joueur peut apparaître sur plusieurs circuits.

Le statut de résolution (`RESOLVED` / `UNRESOLVED` / `AMBIGUOUS` / `CONFLICT`) et la file de revue manuelle de la v1 sont conservés à l'identique — aucun rattachement automatique par proximité de nom, quel que soit le sport.

---

## 10. Exigences

### 10.1 Fonctionnelles

| # | Exigence | Priorité |
|---|---|---|
| GW-FR-001 | Ajouter un sport ne modifie aucun fichier de `core/` ou `cache/` — seulement `sports/<sport>/` + une entrée dans `sports/registry.py` | Must |
| GW-FR-002 | `competition_registry` et `provider_coverage_registry` sont deux objets distincts ; aucune identité de compétition ne porte d'ID provider | Must |
| GW-FR-003 | La couverture provider est modélisée par `(provider, competition_id, season, data_type)` | Must |
| GW-FR-004 | Toute `CanonicalEnvelope` porte `sport`, `season`, `data_type`, `schema_version`, `provider_entity_id` en plus des champs v1 | Must |
| GW-FR-005 | Une couverture `UNVERIFIED` n'est jamais utilisée en production ; l'activation exige `verification_method = "live_call"` | Must |
| GW-FR-006 | La sélection de provider suit strictement l'ordre §8.1/§8.2 ; les déclencheurs de fallback sont ceux de §8.3, sans ajout implicite | Must |
| GW-FR-007 | `validate_payload` du `SportModule` est appelé avant toute écriture dans le `point_in_time_store` | Must |
| GW-FR-008 | Tout `canonical_id` est typé `{entity_type}:{sport}:{scope}:{slug}` ; deux types d'entités ne partagent jamais un espace de noms | Must |
| GW-FR-009 | La lecture d'un snapshot dont le `schema_version` est incompatible échoue explicitement, jamais silencieusement | Must |
| GW-FR-010 | Le socle v1 (football, Ligue 1 + Premier League) fonctionne sans régression après migration | Must |
| GW-FR-011 | CLI `axon sports-status --sport <s> --competition <id> --season <y>` affiche la couverture réelle par `data_type` | Should |
| GW-FR-012 | Un dataset dérivé est une fonction pure et déterministe des faits canoniques ; aucun paramètre appris n'y est admis | Must |

### 10.2 Non-fonctionnelles

- **GW-NFR-001 · Déterminisme** — à entrée identique et `point_in_time` identique, le résultat est identique : même provider sélectionné, même payload, même dérivés. Aucune source d'aléa (ordre d'itération de dict non ordonné, horloge lue en cours de calcul) dans le chemin de sélection.
- **GW-NFR-002 · Idempotence** — réingérer la même réponse provider ne crée pas de doublon : mécanisme `fetch_event` / `data_snapshot` + `content_hash` de la v1, étendu pour inclure `schema_version` dans le hash.
- **GW-NFR-003 · Observabilité** — chaque requête expose : provider sélectionné, candidats écartés et raison, fallback utilisé ou non, cache hit/miss, latence, `data_quality`, `freshness_score`, quota restant. Log structuré JSON.
- **GW-NFR-004 · Performance** — p95 lecture cache < 50 ms ; p95 résolution d'identité sans appel réseau < 100 ms ; la latence provider est mesurée et documentée séparément (hors de ce budget, car non maîtrisée).
- **GW-NFR-005 · Compatibilité** — tout changement de schéma canonique incrémente `schema_version` ; les anciens snapshots restent lisibles ou explicitement rejetés, jamais réinterprétés.
- **GW-NFR-006 · Résilience par sport** — la défaillance d'un `SportModule` (import cassé, schéma invalide) n'interrompt pas les autres sports : `get_sport_module` isole l'erreur au sport concerné.
- **GW-NFR-007 · Auditabilité** — toute valeur retournée est reliable à la réponse provider d'origine via `(provider, provider_entity_id, fetched_at, content_hash)` conservés dans le `point_in_time_store`.
- **GW-NFR-008 · Rétention** — purger le cache opérationnel ne supprime jamais un snapshot du `point_in_time_store` (règle v1 conservée).

---

## 11. Rollout

Le rollout est réordonné : le tennis et le baseball sont les priorités réelles ; le football, déjà livré, est protégé de toute régression mais ne monopolise plus le développement.

**Vague 0 — Socle (bloquant pour le reste)**
- `canonical/envelope.py` (`CanonicalEnvelope`), `canonical/data_types.py`
- `sports/registry.py` + protocole `SportModule`
- `registries/` : `competition_registry`, `provider_coverage_registry`, `coverage_verification`
- Extension de `identity_resolver` au namespace typé (§9.1)
- Migration du football existant vers cette structure : `sports/football/`, réécriture des snapshots avec `schema_version="football/1.0"`, entrées de couverture pour Ligue 1 / Premier League
- **Critère de sortie : non-régression football vérifiée** (tests v1 verts, `recent_form` et `standings_strength` identiques avant/après)

**Vague 1 — Tennis ATP/WTA**
- `sports/tennis/` complet : module, faits canoniques (match, tour, surface, classement), normalizers, dérivés (forme, head-to-head, hold/break sur fenêtre)
- Un tournoi ATP et un tournoi WTA vérifiés (`live_call`) et activés
- Identité : joueurs, paires, tournois — avec les cas §9.2 traités
- Historisation des classements et statistiques disponibles
- Validation complète du pipeline point-in-time sur ce sport

**Vague 2 — Baseball MLB**
- `sports/baseball/` : matchs, équipes, pitchers, lineups, résultats
- Valide le modèle d'événement multi-participants avec rôles (pitcher partant ≠ autres joueurs), là où le tennis valide l'événement à deux participants symétriques
- Vérification de la profondeur historique disponible (`historical_depth_years`)

**Vague 3+ — Extension**
- Nouvelles compétitions football selon les besoins réels du catalogue bookmaker
- Volley, basket, hockey et autres, selon la disponibilité provider **vérifiée** et l'usage réel — jamais par exhaustivité théorique

---

## 12. Risques

| Risque | Impact | Mitigation |
|---|---|---|
| Aucun provider ne couvre réellement certaines compétitions visées (Coupe de Lituanie, tournois ATP mineurs, NPB) | Développement de modèles canoniques pour des données inexistantes | Vérification `live_call` obligatoire avant activation (GW-FR-005) ; compétitions mineures traitées en Vague 3+ |
| La gateway dérive en feature engine (dérivés qui deviennent des features apprises) | Duplication et confusion de responsabilité avec `axon-betting-engine` | Règle GW-FR-012 (dérivé = fonction pure des faits) ; revue de code dédiée sur `derived.py` à chaque nouveau sport |
| Migration v1 → v2 casse le pipeline football existant | Perte du seul pipeline validé | Vague 0 traitée comme un chantier de migration à part entière, critère de sortie = non-régression vérifiée, pas un simple déplacement de fichiers |
| `schema_version` mal géré : anciens snapshots réinterprétés avec un nouveau schéma | Backtests faussés silencieusement — le pire type de bug ici | `is_schema_compatible` obligatoire en lecture, échec explicite (GW-FR-009) |
| Explosion du volume d'entrées de couverture (provider × compétition × saison × data_type) | Registre lourd et non maintenu | Génération scriptée via `coverage_verification`, `verified_at` obligatoire, revue périodique ; entrées `deprecated` plutôt que supprimées |
| Collision d'identité sur un nouveau sport | Données servies pour la mauvaise entité (bug déjà survenu en v1) | Namespace typé obligatoire (GW-FR-008), validation à l'écriture, statuts de résolution v1 conservés |

---

## 13. Critères d'acceptation

Au-delà des critères généraux, ces scénarios doivent être vérifiés explicitement.

**Sélection de provider**
```gherkin
Given une compétition tennis en status "active"
  And une couverture verified (live_call) pour le provider P, saison 2026, data_type FIXTURES
When get_fixtures est appelé pour cette compétition, saison 2026
Then seuls les providers éligibles selon §8.1 sont considérés
  And le payload est validé par TennisModule.validate_payload avant écriture
  And la CanonicalEnvelope porte sport, data_type, schema_version et provider_entity_id
  And les cinq horodatages point-in-time sont présents
  And la réponse brute d'origine reste reliable via le point_in_time_store
```

**Fallback**
```gherkin
Given un provider tennis P1 éligible mais indisponible (timeout réseau)
  And un second provider P2 éligible pour la même compétition/saison/data_type
When get_fixtures est appelé
Then le fallback vers P2 est utilisé
  And la raison "network_error" est journalisée avec le candidat écarté
  And la réponse indique P2 comme provider final
```

**Refus point-in-time**
```gherkin
Given une donnée disponible chez le provider mais publiée après le point_in_time demandé
When une requête est faite avec ce point_in_time
Then aucun fallback n'est déclenché
  And la requête échoue proprement (NoDataAvailableError)
  And aucune donnée postérieure n'est retournée
```

**Incompatibilité de schéma**
```gherkin
Given un snapshot stocké sous schema_version "tennis/1.0"
  And un TennisModule courant en schema_version "tennis/2.0" incompatible
When ce snapshot est relu
Then la lecture échoue explicitement
  And aucun payload n'est réinterprété avec le schéma courant
```

**Non-régression football**
```gherkin
Given le socle v1 football migré vers la structure v2
When recent_form et standings_strength sont appelés sur Ligue 1 et Premier League
Then les résultats sont identiques à ceux de la v1 pour les mêmes entrées et le même point_in_time
  And les 17 tests unitaires v1 passent
```

**Isolation par sport**
```gherkin
Given un SportModule baseball défaillant (schéma invalide)
When une requête tennis est effectuée
Then elle aboutit normalement
  And seul le sport baseball remonte une erreur
```

---

## 14. Décisions ouvertes

1. **Format de stockage des registres** : SQLite (cohérent avec le `point_in_time_store` existant) vs fichiers YAML versionnés en git (plus lisibles, revue par diff). *Recommandation : YAML pour `Competition` (peu volumineux, édité à la main), SQLite pour `ProviderCompetitionCoverage` (volumineux, généré par script).*
2. **Politique de revérification de couverture** : quelle périodicité avant qu'un `verified_at` soit considéré périmé ? À définir empiriquement — les tiers gratuits changent sans préavis.
3. **`scope` dans le namespace d'identité** : circuit (`atp`/`wta`) pour le tennis, code pays pour le football de clubs, ligue pour le baseball. Faut-il une règle unique par sport, portée par `SportModule` ? *Recommandation : oui, méthode `namespace_scope_for(entity_type)` à ajouter au protocole si un troisième sport révèle des cas non couverts.*
4. **Granularité de `schema_version`** : par sport (`tennis/1.2`) ou par sport × data_type (`tennis/fixtures/1.2`) ? *v2 : par sport, plus simple ; à revoir si un seul data_type évolue beaucoup plus vite que les autres.*
5. **Seuils de `data_quality` par `data_type`** déclenchant le fallback (§8.3) : valeurs à calibrer une fois qu'il y a assez d'observations réelles.
