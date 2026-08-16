# Provenance — jeu de données tennis

`tennis_data_loader.py` renvoyait vers ce document, qui n'existait pas : la
provenance était annoncée comme documentée alors qu'elle ne l'était nulle part.
Ce fichier ne contient que du **vérifiable sur les fixtures présentes**.

## Fichiers

| Fixture | Taille (gz) | Lignes | sha256 |
|---|--:|--:|---|
| `tests/fixtures/tennis/tennis_data_atp_2000_2026.csv.gz` | 1 651 Ko | 71 074 | `9fa413c2c985f057…` |
| `tests/fixtures/tennis/tennis_data_wta_2000_2026.csv.gz` | 1 230 Ko | 47 080 | `a5926061a8de78b4…` |

Le checksum complet est recalculé à chaque chargement et exposé par
`TennisDataset.files[].checksum` — `axon tennis-inventory` l'affiche.

Périodes réellement couvertes (mesurées, pas déduites du nom de fichier) :
ATP `2000-01-03 → 2026-07-26`, WTA `2006-12-31 → 2026-07-26`.

> ⚠ Le nom dit « 2026 », la couverture WTA commence en **2006** malgré le `2000`
> du nom de fichier. Se fier au nom donnerait six ans d'historique imaginaire.

## Source

[tennis-data.co.uk](http://www.tennis-data.co.uk/) — un classeur par saison et par
circuit. Les colonnes de la fixture sont celles de cette source, sans renommage :

```
Date, Level, Court, Surface, Round, BestOf, Winner, Loser, WRank, LRank,
WPts, LPts, Comment, B365W, B365L, PSW, PSL, AvgW, AvgL, Wsets, Lsets, Tournament
```

## Point-in-time — ce qui est PRÉ-match et ce qui ne l'est pas

C'est la distinction qui empêche la fuite. Elle est vérifiée dans le `Notes.txt`
de la source et appliquée par `_row_to_match` :

| Pré-match (utilisable en feature) | Post-match (issue — jamais en feature) |
|---|---|
| `WRank`/`LRank`, `WPts`/`LPts` — classement au **début du tournoi** | `Winner`/`Loser` |
| `B365W/L`, `PSW/L`, `AvgW/L` — cote « most recent before play starts » | `Comment`, `Wsets`/`Lsets` |
| `Surface`, `Court`, `Level`, `Round`, `BestOf` | |

Les colonnes de cotes portent déjà le vainqueur dans leur **nom** (`AvgW` = cote
du gagnant). Le modèle ne les lit jamais pour prédire : elles ne servent qu'au
report du marché comme contexte, et à la CLV.

## Traitement à l'ingestion

- `Walkover` **exclu** — un forfait avant match n'est pas un résultat de jeu
  (386 lignes ATP).
- `Retired` **conservé** — l'abandon en cours de match est un vrai résultat de
  pari « vainqueur » (2 182 lignes ATP).
- Répartition observée de `Comment` (ATP) : `Completed` 68 497 · `Retired` 2 182 ·
  `Walkover` 386 · `Awarded` 5 · `Disqualified` 2.
- Tri chronologique à la lecture — le walk-forward en dépend.

## Rafraîchir

**Non automatisé, et c'est aujourd'hui le plus gros écart d'exactitude du modèle**
(voir `axon tennis-inventory --tour atp`, ligne `fraîcheur`). Les notes Elo ne
bougent que quand cette fixture bouge.

1. Récupérer les classeurs de la saison courante depuis tennis-data.co.uk
   (un fichier par circuit et par année).
2. Les concaténer aux années déjà présentes, en gardant l'en-tête ci-dessus et
   l'ordre des colonnes.
3. Réécrire `tennis_data_{tour}_2000_2026.csv.gz` (gzip).
4. Contrôler : `axon tennis-inventory --dir tests/fixtures/tennis --tour atp`
   — vérifier le nombre de lignes, la nouvelle période, et que la ligne
   `fraîcheur` repasse sous le seuil.
5. Régler les prédictions devenues jugeables : `axon outcomes settle`.

L'étape 5 n'est pas optionnelle : c'est elle qui transforme un rafraîchissement
de données en mesure de justesse.

## Ce que ce document ne prétend pas

La date exacte de récupération des fixtures actuelles n'est pas connue — elle
n'avait été consignée nulle part. Seule la **couverture** est mesurable, et c'est
elle qui fait foi.
