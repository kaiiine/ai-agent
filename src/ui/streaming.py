import re
import subprocess
import threading
from pathlib import Path
from time import perf_counter

from langchain_core.messages import AIMessageChunk, AIMessage, ToolMessage
from rich.live import Live
from rich.rule import Rule
from rich.text import Text
from rich.panel import Panel
from rich.pretty import Pretty
from rich.console import Console
from prompt_toolkit import PromptSession
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.styles import Style
from prompt_toolkit.key_binding import KeyBindings


from .config import fmt_ms, SessionConfig
from .language import detect_lang, enforce_lang_output
from .panels import live_panel_initial, tool_call_panel, command_panel, plan_panel, compile_panel, ACCENT
from .render import update_live_markdown, finalize_live
from .commands import debug_state
from .attachments import AttachmentStore, open_file_picker, get_clipboard_image, build_message_with_attachments
from .completer import SlashCompleter

console = Console()
_attachments = AttachmentStore()

_DEBOUNCE = 0.03
_REFRESH_RATE = 20
_THINKING_WAIT = 0.4


def _make_thinking_loop(stop_event: threading.Event, live: "Live",
                        compile_mode: threading.Event | None = None):
    """Retourne une fonction de loop d'animation pour un thread daemon.
    Si compile_mode est set, affiche le panel de compilation plutôt que thinking."""
    def _loop():
        i = 0
        while not stop_event.is_set():
            try:
                if compile_mode and compile_mode.is_set():
                    live.update(compile_panel(i % 4))
                else:
                    live.update(live_panel_initial(i % 4))
            except Exception:
                pass
            i += 1
            stop_event.wait(_THINKING_WAIT)
    return _loop

_pt_style = Style.from_dict({
    "axon":       "bold ansiyellow",
    "sep":        "ansiyellow",
    # Plan mode badge in the prompt
    "plan-badge": "bold bg:#1a0d00 fg:#ffaf00",
    # Completion dropdown — dark, minimal, orange accent on selection
    "completion-menu":                         "bg:#1a1a1a #606060",
    "completion-menu.completion":              "bg:#1a1a1a #606060",
    "completion-menu.completion.current":      "bg:#242424 bold fg:#ffaf00",
    "completion-menu.meta.completion":         "bg:#141414 #404040",
    "completion-menu.meta.completion.current": "bg:#1e1e1e #606060",
    "scrollbar.background":                    "bg:#1a1a1a",
    "scrollbar.button":                        "bg:#404040",
})


def _make_keybindings() -> KeyBindings:
    kb = KeyBindings()

    @kb.add("c-o")
    def _kb_attach(event):
        event.current_buffer.text = "/attach"
        event.current_buffer.validate_and_handle()

    @kb.add("c-p")
    def _kb_paste(event):
        from .attachments import get_clipboard_image
        img = get_clipboard_image()
        if img:
            _attachments.add_clipboard_image(img)
        event.app.invalidate()

    @kb.add("c-t")
    def _kb_plan(event):
        from .plan_mode import toggle
        toggle()
        event.app.invalidate()

    @kb.add("c-d")
    def _kb_detach(event):
        _attachments.pop_all()
        event.app.invalidate()

    return kb


