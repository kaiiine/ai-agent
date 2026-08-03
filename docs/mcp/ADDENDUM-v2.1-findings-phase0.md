# Addendum v2.1 — Corrections issues du spike Phase 0

**Statut :** Phase 0 validée le 2026-08-03, `call_tool` réussi contre BlenderMCP 1.29.0 (protocole 2025-11-25, 22 tools).
**Portée :** corrige le PRD v2 et le Design Technique v2. À lire **avant** d'implémenter la Phase 1.
**Modifie :** DESIGN §3, §4, §5.3, §6, §7, §9.1, §10.2 · PRD §6.2, §6.4 · TEST-PLAN prérequis, tests 1/4/5

---

## Correction 1 (CRITIQUE) — `isError` n'est pas fiable

### Constat

Blender fermé, `get_scene_info` renvoie :

```
content : "Could not connect to Blender. Make sure the Blender addon is running."
isError : False        ← l'échec n'est PAS signalé par le protocole
```

L'échec applicatif remonte comme un succès protocolaire. Conséquences si on ne corrige rien :

- `MCPClientManager._log_invocation` logue `success: true` sur un appel raté → la provenance ment.
- Le LLM reçoit un message d'erreur en guise de résultat métier et va l'interpréter comme une donnée.
- La détection `DEGRADED` du §5.3, fondée sur `isError`, ne se déclenche **jamais**.

### Le piège à éviter dans la correction

La solution évidente serait un test sur le contenu dans `connection.py` :

```python
# ❌ INTERDIT — casse le milestone n°1
if "Could not connect to Blender" in text:
    ...
```

Toute chaîne spécifique à un serveur dans le code d'Axon fait échouer le critère « aucune connaissance Blender codée en dur ». Le mécanisme doit être générique, le contenu doit venir de la config.

### Correction retenue : health predicate déclaratif

**Ajout à `MCPServerConfig` (DESIGN §3) :**

```python
@dataclass
class MCPHealthPolicy:
    """Certains serveurs renvoient des échecs backend avec isError=False.
    Les patterns sont déclarés en CONFIG, jamais en code."""
    probe_tool: str | None = None            # tool read-only pour /mcp test --deep
    failure_patterns: list[str] = field(default_factory=list)
    consecutive_failures_to_degrade: int = 3


@dataclass
class MCPServerConfig:
    ...
    health: MCPHealthPolicy = field(default_factory=MCPHealthPolicy)
```

**Ajout à `ToolResult` (DESIGN §3)** — distinguer l'erreur protocolaire de l'erreur détectée :

```python
@dataclass
class ToolResult:
    ...
    is_error: bool = False           # isError du protocole MCP
    suspected_error: bool = False    # détecté par health predicate
    error_source: Literal["protocol", "heuristic", "timeout", "transport"] | None = None

    @property
    def failed(self) -> bool:
        return self.is_error or self.suspected_error
```

**Ajout à `adapter.py` (DESIGN §7) :**

```python
def apply_health_policy(result: ToolResult, policy: MCPHealthPolicy) -> ToolResult:
    """Générique. Les patterns viennent de la config du serveur."""
    if result.is_error:
        result.error_source = "protocol"
        return result
    if result.text and policy.failure_patterns:
        haystack = result.text.lower()
        if any(p.lower() in haystack for p in policy.failure_patterns):
            result.suspected_error = True
            result.error_source = "heuristic"
    return result
```

**Config Blender correspondante (DESIGN §10.2) :**

```json
"health": {
  "probe_tool": "get_scene_info",
  "failure_patterns": [
    "Could not connect to Blender",
    "Make sure the Blender addon is running"
  ],
  "consecutive_failures_to_degrade": 3
}
```

### §5.3 réécrit — détection de `DEGRADED`

```
ping OK  + N résultats consécutifs avec result.failed  →  DEGRADED
ping KO                                                 →  ERROR
result.failed == False                                  →  reset compteur, READY
```

`ping()` reste utile mais ne prouve toujours que la vivacité du process MCP, jamais celle du backend. C'est précisément la distinction que cette correction rend opérationnelle.

### Provenance (DESIGN §6.1)

```python
"success": not result.failed,
"error_source": result.error_source,
```

### Impact sur le LLM

Un `ToolResult` avec `failed == True` doit être présenté au modèle comme une **erreur d'outil**, pas comme un résultat. Sinon le LLM raisonne sur « Could not connect to Blender » comme s'il s'agissait de l'état de la scène.

---

## Correction 2 — Arguments requis, dérivation depuis `inputSchema`

### Constat

`get_scene_info` en 1.29.0 exige `user_prompt` (« required for telemetry »), **même avec `DISABLE_TELEMETRY=true`**. Un appel avec `{}` échoue en validation.

