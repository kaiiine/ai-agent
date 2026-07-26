# PRD — Axon Cron : tâches planifiées avec LLM

## Problème

Axon est réactif — il répond quand on lui parle. Mais beaucoup de tâches utiles sont proactives :
surveiller un score en direct, rappeler un événement, envoyer un résumé quotidien, alerter si un prix dépasse un seuil, vérifier périodiquement une CI. Aujourd'hui : impossible sans intervention manuelle.

---

## Vision

L'utilisateur dit à Axon en langage naturel ce qu'il veut surveiller ou être rappelé. Axon comprend, crée une tâche planifiée, l'exécute en background avec accès à ses outils (recherche web, shell, Gmail…) et notifie via desktop ou Slack quand il y a quelque chose à dire.

---

## Exemples d'usage

```
› Surveille le score France-Espagne toutes les 5 minutes et notifie-moi dès qu'il change
› Rappelle-moi dans 2h d'appeler Pierre au sujet du contrat
› Chaque matin à 8h30 : résume mes emails non lus et envoie-les moi sur Slack
› Vérifie toutes les heures si ma PR #42 a été mergée, notifie si oui
› Alerte-moi si le prix du BTC dépasse 100k$ (vérifie toutes les 10 min)
› Surveille les logs de prod toutes les 15 min et notifie si erreur critique
```

---

## Architecture

### Vue d'ensemble

```
Axon (terminal)
    │
    │  schedule_task(description, prompt, interval, channels)
    ▼
~/.axon/crons.json          ← stockage persistant des tâches
    │
    ▼
axon-cron (daemon)          ← processus léger, lancé au démarrage système
    │
    ├── APScheduler         ← exécution à l'heure prévue
    │
    ├── LLM + outils        ← analyse + décision de notifier
    │       (web_search, shell_run, gmail_search, etc.)
    │
    └── Notifications
            ├── notify-send (desktop)
            └── slack_send_message (si configuré)
```

### Composants

#### 1. `schedule_task` — outil Axon

L'outil que le LLM appelle quand l'utilisateur demande une tâche planifiée.

```python
@tool
def schedule_task(
    description: str,     # Libellé humain : "Surveille score France-Espagne"
    prompt: str,          # Ce que le daemon doit faire/vérifier à chaque tick
    interval_seconds: int,# Fréquence (300 = toutes les 5 min)
    notify_channels: list,# ["desktop", "slack"] — au moins un
    run_at: str = "",     # ISO datetime pour one-shot (vide = répétitif)
    stop_condition: str = "",  # Optionnel : "si la France a gagné, stop"
) -> str
```

Écrit dans `~/.axon/crons.json`, retourne l'ID de la tâche.

---

#### 2. `~/.axon/crons.json` — stockage

```json
[
  {
    "id": "cron_abc123",
    "description": "Score France-Espagne",
    "prompt": "Recherche le score actuel France vs Espagne. Si le score a changé depuis la dernière fois, notifie avec le score et le temps de jeu. Dernière valeur connue : {last_result}",
    "interval_seconds": 300,
    "notify_channels": ["desktop", "slack"],
    "run_at": null,
    "stop_condition": "si le match est terminé",
    "created_at": "2026-07-21T15:00:00",
    "last_run": null,
    "last_result": "",
    "active": true
  }
]
```

---

#### 3. `axon-cron` — daemon

Processus Python léger (`src/cron_daemon.py`), tourne en background.

**Boucle principale :**
```
toutes les 10s : relit crons.json → pour chaque tâche active dont next_run ≤ now :
    1. Injecte {last_result} dans le prompt
    2. Invoque le LLM avec accès aux outils (web_search, shell, gmail…)
    3. Le LLM décide : "notify: oui/non" + contenu
    4. Si notify → envoie via les canaux configurés
    5. Sauvegarde last_result + last_run
    6. Vérifie stop_condition → désactive si remplie
```

**LLM système du daemon (léger, fast) :**
```
Tu es un agent de monitoring. Exécute la tâche demandée.
Réponds UNIQUEMENT en JSON :
{
  "notify": true/false,
  "message": "texte de la notification (court, max 200 chars)",
  "result_summary": "état actuel à mémoriser pour la prochaine exécution",
  "stop": true/false
}
```

---

#### 4. Gestion du daemon

**Démarrage :**
```bash
axon-cron start    # lance en background, PID dans ~/.axon/cron.pid
axon-cron stop     # arrête
axon-cron status   # liste les tâches actives + prochaine exécution
```

