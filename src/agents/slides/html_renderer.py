"""HTML/Reveal.js renderer — professional alternating dark/light theme."""
from __future__ import annotations

import html as _html
import re as _re
import re
from datetime import date
from typing import Any


# L'identité d'Axon est l'ambre : `color(214)` = #ffaf00, présent dans toute
# l'interface terminal — invite, badges, règles, panneaux. Le violet du banner
# n'est pas ce que le produit montre à l'usage.
#
# UN SEUL accent, décliné en intensité. Trois couleurs saturées attribuées à des
# cartes voisines sans raison sémantique, c'est le rendu « arc-en-ciel » qui
# signe une génération automatique — et que l'anti-slop de `skills/frontend.md`
# interdit déjà pour le web. Les deux valeurs suivantes ne sont donc plus des
# accents concurrents mais des DEGRÉS du même.
_ACCENTS = ["#ffaf00", "#d98c00", "#8a6a2f"]

def _accent(idx: int) -> str:
    return _ACCENTS[idx % len(_ACCENTS)]

def _e(s: Any) -> str:
    return _html.escape(str(s or ""))

def _md(s: Any) -> str:
    """HTML-escape then convert basic inline markdown (**bold**, *italic*, `code`)."""
    text = _html.escape(str(s or ""))
    text = _re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', text)
    text = _re.sub(r'\*(.*?)\*', r'<em>\1</em>', text)
    text = _re.sub(r'`(.*?)`', r'<code>\1</code>', text)
    return text

# Noir CHAUD, pas l'ardoise bleue générique : un fond neutre-froid sous un
# accent ambre produit un contraste sale. Le terminal utilise #1a0d00 derrière
# son badge de plan — même famille.
_DARK_BG    = "#0c0a08"
_SECTION_BG = "#12100c"
_QUOTE_BG   = "#0a0806"


def _section_open(slide: dict, extra_class: str = "") -> str:
    return f'<section class="s-dark {extra_class}" style="background-color:{_DARK_BG}">'


# ── Blocs de code ─────────────────────────────────────────────────────────────
#
# Une présentation sur TypeScript sans un seul bloc de code : c'est ce que le
# gabarit produisait, faute d'un type qui en accepte. Le modèle repliait sur des
# `<code>` en ligne au milieu des puces — 31 dans un deck, zéro `<pre>`.
#
# La coloration est faite ICI, en Python, et non par une bibliothèque chargée
# depuis un CDN : le deck doit rester lisible hors ligne, et une dépendance
# réseau de plus est une panne de plus le jour de la présentation.

_MOTS_CLES = frozenset("""
const let var function return if else for while do switch case break continue
class extends implements interface type enum import export from as default
new await async yield try catch finally throw typeof instanceof in of delete
public private protected readonly static abstract declare namespace satisfies
def elif lambda pass raise with global nonlocal assert None True False
fn pub impl struct trait match mut use where self Self crate
""".split())

_TYPES_CONNUS = frozenset("""
string number boolean object symbol bigint any unknown never void null undefined
Array Promise Record Partial Pick Omit Readonly ReturnType Map Set Date RegExp
React FC ReactNode JSX Props State int float str bool list dict tuple
""".split())

_JETON = re.compile(r"""
    (?P<commentaire>//[^\n]*|\#[^\n]*|/\*.*?\*/)
  | (?P<chaine>"(?:[^"\\\n]|\\.)*"|'(?:[^'\\\n]|\\.)*'|`(?:[^`\\]|\\.)*`)
  | (?P<nombre>\b\d+(?:\.\d+)?\b)
  | (?P<mot>[A-Za-z_$][\w$]*)
""", re.X | re.S)


def _colorer(code: str) -> str:
    """Colorise un extrait sans exécuter ni parser : on ne fait que TEINTER.

    Un vrai analyseur syntaxique se tromperait sur les langages qu'il ne connaît
    pas et casserait l'affichage. Ici, un jeton non reconnu reste du texte
    normal : le pire cas est un extrait en noir et blanc, jamais un extrait
    illisible ou tronqué.
    """
    sortie: list[str] = []
    position = 0
    for m in _JETON.finditer(code):
        sortie.append(_e(code[position:m.start()]))
        position = m.end()
        brut = m.group(0)
        if m.group("commentaire"):
            classe = "cm"
        elif m.group("chaine"):
            classe = "st"
        elif m.group("nombre"):
            classe = "nb"
        elif brut in _MOTS_CLES:
            classe = "kw"
        elif brut in _TYPES_CONNUS or (brut[:1].isupper() and len(brut) > 1):
            classe = "ty"
        else:
            sortie.append(_e(brut))
            continue
        sortie.append(f'<span class="c-{classe}">{_e(brut)}</span>')
    sortie.append(_e(code[position:]))
    return "".join(sortie)


def _bloc_code(code: str, langage: str = "", legende: str = "") -> str:
    if not code:
        return ""
    chip = f'<span class="code-lang">{_e(langage)}</span>' if langage else ""
    cap = f'<div class="code-cap">{_e(legende)}</div>' if legende else ""
    return (f'<div class="code-wrap">{chip}'
            f'<pre class="code-pre"><code>{_colorer(code.strip())}</code></pre>{cap}</div>')


# ── Slide renderers ───────────────────────────────────────────────────────────

_MOIS = ("janvier", "février", "mars", "avril", "mai", "juin", "juillet",
         "août", "septembre", "octobre", "novembre", "décembre")


def _mois_courant() -> str:
    """« août 2026 », pas « August 2026 ».

    `strftime("%B %Y")` suit la locale du processus, qui est le plus souvent C :
    un deck écrit en français se datait donc en anglais.
    """
    aujourd_hui = date.today()
    return f"{_MOIS[aujourd_hui.month - 1]} {aujourd_hui.year}"


def _slide_title(s: dict, idx: int) -> str:
    ac = _accent(0)
    subtitle = f'<p class="s-subtitle">{_e(s.get("subtitle",""))}</p>' if s.get("subtitle") else ""
    meta = [x for x in [s.get("author"), s.get("date", _mois_courant())] if x]
    chips = "".join(f'<span class="chip">{_e(m)}</span>' for m in meta)
    chips_html = f'<div class="s-chips">{chips}</div>' if chips else ""
    src_html = f'<div class="s-source">{_e(s.get("source",""))}</div>' if s.get("source") else ""
    eyebrow = _e(s.get("eyebrow", "PRÉSENTATION"))
    image_url = s.get("image_url", "")
    img_bg = (
        f'<div class="s-bg-image" style="background-image:url(\'{image_url}\')" '
        f'onerror="this.style.display=\'none\'"></div>'
        f'<div class="s-bg-overlay"></div>'
    ) if image_url else ""
    return f"""
<section class="s-dark" style="background-color:{_DARK_BG}">
  <div class="s-deco-bar" style="background:{ac}"></div>
  {img_bg}
  <div class="s-bg-grid"></div>
  <div class="s-glow" style="background:radial-gradient(ellipse 55% 60% at 15% 60%,{ac}28,transparent);"></div>
  <div class="s-inner s-title-layout">
    <div class="eyebrow" style="color:{ac}">{eyebrow}</div>
    <h1 class="s-main-title">{_e(s.get("title",""))}</h1>
    {subtitle}
    {chips_html}
    {src_html}
  </div>
</section>"""


#: Encre à poser SUR une surface accent. L'ambre est une couleur CLAIRE : du
#: blanc dessus tombe sous le seuil de contraste. Les gabarits alternaient
#: `#0d1320` et `#fff` selon l'INDICE de la colonne — donc une colonne sur deux
#: était illisible, quelle que soit la couleur de fond réelle.
_ENCRE_SUR_ACCENT = "#1a1206"


