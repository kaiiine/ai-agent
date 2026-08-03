# Dette technique

Défauts identifiés, diagnostiqués, et volontairement non corrigés. Chaque entrée
porte le diagnostic complet pour que la correction ne demande pas de refaire
l'enquête.

---

## DETTE-001 — I/O à l'import dans `checkpoint.py` et `google_auth.py`

**Identifié le** 2026-08-03, en auditant les tests après le chantier MCP.
**Statut :** ouvert, hors périmètre MCP, antérieur au chantier.
**Gravité :** faible en production, gênante en test.

### Constat

Quatre fichiers de test écrivent sous `~/` alors qu'aucun ne le demande. Mesuré
en rejouant la suite complète avec `HOME` détourné vers un répertoire vide, puis
en inventoriant fichier de test par fichier de test :

| Test | Créé sous `~/` |
|---|---|
| `tests/test_mcp_commands.py` | `~/.axon/`, `~/.axon/memory.db`, `~/.ai-agent/` |
| `tests/test_mcp_registry.py` | `~/.axon/`, `~/.axon/memory.db`, `~/.ai-agent/` |
| `tests/test_key_pool_fallback.py` | `~/.ai-agent/` |
| `tests/test_us_leagues_live.py` | `~/.axon/sports_provider_coverage.db` |

Les tests ne sont pas en cause : ils importent des modules dont l'import a des
effets de bord sur le système de fichiers.

### Cause exacte

Deux modules exécutent des I/O **au niveau module**, donc à l'import :

```
src/infra/checkpoint.py:27    _AXON_DIR.mkdir(parents=True, exist_ok=True)
src/infra/checkpoint.py:30    _conn = sqlite3.connect(str(_DB_PATH), ...)   -> crée ~/.axon/memory.db

src/infra/google_auth.py:15   TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)   -> crée ~/.ai-agent/
```

### Cascade qui propage l'effet de bord

```
tests/test_mcp_registry.py     (CachedToolNode)
tests/test_mcp_commands.py     (handle_slash)
        │
        ├─ src/ui/commands.py ─┐
        └─ src/orchestrator/graph.py
                │
                ├─ graph.py:521  from src.infra.checkpoint import build_checkpointer
                │                     └─ checkpoint.py:27,30   ->  ~/.axon/memory.db
                │
                └─ graph.py:531  from src.orchestrator.registry import build_all_tools
                                     └─ registry.py:60  src.agents.gmail.tools
                                        registry.py:61  src.agents.google_drive.tools
                                            └─ from src.infra.google_auth import …
                                                └─ google_auth.py:15  ->  ~/.ai-agent/
```

`tests/test_key_pool_fallback.py` emprunte la seconde branche : il importe
`src.orchestrator.registry.build_all_tools` dans un test. Importer
`src.llm.key_pool` seul ne crée rien — vérifié.

### Hors périmètre de cette dette

`tests/test_us_leagues_live.py` crée `~/.axon/sports_provider_coverage.db` par un
chemin différent :
[`provider_coverage_registry.py:19`](../src/agents/quant/gateway/registries/provider_coverage_registry.py#L19)
n'ouvre rien à l'import — la base est créée à l'**appel**, `_connection()` acceptant
déjà un `db_path` injectable. C'est le test qui n'injecte pas de chemin
temporaire ; le correctif y est local au test, pas au module.

### Correctif proposé

**Connexion paresseuse**, pas de contournement côté tests. Le contournement
(`monkeypatch` de `HOME`, fixture globale) masquerait le défaut sans le corriger
et laisserait le prochain import problématique passer inaperçu.

- `checkpoint.py` : déplacer le `mkdir` et le `sqlite3.connect` dans
  `build_checkpointer()`, en mémorisant la connexion dans une variable de module
  au premier appel. `build_checkpointer()` n'est appelé que par
  `build_orchestrator()`, donc jamais pendant un simple import.
- `google_auth.py` : déplacer le `mkdir` dans la fonction qui écrit réellement le
  token.

Aucune signature publique ne change. Un test de non-régression naturel :
importer `src.orchestrator.graph` avec `HOME` détourné ne doit rien créer.

### Pourquoi ce n'est pas corrigé

Défaut antérieur au chantier MCP, sans rapport avec lui, et sans conséquence en
production — les répertoires créés à l'import sont ceux que l'application
utilisera de toute façon. Correction à planifier hors d'un lot fonctionnel.
