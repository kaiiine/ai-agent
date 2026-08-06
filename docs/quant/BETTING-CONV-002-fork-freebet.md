# BETTING-CONV-002 — STOP money : contrat freebet

**Statut : BLOQUÉ, en attente d'arbitrage.** Aucune formule de valorisation ni de
dimensionnement promotionnel n'a été écrite.

---

## 1. Constat

Aucun contrat promotionnel n'existe dans le code. Recherche sur tout `src/` :

```
freebet | free_bet | promotional | promo   →  0 occurrence de domaine
```

Les seules correspondances sont le mot « promotion » au sens de *promotion de
maturité de modèle* (`EXPERIMENTAL → SUPPORTED`), sans aucun rapport.

L'Advisor ne connaît qu'une `bankroll: Decimal`. Toute la chaîne de sizing —
Kelly, caps d'exposition, bankroll non allouée — raisonne sur du cash dont la
mise est **rendue** en cas de gain.

## 2. Ce qui a été fait sans arbitrage

Le strict minimum non-décisionnel, parce que ne rien faire aurait été pire :
l'utilisateur déclare 20 € de freebets, et le système les traitait comme 20 € de
bankroll.

- `PromotionalBalance{amount, currency, terms}` — un **enregistrement**, pas une
  valorisation. `terms` vaut `PROMOTION_TERMS_UNKNOWN`.
- Les soldes promotionnels sont **exclus** de la `bankroll` transmise à l'Advisor.
- Ils sont **restitués** dans le rendu, avec la mention explicite qu'ils ne sont
  pas optimisés et qu'un freebet n'est jamais « sans risque ».

C'est un refus documenté, pas une règle d'argent.

## 3. Pourquoi ça ne peut pas aller plus loin sans décision

Un freebet change **trois** choses à la fois, et chacune modifie le sizing :

### 3.1 La valeur du gain

| Type | Retour net si gain | Perte si échec |
|---|---|---|
| `CASH` | `mise × (cote − 1)` | `mise` |
| `FREEBET_STAKE_NOT_RETURNED` | `mise × (cote − 1)` | **0 € de cash**, mais tout le freebet |
| `FREEBET_STAKE_RETURNED` | `mise × cote` | idem |

Le piège n'est pas la formule, c'est la conclusion qu'on en tire : comme la
perte ne coûte aucun **cash**, il est tentant de conclure « donc sans risque ».
C'est faux — perdre le freebet en détruit toute la valeur économique. Aucun
rendu ne doit jamais employer ce mot.

### 3.2 La cote optimale

Sur du cash, Kelly arbitre entre espérance et variance à partir de la
probabilité du modèle. Sur un freebet stake-not-returned, la mise n'étant pas à
risque, la **cote optimale monte mécaniquement** : la stratégie qui maximise
l'espérance n'est plus celle du cash. Transposer Kelly tel quel produirait un
dimensionnement faux dans une direction systématique.

### 3.3 Les contraintes du bonus

Cote minimale, date d'expiration, marchés éligibles, combinabilité. Aucune n'est
connue du système, et chacune peut rendre une recommandation **inapplicable** —
recommander un freebet à 1,40 quand la cote minimale est 1,50 produit une
instruction que le bookmaker refusera.

## 4. Options

### Option A — statu quo explicite (implémenté)

`PROMOTION_TERMS_UNKNOWN` : enregistré, restitué, jamais optimisé, exclu de la
bankroll.

**Pour** : zéro règle d'argent inventée ; l'utilisateur voit son solde et sait
pourquoi il n'est pas utilisé.
**Contre** : les 20 € de freebet ne servent à rien.

### Option B — contrat déclaré par l'utilisateur, sizing séparé

`PromotionalBalance` gagne `promotion_type`, `stake_returned`, `minimum_odds`,
`expiry`, `eligible_markets`, `combinability_rules` — **renseignés par
l'utilisateur**, jamais devinés. Une seconde passe de sélection, disjointe du
portefeuille cash, choisit une sélection éligible.

**Pour** : le freebet devient utilisable sans polluer le sizing cash.
**Contre** : introduit une **nouvelle règle de décision d'argent** (quelle cote
viser sur un stake-not-returned), qui doit être spécifiée puis testée.
**Prérequis** : les conditions réelles Winamax, fournies ou vérifiées.

### Option C — Advisor unifié, bankroll multi-devises

`bankroll` devient un panier `{CASH, FREEBET_*}` et l'optimiseur alloue sur les
deux.

**Pour** : un seul chemin d'allocation.
**Contre** : le plus invasif — touche Kelly, les caps, l'exposition et l'audit,
c'est-à-dire tout ce qui décide de l'argent. À ne pas faire tant que les modèles
sont EXPERIMENTAL et ne produisent aucune mise réelle.

## 5. Recommandation

**Rester en A tant qu'aucun modèle n'est SUPPORTED.**

Aucun modèle ne produit aujourd'hui de mise réelle : le portefeuille cash est
vide, donc le portefeuille freebet le serait aussi. Construire B ou C maintenant
reviendrait à spécifier une règle d'argent qu'aucun test de bout en bout ne
pourrait exercer sur une vraie recommandation — et donc à ne pas savoir si elle
est juste.

**Ce qu'il faut pour lever le STOP** : les conditions Winamax réelles (mise
rendue ou non, cote minimale, expiration, marchés éligibles, combinabilité) et le
choix explicite entre B et C.
