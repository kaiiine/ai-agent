"""`/deep` restait « non reconnu ».

Le commit d43876a a livré le sous-graphe `src/agents/deep/`, l'outil
`deep_research` et le nœud `approfondir` — mais jamais la commande. La même
demande en langage naturel fonctionnait ; la barre oblique, non.

Elle réécrit le message plutôt que d'ouvrir un chemin parallèle : tout ce qui
s'applique au graphe continue de s'appliquer.
"""
from __future__ import annotations

from pathlib import Path


def test_la_commande_est_declaree_dans_laide_et_lautocompletion():
    for chemin in ("src/ui/commands.py", "src/ui/completer.py"):
        assert "/deep" in Path(chemin).read_text(encoding="utf-8"), chemin


def test_elle_passe_par_le_graphe_et_non_par_un_runner():
    """`/build` appelle son runner directement — c'est légitime, il pilote des
    phases. `/deep` a un nœud dans le graphe : le court-circuiter lui ferait
    perdre confirmation, révision et compression."""
    src = Path("src/ui/streaming.py").read_text(encoding="utf-8")
    bloc = src[src.index('user_message.startswith("/deep ")'):]
    bloc = bloc[:bloc.index("build_message_with_attachments")]
    assert "deep_research" in bloc
    assert "run_deep" not in bloc


def test_loutil_et_le_noeud_existent_bien():
    from src.orchestrator.registry import build_all_tools

    assert "deep_research" in {o.name for o in build_all_tools()}
    from src.agents.deep.noeud import approfondir  # noqa: F401


def test_sans_sujet_elle_explique_au_lieu_de_lancer():
    src = Path("src/ui/streaming.py").read_text(encoding="utf-8")
    assert "usage : /deep <ce que tu veux creuser>" in src