def _slide_agenda(s: dict, idx: int) -> str:
    hdr_ac = _accent(idx)
    items = s.get("items", [])
    cards = ""
    for i, item in enumerate(items[:6]):
        # Le même accent pour tous les numéros. `_accent(i)` cyclait sur trois
        # intensités du même ambre : le troisième point sortait plus terne que
        # ses voisins, ce qui se lit comme une erreur d'affichage et non comme
        # une intention.
        ac = _accent(0)
        if isinstance(item, dict):
            label = _e(item.get("label", ""))
            sub   = f'<div class="agc-sub">{_e(item.get("sub",""))}</div>' if item.get("sub") else ""
        else:
            label = _e(item)
            sub   = ""
        cards += f"""
      <div class="agc-card">
        <div class="agc-num" style="color:{ac}">{str(i+1).zfill(2)}</div>
        <div class="agc-label">{label}</div>
        {sub}
      </div>"""
    # `min(3, n)` laissait un orphelin dès que le compte n'était pas un multiple
    # de 3 : quatre points donnaient trois cartes puis une seule, et un trou.
    # Une grille se choisit pour que la DERNIÈRE rangée soit pleine.
    n = min(len(items), 6) or 1
    cols = {1: 1, 2: 2, 3: 3, 4: 2, 5: 3, 6: 3}[n]
    return f"""
{_section_open(s)}
  <div class="s-inner">
    <div class="s-hdr">
      <div class="s-stripe" style="background:{hdr_ac}"></div>
      <h2 class="s-title">{_e(s.get("title","Sommaire"))}</h2>
    </div>
    <div class="agc-grid agc-cols-{cols}">{cards}
    </div>
  </div>
</section>"""


def _slide_content(s: dict, idx: int) -> str:
    ac = _accent(idx)
    raw_body = s.get("body", "")
    body_text = raw_body[:500] + ("…" if len(raw_body) > 500 else "") if raw_body else ""
    body    = f'<p class="s-body">{_md(body_text)}</p>' if body_text else ""
    bullets = s.get("bullets", [])[:6]
    bl_html = ""
    if bullets:
        n = len(bullets)
        density = "bl-few" if n <= 3 else "bl-med" if n <= 5 else "bl-many"
        items = "".join(
            f'<li style="border-left-color:{ac}">{_md(b)}</li>'
            for b in bullets
        )
        bl_html = f'<ul class="bl-list {density}">{items}</ul>'
    deco_panel = f'<div class="s-deco-panel" style="background:linear-gradient(90deg,transparent 0%,{ac}08 55%,{ac}1c 100%)"></div>'
    return f"""
{_section_open(s)}
  <div class="s-glow" style="background:radial-gradient(ellipse 50% 55% at 85% 15%,{ac}1a,transparent);"></div>
  {deco_panel}
  <div class="s-inner s-has-deco">
    <div class="s-hdr">
      <div class="s-stripe" style="background:{ac}"></div>
      <h2 class="s-title">{_e(s.get("title",""))}</h2>
    </div>
    <div class="s-cbody">{body}{bl_html}</div>
  </div>
</section>"""


def _slide_split(s: dict, idx: int) -> str:
    ac = _accent(idx)

    def _col(col: dict, col_ac: str) -> str:
        h  = f'<div class="col-hd" style="color:{col_ac}">{_e(col.get("heading",""))}</div>' if col.get("heading") else ""
        raw_b = col.get("body", "")
        body_text = raw_b[:350] + ("…" if len(raw_b) > 350 else "") if raw_b else ""
        b  = f'<p class="s-body">{_md(body_text)}</p>' if body_text else ""
        bl = col.get("bullets", [])[:5]
        bl_html = ""
        if bl:
            n = len(bl)
            density = "bl-few" if n <= 3 else "bl-med" if n <= 4 else "bl-many"
            items = "".join(
                f'<li style="border-left-color:{col_ac}">{_md(x)}</li>'
                for x in bl
            )
            bl_html = f'<ul class="bl-list {density}">{items}</ul>'
        return f'<div class="split-col">{h}{b}{bl_html}</div>'

    return f"""
{_section_open(s)}
  <div class="s-glow" style="background:radial-gradient(ellipse 60% 50% at 50% 85%,{ac}18,transparent);"></div>
  <div class="s-inner">
    <div class="s-hdr">
      <div class="s-stripe" style="background:{ac}"></div>
      <h2 class="s-title">{_e(s.get("title",""))}</h2>
    </div>
    <div class="split-grid">
      {_col(s.get("left",  {}), _accent(0))}
      <div class="split-div"></div>
      {_col(s.get("right", {}), _accent(0))}
    </div>
  </div>
</section>"""


def _slide_split3(s: dict, idx: int) -> str:
    cols_data = s.get("columns", [])
    cols_html = ""
    for i, col in enumerate(cols_data[:3]):
        ac = col.get("color") or _accent(i)
        hdr = _e(col.get("heading", ""))
        bl  = col.get("bullets", [])[:5]
        raw_body = col.get("body", "")
        body_text = raw_body[:300] + ("…" if len(raw_body) > 300 else "") if raw_body else ""
        body = f'<p class="s-body">{_md(body_text)}</p>' if body_text else ""
        n = len(bl)
        density = "bl-few" if n <= 3 else "bl-med" if n <= 4 else "bl-many"
        items = "".join(
            f'<li style="border-left-color:{ac}">{_md(b)}</li>'
            for b in bl
        )
        bl_html = f'<ul class="bl-list {density}">{items}</ul>' if bl else ""
        text_col = "#0d1320" if i == 1 else "#ffffff"
        cols_html += f"""
      <div class="split3-col">
        <div class="split3-hdr" style="background:{ac};color:{text_col}">{hdr}</div>
        <div class="split3-body">{body}{bl_html}</div>
      </div>"""
    return f"""
{_section_open(s)}
  <div class="s-inner">
    <div class="s-hdr">
      <div class="s-stripe" style="background:{_accent(idx)}"></div>
      <h2 class="s-title">{_e(s.get("title",""))}</h2>
    </div>
    {f'<p class="s-body" style="margin-bottom:16px">{_e(s.get("body",""))}</p>' if s.get("body") else ""}
    <div class="split3-grid">{cols_html}
    </div>
  </div>
</section>"""


def _slide_stats(s: dict, idx: int) -> str:
    stats = s.get("stats", [])
    cards = ""
    for i, st in enumerate(stats[:6]):
        # Le MÊME accent pour toutes : une couleur par carte ferait croire à une
        # distinction qui n'existe pas, et c'est ce qui produit l'arc-en-ciel.
        ac = _accent(0)
        src  = f'<div class="st-src">{_e(st.get("source",""))}</div>' if st.get("source") else ""
        cards += f"""
      <div class="st-card">
        <div class="st-val" style="color:{ac}">{_e(st.get("value",""))}</div>
        <div class="st-lbl">{_e(st.get("label",""))}</div>
        {src}
      </div>"""
    n = min(len(stats), 6)
    # `2 if n <= 4 else 3` mettait TROIS stats sur deux colonnes : deux cartes en
    # haut, une en bas à gauche, et un trou béant en bas à droite. Le nombre de
    # colonnes doit suivre le nombre d'éléments, pas un seuil.
    cols = {1: 1, 2: 2, 3: 3, 4: 2, 5: 3, 6: 3}[n]
    grid_max = {1: "460px", 2: "820px", 3: "1080px",
                4: "820px", 5: "1080px", 6: "1080px"}[n]
    src_global = f'<p class="s-source-global">{_e(s.get("source",""))}</p>' if s.get("source") else ""
    return f"""
{_section_open(s)}
  <div class="s-inner s-stack">
    <h2 class="s-title s-title-dark">{_e(s.get("title",""))}</h2>
    {src_global}
    <div class="st-grid st-cols-{cols}" style="max-width:{grid_max}">{cards}
    </div>
  </div>
</section>"""


