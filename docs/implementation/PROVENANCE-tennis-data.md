# Provenance — dataset tennis (tennis-data.co.uk)

Récupéré **automatiquement** (aucune fourniture manuelle) le 2026-08-02.

## Pourquoi cette source
Reconnaissance réseau réelle, avec preuves :

| Source | Méthode | Résultat | Verdict |
|---|---|---|---|
| `raw.githubusercontent.com/torvalds/linux/…` | HTTP GET | 200 | hôte raw NON filtré (témoin) |
| `github.com/JeffSackmann/tennis_atp` | HTTP GET | 404 | dépôt absent |
| `api.github.com/repos/JeffSackmann/tennis_atp` | API | 404 Not Found | dépôt supprimé/renommé |
| `cdn.jsdelivr.net/gh/JeffSackmann/tennis_atp@master/…` | CDN indépendant | 404 | confirme : pas un filtrage local |
| `api.github.com/users/JeffSackmann/repos` | API | 200 | ne liste plus `tennis_atp`/`tennis_wta` |
| forks (`serve-and-volley`, `Tennismylife`, …) | raw | 404 | forks sans les CSV |
| `git clone …/tennis_atp` | git | échec auth | inaccessible |
| `v1.tennis.api-sports.io` | HTTPS | DNS/URLError | api-sports n'a AUCUN produit tennis |
| `tennisabstract.com/reports/*_elo_ratings.html` | HTTP GET | 200 | joignable, mais Elo DÉRIVÉ (pas de résultats bruts point-in-time) |
| **`tennis-data.co.uk`** | HTTP GET | **200** | **RETENUE** : le plus d'historique + cotes bookmaker |

Jeff Sackmann (`tennis_atp`/`tennis_wta`) est **introuvable** — confirmé par trois
sources indépendantes (github.com, api.github.com, jsDelivr). tennis-data.co.uk offre
l'historique le plus profond ET les cotes de clôture, décisives pour un modèle de paris.

## Contenu récupéré
- **49 fichiers annuels** (ATP `<year>/<year>.xls[x]`, WTA `<year>w/<year>.xls[x]`).
- Formats mixtes : `.xls` (OLE2/BIFF, années anciennes) et `.xlsx` (ZIP/XML).

### Gardes d'intégrité appliquées à l'ingestion
1. **Détection de format par MAGIC BYTES** (`PK` vs `D0CF11E0`) : le serveur fait de la
   négociation de contenu et sert le `.xls` sous une URL `.xlsx`.
2. **Intégrité de circuit** : le fichier masculin porte une colonne `ATP`, le féminin une
   colonne `WTA`. Toute année WTA inexistante (avant 2007) renvoie le fichier ATP — ces
   fichiers sont **REJETÉS**, sinon des matchs masculins entreraient dans le dataset WTA.
3. **Dates aberrantes** : une ligne dont la date est dans le FUTUR ou s'écarte de plus
   d'un an de l'année du fichier est **rejetée** (coquilles réelles de la source).
   Aucune donnée n'est « corrigée » : elle est écartée.

## Point-in-time (Notes.txt, vérifié)
- `WRank`/`LRank`/`WPts`/`LPts` = classement/points **au DÉBUT du tournoi** → PRÉ-MATCH ;
- cotes (`B365`/`PS`/`Avg` W/L) = « most recent before play starts » → PRÉ-MATCH ;
- `Winner`/`Loser`, sets, `Comment` = ISSUE → **POST-MATCH**, jamais des features.
- `Walkover` exclus (non-matchs) ; `Retired` conservés (résultat de pari réel).

## Licence / attribution
Données **factuelles** (résultats, classements, cotes), diffusées gratuitement.
`Notes.txt` demande l'attribution des sources : Xscores, ATP, stevegtennis.com,
Livescore (résultats) ; ATP/WTA (classements) ; **oddsportal** (cotes).
**Aucune licence open-source explicite** n'est déclarée par le site : usage
recherche/analyse avec attribution ; les conditions de REDISTRIBUTION ne sont pas
explicitées → décision du propriétaire du dépôt.

## Fixtures embarquées
- `tests/fixtures/tennis/tennis_data_atp_2000_2026.csv.gz` — **71074 matchs** — 2000-01-03 → 2026-07-26 — 1650 KB — `sha256:9fa413c2c985f0576803579236374ab9511984506966f2acd880a4df0273cbc2`
- `tests/fixtures/tennis/tennis_data_wta_2000_2026.csv.gz` — **47080 matchs** — 2006-12-31 → 2026-07-26 — 1229 KB — `sha256:a5926061a8de78b43d7765bbb8d9d4ceed705c5ec62d03efa5f3c0add0174e09`

