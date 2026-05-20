"""Mermaid diagram tool — renders clean diagrams from text definitions.

The LLM writes a Mermaid definition (text), this tool wraps it in a
standalone HTML page (dark theme, mermaid.js CDN) and opens it in the
browser. For web projects, it can also save the HTML to a specific path
and returns a ready-to-use embed snippet.
"""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from langchain_core.tools import tool


_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{title}</title>
  <script type="module">
    import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs';
    mermaid.initialize({{
      startOnLoad: true,
      theme: 'base',
      themeVariables: {{
        darkMode: true,
        background: '#0d1117',
        primaryColor: '#1e3a5f',
        primaryTextColor: '#e2e8f0',
        primaryBorderColor: '#3b82f6',
        lineColor: '#94a3b8',
        secondaryColor: '#2d1b69',
        tertiaryColor: '#1a3a2a',
        edgeLabelBackground: '#1e293b',
        fontFamily: 'Inter, system-ui, sans-serif',
        fontSize: '14px',
      }},
      flowchart: {{ curve: 'linear', padding: 24, useMaxWidth: false, htmlLabels: true }},
      sequence: {{ mirrorActors: false, useMaxWidth: false }},
    }});
  </script>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    html, body {{
      background: #0d1117;
      color: #e2e8f0;
      font-family: Inter, system-ui, sans-serif;
      min-height: 100vh;
      display: flex;
      flex-direction: column;
      align-items: center;
      padding: 40px 24px;
    }}
    h1 {{
      font-size: 1.4rem;
      font-weight: 600;
      color: #f97316;
      margin-bottom: 24px;
      letter-spacing: 0.02em;
    }}
    .export-bar {{
      display: flex;
      gap: 10px;
      margin-bottom: 24px;
    }}
    .export-btn {{
      background: #161b22;
      border: 1px solid #30363d;
      border-radius: 8px;
      color: #94a3b8;
      cursor: pointer;
      font-family: inherit;
      font-size: 0.8rem;
      padding: 6px 14px;
      transition: border-color 0.15s, color 0.15s;
    }}
    .export-btn:hover {{
      border-color: #3b82f6;
      color: #e2e8f0;
    }}
    .export-btn:active {{
      background: #1e293b;
    }}
    .mermaid-wrapper {{
      background: #161b22;
      border: 1px solid #30363d;
      border-radius: 12px;
      padding: 24px;
      width: 100%;
      max-width: 1200px;
      overflow: auto;
    }}
    .mermaid {{
      display: flex;
      justify-content: center;
    }}
    .mermaid svg {{
      max-width: 100%;
      display: block;
    }}
    .mermaid svg text {{
      fill: #e2e8f0 !important;
    }}
    .mermaid .label div,
    .mermaid .nodeLabel {{
      color: #e2e8f0 !important;
      text-align: center;
      line-height: 1.4;
      word-break: break-word;
    }}
  </style>
  <script>
    function exportPng(transparent) {{
      const svg = document.querySelector('.mermaid svg');
      if (!svg) {{ alert('Diagram not ready yet.'); return; }}
      const scale = 2;
      const bbox = svg.getBoundingClientRect();
      const w = Math.round(bbox.width  * scale) || 1200;
      const h = Math.round(bbox.height * scale) || 900;

      // Inline fonts so the canvas renderer doesn't fall back to system fonts
      const svgClone = svg.cloneNode(true);
      svgClone.setAttribute('width',  w);
      svgClone.setAttribute('height', h);

      const serializer = new XMLSerializer();
      const svgStr = serializer.serializeToString(svgClone);
      const blob = new Blob([svgStr], {{ type: 'image/svg+xml;charset=utf-8' }});
      const url  = URL.createObjectURL(blob);

      const img = new Image();
      img.onload = () => {{
        const canvas = document.createElement('canvas');
        canvas.width  = w;
        canvas.height = h;
        const ctx = canvas.getContext('2d');
        if (!transparent) {{
          ctx.fillStyle = '#0d1117';
          ctx.fillRect(0, 0, w, h);
        }}
        ctx.drawImage(img, 0, 0, w, h);
        URL.revokeObjectURL(url);

        const suffix = transparent ? 'transparent' : 'dark';
        canvas.toBlob(pngBlob => {{
          const a = document.createElement('a');
          a.href = URL.createObjectURL(pngBlob);
          a.download = `diagram-${{suffix}}.png`;
          a.click();
          setTimeout(() => URL.revokeObjectURL(a.href), 2000);
        }}, 'image/png');
      }};
      img.onerror = () => {{ URL.revokeObjectURL(url); alert('PNG export failed.'); }};
      img.src = url;
    }}
  </script>