def _slide_table(s: dict, idx: int) -> str:
    cols  = s.get("columns", [])
    rows  = s.get("rows", [])
    ncols = len(cols)
    ac    = _accent(idx)
    grid_cols = f"minmax(200px, 1.2fr) repeat({ncols}, 1fr)"

    hdr_cells = "".join(
        f'<div class="tbl-hdr" style="color:{_accent(0)}">'
        f'{_e(c.get("label","") if isinstance(c,dict) else c)}</div>'
        for c in cols
    )
    rows_html = ""
    for r, row in enumerate(rows):
        # Une ligne peut arriver comme dict {dim, values} ou comme simple liste :
        # la seconde est la forme qu'on écrit spontanément, et elle levait
        # `AttributeError: 'list' object has no attribute 'get'`.
        if isinstance(row, dict):
            dim, valeurs = row.get("dim", ""), row.get("values", [])
        else:
            valeurs = list(row)
            dim, valeurs = (valeurs[0], valeurs[1:]) if len(valeurs) > ncols else ("", valeurs)
        val_cells = "".join(f'<div class="tbl-val">{_e(v)}</div>' for v in valeurs[:ncols])
        alt_class = "tbl-row-alt" if r % 2 == 1 else ""
        rows_html += f"""
      <div class="tbl-row {alt_class}" style="grid-template-columns:{grid_cols}">
        <div class="tbl-dim" style="color:{ac}">{_e(dim)}</div>
        {val_cells}
      </div>"""

    return f"""
{_section_open(s)}
  <div class="s-inner">
    <h2 class="s-title">{_e(s.get("title",""))}</h2>
    <div class="tbl-wrap">
      <div class="tbl-head" style="grid-template-columns:{grid_cols}">
        <div class="tbl-dim-hdr"></div>
        {hdr_cells}
      </div>
      {rows_html}
    </div>
  </div>
</section>"""


def _slide_cases(s: dict, idx: int) -> str:
    ac = _accent(idx)
    cases = s.get("cases", [])
    # Même règle que partout : la dernière rangée doit être pleine. Trois cas
    # dans une grille figée à deux colonnes laissaient un orphelin et un trou.
    ncas = {0: 1, 1: 1, 2: 2, 3: 3, 4: 2}[min(len(cases), 4)]
    cards = ""
    for i, c in enumerate(cases[:4]):
        card_ac    = c.get("color") or _accent(0)
        text_color = _ENCRE_SUR_ACCENT
        body   = _e(c.get("body", ""))
        lesson = _e(c.get("lesson", ""))
        lesson_html = f'<div class="cs-lesson" style="color:{card_ac}">{lesson}</div>' if lesson else ""
        cards += f"""
      <div class="cs-card">
        <div class="cs-hdr" style="background:{card_ac};color:{text_color}">
          <span>{_e(c.get("company",""))}</span>
          <span class="cs-arch">{_e(c.get("arch",""))}</span>
        </div>
        <div class="cs-body">
          <p>{body}</p>
          {lesson_html}
        </div>
      </div>"""
    return f"""
{_section_open(s)}
  <div class="s-inner">
    <div class="s-hdr">
      <div class="s-stripe" style="background:{ac}"></div>
      <h2 class="s-title">{_e(s.get("title",""))}</h2>
    </div>
    <div class="cs-grid cs-cols-{ncas}">{cards}
    </div>
  </div>
</section>"""


def _slide_quote(s: dict, idx: int) -> str:
    ac = _accent(idx)
    role = f'<div class="q-role">{_e(s.get("role",""))}</div>' if s.get("role") else ""
    return f"""
<section class="s-dark" style="background-color:{_QUOTE_BG}">
  <div class="s-glow" style="background:radial-gradient(ellipse 70% 60% at 50% 50%,{ac}22,transparent);"></div>
  <div class="s-inner s-center">
    <div class="q-mark" style="color:{ac}">&ldquo;</div>
    <blockquote class="q-text">{_e(s.get("quote",""))}</blockquote>
    <div class="q-author" style="color:{ac}">&#8212; {_e(s.get("author",""))}</div>
    {role}
  </div>
</section>"""


def _slide_closing(s: dict, idx: int) -> str:
    ac = _accent(0)
    subtitle = f'<p class="s-subtitle cl-sub">{_e(s.get("subtitle",""))}</p>' if s.get("subtitle") else ""
    raw_cta = (s.get("cta") or "")[:60]
    cta = f'<div class="cta-pill" style="border-color:{ac};color:{ac}">{_e(raw_cta)}</div>' if raw_cta else ""
    eyebrow = _e(s.get("eyebrow", "MERCI"))
    return f"""
<section class="s-dark" style="background-color:{_DARK_BG}">
  <div class="s-deco-bar s-deco-right" style="background:{ac}"></div>
  <div class="s-bg-grid"></div>
  <div class="s-glow" style="background:radial-gradient(ellipse 60% 50% at 85% 40%,{ac}22,transparent);"></div>
  <div class="s-inner s-center">
    <div class="eyebrow" style="color:{ac}">{eyebrow}</div>
    <h1 class="s-main-title">{_e(s.get("title",""))}</h1>
    {subtitle}
    {cta}
  </div>
</section>"""


def _slide_timeline(s: dict, idx: int) -> str:
    steps = s.get("steps", [])
    steps_html = ""
    for i, step in enumerate(steps[:6]):
        ac = step.get("color") or _accent(0)
        num = _e(step.get("num", str(i + 1).zfill(2)))
        label = _e(step.get("label", ""))
        sub = f'<div class="tl-sub">{_e(step.get("sub", ""))}</div>' if step.get("sub") else ""
        dur = f'<div class="tl-duration">{_e(step.get("duration", ""))}</div>' if step.get("duration") else ""
        steps_html += f"""
    <div class="tl-step">
      <div class="tl-dot" style="background:{ac}">{num}</div>
      <div class="tl-content">
        <div class="tl-label">{label}</div>
        {sub}
        {dur}
      </div>
    </div>"""
    sub_title = f'<p class="s-body" style="margin-bottom:12px">{_e(s.get("subtitle",""))}</p>' if s.get("subtitle") else ""
    return f"""
<section class="s-dark" style="background-color:{_DARK_BG}">
  <div class="s-inner">
    <h2 class="s-title s-title-dark">{_e(s.get("title", "Programme"))}</h2>
    {sub_title}
    <div class="tl-wrap">
      <div class="tl-track">
        <div class="tl-line"></div>
        {steps_html}
      </div>
    </div>
  </div>
</section>"""


def _slide_section(s: dict, idx: int) -> str:
    ac  = _accent(idx)
    num = _e(s.get("num", str(idx).zfill(2)))
    eyebrow = _e(s.get("eyebrow", "PARTIE"))
    title = _e(s.get("title", ""))
    sub = f'<p class="sec-sub">{_e(s.get("subtitle",""))}</p>' if s.get("subtitle") else ""
    return f"""
<section class="s-dark" style="background-color:{_SECTION_BG}">
  <div class="s-bg-grid"></div>
  <div class="s-glow" style="background:radial-gradient(ellipse 80% 80% at 18% 50%,{ac}1e,transparent);"></div>
  <div class="s-inner sec-layout">
    <div class="sec-left">
      <div class="s-glow" style="background:radial-gradient(ellipse 70% 60% at 50% 50%,{ac}22,transparent);"></div>
      <div class="sec-num-display" style="color:rgba(255,255,255,0.20)">{num}</div>
    </div>
    <div class="sec-right">
      <div class="eyebrow" style="color:{ac}">{eyebrow}</div>
      <div class="sec-vbar" style="background:{ac}"></div>
      <h2 class="sec-title">{title}</h2>
      {sub}
    </div>
  </div>
</section>"""


# ── Schémas ───────────────────────────────────────────────────────────────────
#
# Boîtes en HTML, liens en SVG, positions calculées en Python.
#
# Le tout-SVG obligerait à découper le texte à la main : SVG n'a pas de retour à
# la ligne automatique, et un libellé un peu long déborderait de sa boîte sans
# rien dire. Le tout-HTML, lui, ne sait pas tracer une courbe entre deux boîtes.
# On garde donc chacun pour ce qu'il fait : le SVG dessine DERRIÈRE, en
# coordonnées relatives (viewBox 0-100), et les boîtes se placent en pourcentage
# au-dessus. Les deux restent alignés à toutes les tailles.

def _boite(label: str, sub: str, x: float, y: float, w: float,
           classe: str = "") -> str:
    """Une boîte centrée sur (x, y), exprimés en pourcentage du cadre."""
    detail = f'<div class="dg-sub">{_md(sub)}</div>' if sub else ""
    return (f'<div class="dg-box {classe}" style="left:{x}%;top:{y}%;width:{w}%">'
            f'<div class="dg-lbl">{_md(label)}</div>{detail}</div>')


def _champ(s: dict) -> tuple[str, str]:
    """L'ouverture commune à tous les schémas : titre puis cadre de dessin."""
    return (f"""
{_section_open(s)}
  <div class="s-bg-grid"></div>
  <div class="s-inner s-stack">
    <h2 class="s-title s-title-dark">{_e(s.get("title",""))}</h2>
    <div class="dg-field">""",
            """
    </div>
  </div>
</section>""")


