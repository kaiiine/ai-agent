# Provenance — dataset tennis (tennis-data.co.uk)

Récupéré AUTOMATIQUEMENT le 2026-08-01 (aucune fourniture manuelle). Source retenue
après reconnaissance réseau réelle : Jeff Sackmann `tennis_atp`/`tennis_wta` est
INTROUVABLE (repo 404 sur github.com ET api.github.com ET jsDelivr — supprimé/renommé) ;
tennis-data.co.uk est accessible (HTTP 200) et offre le PLUS d'historique + les cotes
bookmaker de clôture, idéales pour un modèle de paris.

## Source
- Site : http://www.tennis-data.co.uk/ (ATP dès 2000, WTA dès 2007 ; odds oddsportal).
- Fichiers annuels XLSX : `http://www.tennis-data.co.uk/<year>/<year>.xlsx` (ATP),
  `http://www.tennis-data.co.uk/<year>w/<year>.xlsx` (WTA).
- Plage récupérée : **2015–2024** (10 saisons/tour).

## Point-in-time (Notes.txt, vérifié)
- `WRank/LRank/WPts/LPts` = classement/points **au DÉBUT du tournoi** → PRÉ-MATCH.
- Cotes (`B365/PS/Max/Avg` W/L) = « most recent before play starts » → PRÉ-MATCH.
- `Winner/Loser`, scores de sets, `Comment` = ISSUE → POST-MATCH (jamais des features).

## Licence / acknowledgement
- Données FACTUELLES (résultats/classements/cotes). tennis-data.co.uk les fournit
  gratuitement ; Notes.txt demande l'acknowledgement des sources : Xscores, ATP,
  stevegtennis.com, Livescore (résultats) ; ATP/WTA (classements) ; oddsportal (cotes).
- **Aucune licence open-source explicite** n'est déclarée par le site (pas de MIT/CC).
  Usage : recherche/analyse personnelle avec attribution. Les conditions de
  redistribution ne sont pas explicitées → décision du propriétaire du repo.

## Fixtures embarquées (compactées, colonnes essentielles + cotes de clôture)
- `tests/fixtures/tennis/tennis_data_atp_2015_2024.csv.gz` — 24930 matchs — sha256:737d0ab4f5f88ca1eb5b40a20df1b582cf6a75346375fe78e52fa0fb480536c6
- `tests/fixtures/tennis/tennis_data_wta_2015_2024.csv.gz` — 23336 matchs — sha256:087c5aab47287244803ce074dfb3a8724d37d1bb875f24ffd75c57ef5eea852e
- Colonnes : Date, Level(Series/Tier), Court, Surface, Round, BestOf, Winner, Loser,
  WRank, LRank, WPts, LPts, Comment, B365W/L, PSW/L, AvgW/L.

## Checksums des fichiers SOURCES originaux (XLSX)
| tour | année | octets | sha256 |
|---|---|---|---|
| atp | 2015 | 526784 | `sha256:74d1ffa15ad8b13aea0ffd6eba17fa5dc05b2b57263515d20e7ee39be0354485` |
| wta | 2015 | 496722 | `sha256:f2625eb24820743514a635f2daf57945d40d0108c5aafd244345df8368197648` |
| atp | 2016 | 546990 | `sha256:e55547add1d8c8cad17d1eb7be5a24de7757f33dd90fe4f91ca7d4ee8a3e4b08` |
| wta | 2016 | 496904 | `sha256:810ec9c7fe558614331cac2d9b328545ea6d3c0c840863ad5653efa0bbd9a40a` |
| atp | 2017 | 526053 | `sha256:d8d2e2af5bda1f7891de39b18739ba229719e00672c22d2892b3e347dc6e1537` |
| wta | 2017 | 463132 | `sha256:5476fa98ea38a885a5f7141e6aa6c4979dfb2d7f93715f7d13b46a17c1f140e0` |
| atp | 2018 | 474033 | `sha256:3e52c70872c87736110bfe22f682bd224bb5883bf5367a7f8997aab991c7162a` |
| wta | 2018 | 488666 | `sha256:e96cc8317a634f0238c51f375896bfc47f53de96554adb0291003cc9b26c7278` |
| atp | 2019 | 411531 | `sha256:a267a7a779406ccd89762b98cbe4bb6370839a658f2a95ac098310ea3394e827` |
| wta | 2019 | 383919 | `sha256:3302aa2b04e4873cd1079ef470d8b63778b35b9b821d2ca52621b933f88a567d` |
| atp | 2020 | 206869 | `sha256:310467bb81360e1981e9f3775946c63a5dc707a1d941e5ad4d9713da97daa752` |
| wta | 2020 | 168741 | `sha256:f7dd7c632d8fc3a02c259983ab2dfd83a2e4516a3011d9b70caef6cd49c3eae1` |
| atp | 2021 | 395807 | `sha256:dcbd273a4fa101f4783384dbfe3410bfc7ee7bed0aed4ab9a09afbffb294c4ca` |
| wta | 2021 | 382230 | `sha256:a364ca800b49b6ffc770b6766b8b15cec50ecfa9baf850c7973076dc936b1cc3` |
| atp | 2022 | 417917 | `sha256:9feaa1567783cb063e23b6f2d653d4c97210a48b001373eb367eb2d8b6a60a86` |
| wta | 2022 | 370069 | `sha256:d173f08e2607e2a3259448261f50cbe5bed6f298dd204427ea07b7795b4cc155` |
| atp | 2023 | 447088 | `sha256:5789a33720cbd5da9c7909713cfca131927eedaf305ab2b111ec6f8dda842b29` |
| wta | 2023 | 407251 | `sha256:ea4c4556c841ad696cd417885015fe0c63b7a2414c94d856f9515a238f2fef2a` |
| atp | 2024 | 445729 | `sha256:d92a4d4167cfece60b624e81ba8d6724d90a4704637341bb0bc87539a36c746a` |
| wta | 2024 | 406783 | `sha256:0ce3a4e87c269253dd61e1ab4a3bbeb2d9acdd512f316189e5ad872c86c67b53` |
