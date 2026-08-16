# Variantes de prompt à comparer

Tout fichier `*.md` déposé ici devient un **bras** du banc, nommé d'après le
fichier. Son contenu est envoyé tel quel comme prompt système.

```bash
cp ../../src/agents/coding/prompts/base.py /tmp/       # point de départ
$EDITOR benchmarks/variantes/sans-echelle.md            # la variante à tester
python benchmarks/prompt_bench.py --repeat 5
```

Le bras `actuel` lit toujours `src/agents/coding/prompts/base.py` : une variante
se compare donc au prompt réellement en production, jamais à une copie figée.