def _slide_flow(s: dict, idx: int) -> str:
    """Un enchaînement d'étapes, reliées par des flèches."""
    ac = _accent(0)
    etapes = (s.get("steps") or [])[:6]
    if not etapes:
        return _slide_content(s, idx)
    vertical = str(s.get("orientation", "h")).startswith("v")
    n = len(etapes)
    boites, fleches = [], []
    for i, e in enumerate(etapes):
        label = e.get("label", "") if isinstance(e, dict) else str(e)
        sub = e.get("sub", "") if isinstance(e, dict) else ""
        if vertical:
            y = (i + 0.5) * 100 / n
            boites.append(_boite(label, sub, 50, y, 46))
            if i:
                haut = (i - 0.5) * 100 / n
                fleches.append(f'<path d="M50 {haut + 7} L50 {y - 7}" '
                               f'stroke="{ac}" stroke-width="0.5" marker-end="url(#fl)"/>')
        else:
            x = (i + 0.5) * 100 / n
            boites.append(_boite(label, sub, x, 50, 92 / n))
            if i:
                gauche = (i - 0.5) * 100 / n
                fleches.append(f'<path d="M{gauche + 46 / n} 50 L{x - 46 / n} 50" '
                               f'stroke="{ac}" stroke-width="0.5" marker-end="url(#fl)"/>')
    ouvre, ferme = _champ(s)
    return (ouvre + _svg(ac, "".join(fleches)) + "".join(boites) + ferme)


def _slide_tree(s: dict, idx: int) -> str:
    """Un organigramme : une racine, ses branches, leurs feuilles.

    Trois niveaux au plus. Au-delà, les boîtes deviennent illisibles à l'écran —
    mieux vaut deux diapositives qu'un arbre qu'on ne peut pas lire.
    """
    ac = _accent(0)
    racine = s.get("root") or {}
    if not racine:
        return _slide_content(s, idx)

    boites, liens = [], []
    niveaux = [[(racine, 50.0, 12.0)]]
    enfants = (racine.get("children") or [])[:5]
    if enfants:
        pas = 100.0 / len(enfants)
        niveaux.append([(e, (i + 0.5) * pas, 48.0) for i, e in enumerate(enfants)])
    # Chaque parent possède une BANDE ; ses feuilles se partagent cette bande et
    # rien d'autre. Une largeur fixe les faisait déborder sur la bande voisine
    # dès qu'un parent avait trois enfants — les boîtes se chevauchaient.
    bande = 100.0 / max(len(niveaux[1]), 1) if len(niveaux) > 1 else 100.0
    troisieme: list = []
    for noeud, x, y in (niveaux[1] if len(niveaux) > 1 else []):
        petits = (noeud.get("children") or [])[:3]
        if not petits:
            continue
        pas = bande / len(petits)
        base = x - bande / 2
        largeur_feuille = pas * 0.74
        troisieme += [(pe, base + (j + 0.5) * pas, 84.0, largeur_feuille)
                      for j, pe in enumerate(petits)]
    if troisieme:
        niveaux.append([(n, x, y) for n, x, y, _ in troisieme])

    largeurs = {0: 34.0, 1: bande * 0.84, 2: None}
    for profondeur, rang in enumerate(niveaux):
        for i, (noeud, x, y) in enumerate(rang):
            if profondeur >= 2:
                largeur = troisieme[i][3]
            else:
                largeur = largeurs[profondeur]
            boites.append(_boite(noeud.get("label", ""), noeud.get("sub", ""),
                                 x, y, largeur,
                                 "dg-racine" if profondeur == 0 else ""))
    # Les liens : une descente, un palier, une descente. Un trait droit en
    # diagonale se croiserait avec ses voisins dès trois branches.
    for depart, arrivees in ((niveaux[0][0], niveaux[1] if len(niveaux) > 1 else []),):
        for noeud, x, y in arrivees:
            liens.append(_lien(depart[1], depart[2] + 9, x, y - 9, ac))
    if len(niveaux) > 2:
        for noeud, x, y in niveaux[2]:
            parent = min(niveaux[1], key=lambda p: abs(p[1] - x))
            liens.append(_lien(parent[1], parent[2] + 9, x, y - 9, ac))
    ouvre, ferme = _champ(s)
    return ouvre + _svg(ac, "".join(liens)) + "".join(boites) + ferme


def _lien(x1: float, y1: float, x2: float, y2: float, couleur: str) -> str:
    milieu = (y1 + y2) / 2
    return (f'<path d="M{x1} {y1} L{x1} {milieu} L{x2} {milieu} L{x2} {y2}" '
            f'fill="none" stroke="{couleur}" stroke-width="0.4" opacity="0.55"/>')


def _slide_cycle(s: dict, idx: int) -> str:
    """Des étapes en cercle : une boucle, pas une ligne qui s'arrête."""
    import math
    ac = _accent(0)
    etapes = (s.get("steps") or [])[:6]
    if not etapes:
        return _slide_content(s, idx)
    n, r = len(etapes), 33.0
    boites = []
    # L'anneau est tracé d'un seul trait, DERRIÈRE, et les chevrons donnent le
    # sens. Des arcs calculés paire par paire passaient au travers des boîtes :
    # le champ n'est pas carré et `preserveAspectRatio="none"` déforme le cercle,
    # si bien qu'un arc ne rejoint jamais exactement les points visés.
    anneau = (f'<ellipse cx="50" cy="50" rx="{r * 0.92}" ry="{r}" fill="none" '
              f'stroke="{ac}" stroke-width="0.35" opacity="0.3"/>')
    chevrons = []
    for i, e in enumerate(etapes):
        angle = -math.pi / 2 + 2 * math.pi * i / n
        x, y = 50 + r * math.cos(angle) * 0.92, 50 + r * math.sin(angle)
        label = e.get("label", "") if isinstance(e, dict) else str(e)
        sub = e.get("sub", "") if isinstance(e, dict) else ""
        boites.append(_boite(label, sub, x, y, min(30, 150 / n)))
        milieu = angle + math.pi / n
        mx, my = 50 + r * math.cos(milieu) * 0.92, 50 + r * math.sin(milieu)
        degres = math.degrees(milieu) + 90
        chevrons.append(
            f'<path d="M-1.6 -1.4 L1.4 0 L-1.6 1.4" fill="none" stroke="{ac}" '
            f'stroke-width="0.5" stroke-linecap="round" stroke-linejoin="round" '
            f'transform="translate({mx} {my}) rotate({degres})"/>')
    arcs = [anneau] + chevrons
    centre = (f'<div class="dg-centre">{_md(s.get("center",""))}</div>'
              if s.get("center") else "")
    ouvre, ferme = _champ(s)
    return ouvre + _svg(ac, "".join(arcs)) + centre + "".join(boites) + ferme


def _slide_quadrant(s: dict, idx: int) -> str:
    """Deux axes, quatre cases : positionner des options les unes par rapport
    aux autres plutôt que les empiler en liste."""
    ac = _accent(0)
    items = (s.get("items") or [])[:10]
    points = "".join(
        f'<div class="dg-pt" style="left:{float(i.get("x", 0.5)) * 86 + 7:.1f}%;'
        f'top:{(1 - float(i.get("y", 0.5))) * 82 + 9:.1f}%">'
        f'<span></span>{_md(i.get("label",""))}</div>'
        for i in items if isinstance(i, dict))
    axes = (f'<div class="dg-axe dg-axe-x">{_e(s.get("x_label",""))}</div>'
            f'<div class="dg-axe dg-axe-y">{_e(s.get("y_label",""))}</div>'
            f'<div class="dg-croix"></div>')
    ouvre, ferme = _champ(s)
    return ouvre + axes + points + ferme


def _svg(couleur: str, contenu: str) -> str:
    """Le calque de liens, sous les boîtes, en coordonnées relatives."""
    return (f'<svg class="dg-svg" viewBox="0 0 100 100" preserveAspectRatio="none">'
            f'<defs><marker id="fl" viewBox="0 0 10 10" refX="8" refY="5" '
            f'markerWidth="4" markerHeight="4" orient="auto">'
            f'<path d="M0 0 L10 5 L0 10 z" fill="{couleur}"/></marker></defs>'
            f'{contenu}</svg>')