Le plan de test v2 indiquait `call_tool("get_scene_info", {})` : c'est faux et ça doit être corrigé.

### Portée réelle du problème

Ça dépasse Blender : n'importe quel serveur MCP peut exiger des paramètres inattendus. Le `--deep` du §9.1 ne peut donc pas appeler un tool avec un dict vide.

### Correction — `adapter.py`

```python
def derive_probe_arguments(schema: dict) -> dict:
    """Remplit les champs REQUIRED d'un inputSchema avec des valeurs
    bénignes typées. Générique : aucun nom de champ en dur."""
    args = {}
    props = schema.get("properties", {})
    for name in schema.get("required", []):
        spec = props.get(name, {})
        if "default" in spec:
            args[name] = spec["default"]
            continue
        if "enum" in spec:
            args[name] = spec["enum"][0]
            continue
        match spec.get("type"):
            case "string":  args[name] = "axon health probe"
            case "integer": args[name] = 0
            case "number":  args[name] = 0
            case "boolean": args[name] = False
            case "array":   args[name] = []
            case "object":  args[name] = {}
            case _:         args[name] = None
    return args
```

Utilisé par `probe_readonly_tool()` dans `/mcp test --deep`. Le tool sondé vient de `health.probe_tool`, ou à défaut du premier tool `risk_level == "read"`.

---

## Correction 3 — Environnement du sous-processus

### Constat

`env` dans `StdioServerParameters` **remplace** l'environnement, il ne le fusionne pas. Passer le bloc `env` de la §10.2 tel quel prive le sous-processus de `PATH`.

### Nuance

`build_subprocess_env()` (DESIGN §4) fusionnait déjà `os.environ`, donc le code du design n'était pas cassé. La correction est retenue pour une **autre raison, meilleure** : `os.environ` déverse l'intégralité de l'environnement — y compris des tokens sans rapport — dans chaque serveur MCP tiers. `get_default_environment()` du SDK renvoie un sous-ensemble assaini.

### Correction — `config.py`

```python
from mcp.client.stdio import get_default_environment

def build_subprocess_env(cfg: MCPServerConfig) -> dict[str, str]:
    """get_default_environment() plutôt que os.environ : sous-ensemble
    assaini par le SDK, évite de propager des secrets non liés au serveur.
    Le merge reste indispensable — StdioServerParameters REMPLACE l'env."""
    return {**get_default_environment(), **resolve_env(cfg.env)}
```

Si un serveur a besoin d'une variable absente du set par défaut, elle se déclare explicitement en config via `"MA_VAR": "${MA_VAR}"` — ce qui est le comportement souhaitable.

---

## Correction 4 — Session graphique obligatoire

### Constat

`blender -b` (background) ne fonctionnera jamais. L'addon renvoie l'exécution des commandes sur le thread principal via `bpy.app.timers.register` ; sans boucle principale, la socket accepte la connexion mais ne répond pas.

C'est une limite **structurelle**, pas un bug de configuration.

### Conséquences

- Prérequis du plan de test : « session graphique réelle ou xvfb » devient un prérequis dur, pas une remarque.
- Un timeout sur `call_tool` alors que la connexion socket a réussi est le symptôme typique du mode background → à ajouter aux pistes de debug du test 1.
- Aucune automatisation CI de la recette Blender sans `xvfb-run`.

### Ajout aux prérequis du plan de test

```
- [ ] Blender lancé en mode GRAPHIQUE (jamais -b / --background).
      En headless : xvfb-run blender. Le mode background fait timeouter
      tous les appels alors que la socket se connecte normalement.
```

---

## Correction 5 (mineure) — Normalisation du chemin résolu

`shutil.which` peut renvoyer un chemin non normalisé (`/home/kaine/.local/share/../bin/uvx`). La ligne `command resolved` de `/mcp test` sert au debug de PATH : elle doit être lisible.

```python
def resolve_command(command: str) -> str | None:
    import shutil, os
    path = shutil.which(command)
    return os.path.realpath(path) if path else None
```

---

## Hors périmètre

Blender 5.2 émet un `ModuleNotFoundError: cattrs` au registre de son addon core `bl_pkg`. Sans rapport avec MCP, non bloquant, aucune action côté Axon.

---

## Impact sur la Definition of Done (PRD §12)

Deux critères ajoutés :

- [ ] Un appel de tool avec Blender fermé produit `result.failed == True` et un log `success: false` — **sans** qu'aucune chaîne spécifique à Blender ne figure dans `axon/mcp/*.py`
- [ ] `grep -ri "blender" axon/mcp/` ne renvoie aucun résultat en dehors des commentaires

Le second est la formalisation directe du milestone n°1 et se vérifie en une commande.