Colonnes : Date, Level, Court, Surface, Round, BestOf, Winner, Loser, WRank, LRank,
WPts, LPts, Comment, B365W/L, PSW/L, AvgW/L, Wsets, Lsets, Tournament.

## Checksums des fichiers SOURCES
| tour | année | octets | lignes | sha256 |
|---|---|---|---|---|
| atp | 2000 | 811520 | 2963 | `sha256:03db38ea13c83795b24eac6c068432ca86d735ac816ef42928d89216d28415f8` |
| atp | 2001 | 1176064 | 2963 | `sha256:a3161067b946881e1a2b067ec5a78f078155b8177e17ae307084e7e3facca2fc` |
| wta | 2001 | 988160 | 0 | `sha256:9eb750c4e8d17ea0255a9b9144f8e77460bd0926fdae992f5f47a650d8259039` |
| atp | 2002 | 1288704 | 2854 | `sha256:60bed111e535655bbba9a6634777ef5c8984a83d61f4116fda77e7fea7b68798` |
| wta | 2002 | 168741 | 0 | `sha256:f7dd7c632d8fc3a02c259983ab2dfd83a2e4516a3011d9b70caef6cd49c3eae1` |
| atp | 2003 | 1597952 | 2861 | `sha256:d570759da44f474a9091c1143c6a077d4975ee5abae534ca63a583df7b3de382` |
| atp | 2004 | 1110016 | 2877 | `sha256:134f007467923e36eec83cef311dce89a711c46f7f2e70d4ad5c4c1bbd3292ca` |
| atp | 2005 | 1136128 | 2909 | `sha256:8c7d3aff7c00ccceef571d2ee4236636621da4d11def5aa9c707620e6c309908` |
| atp | 2006 | 1146880 | 2909 | `sha256:4317bc976cb17d0346a36ad5c09024b7957c28155ed5a59bd38e2df7226aa492` |
| atp | 2007 | 1107968 | 2806 | `sha256:77e2b8504a6f0376a76a1a1e55e55ec53b008e400beebba8fdc2e655eaff8449` |
| wta | 2007 | 970752 | 2491 | `sha256:276b61366afe8016eb5b5822e0f83efe33b8449743ffc07781f0be48e2b8aa1a` |
| atp | 2008 | 1092608 | 2707 | `sha256:d374f8563fd417a1e3b57eeb6cc4f83042cd62bb63323a528ae5a3483fc0113c` |
| wta | 2008 | 952832 | 2404 | `sha256:eb745d440250d321f02353c135b91bc1fcb39d2c30757d116f60fd0f6a8902d9` |
| atp | 2009 | 1078272 | 2731 | `sha256:94028838328000f8c0b9c4ff2e8821a18e7a5d3653e7b5d0d870c81222bdc06d` |
| wta | 2009 | 947712 | 2433 | `sha256:20c2b846a5d20f4c297d5ea058503b12c8f8bfd9994ec298bdb64615e0f3234f` |
| atp | 2010 | 1099264 | 2679 | `sha256:c90c5bfe3b801a351240110212c48dc71c46a2a83bb64f07fd9e1372730ce638` |
| wta | 2010 | 988160 | 2447 | `sha256:9eb750c4e8d17ea0255a9b9144f8e77460bd0926fdae992f5f47a650d8259039` |
| atp | 2011 | 1093632 | 2675 | `sha256:56d5a35f05f1c74afe576bfb2f34710971d92229e56bf91e44164c36bbc16ef1` |
| wta | 2011 | 996352 | 2468 | `sha256:bfa3c9803c8e2b4bc512f9d1a3938d0aed4a3079e0acc404f7f737359a4190f8` |
| atp | 2012 | 1065984 | 2607 | `sha256:c54d1b4d816479d0b4ecb37468dbf710140053a76b0494237c42773092687234` |
| wta | 2012 | 969216 | 2406 | `sha256:204e823154e57723ea8b7c00dd837e6eb319485373d59f82e41439abf8f87111` |
| atp | 2013 | 504086 | 2631 | `sha256:95b8af095a5ae0d64be2cbc838684a094ac542f5cb151da545ebf166ed21a80c` |
| wta | 2013 | 515133 | 2442 | `sha256:94b8c1033b45ebe01b25e6faf2f86a052c4c991ae1950d7100e1bb29d97ab492` |
| atp | 2014 | 573801 | 2600 | `sha256:ebc5749b3b537cc6dafde5d416a330752dc64a1b2f3f4f9698699763a3ce7d9f` |
| wta | 2014 | 540026 | 2476 | `sha256:0e1ae9ad8d781825ca79df0be18ebf861383b9f2b3630e4bcc0166a8adc9f047` |
| atp | 2015 | 526784 | 2630 | `sha256:74d1ffa15ad8b13aea0ffd6eba17fa5dc05b2b57263515d20e7ee39be0354485` |
| wta | 2015 | 496722 | 2521 | `sha256:f2625eb24820743514a635f2daf57945d40d0108c5aafd244345df8368197648` |
| atp | 2016 | 546990 | 2626 | `sha256:e55547add1d8c8cad17d1eb7be5a24de7757f33dd90fe4f91ca7d4ee8a3e4b08` |
| wta | 2016 | 496904 | 2522 | `sha256:810ec9c7fe558614331cac2d9b328545ea6d3c0c840863ad5653efa0bbd9a40a` |
| atp | 2017 | 526053 | 2633 | `sha256:d8d2e2af5bda1f7891de39b18739ba229719e00672c22d2892b3e347dc6e1537` |
| wta | 2017 | 463132 | 2500 | `sha256:5476fa98ea38a885a5f7141e6aa6c4979dfb2d7f93715f7d13b46a17c1f140e0` |
| atp | 2018 | 474033 | 2637 | `sha256:3e52c70872c87736110bfe22f682bd224bb5883bf5367a7f8997aab991c7162a` |
| wta | 2018 | 488666 | 2469 | `sha256:e96cc8317a634f0238c51f375896bfc47f53de96554adb0291003cc9b26c7278` |
| atp | 2019 | 411531 | 2610 | `sha256:a267a7a779406ccd89762b98cbe4bb6370839a658f2a95ac098310ea3394e827` |
| wta | 2019 | 383919 | 2472 | `sha256:3302aa2b04e4873cd1079ef470d8b63778b35b9b821d2ca52621b933f88a567d` |
| atp | 2020 | 206869 | 1267 | `sha256:310467bb81360e1981e9f3775946c63a5dc707a1d941e5ad4d9713da97daa752` |
| wta | 2020 | 168741 | 1055 | `sha256:f7dd7c632d8fc3a02c259983ab2dfd83a2e4516a3011d9b70caef6cd49c3eae1` |
| atp | 2021 | 395807 | 2489 | `sha256:dcbd273a4fa101f4783384dbfe3410bfc7ee7bed0aed4ab9a09afbffb294c4ca` |
| wta | 2021 | 382230 | 2447 | `sha256:a364ca800b49b6ffc770b6766b8b15cec50ecfa9baf850c7973076dc936b1cc3` |
| atp | 2022 | 417917 | 2632 | `sha256:9feaa1567783cb063e23b6f2d653d4c97210a48b001373eb367eb2d8b6a60a86` |
| wta | 2022 | 370069 | 2369 | `sha256:d173f08e2607e2a3259448261f50cbe5bed6f298dd204427ea07b7795b4cc155` |
| atp | 2023 | 447088 | 2703 | `sha256:5789a33720cbd5da9c7909713cfca131927eedaf305ab2b111ec6f8dda842b29` |
| wta | 2023 | 407251 | 2491 | `sha256:ea4c4556c841ad696cd417885015fe0c63b7a2414c94d856f9515a238f2fef2a` |
| atp | 2024 | 445729 | 2703 | `sha256:d92a4d4167cfece60b624e81ba8d6724d90a4704637341bb0bc87539a36c746a` |
| wta | 2024 | 406783 | 2490 | `sha256:0ce3a4e87c269253dd61e1ab4a3bbeb2d9acdd512f316189e5ad872c86c67b53` |
| atp | 2025 | 426707 | 2644 | `sha256:941aaa1abc49131f51e1f7f6eee93dac829dd72578ca10b341dfc4c9d41ba013` |
| wta | 2025 | 399398 | 2505 | `sha256:aac890b7465d0c74812578b2a962b4e5cb4c76455dccb6cece2efa5067448c13` |
| atp | 2026 | 277950 | 1728 | `sha256:49853f6389dbc98a0ea72b58d04f20bd6bcbceae2238bf5e0345b90ebada9782` |
| wta | 2026 | 264884 | 1672 | `sha256:f6f913da3dabbb54add6e9edd167a1d33d669c9ede9741e63e9069f18b3977ba` |
