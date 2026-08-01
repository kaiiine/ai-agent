# Opérations — collecte CLV planifiée (odds_history)

But : accumuler l'`odds_history` réel dont la maturité CLV a besoin (§16). C'est la
SEULE chose qui bloque encore la promotion de hockey vers `SUPPORTED` (son unique
blocker restant est `positive_clv`), et un prérequis de tout premier `SUPPORTED`.

Aucune donnée n'est fabriquée : la collecte n'écrit que des cotes réellement observées
(capture LIVE réseau) ; un échec réseau LÈVE, il ne se replie jamais sur du synthétique.

## Commande

```
axon record-odds --live <SPORT> --phase <decision|closing> [--store <path>] [--now <iso>]
```

- `<SPORT>` ∈ {football, basketball, hockey, baseball, american_football, volleyball}
  (les 6 sports live-câblés ; `SPORT_IDS` porte le sportId Winamax).
- `--phase decision` : capture aux fenêtres de DÉCISION (plusieurs par événement).
- `--phase closing` : UNE capture au plus près du coup d'envoi (référence CLV).
- Le schéma de marché vient du registre de modèles (`VALIDATED_MODELS`) : 3-way pour
  football/hockey, 2-way sinon — aucune hypothèse 1X2 résiduelle.

Une paire CLV naît quand un même marché a une observation `DECISION` PUIS une
`CLOSING` strictement postérieure (cf. `clv.clv_readiness`). L'ÉCHANTILLON effectif
compté par la maturité est le nombre d'ÉVÉNEMENTS indépendants (`n_events`), jamais le
nombre brut de lignes (home/away, snapshots répétés d'un même match ne comptent qu'une
fois — anti-pseudo-réplication, cf. `maturity.py` + policy `min_clv_events`).

## Fenêtres (CONFIGURABLES — aucun horaire codé en dur)

Le timing est une décision d'exploitation, pas une constante du code. Cadence
CONSERVATRICE suggérée (à ajuster par sport/ligue selon la vitesse de mouvement des
lignes) :

| Phase     | Fenêtre suggérée                        | Fréquence          |
|-----------|-----------------------------------------|--------------------|
| DECISION  | de T-24 h à T-1 h avant le coup d'envoi | toutes les 1–3 h   |
| CLOSING   | T-15 min à T-2 min avant le coup d'envoi| 1 capture          |

`T` = début du match. Ces bornes sont des paramètres de planification (cron), pas des
valeurs du domaine ; les affiner ne modifie aucun code.

## Planification (cron)

Un exemple conceptuel (à adapter à l'ordonnanceur réel de la machine) :

```cron
# DECISION — balayage horaire des 6 sports (fenêtre T-24h..T-1h gérée en amont)
0 * * * *  for s in football basketball hockey baseball american_football volleyball; do \
             axon record-odds --live $s --phase decision >> var/log/clv_decision.log 2>&1; done

# CLOSING — capture rapprochée toutes les 5 min (ne retient que les matchs proches du KO)
*/5 * * * * for s in football basketball hockey baseball american_football volleyball; do \
             axon record-odds --live $s --phase closing >> var/log/clv_closing.log 2>&1; done
```

## Stockage

- Store JSONL append-only : `var/betting_engine/odds_history.jsonl` (gitignoré,
  JAMAIS `~/.axon`). Une observation par ligne, cotes en `Decimal` (jamais float).
- Chemin surchargeable via `--store` (tests : tmp).

## Logs / erreurs / reprise

- Chaque exécution imprime : nb d'observations écrites, événements enregistrés/ignorés,
  `source` (LIVE vs synthétique) et phase. Rediriger vers `var/log/…`.
- Échec réseau → la commande LÈVE (code ≠ 0) ; jamais de repli synthétique déguisé.
  Le cron réessaiera à la fenêtre suivante — le store append-only rend la reprise sûre
  (aucune mutation, aucune paire perdue).
- Un événement non résolu (identité/compétition) est IGNORÉ et compté, jamais fabriqué.

## Suivre la progression vers SUPPORTED

```
axon readiness --competition <fl1|nba|mlb|nfl|volley|nhl|…>
```

Expose l'échantillon CLV effectif (`n_events`), la moyenne et la borne de confiance
inférieure, aux côtés des autres critères et des bloqueurs exacts. `positive_clv` ne
passe que lorsque `n_events ≥ min_clv_events` ET borne basse > 0 (policy v2) — jamais
sur une observation isolée.
```