def _slide_code(s: dict, idx: int) -> str:
    """Un extrait de code, en grand, avec sa légende.

    Le type qui manquait le plus : sans lui, une présentation technique parle
    de code sans jamais en montrer.
    """
    ac = _accent(0)
    note = f'<p class="s-body" style="margin-top:26px">{_md(s.get("note",""))}</p>' if s.get("note") else ""
    return f"""
{_section_open(s)}
  <div class="s-bg-grid"></div>
  <div class="s-glow" style="background:radial-gradient(ellipse 55% 50% at 80% 20%,{ac}14,transparent);"></div>
  <div class="s-inner s-stack">
    <h2 class="s-title s-title-dark">{_e(s.get("title",""))}</h2>
    {_bloc_code(s.get("code", ""), s.get("lang", ""), s.get("caption", ""))}
    {note}
  </div>
</section>"""


def _slide_compare(s: dict, idx: int) -> str:
    """Deux panneaux face à face — l'avant et l'après, l'un et l'autre.

    `split` existait déjà mais n'accepte que des puces. Celui-ci prend du CODE
    des deux côtés, ce qui est la forme naturelle de « JavaScript contre
    TypeScript » ou de « avant / après refactor ».
    """
    ac = _accent(0)

    def panneau(d: dict, ton: str) -> str:
        if not d:
            return ""
        puces = "".join(f'<li>{_md(x)}</li>' for x in (d.get("bullets") or []))
        return f"""
      <div class="cmp-col cmp-{ton}">
        <div class="cmp-hdr">{_e(d.get("heading",""))}</div>
        {_bloc_code(d.get("code",""), d.get("lang",""))}
        {f'<ul class="bl-list cmp-list">{puces}</ul>' if puces else ""}
      </div>"""

    verdict = (f'<div class="cmp-verdict" style="border-color:{ac}55">{_md(s.get("verdict",""))}</div>'
               if s.get("verdict") else "")
    return f"""
{_section_open(s)}
  <div class="s-bg-grid"></div>
  <div class="s-inner s-stack">
    <h2 class="s-title s-title-dark">{_e(s.get("title",""))}</h2>
    <div class="cmp-grid">
      {panneau(s.get("left", {}), "avant")}
      {panneau(s.get("right", {}), "apres")}
    </div>
    {verdict}
  </div>
</section>"""


def _slide_punch(s: dict, idx: int) -> str:
    """UNE phrase, en grand, et rien d'autre.

    Remplace les inter-parties muettes : une diapositive qui ne porte qu'un
    numéro et un titre se lit comme un vide, alors qu'une affirmation nette
    tenue seule à l'écran est le moment le plus fort d'un exposé.
    """
    ac = _accent(0)
    src = f'<div class="pu-src">{_e(s.get("source",""))}</div>' if s.get("source") else ""
    eyebrow = f'<div class="eyebrow" style="color:{ac}">{_e(s.get("eyebrow",""))}</div>' if s.get("eyebrow") else ""
    return f"""
{_section_open(s)}
  <div class="s-deco-bar" style="background:{ac}"></div>
  <div class="s-bg-grid"></div>
  <div class="s-glow" style="background:radial-gradient(ellipse 70% 60% at 25% 55%,{ac}1e,transparent);"></div>
  <div class="s-inner s-title-layout">
    {eyebrow}
    <p class="pu-text">{_md(s.get("text", s.get("title","")))}</p>
    {src}
  </div>
</section>"""


_RENDERERS = {
    "flow":     _slide_flow,
    "tree":     _slide_tree,
    "cycle":    _slide_cycle,
    "quadrant": _slide_quadrant,
    "code":     _slide_code,
    "compare":  _slide_compare,
    "punch":    _slide_punch,
    "title":    _slide_title,
    "agenda":   _slide_agenda,
    "timeline": _slide_timeline,
    "content":  _slide_content,
    "section":  _slide_section,
    "split":    _slide_split,
    "split3":   _slide_split3,
    "stats":    _slide_stats,
    "table":    _slide_table,
    "cases":    _slide_cases,
    "quote":    _slide_quote,
    "closing":  _slide_closing,
}


# ── CSS — NOTE: single braces, this is NOT an f-string ───────────────────────
# _CSS is substituted as a value into _TEMPLATE.format(), so {{ would stay
# as {{ in the output (invalid CSS). Use plain single { and } here.

