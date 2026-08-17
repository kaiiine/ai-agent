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
from prompt_toolkit.filters import Condition
from prompt_toolkit.history import FileHistory, InMemoryHistory
from prompt_toolkit.styles import Style
from prompt_toolkit.key_binding import KeyBindings


from .config import fmt_ms, SessionConfig
from .language import detect_lang, enforce_lang_output
from .panels import live_panel_initial, tool_call_panel, command_panel, plan_panel, compile_panel, ACCENT, _BOX
from .render import update_live_markdown, finalize_live
from .commands import debug_state
from .attachments import AttachmentStore, open_file_picker, get_clipboard_image, build_message_with_attachments
from .completer import SlashCompleter
from .suggest import HistorySuggest

console = Console()
_attachments = AttachmentStore()
_BORDER = f"dim {ACCENT}"

_DEBOUNCE = 0.03
_REFRESH_RATE = 20
_THINKING_WAIT = 0.4
_ARRET_ANIMATION = 1.0

#: Nom du nœud d'outils de l'orchestrateur (`build_orchestrator`).
#:
#: Sortir du générateur `graph.stream()` pour afficher le questionnaire ABANDONNE
#: le run : le superstep `tools` est bien commité, mais le suivant n'est jamais
#: planifié — `get_state().next` vaut `()`. Une reprise avec `None` ne fait alors
#: RIEN, en silence. `update_state(..., as_node="tools")` réinscrit la mise à jour
#: comme venant de ce nœud, ce qui replanifie `chatbot` et rend la reprise réelle.
#:
#: Un renommage du nœud casserait la reprise sans erreur ; le test
#: `test_le_noeud_outils_de_l_ui_existe_dans_l_orchestrateur` l'attrape.
_NOEUD_OUTILS = "tools"


def _safe_stop(live, stop_event: threading.Event | None = None,
               thread: threading.Thread | None = None) -> None:
    """Clear the live panel then stop it — prevents committing the thinking frame to stdout."""
    if stop_event is not None:
        stop_event.set()
    if thread is not None:
        thread.join(timeout=_ARRET_ANIMATION)
    try:
        live.update(Text(""))
    except Exception:
        pass
    try:
        live.stop()
    except Exception:
        pass


def _make_thinking_loop(stop_event: threading.Event, live: "Live",
                        compile_mode: threading.Event | None = None,
                        activity: dict | None = None):
    """Retourne une fonction de loop d'animation pour un thread daemon.
    Si compile_mode est set, affiche le panel de compilation plutôt que thinking.
    `activity` est relu à chaque frame — le label change sans relancer le thread."""
    def _loop():
        i = 0
        while not stop_event.is_set():
            try:
                if compile_mode and compile_mode.is_set():
                    live.update(compile_panel(i % 4))
                else:
                    label = (activity or {}).get("label") or "thinking"
                    live.update(live_panel_initial(i % 4, label))
            except Exception:
                pass
            i += 1
            stop_event.wait(_THINKING_WAIT)
        # Effacer sa propre frame : sinon l'arrêt du Live la grave.
        try:
            live.update(Text(""))
        except Exception:
            pass
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
    # Suggestion de saisie — délibérément plus sombre que tout le reste : elle
    # doit se lire comme une ombre, jamais se confondre avec ce qui est tapé.
    "auto-suggestion":                         "#4a4a4a",
})


@Condition
def _suggestion_affichee() -> bool:
    """Une suggestion est-elle visible et acceptable à cet instant ?

    Filtre de la liaison Tab. Quand il rend faux, prompt_toolkit retombe sur la
    liaison par défaut — Tab redevient la complétion du menu. C'est ce qui permet
    aux deux mécanismes de partager la touche sans se marcher dessus : le menu
    garde `/commande` et `@fichier`, la suggestion prend le reste.
    """
    from prompt_toolkit.application import get_app

    try:
        buf = get_app().current_buffer
    except Exception:
        return False
    return (buf.suggestion is not None
            and bool(buf.suggestion.text)
            and buf.complete_state is None
            and buf.document.is_cursor_at_the_end)


