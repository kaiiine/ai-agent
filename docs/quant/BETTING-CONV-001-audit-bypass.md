# BETTING-CONV-001 — Audit du chemin conversationnel : le premier bypass

**Statut** : audit clos, correctifs en cours.
**Portée** : chemin `User → UI → graphe LangGraph → tools → réponse`, comparé au chemin
produit `axon recommend` (Betting Engine → Adapter → Advisor).

---

## 1. Le graphe réel

```
StateGraph(GlobalState)                       src/orchestrator/graph.py:467
  ├── node "chatbot"                          :468
  └── node "tools" (CachedToolNode)           :469
  START → chatbot                             :471
  chatbot → tools_condition                   :472        (tool_calls ? "tools" : END)
  tools  → chatbot                            :473
```

Deux nœuds. **Aucun nœud final**, aucun renderer, aucune validation de sortie.
Lorsque le LLM n'émet plus de `tool_calls`, `tools_condition` route vers `END` et
le `content` de l'`AIMessage` **est** la réponse affichée. Rien ne le lit, rien ne
le contraint.

## 2. Surface d'outils exposée au LLM

90 tools enregistrés (`src/orchestrator/registry.py`), dont 6 pour le betting
(`:263-268`) :

| Tool | Signature | Ce qu'il rend |
|---|---|---|
| `winamax_odds_fetch` | `(sport, team)` | catalogue brut **+ `implied_probability` = 1/cote** |
| `sports_stats_fetch` | `(home_team, away_team, competition)` | forme récente |
| `probability_compute` | `(home_team, away_team)` | probas structurées d'**un** match |
| `ev_analyze` | `(home_team, away_team, market, odds)` | décision d'**une** sélection |
| `same_match_combo_analyze` | `(home_team, away_team, markets_json, …)` | jambes d'**un** match |
| `parlay_analyze` | `(legs_json, …)` | jambes de matchs **déjà nommés** |

Les six sont correctement reroutés vers le structuré : `tools.py` ne calcule
aucune proba, aucun EV, aucun Kelly. **Ce n'est pas là qu'est la faille.**

## 3. Le premier bypass — exact

> **Aucun outil du graphe n'atteint l'Advisor. Le seul chemin qui sait
> scanner, classer et dimensionner est lié à `sys.argv`, pas à un `@tool`.**

Preuve mécanique — occurrences de `advisor` hors de son propre package, dans
toute la couche conversationnelle (`src/orchestrator/`, `src/agents/`,
`src/llm/`, `src/ui/`) :

```
src/ui/main.py:28:    from src.agents.quant.advisor.cli import main as _advisor_recommend
src/ui/main.py:29:    sys.exit(_advisor_recommend(sys.argv[2:]))
```

Deux lignes, toutes deux **à l'intérieur** de :

```python
if len(sys.argv) > 1 and sys.argv[1] == "recommend":     # src/ui/main.py:25
```

Le graphe ne peut pas les atteindre. `RecommendationResponse`, `audit_id`,
`RecommendationOutcome`, le Combo Builder, le sizing Advisor, les caps de
bankroll : **rien de tout cela n'existe dans l'espace d'outils du LLM.**

### 3.1 Pourquoi cela produit exactement le dump observé

Requête : *« 20 € de bankroll, 20 € de freebets, scanne tout aujourd'hui et
demain, tous sports et toutes compétitions, propose ce qu'Axon peut honnêtement
recommander »*.

1. `ev_analyze` / `parlay_analyze` exigent `home_team` et `away_team` **connus
   d'avance**. Aucun n'énumère un catalogue.
2. Le LLM ne peut donc pas satisfaire la demande. Il appelle `ask_clarification`
   — *« proposez-moi 2 à 4 matchs »* — ce qui **inverse la demande** : on
   demandait à Axon de trouver, Axon demande à l'utilisateur de trouver.
3. L'utilisateur répond « tout me va, tous les sports ». La clarification ne
   débloque rien : le tool manquant reste manquant.
4. Le seul outil qui accepte « tous les sports » est `winamax_odds_fetch`. Il
   rend un catalogue **avec `implied_probability` déjà calculée** (`tools.py:81`).
5. À partir de là, le LLM dispose de tout ce qu'il faut pour terminer seul :
   des matchs, des cotes, et une « probabilité ». Il classe, combine, dimensionne
   et rédige. **Rien en aval ne l'en empêche.**

Le bypass n'est donc pas une désobéissance du modèle à son prompt. C'est un
**trou de surface** : la demande produit est irréalisable avec les outils
fournis, et le seul outil atteignable livre l'ingrédient exact de l'EV fictive.

## 4. Réponses factuelles aux six questions

