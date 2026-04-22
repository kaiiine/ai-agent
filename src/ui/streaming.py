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


def _make_thinking_loop(stop_event: threading.Event, live: "Live"):
    """Retourne une fonction de loop d'animation 'thinking' pour un thread daemon."""
    def _loop():
        i = 0
        while not stop_event.is_set():
            try:
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
    "plan-badge": "bold bg:#1a0d00 #ff8700",
    # Completion dropdown — dark, minimal, orange accent on selection
    "completion-menu":                         "bg:#1a1a1a #606060",
    "completion-menu.completion":              "bg:#1a1a1a #606060",
    "completion-menu.completion.current":      "bg:#242424 bold #ff8700",
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
        event.current_buffer.text = "/paste"
        event.current_buffer.validate_and_handle()

    @kb.add("c-t")
    def _kb_plan(event):
        from .plan_mode import toggle
        toggle()
        event.app.invalidate()

    return kb


def _prompt_tokens():
    """Dynamic prompt: shows PLAN badge when plan mode is active."""
    from .plan_mode import is_active
    if is_active():
        return [("class:plan-badge", " PLAN "), ("", "  ")]
    return [("class:sep", "› ")]


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
        _tool_list = [t.strip() for t in get_tool_names().split(",") if t.strip()]
        _prompt_preview = build_system_prompt(_tool_list, str(date.today()), _user_name)[:300]
        parts = [f"[dim]system:[/dim] {_prompt_preview}..."]
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

    Tries exact path first, then fuzzy match on git-tracked files.
    Files larger than _AT_MAX_CHARS are truncated with a notice.
    """
    mentions = _AT_RE.findall(text)
    if not mentions:
        return text

    for mention in mentions:
        p = Path(mention)
        if not (p.exists() and p.is_file()):
            # Fuzzy: find matching git-tracked files
            try:
                r = subprocess.run(
                    ["git", "ls-files"],
                    capture_output=True, text=True, timeout=5,
                )
                files = r.stdout.strip().splitlines()
                ml = mention.lower()
                matches = [f for f in files if ml in f.lower()]
                if matches:
                    p = Path(matches[0])
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


def stream_once(graph, state: dict, cfg: SessionConfig) -> None:
    console.print(_separator_rule())

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

        if user_message == "/letter":
            _handle_lettre(graph, state, cfg)
            return

        if user_message == "/upgrade":
            _handle_ameliore(graph, state, cfg)
            return

        from .commands import handle_slash
        result = handle_slash(user_message, state, cfg, graph, console)
        if result:
            console.print(result)
        return

    # ── Résolution des @mentions (injection fichiers) ─────────────────────────
    user_message = _resolve_at_mentions(user_message)

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

    # Forcer la langue si /lang a été défini (injecte un system message éphémère)
    if cfg.lang_pref in {"fr", "en"}:
        from .language import enforce_lang_ephemeral_system
        enforce_lang_ephemeral_system(current_state, cfg.lang_pref)
    config = {"configurable": {"thread_id": cfg.thread_id}}

    if cfg.debug:
        _debug_prompt(state, graph, cfg)

    from src.ui.edit_mode import get_mode
    from src.agents.coding.specialist import set_progress_callback
    from src.orchestrator.graph import set_compile_callback

    pending_refinements: list[str] = []
    stop_thinking = threading.Event()

    live = Live(live_panel_initial(), console=console, refresh_per_second=_REFRESH_RATE, vertical_overflow="crop")

    def _on_compile() -> None:
        """Called by graph.py when context compression starts."""
        stop_thinking.set()
        live.update(compile_panel())

    def _coding_progress(tool_name: str, args: dict):
        """Called by the coding specialist for plan/file events — updates the terminal in real time.

        Returns a dict to override the ToolMessage content sent back to the specialist LLM,
        or None to keep the original tool result unchanged.
        This is the mechanism for feeding HITL decisions back to the specialist.
        """
        stop_thinking.set()
        try:
            live.update(Text(""))
            live.stop()
        except Exception:
            pass
        nonlocal response_content, saw_any_token
        response_content = ""
        saw_any_token = False

        override = None

        if tool_name in ("dev_plan_create", "dev_plan_step_done"):
            from src.agents.coding.pending import render_plan
            render_plan(console)
        elif tool_name == "dev_explain":
            message = args.get("message", "") if args else ""
            if message:
                from rich.markdown import Markdown
                console.print(Panel(
                    Markdown(message),
                    border_style=f"dim {ACCENT}",
                    title="[dim]analyse[/dim]",
                    title_align="left",
                    padding=(0, 2),
                ))
        elif tool_name == "propose_file_change" and get_mode() == "ask":
            from .review import review_single_latest
            action, refinement = review_single_latest()
            if action == "reject":
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
            # action == "apply" → override stays None, original result kept

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

        t = threading.Thread(target=_make_thinking_loop(stop_thinking, live), daemon=True)
        t.start()

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
                elif tool_name == "propose_file_change" and get_mode() == "ask":
                    stop_thinking.set()
                    live.stop()
                    from .review import review_single_latest
                    action, refinement = review_single_latest()
                    if action == "refine" and refinement:
                        pending_refinements.append(refinement)
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

            if isinstance(msg, AIMessageChunk):
                chunk_text = msg.content or ""
                if not chunk_text:
                    continue
                if last_node == "tools":
                    response_content = ""
                    saw_any_token = False
                    plan_rendered = False
                    last_node = "chatbot"
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

            elif isinstance(msg, AIMessage) and not saw_any_token:
                chunk_text = msg.content or ""
                if not chunk_text:
                    continue
                if last_node == "tools":
                    response_content = ""
                    plan_rendered = False
                    last_node = "chatbot"
                stop_thinking.set()
                saw_any_token = True
                response_content = chunk_text
                update_live_markdown(live, response_content, deb, cursor=False)

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
        console.print(command_panel(f"erreur : {e}", error=True))
    finally:
        set_progress_callback(None)
        set_compile_callback(None)

    # ── Post-stream: write files or ask ───────────────────────────────────────
    from src.agents.coding.pending import pending_changes
    if pending_changes:
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
