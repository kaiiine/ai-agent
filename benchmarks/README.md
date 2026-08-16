# Banc de mesure des prompts

Chaque correctif apporté à `BASE_PROMPT` a longtemps été validé par un test
unitaire ou à l'œil. Aucun ne répondait à la seule question qui compte :
**est-ce que l'agent produit un meilleur résultat ?** Sans instrument, une
modification de prompt est une opinion.

```bash
python benchmarks/prompt_bench.py --repeat 5
python benchmarks/prompt_bench.py --backend gemini --repeat 5
python benchmarks/prompt_bench.py --montrer date-picker actuel   # lire le code produit
```

## Les bras

| bras | ce que c'est |
|---|---|
| `aucun` | aucun prompt système — le plancher |
| `actuel` | `src/agents/coding/prompts/base.py` tel qu'il est aujourd'hui |
| `<nom>` | tout fichier déposé dans `benchmarks/variantes/<nom>.md` |

Pour comparer une réécriture : dépose-la en `variantes/`, relance, lis l'écart.

## Les tâches

Six tâches à piège : chacune a une réponse native ou standard qu'un modèle non
contraint remplace par du sur-mesure (`<input type="date">` contre un composant
de 400 lignes, `@lru_cache` contre une classe de cache maison). C'est là que
l'écart entre deux prompts est visible ; sur du code déjà minimal, il n'y a rien
à gagner et le banc le montrera.

## Ce que ce banc ne montre pas

- **Ce n'est pas une session agentique.** Un prompt, une complétion. Le
  specialist, lui, planifie, appelle des outils et itère. Un prompt qui gagne
  ici peut perdre en session, où il est réinjecté à chaque tour.
- **Moins de lignes n'est pas mieux en soi.** Un bras qui livre un bout de code
  inutilisable gagnerait la colonne. `--montrer` sert à aller lire avant de
  conclure.
- **La dispersion est rapportée.** Si elle dépasse l'écart mesuré, le banc le
  dit : il n'y a alors rien à conclure, quel que soit le pourcentage affiché.

ponytail a mesuré que son échelle ne transfère **pas** à un petit modèle local
(llama3.2 3.2B : le signal disparaît dans la variance, et le temps augmente).
Les backends d'AXON sont plus gros ; la question reste ouverte, et c'est
précisément ce que ce banc permet de trancher au lieu d'en débattre.

## Origine

Inspiré de `benchmarks/benchmark-local.py` de
[ponytail](https://github.com/DietrichGebert/ponytail) (MIT), adapté aux
backends d'AXON, à sa rotation de clés, et à son propre prompt comme sujet.