_CSS = """
/* fonts */
:root {
  --font:   'Inter', 'Helvetica Neue', system-ui, sans-serif;
  --font-d: 'Space Grotesk', 'Inter', system-ui, sans-serif;
  --font-c: 'Barlow Condensed', 'Space Grotesk', sans-serif;
}

/* reveal reset */
.reveal { font-family: var(--font); background: #0c0a08; }
.reveal h1, .reveal h2, .reveal h3 {
  font-family: var(--font-d);
  text-transform: none;
  letter-spacing: -0.02em;
  line-height: 1.15;
  margin: 0;
}
.reveal ul, .reveal ol { margin: 0; padding: 0; list-style: none; }
.reveal p { margin: 0; }
.reveal *::selection { background: #ffaf0033; }

/* theme layers */
/* Encres CHAUDES : un gris bleuté (#94a3b8) sous un accent ambre donne un
   contraste sale. Les neutres suivent la température de l'accent. */
.s-dark  { --s-text: #f7f3ec; --s-muted: #a29684; --s-title-c: #f7f3ec; }
.s-light { --s-text: #f7f3ec; --s-muted: #a29684; --s-title-c: #f7f3ec; }

/* Fix section height — in print-pdf mode Reveal.js sets sections to display:block with no height,
   breaking position:absolute on .s-inner. Forcing 720px (or the CSS var) fixes it in all modes. */
.reveal .slides section {
  height: var(--slide-height, 720px) !important;
  min-height: var(--slide-height, 720px) !important;
}
.print-pdf .reveal .slides section {
  height: 720px !important;
  min-height: 720px !important;
  position: relative !important;
  overflow: hidden !important;
}

/* slide layout */
.s-inner {
  position: absolute !important;
  inset: 0 !important;
  z-index: 2;
  display: flex !important;
  flex-direction: column !important;
  padding: 56px 84px !important;
  box-sizing: border-box !important;
  /* Reveal.js centre le texte de toute `section`. Les blocs en héritaient
     (eyebrow, h1) tandis que les conteneurs flex s'alignaient à gauche : QUATRE
     alignements différents sur la diapo de titre, par accident et non par
     intention. Une composition se cale sur un seul bord. */
  /* `stretch`, pas `flex-start` : caler l'alignement du TEXTE est le travail de
     `text-align`. Passer `align-items` à `flex-start` fait en plus rétrécir
     chaque bloc à la largeur de son contenu — le tableau n'occupait alors qu'un
     tiers de la diapo, et le vide à droite se lisait comme un oubli. */
  align-items: stretch !important;
  text-align: left !important;
}
.s-center {
  align-items: center !important;
  justify-content: center !important;
  text-align: center !important;
}
/* Empilé sur le MÊME bord gauche que la diapo de titre, centré verticalement.
   Un titre centré au-dessus de cartes dont le contenu est calé à gauche donne
   deux axes de lecture concurrents sur une seule diapo. */
.s-stack {
  align-items: stretch !important;
  justify-content: center !important;
  text-align: left !important;
}
.s-stack .s-title { align-self: flex-start; }

/* decorative circles on dark slides */
.s-dark::before {
  content: ''; position: absolute; width: 440px; height: 440px; border-radius: 50%;
  border: 1.5px solid rgba(255,255,255,0.035);
  top: -130px; right: -90px; pointer-events: none; z-index: 0;
}
.s-dark::after {
  content: ''; position: absolute; width: 240px; height: 240px; border-radius: 50%;
  border: 1.5px solid rgba(255,255,255,0.035);
  bottom: -70px; left: 140px; pointer-events: none; z-index: 0;
}

/* decorative */
.s-bg-grid {
  position: absolute; inset: 0; pointer-events: none; z-index: 0;
  background-image:
    linear-gradient(rgba(255,255,255,0.022) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255,255,255,0.022) 1px, transparent 1px);
  background-size: 48px 48px;
}
.s-glow { position: absolute; inset: 0; pointer-events: none; z-index: 1; }
.s-deco-bar {
  position: absolute; left: 0; top: 0; bottom: 0;
  width: 5px; z-index: 3;
}
.s-deco-right { left: auto; right: 0; }

/* title */
.s-title-layout { justify-content: center !important; }
.eyebrow {
  font-size: 0.68rem; font-weight: 700;
  letter-spacing: 0.14em; text-transform: uppercase;
  margin-bottom: 18px;
}
.s-main-title {
  /* Le dégradé blanc→gris délavait la fin de chaque titre et rendait les mots
     longs illisibles sur fond sombre. Une seule encre, et le contraste porte. */
  font-size: clamp(3.4rem, 7.5vw, 6.4rem); font-weight: 800;
  margin-bottom: 22px;
  color: #f7f3ec;
  max-width: 15ch; line-height: 0.98; letter-spacing: -0.035em;
}
.s-subtitle { font-size: 1.18rem; color: var(--s-muted); max-width: 46ch; line-height: 1.6; margin-bottom: 30px; }
.cl-sub { color: #94a3b8; }
.s-chips { display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 8px; }
.chip {
  font-size: 0.72rem; padding: 4px 14px; border-radius: 99px;
  background: rgba(255,255,255,0.07); border: 1px solid rgba(255,255,255,0.12); color: #94a3b8;
}
.s-source { font-size: 0.62rem; color: #64748b; margin-top: 16px; }
.s-source-global { font-size: 0.7rem; color: var(--s-muted); margin-bottom: 16px; }
.cta-pill {
  margin-top: 22px; display: inline-block;
  padding: 9px 26px; border-radius: 99px;
  border: 1.5px solid; font-size: 0.88rem; font-weight: 600;
}

/* slide header */
.s-hdr { display: flex; align-items: center; gap: 12px; margin-bottom: 32px; flex-shrink: 0; }
.s-stripe { width: 4px; height: 30px; border-radius: 2px; flex-shrink: 0; }
.s-icon { font-size: 2.8rem; line-height: 1; }
/* background image (title slides) */
.s-bg-image {
  position: absolute; inset: 0; z-index: 0;
  background-size: cover; background-position: center;
}
.s-bg-overlay {
  position: absolute; inset: 0; z-index: 1;
  background: linear-gradient(120deg, rgba(13,19,32,0.95) 50%, rgba(13,19,32,0.55) 100%);
}
/* right image panel (content slides) */
.s-img-panel {
  position: absolute; right: 0; top: 0; bottom: 0; width: 38%;
  background-size: cover; background-position: center; z-index: 0;
}
.s-img-panel::after {
  content: ''; position: absolute; inset: 0; z-index: 1;
  background: linear-gradient(90deg, #0d1320 0%, rgba(13,19,32,0.15) 100%);
}
.s-narrow { padding-right: 42% !important; }
.s-has-deco { padding-right: 360px !important; }
.s-deco-panel {
  position: absolute; right: 0; top: 0; bottom: 0; width: 440px;
  z-index: 0; pointer-events: none;
}
.s-title { font-size: clamp(2rem, 4.2vw, 3.2rem); font-weight: 800; font-family: var(--font-d);
           color: var(--s-title-c); letter-spacing: -0.03em; line-height: 1.05; }
.s-title-dark { color: var(--s-title-c) !important; -webkit-text-fill-color: var(--s-title-c) !important; margin-bottom: 46px; }
.s-title-center { margin-bottom: 28px; }

/* body / bullets */
.s-cbody { flex: 1; display: flex !important; flex-direction: column; justify-content: center; gap: 20px; overflow: hidden; min-height: 0; }
.s-body { font-size: 1.05rem; line-height: 1.78; color: var(--s-muted); max-width: 880px; margin-bottom: 4px; }
.bl-list { display: flex; flex-direction: column; gap: 9px; }
.bl-list li {
  display: flex; align-items: flex-start; gap: 14px;
  font-size: 0.96rem; line-height: 1.62; color: var(--s-text);
  padding: 12px 18px;
  background: rgba(255,255,255,0.045);
  border-radius: 10px;
  border: 1px solid rgba(255,255,255,0.07);
  border-left-width: 3px;
}
.bl-dot { width: 0; height: 0; display: none; }
.bl-list.bl-few li  { font-size: 0.96rem; padding: 12px 18px; }
.bl-list.bl-med li  { font-size: 0.90rem; padding: 10px 16px; }
.bl-list.bl-many li { font-size: 0.82rem; padding: 8px 14px; line-height: 1.5; }
.col-hd { font-size: 0.78rem; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase; margin-bottom: 10px; }

/* agenda grid */
.agc-grid { flex: 1; display: grid !important; gap: 20px; align-content: center; min-height: 0; width: 100%; }
.agc-cols-3 { grid-template-columns: repeat(3, 1fr) !important; }
.agc-cols-2 { grid-template-columns: repeat(2, 1fr) !important; }
.agc-cols-1 { grid-template-columns: 1fr !important; }
.agc-card {
  background: rgba(255,255,255,0.05);
  border: 1px solid rgba(255,255,255,0.10);
  border-radius: 10px; padding: 14px 18px;
  display: flex; flex-direction: column;
}
.agc-num { font-size: clamp(2.2rem, 4vw, 3.2rem); font-weight: 800; font-family: var(--font-c); margin-bottom: 10px; line-height: 1; }
.agc-label { font-size: 0.95rem; font-weight: 700; color: #f0f4ff; margin-bottom: 6px; line-height: 1.3; }
.agc-sub { font-size: 0.78rem; color: #94a3b8; line-height: 1.5; margin-top: auto; padding-top: 8px; }

/* split (2 col) */
.split-grid {
  flex: 1; display: grid !important;
  grid-template-columns: 1fr 1px 1fr !important;
  gap: 0 32px; align-items: start; min-height: 0;
}
.split-col { display: flex; flex-direction: column; gap: 12px; }
.split-div { background: rgba(255,255,255,0.07); align-self: stretch; }

/* split3 (3 col) */
.split3-grid {
  flex: 1; display: grid !important;
  grid-template-columns: 1fr 1fr 1fr !important;
  gap: 16px; align-items: start; min-height: 0;
}
.split3-col {
  display: flex; flex-direction: column; gap: 10px;
  background: rgba(255,255,255,0.04); border-radius: 10px;
  border: 1px solid rgba(255,255,255,0.07); overflow: hidden;
}
.split3-hdr {
  padding: 14px 18px; font-size: 0.82rem; font-weight: 700;
  text-align: center; letter-spacing: 0.05em; text-transform: uppercase;
}
.split3-body { padding: 14px 18px; flex: 1; display: flex; flex-direction: column; gap: 8px; }

/* stats grid */
.st-grid { display: grid !important; gap: 20px; width: 100%; max-width: 980px; }
.st-cols-3 { grid-template-columns: repeat(3, 1fr) !important; }
.st-cols-2 { grid-template-columns: repeat(2, 1fr) !important; }
.st-cols-1 { grid-template-columns: 1fr !important; }
.st-card {
  background: linear-gradient(180deg, rgba(255,175,0,0.06), rgba(255,175,0,0.015));
  border: 1px solid rgba(255,175,0,0.16);
  border-radius: 14px; padding: 40px 32px 34px; min-height: 200px;
  display: flex; flex-direction: column; align-items: flex-start; justify-content: center; gap: 10px;
  text-align: left;
}
.st-icon { font-size: 1.6rem; }
/* `--font-c` est un condensé très gras : à côté d'Inter il ne lit pas comme la
   même famille, et sa virgule décimale se colle au chiffre suivant. */
.st-val { font-size: clamp(3.4rem, 7vw, 6rem); font-weight: 700; font-family: var(--font-d);
          line-height: 1; letter-spacing: -0.045em; font-variant-numeric: tabular-nums; }
.st-lbl { font-size: 0.82rem; font-weight: 600; color: #e2e8f0; text-align: center; line-height: 1.4; }
.st-src { font-size: 0.65rem; color: #64748b; margin-top: 2px; font-style: italic; }

/* comparison table */
.tbl-wrap { flex: 1; display: flex !important; flex-direction: column;
            justify-content: flex-start; margin-top: 48px; }
.tbl-head {
  display: grid !important; gap: 4px; margin-bottom: 4px;
  grid-template-columns: 160px repeat(2, 1fr);
}
.tbl-hdr { padding: 10px 18px 12px; font-size: 0.78rem; font-weight: 700; text-align: left;
           text-transform: uppercase; letter-spacing: 0.12em;
           border-bottom: 2px solid rgba(255,175,0,0.5); }
.tbl-row {
  display: grid !important; gap: 4px;
  grid-template-columns: 160px repeat(2, 1fr);
  border-bottom: 1px solid rgba(255,255,255,0.05);
  padding: 4px 0;
}
.tbl-row-alt { background: rgba(255,255,255,0.025); border-radius: 4px; }
.tbl-dim-hdr { border-bottom: 2px solid rgba(255,175,0,0.5); }
.tbl-dim { font-size: 1rem; font-weight: 700; padding: 14px 8px; display: flex; align-items: center; }
.tbl-val { font-size: 1rem; color: var(--s-text); padding: 14px 18px; display: flex; align-items: center; opacity: 0.9; font-variant-numeric: tabular-nums; }

/* schémas : flow · tree · cycle · quadrant */
.dg-field { position: relative; flex: 1; margin-top: 30px; min-height: 0; }
.dg-svg { position: absolute; inset: 0; width: 100%; height: 100%; z-index: 0; }
.dg-box {
  position: absolute; transform: translate(-50%, -50%); z-index: 2;
  background: rgba(255,175,0,0.055); border: 1px solid rgba(255,175,0,0.22);
  border-radius: 12px; padding: 14px 16px; text-align: center;
  display: flex; flex-direction: column; gap: 4px; justify-content: center;
}
.dg-racine { background: rgba(255,175,0,0.13); border-color: rgba(255,175,0,0.5); }
.dg-lbl { font-size: clamp(0.82rem, 1.35vw, 1.06rem); font-weight: 600; color: var(--s-text); line-height: 1.3; }
.dg-sub { font-size: clamp(0.66rem, 1vw, 0.8rem); color: var(--s-muted); line-height: 1.4; }
.dg-centre {
  position: absolute; left: 50%; top: 50%; transform: translate(-50%, -50%);
  z-index: 1; max-width: 26%; text-align: center;
  font-size: clamp(0.9rem, 1.7vw, 1.3rem); font-weight: 700;
  font-family: var(--font-d); color: #ffaf00; line-height: 1.25;
}
/* quadrant */
.dg-croix {
  position: absolute; inset: 9% 7%; z-index: 0;
  border-left: 1px solid rgba(255,175,0,0.28);
  border-bottom: 1px solid rgba(255,175,0,0.28);
  background:
    linear-gradient(rgba(255,175,0,0.22), rgba(255,175,0,0.22)) no-repeat 50% 0/1px 100%,
    linear-gradient(rgba(255,175,0,0.22), rgba(255,175,0,0.22)) no-repeat 0 50%/100% 1px;
}
.dg-axe {
  position: absolute; z-index: 1; font-size: 0.7rem; font-weight: 700;
  letter-spacing: 0.12em; text-transform: uppercase; color: var(--s-muted);
}
.dg-axe-x { bottom: 0; left: 50%; transform: translateX(-50%); }
.dg-axe-y { left: 0; top: 50%; transform: rotate(-90deg) translateX(50%); transform-origin: left center; }
.dg-pt {
  position: absolute; z-index: 2; transform: translate(-50%, -50%);
  display: flex; align-items: center; gap: 8px; white-space: nowrap;
  font-size: clamp(0.74rem, 1.15vw, 0.94rem); color: var(--s-text);
  background: rgba(12,10,8,0.82); padding: 5px 12px 5px 8px; border-radius: 99px;
  border: 1px solid rgba(255,175,0,0.2);
}
.dg-pt span { width: 8px; height: 8px; border-radius: 50%; background: #ffaf00; flex: none; }

/* code, compare, punch */
.code-wrap { position: relative; margin-top: 30px; }
.code-lang {
  position: absolute; top: -11px; left: 22px; z-index: 2;
  font-size: 0.62rem; font-weight: 700; letter-spacing: 0.14em; text-transform: uppercase;
  color: #1a1206; background: #ffaf00; padding: 3px 12px; border-radius: 99px;
}
.code-pre {
  margin: 0; padding: 30px 30px 28px; border-radius: 14px; overflow: auto;
  background: rgba(255,175,0,0.04); border: 1px solid rgba(255,175,0,0.16);
  font-family: 'JetBrains Mono', ui-monospace, 'SF Mono', Menlo, monospace;
  font-size: clamp(0.82rem, 1.35vw, 1.12rem); line-height: 1.7;
  color: #efe7da; text-align: left; white-space: pre; tab-size: 2;
}
.code-pre code { font-family: inherit; background: none; padding: 0; }
/* Quatre teintes seulement : un extrait arc-en-ciel se lit moins bien qu'un
   extrait sobre, et la couleur doit servir la STRUCTURE, pas la décorer. */
.c-kw { color: #ffaf00; font-weight: 600; }
.c-st { color: #b8d98a; }
.c-cm { color: #7a6f5e; font-style: italic; }
.c-ty { color: #7fd1e0; }
.c-nb { color: #e0a87f; }
.code-cap { font-size: 0.78rem; color: var(--s-muted); margin-top: 12px; }

.cmp-grid {
  flex: 1; display: grid !important; grid-template-columns: 1fr 1fr;
  gap: 24px; align-content: center; min-height: 0; margin-top: 34px;
}
.cmp-col {
  border-radius: 14px; padding: 26px 26px 24px; min-height: 0;
  background: rgba(255,255,255,0.022); border: 1px solid rgba(255,255,255,0.08);
  display: flex; flex-direction: column;
}
/* La distinction entre les deux colonnes passe par l'INTENSITÉ, pas par deux
   couleurs opposées : un rouge contre un vert impose un jugement que le
   contenu ne porte pas toujours. */
.cmp-avant { border-color: rgba(255,255,255,0.10); }
.cmp-apres { border-color: rgba(255,175,0,0.30); background: rgba(255,175,0,0.035); }
.cmp-hdr {
  font-size: 0.72rem; font-weight: 700; letter-spacing: 0.14em; text-transform: uppercase;
  color: var(--s-muted); margin-bottom: 6px;
}
.cmp-apres .cmp-hdr { color: #ffaf00; }
.cmp-col .code-wrap { margin-top: 18px; }
.cmp-col .code-pre { padding: 20px 20px 18px; font-size: clamp(0.72rem, 1.05vw, 0.92rem); }
.cmp-list { margin-top: 16px; }
.cmp-verdict {
  margin-top: 24px; padding: 16px 22px; border-left: 3px solid;
  background: rgba(255,175,0,0.05); border-radius: 0 10px 10px 0;
  font-size: 1.02rem; color: var(--s-text);
}

.pu-text {
  font-size: clamp(2.4rem, 5.2vw, 4.2rem); font-weight: 700; font-family: var(--font-d);
  line-height: 1.08; letter-spacing: -0.03em; color: #f7f3ec; max-width: 20ch;
}
.pu-src { font-size: 0.8rem; color: var(--s-muted); margin-top: 30px; }

/* cases grid */
.cs-grid {
  flex: 1; display: grid !important;
  gap: 20px; align-content: center; min-height: 0;
}
.cs-cols-1 { grid-template-columns: 1fr !important; }
.cs-cols-2 { grid-template-columns: repeat(2, 1fr) !important; }
.cs-cols-3 { grid-template-columns: repeat(3, 1fr) !important; }
.cs-card {
  border-radius: 10px; overflow: hidden;
  border: 1px solid rgba(255,255,255,0.10);
  display: flex; flex-direction: column;
}
.cs-hdr {
  padding: 12px 18px; display: flex;
  justify-content: space-between; align-items: center;
  font-size: 0.9rem; font-weight: 700;
}
.cs-arch { font-size: 0.72rem; font-weight: 600; opacity: 0.9; }
.cs-body { padding: 16px 18px; background: rgba(255,255,255,0.04); flex: 1; display: flex; flex-direction: column; }
.cs-body p { font-size: 0.84rem; color: #cbd5e1; line-height: 1.6; margin-bottom: 10px; }
.cs-lesson { font-size: 0.78rem; font-style: italic; font-weight: 600; margin-top: auto; padding-top: 8px; border-top: 1px solid rgba(255,255,255,0.10); }

/* quote */
.q-mark { font-size: 5.5rem; line-height: 0.6; font-family: Georgia, serif; margin-bottom: 16px; }
.q-text {
  font-size: clamp(1rem, 2.3vw, 1.5rem); font-style: italic;
  line-height: 1.55; max-width: 800px; margin-bottom: 20px; color: #f0f4ff;
}
.q-author { font-size: 0.95rem; font-weight: 600; }
.q-role { font-size: 0.72rem; color: #94a3b8; margin-top: 4px; }

/* section break (EPF-style: giant number left, title right) */
.sec-layout {
  flex-direction: row !important;
  padding: 0 !important;
  align-items: stretch !important;
}
.sec-left {
  width: 42%; display: flex; align-items: center; justify-content: center;
  background: rgba(0,0,0,0.12); flex-shrink: 0; position: relative; overflow: hidden;
}
.sec-left::before, .sec-left::after { display: none; }
.sec-num-display {
  font-size: clamp(11rem, 20vw, 17rem); font-weight: 900;
  font-family: var(--font-c); color: rgba(255,255,255,0.20);
  line-height: 1; user-select: none; letter-spacing: -0.04em;
}
.sec-right {
  flex: 1; display: flex; flex-direction: column;
  justify-content: center; padding: 60px 68px;
}
.sec-vbar { width: 4px; height: 60px; border-radius: 2px; margin: 18px 0 24px; }
.sec-title {
  font-size: clamp(2rem, 4.2vw, 3.5rem); font-weight: 800; line-height: 1.15; max-width: 520px;
  background: linear-gradient(135deg, #f0f4ff 30%, #94a3b8 100%);
  -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text;
}
.sec-sub { font-size: 0.95rem; color: #64748b; margin-top: 16px; line-height: 1.65; max-width: 480px; }

/* timeline (EPF-style horizontal agenda) */
.tl-wrap { flex: 1; display: flex !important; flex-direction: column; justify-content: center; min-height: 0; }
.tl-track {
  position: relative;
  display: flex !important;
  justify-content: space-around;
  align-items: flex-start;
  padding-top: 36px;
}
.tl-line {
  position: absolute;
  top: 64px;
  left: 8%; right: 8%;
  height: 2px;
  background: linear-gradient(90deg, transparent, rgba(255,255,255,0.15) 20%, rgba(255,255,255,0.15) 80%, transparent);
}
.tl-step {
  display: flex; flex-direction: column; align-items: center;
  gap: 18px; flex: 1; position: relative; z-index: 1; padding: 0 8px;
}
.tl-dot {
  width: 56px; height: 56px; border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  font-family: var(--font-c); font-size: 1.35rem; font-weight: 900;
  color: #fff; flex-shrink: 0;
  box-shadow: 0 4px 20px rgba(0,0,0,0.18);
}
.tl-content { text-align: center; }
.tl-label { font-size: 0.88rem; font-weight: 700; color: #f0f4ff; line-height: 1.3; margin-bottom: 6px; }
.tl-sub { font-size: 0.73rem; color: #94a3b8; line-height: 1.45; }
.tl-duration {
  font-size: 0.66rem; font-weight: 700; letter-spacing: 0.09em;
  text-transform: uppercase; color: #94a3b8; margin-top: 8px;
}

/* controls */
.reveal .controls { color: #7c3aed; }
.reveal .progress { background: rgba(255,255,255,0.08); }
.reveal .progress span { background: #7c3aed; }
.reveal .slide-number { font-size: 0.62rem; color: #64748b; background: transparent; }

/* export bar */
#exp-bar {
  position: fixed; top: 12px; right: 12px;
  z-index: 9999; display: flex; gap: 8px;
}
.exp-btn {
  /* Bleu nuit sur une palette ambre : la barre d'outils appartenait à un autre
     thème que les diapos qu'elle surplombe. */
  background: rgba(20,16,12,0.82); backdrop-filter: blur(10px);
  border: 1px solid rgba(255,175,0,0.18); border-radius: 7px;
  color: #a29684; cursor: pointer;
  font-family: var(--font); font-size: 0.7rem;
  padding: 5px 12px; transition: color .15s, border-color .15s;
  text-decoration: none; display: inline-flex; align-items: center;
}
.exp-btn:hover { color: #f7f3ec; border-color: rgba(255,175,0,0.55); }
.exp-btn[disabled], .exp-btn.disabled { opacity: 0.35; pointer-events: none; }
@media print {
  #exp-bar { display: none !important; }
  * { -webkit-print-color-adjust: exact !important; print-color-adjust: exact !important; }
}
"""

