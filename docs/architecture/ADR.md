# Architecture Decision Records — Axon (domaine paris sportifs)

Chaque ADR documente **une décision structurante**, son contexte, les alternatives écartées et ce qu'elle coûte. Le but n'est pas de justifier après coup, mais de pouvoir répondre dans deux ans à « pourquoi c'est fait comme ça ? » — y compris pour se rendre compte qu'une décision n'est plus valable.

**Format** : Contexte → Décision → Alternatives écartées → Conséquences (bonnes et mauvaises) → Statut.

| # | Décision | Statut |
|---|---|---|
| [ADR-001](#adr-001) | Séparer `sports-data-gateway` et `betting-engine` en deux projets | Accepté |
| [ADR-002](#adr-002) | `MarketModel` par marché, et non `SportModel` par sport | Accepté |
| [ADR-003](#adr-003) | Les features vivent dans le betting-engine, pas dans la gateway | Accepté |
| [ADR-004](#adr-004) | `point_in_time` obligatoire sur tout le chemin de prédiction | Accepté |
| [ADR-005](#adr-005) | Modules sportifs (`SportModule`), pas adaptateurs | Accepté |
| [ADR-006](#adr-006) | Sélection de provider hiérarchique, pas par score composite | Accepté |
| [ADR-007](#adr-007) | Couverture provider modélisée par saison et type de donnée | Accepté |
| [ADR-008](#adr-008) | Espaces de noms d'identité typés | Accepté |
| [ADR-009](#adr-009) | Schémas canoniques versionnés | Accepté |
| [ADR-010](#adr-010) | Partir du catalogue bookmaker, pas du calendrier sportif mondial | Accepté |
| [ADR-011](#adr-011) | Aucune donnée inventée : `stale=True` ou échec explicite | Accepté |
| [ADR-012](#adr-012) | Structure multi-bookmaker dès le départ | Accepté |
| [ADR-013](#adr-013) | Explicabilité obligatoire dans chaque prédiction | Accepté |
| [ADR-014](#adr-014) | Pas de placement automatique de pari | Accepté |
| [ADR-015](#adr-015) | Ordre des participants Winamax : slots génériques + traduction par SportModule | Accepté |

---

## ADR-001
### Séparer `axon-sports-data-gateway` et `axon-betting-engine` en deux projets

**Contexte.** Le projet a démarré comme une couche de données sportives. En s'étendant (modèles probabilistes, cotes, calcul de valeur), la gateway commençait à absorber des responsabilités qui n'étaient plus les siennes. Un premier PRD (`axon-betting-platform`) faisait encore raisonner l'ensemble en partant de la gateway.

**Décision.** Deux projets distincts, avec une direction de dépendance stricte : `axon-betting-engine` **dépend de** `axon-sports-data-gateway`, jamais l'inverse. La gateway ignore totalement l'existence du betting-engine.

**Alternatives écartées.**
- *Un seul projet monolithique* : plus simple au début, mais la gateway aurait fini par contenir modèles sportifs, logique bookmaker et calculs de valeur — exactement la dette qu'on cherche à éviter.
- *Betting-engine comme sous-module de la gateway* : conserve l'inversion de dépendance problématique.

**Conséquences.**
- ✅ La gateway reste réutilisable par n'importe quel consommateur, pas seulement un moteur de paris.
- ✅ Une modification du betting-engine ne peut pas casser le pipeline de données déjà validé sur données réelles.
- ✅ Critère de non-régression mesurable : « aucune ligne de `core/`, `cache/`, `providers/` modifiée ».
- ⚠️ Coût de coordination : ajouter un sport touche les deux projets (module gateway + module betting-engine). Assumé.
- ⚠️ Risque de duplication accidentelle des normalizers si la frontière est mal comprise — mitigé par ADR-003.

**Statut.** Accepté.

---

## ADR-002
### `MarketModel` par marché, et non `SportModel` par sport

**Contexte.** Une première version définissait un modèle par sport (`SportModel`), exposant tous ses marchés. Or, pour un même match de football, « 1X2 », « Over/Under 2,5 » et « BTTS » n'ont ni les mêmes variables déterminantes, ni le même historique de fiabilité, ni la même difficulté.

**Décision.** Le contrat est défini par couple `(sport, market_type)`. Un `MarketModel` = un marché. Le routage se fait par ce couple ; l'absence d'implémentation vaut `UNSUPPORTED` par défaut.

**Alternatives écartées.**
- *Un `SportModel` exposant `supported_markets()`* : masque le fait que la fiabilité varie énormément d'un marché à l'autre au sein d'un même sport. Un modèle tennis excellent sur « vainqueur » peut être médiocre sur « total de jeux », et un statut global mentirait sur l'un des deux.

**Conséquences.**
- ✅ Calibration, statut et fiabilité suivis à la bonne granularité — celle où la décision de parier se prend.
- ✅ Refuser un marché non modélisé devient le comportement par défaut, sans code.
- ✅ Ajouter un marché n'oblige pas à toucher aux modèles existants du même sport.
- ⚠️ Plus de fichiers et de duplication potentielle entre marchés proches d'un même sport (ex. deux marchés dérivant d'une même distribution de scores). Mitigé en factorisant les calculs communs dans `feature_engineering/` ou un module partagé du sport, pas dans les modèles eux-mêmes.

**Statut.** Accepté.

---

## ADR-003
### Les features de modèle vivent dans le betting-engine, pas dans la gateway

**Contexte.** La frontière entre « donnée normalisée » et « feature de modèle » est floue par nature. Un premier découpage plaçait `surface`, `ranking`, `head_to_head` et `service_hold_pct` au même niveau, alors qu'il s'agit respectivement d'un fait événementiel, d'un snapshot temporel, d'un calcul dérivé et d'un agrégat sur fenêtre.

**Décision.** Trois niveaux explicitement séparés :

```
Canonical facts  →  Derived datasets   │  →  Model features  →  Market models
────── axon-sports-data-gateway ─────  │  ──── axon-betting-engine ────
```

**Règle opérationnelle** : un *derived dataset* est une fonction **pure et déterministe** des faits canoniques + une fenêtre temporelle. S'il nécessite un paramètre appris, une pondération entraînée ou un modèle, ce n'est pas un dérivé — c'est une feature, et elle appartient au betting-engine.

**Alternatives écartées.**
- *Tout mettre dans la gateway* : elle serait devenue un feature engine caché, couplé aux besoins d'un seul consommateur.
- *Tout mettre dans le betting-engine* : chaque consommateur recalculerait les mêmes agrégats de base, avec des définitions divergentes de « forme récente ».

**Conséquences.**
- ✅ Le critère de tri est objectif et vérifiable en revue de code (« ce calcul a-t-il un paramètre appris ? »).
- ✅ Les datasets dérivés sont recalculables à tout moment depuis les faits, donc reproductibles.
- ⚠️ La frontière reste la zone la plus susceptible d'être franchie par inadvertance — d'où une revue de code dédiée à ce point précis dans les deux PRD.

**Statut.** Accepté.

---

## ADR-004
### `point_in_time` obligatoire sur tout le chemin de prédiction

**Contexte.** Un backtest qui utilise, même partiellement, une information indisponible au moment du pari produit des résultats excellents et faux. C'est le mode d'échec le plus dangereux du domaine, car il ne provoque aucune erreur visible — juste une confiance injustifiée.

**Décision.**
- Le `point_in_time_store` est append-only et conserve cinq horodatages distincts (`event_time`, `published_time`, `available_to_model_time`, `fetched_at`, `ingested_at`).
- `available_to_model_time` est la référence du walk-forward.
- `MarketModel.predict(...)` prend `point_in_time` en paramètre **obligatoire**, non optionnel.
- Une donnée postérieure au `point_in_time` demandé est écartée, et ne déclenche **pas** de fallback (une autre source ne rendrait pas la donnée légitime).

**Alternatives écartées.**
- *Un seul `fetched_at`* : ne distingue pas l'âge du cache de l'âge réel de l'information. Un classement publié il y a trois jours et récupéré il y a dix secondes a un `fetched_at` récent et un contenu périmé.
- *`point_in_time` optionnel avec valeur par défaut « maintenant »* : rend la fuite de données possible par omission, donc inévitable à terme.

**Conséquences.**
- ✅ Les backtests walk-forward sont structurellement corrects, pas correct-par-discipline.
- ✅ Le calcul de closing-line value devient possible (comparer la prédiction à la cote de clôture).
- ⚠️ Coût de stockage supérieur (append-only, snapshots multiples) — mitigé par la déduplication `content_hash`.
- ⚠️ Toute API interne doit propager `point_in_time`, ce qui alourdit les signatures. Assumé : c'est précisément le but.

**Statut.** Accepté.

---

## ADR-005
### Modules sportifs (`SportModule`), pas adaptateurs

**Contexte.** La couche par sport avait d'abord été nommée `SportAdapter`. Le terme évoque le pattern *Adapter* (GoF), dont le rôle est de faire correspondre une interface incompatible à une autre. Ce n'est pas ce que fait cette couche : elle regroupe le schéma canonique du sport, ses normalizers, ses calculateurs dérivés, ses validateurs.

**Décision.** Renommer en `SportModule` / module sportif. Registre `SPORT_MODULES`, accès via `get_sport_module(sport)` qui lève `UnsupportedSportError` plutôt que de renvoyer `None`.

**Alternatives écartées.**
- *Garder `SportAdapter`* : induit en erreur sur la nature de la couche.
- *`SportPlugin`* : suggère un chargement dynamique à l'exécution, non retenu (les modules sont déclarés statiquement dans le registre).

**Conséquences.**
- ✅ Le nom décrit ce que fait la chose : un module métier par sport.
- ✅ `get_sport_module` isole la défaillance d'un sport (un module cassé n'interrompt pas les autres).
- ⚠️ Renommage sur des documents déjà relus. Coût ponctuel, fait avant toute implémentation.

**Statut.** Accepté.

---

## ADR-006
### Sélection de provider hiérarchique, pas par score composite

**Contexte.** Le choix entre plusieurs providers éligibles peut se faire par un score composite (`coverage × quality × freshness × quota − coût − latence`) ou par une cascade de critères ordonnés.

**Décision.** Cascade hiérarchique déterministe. Le score composite est explicitement différé, tant qu'il n'existe pas de données réelles pour calibrer le poids relatif de chaque facteur.

**Alternatives écartées.**
- *Score composite immédiat* : élégant sur le papier, mais les facteurs n'ont pas la même échelle. Un `normalized_cost` mal calibré peut rendre le classement arbitraire — et un classement arbitraire est indébogable.
- *Arbitrage par coût seul* : ferait toujours préférer un provider gratuit incomplet à un provider payant fiable, ce qui est faux dès qu'une décision financière est en jeu.

**Conséquences.**
- ✅ Sélection reproductible et auditable : on peut toujours dire quel critère a tranché.
- ✅ Testable simplement (un test par critère).
- ⚠️ Moins fin qu'un score : deux providers proches sont départagés par un critère qui n'est peut-être pas le plus pertinent. Acceptable tant que le nombre de providers reste faible.
- 🔄 À revisiter quand il y aura assez d'observations réelles pour calibrer un score.

**Statut.** Accepté, à revisiter.

---

## ADR-007
### Couverture provider modélisée par `(provider, compétition, saison, data_type)`

**Contexte.** La v1 traitait la couverture comme binaire : un provider couvre une compétition, ou non. La réalité observée est plus fine — le plan gratuit d'API-Football sert les saisons 2022-2024 et refuse 2025+, et un provider peut fournir les résultats d'une compétition sans fournir ses compositions.

**Décision.** Clé de couverture à quatre dimensions, avec un `CoverageStatus` (`FULL`/`PARTIAL`/`ABSENT`/`UNVERIFIED`) par combinaison, plus `verified_at` et `verification_method`. Une couverture n'est activable qu'après vérification par appel réel (`live_call`) — la documentation du provider ne suffit pas.

**Alternatives écartées.**
- *`providers: dict[str, str]` sur la compétition* : incapable d'exprimer « couvert pour les résultats mais pas pour les compositions », ni la variation par saison.
- *Un score unique `coverage_quality: float`* : ne répond à aucune des questions qui comptent (calculé comment, pour quelle saison, quel endpoint, mis à jour quand).

**Conséquences.**
- ✅ Le cas réel qui a motivé toute la refonte (saison en cours inaccessible) est modélisable.
- ✅ Le fallback peut écarter un provider sans consommer de requête.
- ⚠️ Volume d'entrées important — généré par script, pas saisi à la main.
- ⚠️ Nécessite une revérification périodique : les tiers gratuits changent sans préavis.

**Statut.** Accepté.

---

## ADR-008
### Espaces de noms d'identité typés

**Contexte.** Un bug réel rencontré en v1 : chez API-Sports, l'équipe Wolves et la compétition Premier League portent le même identifiant `39`. Avec un seul sport et un seul type d'entité, un identifiant plat suffisait ; avec joueurs, paires de double, combattants, tournois et lieux, les collisions deviennent structurellement probables.

**Décision.** Format imposé : `{entity_type}:{sport}:{scope}:{slug}` — ex. `player:tennis:atp:carlos_alcaraz`, `team:football:fra:psg`. Deux types d'entités ne peuvent jamais partager un espace de noms. Validation à l'écriture dans le registre.

**Alternatives écartées.**
- *Identifiants plats avec convention informelle* : la v1 a démontré que ça casse.
- *UUID opaques* : évite les collisions mais rend le registre illisible et le debug pénible.

**Conséquences.**
- ✅ Les collisions inter-types deviennent impossibles par construction, pas par vigilance.
- ✅ Les identifiants restent lisibles en debug et en revue de registre.
- ⚠️ Choix du `scope` à trancher par sport (circuit pour le tennis, pays pour le football de clubs). Décision ouverte dans le PRD gateway.

**Statut.** Accepté.

---

## ADR-009
### Schémas canoniques versionnés (`schema_version`, `context_version`)

**Contexte.** Le `point_in_time_store` conserve des snapshots indéfiniment, précisément pour permettre des backtests. Si le schéma d'un sport évolue, le code de lecture courant interpréterait des snapshots anciens écrits sous un autre schéma.

**Décision.** Chaque enveloppe porte un `schema_version` (`"tennis/1.2"`), chaque contexte d'événement un `context_version`. Une lecture sous version incompatible **échoue explicitement** (`is_schema_compatible`), au lieu d'interpréter.

**Alternatives écartées.**
- *Pas de versioning, migration systématique des anciens snapshots* : réécrire l'historique casse la propriété point-in-time qu'on cherche à préserver.
- *Versioning implicite par date* : ne dit rien de la compatibilité réelle entre deux schémas.

**Conséquences.**
- ✅ Le pire mode d'échec (backtest silencieusement faussé par une réinterprétation de schéma) devient un échec bruyant.
- ✅ On peut faire évoluer un modèle de sport sans peur de corrompre l'historique.
- ⚠️ Certains historiques deviennent inutilisables après un changement majeur — c'est le prix de l'honnêteté sur ce qu'on sait et ne sait pas.

**Statut.** Accepté.

---

## ADR-010
### Partir du catalogue bookmaker, pas du calendrier sportif mondial

**Contexte.** L'objectif « couvrir tous les sports » peut se lire de deux façons : collecter tous les événements sportifs existants, ou traiter tous les événements sur lesquels il est possible de parier.

**Décision.** L'univers de travail est le catalogue Winamax. Un événement qui n'y figure pas n'est pas modélisé, quelle que soit la richesse des données disponibles.

**Alternatives écartées.**
- *Collecte exhaustive puis filtrage* : le monde sportif contient des millions d'événements par an, dont l'immense majorité n'est jamais pariable. Coût de collecte et de stockage sans contrepartie.

**Conséquences.**
- ✅ Le périmètre de travail est fini, connu, et directement corrélé à l'usage.
- ✅ Les priorités de développement se déduisent du catalogue réel (quels sports/marchés sont effectivement proposés).
- ⚠️ Dépendance à la disponibilité du catalogue bookmaker — d'où ADR-012.
- ⚠️ Un événement retiré du catalogue disparaît de l'univers de travail : l'historique doit être conservé indépendamment (`odds_history` append-only).

**Statut.** Accepté.

---

## ADR-011
### Aucune donnée inventée : `stale=True` explicite ou échec typé

**Contexte.** Quand aucune source ne peut répondre, un système peut : renvoyer une valeur par défaut, extrapoler, ou refuser. Dans un contexte de pari, une valeur inventée produit une probabilité fausse présentée comme fiable.

**Décision.** Trois comportements possibles, jamais un quatrième :
1. Donnée fraîche → `DataEnvelope` normale.
2. Dernier snapshot connu, **même saison, schéma compatible** → `stale=True` explicite, le consommateur décide.
3. Rien d'exploitable → `NoDataAvailableError` typée.

Côté betting-engine, l'équivalent est `ABSTAIN` : ne pas recommander est un résultat valide, pas un échec.

**Alternatives écartées.**
- *Valeur par défaut ou moyenne de ligue* : produit une prédiction plausible et infondée. Pire que pas de prédiction.
- *Exception silencieuse ou `None`* : déplace la décision vers un appelant qui n'a pas le contexte.

**Conséquences.**
- ✅ Un bug réel a été attrapé grâce à cette règle : le fallback stale servait des données 2024 pour une requête 2026.
- ✅ Le système sait dire « je ne sais pas », ce qui est la propriété la plus importante ici.
- ⚠️ Plus de cas d'abstention visibles, ce qui peut donner l'impression d'un système peu productif. C'est le comportement voulu.

**Statut.** Accepté.

---

## ADR-012
### Structure multi-bookmaker dès le départ, Winamax seul implémenté

**Contexte.** Seul Winamax est utilisé. Coder un accès Winamax en dur serait plus rapide.

**Décision.** Le contrat `BookmakerConnector` et le registre `BOOKMAKERS` sont posés immédiatement ; seul `bookmakers/winamax/` existe réellement. **Aucun dossier vide n'est créé** pour les bookmakers non implémentés : l'extensibilité vient du contrat, pas de répertoires anticipés.

**Alternatives écartées.**
- *Coder Winamax en dur, généraliser plus tard* : la généralisation a posteriori d'un accès en dur est une migration structurelle, bien plus coûteuse que le contrat initial.
- *Créer d'avance les dossiers `betclic/`, `unibet/` vides* : donne l'illusion d'un support inexistant et encombre l'arborescence sans rien apporter.

**Conséquences.**
- ✅ Coût quasi nul aujourd'hui.
- ✅ Ouvre une capacité utile en soi : comparer les cotes entre bookmakers est un signal de valeur (une cote aberrante chez l'un se détecte par rapport aux autres).
- ⚠️ Une abstraction posée sur un seul cas réel risque d'être mal calibrée — le deuxième bookmaker révélera peut-être que le contrat doit changer. Accepté : le coût de correction reste faible.

**Statut.** Accepté.

---

## ADR-013
### Explicabilité obligatoire dans chaque prédiction

**Contexte.** Une probabilité seule (`0.61`) est ininterprétable a posteriori. Six mois après, face à une recommandation, il est impossible de savoir si elle reposait sur des données solides ou sur un artefact.

**Décision.** `PredictionExplanation` est un champ **non optionnel** de `MarketPrediction` : top features contributives, features manquantes, warnings, facteurs d'incertitude. Un modèle incapable de la produire ne peut pas passer `SUPPORTED`.

**Alternatives écartées.**
- *Explicabilité optionnelle, ajoutée après coup* : ne serait jamais implémentée pour les modèles existants, donc absente précisément là où l'historique compte.
- *Logs de debug seulement* : non structurés, non requêtables, perdus à la rotation.

**Conséquences.**
- ✅ Une recommandation passée reste auditable.
- ✅ Les warnings (« pitcher partant non confirmé », « classement vieux de 12 jours ») deviennent des signaux exploitables par le `value_engine`, pas seulement de l'affichage.
- ⚠️ Contrainte sur le choix des modèles : un modèle purement boîte noire est plus difficile à qualifier. Assumé — c'est un critère de sélection légitime dans ce domaine.

**Statut.** Accepté.

---

## ADR-014
### Pas de placement automatique de pari

**Contexte.** Le pipeline produit un classement de recommandations. L'étape suivante naturelle serait de placer les paris automatiquement.

**Décision.** Hors scope. Axon recommande (`BET` / `WATCH` / `ABSTAIN`), l'exécution reste manuelle. Cohérent avec le pattern HITL déjà en place dans Axon (`propose_file_change` → validation humaine).

**Alternatives écartées.**
- *Placement automatique sous seuil de confiance* : ajoute une classe de risques entièrement différente (gestion de bankroll, limites du bookmaker, conditions d'utilisation, irréversibilité) à un système dont les modèles ne sont pas encore calibrés.

**Conséquences.**
- ✅ Toute erreur du système reste rattrapable par un humain avant qu'elle coûte quelque chose.
- ✅ Permet de faire tourner le système en observation (paper trading) pendant la phase de calibration.
- ⚠️ Une opportunité peut disparaître entre la recommandation et l'action manuelle. Acceptable tant que la fiabilité des modèles n'est pas démontrée.
- 🔄 À revisiter uniquement après une période documentée de calibration positive, et avec un ADR dédié sur les aspects bankroll et conditions d'utilisation.

**Statut.** Accepté, à revisiter.

---

## ADR-015
### Ordre des participants Winamax : slots génériques + traduction par le SportModule

**Contexte.** Le catalogue Winamax expose chaque événement avec `competitor1` / `competitor2`. Pour rattacher ces événements à des `CanonicalEvent.participants` (avec leur `role`, cf. `PRD-axon-betting-engine.md` §6.2), il faut décider comment ordonner/nommer ces deux participants. Tentation : figer `competitor1 → home`, `competitor2 → away`. Deux problèmes : (1) est-ce empiriquement fiable ? (2) « home »/« away » n'a pas de sens pour tous les sports (tennis, combats).

**Vérification empirique (menée, pas supposée).** Croisement des matchs Winamax à venir avec les fixtures football-data.org (dont `homeTeam`/`awayTeam` est fiable), par date + paire d'équipes non ordonnée, sur les compétitions couvertes :

| Compétition | competitor1 = homeTeam |
|---|---|
| Ligue 1 | 3/3 · Premier League 10/10 · Bundesliga 4/4 · Serie A 3/3 |
| LaLiga | 7/7 · Championship 12/12 · Eredivisie 8/8 · Primeira 2/2 |
| **Total** | **49/49 = 100,0 %** |

Sur 49 matchs de 8 compétitions, `competitor1` correspond **toujours** à l'équipe à domicile, jamais inversé. Réserve honnête : échantillon de début de saison (journées 1-2, hors-saison), et le contre-check identité-based (résolution en `canonical_id`) n'a pu confirmer sur Ligue 1 (0 overlap résolu : équipes 2026-27 hors du registre 2025-26). Le résultat name-based multi-ligues fait donc foi ; une re-vérification en pleine saison est recommandée.

**Décision.**
1. **Le connecteur/normalizer Winamax préserve l'ordre BRUT en slots génériques** : `competitor1 → slot_1`, `competitor2 → slot_2`. **Aucune sémantique home/away à ce niveau** — un normalizer sport-agnostique ne suppose jamais un « domicile ».
2. **Chaque `SportModule` traduit les slots vers `EventParticipant.role`** :
   - football : `slot_1 → home`, `slot_2 → away` (justifié par le 100 % ci-dessus) ;
   - tennis : `slot_1 → player_a`, `slot_2 → player_b` — **jamais** de home/away fictif ;
   - autres sports : leur propre rôle déclaré.
3. **Filet de repli** : le mapping football `slot_1 = home` repose sur ce 100 % empirique. Si une re-vérification (pleine saison, échantillon plus large) tombe sous 100 %, le module football **doit** basculer sur un mapping **identité-based** (résoudre les noms en `canonical_id`, prendre le home/away d'un provider de stats comme vérité) plutôt que de se fier à l'ordre brut.

**Alternatives écartées.**
- *`competitor1 = home` universel, tous sports confondus* : invente un « domicile » là où il n'existe pas (tennis) — faux modèle.
- *Se fier à l'ordre brut sans vérification* : risquait un décalage systématique non détecté.
- *Mapping identité-based dès le départ* : plus robuste mais exige chaque équipe résolue ; le 100 % empirique montre que l'ordre brut suffit pour le football, avec l'identité-based comme repli documenté.

**Conséquences.**
- ✅ Normalizer sport-agnostique (slots), sémantique dans le `SportModule` — cohérent avec `EventParticipant.role`.
- ✅ Aucun home/away fictif sur les sports qui n'en ont pas.
- ✅ Décision ancrée dans une mesure réelle (49/49), avec un critère de bascule clair si elle se dégrade.
- ⚠️ L'actuel `odds_fetcher.py` étiquette déjà `home`/`away` en dur : provisoire, à remplacer par les slots génériques dans le futur `WinamaxNormalizer` (côté betting-engine, cf. ADR-001).
- ⚠️ Échantillon début de saison : re-vérifier en pleine saison (déclencheur du repli identité-based).

**Statut.** Accepté.