def _prompt_tokens():
    """Dynamic prompt: separator line + indicator, using raw ANSI codes to match Rich exactly."""
    import shutil
    from prompt_toolkit.formatted_text import ANSI
    from .plan_mode import is_active as _plan_active

    try:
        width = shutil.get_terminal_size((120, 24)).columns
    except Exception:
        width = 120

    DIM = "\033[2m\033[38;5;214m"  # dim color(214) — exactly what Rich emits
    RST = "\033[0m"

    items: list[str] = []
    if _plan_active():
        items.append("◆ PLAN")
    for a in _attachments.items:
        icon = "📷" if a.is_image else "📎"
        items.append(f"{icon} {a.name}  [{a.size_hint}]")

    if items:
        title = "  ·  ".join(items)
        title_display = f" {title} "
        tlen = sum(2 if ord(c) > 0x2000 else 1 for c in title_display)
        pad_l = max(1, (width - tlen) // 2)
        pad_r = max(1, width - pad_l - tlen)
        sep = DIM + "·" * pad_l + RST + title_display + DIM + "·" * pad_r + RST
    else:
        sep = DIM + "·" * width + RST

    indicator = "\033[33m› \033[0m" if not _plan_active() else "\033[1m\033[38;5;214m PLAN \033[0m  "

    return ANSI(sep + "\n" + indicator)


_session: PromptSession = PromptSession(
    history=InMemoryHistory(),
    style=_pt_style,
    mouse_support=False,
    key_bindings=_make_keybindings(),
    completer=SlashCompleter(),
    complete_while_typing=True,
)


def _attachment_hint() -> str:
    if not _attachments:
        return ""
    names = "  ·  ".join(f"📎 {a.name}" for a in _attachments.items)
    return f"  {names}  "


def _debug_prompt(state: dict, graph, cfg: SessionConfig):
    try:
        from src.llm.prompts import build_system_prompt
        from src.utils.tools import get_tool_names

        config = {"configurable": {"thread_id": cfg.thread_id}}
        snapshot = graph.get_state(config)
        messages = snapshot.values.get("messages", []) if snapshot.values else state.get("messages", [])

        from datetime import date
        import os
        _user_name = os.getenv("USER_NAME", "l'utilisateur")
        _tool_list = get_tool_names()  # already a list
        _prompt_preview = build_system_prompt(_tool_list, str(date.today()), _user_name)[:300]

        from src.orchestrator.graph import get_last_selected_tools
        _selected = get_last_selected_tools()
        _selected_str = ", ".join(_selected) if _selected else "—"
        parts = [
            f"[dim]tools sélectionnés :[/dim] {_selected_str}",
            f"[dim]system:[/dim] {_prompt_preview}...",
        ]
        for m in messages:
            content = m.get("content", "") if isinstance(m, dict) else getattr(m, "content", "")
            role = m.get("role", "?") if isinstance(m, dict) else getattr(m, "type", "?")
            parts.append(f"[dim]{role}:[/dim] {content[:200]}")

        console.print(Panel(
            "\n\n".join(parts),
            box=__import__("rich.box", fromlist=["SIMPLE_HEAD"]).SIMPLE_HEAD,
            border_style="dim",
            title="prompt",
        ))
    except Exception as e:
        console.print(f"[dim]debug error: {e}[/dim]")


_FICHE_PROMPT = """\
INSTRUCTION PRIORITAIRE : Réponds UNIQUEMENT avec le code HTML complet. Aucun texte avant ou après, aucun bloc markdown, aucune explication.

Tu es un expert pédagogique. Génère une fiche de révision complète et visuellement soignée à partir du ou des documents fournis.

━━ OBJECTIF ━━

La meilleure fiche possible pour réviser un partiel : complète, dense, structurée.
Couvre TOUTES les notions du document — rien ne doit manquer.
Page unique, défilement vertical. Les éléments interactifs (accordéons, QCM rapide, flip cards) sont bienvenus quand ils aident à mémoriser, mais jamais obligatoires.

━━ STRUCTURE DU CONTENU ━━

1. HEADER STICKY : titre de la matière + badge + bouton Imprimer (window.print())

2. CHIFFRES CLÉS & FAITS ESSENTIELS (si applicable) :
   - Grid de cards avec les chiffres, dates, statistiques incontournables
   - Ce que l'examinateur attend qu'on sache par cœur

3. CONCEPTS & DÉFINITIONS :
   - Toutes les définitions importantes, précises, dans des cards (border-left teal)
   - Acronymes développés et expliqués
   - Mnémotechniques pour les listes longues

4. FORMULES, RÈGLES, THÉORÈMES :
   - Cards border-left violet, formule en monospace bien lisible
   - Conditions d'application, cas particuliers

5. CHAPITRES (dans l'ordre du document, tous couverts) :
   - Chaque chapitre = section h2 avec tout son contenu
   - Définitions, exemples concrets, cas pratiques
   - Tableaux comparatifs pour les éléments similaires (ex: types A/B/C)
   - Listes structurées et denses — pas de paraphrase vague
   - Accordéons JS optionnels pour les sous-sections très longues

6. DISTINCTIONS SUBTILES & PIÈGES :
   - Cards border-left rouge pour les confusions fréquentes
   - "X ≠ Y" clairement formulé
   - Erreurs classiques d'examen

7. SYNTHÈSE & RÉCAP FINAL :
   - Tableau récapitulatif des concepts essentiels (tout en une vue)
   - Acronymes et points à retenir absolument
   - Ce qui tombe souvent aux partiels

━━ DESIGN — AXON SLATE GLASS ━━

CSS entièrement embarqué dans le <style>. Aucune dépendance externe.
JS vanilla embarqué. Mode LIGHT par défaut, toggle dark/light dans le header.

━━ SYSTÈME DE THÈME DARK/LIGHT ━━

Implémente un système de thème complet avec CSS custom properties redéfinies par classe.
HTML : <html> sans classe par défaut = LIGHT MODE (parchemin chaud).
La classe .dark sur <html> active le dark mode.
Toggle JS : document.documentElement.classList.toggle('dark')
Persister dans localStorage : localStorage.setItem('theme', isDark ? 'dark' : 'light')
Au chargement : lire localStorage et appliquer la classe avant tout rendu (dans <head> avec script inline).

Variables :root (LIGHT par défaut — parchemin chaud) :
  --bg-base:      #f0e6d0
  --bg-grad:      linear-gradient(150deg, #f5edd8 0%, #ede0c4 40%, #f2e8d0 70%, #e8d8b8 100%)
  --bg-vignette:  radial-gradient(ellipse at 50% 100%, rgba(120,70,20,0.12) 0%, transparent 60%)
  --surface:      rgba(255,255,255,0.45)
  --surface-border: rgba(160,110,40,0.22)
  --header-bg:    rgba(240,230,210,0.90)
  --accent:       #b45309
  --accent-dim:   rgba(180,83,9,0.12)
  --accent-glow:  rgba(180,83,9,0.20)
  --text:         #292010
  --text-strong:  #1a1208
  --muted:        #7a6040
  --concept:      #0f766e
  --concept-bg:   rgba(15,118,110,0.10)
  --formula:      #6d28d9
  --formula-bg:   rgba(109,40,217,0.10)
  --example:      #1d4ed8
  --example-bg:   rgba(29,78,216,0.10)
  --danger:       #991b1b
  --danger-bg:    rgba(153,27,27,0.10)
  --success:      #166534
  --success-bg:   rgba(22,101,52,0.10)
  --scrollbar-track: rgba(160,110,40,0.15)
  --scrollbar-thumb: rgba(180,83,9,0.40)

Variables html.dark (dark mode — slate sombre) :
  --bg-base:      #0d1117
  --bg-grad:      linear-gradient(150deg, #0d1117 0%, #111520 40%, #0f1319 70%, #090d13 100%)
  --bg-vignette:  radial-gradient(ellipse at 50% 0%, rgba(99,102,241,0.08) 0%, transparent 65%)
  --surface:      rgba(255,255,255,0.05)
  --surface-border: rgba(255,255,255,0.10)
  --header-bg:    rgba(9,13,19,0.85)
  --accent:       #f59e0b
  --accent-dim:   rgba(245,158,11,0.15)
  --accent-glow:  rgba(245,158,11,0.30)
  --text:         #e2d9c8
  --text-strong:  #f0e8d8
  --muted:        #7a7060
  --concept:      #5eead4
  --concept-bg:   rgba(94,234,212,0.10)
  --formula:      #c4b5fd
  --formula-bg:   rgba(196,181,253,0.10)
  --example:      #93c5fd
  --example-bg:   rgba(147,197,253,0.10)
  --danger:       #fca5a5
  --danger-bg:    rgba(252,165,165,0.10)
  --success:      #86efac
  --success-bg:   rgba(134,239,172,0.10)
  --scrollbar-track: rgba(0,0,0,0.2)
  --scrollbar-thumb: rgba(245,158,11,0.35)

Règles globales :
  html, body {{ overflow-x: hidden; }}
  * {{ box-sizing: border-box; }}
  html {{ background: var(--bg-base); scrollbar-width: thin; scrollbar-color: var(--scrollbar-thumb) var(--scrollbar-track); }}
  body {{ background: var(--bg-grad); min-height: 100vh; color: var(--text); font-family: system-ui, "Segoe UI", sans-serif; font-size: 15px; line-height: 1.75; position: relative; }}
  body::before {{ content:""; position:fixed; inset:0; background:var(--bg-vignette); pointer-events:none; z-index:0; }}
  .container {{ max-width: 960px; margin: 0 auto; padding: 0 1.5rem 5rem; position: relative; z-index: 1; }}

  ANTI SCROLL HORIZONTAL — règles obligatoires :
  - Ne JAMAIS mettre min-width sur les tables
  - Entourer chaque table d'un div.table-wrapper {{ overflow-x: auto; width: 100%; border-radius: 10px; }}
  - Grids : grid-template-columns: repeat(auto-fit, minmax(160px, 1fr))
  - Tout élément enfant : max-width: 100%

Sticky header :
  position sticky, top 0, z-index 100
  background: var(--header-bg), backdrop-filter: blur(20px), -webkit-backdrop-filter: blur(20px)
  border-bottom: 2px solid var(--accent)
  padding: 0.8rem 1.5rem, display flex, justify-content space-between, align-items center, gap 1rem
  Titre h1 : font-size 1.1rem, font-weight 700, color var(--text-strong)
  Badge matière : background var(--accent), color white, border-radius 5px, padding 0.2em 0.7em, font-size 0.75rem, font-weight 700
  Zone boutons (flex, gap 0.5rem) :
    Bouton toggle thème : texte "☀ Clair" en dark / "◑ Sombre" en light
    Bouton imprimer : "⎙ Imprimer"
    Style commun : background var(--accent-dim), border 1.5px solid var(--accent), border-radius 6px,
      padding 0.3rem 0.8rem, font-size 0.8rem, font-weight 600, color var(--accent), cursor pointer
      hover : background var(--accent), color white (ou #1a0e00 en dark)

Sections h2 :
  color: var(--accent), font-size 0.78rem, font-weight 700, letter-spacing 0.14em, text-transform uppercase
  border-bottom: 2px solid var(--accent), padding-bottom 0.3rem, margin-top 2.5rem, margin-bottom 1.2rem

Cards (glassmorphism — marche en dark ET en light grâce aux variables) :
  background: var(--surface)
  backdrop-filter: blur(16px), -webkit-backdrop-filter: blur(16px)
  border: 1px solid var(--surface-border)
  border-radius: 12px, padding: 1.2rem 1.3rem, margin-bottom: 1rem
  box-shadow: 0 2px 16px rgba(0,0,0,0.12)
  position: relative, overflow: hidden

Cards sémantiques (border-left + fond via variable) :
  .card-concept : border-left 3px solid var(--concept), background var(--concept-bg), backdrop-filter blur(16px)
  .card-formula : border-left 3px solid var(--formula), background var(--formula-bg), backdrop-filter blur(16px)
  .card-example : border-left 3px solid var(--example), background var(--example-bg), backdrop-filter blur(16px)
  .card-danger  : border-left 3px solid var(--danger),  background var(--danger-bg),  backdrop-filter blur(16px)
  .card-mnemo   : border-left 3px solid var(--success), background var(--success-bg), backdrop-filter blur(16px)

Labels pill (haut à droite, position absolute) :
  font-size 0.65rem, font-weight 700, text-transform uppercase, border-radius 4px, padding 0.12em 0.5em
  Concept : color var(--concept), background var(--concept-bg), border 1px solid var(--concept)
  Formule : color var(--formula), background var(--formula-bg), border 1px solid var(--formula)
  Exemple : color var(--example), background var(--example-bg), border 1px solid var(--example)
  Piège   : color var(--danger),  background var(--danger-bg),  border 1px solid var(--danger)

Chiffres clés :
  grid repeat(auto-fit, minmax(160px, 1fr)), gap 1rem, margin-bottom 1.5rem
  Chaque card : background var(--surface), backdrop-filter blur(16px), border 1px solid var(--surface-border)
    border-radius 12px, padding 1.2rem 1rem, text-align center
  Chiffre : font-size 2.2rem, font-weight 800, color var(--accent)
  Label : font-size 0.78rem, color var(--muted), margin-top 0.25rem

Code inline : background var(--formula-bg), color var(--formula), border 1px solid var(--formula), border-radius 4px, padding 0.1em 0.4em, font-family monospace
Code bloc : background rgba(0,0,0,0.25), backdrop-filter blur(8px), border 1px solid var(--surface-border), border-radius 10px, padding 1rem, font-family monospace, overflow-x auto

Tableaux (dans div.table-wrapper overflow-x auto) :
  table : border-collapse collapse, width 100%
  th : background var(--accent-dim), color var(--accent), font-weight 700, padding 0.7rem 1rem, border-bottom 2px solid var(--accent), text-align left
  td : padding 0.6rem 1rem, border-bottom 1px solid var(--surface-border), color var(--text)
  tr:nth-child(even) : background var(--surface)

Mnémotechniques : background var(--success-bg), border-left 3px solid var(--success), border-radius 10px, padding 0.9rem 1.1rem
  .mnemo-label : color var(--success), font-size 0.72rem, font-weight 700, display block, margin-bottom 0.3rem

@media print :
  header display none
  body background white !important, color #1c1917 !important
  .card {{ background #f9f6f0 !important; border 1px solid #d0c8b8 !important; backdrop-filter none !important; }}
  h2 {{ color #8b5e3c !important; border-color #8b5e3c !important; }}

━━ JS THÈME ━━

Script dans <head> (avant tout rendu, évite le flash) :
  const saved = localStorage.getItem('axon-theme');
  if (saved === 'dark') document.documentElement.classList.add('dark');
  // pas de classe = light (défaut)

Bouton toggle dans le header — texte initial "◑ Sombre" (car on est en light par défaut) :
  onclick :
    const isDark = document.documentElement.classList.toggle('dark');
    localStorage.setItem('axon-theme', isDark ? 'dark' : 'light');
    this.textContent = isDark ? '☀ Clair' : '◑ Sombre';

━━ CONTENU ━━

Sois exhaustif — une fiche utile est dense, pas vague.
Fusionne intelligemment si plusieurs documents.
Inclure des mémotechniques quand les listes sont longues (acronymes, phrases).
Les tableaux comparatifs sont préférables aux listes pour les éléments similaires.

━━ DOCUMENTS À ANALYSER ━━
{content}
"""

_EXO_PROMPT = """\
INSTRUCTION PRIORITAIRE : Réponds UNIQUEMENT avec le code HTML complet. Aucun texte avant ou après, aucun bloc markdown.

Tu es un expert pédagogique. Génère un fichier d'exercices interactifs complet à partir du ou des documents fournis.

━━ TYPE D'EXERCICES ━━
{type_exo}

━━ STRUCTURE ━━

1. En-tête : titre, nombre de questions, score en temps réel
2. Barre de progression (trait fin accent orange)
3. Questions (une par écran) :
   - QCM : 4 choix, clic → feedback immédiat + explication de la bonne réponse
   - Question ouverte : textarea + bouton "Voir la réponse" qui révèle la réponse correcte
   - Vrai/Faux : 2 boutons avec feedback
4. Navigation : Précédent / Suivant, "X / Y"
5. Score final : résumé, questions ratées avec corrections, bouton Rejouer

━━ JAVASCRIPT ━━

Vanilla JS embarqué. Logique :
- État de session (réponses, score)
- Feedback visuel immédiat, réponse verrouillée après validation
- Résumé final complet
- Bouton Rejouer

━━ DESIGN — AXON DARK ━━

CSS entièrement embarqué. Aucune dépendance externe.

Palette stricte :
  --bg:         #0f0f13
  --surface:    #16161d
  --border:     rgba(255, 175, 0, 0.15)
  --accent:     #ffaf00
  --accent-dim: rgba(255, 175, 0, 0.08)
  --text:       #e2e8f0
  --muted:      #888
  --correct:    #22c55e
  --wrong:      #ef4444
  --reveal:     #3b82f6

Règles :
- body : background --bg, color --text, font-family "JetBrains Mono", "Fira Code", monospace, font-size 15px
- max-width 720px centré, padding 2rem
- En-tête : titre color --accent, compteur color --muted
- Barre de progression : height 2px, background --border, fill --accent, transition smooth
- Card question : background --surface, border 1px solid --border, border-radius 6px, padding 1.5rem
- Choix QCM : boutons full-width, background transparent, border 1px solid --border, color --text, hover → border-color --accent background --accent-dim
- Correct → border --correct, background rgba(34,197,94,0.08), color --correct
- Incorrect → border --wrong, background rgba(239,68,68,0.08), color --wrong
- Révélation → border --reveal, background rgba(59,130,246,0.08)
- Explication : font-size 0.85rem, color --muted, margin-top 0.75rem, border-left 2px solid --accent, padding-left 0.75rem
- Boutons nav : background --accent-dim, border 1px solid --border, color --accent, border-radius 4px, hover → background --accent color #0f0f13
- Textarea : background #0a0a10, border 1px solid --border, color --text, border-radius 4px
- Transitions : 150ms ease sur couleurs et opacité
- Scrollbar thin, track --bg, thumb --accent

━━ CONTENU ━━

Génère entre 10 et 20 questions selon la richesse du document.
Questions couvrant les points importants, pas triviales.
Distracteurs QCM plausibles.

━━ DOCUMENTS À ANALYSER ━━
{content}
"""


def _build_pdf_content(attachments) -> str:
    """Assemble le contenu textuel des pièces jointes pour /fiche et /exo.
    Utilise le contenu brut complet (pas la version tronquée à 25k de l'orchestrateur)."""
    from .attachments import _extract_pdf
    parts = []
    for a in attachments:
        if a.is_image:
            continue
        # Re-extract at full size if this is a PDF attachment stored with a path hint
        content = a.content or ""
        parts.append(f"=== {a.name} ===\n{content}")
    return "\n\n".join(parts) if parts else ""


def _save_html_output(content: str, prefix: str, slug: str = "") -> Path:
    """Extrait le HTML de la réponse LLM et le sauvegarde."""
    import re as _re

    m = _re.search(r'```html\s*(.*?)```', content, _re.DOTALL)
    html = m.group(1).strip() if m else content.strip()

    out_dir = Path.home() / "Documents" / "axon_fiches"
    out_dir.mkdir(parents=True, exist_ok=True)
    name = f"{prefix}_{slug}.html" if slug else f"{prefix}.html"
    out = out_dir / name
    # avoid overwrite
    if out.exists():
        import time
        out = out_dir / f"{prefix}_{slug}_{int(time.time())}.html"
    out.write_text(html, encoding="utf-8")
    return out


def _pdf_slug(attachments) -> str:
    """Génère un slug lisible depuis les noms de fichiers joints."""
    import re as _re
    names = [a.name for a in attachments if not a.is_image]
    if not names:
        from datetime import datetime
        return datetime.now().strftime("%Y%m%d_%H%M")
    # Prend le premier nom, retire l'extension, nettoie
    raw = Path(names[0]).stem
    slug = _re.sub(r"[^a-zA-Z0-9À-ÿ]+", "-", raw).strip("-")[:50].lower()
    return slug or "fiche"


def _handle_fiche(graph, state: dict, cfg: "SessionConfig") -> None:
    if not _attachments:
        console.print(command_panel("joint d'abord tes PDF avec /attach, puis relance /fiche", error=True))
        return

    attachments = _attachments.pop_all()
    content = _build_pdf_content(attachments)
    if not content:
        console.print(command_panel("aucun contenu texte extrait des pièces jointes", error=True))
        return

    slug = _pdf_slug(attachments)
    prompt = _FICHE_PROMPT.format(content=content[:60_000])
    result = _run_letter_stream(graph, prompt, [], cfg)
    if result:
        try:
            out = _save_html_output(result, "fiche", slug)
            t = Text()
            t.append("  📄  ", style=f"bold {ACCENT}")
            t.append(str(out), style=ACCENT)
            console.print(t)
            import subprocess
            subprocess.Popen(["xdg-open", str(out)])
        except Exception as e:
            console.print(command_panel(f"erreur sauvegarde : {e}", error=True))


def _handle_exo(graph, state: dict, cfg: "SessionConfig") -> None:
    if not _attachments:
        console.print(command_panel("joint d'abord tes PDF avec /attach, puis relance /exo", error=True))
        return

    console.print(Rule(characters="·", style=f"dim {ACCENT}"))
    t = Text()
    t.append("  🎯  ", style=f"bold {ACCENT}")
    t.append("Type d'exercices", style=f"dim {ACCENT}")
    t.append("  — qcm / ouvert / mixte (défaut: mixte)", style="dim")
    console.print(t)
    try:
        choix = _session.prompt("  ").strip().lower() or "mixte"
    except (EOFError, KeyboardInterrupt):
        return

    types = {
        "qcm":    "QCM uniquement (4 choix par question, avec explication de la bonne réponse).",
        "ouvert": "Questions ouvertes uniquement (textarea + bouton révéler la réponse correcte).",
        "mixte":  "Mélange de QCM (60%) et questions ouvertes (40%), plus quelques Vrai/Faux.",
    }
    type_exo = types.get(choix, types["mixte"])

    attachments = _attachments.pop_all()
    content = _build_pdf_content(attachments)
    if not content:
        console.print(command_panel("aucun contenu texte extrait des pièces jointes", error=True))
        return

    slug = _pdf_slug(attachments)
    prompt = _EXO_PROMPT.format(content=content[:60_000], type_exo=type_exo)
    result = _run_letter_stream(graph, prompt, [], cfg)
    if result:
        try:
            out = _save_html_output(result, "exo", slug)
            t = Text()
            t.append("  🎯  ", style=f"bold {ACCENT}")
            t.append(str(out), style=ACCENT)
            console.print(t)
            import subprocess
            subprocess.Popen(["xdg-open", str(out)])
        except Exception as e:
            console.print(command_panel(f"erreur sauvegarde : {e}", error=True))


_LETTRE_PROMPT = """\
INSTRUCTION PRIORITAIRE : Réponds UNIQUEMENT avec la lettre de motivation.
Aucune section de réflexion, aucun commentaire, aucun emoji de section, aucun texte avant ou après.
N'utilise aucun outil (pas de web_research_report, pas de recherche web).

━━ PRÉPARATION (mentale, ne pas écrire) ━━
1. Extrais du CV : formation actuelle, 2-3 expériences techniques les plus récentes avec technologies précises.
2. Extrais de l'offre : les 3 missions principales et les compétences techniques demandées.
3. Construis 2-3 correspondances explicites : expérience CV → compétence démontrée → mission de l'offre.
4. Identifie 1 élément différenciant du profil (ML, RAG, migration legacy, temps réel, API…).
5. Identifie pourquoi cet environnement technique est intéressant (sécurité, scale, legacy, performance…).

━━ STRUCTURE (4 paragraphes, 160-220 mots au total) ━━

§1 — Introduction (2-3 lignes)
  Présente le profil, la formation, le poste visé.
  Pas de "Je vous soumets", "C'est avec grand intérêt", "Je me permets", "je suis ravi".
  Commence directement par le contexte : "Étudiant en [formation] à [école]..."

§2 — Expériences techniques (5-6 lignes)
  2-3 expériences concrètes du CV avec le schéma :
    contexte → technologie utilisée → problème résolu ou résultat obtenu
  Exemples : migration Symfony PHP 5→8, API NestJS+Mercury, assistant RAG, full-stack Angular.
  Intégrer au moins 1 compétence différenciante (ML, RAG, temps réel, migration legacy).
  Ce que le candidat a réellement fait, pas ce qu'il veut faire.

§3 — Adéquation avec le poste (3-4 lignes)
  Relier explicitement 2 expériences aux missions de l'offre.
  Format : "Ces expériences m'ont préparé à [mission du poste]."
  Ajouter 1 phrase sur l'environnement technique de l'entreprise (fiabilité, sécurité, scale, legacy).
  Pas de flatterie générique sur la notoriété de l'entreprise.

§4 — Conclusion (2 lignes)
  Montrer l'envie de contribuer à l'équipe technique.
  Proposer un entretien de façon directe et non servile.

━━ MOTS ET FORMULES INTERDITS ━━
ravi · enchanté · dynamique · motivé · passionné · je me permets · en effet ·
dans ce contexte · je suis convaincu · permettre de · désireux · je vous soumets ·
ma candidature · à ce titre · fort de · cette opportunité · contribuer à votre succès ·
entreprise leader · n'hésitez pas à · toute information complémentaire

━━ RÈGLES SUPPLÉMENTAIRES ━━
- Aucun titre, sous-titre ou label de section dans la lettre
- Aucune liste à puces ou numérotée
- Chaque paragraphe commence par un mot différent
- Aucune idée répétée dans deux paragraphes différents
- Longueur : 160-220 mots (hors en-tête et signature)
- Ton : professionnel, direct, technique — pas marketing, pas RH

━━ FORMAT DE SORTIE EXACT ━━

Objet : [intitulé du poste] chez [nom de l'entreprise]

Madame, Monsieur,

[§1]

[§2]

[§3]

[§4]

Cordialement,

[Prénom NOM extrait du CV]

━━ OFFRE D'EMPLOI ━━
{offre}
"""

_AMELIORE_PROMPT = """\
INSTRUCTION PRIORITAIRE : Réponds UNIQUEMENT avec la lettre améliorée.
Aucun commentaire, aucune explication, aucun texte avant ou après.

Tu peux utiliser l'outil web_research_report pour rechercher des informations sur l'entreprise \
(stack technique, produits, culture, taille, secteur) afin de personnaliser la lettre. \
Fais cette recherche en premier si le nom de l'entreprise est identifiable dans l'offre.

━━ TA MISSION ━━
Améliore la lettre de motivation existante pour atteindre un niveau 9/10 pour un poste IT junior/alternance.
Ne réécris pas depuis zéro — conserve les expériences du candidat, améliore la forme et la pertinence.

━━ PRÉPARATION (mentale, ne pas écrire) ━━
1. Identifier les expériences techniques du CV (technologies, projets, résultats).
2. Identifier les 3 missions principales de l'offre.
3. Associer chaque expérience à une mission avec le schéma : contexte → techno → résultat → mission couverte.
4. Supprimer toute phrase générique ou paraphrase du CV sans valeur ajoutée.
5. Si recherche web effectuée : intégrer 1 fait concret sur l'environnement technique de l'entreprise.

━━ AMÉLIORATIONS OBLIGATOIRES ━━
- Transformer "je suis compétent en X" → "j'ai résolu Y avec X dans le contexte Z"
- Remplacer toute phrase RH générique par un fait technique précis
- Corriger les noms de technologies mal orthographiés ou mal utilisés
- Ajouter le lien explicite : expérience → mission du poste (si absent)
- Renforcer la conclusion : intérêt pour l'env. technique + proposition d'entretien directe

━━ STRUCTURE (4 paragraphes, 160-200 mots) ━━

§1 — Introduction (2-3 lignes)
  Formation actuelle + domaine + poste visé.
  Commencer par le profil, pas par une formule de politesse.

§2 — Expériences techniques (5-6 lignes)
  2-3 expériences avec : contexte → technologie → problème résolu / résultat.
  Au moins 1 compétence différenciante (ML, RAG, migration legacy, temps réel, API…).

§3 — Adéquation avec le poste (3-4 lignes)
  Relier 2 expériences aux missions de l'offre de façon explicite.
  1 phrase sur l'environnement technique de l'entreprise si info disponible.

§4 — Conclusion (2 lignes)
  Envie de contribuer à l'équipe + proposition d'entretien directe et non servile.

━━ MOTS ET FORMULES INTERDITS ━━
ravi · enchanté · dynamique · motivé · passionné · je me permets · en effet ·
dans ce contexte · je suis convaincu · permettre de · désireux · je vous soumets ·
à ce titre · fort de · cette opportunité · contribuer à votre succès · entreprise leader ·
n'hésitez pas · toute information complémentaire · mes compétences correspondent

━━ FORMAT DE SORTIE EXACT ━━

Objet : [intitulé du poste] chez [nom de l'entreprise]

Madame, Monsieur,

[§1]

[§2]

[§3]

[§4]

Cordialement,

[Prénom NOM extrait du CV]

━━ ENTRÉES ━━
LETTRE EXISTANTE :
{lettre}

OFFRE D'EMPLOI :
{offre}
"""


def _collect_multiline(prompt_text: str, icon: str = "📋") -> str | None:
    """Collecte du texte multi-lignes, puis efface le contenu collé et affiche un résumé propre."""
    console.print(Rule(characters="·", style=f"dim {ACCENT}"))
    t = Text()
    t.append(f"  {icon}  ", style=f"bold {ACCENT}")
    t.append(f"{prompt_text}", style=f"dim {ACCENT}")
    t.append("  — colle puis ligne vide pour valider", style="dim")
    console.print(t)
    console.print()

    lines = []
    try:
        while True:
            line = _session.prompt("  ").strip()
            if not line:
                break
            lines.append(line)
    except (EOFError, KeyboardInterrupt):
        console.print(command_panel("annulé"))
        return None

    if not lines:
        return None

    text = "\n".join(lines)
    word_count = len(text.split())
    char_count = len(text)

    # Efface le contenu collé et affiche un résumé propre
    console.clear()
    console.print(Rule(characters="·", style=f"dim {ACCENT}"))
    summary = Text()
    summary.append(f"  {icon}  ", style=f"bold {ACCENT}")
    summary.append(f"{prompt_text}  ", style=ACCENT)
    summary.append(f"{word_count} mots · {char_count} caractères", style="dim")
    console.print(summary)

    return text


def _run_letter_stream(graph, prompt_text: str, attachments, cfg: SessionConfig) -> str:
    """Lance le stream pour une lettre, retourne le texte généré.
    Appelle le LLM directement (pas via le graph) pour éviter le overhead
    du system prompt + tools descriptions qui ferait exploser le contexte.
    """
    from langchain_core.messages import HumanMessage
    from src.llm.models import make_llm, make_llm_ollama_cloud, make_llm_groq
    from src.infra.settings import settings
    _factories = {"ollama": make_llm, "groq": make_llm_groq, "ollama_cloud": make_llm_ollama_cloud}
    factory = _factories.get(settings.llm_backend, make_llm_ollama_cloud)

    # Construire le message avec pièces jointes
    if attachments:
        from .attachments import build_message_with_attachments
        msg_dict = build_message_with_attachments(prompt_text, attachments)
        human_msg = HumanMessage(content=msg_dict["content"])
    else:
        human_msg = HumanMessage(content=prompt_text)

    llm = factory()
    stop_thinking = threading.Event()

    response_content = ""
    try:
        with Live(live_panel_initial(), console=console, refresh_per_second=_REFRESH_RATE, vertical_overflow="crop") as live:
            saw_any_token = False
            deb = {"DEBOUNCE": _DEBOUNCE, "last_update": 0.0}
            t0 = perf_counter()

            t = threading.Thread(target=_make_thinking_loop(stop_thinking, live), daemon=True)
            t.start()

            for chunk in llm.stream([human_msg]):
                chunk_text = chunk.content or "" if hasattr(chunk, "content") else str(chunk)
                if not chunk_text:
                    continue
                stop_thinking.set()
                saw_any_token = True
                response_content += chunk_text
                update_live_markdown(live, response_content, deb, cursor=True)

            stop_thinking.set()
            footer = fmt_ms(perf_counter() - t0)
            if saw_any_token:
                finalize_live(live, response_content, footer)
    except Exception as e:
        console.print(command_panel(f"erreur : {e}", error=True))

    return response_content


def _export_letter(response_content: str) -> None:
    """Génère DOCX + PDF depuis le texte de la lettre."""
    if not response_content:
        return
    try:
        from src.agents.filesystem.letter import generate_docx, docx_to_pdf

        company = ""
        for line in response_content.splitlines():
            if line.strip().lower().startswith("objet"):
                m = re.search(r"chez\s+(.+)", line, re.IGNORECASE)
                if m:
                    parts = m.group(1).strip().split()
                    company = parts[0] if parts else ""
                break

        candidate = "Quentin Dufour"
        for line in reversed(response_content.splitlines()):
            s = line.strip()
            if s and not s.lower().startswith("cordialement") and len(s.split()) <= 4:
                candidate = s
                break

        docx_path = generate_docx(response_content, candidate_name=candidate, company=company)
        pdf_path  = docx_to_pdf(docx_path)

        t = Text()
        t.append("  📄  ", style=f"bold {ACCENT}")
        t.append(str(docx_path.name), style=ACCENT)
        t.append("  +  PDF  →  ", style="dim")
        t.append(str(pdf_path), style=f"dim {ACCENT}")
        console.print(t)
    except Exception as e:
        console.print(command_panel(f"export échoué : {e}", error=True))


def _handle_lettre(graph, state: dict, cfg: SessionConfig) -> None:
    if not _attachments:
        console.print(command_panel("joint ton CV d'abord avec /attach, puis relance /lettre", error=True))
        return

    offre = _collect_multiline("offre d'emploi", icon="💼")
    if not offre:
        console.print(command_panel("aucune offre fournie", error=True))
        return

    attachments = _attachments.pop_all()
    result = _run_letter_stream(graph, _LETTRE_PROMPT.format(offre=offre), attachments, cfg)
    _export_letter(result)


def _handle_ameliore(graph, state: dict, cfg: SessionConfig) -> None:
    if not _attachments:
        console.print(command_panel(
            "attache au moins ton CV avec /attach (+ optionnellement ta lettre)", error=True
        ))
        return

    # Si 2+ fichiers attachés → le 2e est la lettre existante, pas besoin de la coller
    if len(_attachments) >= 2:
        lettre = "(voir fichier joint)"
        console.print(Text(
            "  📎  CV + lettre détectés dans les pièces jointes", style=f"dim {ACCENT}"
        ))
    else:
        lettre = _collect_multiline("lettre existante", icon="📝")
        if not lettre:
            console.print(command_panel("aucune lettre fournie", error=True))
            return

    offre = _collect_multiline("offre d'emploi", icon="💼")
    if not offre:
        console.print(command_panel("aucune offre fournie", error=True))
        return

    attachments = _attachments.pop_all()
    prompt = _AMELIORE_PROMPT.format(lettre=lettre, offre=offre)
    result = _run_letter_stream(graph, prompt, attachments, cfg)
    _export_letter(result)


def _stream_message(graph, text: str, cfg: SessionConfig) -> None:
    """Streams a single text message to the graph (no slash commands, no HITL re-check)."""
    from langchain_core.messages import HumanMessage

    current_state = {"messages": [HumanMessage(content=text)]}
    config = {"configurable": {"thread_id": cfg.thread_id}}

    stop_thinking = threading.Event()
    pending_refinements_inner: list[str] = []

    try:
        with Live(live_panel_initial(), console=console, refresh_per_second=_REFRESH_RATE, vertical_overflow="crop") as live:
            response_content = ""
            saw_any_token = False
            last_node = ""
            deb = {"DEBOUNCE": _DEBOUNCE, "last_update": 0.0}
            t0 = perf_counter()

            t = threading.Thread(target=_make_thinking_loop(stop_thinking, live), daemon=True)
            t.start()

            for msg, meta in graph.stream(current_state, config=config, stream_mode="messages"):
                node = meta.get("langgraph_node") or "unknown"
                if isinstance(msg, ToolMessage):
                    tool_name = getattr(msg, "name", None) or getattr(msg, "tool_name", None) or meta.get("tool", "tool")
                    if tool_name == "gmail_send_email":
                        stop_thinking.set()
                        live.stop()
                        from .review import review_email
                        action, refinement = review_email()
                        if action == "send":
                            pending_refinements_inner.append("Email envoyé avec succès.")
                        elif action == "cancel":
                            pending_refinements_inner.append("Envoi annulé par l'utilisateur.")
                        elif action == "modify" and refinement:
                            pending_refinements_inner.append(f"L'utilisateur veut modifier le mail : {refinement}")
                        live.start(refresh=False)
                    elif tool_name in ("dev_plan_create", "dev_plan_step_done"):
                        stop_thinking.set()
                        live.update(Text(""))
                        live.stop()
                        from src.agents.coding.pending import render_plan
                        render_plan(console)
                        live.start(refresh=False)
                        last_node = "tools"
                    else:
                        live.update(tool_call_panel(tool_name))
                    last_node = "tools"
                    continue
                if isinstance(msg, AIMessageChunk):
                    chunk_text = msg.content or ""
                    if not chunk_text:
                        continue
                    if last_node == "tools":
                        response_content = ""
                        saw_any_token = False
                        last_node = "chatbot"
                    stop_thinking.set()
                    saw_any_token = True
                    response_content += chunk_text
                    update_live_markdown(live, response_content, deb, cursor=True)
                elif isinstance(msg, AIMessage) and not saw_any_token:
                    chunk_text = msg.content or ""
                    if not chunk_text:
                        continue
                    if last_node == "tools":
                        response_content = ""
                        last_node = "chatbot"
                    stop_thinking.set()
                    saw_any_token = True
                    response_content = chunk_text
                    update_live_markdown(live, response_content, deb, cursor=False)

            stop_thinking.set()
            footer = fmt_ms(perf_counter() - t0)
            if saw_any_token:
                finalize_live(live, response_content, footer)
    except Exception as e:
        console.print(command_panel(f"erreur : {e}", error=True))

    for refinement in pending_refinements_inner:
        _stream_message(graph, refinement, cfg)


_AT_RE = re.compile(r'@([\w./\-]+)')
_AT_MAX_CHARS = 6_000


def _resolve_at_mentions(text: str) -> str:
    """Replace @filepath tokens with the file's content in a fenced code block.

    Tries exact path first (absolute, then relative to shell CWD), then fuzzy
    match on git-tracked files inside the current working directory.
    Files larger than _AT_MAX_CHARS are truncated with a notice.
    """
    from src.agents.shell.tools import get_cwd
    mentions = _AT_RE.findall(text)
    if not mentions:
        return text

    cwd = get_cwd()

    for mention in mentions:
        p = Path(mention)
        # 1. Absolute path
        if not (p.exists() and p.is_file()):
            # 2. Relative to shell CWD
            candidate = (cwd / mention).resolve()
            if candidate.exists() and candidate.is_file():
                p = candidate
        if not (p.exists() and p.is_file()):
            # 3. Fuzzy match on git-tracked files inside CWD
            try:
                r = subprocess.run(
                    ["git", "ls-files"],
                    capture_output=True, text=True, timeout=5,
                    cwd=str(cwd),
                )
                files = r.stdout.strip().splitlines()
                ml = mention.lower()
                matches = [f for f in files if ml in f.lower()]
                if matches:
                    p = (cwd / matches[0]).resolve()
            except Exception:
                continue

        if not (p.exists() and p.is_file()):
            continue

        try:
            content = p.read_text(encoding="utf-8", errors="replace")
            truncated = len(content) > _AT_MAX_CHARS
            if truncated:
                content = content[:_AT_MAX_CHARS]
            ext = p.suffix.lstrip(".")
            block = (
                f"\n\n```{ext}\n# {p}\n{content}"
                f"{'…[tronqué]' if truncated else ''}\n```\n"
            )
            text = text.replace(f"@{mention}", block, 1)

            label = Text()
            label.append("  @  ", style=f"bold {ACCENT}")
            label.append(str(p), style="dim")
            if truncated:
                label.append("  [tronqué]", style="dim red")
            console.print(label)
        except Exception:
            pass

    return text


def _separator_rule() -> Rule:
    """Build the separator rule with optional plan badge, attachment hint and token gauge."""
    from src.ui.token_gauge import gauge_markup, has_tokens
    from src.ui.plan_mode import is_active as _is_plan_mode
    from src.infra.settings import settings

    hint  = _attachment_hint().strip()
    gauge = gauge_markup(settings.llm_backend) if has_tokens() else ""
    plan  = _is_plan_mode()

    if plan or hint or gauge:
        title = Text()
        if plan:
            title.append_text(Text.from_markup(f"[bold {ACCENT}]◆ PLAN[/bold {ACCENT}]"))
        if plan and (hint or gauge):
            title.append("  ·  ", style="dim")
        if hint:
            title.append(hint, style=f"dim {ACCENT}")
        if hint and gauge:
            title.append("  ·  ", style="dim")
        if gauge:
            title.append_text(Text.from_markup(gauge))
        return Rule(title, characters="·", style=f"dim {ACCENT}")
    return Rule(characters="·", style=f"dim {ACCENT}")


def _prune_after_compression(graph, config: dict) -> None:
    """After stream completes: if a compressed summary exists in state, remove all
    pre-summary messages from the checkpoint so next session starts clean."""
    try:
        from langchain_core.messages import RemoveMessage, SystemMessage

        snap = graph.get_state(config)
        if not snap or not snap.values:
            return
        msgs = snap.values.get("messages", [])

        def _content(m):
            return str(m.get("content", "") if isinstance(m, dict) else getattr(m, "content", ""))

        def _msg_id(m):
            return m.get("id") if isinstance(m, dict) else getattr(m, "id", None)

        def _is_system(m):
            t = m.get("type") or m.get("role", "") if isinstance(m, dict) else getattr(m, "type", "")
            return t == "system"

        # Find the LAST summary message (most recent compression)
        summary_idx = None
        for i, m in enumerate(msgs):
            if "[CONTEXTE COMPRESSÉ" in _content(m):
                summary_idx = i

        if summary_idx is None:
            return  # no compression in this state

        # Remove all non-system messages that appear before the last summary
        to_remove = [
            RemoveMessage(id=_msg_id(m))
            for m in msgs[:summary_idx]
            if not _is_system(m) and _msg_id(m)
        ]
        if to_remove:
            graph.update_state(config, {"messages": to_remove})
    except Exception:
        pass


def stream_once(graph, state: dict, cfg: SessionConfig) -> None:
    try:
        user_message = _session.prompt(_prompt_tokens).strip()
    except (EOFError, KeyboardInterrupt):
        raise KeyboardInterrupt

    if not user_message:
        return

    if user_message.lower() in {"quit", "exit", "q"}:
        raise KeyboardInterrupt

    if user_message.startswith("/"):
        # Commandes pièces jointes gérées ici (accès à _attachments et console)
        if user_message == "/attach":
            path = open_file_picker()
            if path:
                a = _attachments.add_file(path)
                if a:
                    t = Text()
                    t.append("  📎  ", style=f"bold {ACCENT}")
                    t.append(a.name, style=ACCENT)
                    t.append(f"  [{a.size_hint}]", style="dim")
                    console.print(t)
                else:
                    console.print(command_panel("fichier introuvable ou illisible", error=True))
            return

        if user_message.startswith("/detach"):
            parts = user_message.split(maxsplit=1)
            if len(parts) == 1:
                # /detach sans argument → supprimer tout
                _attachments.pop_all()
                console.print(command_panel("pièces jointes supprimées"))
            else:
                name = parts[1].strip()
                if _attachments.remove(name):
                    console.print(command_panel(f"supprimé : {name}"))
                else:
                    console.print(command_panel(f"introuvable : {name}", error=True))
            return

        if user_message == "/paste":
            img = get_clipboard_image()
            if img:
                a = _attachments.add_clipboard_image(img)
                t = Text()
                t.append("  📷  ", style=f"bold {ACCENT}")
                t.append(a.name, style=ACCENT)
                t.append(f"  [{a.size_hint}]", style="dim")
                console.print(t)
            else:
                console.print(command_panel("aucune image dans le presse-papiers", error=True))
            return

        if user_message == "/attachments":
            if not _attachments:
                console.print(command_panel("aucune pièce jointe en attente"))
            else:
                from rich.table import Table
                from rich import box as rbox
                tbl = Table(box=rbox.SIMPLE_HEAD, show_header=False, padding=(0, 2))
                tbl.add_column("", style=f"bold {ACCENT}", no_wrap=True)
                tbl.add_column("", style="dim")
                for a in _attachments.items:
                    icon = "📷" if a.is_image else "📎"
                    tbl.add_row(f"{icon}  {a.name}", a.size_hint)
                from rich.panel import Panel as _Panel
                from .panels import _BOX
                console.print(_Panel(tbl, box=_BOX, border_style=f"dim {ACCENT}", title="pièces jointes"))
            return

        if user_message == "/purge":
            config = {"configurable": {"thread_id": cfg.thread_id}}
            try:
                from langchain_core.messages import HumanMessage as _HM
                snap = graph.get_state(config)
                if snap and snap.values:
                    msgs = snap.values.get("messages", [])
                    patched, n = [], 0
                    for m in msgs:
                        if hasattr(m, "content") and isinstance(m.content, list):
                            text_parts = [
                                p.get("text", "")
                                for p in m.content
                                if isinstance(p, dict) and p.get("type") == "text"
                            ]
                            patched.append(_HM(
                                content=" ".join(text_parts).strip() or "[message nettoyé]",
                                id=getattr(m, "id", None),
                            ))
                            n += 1
                        else:
                            patched.append(m)
                    if n:
                        graph.update_state(config, {"messages": patched})
                        console.print(command_panel(f"{n} message(s) nettoyé(s) — images supprimées de l'état"))
                    else:
                        console.print(command_panel("aucune image dans l'état du thread"))
                else:
                    console.print(command_panel("état vide"))
            except Exception as ex:
                console.print(command_panel(f"erreur purge : {ex}", error=True))
            return

        if user_message == "/letter":
            _handle_lettre(graph, state, cfg)
            return

        if user_message == "/upgrade":
            _handle_ameliore(graph, state, cfg)
            return

        if user_message == "/fiche":
            _handle_fiche(graph, state, cfg)
            return

        if user_message == "/exo":
            _handle_exo(graph, state, cfg)
            return

        from .commands import handle_slash
        result = handle_slash(user_message, state, cfg, graph, console)
        if result:
            console.print(result)
        return

    # ── Résolution des @mentions (injection fichiers) ─────────────────────────
    user_message = _resolve_at_mentions(user_message)

    # ── Détection intention fiche/exo en mode normal (avec pièces jointes) ────
    if _attachments:
        _msg_lower = user_message.lower()
        _FICHE_TRIGGERS = (
            "fiche", "révision", "revision", "résumé de cours", "resume de cours",
            "fais moi une fiche", "fais-moi une fiche", "fait moi une fiche",
            "crée une fiche", "cree une fiche", "génère une fiche", "genere une fiche",
        )
        _EXO_TRIGGERS = (
            "exercice", "exo", "qcm", "quiz", "entraînement", "entrainement",
            "fais moi des exercices", "génère des exercices", "genere des exercices",
        )
        if any(t in _msg_lower for t in _FICHE_TRIGGERS):
            _handle_fiche(graph, state, cfg)
            return
        if any(t in _msg_lower for t in _EXO_TRIGGERS):
            _handle_exo(graph, state, cfg)
            return

    # ── Guard : détection tentative d'extraction du prompt ────────────────────
    from .prompt_guard import is_prompt_request, sanitize as _guard_sanitize
    if is_prompt_request(user_message):
        console.print(command_panel("Ces informations sont confidentielles."))
        return

    cfg.debug = debug_state["enabled"]
    user_lang = cfg.lang_pref if cfg.lang_pref in {"fr", "en"} else detect_lang(user_message)

    # Injecter les pièces jointes dans le message
    attachments = _attachments.pop_all()
    message_dict = build_message_with_attachments(user_message, attachments)
    current_state = {"messages": [message_dict]}

    config = {"configurable": {"thread_id": cfg.thread_id}}

    if cfg.debug:
        _debug_prompt(state, graph, cfg)

    from src.ui.edit_mode import get_mode
    from src.agents.coding.specialist import set_progress_callback
    from src.orchestrator.graph import set_compile_callback

    pending_refinements: list[str] = []
    stop_thinking = threading.Event()
    compile_mode = threading.Event()  # shared with thinking thread — switches panel
    _thinking_thread: list[threading.Thread] = []  # mutable holder so _coding_progress can join it
    _last_explain: str = ""  # dedup dev_explain panels

    live = Live(live_panel_initial(), console=console, refresh_per_second=_REFRESH_RATE, vertical_overflow="crop")

    def _on_compile() -> None:
        """Switch the existing thinking thread to compile animation — no new thread."""
        compile_mode.set()

    def _coding_progress(tool_name: str, args: dict, result: dict | None = None):
        """Called by the coding specialist for plan/file/shell events.

        Called BEFORE execution with tool_name="shell_run:before" (pre-hook).
        Called AFTER execution with the actual tool_name and result.

        Returns a dict to override the ToolMessage content (HITL mechanism),
        or None to keep the original result.
        """
        nonlocal response_content, saw_any_token
        response_content = ""
        saw_any_token = False
        override = None

        # Stop thinking animation once (first call only) — join to avoid race on live.update
        if not stop_thinking.is_set():
            stop_thinking.set()
            if _thinking_thread:
                _thinking_thread[0].join(timeout=0.5)
            try:
                live.update(Text(""))
            except Exception:
                pass

        # ── Specialist context compression → compile animation ───────────────
        if tool_name == "specialist:compress":
            compile_mode.set()
            return None

        # ── Pre-execution: shell command preview ──────────────────────────────
        if tool_name == "shell_run:before":
            cmd = (args or {}).get("command", "")
            if cmd:
                display = cmd if len(cmd) <= 90 else cmd[:87] + "…"
                t = Text()
                t.append("  $ ", style=f"bold {ACCENT}")
                t.append(display, style="white")
                console.print(t)

        elif tool_name == "shell_cd:before":
            path = (args or {}).get("path", "")
            if path:
                t = Text()
                t.append("  cd ", style=f"dim {ACCENT}")
                t.append(path, style="dim white")
                console.print(t)

        # ── Post-execution: shell result ──────────────────────────────────────
        elif tool_name == "shell_run":
            if result:
                stdout = (result.get("stdout") or "").strip()
                stderr = (result.get("stderr") or "").strip()
                exit_code = result.get("exit_code", 0)
                output = stdout or stderr

                t = Text()
                t.append("     ", style="")
                if exit_code == 0:
                    t.append("✓", style=f"bold {ACCENT}")
                    if output:
                        first = output.splitlines()[0][:80]
                        t.append(f"  {first}", style="dim")
                else:
                    t.append(f"exit {exit_code}", style="bold red")
                    if output:
                        first = output.splitlines()[0][:70]
                        t.append(f"  {first}", style="dim red")
                console.print(t)

                has_real_output = output and (exit_code != 0 or len(output.splitlines()) > 3)
                if has_real_output:
                    lines = output.splitlines()
                    if len(lines) > 20:
                        output = "\n".join(lines[:20]) + f"\n[dim]…({len(lines) - 20} lignes)[/dim]"
                    style = "red" if exit_code != 0 else "dim"
                    border = "red" if exit_code != 0 else f"dim {ACCENT}"
                    console.print(Panel(
                        f"[{style}]{output}[/{style}]",
                        border_style=border,
                        padding=(0, 2),
                    ))

        # ── Read-only exploration (compact one-liner) ────────────────────────
        elif tool_name in ("local_read_file", "local_grep", "local_glob",
                           "local_find_file", "local_list_directory", "shell_ls",
                           "shell_pwd", "url_fetch", "web_research_report",
                           "web_search_news", "git_status", "git_log", "git_diff"):
            label = (args or {}).get("path") or (args or {}).get("query") or (args or {}).get("pattern") or ""
            short = label[:60] + "…" if len(label) > 60 else label
            icon = {
                "local_read_file": "📖", "local_grep": "🔍", "local_glob": "🔍",
                "local_find_file": "🔍", "local_list_directory": "📂", "shell_ls": "📂",
                "web_research_report": "🌐", "web_search_news": "🌐", "url_fetch": "🌐",
                "git_status": "git", "git_log": "git", "git_diff": "git",
            }.get(tool_name, "·")
            t = Text()
            t.append(f"  {icon}  ", style=f"dim {ACCENT}")
            t.append(tool_name, style="dim")
            if short:
                t.append(f"  {short}", style="dim")
            console.print(t)

        # ── Plan events ───────────────────────────────────────────────────────
        elif tool_name in ("dev_plan_create", "dev_plan_step_done"):
            from src.agents.coding.pending import render_plan
            render_plan(console)

        # ── Explain / analyse ─────────────────────────────────────────────────
        elif tool_name == "dev_explain":
            message = args.get("message", "") if args else ""
            fingerprint = message[:120]
            if message and fingerprint != _last_explain:
                _last_explain = fingerprint
                from rich.markdown import Markdown
                console.print(Panel(
                    Markdown(message),
                    border_style=f"dim {ACCENT}",
                    title="[dim]analyse[/dim]",
                    title_align="left",
                    padding=(0, 2),
                ))

        # ── File change — HITL only stops/starts the live ────────────────────
        elif tool_name == "propose_file_change":
            _file_path = args.get("path", "") if args else ""
            _is_internal = ".axon/" in _file_path or _file_path.endswith("AXON.md")

            if get_mode() == "auto" or _is_internal:
                from src.agents.coding.pending import pending_changes as _pending, snapshots
                from src.infra.tools_cache import session_cache
                change = _pending.pop_latest()
                if change:
                    try:
                        p = Path(change.path)
                        p.parent.mkdir(parents=True, exist_ok=True)
                        snapshots.save(change.path, change.original)
                        p.write_text(change.proposed, encoding="utf-8")
                        session_cache.invalidate_filesystem()
                        t = Text()
                        t.append("  ✓  ", style="bold green")
                        t.append(str(p), style="dim")
                        console.print(t)
                        override = {
                            "status": "accepted",
                            "path": change.path,
                            "awaiting_confirmation": False,
                            "message": "Fichier écrit avec succès.",
                        }
                    except Exception as e:
                        console.print(Text(f"  ✗  {change.path}: {e}", style="red"))
                else:
                    # Store was empty (already popped by a previous call) — still confirm
                    override = {
                        "status": "accepted",
                        "path": _file_path,
                        "awaiting_confirmation": False,
                        "message": "Fichier déjà appliqué.",
                    }
            else:
                # HITL review needs full terminal — stop live during interaction only
                try:
                    live.update(Text(""))
                    live.stop()
                except Exception:
                    pass
                from .review import review_single_latest
                action, refinement = review_single_latest()
                if action == "apply":
                    override = {
                        "status": "accepted",
                        "path": args.get("path", ""),
                        "awaiting_confirmation": False,
                        "message": "Fichier écrit avec succès.",
                    }
                elif action == "reject":
                    override = {
                        "status": "rejected",
                        "path": args.get("path", ""),
                        "message": "L'utilisateur a refusé ce changement. N'écris pas ce fichier en l'état.",
                    }
                elif action == "refine" and refinement:
                    override = {
                        "status": "needs_refinement",
                        "path": args.get("path", ""),
                        "feedback": refinement,
                        "message": (
                            f"L'utilisateur demande des modifications : {refinement}. "
                            "Prends en compte ce feedback et rappelle propose_file_change avec le contenu corrigé."
                        ),
                    }
                try:
                    live.start(refresh=False)
                except Exception:
                    pass

        return override

    set_progress_callback(_coding_progress)
    set_compile_callback(_on_compile)

    try:
        live.start(refresh=False)
        response_content = ""
        saw_any_token = False
        plan_rendered = False          # have we already rendered an <axon:plan> block?
        last_node = ""
        last_debug_node = ""
        deb = {"DEBOUNCE": 0.03, "last_update": 0.0}
        t0 = perf_counter()

        t = threading.Thread(target=_make_thinking_loop(stop_thinking, live, compile_mode), daemon=True)
        t.start()
        _thinking_thread.append(t)

        for msg, meta in graph.stream(current_state, config=config, stream_mode="messages"):
            node = meta.get("langgraph_node") or "unknown"

            if cfg.debug and node != last_debug_node:
                console.print(f"[dim]→ {node}[/dim]")
                last_debug_node = node

            if isinstance(msg, ToolMessage):
                tool_name = getattr(msg, "name", None) or getattr(msg, "tool_name", None) or meta.get("tool", "tool")
                if tool_name == "gmail_send_email":
                    stop_thinking.set()
                    live.stop()
                    from .review import review_email
                    action, refinement = review_email()
                    if action == "send":
                        pending_refinements.append("Email envoyé avec succès.")
                    elif action == "cancel":
                        pending_refinements.append("Envoi annulé par l'utilisateur.")
                    elif action == "modify" and refinement:
                        pending_refinements.append(f"L'utilisateur veut modifier le mail : {refinement}")
                    live.start(refresh=False)
                elif tool_name in ("dev_plan_create", "dev_plan_step_done"):
                    stop_thinking.set()
                    response_content = ""
                    saw_any_token = False
                    live.update(Text(""))
                    live.stop()
                    from src.agents.coding.pending import render_plan
                    render_plan(console)
                    live.start(refresh=False)
                else:
                    live.update(tool_call_panel(tool_name))
                if cfg.debug:
                    live.console.print(Panel(
                        Pretty(msg.content),
                        title=f"[dim]{tool_name}[/dim]",
                        border_style="dim",
                    ))
                last_node = "tools"
                continue

            if isinstance(msg, (AIMessageChunk, AIMessage)):
                raw = msg.content or ""
                from src.infra.settings import settings
                if settings.llm_backend == "gemini" and isinstance(raw, list):
                    chunk_text = "".join(
                        p.get("text", "") if isinstance(p, dict) else str(p)
                        for p in raw
                    )
                else:
                    chunk_text = raw
                if not chunk_text:
                    continue
                if last_node == "tools":
                    response_content = ""
                    saw_any_token = False
                    plan_rendered = False
                    last_node = "chatbot"
                compile_mode.clear()  # back to normal after compilation
                stop_thinking.set()
                saw_any_token = True
                response_content += chunk_text

                _PLAN_OPEN  = "<axon:plan>"
                _PLAN_CLOSE = "</axon:plan>"

                if not plan_rendered:
                    if _PLAN_OPEN in response_content and _PLAN_CLOSE in response_content:
                        # Complete plan block — extract, render, strip from content
                        pre, rest = response_content.split(_PLAN_OPEN, 1)
                        steps, post = rest.split(_PLAN_CLOSE, 1)
                        plan_rendered = True
                        live.update(Text(""))
                        live.stop()
                        console.print(plan_panel(steps.strip()))
                        live.start(refresh=False)
                        response_content = (pre + post).strip()
                        if response_content:
                            update_live_markdown(live, response_content, deb, cursor=True)
                    elif _PLAN_OPEN in response_content:
                        # Partial plan still streaming — show any text before the tag
                        pre = response_content.split(_PLAN_OPEN, 1)[0].strip()
                        if pre:
                            update_live_markdown(live, pre, deb, cursor=False)
                    else:
                        update_live_markdown(live, response_content, deb, cursor=True)
                else:
                    update_live_markdown(live, response_content, deb, cursor=True)

        footer = fmt_ms(perf_counter() - t0)
        if saw_any_token:
            safe = _guard_sanitize(enforce_lang_output(response_content, user_lang))
            finalize_live(live, safe, footer)
        else:
            final_state = graph.invoke(current_state, config=config)
            last = final_state["messages"][-1]
            text = last["content"] if isinstance(last, dict) else getattr(last, "content", "")
            safe = _guard_sanitize(enforce_lang_output(text, user_lang))
            finalize_live(live, safe, footer)
        live.stop()

    except Exception as e:
        try:
            live.stop()
        except Exception:
            pass
        err_str = str(e)
        if ("RESOURCE_EXHAUSTED" in err_str or "generativelanguage.googleapis.com" in err_str
                or ("429" in err_str and "gemini" in err_str.lower())):
            import re as _re
            delay_match = _re.search(r"retry[^\d]*(\d+)", err_str, _re.IGNORECASE)
            wait_s = int(delay_match.group(1)) + 2 if delay_match else 15
            t = Text()
            t.append("  ⏳  ", style=f"bold {ACCENT}")
            t.append(f"quota Gemini atteint — retry dans {wait_s}s…", style="dim")
            console.print(t)
            import time as _time
            _time.sleep(wait_s)
            # Retry once after waiting
            try:
                live2 = Live(live_panel_initial(), console=console, refresh_per_second=_REFRESH_RATE, vertical_overflow="crop")
                live2.start(refresh=False)
                stop2 = threading.Event()
                threading.Thread(target=_make_thinking_loop(stop2, live2), daemon=True).start()
                rc2 = ""
                saw2 = False
                for msg2, meta2 in graph.stream(current_state, config=config, stream_mode="messages"):
                    if isinstance(msg2, (AIMessageChunk, AIMessage)):
                        chunk2 = msg2.content or ""
                        if isinstance(chunk2, list):
                            chunk2 = "".join(p.get("text","") if isinstance(p,dict) else str(p) for p in chunk2)
                        if chunk2:
                            stop2.set(); saw2 = True; rc2 += chunk2
                            update_live_markdown(live2, rc2, {"DEBOUNCE":_DEBOUNCE,"last_update":0.0}, cursor=True)
                stop2.set()
                if saw2:
                    finalize_live(live2, _guard_sanitize(enforce_lang_output(rc2, user_lang)), "retry")
                live2.stop()
            except Exception:
                live2.stop()
                console.print(command_panel("Quota toujours atteint — réessaie dans une minute.", error=True))
        elif "503" in err_str or "UNAVAILABLE" in err_str or "high demand" in err_str.lower():
            console.print(command_panel("Gemini est surchargé, réessaie dans quelques secondes.", error=True))
        elif "image" in err_str.lower() and any(
            kw in err_str.lower() for kw in ("not support", "no support", "doesn't support", "multimodal", "vision")
        ):
            # Strip image blobs from ALL checkpointed messages so they don't cascade
            try:
                from langchain_core.messages import HumanMessage as _HM
                snap = graph.get_state(config)
                if snap and snap.values:
                    msgs = snap.values.get("messages", [])
                    patched = []
                    changed = False
                    for m in msgs:
                        if hasattr(m, "content") and isinstance(m.content, list):
                            text_parts = [
                                p.get("text", "")
                                for p in m.content
                                if isinstance(p, dict) and p.get("type") == "text"
                            ]
                            new_content = " ".join(text_parts).strip()
                            patched.append(_HM(content=new_content or "[message supprimé — images non supportées]", id=getattr(m, "id", None)))
                            changed = True
                        else:
                            patched.append(m)
                    if changed:
                        graph.update_state(config, {"messages": patched})
            except Exception:
                pass
            console.print(command_panel(
                "Ce modèle ne supporte pas les images — utilise /new pour repartir sur un thread propre.",
                error=True,
            ))
        else:
            console.print(command_panel(f"erreur : {e}", error=True))
    finally:
        set_progress_callback(None)
        set_compile_callback(None)

    # ── Post-stream: prune stale messages if compression happened ────────────
    _prune_after_compression(graph, config)

    # ── Post-stream: write files or ask ───────────────────────────────────────
    from src.agents.coding.pending import pending_changes
    if pending_changes:
        if get_mode() == "auto":
            from .review import auto_write_all
            auto_write_all(console)
        else:
            # Fallback: batch review for any remaining (edge cases)
            while pending_changes:
                from .review import review_pending
                action, refinement = review_pending()
                if action == "refine" and refinement:
                    pending_refinements.append(refinement)
                else:
                    break

    for refinement in pending_refinements:
        _stream_message(graph, refinement, cfg)
