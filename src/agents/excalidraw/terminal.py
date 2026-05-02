"""Terminal diagram renderer — draws flowcharts/architectures inline in the console."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from rich.console import Console
from rich.text import Text
from rich.panel import Panel
from rich import box as rbox

_console = Console()

NodeType = Literal["box", "diamond", "rounded", "circle", "note"]

_ACCENT = "color(214)"


@dataclass
class Node:
    id: str
    label: str
    type: NodeType = "box"
    color: str = "white"
    bg: str = ""
    row: int = 0
    col: int = 0


@dataclass
class Edge:
    src: str
    dst: str
    label: str = ""
    style: Literal["solid", "dashed", "dotted"] = "solid"


# ── Unicode shapes ─────────────────────────────────────────────────────────────

def _render_node(node: Node, width: int = 20) -> list[str]:
    """Returns a list of text lines representing the node shape."""
    label = node.label
    w = max(width, len(label) + 4)

    if node.type == "diamond":
        half = (w + 2) // 2
        top = " " * (half) + "◆"
        mid = "◀" + " " + label.center(w - 2) + " " + "▶"
        bot = " " * (half) + "◆"
        return [top, mid, bot]

    if node.type == "circle":
        return [f"( {label} )"]

    if node.type == "note":
        lines = [
            f"┌{'─' * (w - 2)}╮",
            f"│ {label.center(w - 4)} │",
            f"└{'─' * (w - 2)}┘",
        ]
        return lines

    if node.type == "rounded":
        lines = [
            f"╭{'─' * (w - 2)}╮",
            f"│ {label.center(w - 4)} │",
            f"╰{'─' * (w - 2)}╯",
        ]
        return lines

    # default: box
    lines = [
        f"┌{'─' * (w - 2)}┐",
        f"│ {label.center(w - 4)} │",
        f"└{'─' * (w - 2)}┘",
    ]
    return lines


def _arrow(style: str = "solid", label: str = "") -> str:
    body = "──" if style == "solid" else ("╌╌" if style == "dashed" else "··")
    lbl = f" {label} " if label else ""
    return f"    {body}{lbl}{body}▶"


def _render_vertical(nodes: list[Node], edges: list[Edge], title: str) -> str:
    """Render a top-to-bottom flow."""
    # Build adjacency for ordering
    id_map = {n.id: n for n in nodes}
    edge_map: dict[str, list[Edge]] = {n.id: [] for n in nodes}
    for e in edges:
        if e.src in edge_map:
            edge_map[e.src].append(e)

    # Topological order (or insertion order as fallback)
    visited: set[str] = set()
    ordered: list[Node] = []

    def _visit(nid: str):
        if nid in visited:
            return
        visited.add(nid)
        ordered.append(id_map[nid])
        for e in edge_map.get(nid, []):
            _visit(e.dst)

    # Find roots (nodes with no incoming edges)
    has_incoming = {e.dst for e in edges}
    roots = [n for n in nodes if n.id not in has_incoming]
    if not roots:
        roots = nodes[:1]
    for r in roots:
        _visit(r.id)
    # Any remaining
    for n in nodes:
        _visit(n.id)

    max_label = max((len(n.label) for n in nodes), default=10)
    node_width = max_label + 6

    lines: list[str] = []
    for i, node in enumerate(ordered):
        node_lines = _render_node(node, node_width)
        lines.extend(node_lines)

        # Find outgoing edges from this node
        out_edges = edge_map.get(node.id, [])
        # Only draw arrow if next node is the direct successor
        next_node = ordered[i + 1] if i + 1 < len(ordered) else None
        if next_node:
            matching = [e for e in out_edges if e.dst == next_node.id]
            e = matching[0] if matching else Edge(node.id, next_node.id)
            lines.append(_arrow(e.style, e.label))

    return "\n".join(lines)


def _render_horizontal(nodes: list[Node], edges: list[Edge], title: str) -> str:
    """Render a left-to-right row of nodes connected by arrows."""
    id_map = {n.id: n for n in nodes}
    edge_map: dict[str, Edge} = {}
    for e in edges:
        edge_map[e.src] = e

    max_label = max((len(n.label) for n in nodes), default=10)
    node_width = max_label + 6

    # Build rows: each node = 3 lines, padded to same height
    top_row = ""
    mid_row = ""
    bot_row = ""

    for i, node in enumerate(nodes):
        nl = _render_node(node, node_width)
        while len(nl) < 3:
            nl.append(" " * len(nl[0]))
        top_row += nl[0]
        mid_row += nl[1]
        bot_row += nl[2]

        if i < len(nodes) - 1:
            e = edge_map.get(node.id)
            connector = "──▶" if not e or e.style == "solid" else "╌╌▶"
            label = f"╌{e.label}╌" if e and e.label else ""
            pad = (len(nl[0]) // 2)
            top_row += "   "
            mid_row += f"{connector}{label}"
            bot_row += "   "

    return f"{top_row}\n{mid_row}\n{bot_row}"


# ── Public renderer ────────────────────────────────────────────────────────────

def render_diagram(
    title: str,
    nodes: list[Node],
    edges: list[Edge],
    direction: Literal["vertical", "horizontal"] = "vertical",
    console: Console | None = None,
) -> None:
    con = console or _console
    if direction == "horizontal":
        body = _render_horizontal(nodes, edges, title)
    else:
        body = _render_vertical(nodes, edges, title)

    con.print(Panel(
        Text(body, style="white"),
        title=f"[bold {_ACCENT}]{title}[/bold {_ACCENT}]",
        border_style=f"dim {_ACCENT}",
        box=rbox.SIMPLE_HEAD,
        padding=(1, 3),
    ))