# ── Full HTML template ────────────────────────────────────────────────────────
# NOTE: {{ and }} in _TEMPLATE are f-string escapes → become { and } in output
# (used for the Reveal.initialize JS block)

_TEMPLATE = """\
<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>{title}</title>
  <link rel="preconnect" href="https://fonts.googleapis.com"/>
  <link href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@700;800;900&family=JetBrains+Mono:wght@400;500;600&family=Inter:wght@300;400;500;600;700;800&family=Space+Grotesk:wght@500;600;700;800&display=swap" rel="stylesheet"/>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/reveal.js@5/dist/reset.css"/>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/reveal.js@5/dist/reveal.css"/>
  <style>
{css}
  </style>
</head>
<body>

<div id="exp-bar">
  <a class="exp-btn" {pdf_link}>&#11015; PDF</a>
  <a class="exp-btn" {pptx_link}>&#11015; PPTX</a>
  <button class="exp-btn" onclick="document.documentElement.requestFullscreen()">&#9633; Plein &#233;cran</button>
</div>

<div class="reveal">
  <div class="slides">
{slides}
  </div>
</div>

<script src="https://cdn.jsdelivr.net/npm/reveal.js@5/dist/reveal.js"></script>
<script>
  Reveal.initialize({{
    hash: true,
    transition: 'slide',
    transitionSpeed: 'fast',
    backgroundTransition: 'fade',
    controls: true,
    controlsLayout: 'bottom-right',
    progress: true,
    slideNumber: 'c/t',
    showSlideNumber: 'all',
    center: false,
    width: 1280,
    height: 720,
    margin: 0.04,
    minScale: 0.1,
    maxScale: 3.0,
  }});
  if (location.search.indexOf('print-pdf') !== -1) {{
    Reveal.addEventListener('ready', function() {{
      setTimeout(window.print, 1800);
    }});
  }}
</script>
</body>
</html>
"""