**Autostart (optionnel, proposé à l'install) :**

Systemd user service (`~/.config/systemd/user/axon-cron.service`) :
```ini
[Unit]
Description=Axon Cron Daemon

[Service]
ExecStart=/home/user/Documents/projets-perso/ai-agent/venv/bin/python src/cron_daemon.py
Restart=always

[Install]
WantedBy=default.target
```
```bash
systemctl --user enable --now axon-cron
```

---

#### 5. Commandes Axon

| Commande | Action |
|----------|--------|
| `/cron` | Liste les tâches actives (id, description, prochaine exécution) |
| `/cron stop <id>` | Désactive une tâche |
| `/cron pause <id>` | Met en pause sans supprimer |
| `/cron log <id>` | Affiche les dernières exécutions |

---

## Plan d'implémentation

### Phase 1 — Stockage + outil (2-3h)

- [ ] `src/agents/cron/tools.py` — `schedule_task`, `list_tasks`, `stop_task`
- [ ] `src/agents/cron/store.py` — lecture/écriture `~/.axon/crons.json` avec verrou fichier
- [ ] Enregistrement dans `registry.py` + `tool_retriever.py`
- [ ] Prompt système : détecter les intentions "surveille / rappelle / chaque jour…" et appeler `schedule_task`

### Phase 2 — Daemon (3-4h)

- [ ] `src/cron_daemon.py` — boucle APScheduler, reload du JSON, invocation LLM
- [ ] Gestion `{last_result}` dans le prompt (contexte inter-exécutions)
- [ ] Notification desktop (`notify-send`) + Slack (`slack_send_message`)
- [ ] Gestion `stop_condition` — eval par le LLM, désactivation auto
- [ ] PID file + signal handling (SIGTERM graceful)

### Phase 3 — Intégration (1h)

- [ ] `axon-cron` CLI wrapper dans `setup.sh`
- [ ] Commandes `/cron`, `/cron stop`, `/cron log` dans `commands.py`
- [ ] Option systemd dans `setup.sh` (prompt : "Démarrer axon-cron au login ? [y/N]")

---

## Dépendances à ajouter

```
apscheduler>=3.10
```

APScheduler est léger, pas de serveur, pure Python.

---

## Considérations

**Coût LLM :** chaque exécution = 1 appel LLM. Pour des tâches fréquentes (toutes les 5 min), préférer un modèle rapide/gratuit (Gemini Flash, Mistral Small). Le daemon choisit le backend configuré — envisager une option `cron_backend` dans `base.yaml`.

**Sécurité :** `prompt` est du texte libre — le daemon doit éviter les injections de prompt via les résultats de recherche. Wrapper les résultats d'outils dans `[TOOL_RESULT]...[/TOOL_RESULT]` avant injection.

**Offline :** si pas de connexion, la tâche est retentée au prochain tick sans erreur.

**One-shot vs répétitif :** `run_at` non vide = exécution unique à une datetime précise (rappel dans 2h). Vide = répétitif avec `interval_seconds`.

---

## Points ouverts à spécifier

### 1. Schéma de log pour `/cron log <id>`

Chaque exécution est appendée dans `~/.axon/cron_logs/<id>.jsonl` (un objet JSON par ligne) :

```json
{
  "ts": "2026-07-21T15:05:00",
  "status": "ok",
  "notified": true,
  "message": "France 1 - 0 Espagne (32')",
  "result_summary": "France 1 - Espagne 0, 32e minute",
  "duration_ms": 1840,
  "error": null
}
```

`status` : `"ok"` | `"error"` | `"skipped"` (stop_condition remplie) | `"no_change"` (notify=false).

`/cron log <id>` affiche les N dernières entrées (défaut : 10) en tableau Rich, triées du plus récent au plus ancien.

---

### 2. Rattrapage au redémarrage du daemon

**Règle : skip, jamais de rattrapage automatique.**

Justification : une tâche manquée pendant que le daemon était down est dans un état inconnu. Ré-exécuter immédiatement risque de notifier sur une donnée périmée, ou de déclencher plusieurs fois un one-shot.

**Comportement concret au démarrage du daemon :**

- **Tâche répétitive** (`run_at` vide) : `next_run` est recalculé à `now + interval_seconds`. Toutes les exécutions manquées sont ignorées. Une entrée `"status": "skipped", "error": "daemon was down"` est écrite dans le log pour chaque tick manqué (estimé).
- **Tâche one-shot** (`run_at` non vide, dans le passé) : marquée `active: false` avec `status: "skipped"` dans le log. L'utilisateur reçoit une notification desktop : *"Tâche [description] n'a pas pu s'exécuter (daemon inactif). Recréer ?"*

---

### 3. Drift d'intervalle

APScheduler en mode `BackgroundScheduler` avec `IntervalTrigger` est précis à la seconde et **ne dérive pas** — il calcule `next_run = last_run + interval`, pas `next_run = now + interval`. Le drift dû à la durée d'exécution de la tâche est donc absorbé.

Le risque vient de la **boucle de reload à 10s** en surcouche : si une nouvelle tâche est ajoutée au JSON alors qu'APScheduler tourne déjà, le reload pourrait reschedule le job et décaler son `next_run`. Fix : lors du reload, ne toucher que les jobs **nouveaux ou supprimés** — ne jamais modifier le `next_run` d'un job existant déjà schedulé.
