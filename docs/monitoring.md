# Supervision d'AXON

Ce qui est mesuré, ce qui ne l'est pas, et pourquoi Prometheus n'est pas là.

---

## Le principe

**Une ligne par action, `run_id` comme clé de regroupement**, écrite sur le
disque en JSONL par [`src/infra/trace.py`](../src/infra/trace.py). Tout le reste
— la relecture, l'alerting, l'export Langfuse, et un exportateur Prometheus le
jour où il se justifie — LIT ce fichier. Aucun consommateur n'est dans le chemin
critique d'un tour.

L'ordre n'est pas cosmétique. Brancher un traceur externe d'abord aurait paru
moins cher, mais aurait laissé le substrat à construire ensuite, en double.

### Ce qu'un traceur générique ne voit pas

LangSmith et Langfuse observent les appels LLM et les `tool_call`. Les décisions
d'AXON se prennent **entre** ces appels :

| Colonne | Qui la produit | Vue par un traceur générique |
|---|---|---|
| groupes élus + rang | `tool_retriever.get` | non |
| outils liés | `graph.chatbot` | non |
| rattrapage au catalogue | `graph.chatbot` | non |
| verdict de policy | statut rendu par l'outil | non |
| confirmation HITL | `revision.reviser` | non |
| résultat de `verifier()` | `verification.verifier` | non |
| tokens, latence, modèle | `invocation` | oui |

Les six premières lignes sont celles qui portent le diagnostic. C'est la raison
d'être du module.

### Le schéma

```
run_id · seq · at · source · projet · axon_sha
genre · intent · groupes · outils_lies · outil · cible
policy · confirmation · resultat · verification · erreur
tokens_entree · tokens_sortie · latence_ms · backend · modele · extra
```

`source` vaut `tui`, `cron`, `api` ou `mcp`. Elle isole d'un coup le chemin que
personne ne regarde.

`projet` est le dépôt d'où part le run, ou `—` hors dépôt. Ajoutée par
`feat/memory` : le journal d'incidents qui s'appuie dessus est global pour servir
d'une conversation à l'autre, et sans provenance il mélangerait des leçons qui ne
se transposent pas — le catalogue d'outils d'un dépôt n'est pas celui d'un autre.
Elle est résolue **à chaque run**, pas une fois par processus : l'agent shell
déplace le `cwd` en cours de session. Voir
[`docs/apprentissage.md`](apprentissage.md).

`verification` vaut `ok`, `casse`, ou **`none` écrit explicitement** quand rien
ne sait contrôler cette action. `verifier()` ne couvre aujourd'hui que `.py` et
`.json` : laisser un vide se relirait plus tard comme un succès. Le trou doit se
compter — c'est lui qui dira quand étendre VERIFY, et à quoi.

---

## Relire

```bash
axon trace                     # les derniers tours, action par action
axon trace <run_id>            # un tour en entier (préfixe accepté)
axon trace --route             # quel groupe gagne, à quel rang, et le filet
axon trace --outils            # par outil : ok / erreur / bloqué / latence
axon trace --llm               # tokens et latence par backend
axon trace --erreurs           # ce qui a raté, par outil et par cible
axon trace --source cron       # n'importe laquelle des vues, filtrée
```

`--route` porte la mesure que `graph.py` réclamait en commentaire depuis le
chantier de routage : **le taux de rattrapage au catalogue**. C'est lui qui dira
jusqu'où la sélection peut être resserrée — un filet qui sert souvent dit que le
budget est trop bas, un filet qui ne sert jamais dit qu'il peut baisser encore.
Jusqu'ici ce taux défilait à l'écran et disparaissait avec la session.

`AXON_TRACE=0` éteint tout. Allumée par défaut : éteinte, la trace serait
toujours absente le jour où la question se pose.

---

## Alerter

Seulement sur le démon cron. Le TUI n'en a pas besoin — l'utilisateur est devant
l'écran, une commande refusée s'affiche. Le démon tourne sans témoin, et c'est là
qu'une tâche a logué `status: "ok"` alors que **toutes** ses commandes avaient
été bloquées.

[`src/infra/alerte.py`](../src/infra/alerte.py) lit la trace du run qui vient de
finir et rend des raisons ; le démon les envoie sur les canaux de la tâche
(bureau, Slack). Déterministe, sans modèle : ce qui alerte doit être aussi fiable
que ce qu'il surveille.

| Signal | Seuil |
|---|---|
| outil refusé ou bloqué | toujours — avec le remède (`commandes_autorisees`) |
| outil en erreur | toujours, avec son code |
| fichier écrit mais cassé | toujours |
| appel modèle trop gros | `AXON_ALERTE_TOKENS`, défaut 12 000 |

Le seuil de tokens vient d'une mesure : le plancher de schémas d'outils
atteignait **30 outils / 12 731 tokens** sur une requête réelle, au-dessus de ce
que Groq accepte, sans que rien ne le signale.

Les raisons sont dédupliquées : dix commandes bloquées font une alerte, pas dix.
Une notification qu'on trouve bavarde finit coupée, et c'est le jour d'après
qu'elle aurait servi.

En `axon cron-test`, rien n'est envoyé : l'entrée de journal porte
`aurait_alerte`, comme elle porte déjà `aurait_notifie`.

---

## Exporter vers Langfuse (auto-hébergé)