def _make_keybindings() -> KeyBindings:
    kb = KeyBindings()

    @kb.add("tab", filter=_suggestion_affichee)
    def _kb_accepter_suggestion(event):
        """Tab écrit la suggestion — le seul geste qui l'insère jamais."""
        buf = event.current_buffer
        if buf.suggestion:
            buf.insert_text(buf.suggestion.text)

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

    # ── Saisie multi-ligne ────────────────────────────────────────────────────
    #
    # La session passe en `multiline=True`, ce qui INVERSE le rôle d'Entrée :
    # par défaut elle insérerait un retour à la ligne et plus rien n'enverrait.
    # Ces deux liaisons rétablissent le geste attendu — Entrée envoie, une autre
    # touche va à la ligne.
    #
    # Plusieurs touches pour aller à la ligne, et ce n'est pas de la générosité.
    #
    # prompt_toolkit 3.0.52 NE CONNAÎT PAS Maj+Entrée : `enter` est un alias de
    # `c-m`, et l'énumération des touches n'a aucune variante shift pour elle —
    # vérifié, `s-tab` et `s-left` existent, rien pour entrée. La raison est en
    # amont : la plupart des terminaux envoient le même octet `\r` pour Entrée et
    # Maj+Entrée, donc il n'y a rien à distinguer.
    #
    # Deux réponses, complémentaires :
    #   · Alt+Entrée et Ctrl+J, que TOUT terminal émet distinctement — ce sont
    #     elles qui garantissent que la fonctionnalité marche partout ;
    #   · la séquence du protocole clavier kitty (`ESC [ 13 ; 2 u`), qu'émettent
    #     kitty, ghostty, WezTerm et foot quand le protocole est actif. Là où
    #     c'est le cas, Maj+Entrée marche vraiment ; ailleurs la séquence
    #     n'arrive jamais et la liaison dort sans gêner personne.

    @kb.add("enter")
    def _kb_envoyer(event):
        """Entrée envoie, toujours.

        Une version précédente validait d'abord la complétion ouverte, en croyant
        éviter qu'Entrée n'envoie au lieu d'insérer `/build`. C'était faux et
        mesuré comme tel : dans prompt_toolkit, Tab INSÈRE déjà la complétion
        dans le tampon tout en laissant `current_completion` renseigné. La
        condition ne distinguait donc pas « en attente » de « déjà écrite »,
        Entrée réappliquait la complétion, et la saisie ne se terminait jamais —
        deux tests de complétion restaient bloqués indéfiniment.
        """
        event.current_buffer.validate_and_handle()

    @kb.add("escape", "enter")
    @kb.add("c-j")
    @kb.add("escape", "[", "1", "3", ";", "2", "u")
    def _kb_nouvelle_ligne(event):
        """Alt+Entrée · Ctrl+J · Maj+Entrée (terminaux au protocole kitty)."""
        event.current_buffer.insert_text("\n")

    return kb


def _continuation(largeur: int, ligne: int, doit_envelopper: bool):
    """Le préfixe des lignes 2 et suivantes d'une saisie multi-ligne.

    Aligné sur le « › » de la première ligne : sans lui, prompt_toolkit met des
    points de suite qui ne ressemblent à rien de la DA, et le texte se décale
    d'une colonne à chaque nouvelle ligne.
    """
    from prompt_toolkit.formatted_text import ANSI

    return ANSI("\033[2m\033[38;5;214m│ \033[0m")


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


def _historique():
    """Historique de saisie, persistant entre les sessions.

    Une suggestion tirée d'un historique en mémoire ne servirait à rien : elle
    n'existerait qu'après avoir déjà retapé la phrase dans la MÊME session. Le
    fichier vit dans `~/.axon/`, avec la base de threads — il contient donc tout
    ce qui a été saisi, en clair, et se supprime sans conséquence.

    Un disque en lecture seule ou un `$HOME` absent retombe en mémoire : la
    saisie doit démarrer même sans persistance.
    """
    try:
        chemin = Path.home() / ".axon" / "input_history"
        chemin.parent.mkdir(parents=True, exist_ok=True)
        return FileHistory(str(chemin))
    except Exception:
        return InMemoryHistory()


def build_session(**overrides) -> PromptSession:
    """Fabrique la session de saisie — un seul endroit la configure.

    Les `overrides` servent aux tests, qui rejouent des frappes sur une session
    identique à celle du produit avec une entrée/sortie factice. Sans cette
    fabrique, la liaison Tab ne serait vérifiable que manuellement.
    """
    options = dict(
        history=_historique(),
        style=_pt_style,
        mouse_support=False,
        key_bindings=_make_keybindings(),
        completer=SlashCompleter(),
        complete_while_typing=True,
        auto_suggest=HistorySuggest(),
        # Le tampon accepte les retours à la ligne ; ce sont les liaisons de
        # `_make_keybindings` qui décident quelle touche envoie et laquelle va à
        # la ligne. Sans `multiline`, aucune touche ne peut insérer de retour.
        multiline=True,
        prompt_continuation=_continuation,
    )
    options.update(overrides)
    return PromptSession(**options)


