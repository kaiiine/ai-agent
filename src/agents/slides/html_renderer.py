"""HTML/Reveal.js renderer — professional alternating dark/light theme."""
from __future__ import annotations

import html as _html
import re as _re
from datetime import date
from typing import Any


_ACCENTS = ["#7c3aed", "#06b6d4", "#f59e0b"]

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

_DARK_BG    = "#0f172a"
_SECTION_BG = "#0d1b2a"
_QUOTE_BG   = "#091422"


def _section_open(slide: dict, extra_class: str = "") -> str:
    return f'<section class="s-dark {extra_class}" style="background-color:{_DARK_BG}">'


# ── Slide renderers ───────────────────────────────────────────────────────────

def _slide_title(s: dict, idx: int) -> str:
    ac = _accent(0)
    subtitle = f'<p class="s-subtitle">{_e(s.get("subtitle",""))}</p>' if s.get("subtitle") else ""
    meta = [x for x in [s.get("author"), s.get("date", str(date.today().strftime("%B %Y")))] if x]
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


def _slide_agenda(s: dict, idx: int) -> str:
    hdr_ac = _accent(idx)
    items = s.get("items", [])
    cards = ""
    for i, item in enumerate(items[:6]):
        ac = _accent(i)
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
    cols = min(3, max(len(items), 1))
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
    deco_panel = f'<div class="s-deco-panel" style="background:linear-gradient(135deg,{ac}28 0%,{ac}08 60%,transparent 100%)"></div>'
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
      {_col(s.get("left",  {}), _accent(idx))}
      <div class="split-div"></div>
      {_col(s.get("right", {}), _accent(idx + 1))}
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
        ac = _accent(i)
        src  = f'<div class="st-src">{_e(st.get("source",""))}</div>' if st.get("source") else ""
        cards += f"""
      <div class="st-card" style="border-top:3px solid {ac}">
        <div class="st-val" style="color:{ac}">{_e(st.get("value",""))}</div>
        <div class="st-lbl">{_e(st.get("label",""))}</div>
        {src}
      </div>"""
    n = min(len(stats), 6)
    cols = 2 if n <= 4 else 3
    grid_max = "900px" if n <= 4 else "980px"
    src_global = f'<p class="s-source-global">{_e(s.get("source",""))}</p>' if s.get("source") else ""
    return f"""
{_section_open(s)}
  <div class="s-inner s-center">
    <h2 class="s-title s-title-dark s-title-center">{_e(s.get("title",""))}</h2>
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
    grid_cols = f"160px repeat({ncols}, 1fr)"

    hdr_cells = "".join(
        f'<div class="tbl-hdr" style="background:{_accent(i)};color:{"#0d1320" if i==1 else "#fff"}">'
        f'{_e(c.get("label","") if isinstance(c,dict) else c)}</div>'
        for i, c in enumerate(cols)
    )
    rows_html = ""
    for r, row in enumerate(rows):
        val_cells = "".join(
            f'<div class="tbl-val">{_e(v)}</div>'
            for v in row.get("values", [])[:ncols]
        )
        alt_class = "tbl-row-alt" if r % 2 == 1 else ""
        rows_html += f"""
      <div class="tbl-row {alt_class}" style="grid-template-columns:{grid_cols}">
        <div class="tbl-dim" style="color:{ac}">{_e(row.get("dim",""))}</div>
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
    cards = ""
    for i, c in enumerate(cases[:4]):
        card_ac    = c.get("color") or _accent(i)
        text_color = "#0d1320" if (i % 2 == 0) else "#ffffff"
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
    <div class="cs-grid">{cards}
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
        ac = step.get("color") or _accent(i)
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