```bash
axon trace --export-langfuse          # ce qui est nouveau depuis le dernier export
axon trace --export-langfuse --tout   # tout, depuis le début
```

```bash
# .env
LANGFUSE_HOST=http://localhost:3000
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
```

L'instance : `git clone https://github.com/langfuse/langfuse && cd langfuse &&
docker compose up -d`. Aucun `docker-compose.yml` n'est recopié ici — celui du
projet amont change avec ses versions, et une copie périmée dans ce dépôt serait
pire que pas de copie.

**Trois choix de forme**, chacun pour une raison :

- **Par lots, depuis le disque.** Pas de callback dans le graphe : AXON tourne
  sans Langfuse, hors ligne, sans rien perdre. Un capteur en ligne ferait
  dépendre le tour d'un service tiers — pour un journal, c'est inverser le
  rapport de force. Et l'export devient rejouable : instance éteinte, clé
  fausse, mauvaise URL, on relance.
- **L'API d'ingestion, pas le SDK.** Le client Python de Langfuse a changé
  d'interface entre ses majeures (v2 objet, v3 sur OpenTelemetry). L'endpoint,
  lui, prend un lot JSON en authentification basique. `requests` suffit, et il
  est déjà là — aucune dépendance ajoutée.
- **Identifiants déterministes.** `run_id` comme identifiant de trace,
  `run_id-seq` comme identifiant d'observation : Langfuse met à jour au lieu
  d'insérer, donc un double export ne fabrique pas de doublons.

Un refus part en `WARNING`, pas en `ERROR` : bloqué veut dire que le garde a fait
son travail, et le peindre en rouge noierait les vraies pannes.

> **Non éprouvé contre une instance réelle.** Aucun Langfuse ne tournait sur la
> machine au moment d'écrire ce module. Le lot est construit et sérialisé sous
> test ; l'envoi ne l'est pas. À vérifier au premier branchement.

---

## Prometheus et Grafana — écartés, et à quelle condition les reprendre

Pas un jugement de goût : trois désaccords de forme avec l'AXON d'aujourd'hui.

**1. Prometheus tire, le TUI ne tourne pas.** Prometheus scrute un endpoint HTTP
toutes les N secondes. Le processus où se prennent presque toutes ces décisions
est interactif, au premier plan, sans serveur, né et mort avec la session. Le
couvrir demanderait un Pushgateway — que la documentation de Prometheus
déconseille hors job batch, et qui perd l'identité par run. Les deux processus
qui lui conviendraient, `api_server.py` et `cron_daemon.py`, sont justement ceux
où il se passe le moins de choses.

**2. Les labels doivent rester à basse cardinalité ; les questions sont à haute
cardinalité.** `run_id`, la requête, l'argument d'un outil y sont proscrits — ils
font exploser la mémoire. Or toutes les questions de `CHANTIERS.md` sont de cette
forme : quels outils pour **cette** requête, quelle commande bloquée dans **cette**
tâche, pourquoi `calendar` sort cinquième sur sa propre requête. Prometheus sait
dire « 4 % de refus » ; il ne sait pas dire lequel, et le diagnostic est toujours
dans le lequel.

**3. Sur un utilisateur, un taux n'est pas une mesure.** Un panneau Grafana
calculé sur douze runs par jour est un tableau décoré.

### Le déclencheur

**Un processus long servant du trafic continu** : `api_server.py` ouvert à
plusieurs clients ou à un IDE en permanence, ou le démon cron à haute fréquence.
Alors cinq compteurs à basse cardinalité (`axon_tool_calls_total{outil,resultat}`,
`axon_llm_tokens`, `axon_cron_runs_total{status}`) dans **ces deux processus-là**
deviennent justes, et coûtent trois lignes parce qu'ils sont déjà longs.

La trace reste la source dans ce cas : l'exportateur lit ces lignes, il ne les
remplace pas.

---

## Ce qui n'est pas couvert

- **Le démon cron n'utilise pas `CachedToolNode`.** Il a son propre graphe
  (`create_react_agent`), donc ses appels d'outils ne passent pas par le point
  d'émission commun. Seuls ses refus et son verdict de tâche sont tracés, écrits
  à la main dans `cron_daemon.py`. Le jour où les deux graphes n'en font qu'un
  (`CHANTIERS.md` §2), ces lignes deviennent inutiles et doivent partir.
- **L'agent de code** est un sous-graphe avec ses propres outils : ses écritures
  sont tracées via `revision`, ses appels d'outils internes ne le sont pas.
- **Sentry.** Proposé, non retenu pour l'instant : `failure_log.py` couvre déjà
  les pannes de backend avec leur stratégie de récupération, et sur une
  application locale à un utilisateur une exception est visible immédiatement.
  Le seul vrai trou est le démon — que l'alerting ci-dessus couvre, sans service
  tiers.
- **Le juge hors ligne** (échantillon de traces noté par un modèle, en batch)
  n'est pas écrit. Il lira ce fichier quand il le sera. À ne pas confondre avec
  le nœud de réflexion que `CHANTIERS.md` écarte : celui-là bloquait le tour et
  ajoutait un appel de modèle dans le chemin critique.
- **Le corpus held-out en CI** reste à faire (`CHANTIERS.md` §6). `--route` lui
  donne maintenant de quoi comparer deux arbres : `axon_sha` est sur chaque
  ligne.
