"""Primitives d'indexation partagées par les deux routeurs à deux étages.

Le routing natif (`src/orchestrator/tool_retriever.py`) et le routing MCP
(`src/mcp_client/registry.py`) ont la même forme : un document d'étage 1 qui
décrit un CONTENANT (un groupe, un serveur) et sert à l'élire, puis un étage 2
qui ne cherche que parmi son contenu. Les deux ont besoin des deux mêmes
primitives, et aucun des deux ne doit dépendre de l'autre — d'où ce module
neutre plutôt qu'un import croisé.
"""

from __future__ import annotations

from typing import Iterable

# Place réservée au suffixe d'omission, pour qu'il tienne toujours sous le plafond.
_OMISSION_RESERVE = 32


def unique(values: Iterable) -> list[str]:
    """Dédoublonne en conservant l'ordre — celui d'un index est son classement
    de pertinence, le perdre revient à jeter le résultat de la recherche."""
    seen, out = set(), []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            out.append(value)
    return out


def build_catalog_document(header: dict[str, str], items_label: str,
                           names: Iterable[str], *, max_chars: int) -> str:
    """Document d'étage 1 : un en-tête descriptif, puis les noms qu'il contient.

    **Borné par construction.** Les descriptions du contenu n'ont rien à faire
    ici : elles vivent déjà dans les documents de l'étage 2. Les répéter
    n'ajouterait aucune information et ferait croître le document avec le nombre
    d'éléments — jusqu'à dépasser le contexte de l'embedder, qui échoue alors sur
    le catalogue entier. La taille doit être une propriété du document, pas un
    coup de chance sur le nombre d'éléments.

    Ce qui déborde est signalé (« … (+N autres) ») plutôt que tronqué en
    silence : un catalogue amputé sans trace est un catalogue faux.
    """
    names = list(names)
    head = "".join(f"{k}: {v[: max_chars // 2]}\n" for k, v in header.items())
    head += f"{items_label}: "
    budget = max(0, max_chars - len(head) - _OMISSION_RESERVE)

    kept: list[str] = []
    used = 0
    for name in names:
        piece = name if not kept else f", {name}"
        if used + len(piece) > budget:
            break
        kept.append(name)
        used += len(piece)

    document = head + ", ".join(kept)
    omitted = len(names) - len(kept)
    if omitted:
        document += f" … (+{omitted} autres)"
    return document[:max_chars]      # filet : le plafond est dur, jamais indicatif
