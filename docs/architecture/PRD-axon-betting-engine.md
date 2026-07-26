# PRD — `axon-betting-engine`

**Statut :** Accepted for implementation — corrige l'orientation architecturale de `PRD-axon-betting-platform.md` (obsolète, remplacé par ce document)
**Dépend de :** `axon-sports-data-gateway` (v1 livré + extension v2 multi-sport), consommé comme **dépendance externe** — jamais modifié depuis ce PRD, uniquement appelé via son API publique
**Position dans la chaîne :** ce PRD est le sommet — rien d'autre dans Axon ne dépend de `axon-betting-engine`
**Module parent :** Axon (`/home/kaine/Documents/projets-perso/ai-agent/`)
**Auteur :** Kaine
**Dernière mise à jour :** 24 juillet 2026

---

## 1. Correction de direction architecturale

Le PRD précédent (`axon-betting-platform`) faisait encore raisonner le projet en partant de la gateway :

```
Gateway → Football → Tennis → Baseball
```

C'est l'inverse de ce qui est réellement construit. `axon-sports-data-gateway` est un **fournisseur de données** — providers, normalisation, résolution d'identité, cache, point-in-time. Son rôle s'arrête là, et son PRD (v1 + v2) reste inchangé par ce document. Le vrai produit est ailleurs :

```
Bookmaker → Catalog → [sports_data_gateway] → Sport Modules → Feature Engineering → Market Models → Calibration → Value Engine → Bet Ranking
```

Ce PRD introduit donc `axon-betting-engine` comme projet séparé, qui **dépend de** `axon-sports-data-gateway` (import, appel à son API publique), sans jamais modifier son cœur. Si un besoin de données oblige à changer `axon-sports-data-gateway` (nouveau provider, nouvelle compétition), ce changement reste porté par les PRD de la gateway elle-même, pas par celui-ci.

