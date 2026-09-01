"""Un extrait de code sans barrières ne doit pas être détruit par le rendu.

`rich.Markdown` recolle les lignes d'un paragraphe et interprète ses marques. Vécu
sur une réponse finale de l'agent de code :

    def parse_numbers(tokens): numbers = [] for token in tokens: try: …
    if name == "main": main()

Tout le corps sur une ligne, `__name__` avalé par le gras de `__…__`. Le prompt
demande désormais les barrières, mais un modèle qui les oublie ne doit pas rendre
sa réponse illisible pour autant.
"""
from __future__ import annotations

from src.ui.code_non_barre import barrer_le_code

SOURCE = '''#!/usr/bin/env python3

import sys

def parse_numbers(tokens):
    numbers = []
    for token in tokens:
        try:
            numbers.append(int(token))
        except ValueError:
            sys.exit(1)
    return numbers

if __name__ == "__main__":
    main()
'''


def _rendu(texte: str) -> str:
    from rich.console import Console
    from rich.markdown import Markdown

    console = Console(width=100, file=__import__("io").StringIO())
    console.print(Markdown(barrer_le_code(texte)))
    return console.file.getvalue()


def test_le_code_garde_ses_sauts_de_ligne():
    rendu = _rendu(SOURCE)

    assert "def parse_numbers(tokens): numbers = []" not in rendu
    assert "return numbers" in rendu


def test_les_doubles_soulignes_survivent():
    """`__name__` devenait `name` : le gras markdown mangeait les soulignés."""
    assert '__name__ == "__main__"' in _rendu(SOURCE)


def test_une_source_aeree_forme_un_seul_bloc():
    """Les lignes vides d'une source ne doivent pas la casser en fragments."""
    barre = barrer_le_code(SOURCE)

    assert barre.count("```") == 2


def test_la_prose_reste_de_la_prose():
    """Une fausse barrière abîmerait un paragraphe — c'est ce qu'on évite."""
    prose = ("Le script a été créé et testé. Il accepte des nombres en arguments\n"
             "ou sur l'entrée standard.\n\n"
             "J'ai vérifié deux cas :\n"
             "- `python tri.py 5 2 9` rend `[2, 5, 9]`\n"
             "- `python tri.py a b` sort en 1\n")

    assert barrer_le_code(prose) == prose


def test_une_phrase_finissant_par_deux_points_nest_pas_du_code():
    texte = "J'ai vérifié deux cas :\nle tri normal, et l'entrée invalide.\n"

    assert barrer_le_code(texte) == texte


def test_ce_qui_est_deja_barre_nest_pas_retouche():
    texte = "Voici :\n\n```python\ndef f(x):\n    return x\n```\n\nEt c'est tout."

    assert barrer_le_code(texte) == texte


def test_du_code_barre_et_de_la_prose_cohabitent():
    texte = ("Le résultat :\n\n" + SOURCE + "\nVoilà, c'est fini.\n")

    barre = barrer_le_code(texte)

    assert barre.count("```") == 2
    assert barre.startswith("Le résultat :")
    assert barre.rstrip().endswith("Voilà, c'est fini.")


def test_un_texte_vide_ne_casse_rien():
    assert barrer_le_code("") == ""