_RENDERERS = {
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
.reveal { font-family: var(--font); background: #0f0c24; }
.reveal h1, .reveal h2, .reveal h3 {
  font-family: var(--font-d);
  text-transform: none;
  letter-spacing: -0.02em;
  line-height: 1.15;
  margin: 0;
}
.reveal ul, .reveal ol { margin: 0; padding: 0; list-style: none; }
.reveal p { margin: 0; }
.reveal *::selection { background: #7c3aed40; }

/* theme layers */
.s-dark  { --s-text: #f0f4ff; --s-muted: #94a3b8; --s-title-c: #f0f4ff; }
.s-light { --s-text: #f0f4ff; --s-muted: #94a3b8; --s-title-c: #f0f4ff; }

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
  padding: 48px 68px !important;
  box-sizing: border-box !important;
}
.s-center {
  align-items: center !important;
  justify-content: center !important;
  text-align: center !important;
}

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
  font-size: clamp(3rem, 6.5vw, 5.5rem); font-weight: 800;
  margin-bottom: 20px;
  background: linear-gradient(135deg, #f0f4ff 30%, #94a3b8 100%);
  -webkit-background-clip: text; -webkit-text-fill-color: transparent;
  background-clip: text; max-width: 900px; line-height: 1.05;
}
.s-subtitle { font-size: 1rem; color: var(--s-muted); max-width: 640px; line-height: 1.65; margin-bottom: 24px; }
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
  position: absolute; right: 0; top: 0; bottom: 0; width: 320px;
  z-index: 0; pointer-events: none;
}
.s-title { font-size: clamp(1.7rem, 3.4vw, 2.5rem); font-weight: 800; font-family: var(--font-d); color: var(--s-title-c); }
.s-title-dark { color: var(--s-title-c) !important; -webkit-text-fill-color: var(--s-title-c) !important; margin-bottom: 28px; }
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
.agc-grid { flex: 1; display: grid !important; gap: 14px; align-content: center; min-height: 0; }
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
.st-grid { display: grid !important; gap: 14px; width: 100%; max-width: 980px; }
.st-cols-3 { grid-template-columns: repeat(3, 1fr) !important; }
.st-cols-2 { grid-template-columns: repeat(2, 1fr) !important; }
.st-cols-1 { grid-template-columns: 1fr !important; }
.st-card {
  background: rgba(255,255,255,0.05);
  border: 1px solid rgba(255,255,255,0.10);
  border-radius: 12px; padding: 26px 20px 20px;
  display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 8px;
}
.st-icon { font-size: 1.6rem; }
.st-val { font-size: clamp(2.8rem, 5.5vw, 4.8rem); font-weight: 900; font-family: var(--font-c); line-height: 1; letter-spacing: -0.02em; }
.st-lbl { font-size: 0.82rem; font-weight: 600; color: #e2e8f0; text-align: center; line-height: 1.4; }
.st-src { font-size: 0.65rem; color: #64748b; margin-top: 2px; font-style: italic; }

/* comparison table */
.tbl-wrap { flex: 1; display: flex !important; flex-direction: column; }
.tbl-head {
  display: grid !important; gap: 4px; margin-bottom: 4px;
  grid-template-columns: 160px repeat(2, 1fr);
}
.tbl-hdr { padding: 8px 14px; border-radius: 6px; font-size: 0.84rem; font-weight: 700; text-align: center; }
.tbl-row {
  display: grid !important; gap: 4px;
  grid-template-columns: 160px repeat(2, 1fr);
  border-bottom: 1px solid rgba(255,255,255,0.05);
  padding: 4px 0;
}
.tbl-row-alt { background: rgba(255,255,255,0.025); border-radius: 4px; }
.tbl-dim-hdr { }
.tbl-dim { font-size: 0.8rem; font-weight: 700; padding: 8px; display: flex; align-items: center; }
.tbl-val { font-size: 0.8rem; color: var(--s-text); padding: 8px 12px; display: flex; align-items: center; opacity: 0.88; }

/* cases grid */
.cs-grid {
  flex: 1; display: grid !important;
  grid-template-columns: 1fr 1fr !important;
  gap: 14px; align-content: center; min-height: 0;
}
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
  background: rgba(13,19,32,0.88); backdrop-filter: blur(8px);
  border: 1px solid rgba(255,255,255,0.1); border-radius: 7px;
  color: #94a3b8; cursor: pointer;
  font-family: var(--font); font-size: 0.7rem;
  padding: 5px 12px; transition: color .15s, border-color .15s;
  text-decoration: none; display: inline-flex; align-items: center;
}
.exp-btn:hover { color: #f0f4ff; border-color: #4a90d9; }
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
  <link href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@700;800;900&family=Inter:wght@300;400;500;600;700;800&family=Space+Grotesk:wght@500;600;700;800&display=swap" rel="stylesheet"/>
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
