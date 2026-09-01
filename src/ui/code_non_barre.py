"""Reposer les barrières que le modèle a oubliées.

`rich.Markdown` traite un bloc de lignes non barré comme un PARAGRAPHE : il en
recolle les lignes et interprète les marques en ligne. Un extrait de code y
survit mal. Vécu, sur une réponse finale de l'agent :

    def parse_numbers(tokens): numbers = [] for token in tokens: try: …
    if name == "main": main()

Tout le corps sur une ligne, et `__name__` avalé par le gras de `__…__`.

On ne devine pas : un paragraphe n'est du code que s'il en porte une marque sans
équivoque — `def`, `import`, un `#!`, un nom entouré de doubles soulignés. Ce qui
n'est pas reconnu reste de la prose, toujours : une fausse barrière abîmerait un
paragraphe, ce qu'on cherche justement à éviter.

Les paragraphes de code qui se suivent sont barrés ENSEMBLE. Une source aérée de
lignes vides — l'usage — se découperait sinon en fragments, et les morceaux sans
marque propre (`if __name__ == "__main__":` seul) retomberaient en prose.
"""
from __future__ import annotations

import re

#: Ouvre sans ambiguïté du code : aucune prose ne commence ainsi.
_STRUCTURE = re.compile(
    r"^\s*(?:def |class |import |from \s*\S+\s+import |@\w|#!|"
    r"(?:async\s+)?function |const |let |var |public |private )")

#: Un nom entouré de doubles soulignés. La prose n'en écrit pas — et c'est
#: précisément ce que le gras markdown dévore.
_DUNDER = re.compile(r"__\w+__")

#: Les barrières déjà posées, qu'on ne touche pas.
_BARRIERE = re.compile(r"^\s*(?:```|~~~)")


def _est_du_code(lignes: list[str]) -> bool:
    if any(_STRUCTURE.match(l) or _DUNDER.search(l) for l in lignes):
        return True
    # Sinon il faut la charpente : une ligne qui ouvre un bloc, et l'indentation
    # qui la suit. Une phrase finissant par « : » n'a pas de suite indentée.
    return (len(lignes) >= 2
            and any(l.rstrip().endswith(":") for l in lignes)
            and any(l[:1] in (" ", "\t") for l in lignes))


def _paragraphes(lignes: list[str]) -> list[tuple[bool, list[str]]]:
    """Découpe en (est_vide, lignes), les lignes vides formant leurs propres blocs."""
    blocs: list[tuple[bool, list[str]]] = []
    courant: list[str] = []
    vide = False
    for ligne in lignes:
        if bool(ligne.strip()) == (not vide):
            courant.append(ligne)
            continue
        if courant:
            blocs.append((vide, courant))
        vide = not vide
        courant = [ligne]
    if courant:
        blocs.append((vide, courant))
    return blocs


def _barrer_hors_barriere(lignes: list[str]) -> list[str]:
    blocs = _paragraphes(lignes)
    code = [not vide and _est_du_code(contenu) for vide, contenu in blocs]

    # Une région de code absorbe les lignes vides qu'elle enjambe.
    for i, (vide, _) in enumerate(blocs):
        if vide and 0 < i < len(blocs) - 1 and code[i - 1] and code[i + 1]:
            code[i] = True

    sortie: list[str] = []
    dedans = False
    for est_code, (_, contenu) in zip(code, blocs):
        if est_code and not dedans:
            sortie.append("```")
        elif dedans and not est_code:
            sortie.append("```")
        dedans = est_code
        sortie.extend(contenu)
    if dedans:
        sortie.append("```")
    return sortie


def barrer_le_code(texte: str) -> str:
    """Le même markdown, ses blocs de code barrés."""
    if not texte:
        return texte

    sortie: list[str] = []
    hors: list[str] = []
    dans_une_barriere = False

    for ligne in texte.split("\n"):
        if _BARRIERE.match(ligne):
            sortie.extend(_barrer_hors_barriere(hors))
            hors = []
            dans_une_barriere = not dans_une_barriere
            sortie.append(ligne)
        elif dans_une_barriere:
            sortie.append(ligne)
        else:
            hors.append(ligne)
    sortie.extend(_barrer_hors_barriere(hors))
    return "\n".join(sortie)