</head>
<body>
  {title_tag}
  <div class="export-bar">
    <button class="export-btn" onclick="exportPng(true)">⬇ PNG sans fond</button>
    <button class="export-btn" onclick="exportPng(false)">⬇ PNG fond sombre</button>
  </div>
  <div class="mermaid-wrapper">
    <pre class="mermaid">
{definition}
    </pre>
  </div>
</body>
</html>
"""

_REACT_SNIPPET = """\
"use client";
import {{ useEffect, useRef }} from "react";

export default function Diagram() {{
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {{
    import("https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs").then((m) => {{
      m.default.initialize({{ startOnLoad: false, theme: "dark" }});
      if (ref.current) m.default.run({{ nodes: [ref.current] }});
    }});
  }}, []);

  return (
    <div ref={{ref}} className="mermaid">
      {definition_escaped}
    </div>
  );
}}
"""


def _inject_dark_theme(definition: str) -> str:
    """Prepend dark theme init directive if not already present."""
    if "%%{init" in definition:
        return definition
    return '%%{init: {"theme": "dark"}}%%\n' + definition


def _sanitize_definition(definition: str) -> str:
    """Quote node labels so special chars never break the Mermaid parser."""
    import re

    # Strip BOM / zero-width chars that confuse the lexer
    definition = definition.lstrip('﻿​‌‍')
    # Strip markdown code fences the LLM sometimes wraps around the definition
    definition = re.sub(r'^```(?:mermaid)?\s*', '', definition, flags=re.MULTILINE)
    definition = re.sub(r'\s*```$', '', definition, flags=re.MULTILINE)
    definition = definition.strip()

    def _force_quote(m: re.Match) -> str:
        open_b, content, close_b = m.group(1), m.group(2), m.group(3)
        if content.startswith('"') and content.endswith('"'):
            inner = content[1:-1].replace('"', "'")
            return f'{open_b}"{inner}"{close_b}'
        content = content.replace('"', "'").replace('`', "'")
        return f'{open_b}"{content}"{close_b}'

    _SKIP = ('%%', 'graph ', 'flowchart ', 'end', 'sequenceDiagram',
             'classDiagram', 'erDiagram', 'mindmap', 'gantt', 'style ', 'classDef ',
             'linkStyle ', 'direction ', 'xychart', 'timeline', 'sankey', 'block-beta',
             'architecture-beta')

    _EMOJI_RE = re.compile(r'[^\x00-\x7FÀ-ɏ̀-ͯ]')

    def _flatten_nested_brackets(line: str) -> str:
        result = []
        i = 0
        while i < len(line):
            if line[i] == '[':
                depth = 1
                j = i + 1
                while j < len(line) and depth > 0:
                    if line[j] == '[': depth += 1
                    elif line[j] == ']': depth -= 1
                    j += 1
                if depth == 0 and j > i + 2:
                    inner = line[i + 1:j - 1]
                    inner = re.sub(r'\["([^"]+)"\]', r'(\1)', inner)
                    inner = re.sub(r'\[([^\[\]]{1,60})\]', r'(\1)', inner)
                    result.append('[' + inner + ']')
                    i = j
                    continue
            result.append(line[i])
            i += 1
        return ''.join(result)

    cleaned = []
    for line in definition.splitlines():
        stripped = line.strip()
        if not stripped or any(stripped.startswith(p) for p in _SKIP):
            cleaned.append(line)
            continue
        if stripped.startswith('subgraph'):
            line = _EMOJI_RE.sub('', line).rstrip()
            # Auto-quote multi-word subgraph names not already in ID["Title"] format
            sg_m = re.match(r'^(\s*subgraph\s+)([\w][\w\s]*)$', line)
            if sg_m:
                prefix, name = sg_m.group(1), sg_m.group(2).strip()
                if ' ' in name:
                    node_id = ''.join(w[0].upper() for w in name.split())
                    line = f'{prefix}{node_id}["{name}"]'
            cleaned.append(line)
            continue
        line = _flatten_nested_brackets(line)
        # Fix already-quoted pipe labels with inner double quotes: |"a "b" c"| → |"a 'b' c"|
        line = re.sub(r'\|"((?:[^|])*?)"\|', lambda m: f'|"{m.group(1).replace(chr(34), chr(39))}"|', line)
        # Pipe edge labels: |text| → |"text"| (avoid parser ambiguity with special chars)
        line = re.sub(r'\|([^|"]{2,})\|', lambda m: f'|"{m.group(1).replace(chr(34), chr(39))}"|', line)
        # Quote (paren) nodes
        line = re.sub(r'(\()([^()\[\]]+)(\))', _force_quote, line)
        # Quote [bracket] nodes
        line = re.sub(r'(\[)([^\[\]]+)(\])', _force_quote, line)
        # Quote {curly} nodes (decision diamonds)
        line = re.sub(r'(\{)([^{}]+)(\})', _force_quote, line)
        cleaned.append(line)
    return '\n'.join(cleaned)


def _open_in_browser(path: Path) -> None:
    for cmd in (["xdg-open"], ["open"], ["wslview"]):
        try:
            subprocess.Popen(cmd + [str(path)],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        except FileNotFoundError:
            continue


@tool
def mermaid_diagram(
    definition: str,
    title: str = "Diagramme",
    export_to: str = "",
) -> str:
    """
    Génère un diagramme Mermaid et l'ouvre dans le navigateur.

    Utilise cet outil dès que l'utilisateur demande un schéma, diagramme,
    flowchart, graphe, architecture, séquence, mindmap, ou toute représentation
    visuelle. Mermaid génère automatiquement un layout propre — aucune coordonnée
    à calculer.

    Args:
        definition: Définition Mermaid complète.
                    Exemples de types :
                      graph TD / graph LR (flowchart)
                      sequenceDiagram
                      classDiagram
                      erDiagram
                      mindmap
                      gantt
                      C4Context / C4Container (architecture)
        title:      Titre affiché en haut du diagramme.
        export_to:  Chemin optionnel pour sauvegarder le fichier HTML dans un projet web.
                    Ex: "/home/user/mon-projet/public/diagrams/architecture.html"
                    Si vide → fichier temporaire ouvert dans le navigateur.
    Returns:
        Snippet d'intégration web (HTML + React/Next.js) + chemin du fichier généré.
    """
    definition = definition.strip()
    definition = _sanitize_definition(definition)

    title_tag = f"<h1>{title}</h1>" if title else ""
    html = _HTML_TEMPLATE.format(
        title=title or "Diagramme",
        title_tag=title_tag,
        definition=definition,
    )

    if export_to:
        out_path = Path(export_to).expanduser()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(html, encoding="utf-8")
        _open_in_browser(out_path)
        target = str(out_path)
    else:
        tmp = tempfile.NamedTemporaryFile(
            suffix=".html", prefix="axon_diagram_", delete=False
        )
        tmp.write(html.encode("utf-8"))
        tmp.flush()
        tmp.close()
        _open_in_browser(Path(tmp.name))
        target = tmp.name

    # Clean definition for embed snippet (strip theme directive)
    embed_def = definition
    if embed_def.startswith("%%{init"):
        embed_def = "\n".join(embed_def.split("\n")[1:]).strip()

    embed_html = (
        f'<!-- Mermaid CDN -->\n'
        f'<script type="module">\n'
        f'  import mermaid from "https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs";\n'
        f'  mermaid.initialize({{ startOnLoad: true, theme: "dark" }});\n'
        f'</script>\n'
        f'<div class="mermaid">\n{embed_def}\n</div>'
    )

    react_snippet = (
        f'// Composant React/Next.js\n'
        f'// Copie le composant ci-dessous dans ton projet :\n'
        + _REACT_SNIPPET.format(definition_escaped=embed_def.replace("`", "\\`"))
    )

    return (
        f"Diagramme généré : {target}\n\n"
        f"Si le navigateur affiche 'Syntax error', voici la définition sanitizée utilisée "
        f"(vérifie la syntaxe Mermaid 11) :\n```mermaid\n{definition}\n```\n\n"
        f"--- Embed HTML ---\n{embed_html}\n\n"
        f"--- React/Next.js ---\n{react_snippet}"
    )
