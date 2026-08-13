# ADR-BE-004 — Dette statistique : forme antérieure hors compétition

**Statut** : ACCEPTÉE comme DETTE. Aucune implémentation. `FUTURE_STATISTICAL_ADR`.
**Date** : 2026-08-13

## Contexte

`PointInTimeGateway.recent_form` refuse de servir un événement d'une autre
compétition que celle pour laquelle elle a été construite :

```
gateway point-in-time construite pour {league_id},
événement de {competition_id} — datasets non interchangeables
```

Ce refus est délibéré. Mélanger deux populations dans un backtest produit un
résultat qui a l'air normal : les métriques restent plausibles, et rien ne
signale que la forme d'un club a été estimée sur un championnat national pour
prédire une coupe d'Europe, où l'adversaire moyen n'a pas le même niveau.

## Ce que la mesure a établi

Le backfill historique a montré que **le signal intra-compétition suffit** là où
la profondeur existe :

| compétition | n_eval | coverage | Brier | baseline |
|---|--:|--:|--:|--:|
| Ligue des Champions | 2 050 | 0,9395 | 0,5859 | 0,6316 |
| Ligue Europa | 734 | 0,9017 | 0,6138 | 0,6383 |

Quinze saisons de Ligue des Champions donnent assez de forme antérieure pour que
`min_data_coverage` passe sans jamais sortir de la compétition. L'argument
« il faut du cross-competition pour couvrir les coupes » est donc **faux dans le
cas général** — c'était un manque de profondeur historique, pas un manque de
transfert entre compétitions.

## Les cas qui restent, et eux seuls

Le cross-competition ne devient nécessaire que lorsqu'aucune profondeur
historique intra-compétition n'est **possible**, pas seulement absente :

- **équipe promue** — un promu n'a, par construction, aucun historique dans sa
  nouvelle division ; mesuré sur la Bundesliga : Holstein Kiel, St. Pauli et
  Hamburger SV, 3 rencontres écartées sur 917 (couverture 0,9869) ;
- **Supercoupe** — une rencontre par an, donc jamais d'échantillon propre ;
- **primo-entrants européens** — un club qui découvre la coupe d'Europe ;
- **tours de qualification** — plateau disjoint du tableau final.

Ces cas partagent une propriété : la donnée manquante n'existe nulle part dans
la compétition, et existe ailleurs pour la même entité.

## Décision

**Ne rien implémenter maintenant.** Un modèle cross-competition demande sa propre
validation : il faudrait démontrer, hors échantillon, qu'une force estimée en
Bundesliga prédit mieux en Ligue des Champions que l'abstention actuelle. Ce
n'est pas un raccordement de données, c'est une hypothèse statistique — d'où le
classement en `FUTURE_STATISTICAL_ADR` plutôt qu'en tâche d'ingénierie.

Le pipeline `historical_discovery` sait déjà **acquérir** ces données : le
backfill d'un promu va jusqu'à `STAGED` (source openfootball `2-bundesliga.txt`,
CC0-1.0, identité ancrable). Il s'arrête au moment de les consommer, faute de
modèle habilité à le faire. La dette est donc côté statistique, et uniquement là.

## Conséquence assumée

Un promu, une Supercoupe ou un primo-entrant produit une **abstention** —
`INSUFFICIENT_DATA` — et non une probabilité estimée sur une population voisine.
C'est un coût de couverture accepté : mesuré à 3 rencontres sur 917 en
Bundesliga, il est très inférieur au risque d'un transfert non validé.

## Ce qu'il faudrait pour lever la dette

1. Un jeu d'évaluation dédié : uniquement des rencontres sans historique
   intra-compétition (promus, primo-entrants), avec leur issue réelle.
2. Une comparaison hors échantillon contre la baseline actuelle — qui est
   l'abstention, donc contre la fréquence a priori.
3. Un facteur de force par compétition, estimé point-in-time et non a posteriori.
4. Le passage des mêmes critères de maturité, sans aucun assouplissement.

Tant que (1) n'existe pas, (2) n'est pas mesurable, et le reste est spéculatif.
