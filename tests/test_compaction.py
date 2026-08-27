"""`/compact` annonçait une compression qui n'avait pas eu lieu.

Vécu : « contexte compressé — 3 666 → 3 666 tokens (-0) ». Deux seuils qui ne se
parlaient pas — la commande refuse sous 3 messages, le compresseur garde les
`keep_recent` derniers intacts, soit 12 sur ollama_cloud et 24 sur gemini. Entre
les deux, l'opération ne fait rien et se déclare réussie.

Un rapport qui appelle succès une opération sans effet coûte plus qu'une opération
absente : il envoie chercher le bug ailleurs.
"""
from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from src.orchestrator.context import (
    _BACKEND_POLICY, _backend_policy, _compress_context, _estimate_tokens,
)


def _fil(n: int) -> list:
    return [SystemMessage("systeme")] + [
        (HumanMessage if i % 2 == 0 else AIMessage)(f"message numero {i} " * 30)
        for i in range(n)
    ]


@pytest.mark.parametrize("backend", sorted(_BACKEND_POLICY))
def test_dans_la_fenetre_recente_rien_nest_compresse(backend):
    """C'est le fait que le message doit énoncer, et non déguiser en gain."""
    garde = _backend_policy(backend)["keep_recent"]
    messages = _fil(garde)
    compresse, retires = _compress_context(messages, None, backend)
    assert _estimate_tokens(compresse) == _estimate_tokens(messages)
    assert retires == []


@pytest.mark.parametrize("backend", sorted(_BACKEND_POLICY))
def test_au_dela_de_la_fenetre_la_compression_agit(backend):
    garde = _backend_policy(backend)["keep_recent"]
    messages = _fil(garde + 8)
    compresse, _ = _compress_context(messages, None, backend)
    assert _estimate_tokens(compresse) < _estimate_tokens(messages)


def test_la_commande_ne_declare_pas_succes_sans_gain():
    """Garde de comportement écrite sur le texte, faute de pouvoir instancier le
    graphe ici : ce qui compte est qu'un chemin traite explicitement le cas où
    rien n'a été libéré, avant de composer le rapport de succès."""
    import pathlib

    src = pathlib.Path("src/ui/commands.py").read_text(encoding="utf-8")
    # La chaîne de FORMAT, pas la phrase : le commentaire qui documente le bug
    # cite le message d'origine et arrivait avant le garde dans le fichier.
    rapport = 'f"contexte compressé — "'
    assert "if freed <= 0:" in src
    assert src.index("if freed <= 0:") < src.index(rapport)