_FALLBACK_PDF  = "class=\"exp-btn disabled\" onclick=\"return false\""
_FALLBACK_PPTX = "class=\"exp-btn disabled\" onclick=\"return false\""


def render_html(title: str, slides: list[dict],
                theme: dict | None = None,
                pdf_link: str = _FALLBACK_PDF,
                pptx_link: str = _FALLBACK_PPTX) -> str:
    global _ACCENTS, _DARK_BG, _SECTION_BG, _QUOTE_BG
    _prev = (_ACCENTS, _DARK_BG, _SECTION_BG, _QUOTE_BG)
    if theme:
        if theme.get("accents"):
            _ACCENTS = theme["accents"]
        if theme.get("bg"):
            _DARK_BG = _SECTION_BG = _QUOTE_BG = theme["bg"]
    try:
        parts = [
            _RENDERERS.get(s.get("type", "content"), _slide_content)(s, i)
            for i, s in enumerate(slides)
        ]
        theme_css = (
            f"\n/* theme overrides */\n"
            f".reveal {{ background: {_DARK_BG}; }}\n"
            f".reveal .controls {{ color: {_accent(0)}; }}\n"
            f".reveal .progress span {{ background: {_accent(0)}; }}\n"
        )
        return _TEMPLATE.format(
            title=_e(title), css=_CSS + theme_css,
            slides="\n".join(parts),
            pdf_link=pdf_link, pptx_link=pptx_link,
        )
    finally:
        _ACCENTS, _DARK_BG, _SECTION_BG, _QUOTE_BG = _prev
