"""La complétion doit proposer TOUTES les commandes, et les vrais backends.

`commands.py` et `completer.py` tenaient chacun leur liste. Elles ont dérivé :

  - `/graph` et `/keys` existaient et étaient dispatchées, sans jamais apparaître
    sous la touche Tab ;
  - la liste des backends du completer s'était arrêtée à `gemini` — `mistral`
    puis `nvidia` étaient utilisables mais invisibles.

Une commande absente de la complétion n'existe pas pour qui découvre l'outil au
clavier. Ces tests comparent les deux sources plutôt que de vérifier une liste
figée : ils restent vrais quand des commandes sont ajoutées.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

_RACINE = Path(__file__).resolve().parents[1]


def _commandes_de(module: str) -> list[str]:
    """Le premier jeton de chaque entrée `_COMMANDS`, lu par AST.

    Par AST et non par import : ces modules tirent l'UI et les réglages, et un
    test de cohérence de listes n'a pas à dépendre d'un environnement complet.
    """
    arbre = ast.parse((_RACINE / "src" / "ui" / module).read_text(encoding="utf-8"))
    for noeud in ast.walk(arbre):
        cible = None
        if isinstance(noeud, ast.AnnAssign) and getattr(noeud.target, "id", None) == "_COMMANDS":
            cible = noeud.value
        elif isinstance(noeud, ast.Assign) and any(
                getattr(t, "id", None) == "_COMMANDS" for t in noeud.targets):
            cible = noeud.value
        if cible is not None:
            return [e.elts[0].value.split()[0] for e in cible.elts]
    raise AssertionError(f"_COMMANDS introuvable dans {module}")


def test_toute_commande_est_proposee_par_la_completion():
    declarees = _commandes_de("commands.py")
    completees = _commandes_de("completer.py")
    manquantes = [c for c in declarees if c not in completees]
    assert not manquantes, (
        "commandes invisibles sous Tab : " + ", ".join(manquantes))


def test_la_completion_ne_propose_rien_qui_n_existe_pas():
    """La faute symétrique : proposer une commande retirée envoie sur un message
    d'erreur, ce qui est pire que ne rien proposer."""
    declarees = _commandes_de("commands.py")
    completees = _commandes_de("completer.py")
    fantomes = [c for c in completees if c not in declarees]
    assert not fantomes, "commandes proposées mais inexistantes : " + ", ".join(fantomes)


def test_le_scanner_trouve_bien_des_commandes():
    """Un extracteur cassé rendrait les deux tests précédents vides, donc verts."""
    assert len(_commandes_de("commands.py")) > 20
    assert len(_commandes_de("completer.py")) > 20


def test_la_liste_des_backends_n_est_pas_recopiee():
    """Elle l'était, et elle a dérivé de deux backends. Le completer doit la LIRE
    chez `commands`, pas en tenir une copie."""
    from src.ui.completer import _SUBCOMMANDS

    assert "/backend" not in _SUBCOMMANDS, (
        "la liste des backends est de nouveau recopiée — elle dérivera")


def test_la_completion_propose_tous_les_backends_utilisables():
    from prompt_toolkit.completion import Completer
    from prompt_toolkit.document import Document

    import src.ui.completer as completer_mod
    from src.ui.commands import _backends

    _BACKENDS = _backends()

    classe = next(o for o in vars(completer_mod).values()
                  if isinstance(o, type) and issubclass(o, Completer) and o is not Completer)
    texte = "/backend "
    proposes = [c.text for c in classe().get_completions(
        Document(texte, len(texte)), None)]
    assert proposes == list(_BACKENDS)


@pytest.mark.parametrize("saisie, attendu", [
    ("/gr", "/graph"),
    ("/ke", "/keys"),
])
def test_les_deux_commandes_oubliees_se_completent(saisie, attendu):
    from prompt_toolkit.completion import Completer
    from prompt_toolkit.document import Document

    import src.ui.completer as completer_mod

    classe = next(o for o in vars(completer_mod).values()
                  if isinstance(o, type) and issubclass(o, Completer) and o is not Completer)
    proposes = [c.text for c in classe().get_completions(
        Document(saisie, len(saisie)), None)]
    assert attendu in proposes