**Règle de dépendance, sans exception :** aucun fichier sous `core/`, `cache/`, `providers/`, ou les `normalizers/` de `axon-sports-data-gateway` n'est un livrable de ce PRD. `axon-betting-engine` ne fait qu'appeler ce que la gateway expose déjà (fixtures, standings, forme, résolution d'identité, disponibilité par compétition).

---

## 2. Objectifs

1. Scanner en continu le catalogue Winamax et le normaliser en un modèle sport-agnostique, sans jamais dupliquer ce que fait déjà `axon-sports-data-gateway` côté stats sportives.
2. Faire du **marché** (pas du sport) l'objet central de prédiction : un `MarketModel` par couple `(sport, market_type)`, avec ses propres features, sa propre calibration, son propre historique de fiabilité.
3. Introduire une couche `Feature Engineering` explicite entre les données canoniques (fournies par la gateway) et les modèles de marché — un modèle ne travaille jamais directement sur les données brutes normalisées.
4. Distinguer clairement deux registres : le `Competition Registry` (déjà posé côté gateway — quels providers de stats couvrent quelle compétition) et un nouveau `Bookmaker Registry` (quels événements Winamax correspondent à quels événements canoniques).
5. Ne jamais recommander un pari sur un marché non certifié — l'abstention reste un résultat valide (hérité du PRD précédent, toujours vrai).
6. Mesurer la performance dans la durée par marché, pas par sport globalement (calibration, Brier score, log loss, closing-line value).

## 3. Non-objectifs

- Ne pas modifier `axon-sports-data-gateway` dans ce PRD — toute évolution de la gateway (nouveau provider, nouvelle compétition ajoutée au `Competition Registry`) reste portée par ses propres PRD.
- Ne pas construire tous les `MarketModel` de tous les sports en une itération — un seul marché, un seul sport, validé de bout en bout, avant d'en ajouter d'autres (cf. §11).
- Ne pas intégrer d'autres bookmakers que Winamax dans ce PRD — l'architecture (`bookmakers/<nom>/` avec un contrat `BookmakerConnector`) doit le permettre plus tard sans réécriture, mais ce n'est pas un livrable ici.
- Ne pas automatiser le placement de pari — Axon recommande, l'exécution reste manuelle. L'automatisation du pari est un chantier ultérieur distinct (bankroll, limites Winamax, questions légales à trancher séparément).
- Ne pas construire de couverture exhaustive des marchés exotiques (corners, buteur, combinés) — ils restent `UNSUPPORTED` tant qu'aucun `MarketModel` dédié n'est validé.
- **Live et cotes boostées ne sont PAS exclus du produit** (cf. §4.4 et §10bis pour leur traitement), mais sont explicitement **différés après la première tranche verticale pré-match** (§11). Construire un `MarketModel` pré-match calibré est le préalable : sans lui, ni le live (qui a besoin d'un modèle de référence à réviser en continu) ni les cotes boostées (qui ont besoin d'un `value_engine` fiable pour détecter qu'un boost dépasse la marge normale) n'ont de socle sur lequel s'appuyer.

---

## 4. Architecture

```
Winamax                          (+ Betclic, Unibet... — structure prête, cf. §4.2)
   │
   ▼
bookmakers/                           (axon-betting-engine — NOUVEAU)
   ├── protocol.py                    contrat BookmakerConnector commun
   ├── registry.py                    BOOKMAKERS: dict[str, BookmakerConnector]
   ├── winamax/                       seul connecteur implémenté
   │     ├── connector.py             scan du catalogue
   │     └── market_mapping.py        libellés Winamax → vocabulaire canonique
   │
   ├── market_normalizer.py           vocabulaire canonique de marchés, partagé
   ├── odds_history.py                historique des cotes, multi-bookmaker par construction
   └── bookmaker_registry.py          bookmaker event_id ↔ canonical_event_id ↔ sport (cf. §5.1)
   │
   ▼
canonical_event_registry.py           (axon-betting-engine — événements pariables, cf. §5.2)
   │
   ▼  (appel à l'API publique, aucune modification interne)
axon-sports-data-gateway              (EXTERNE — v1 + v2, inchangé)
   → canonical facts + derived datasets, identity_resolver, registres de couverture
   │
   ▼
sports/<sport>/                       (axon-betting-engine — cf. §6)
   ├── manifest.py
   ├── feature_engineering/
   ├── market_models/
   ├── validators/
   └── context_schema.py              schéma versionné du contexte d'événement (§5.2)
   │
   ▼
calibration/                          (axon-betting-engine, cf. §7)
   ├── walk_forward.py
   ├── probability_calibration.py
   ├── model_comparison.py
   ├── drift_detection.py
   └── experiment_registry.py         historique de tous les modèles testés (§7.2)
   │
   ▼
value_engine/                         (axon-betting-engine, cf. §8)
   ├── margin_removal.py
   ├── expected_value.py
   ├── uncertainty.py
   └── abstention.py
   │
   ▼
portfolio/                            (axon-betting-engine — NOUVEAU, cf. §9)
   ├── exposure.py                    expositions réelles par événement / participant
   └── correlation.py                 corrélation entre sélections d'un même événement
   │
   ▼
bet_ranking.py                        (axon-betting-engine — classement final des opportunités)
```

### 4.1 Multi-bookmaker dès la structure

Seul Winamax est implémenté, et **aucun dossier vide n'est créé pour les autres** : l'extensibilité vient du contrat `BookmakerConnector` et du registre, pas de répertoires anticipés. Ajouter Betclic ou Unibet plus tard consistera à créer `bookmakers/betclic/` implémentant le protocole et à l'enregistrer — sans toucher au reste du pipeline.

Poser le contrat maintenant coûte quasi rien et évite une migration structurelle plus tard — d'autant que comparer plusieurs bookmakers est directement utile au calcul de valeur (détecter une cote aberrante chez l'un par rapport aux autres est un signal en soi).

```python
class BookmakerConnector(Protocol):
    bookmaker: str

    def scan_catalog(self) -> list[RawBookmakerEvent]:
        ...

    def market_mapping(self) -> dict[str, str]:
        """Libellés bruts de ce bookmaker → market_type canonique."""
        ...
```

### 4.2 Flux de bout en bout

```
Winamax catalog scan
   → CanonicalEvent + CanonicalMarket[] + OddsSnapshot[]      (bookmakers/winamax)
   → bookmaker_registry : rattachement à canonical_event_id    (§5.1)
   → appel axon-sports-data-gateway : fixtures/forme/classement pour les participants de l'événement
   → feature_engineering du sport concerné : canonical facts + derived datasets (gateway) → EventFeatureSet (§6.2)
   → routage vers le(s) MarketModel(s) couvrant ce market_type pour ce sport
   → MarketPrediction (fair_probability, intervalle, data_quality, calibration_status)
   → value_engine : margin_removal + expected_value + uncertainty + corrélation + abstention
   → bet_ranking : classement des opportunités BET/WATCH, ABSTAIN filtré
```

---

### 4.4 Live et cotes boostées — traitement différencié, pas une extension du même modèle

Ces deux extensions sont voulues par Kaine mais ne sont **pas** de simples options à activer sur le pipeline pré-match existant — chacune casse une hypothèse structurelle du modèle de base, et doit donc être pensée comme une extension distincte du contrat.

**Live.** Le pré-match repose sur `point_in_time` figé au moment de la décision (ADR-004). En live, l'état du match change en continu (score, minute, dynamique), donc la feature qui compte le plus n'est plus "la forme avant le match" mais "l'état du match maintenant". Conséquences sur le contrat :

- Un `MarketModel` live n'est **pas** le même objet qu'un `MarketModel` pré-match, même sur le même marché (`MATCH_WINNER` pré-match ≠ `MATCH_WINNER` live) — le second a besoin d'un flux d'état continu en entrée (`LiveMatchState`), pas d'un simple `EventFeatureSet` figé.
- `point_in_time` reste obligatoire, mais glisse en continu : chaque décision live a son propre point_in_time, pas un seul par match.
- La fenêtre de décision se compte en secondes, pas en heures — `value_engine` doit pouvoir répondre dans ce délai, ce qui contraint le choix technique (pas de recalcul lourd à chaque tick).
- **Un `MarketModel` live sur un marché donné ne peut être développé qu'après que sa version pré-match soit `SUPPORTED`** — le live affine un modèle de référence déjà validé, il ne part pas de zéro.

```python
@dataclass(frozen=True)
class LiveMatchState:
    event_id: str
    as_of: datetime               # instant de cet état, pas du match
    elapsed: str                  # ex. "67:00", format propre au sport
    score: dict[str, int]         # par participant
    period: str                   # mi-temps, set en cours, manche...
    momentum_features: dict       # dérivées à court terme (xG cumulé, possession récente...)
```

**Cotes boostées.** Winamax les traite comme une catégorie à part dans son catalogue (confirmé par la cartographie du snapshot réel : `sportId 100000`, catégorie dédiée). Un boost est une décision marketing du bookmaker sur une sélection précise, pas le reflet honnête d'un risque perçu — le convertir en probabilité implicite classique via `margin_removal.py` donnerait un résultat trompeur.

**Un boost n'est pas un marché différent** : c'est toujours `MATCH_WINNER` (ou tout autre marché existant), avec une cote relevée sur une sélection donnée. Créer un `market_type` dédié (`BOOSTED_*`) multiplierait artificiellement les marchés pour un même événement de fond — le `MarketModel` sous-jacent n'a aucune raison de changer. La bonne modélisation est donc au niveau de l'**offre**, portée par trois champs de `OddsSnapshot` (définition canonique unique en §5.3, pas redéfinie ici) :

- `is_boosted: bool` — cette cote précise est-elle une offre promotionnelle sur cette sélection ?
- `boost_reference_odds: float | None` — la cote non boostée connue pour la même sélection, quand le bookmaker la fournit.
- `max_stake: float | None` — mise maximale acceptée sur cette offre, si le bookmaker l'annonce.
- `max_payout: float | None` — plafond de gain annoncé sur cette offre, si distinct de la mise maximale (un plafond de gain à cote 3,00 n'équivaut pas à une mise maximale — les deux sont suivis séparément plutôt que fusionnés sous un seul concept).

Conséquences :
- Le `MarketModel` reste identique, qu'une offre soit boostée ou non — aucune duplication de modèle par statut promotionnel.
- `value_engine` compare toujours la cote au `fair_odds` du même marché ; si `is_boosted=True`, il ne retire **pas** la marge standard sur cette cote précise (le boost casse l'hypothèse de pricing normal du bookmaker sur cette sélection), et privilégie `boost_reference_odds` comme point de comparaison quand elle est connue.
- `max_stake`/`max_payout`, quand présents, sont propagés jusqu'à `bet_ranking.py` — un edge élevé mais plafonné (en mise ou en gain) n'a pas la même valeur qu'un edge élevé exploitable à l'échelle, et les deux ne doivent jamais être classés de la même façon.
- **Une offre boostée n'est évaluée que si son marché sous-jacent est déjà `SUPPORTED`** — sans `fair_odds` de référence fiable sur ce marché, impossible de dire si le boost constitue une vraie opportunité ou juste du marketing sans avantage réel.

### 4.4bis Pourquoi le séquencement compte plus que d'habitude ici

Les deux extensions partagent la même dépendance : elles ont besoin d'un `MarketModel` pré-match déjà `SUPPORTED` sur lequel s'appuyer (comme référence à réviser pour le live, comme référence de comparaison pour les cotes boostées). Ce n'est pas une préférence de rollout, c'est une dépendance logique — les construire avant d'avoir un premier marché calibré reviendrait à comparer une cote à... rien de fiable. D'où leur position dans le rollout révisé (§11, Vague 2).



### 5.1 Bookmaker Registry (nouveau — distinct du Competition Registry)

Le `Competition Registry` (posé dans `axon-sports-data-gateway` v2) répond à la question *"quel provider de stats couvre cette compétition ?"*. Il ne dit rien de ce que Winamax propose. Le `Bookmaker Registry` répond à une question différente : *"cet événement Winamax correspond à quel événement canonique, dans quel sport, dans quelle compétition ?"*.

```python
@dataclass(frozen=True)
class BookmakerEventMapping:
    bookmaker: str                     # "winamax"
    bookmaker_event_id: str
    canonical_event_id: str            # référence canonical_event_registry (§5.2)
    sport: str
    competition_id: str                # référence competition_registry (côté gateway)
    identity_status: Literal["RESOLVED", "UNRESOLVED", "AMBIGUOUS", "CONFLICT"]  # même vocabulaire
                                        # que l'identity_resolver de la gateway, pour cohérence
    confirmed_at: datetime
```

Comme pour l'`identity_resolver` de la gateway (v1) : un événement `UNRESOLVED`/`AMBIGUOUS`/`CONFLICT` n'est jamais rattaché automatiquement par proximité de nom — il part en file de revue, jamais utilisé tel quel par le reste du pipeline.

### 5.2 Canonical Event Registry

Distinct du `Competition Registry` (compétitions) et du `Bookmaker Registry` (mapping bookmaker↔canonique) : le `canonical_event_registry` est la table des événements pariables eux-mêmes (un match, un combat, une rencontre précise à une date donnée), identifiés indépendamment de tout bookmaker.

```python
@dataclass(frozen=True)
class CanonicalEvent:
    event_id: str
    sport: str
    competition_id: str                 # référence competition_registry (gateway)
    participants: list["EventParticipant"]
    scheduled_at: datetime
    context: "EventContext"             # objet typé et versionné par sport — cf. ci-dessous

@dataclass(frozen=True)
class EventParticipant:
    canonical_id: str                   # typé, résolu via axon-sports-data-gateway.identity_resolver
    role: str                           # "home"/"away" (football, baseball), "player_a"/"player_b"
                                         # (tennis), "starting_pitcher" (baseball)... déclaré par le sport
```

### 5.2bis Ordre bookmaker (`slot`) ≠ rôle sportif canonique (`role`) — deux concepts distincts, jamais confondus

Ce sont deux notions d'ordre différentes, qui ne doivent jamais être fusionnées silencieusement :

| Concept | Valeurs | Origine | Portée |
|---|---|---|---|
| **Slot bookmaker** | `slot_1` / `slot_2` | Ordre d'affichage brut d'un bookmaker (ex. `competitor1`/`competitor2` chez Winamax) | Peut être conservé dans les objets d'acquisition et d'audit (utile pour détecter un changement de comportement du catalogue) ; ne devient jamais `EventParticipant.role` sans résolution explicite |
| **Rôle canonique** | `home`/`away`, `player_a`/`player_b`, `starting_pitcher`... | Vérité sportive de l'événement, déclarée par le module sportif | `EventParticipant.role`, ce que tout le reste du pipeline consomme |

`ADR-015` (dépôt de code) établit, par vérification empirique (49/49 sur 8 compétitions), que chez Winamax `slot_1` correspond systématiquement à l'équipe à domicile pour le football *actuellement*. **Mais ce n'est pas une équivalence structurelle** : un composant dédié, `ParticipantRoleResolver` (délibérément pas nommé "Normalizer" — ce mot est réservé à la gateway pour la conversion provider brut → faits canoniques, cf. `ADR-003` et glossaire), traduit explicitement `slot_1`→`role` via le module sportif concerné. Il ne propage jamais `slot_1` tel quel comme s'il était le `role`. Concrètement :

- Si Winamax affiche `slot_1 = PSG, slot_2 = Marseille` pour un match où PSG reçoit → `role(PSG) = home`, `role(Marseille) = away`. Les deux ordres coïncident, mais par vérification, pas par définition.
- **Si un jour le catalogue affiche `slot_1 = Marseille, slot_2 = PSG`** pour ce même match (changement d'ordre d'affichage côté bookmaker, sans rapport avec qui reçoit), l'événement canonique doit rester `role(PSG) = home`, `role(Marseille) = away` — jamais l'inverse simplement parce que l'ordre d'affichage a changé.
- En tennis, il n'y a structurellement pas de `home`/`away` : `slot_1`/`slot_2` se traduisent en `player_a`/`player_b`, un ordre arbitraire mais stable, jamais un "domicile" fictif (cf. §6.2).

**Règle définitive** : le slot brut peut être conservé dans les objets d'acquisition (`RawBookmakerEvent` et équivalents) et dans les logs d'audit — c'est même utile pour détecter qu'un bookmaker a changé sa convention d'affichage sans prévenir. Ce qui est interdit, c'est sa **propagation** comme `EventParticipant.role` sans passer par une résolution explicite. Cette résolution est aujourd'hui une vérification empirique documentée (`ADR-015`, football) ; si une re-vérification en pleine saison (suivi tracé dans les todos du dépôt) tombe un jour sous 100%, elle bascule vers un mapping par identité (nom résolu en `canonical_id`) plutôt que par position brute — jamais un retour silencieux à "slot_1 = home" par défaut.

**`context` est un objet versionné, pas un `dict` libre.** Un champ `format: dict` non typé grossit sans contrôle et finit par contenir des clés incohérentes entre sports, sans qu'aucun consommateur ne puisse savoir ce qu'il peut légitimement lire. Chaque sport déclare donc son schéma de contexte dans `sports/<sport>/context_schema.py` :

```python
@dataclass(frozen=True)
class EventContext:
    """Base commune — chaque sport en dérive une version typée."""
    sport: str
    context_version: str                # ex. "tennis/1.0" — versionné comme les schémas gateway

@dataclass(frozen=True)
class TennisEventContext(EventContext):
    surface: Literal["hard", "clay", "grass", "carpet"]
    best_of: Literal[3, 5]
    indoor: bool
    round: str                          # "R32", "QF", "SF", "F"...

@dataclass(frozen=True)
class BaseballEventContext(EventContext):
    innings: int
    probable_pitchers: dict[str, str | None]   # {role: canonical_id du pitcher}
    park_id: str | None

@dataclass(frozen=True)
class FootballEventContext(EventContext):
    neutral_venue: bool
    leg: int | None                     # aller/retour en coupe
```

Comme pour le `schema_version` de la gateway : faire évoluer un contexte incrémente `context_version`, et un consommateur qui rencontre une version incompatible échoue explicitement plutôt que d'interpréter des champs absents.

### 5.3 Market — l'objet central

```python
@dataclass(frozen=True)
class CanonicalMarket:
    market_id: str
    event_id: str
    market_type: str                    # ex. "MATCH_WINNER", "OVER_UNDER_2_5", "BTTS",
                                         # "TOTAL_GAMES", "RUN_LINE"
    selections: list[str]

@dataclass(frozen=True)
class OddsSnapshot:
    bookmaker: str
    market_id: str
    selection: str
    decimal_odds: float
    observed_at: datetime

    # Propriétés de l'offre — non un market_type distinct, cf. §4.4 et ADR-017
    is_boosted: bool = False
    boost_reference_odds: float | None = None   # cote non boostée connue, si disponible
    max_stake: float | None = None               # mise maximale acceptée, si annoncée
    max_payout: float | None = None              # plafond de gain, si distinct de max_stake
```

**Définition canonique unique** : `OddsSnapshot` n'est défini qu'ici. Toute autre section du document (notamment §4.4 sur les cotes boostées) s'y réfère sans la redéfinir.

`market_normalizer.py` traduit les libellés Winamax bruts ("Vainqueur du match", "Plus de 2,5 buts", "Les deux équipes marquent") vers ce vocabulaire canonique — c'est un composant à part entière, partagé par tous les `MarketModel`.

---

## 6. Module sportif — structure et frontière avec la gateway

### 6.1 Structure retenue, avec une nuance assumée par rapport à la proposition initiale

Même terminologie que la gateway v2 : ce sont des **modules métier** par sport, pas des adaptateurs au sens du pattern GoF (cf. `ADR-005`).

```
sports/<sport>/
   ├── manifest.py            déclare : quels market_models sont enregistrés,
   │                          quelles features requises, quel context_schema
   ├── context_schema.py      EventContext typé et versionné pour ce sport (§5.2)
   ├── feature_engineering/   transforme les canonical facts + derived datasets (gateway)
   │                          en EventFeatureSet exploitable par les market_models
   ├── market_models/         un fichier par market_type (ex. match_winner.py, total_games.py)
   └── validators/            validation du contexte et des features pour ce sport
```

**Nuance assumée par rapport à la proposition initiale** : les `normalizers/` (JSON brut provider → faits canoniques) restent dans `axon-sports-data-gateway`, pas dupliqués ici. C'est une conséquence directe de la règle de dépendance posée en §1 : normaliser les données sportives brutes est le travail de la gateway, déjà construit et validé pour le football. Le dupliquer ici recréerait exactement le mélange de responsabilités que ce PRD cherche à éviter. `sports/<sport>/feature_engineering/` prend donc en entrée les **canonical facts et derived datasets déjà produits par la gateway**, pas le JSON brut d'un provider.

De même, `calibration/` est à la racine du projet (§7.1) et non dans chaque sport : la machinerie est générique, seuls les résultats sont indexés par `(sport, market_type, model_version)`.

### 6.2 Feature Engineering — au niveau de l'événement

Les features ne sont pas portées par une entité isolée. Un modèle football regarde deux équipes ; un modèle tennis deux joueurs ; un modèle baseball deux équipes **plus** un pitcher partant par camp. Une structure `entity_id → features` obligerait chaque modèle à recomposer lui-même l'événement, ce qui déplacerait de la logique métier dans les modèles.

```python
@dataclass(frozen=True)
class EventFeatureSet:
    event_id: str
    sport: str
    as_of: datetime                     # cohérent avec available_to_model_time de la gateway —
                                         # aucune feature ne doit utiliser une donnée postérieure
    feature_set_version: str

    event_features: dict[str, float | str | bool]
    """Features de l'événement lui-même : surface, indoor, importance du tour,
    jours depuis le dernier match pour chaque camp, park factor..."""

    participant_features: dict[str, dict[str, float | str | bool]]
    """{canonical_id du participant: ses features} — Elo par surface, forme,
    hold/break %, ERA du pitcher..."""

    matchup_features: dict[str, float | str | bool]
    """Features qui n'existent qu'en relation : head-to-head, différentiel d'Elo,
    historique sur cette surface entre ces deux joueurs précis."""

    missing_features: set[str]
    """Features attendues mais indisponibles — consommé par assess_data_readiness
    et remonté dans PredictionExplanation (§7)."""
```

La distinction `event` / `participant` / `matchup` évite le principal piège : un head-to-head n'appartient à aucun des deux participants, il n'existe que dans leur relation.

Exemples de features par sport, calculées à partir des faits canoniques et datasets dérivés fournis par la gateway :
- **Tennis** : Elo par surface, forme sur 10 matchs, hold/break %, fatigue (jours de repos, temps passé sur le court), indoor/outdoor.
- **Baseball** : ERA/FIP du starter, forme du bullpen, splits gaucher/droitier, park factor, météo.
- **Football** (migration de l'existant) : forces d'attaque/défense Dixon-Coles, forme récente pondérée.

---

## 7. Market Model — remplace `SportModel`

Le PRD précédent définissait un `SportModel` unique par sport. C'était trop grossier : un modèle "1X2" et un modèle "Over/Under 2,5" pour le même match de football n'ont pas les mêmes variables, pas le même historique de calibration, pas le même taux de réussite. Le contrat est donc défini **par marché**, pas par sport :

```python
class DataReadiness(Enum):
    SUPPORTED = "SUPPORTED"
    EXPERIMENTAL = "EXPERIMENTAL"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    UNSUPPORTED = "UNSUPPORTED"

@dataclass(frozen=True)
class PredictionExplanation:
    """Pourquoi ce modèle a produit cette probabilité. Sans ça, dans six mois,
    « pourquoi Axon conseille ce pari ? » n'a pas de réponse consultable."""
    top_features: list[tuple[str, float]]   # (nom de feature, contribution) — les plus influentes
    missing_features: set[str]              # features attendues mais absentes (issu de EventFeatureSet)
    warnings: list[str]                     # ex. "pitcher partant non confirmé",
                                             # "classement vieux de 12 jours", "surface inhabituelle"
    confidence_drivers: list[str]           # ce qui resserre ou élargit l'intervalle de probabilité

@dataclass(frozen=True)
class MarketPrediction:
    sport: str
    market_type: str
    selection: str
    fair_probability: float
    probability_low: float
    probability_high: float
    model_version: str
    data_quality: float
    calibration_status: DataReadiness
    explanation: PredictionExplanation      # jamais optionnel

class MarketModel(Protocol):
    sport: str
    market_type: str                    # un seul market_type par implémentation
    model_version: str

    def required_features(self) -> set[str]:
        ...

    def assess_data_readiness(self, event: CanonicalEvent, features: EventFeatureSet) -> DataReadiness:
        ...

    def predict(self, event: CanonicalEvent, market: CanonicalMarket,
                features: EventFeatureSet, point_in_time: datetime) -> MarketPrediction:
        """point_in_time obligatoire — aucune donnée postérieure à cet instant ne doit
        entrer dans la prédiction, cohérent avec available_to_model_time de la gateway."""
        ...
```

`explanation` n'est pas optionnel : un modèle qui ne sait pas expliquer sa sortie ne peut pas être audité, donc ne peut pas passer `SUPPORTED`.

Chaque sport enregistre ses `MarketModel` dans son `manifest.py` : `sports/tennis/market_models/match_winner.py`, `sports/tennis/market_models/total_games.py`, `sports/football/market_models/one_x_two.py`, `sports/football/market_models/over_under_2_5.py`, `sports/football/market_models/btts.py`, etc. Le routage se fait par `(sport, market_type)` — si aucun `MarketModel` n'est enregistré pour ce couple, le marché est `UNSUPPORTED` par défaut, sans qu'aucun code supplémentaire ne soit nécessaire pour le refuser explicitement.

### 7.1 Calibration — machinerie partagée, résultats par marché

`calibration/` (racine du projet) contient la machinerie générique — walk-forward, isotonic regression/Platt scaling, comparaison de modèles, détection de drift — réutilisée par tous les sports et tous les marchés. Chaque `MarketModel` s'appuie sur cette machinerie mais possède son **propre historique et son propre statut de calibration** : la calibration du marché "vainqueur du match" en tennis est indépendante de celle du marché "total de jeux", même si les deux utilisent le même moteur Elo par surface en interne.

**Métriques suivies par marché, dès le premier `MarketModel` livré :**
- Brier score et log loss
- Closing-line value (CLV) — comparaison à la cote de clôture, pas seulement la cote au moment du pari
- Calibration curve (probabilité prédite vs fréquence réelle), walk-forward strict grâce à `point_in_time` obligatoire

Aucun `MarketModel` n'est considéré `SUPPORTED` sans historique de calibration walk-forward documenté.

### 7.2 Experiment Registry — mémoire des modèles testés

La calibration dit si un modèle est bon *aujourd'hui*. Elle ne dit pas pourquoi `tennis_match_winner_v7` a remplacé `v6`. Dans deux ans, sans trace, cette information est perdue — et le risque concret est de réessayer une approche déjà invalidée, ou d'abandonner une piste qui marchait pour une mauvaise raison.

```python
@dataclass(frozen=True)
class ModelExperiment:
    experiment_id: str
    sport: str
    market_type: str
    model_version: str                  # ex. "tennis_match_winner_v7"
    parent_version: str | None          # de quoi il dérive
    created_at: datetime

    description: str                    # ce qui a changé par rapport au parent
    hypothesis: str                     # ce qu'on cherchait à améliorer

    evaluation_window: tuple[datetime, datetime]
    metrics: dict[str, float]           # brier, log_loss, clv_mean, calibration_error...
    n_predictions: int

    status: Literal["candidate", "promoted", "rejected", "superseded"]
    decision_rationale: str             # pourquoi promu ou rejeté
```

Toute promotion d'un `model_version` en production écrit une entrée. Un modèle rejeté reste dans le registre — c'est justement la trace la plus utile plus tard. `model_comparison.py` s'appuie sur ce registre plutôt que sur des comparaisons ad hoc.

---

## 8. Value Engine + Bet Ranking

```python
@dataclass(frozen=True)
class BettingDecision:
    selection: str
    bookmaker_odds: float
    model_probability: float
    probability_interval: tuple[float, float]
    expected_value: float
    data_quality: float
    model_reliability: float            # issu de calibration/, propre au (sport, market_type)
    decision: Literal["BET", "WATCH", "ABSTAIN"]
    reason: str
```

Règle de décision (inchangée dans son principe par rapport au PRD précédent, reformulée pour référencer un `MarketModel` plutôt qu'un `SportModel`) :

1. Si `assess_data_readiness` ≠ `SUPPORTED` → `ABSTAIN`, raison = statut du marché.
2. `expected_value` calculé à la borne basse de `probability_interval`, jamais à la moyenne — un edge qui disparaît à la borne basse ne doit jamais produire `BET`.
3. `BET` seulement si EV (borne basse) > seuil ET `data_quality` > seuil ET `model_reliability` (calibration historique du couple sport/marché) > seuil.
4. `WATCH` si EV moyen positif mais un des seuils précédents non atteint.
5. Sinon `ABSTAIN`.

`bet_ranking.py` consomme les `BettingDecision` de tous les marchés/sports actifs, applique les contraintes d'exposition (§9) et produit le classement final des opportunités du moment — c'est la sortie visible par Kaine.

---

## 9. Portfolio & Exposure

Trois recommandations peuvent sembler indépendantes tout en portant le même risque :

```
Djokovic gagne le match     cote 1.45
Djokovic gagne 3-0          cote 2.80
Plus de 38 jeux             cote 1.90
```

Ce sont trois sélections, un seul événement, et une exposition largement commune (les deux premières sont fortement corrélées positivement ; la troisième est corrélée négativement avec la deuxième). Un classement qui les présente comme trois opportunités distinctes donne une illusion de diversification.

Ce module ne gère **pas** la bankroll ni le sizing (hors scope, cf. §3) — il répond à une question plus étroite : *quelle est l'exposition réelle, et quelles sélections ne doivent pas être proposées ensemble ?*

```python
@dataclass(frozen=True)
class ExposureView:
    event_id: str
    participant_ids: list[str]
    selections: list[str]                # sélections recommandées touchant cet événement
    correlation_matrix: dict[tuple[str, str], float]
    aggregate_exposure_note: str         # explication lisible de l'exposition combinée
```

Responsabilités :
- **`portfolio/correlation.py`** — estime la corrélation entre sélections d'un même événement. Les corrélations structurelles (« 3-0 » implique « victoire ») sont déclarées par le module sportif, pas devinées ; les corrélations statistiques sont estimées à partir de l'historique.
- **`portfolio/exposure.py`** — agrège les expositions par événement et par participant, et fournit à `bet_ranking.py` les contraintes : ne pas classer deux sélections fortement corrélées comme deux opportunités indépendantes ; signaler quand plusieurs recommandations reposent sur le même participant.

**Règle appliquée par `bet_ranking.py`** : parmi un groupe de sélections corrélées au-delà d'un seuil configuré, une seule est présentée comme opportunité principale (celle de meilleure EV ajustée), les autres sont rattachées à ce groupe avec leur corrélation affichée, jamais listées comme des lignes indépendantes.

---

## 10. Exigences

### 10.1 Fonctionnelles

| # | Exigence | Priorité |
|---|---|---|
| BE-FR-001 | Aucun fichier de `axon-sports-data-gateway` (`core/`, `cache/`, `providers/`, `normalizers/`) n'est modifié ; seules des données peuvent y être ajoutées | Must |
| BE-FR-002 | `bookmakers/` expose un contrat `BookmakerConnector` ; ajouter un bookmaker ne modifie aucune autre couche | Must |
| BE-FR-003 | Tout événement bookmaker est rattaché à un `canonical_event_id` via le `bookmaker_registry` ; un rattachement non résolu n'est jamais utilisé | Must |
| BE-FR-004 | `CanonicalEvent.context` est un objet typé et versionné par sport, jamais un `dict` libre | Must |
| BE-FR-005 | Chaque participant porte un `role` déclaré par le module sportif (`home`/`away`, `player_a`, `starting_pitcher`…) | Must |
| BE-FR-006 | Les features sont produites au niveau de l'événement (`EventFeatureSet` : event / participant / matchup), jamais par entité isolée | Must |
| BE-FR-007 | Un `MarketModel` couvre exactement un couple `(sport, market_type)` ; l'absence d'implémentation vaut `UNSUPPORTED` sans code dédié | Must |
| BE-FR-008 | `MarketModel.predict` prend `point_in_time` en paramètre obligatoire ; aucune donnée postérieure n'entre dans la prédiction | Must |
| BE-FR-009 | `MarketPrediction.explanation` est non optionnel et non vide pour tout modèle `SUPPORTED` | Must |
| BE-FR-010 | Toute mise en production d'un `model_version` crée une entrée dans l'`experiment_registry` avec son `decision_rationale` | Must |
| BE-FR-011 | Aucun `BET` n'est émis sur un marché `EXPERIMENTAL`, `INSUFFICIENT_DATA` ou `UNSUPPORTED` | Must |
| BE-FR-012 | L'`expected_value` déclenchant un `BET` est calculée à la borne basse de `probability_interval`, jamais à la moyenne | Must |
| BE-FR-013 | Des sélections corrélées au-delà du seuil configuré sont regroupées par `portfolio/`, jamais classées comme opportunités indépendantes | Must |
| BE-FR-014 | Toute sortie `BET` reste une proposition soumise à validation humaine ; aucun placement automatique | Must |
| BE-FR-015 | `odds_history` conserve les cotes observées de l'ouverture à la clôture, en append-only | Should |
| BE-FR-016 | Le classement final expose, pour chaque opportunité, sa provenance de données, sa fraîcheur et son explication | Should |
| BE-FR-017 | Un `MarketModel` live n'est développé que si sa version pré-match du même marché est déjà `SUPPORTED` ; il n'existe pas de modèle live sans référence pré-match validée | Must |
| BE-FR-018 | Une offre boostée (`OddsSnapshot.is_boosted=True`) n'est jamais évaluée par retrait de marge standard ; elle est comparée au `fair_odds` du marché sous-jacent déjà `SUPPORTED` (via `boost_reference_odds` si connue), et ses `max_stake`/`max_payout` (si présents) sont propagés jusqu'à `bet_ranking.py` | Must |

### 10.2 Non-fonctionnelles

- **BE-NFR-001 · Déterminisme** — à `EventFeatureSet`, `point_in_time` et `model_version` identiques, la `MarketPrediction` est identique.
- **BE-NFR-002 · Traçabilité de décision** — toute `BettingDecision` archivée permet de reconstituer a posteriori : cotes utilisées, features, version de modèle, statut de calibration, raison de la décision.
- **BE-NFR-003 · Isolation par sport** — la défaillance d'un module sportif n'interrompt ni le scan du catalogue, ni les autres sports.
- **BE-NFR-004 · Séparation des responsabilités** — aucun normalizer de données sportives brutes n'existe dans ce projet (ils vivent dans la gateway, cf. `ADR-003`).
- **BE-NFR-005 · Versioning** — `context_version`, `feature_set_version` et `model_version` sont explicites ; une incompatibilité échoue bruyamment.
- **BE-NFR-006 · Observabilité** — chaque décision expose les seuils appliqués et le critère ayant produit `BET`/`WATCH`/`ABSTAIN`.
- **BE-NFR-007 · Reproductibilité des backtests** — un backtest relancé sur la même fenêtre et les mêmes versions produit les mêmes métriques.

---

## 11. Rollout — tranche verticale, un seul marché de bout en bout

Toujours Winamax + tennis en priorité (préférence confirmée), mais désormais explicitement **un seul marché**, pas "le tennis" en bloc :

**Étape 1 — Scanner Winamax (sans prédiction)**
- `bookmakers/winamax/connector.py`, `market_normalizer.py`, `odds_history.py`
- Inventaire fiable de tous les sports/marchés/cotes réellement proposés, aucune mise, aucune prédiction

**Étape 2 — Rattachement identitaire**
- `bookmaker_registry.py` : mapping des événements Winamax tennis vers `canonical_event_registry`, participants résolus via `axon-sports-data-gateway.identity_resolver` (ajout des joueurs/tournois ATP/WTA à son registre existant — modification de la gateway limitée à l'ajout de données, pas de code, cf. §1)

**Étape 3 — Contexte + feature engineering tennis**
- `sports/tennis/context_schema.py` : `TennisEventContext` versionné (surface, best_of, indoor, tour)
- `sports/tennis/feature_engineering/` : `EventFeatureSet` (event / participant / matchup) — Elo par surface, forme récente, indicateurs de fatigue, head-to-head — à partir des faits canoniques et datasets dérivés fournis par la gateway

**Étape 4 — Un seul `MarketModel`**
- `sports/tennis/market_models/match_winner.py` uniquement — pas les autres marchés tennis en parallèle
- `PredictionExplanation` produite dès cette étape, pas ajoutée après coup
- Statut `EXPERIMENTAL` (cf. taxonomie §7)

**Étape 5 — Calibration + Experiment Registry**
- `calibration/experiment_registry.py` opérationnel dès le premier modèle — la première entrée est `tennis_match_winner_v1`, pas une reconstruction a posteriori
- Backtests walk-forward, Brier score, CLV
- Passage `EXPERIMENTAL` → `SUPPORTED` uniquement après validation documentée, avec `decision_rationale` écrit dans le registre

**Étape 6 — Value Engine + Portfolio + Bet Ranking sur ce seul marché**
- `value_engine/` puis `portfolio/` (exposition et corrélation) branchés avant `bet_ranking.py`
- Pipeline complet vérifié de bout en bout sur des événements réels : `BET`/`WATCH`/`ABSTAIN` cohérents, sélections corrélées regroupées et non listées comme indépendantes

**Étape 7+ — Extension (Vague 1 : plus de marchés/sports pré-match)**
- Deuxième marché tennis (ex. total de jeux), puis deuxième sport (baseball probablement, cf. préférence), en suivant exactement le même gabarit. Le football, déjà construit côté gateway, peut être branché en migrant Dixon-Coles vers un `MarketModel` (`sports/football/market_models/one_x_two.py`) sans statut prioritaire.

**Vague 2 — Live et cotes boostées (après qu'au moins un marché soit `SUPPORTED`)**
- Prérequis explicite : au moins un `MarketModel` pré-match `SUPPORTED`, pas seulement `EXPERIMENTAL` (cf. §4.4bis).
- **Live d'abord sur ce même marché** : `LiveMatchState`, révision continue de la prédiction pré-match, mesure de latence de décision. Reste `EXPERIMENTAL` jusqu'à sa propre calibration (le live a sa propre courbe de calibration, distincte du pré-match, cf. §7.1).
- **Cotes boostées ensuite** : `is_boosted`/`boost_reference_odds`/`max_stake`/`max_payout` sur `OddsSnapshot` (pas un `market_type` séparé), propagation de ces plafonds jusqu'à `bet_ranking.py`, comparaison à `fair_odds` du marché sous-jacent déjà validé plutôt qu'à une probabilité implicite classique.
- Ne pas ouvrir le live ou les cotes boostées sur un deuxième marché avant que le premier couple (marché pré-match + son extension live/boost) soit lui-même stable — même logique de tranche verticale étroite que le reste du PRD.

---

## 12. Intégration dans l'architecture Axon existante

Cohérent avec le README actuel (orchestrateur LangGraph, agents par domaine sous `src/agents/`, HITL, mémoire persistante `.axon/memory/`) :

- **Nouveaux agents** suivant la convention existante — probablement `src/agents/betting_engine/` (ou éclaté selon la granularité retenue à l'implémentation, cf. décision ouverte §15).
- **HITL** : toute sortie `BET` de `bet_ranking.py` reste une proposition affichée à Kaine, jamais une action automatique — cohérent avec le pattern déjà en place (`propose_file_change`). Pas de "propose_bet → placement automatique" (cf. non-objectifs §3).
- **Mémoire** : les décisions et leurs résultats effectifs alimentent `.axon/memory/` pour que la calibration bénéficie du même mécanisme que le reste d'Axon.
- **README** : toujours désynchronisé des fonctionnalités paris (gateway v1 + ce PRD). Reste une tâche de documentation distincte, à ne pas oublier une fois l'étape 6 fonctionnelle.

---

## 13. Risques

| Risque | Impact | Mitigation |
|---|---|---|
| Méthode d'accès au catalogue Winamax non officielle (pas d'API publique documentée) | Fragilité technique, question ToS à clarifier | À trancher explicitement avant l'étape 1 — préalable, pas un détail d'implémentation |
| Deux registres (`Competition Registry` côté gateway, `Bookmaker Registry` côté betting-engine) qui divergent avec le temps | Un événement mal rattaché produit une prédiction sur les mauvaises données | `bookmaker_registry` référence toujours `competition_id` de la gateway par ID, jamais par nom recopié ; tests de cohérence entre les deux registres |
| La frontière normalizers (gateway) / feature_engineering (betting-engine) posée en §6.1 est mal comprise à l'implémentation et un normalizer finit dupliqué dans les deux projets | Retour du mélange de responsabilités que ce PRD cherche justement à éviter | Règle explicite et documentée (§1, §6.1) ; revue de code dédiée sur ce point précis avant la fin de l'étape 3 |
| `EventContext` d'un sport évolue sans incrémenter `context_version` | Features calculées sur des champs absents ou réinterprétés — bugs silencieux dans `feature_engineering` | `context_version` obligatoire, échec explicite sur version incompatible ; validateur par sport (`sports/<sport>/validators/`) |
| Un `MarketModel` produit une `PredictionExplanation` vide ou générique | L'auditabilité annoncée n'existe pas en pratique — impossible de comprendre une recommandation six mois plus tard | `explanation` non optionnel dans `MarketPrediction` ; contenu non vide vérifié comme critère de passage `SUPPORTED` |
| Sur-confiance dans un `MarketModel` non encore calibré | `BET` recommandé sur un edge illusoire | Statuts `EXPERIMENTAL` → `SUPPORTED` stricts, jamais de `BET` sans historique de calibration walk-forward |
| Corrélation entre sélections du même événement traitées comme indépendantes dans le classement | Sur-exposition perçue comme diversifiée | Module `portfolio/` dédié (§9), dans le scope explicite de l’étape 6, pas différé |
| Un `MarketModel` live est développé avant que sa version pré-match soit calibrée | Aucune référence fiable à réviser, edge live illusoire, latence de décision mal maîtrisée | BE-FR-017 : blocage explicite, contrôlé au niveau du `manifest.py` du sport concerné |
| Une offre boostée est évaluée comme une cote classique (retrait de marge standard) | EV calculé faux — le boost n'est pas une probabilité de marché honnête | BE-FR-018 : comparaison au `fair_odds` du marché sous-jacent uniquement, jamais à une `implied_probability` naïve sur une offre `is_boosted=True` |
| `max_stake`/`max_payout` d'une offre boostée non propagés jusqu'au classement | Une opportunité plafonnée classée au même niveau qu'une opportunité pleinement exploitable | `max_stake`/`max_payout` champs explicites distincts de `OddsSnapshot`, vérifiés en critère de succès (§14) |

---

## 14. Critères de succès

- Le scanner Winamax produit un inventaire fiable, sans erreur de rattachement identitaire entre `bookmaker_registry` et `canonical_event_registry`.
- Un seul `MarketModel` (tennis, vainqueur du match) passe `SUPPORTED` après calibration walk-forward documentée (Brier score, CLV positif en moyenne).
- Le pipeline complet (`bookmakers` → `axon-sports-data-gateway` → `feature_engineering` → `MarketModel` → `calibration` → `value_engine` → `bet_ranking`) fonctionne de bout en bout sur des événements réels.
- Aucune ligne de code de `axon-sports-data-gateway` (`core/`, `cache/`, `providers/`, `normalizers/`) n'a été modifiée pour livrer ce PRD — seules des données (identités, compétitions) y ont été ajoutées.
- Un deuxième `MarketModel` (même sport, marché différent) peut être ajouté sans modifier `bookmakers`, `value_engine`, ni `bet_ranking`.
- Toute recommandation `BET` est accompagnée d'une `PredictionExplanation` non vide (top features, warnings, données manquantes) consultable a posteriori.
- Chaque `model_version` mise en production a une entrée dans l'`experiment_registry` avec son `decision_rationale`.
- Deux sélections fortement corrélées d'un même événement ne sont jamais présentées comme deux opportunités indépendantes dans le classement.
- Ajouter un deuxième bookmaker ne demande qu'un nouveau dossier `bookmakers/<nom>/` implémentant `BookmakerConnector`, sans modification du reste du pipeline.

---

## 15. Décisions ouvertes

1. **Méthode d'accès au catalogue Winamax** (API non documentée, scraping) — préalable technique et légal à trancher avant l'étape 1.
2. **Granularité des agents Axon** : un agent `betting_engine/` global ou plusieurs agents suivant la découpe de ce PRD (`bookmakers/`, `value_engine/`, `portfolio/`) — à trancher à l'implémentation.
3. **Seuils de décision** (EV minimal, data_quality minimale, model_reliability minimale pour `BET`) — non fixés ici, à calibrer une fois qu'il y a un historique réel de décisions.
4. **Fréquence de scan Winamax** (temps réel vs polling) — impacte directement `odds_history`, à trancher selon les contraintes techniques de l'étape 1.
5. **Emplacement de la machinerie de calibration partagée** : un seul module `calibration/` à la racine (retenu dans ce PRD, §7.1) vs dupliquée par sport — à revalider une fois qu'un deuxième sport est en place, si des besoins de calibration trop spécifiques à un sport apparaissent.