_session: PromptSession = build_session()


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
    from src.orchestrator.graph import get_lang_pref
    from src.llm.prompts import _LANG_INSTRUCTIONS
    lang_instruction = _LANG_INSTRUCTIONS.get(get_lang_pref(), _LANG_INSTRUCTIONS["fr"])
    from src.ui.templates import charger as _charger_template
    prompt = _charger_template("fiche", content=content[:60_000],
                               lang=lang_instruction)
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
    from src.orchestrator.graph import get_lang_pref
    from src.llm.prompts import _LANG_INSTRUCTIONS
    lang_instruction = _LANG_INSTRUCTIONS.get(get_lang_pref(), _LANG_INSTRUCTIONS["fr"])
    from src.ui.templates import charger as _charger_template
    prompt = _charger_template("exo", content=content[:60_000],
                               lang=lang_instruction, type_exo=type_exo)
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

    Appelle le LLM directement (pas via le graph) pour éviter le overhead du
    system prompt + tools descriptions qui ferait exploser le contexte. La
    contrepartie est que ce chemin n'hérite d'aucune reprise : d'où la rotation
    de clés explicite ci-dessous.
    """
    from langchain_core.messages import HumanMessage
    from src.infra.settings import settings
    from src.llm.models import make_orchestrator_llm_with_key
    from src.llm.rotation import clients, marquer_echec, vaut_la_peine_de_reessayer

    if attachments:
        from .attachments import build_message_with_attachments
        msg_dict = build_message_with_attachments(prompt_text, attachments)
        human_msg = HumanMessage(content=msg_dict["content"])
    else:
        human_msg = HumanMessage(content=prompt_text)

    def _un_essai(llm) -> str:
        """Un stream complet avec son panneau. Lève si le fournisseur refuse."""
        stop_thinking = threading.Event()
        texte = ""
        with Live(live_panel_initial(), console=console,
                  refresh_per_second=_REFRESH_RATE, vertical_overflow="crop") as live:
            saw_any_token = False
            deb = {"DEBOUNCE": _DEBOUNCE, "last_update": 0.0}
            t0 = perf_counter()
            fil = threading.Thread(target=_make_thinking_loop(stop_thinking, live),
                                   daemon=True)
            fil.start()
            try:
                for chunk in llm.stream([human_msg]):
                    chunk_text = chunk.content or "" if hasattr(chunk, "content") else str(chunk)
                    if not chunk_text:
                        continue
                    stop_thinking.set()
                    saw_any_token = True
                    texte += chunk_text
                    update_live_markdown(live, texte, deb, cursor=True)
            finally:
                stop_thinking.set()
            if saw_any_token:
                finalize_live(live, texte, fmt_ms(perf_counter() - t0), console=console)
        return texte

    def _annonce(fournisseur: str, cle: str) -> None:
        console.print(Text(f"  🔑 {fournisseur} — clé suivante ({cle[:10]}…)",
                           style=f"dim {ACCENT}"))

    derniere: Exception | None = None
    for fournisseur, cle, llm in clients(settings.llm_backend,
                                         make_orchestrator_llm_with_key,
                                         notifier=_annonce):
        try:
            return _un_essai(llm)
        except Exception as exc:   # noqa: BLE001 — on essaie la clé suivante
            derniere = exc
            marquer_echec(fournisseur, cle, exc)
            if not vaut_la_peine_de_reessayer(exc):
                break

    if derniere is not None:
        console.print(command_panel(f"erreur : {derniere}", error=True))
    return ""

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
    from src.infra.settings import settings

    current_state = {"messages": [HumanMessage(content=text)]}
    config = {"configurable": {"thread_id": cfg.thread_id}}

    stop_thinking = threading.Event()
    pending_refinements_inner: list[str] = []
    # Un skill chargé reste en contexte jusqu'à la fin du tour : le label le
    # reflète jusque-là, et se réinitialise au tour suivant.
    activity: dict = {"label": "thinking"}

    try:
        with Live(live_panel_initial(), console=console, refresh_per_second=_REFRESH_RATE, vertical_overflow="crop") as live:
            response_content = ""
            saw_any_token = False
            last_node = ""
            deb = {"DEBOUNCE": _DEBOUNCE, "last_update": 0.0}
            t0 = perf_counter()

            t = threading.Thread(
                target=_make_thinking_loop(stop_thinking, live, activity=activity), daemon=True)
            t.start()

            for msg, meta in graph.stream(current_state, config=config, stream_mode="messages"):
                node = meta.get("langgraph_node") or "unknown"
                if isinstance(msg, ToolMessage):
                    tool_name = getattr(msg, "name", None) or getattr(msg, "tool_name", None) or meta.get("tool", "tool")
                    if tool_name == "gmail_send_email":
                        _safe_stop(live, stop_thinking, t)
                        from .review import review_email
                        action, refinement = review_email()
                        if action == "send":
                            pending_refinements_inner.append("Email envoyé avec succès.")
                        elif action == "cancel":
                            pending_refinements_inner.append("Envoi annulé par l'utilisateur.")
                        elif action == "modify" and refinement:
                            pending_refinements_inner.append(f"L'utilisateur veut modifier le mail : {refinement}")
                        live.start(refresh=False)
                    elif tool_name == "dev_plan_step_done":
                        stop_thinking.set()
                        live.update(Text(""))
                        live.stop()
                        from src.agents.coding.pending import render_plan
                        render_plan(console)
                        stop_thinking.clear()
                        live.start(refresh=False)
                        new_t = threading.Thread(
                            target=_make_thinking_loop(stop_thinking, live, activity=activity),
                            daemon=True
                        )
                        new_t.start()
                        t = new_t
                        last_node = "tools"
                    else:
                        live.update(tool_call_panel(tool_name))
                    if tool_name == "load_skill" and activity.get("skill"):
                        activity["label"] = f"thinking · {activity['skill']}"
                    last_node = "tools"
                    continue
                if isinstance(msg, AIMessageChunk):
                    _raw = msg.content or ""
                    # Gemini returns content as list-of-parts — extract text
                    if isinstance(_raw, list):
                        chunk_text = "".join(
                            p.get("text", "") if isinstance(p, dict) else str(p)
                            for p in _raw
                        )
                    else:
                        chunk_text = _raw
                    if not chunk_text:
                        tool_calls = getattr(msg, "tool_calls", None) or []
                        for tc in tool_calls:
                            name = tc.get("name") or ""
                            if name == "run_coding_agent":
                                live.update(tool_call_panel("run_coding_agent"))
                            elif name == "load_skill":
                                # Args streamés par morceaux : on retient la dernière
                                # valeur vue, promue en label au retour du ToolMessage.
                                skill = (tc.get("args") or {}).get("stack")
                                if skill:
                                    activity["skill"] = str(skill)
                        continue
                    if last_node == "tools":
                        response_content = ""
                        saw_any_token = False
                        last_node = "chatbot"
                    stop_thinking.set()
                    saw_any_token = True
                    if settings.llm_backend == "gemini" and response_content and chunk_text.startswith(response_content):
                        chunk_text = chunk_text[len(response_content):]
                    response_content += chunk_text
                    update_live_markdown(live, response_content, deb, cursor=True)
                elif isinstance(msg, AIMessage) and not saw_any_token:
                    _raw = msg.content or ""
                    if isinstance(_raw, list):
                        chunk_text = "".join(
                            p.get("text", "") if isinstance(p, dict) else str(p)
                            for p in _raw
                        )
                    else:
                        chunk_text = _raw
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
                finalize_live(live, response_content, footer, console=console)
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


def _dernier_texte_du_modele(messages: list) -> str:
    """Le dernier texte RÉDIGÉ par le modèle, en remontant la conversation.

    Prendre `messages[-1]` aveuglément affichait le dernier message quel qu'il
    soit. Après un questionnaire, ce message est le résultat d'outil qui porte les
    réponses : l'utilisateur voyait `{"answers": {"Bankroll ?": "20"}}` à la place
    d'une réponse. Un résultat d'outil n'est jamais une réponse — il en est la
    matière première.

    La remontée S'ARRÊTE au message de l'utilisateur : au-delà commence le tour
    précédent, et en ressortir une vieille réponse serait pire que n'en afficher
    aucune — elle passerait pour la réponse d'aujourd'hui.
    """
    for m in reversed(messages or []):
        if isinstance(m, dict):
            role = m.get("type") or m.get("role") or ""
            contenu = m.get("content", "")
        else:
            role = getattr(m, "type", "") or ""
            contenu = getattr(m, "content", "")
        # `type` pour les objets LangChain, `role` pour les messages en dict :
        # les deux vocabulaires coexistent dans l'état.
        if role in ("human", "user"):
            break
        if role in ("tool", "system"):
            continue
        if isinstance(contenu, list):   # gemini : liste de blocs
            contenu = "".join(p.get("text", "") if isinstance(p, dict) else str(p)
                              for p in contenu)
        if isinstance(contenu, str) and contenu.strip():
            return contenu
    return ""


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

        if user_message.startswith("/spec"):
            from src.ui.spec import run_spec_wizard
            parts = user_message.split(maxsplit=1)
            initial = parts[1].strip() if len(parts) > 1 else ""
            run_spec_wizard(initial, console)
            return

        if user_message.startswith("/build"):
            from src.agents.coding.build_runner import run_build
            parts = user_message.split(maxsplit=1)
            if len(parts) < 2 or not parts[1].strip():
                console.print(command_panel("usage : /build <nom-du-projet>", error=True))
                return
            run_build(parts[1].strip(), console)
            return
        
        if user_message == "cron" or user_message.startswith("/cron"):
            from src.agents.cron.store import get_tasks, get_logs, deactivate_task
            from rich.table import Table
            from rich import box as rbox

            parts = user_message.split(maxsplit=2)
            sub = parts[1] if len(parts) > 1 else ""

            if sub == "stop" and len(parts) > 2:
                ok = deactivate_task(parts[2].strip())
                console.print(command_panel(
                    f"tâche {parts[2].strip()} désactivée" if ok else "ID introuvable",
                    error=not ok,
                ))

            elif sub == "log" and len(parts) > 2:
                logs = get_logs(parts[2].strip(), nb=10)
                if not logs:
                    console.print(command_panel("aucun log pour cette tâche"))
                else:
                    tbl = Table(box=rbox.SIMPLE_HEAD, padding=(0, 1))
                    tbl.add_column("Date", style="dim", no_wrap=True)
                    tbl.add_column("Status", no_wrap=True)
                    tbl.add_column("Notifié", no_wrap=True)
                    tbl.add_column("Message", style="dim")
                    for entry in logs:
                        s = entry["status"]
                        style = "green" if s == "ok" else "red" if s == "error" else "dim"
                        tbl.add_row(
                            entry["ts"][:16],
                            f"[{style}]{s}[/{style}]",
                            "✓" if entry.get("notified") else "—",
                            (entry.get("message") or entry.get("result_summary") or "")[:60],
                        )
                    console.print(tbl)

            else:  # /cron sans argument → liste
                tasks = get_tasks(active_only=True)
                if not tasks:
                    console.print(command_panel("aucune tâche planifiée active"))
                else:
                    tbl = Table(box=rbox.SIMPLE_HEAD, padding=(0, 1))
                    tbl.add_column("ID", style=f"dim {ACCENT}", no_wrap=True)
                    tbl.add_column("Description")
                    tbl.add_column("Fréquence", style="dim")
                    tbl.add_column("Dernier run", style="dim")
                    for t in tasks:
                        freq = f"{t['interval_sec'] // 60} min" if not t.get("run_at") else t["run_at"][:16]
                        tbl.add_row(
                            t["id"],
                            t["description"],
                            freq,
                            (t.get("last_run") or "jamais")[:16],
                        )
                    console.print(tbl)
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
    live = Live(live_panel_initial(), console=console, refresh_per_second=_REFRESH_RATE, vertical_overflow="crop")

    def _on_compile() -> None:
        """Switch the existing thinking thread to compile animation — no new thread."""
        compile_mode.set()

    def _coding_progress(tool_name: str, args: dict, result: dict | None = None):
        """Called by the coding specialist for plan/file/shell events."""
        nonlocal response_content, saw_any_token
        response_content = ""
        saw_any_token = False
        override = None

        # Stop thinking animation before any output
        stop_thinking.set()
        if _thinking_thread:
            _thinking_thread[0].join(timeout=_ARRET_ANIMATION)
        try:
            live.update(Text(""))
        except Exception:
            pass

        def _resume_thinking():
            stop_thinking.clear()
            new_t = threading.Thread(
                target=_make_thinking_loop(stop_thinking, live, compile_mode), daemon=True
            )
            new_t.start()
            if _thinking_thread:
                _thinking_thread[0] = new_t
            elif _thinking_thread is not None:
                _thinking_thread.append(new_t)

        # ── Specialist start → show model + stacks ────────────────────────────
        if tool_name == "specialist:start":
            model = (args or {}).get("model", "?")
            t = Text()
            t.append("  ⚙ ", style=f"bold {ACCENT}")
            t.append("Agent code : ", style="dim white")
            t.append(model, style=f"bold {ACCENT}")
            console.print(t)
            _resume_thinking()
            return None

        # ── load_skill → show detected stack ─────────────────────────────────
        if tool_name == "load_skill":
            stack = (args or {}).get("stack", "")
            if stack:
                t = Text()
                t.append("  ◈ ", style=f"bold {ACCENT}")
                t.append("Stack détecté : ", style="dim white")
                t.append(stack, style=f"bold {ACCENT}")
                console.print(t)
            _resume_thinking()
            return None

        # ── Context compression → compile animation ───────────────────────────
        if tool_name == "specialist:compress":
            compile_mode.set()
            _resume_thinking()
            return None

        # ── Rotation de clé / bascule de fournisseur ─────────────────────────
        # Émis par le specialist et affichés nulle part jusqu'ici.
        if tool_name == "specialist:key_rotate":
            t = Text()
            t.append("  🔑 ", style=f"bold {ACCENT}")
            raison = (args or {}).get("raison", "quota atteint")
            t.append(f"{(args or {}).get('provider', '?')} — {raison}, "
                     f"clé suivante ({(args or {}).get('key', '')})", style="dim white")
            console.print(t)
            _resume_thinking()
            return None

        if tool_name == "specialist:backend_switch":
            depuis = (args or {}).get("from", "?")
            vers = (args or {}).get("to", "?")
            t = Text()
            t.append("  ⇄  ", style="bold yellow")
            t.append(f"{depuis} épuisé — bascule sur ", style="dim white")
            t.append(vers, style=f"bold {ACCENT}")
            t.append("  (le backend courant devient celui-ci)", style="dim")
            console.print(t)
            _resume_thinking()
            return None

        # ── Shell command preview (before execution) ──────────────────────────
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

        # ── Shell result (after execution) ────────────────────────────────────
        elif tool_name == "shell_run":
            if result:
                stdout = (result.get("stdout") or "").strip()
                stderr = (result.get("stderr") or "").strip()
                exit_code = result.get("exit_code", 0)
                output = stdout or stderr

                t = Text()
                t.append("     ")
                if exit_code == 0:
                    t.append("✓", style=f"bold {ACCENT}")
                    if output:
                        t.append(f"  {output.splitlines()[0][:80]}", style="dim")
                else:
                    t.append(f"exit {exit_code}", style="bold red")
                    if output:
                        t.append(f"  {output.splitlines()[0][:70]}", style="dim red")
                console.print(t)

                has_real_output = output and (exit_code != 0 or len(output.splitlines()) > 3)
                if has_real_output:
                    lines = output.splitlines()
                    if len(lines) > 20:
                        output = "\n".join(lines[:20]) + f"\n[dim]…({len(lines) - 20} lignes)[/dim]"
                    style = "red" if exit_code != 0 else "dim"
                    border = "red" if exit_code != 0 else f"dim {ACCENT}"
                    console.print(Panel(f"[{style}]{output}[/{style}]", border_style=border, padding=(0, 2)))

        # ── Read-only exploration (compact one-liner) ─────────────────────────
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
            t.append(short or tool_name, style="dim")
            console.print(t)

        # ── Plan ──────────────────────────────────────────────────────────────
        elif tool_name in ("dev_plan_step_done", "dev_plan_update"):
            if tool_name == "dev_plan_update":
                raison = (args or {}).get("reason", "")
                t = Text()
                t.append("  ↻  ", style=f"bold {ACCENT}")
                t.append("plan révisé", style="dim white")
                if raison:
                    t.append(f" — {raison[:90]}", style="dim")
                console.print(t)
            from src.agents.coding.pending import render_plan
            render_plan(console)

        # ── Explain / analyse ─────────────────────────────────────────────────
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

        # ── Question à l'utilisateur, SANS quitter le run ─────────────────────
        # Même canal que la revue de fichier : on bloque, on interroge, on rend
        # les réponses à la boucle. Une question en texte libre terminait le run.
        elif tool_name == "ask_clarification":
            # Le terminal se bloque ici : c'est ici que le format doit être prouvé.
            from src.agents.coding.tools import normaliser_questions
            try:
                _questions = normaliser_questions((args or {}).get("questions"))
            except ValueError as _err:
                return {"status": "error", "reason": str(_err)}
            # Libérer le terminal : le Live de Rich capterait le clavier.
            try:
                live.update(Text(""))
                live.stop()
            except Exception:
                pass
            from .review import ask_user_questions
            try:
                _answers = ask_user_questions(_questions)
            except (KeyboardInterrupt, EOFError):
                _answers = {}
            except Exception as _qe:
                console.print(Text(f"  erreur questionnaire : {_qe}", style="red"))
                _answers = {}
            try:
                live.start(refresh=False)
            except Exception:
                pass
            _resume_thinking()
            if not _answers:
                return {"status": "no_answer",
                        "message": ("L'utilisateur n'a pas répondu. Choisis l'option la plus "
                                    "raisonnable, signale-la dans dev_explain, et CONTINUE "
                                    "le plan — ne repose pas la question.")}
            return {
                "status": "answered",
                "answers": _answers,
                "message": ("Réponses obtenues. Applique-les MAINTENANT et poursuis le plan "
                            "en cours — ne repose pas ces questions, ne recommence rien."),
            }

        # ── File change (HITL) ────────────────────────────────────────────────
        elif tool_name in ("propose_file_change", "edit_file"):
            # Sans proposition déposée, la revue trouverait la pile vide et
            # fabriquerait un refus que l'utilisateur n'a jamais donné.
            if isinstance(result, dict) and result.get("status") == "error":
                return None
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
                    override = {
                        "status": "accepted",
                        "path": _file_path,
                        "awaiting_confirmation": False,
                        "message": "Fichier déjà appliqué.",
                    }
            else:
                # HITL review — temporarily stop Live to free the terminal
                try:
                    live.update(Text(""))
                    live.stop()
                except Exception:
                    pass
                from .review import review_single_latest
                action, refinement = review_single_latest()
                # Resume Live after review
                stop_thinking.clear()
                try:
                    live.start(refresh=False)
                except Exception:
                    pass
                new_t = threading.Thread(
                    target=_make_thinking_loop(stop_thinking, live, compile_mode), daemon=True
                )
                new_t.start()
                if _thinking_thread:
                    _thinking_thread[0] = new_t
                elif _thinking_thread is not None:
                    _thinking_thread.append(new_t)
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
                elif action == "nothing":
                    # Rien à relire : l'agent doit corriger son appel, pas deviner.
                    override = {
                        "status": "error",
                        "path": args.get("path", ""),
                        "error": ("Aucune proposition n'est arrivée jusqu'à la revue — "
                                  "l'appel propose_file_change n'a rien déposé. "
                                  "Vérifie son résultat : un plan est-il actif "
                                  "(dev_plan_create) ? L'utilisateur n'a RIEN refusé."),
                    }
                elif action == "refine" and refinement:
                    override = {
                        "status": "needs_refinement",
                        "path": args.get("path", ""),
                        "feedback": refinement,
                        "message": (
                            f"L'utilisateur demande des modifications : {refinement}. "
                            f"Prends en compte ce feedback et rappelle {tool_name} corrigé."
                        ),
                    }

        # ── Notebook cell HITL ────────────────────────────────────────────────
        elif tool_name in ("notebook_edit_cell", "notebook_insert_cell"):
            if get_mode() == "auto":
                from src.agents.notebook.tools import pending_cell_changes as _pcells, apply_cell_change
                from src.infra.tools_cache import session_cache
                change = _pcells.pop_latest()
                if change:
                    try:
                        apply_cell_change(change)
                        session_cache.invalidate_filesystem()
                        t = Text()
                        t.append("  ✓  ", style="bold green")
                        t.append(change.path, style="dim")
                        console.print(t)
                        override = {"status": "accepted", "awaiting_confirmation": False}
                    except Exception as e:
                        override = {"status": "error", "error": str(e)}
                else:
                    override = {"status": "accepted", "awaiting_confirmation": False}
            else:
                try:
                    live.update(Text(""))
                    live.stop()
                except Exception:
                    pass
                from .review import review_latest_cell_change
                action, refinement = review_latest_cell_change()
                stop_thinking.clear()
                try:
                    live.start(refresh=False)
                except Exception:
                    pass
                new_t = threading.Thread(
                    target=_make_thinking_loop(stop_thinking, live, compile_mode), daemon=True
                )
                new_t.start()
                if _thinking_thread:
                    _thinking_thread[0] = new_t
                elif _thinking_thread is not None:
                    _thinking_thread.append(new_t)
                if action == "apply":
                    override = {"status": "accepted", "awaiting_confirmation": False}
                elif action == "reject":
                    override = {
                        "status": "rejected",
                        "message": "L'utilisateur a refusé ce changement. Ne modifie pas cette cellule en l'état.",
                    }
                elif action == "nothing":
                    # Rien à relire : l'agent doit corriger son appel, pas deviner.
                    override = {
                        "status": "error",
                        "error": ("Aucune proposition n'est arrivée jusqu'à la revue — "
                                  "notebook_edit_cell n'a rien déposé. "
                                  "L'utilisateur n'a RIEN refusé."),
                    }
                elif action == "refine" and refinement:
                    override = {
                        "status": "needs_refinement",
                        "feedback": refinement,
                        "message": (
                            f"L'utilisateur demande des modifications : {refinement}. "
                            "Rappelle notebook_edit_cell avec le contenu corrigé."
                        ),
                    }

        # Restart thinking so LLM-think time shows animation (HITL branches cleared it already)
        if stop_thinking.is_set():
            _resume_thinking()
        return override

    set_progress_callback(_coding_progress)
    set_compile_callback(_on_compile)

    plan_rendered = False  # track outside try so post-stream HITL can read it

    try:
        live.start(refresh=False)
        response_content = ""
        saw_any_token = False
        last_node = ""
        last_debug_node = ""
        deb = {"DEBOUNCE": 0.03, "last_update": 0.0}
        t0 = perf_counter()

        t = threading.Thread(target=_make_thinking_loop(stop_thinking, live, compile_mode), daemon=True)
        t.start()
        _thinking_thread.append(t)

        _stream_input = current_state
        while True:
            _needs_stream_restart = False
            for msg, meta in graph.stream(_stream_input, config=config, stream_mode="messages"):
                node = meta.get("langgraph_node") or "unknown"

                if cfg.debug and node != last_debug_node:
                    console.print(f"[dim]→ {node}[/dim]")
                    last_debug_node = node

                if isinstance(msg, ToolMessage):
                    tool_name = getattr(msg, "name", None) or getattr(msg, "tool_name", None) or meta.get("tool", "tool")
                    if tool_name == "gmail_send_email":
                        _safe_stop(live, stop_thinking, _thinking_thread[0] if _thinking_thread else None)
                        from .review import review_email
                        action, refinement = review_email()
                        if action == "send":
                            pending_refinements.append("Email envoyé avec succès.")
                        elif action == "cancel":
                            pending_refinements.append("Envoi annulé par l'utilisateur.")
                        elif action == "modify" and refinement:
                            pending_refinements.append(f"L'utilisateur veut modifier le mail : {refinement}")
                        stop_thinking.clear()
                        live.start(refresh=False)
                        new_t = threading.Thread(target=_make_thinking_loop(stop_thinking, live, compile_mode), daemon=True)
                        new_t.start()
                        if _thinking_thread:
                            _thinking_thread[0] = new_t
                        else:
                            _thinking_thread.append(new_t)
                    elif tool_name == "ask_clarification":
                        import json as _json
                        try:
                            content = msg.content
                            if not isinstance(content, str):
                                content = _json.dumps(content)
                            payload = _json.loads(content)
                            questions = payload.get("questions", []) if isinstance(payload, dict) else []
                        except Exception:
                            questions = []
                        _safe_stop(live, stop_thinking, _thinking_thread[0] if _thinking_thread else None)
                        from .review import ask_user_questions
                        try:
                            answers = ask_user_questions(questions)
                        except Exception as _qe:
                            console.print(Text(f"  erreur questionnaire : {_qe}", style="red"))
                            answers = {}
                        # Remplace le ToolMessage placeholder par les vraies réponses dans l'état du graph.
                        # IMPORTANT : msg.id (l'objet streamé en direct) vaut encore None ici — l'id réel
                        # n'est attribué par LangGraph qu'au moment du commit dans l'état persistant.
                        # Il faut donc relire l'état via get_state() pour cibler le bon message par
                        # tool_call_id (fiable), sinon le remplacement ne matche rien et se perd
                        # silencieusement — la réponse de l'utilisateur n'atteint jamais le LLM.
                        try:
                            from langchain_core.messages import ToolMessage as _TM
                            _real_id = msg.tool_call_id  # fallback si la relecture échoue
                            try:
                                _snap = graph.get_state(config)
                                _placeholder = next(
                                    (
                                        m for m in reversed(_snap.values.get("messages", []))
                                        if isinstance(m, _TM) and m.tool_call_id == msg.tool_call_id
                                    ),
                                    None,
                                )
                                if _placeholder is not None:
                                    _real_id = _placeholder.id
                            except Exception:
                                pass
                            updated = _TM(
                                content=_json.dumps({"answers": answers}),
                                tool_call_id=msg.tool_call_id,
                                name="ask_clarification",
                                id=_real_id,
                            )
                            # `as_node` n'est PAS cosmétique : sans lui la reprise ne
                            # replanifie aucun nœud et le tour meurt sans un mot.
                            graph.update_state(config, {"messages": [updated]},
                                               as_node=_NOEUD_OUTILS)
                            # `add_messages` ne REMPLACE que si l'id correspond à un
                            # message DÉJÀ dans l'état ; sinon il AJOUTE. Le placeholder
                            # `{"awaiting_input": true}` restait alors présent À CÔTÉ des
                            # réponses : le modèle voyait « en attente de réponse » et
                            # reposait les mêmes questions. On répare explicitement en
                            # supprimant tout placeholder résiduel (RemoveMessage).
                            try:
                                from langchain_core.messages import RemoveMessage as _RM

                                _after = graph.get_state(config)
                                _same = [
                                    m for m in _after.values.get("messages", [])
                                    if isinstance(m, _TM) and m.tool_call_id == msg.tool_call_id
                                ]
                                _stale = [
                                    m for m in _same
                                    if "answers" not in (
                                        m.content if isinstance(m.content, str)
                                        else _json.dumps(m.content)
                                    )
                                ]
                                if _stale:
                                    graph.update_state(
                                        config,
                                        {"messages": [_RM(id=m.id) for m in _stale if m.id]},
                                        as_node=_NOEUD_OUTILS,
                                    )
                                    _after = graph.get_state(config)
                                    _same = [
                                        m for m in _after.values.get("messages", [])
                                        if isinstance(m, _TM)
                                        and m.tool_call_id == msg.tool_call_id
                                    ]
                                _ok = any(
                                    "answers" in (
                                        m.content if isinstance(m.content, str)
                                        else _json.dumps(m.content)
                                    )
                                    for m in _same
                                )
                                if not _ok or len(_same) != 1:
                                    console.print(Text(
                                        f"  ⚠ réponses mal injectées ({len(_same)} message(s), "
                                        f"answers={_ok}) — le modèle risque de reposer "
                                        f"les questions", style="yellow"))
                                # Les réponses peuvent être PARFAITEMENT injectées et
                                # n'être jamais lues : sans nœud replanifié, la reprise
                                # ne réveille personne. C'est la panne muette qu'on
                                # refuse de laisser passer sans le dire.
                                if not _after.next:
                                    console.print(Text(
                                        "  ⚠ reprise non planifiée après le questionnaire — "
                                        "les réponses n'atteindront pas le modèle",
                                        style="yellow"))
                            except Exception as _ve:
                                console.print(Text(
                                    f"  ⚠ vérification d'injection impossible : {_ve}",
                                    style="yellow"))
                        except Exception as _ue:
                            # Ne JAMAIS perdre les réponses en silence.
                            console.print(Text(
                                f"  ⚠ échec d'injection des réponses : {_ue}", style="yellow"))
                        stop_thinking.clear()
                        try:
                            live.start(refresh=False)
                        except Exception:
                            pass
                        new_t = threading.Thread(target=_make_thinking_loop(stop_thinking, live, compile_mode), daemon=True)
                        new_t.start()
                        if _thinking_thread:
                            _thinking_thread[0] = new_t
                        else:
                            _thinking_thread.append(new_t)
                        _needs_stream_restart = True
                        break
                    elif tool_name == "run_coding_agent":
                        # Stop coding-specialist thinking thread, restart for orchestrator response
                        stop_thinking.set()
                        if _thinking_thread:
                            _thinking_thread[0].join(timeout=_ARRET_ANIMATION)
                        compile_mode.clear()
                        stop_thinking.clear()
                        new_t = threading.Thread(target=_make_thinking_loop(stop_thinking, live, compile_mode), daemon=True)
                        new_t.start()
                        if _thinking_thread:
                            _thinking_thread[0] = new_t
                        else:
                            _thinking_thread.append(new_t)
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
                        tool_calls = getattr(msg, "tool_calls", None) or []
                        for tc in tool_calls:
                            if (tc.get("name") or "") == "run_coding_agent":
                                # Commit any accumulated orchestrator text to scrollback
                                # BEFORE specialist starts printing — fixes visual ordering
                                if saw_any_token and response_content:
                                    from .panels import final_panel
                                    console.print(final_panel(response_content))
                                    response_content = ""
                                    saw_any_token = False
                                live.update(Text(""))
                        continue
                    if last_node == "tools":
                        response_content = ""
                        saw_any_token = False
                        plan_rendered = False
                        last_node = "chatbot"
                        stop_thinking.set()
                        if _thinking_thread:
                            _thinking_thread[0].join(timeout=_ARRET_ANIMATION)
                        # Efface le panel sans stop/start — évite de committer le contenu
                        # partiel dans le scrollback à chaque appel d'outil.
                        # Le stop/start (re-ancrage) n'est nécessaire que pour run_coding_agent
                        # qui imprime dans le console ; il est géré séparément plus haut.
                        live.update(Text(""))
                    compile_mode.clear()
                    stop_thinking.set()

                    _PLAN_OPEN  = "<axon:plan>"
                    _PLAN_CLOSE = "</axon:plan>"

                    if settings.llm_backend == "gemini" and response_content and chunk_text.startswith(response_content):
                        chunk_text = chunk_text[len(response_content):]
                    response_content += chunk_text

                    saw_any_token = True

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

            if _needs_stream_restart:
                _stream_input = None
                continue
            break
        footer = fmt_ms(perf_counter() - t0)
        if saw_any_token:
            safe = _guard_sanitize(enforce_lang_output(response_content, user_lang))
            finalize_live(live, safe, footer, console=console)
        else:
            # `_stream_input`, PAS `current_state` : après un questionnaire, la
            # question de l'utilisateur est déjà dans l'état et la reprise vaut
            # `None`. Réinjecter le message d'origine relançait le tour depuis zéro
            # — le modèle reposait alors les questions auxquelles on venait de
            # répondre, et sans passer par l'affichage du questionnaire.
            final_state = graph.invoke(_stream_input, config=config)
            text = _dernier_texte_du_modele(final_state.get("messages") or [])
            if not text.strip():
                text = ("_Le modèle n'a rien rédigé pour ce tour. Relance ta "
                        "demande — rien n'a été perdu de la conversation._")
            safe = _guard_sanitize(enforce_lang_output(text, user_lang))
            finalize_live(live, safe, footer, console=console)
        live.stop()

    except KeyboardInterrupt:
        stop_thinking.set()
        try:
            live.stop()
        except Exception:
            pass
        msg = Text()
        msg.append("  ⊘  ", style=f"bold {ACCENT}")
        msg.append("interrompu", style="dim")
        console.print(msg)
        return

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
                    finalize_live(live2, _guard_sanitize(enforce_lang_output(rc2, user_lang)), "retry", console=console)
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

    # ── Post-stream: plan HITL ────────────────────────────────────────────────
    from src.ui.plan_mode import is_active as _is_plan_active
    if plan_rendered and _is_plan_active():
        from .review import review_plan
        from src.ui.plan_mode import set_active as _set_plan_active

        while True:
            _plan_action, _plan_refinement = review_plan()
            if _plan_action == "accept":
                _set_plan_active(False)
                pending_refinements.append(
                    "Plan approuvé. Procède maintenant aux changements en suivant exactement ce plan."
                )
                break
            elif _plan_action == "refine" and _plan_refinement:
                _stream_message(
                    graph,
                    f"Voici des précisions pour le plan : {_plan_refinement}. "
                    "Révise le plan en tenant compte de ces spécifications et propose un plan mis à jour.",
                    cfg,
                )
                # Loop back → review_plan() on the updated plan
            else:  # reject or empty refine
                _set_plan_active(False)
                break

    for refinement in pending_refinements:
        _stream_message(graph, refinement, cfg)