| # | Question | Réponse |
|---|---|---|
| 1 | Le Betting Engine est-il réellement appelé ? | **Seulement** si le LLM appelle `ev_analyze`/`probability_compute` avec deux noms d'équipes qu'il possède déjà. Sur une requête de scan : non. |
| 2 | L'Advisor est-il réellement appelé ? | **Jamais.** Zéro import depuis la couche conversationnelle. |
| 3 | Le nœud final reçoit-il une `RecommendationResponse` ? | **Il n'y a pas de nœud final.** |
| 4 | Le LLM peut-il recommander sans cette réponse ? | **Oui, sans aucune contrainte.** |
| 5 | Peut-il écrire « ev_analyze a retourné BET » sans ToolMessage ? | **Oui.** Aucune vérification de provenance n'existe. |
| 6 | Le legacy peut-il produire un pari indépendant ? | `tools.py` est proprement rerouté (aucune math locale). Mais `winamax_odds_fetch` **expose `1/cote` comme probabilité**, ce qui suffit au LLM pour le faire à sa place. |

## 5. Défaut de second rang — la chaîne de résolution n'est toujours pas unique

`BookmakerEventResolver` accepte un `competition_resolver` injectable dont le
défaut résout par identifiant de tournoi bookmaker (table des sports de ligue).
Quatre sites le construisent :

| Site | `competition_resolver` | Conséquence |
|---|---|---|
| `structured_decision.py:133` | `resolve_competition_any_sport` | ✅ |
| `betting_engine/cli.py:104` | `resolve_competition_any_sport` | ✅ |
| `advisor/cli.py:142` | **absent** | tennis → `comp=None` → `EVENT_NOT_RESOLVED` |
| `clv/cli.py:58` | **absent** | idem sur la collecte CLV |

Deux agrégateurs d'identité coexistent également (`all_sport_teams`,
`all_known_entities`). Le chemin `axon recommend` — celui vers lequel il faut
rerouter — souffre donc **encore** de la divergence corrigée ailleurs : le
rerouter sans le réparer d'abord ne ferait que déplacer le zéro.

## 6. Conclusion — ordre imposé par l'audit

1. **Fermer la chaîne de résolution** (4 sites → 1 fabrique), sinon le reroutage
   pointe vers un pipeline qui n'évalue rien en tennis.
2. **Créer le tool structuré manquant** : c'est l'absence de ce tool, et non le
   prompt, qui produit la réponse libre.
3. **Garde de provenance programmatique** : le prompt seul ne peut pas fermer un
   trou de surface, et n'aura jamais de valeur de preuve.

---

# Après

## 7. Le chemin, désormais

```
demande utilisateur
  → UserBettingConstraints          (state typé, fusionné entre les tours)
  → TimeWindow                      (Europe/Paris, résolue en absolu)
  → RecommendationRequest
  → scan Winamax multisport         (filtré par la fenêtre AVANT évaluation)
  → Betting Engine → Adapter → Advisor
  → RecommendationResponse + BettingResponseEvidence
  → renderer déterministe
  → garde de provenance             (remplace toute réponse non sourcée)
```

`src/agents/quant/conversation/` : `window.py`, `constraints.py`, `session.py`,
`recommend.py`, `renderer.py`, `evidence.py`, `guard.py`, `tools.py`.

## 8. Chaîne de résolution — un seul site

`BookmakerEventResolver(` n'apparaît plus qu'une fois dans tout `src/`, à
l'intérieur de `sports/registry.build_event_resolver()`. Les cinq chemins qui
scannent du live (unitaire, batch, `axon recommend`, collecte CLV,
conversationnel) le citent. Verrouillé par
`tests/test_pipeline_convergence.py`, qui compte les sites plutôt que d'inspecter
leurs arguments — le cinquième site réintroduirait l'oubli.

`all_sport_teams` énumérait les référentiels à la main et produisait le même
ensemble que le registre ; il délègue désormais, au lieu d'être maintenu en
parallèle.

## 9. Run réel, chaîne complète

```
status : COMPLETED    outcome : REVIEW_CANDIDATES    audit : audit:091276d9…
fenêtre  : 6 août 2026, 16:45 → 7 août 2026, 23:59 (Europe/Paris)
sports   : american_football, baseball, basketball, football, hockey, tennis, volleyball
événements : 756 scannés · 130 dans la fenêtre · 76 sélections évaluées
portefeuilles : 0        mises : aucune
```

Aucun modèle n'étant SUPPORTED, `maturity_decision` rend `REVIEW_ONLY`, et un
`REVIEW_ONLY` ne produit aucun portefeuille. Le zéro mise est donc mécanique, pas
une politique de prudence ajoutée par-dessus.

## 10. Ce qui reste ouvert

- **Freebet** : STOP money assumé — voir `BETTING-CONV-002-fork-freebet.md`.
- **Routing** : `tests/test_tool_routing.py` échoue sur 4 cas **à HEAD**, sans
  rapport avec cette mission (vérifié dans un worktree propre à `HEAD` et après
  reconstruction complète de l'index). Dérive du corpus d'embedding, à traiter
  dans sa propre vague.
