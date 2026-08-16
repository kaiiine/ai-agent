"""Le moteur de spécification — méthode séparée de l'interface.

`src/ui/spec.py` mène la conversation ; ce paquet décide QUOI demander, dans quel
ordre, sous quelle forme écrire le résultat, et ce qui manque encore. La
séparation n'est pas cosmétique : la méthode est testable sans terminal, et le
wizard peut changer d'habillage sans toucher à ce qui fait la qualité d'une spec.

    taxonomy   les zones d'ambiguïté, socle commun + profils par nature de projet
    coverage   ce que le descriptif dit déjà, et l'ordre des questions restantes
    template   la forme de la spec — tranches priorisées, critères vérifiables
    analyze    ce qui manque encore, vérifié sans appel de modèle

La taxonomie d'ambiguïté et le découpage en tranches indépendantes viennent de
spec-kit (github/spec-kit, MIT), réimplémentés plutôt qu'importés : le dépôt
apporte ~2 400 lignes de méthode utile dans 53 000 lignes d'installeur destiné à
vingt autres agents, et suppose une branche git par fonctionnalité que la
convention d'AXON — un projet, un dossier, une `spec.md` — ne suit pas.
"""

from .analyze import Constat, analyser, bloquant
from .coverage import Lecture, a_demander, scanner
from .taxonomy import LIBELLES_PROFIL, Categorie, categories_du_profil
from .template import journal_des_clarifications, systeme_de_generation

__all__ = [
    "Categorie", "Constat", "Lecture", "LIBELLES_PROFIL",
    "a_demander", "analyser", "bloquant", "categories_du_profil",
    "journal_des_clarifications", "scanner", "systeme_de_generation",
]
