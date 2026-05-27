from langchain_core.tools import BaseTool
from typing import List
import json


def _repair_json(s: str) -> dict | None:
    """Attempt to repair a truncated JSON string and return parsed dict, or None."""
    # Walk the string tracking open structures, then close them
    open_braces = 0
    open_brackets = 0
    in_string = False
    escape_next = False
    last_valid_pos = 0

    for i, ch in enumerate(s):
        if escape_next:
            escape_next = False
            continue
        if ch == '\\' and in_string:
            escape_next = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == '{':
            open_braces += 1
        elif ch == '}':
            open_braces = max(0, open_braces - 1)
        elif ch == '[':
            open_brackets += 1
        elif ch == ']':
            open_brackets = max(0, open_brackets - 1)
        if open_braces == 0 and open_brackets == 0:
            last_valid_pos = i + 1

    # If the string was cut mid-string literal, close it
    candidate = s if not in_string else s + '"'
    # Strip trailing comma before closing (common in truncated arrays/objects)
    candidate = candidate.rstrip().rstrip(',')
    candidate += ']' * open_brackets + '}' * open_braces

    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass

    # Last resort: try up to the last known balanced position
    if last_valid_pos > 0:
        try:
            return json.loads(s[:last_valid_pos])
        except json.JSONDecodeError:
            pass

    return None

from src.agents.search.tools import web_research_report, web_search_news
from src.agents.weather.tools import get_weather_by_city
from src.agents.gmail.tools import gmail_search, gmail_edit_draft, gmail_confirm_send, gmail_send_email, gmail_summarize
from src.agents.google_drive.tools import drive_find_file_id, drive_list_files, drive_delete_file, drive_get_file_metadata, drive_read_file
from src.agents.google_doc.tools import google_docs_create, google_docs_update, google_docs_read
# TODO: restore once src/agents/slides/tools.py is rebuilt
# from src.agents.slides.tools import create_slides
from src.agents.filesystem.tools import local_find_file, local_read_file, local_list_directory, local_grep, local_glob
from src.agents.google_calendar.tools import (
    calendar_list_events, calendar_create_event, calendar_update_event,
    calendar_delete_event, calendar_list_calendars, calendar_search_events,
)
from src.agents.time.tools import get_current_time
from src.agents.slack.tools import (
    slack_list_channels, slack_read_channel, slack_get_mentions,
    slack_list_dms, slack_send_message, slack_search_messages, slack_find_user,
)
from src.agents.shell.tools import notify, clipboard_read, clipboard_write
from src.agents.git.tools import (
    git_status, git_log, git_diff, git_suggest_commit,
    git_add, git_commit, git_checkout, git_stash,
    url_fetch,
)
from src.agents.system.tools import (
    screenshot_take, process_list, process_kill, wifi_info,
)
from src.agents.arxiv.tools import arxiv_search, arxiv_get_paper
from src.agents.memory.tools import axon_note
from src.agents.mermaid.tools import mermaid_diagram
from src.agents.study.tools import save_study_file
from src.agents.jira.tools import (
    jira_get_my_issues, jira_get_issue, jira_search_issues,
    jira_get_project_summary, jira_get_sprint_issues,
    jira_list_projects, jira_add_comment, jira_transition_issue, jira_get_workload,
    jira_create_issue, jira_create_issues_bulk, jira_assign_issue, jira_update_issue,
    jira_get_issue_comments, jira_search_users, jira_move_issue,
    jira_delete_issue, jira_link_to_epic,
)

from datetime import date as _date
from langchain_core.tools import tool as lc_tool


def _sanitize_slides(slides: list, title: str) -> list:
    # Ensure title slide is first
    if not slides or slides[0].get("type") != "title":
        slides.insert(0, {
            "type": "title",
            "title": title,
            "date": _date.today().strftime("%B %Y"),
        })

    # Truncate after first closing; add one if missing
    closing_idx = next((i for i, s in enumerate(slides) if s.get("type") == "closing"), None)
    if closing_idx is not None:
        slides = slides[:closing_idx + 1]
    else:
        slides.append({"type": "closing", "title": title, "eyebrow": "MERCI"})

    # Section subtitle fallback: avoid empty subtitle on section slides
    for slide in slides:
        if slide.get("type") == "section" and not slide.get("subtitle"):
            slide["subtitle"] = f"Découvrez {slide.get('title', '')}"

    # Auto-assign sequential section numbers (01, 02, 03…) regardless of LLM output
    section_counter = 0
    for slide in slides:
        if slide.get("type") == "section":
            section_counter += 1
            slide["num"] = str(section_counter).zfill(2)

    # Warn on consecutive content slides (no auto-fix this iteration)
    for i in range(len(slides) - 1):
        if slides[i].get("type") == "content" and slides[i + 1].get("type") == "content":
            print(f"[slides] WARNING: consecutive 'content' slides at index {i} and {i+1}")

    return slides


@lc_tool("create_presentation")
def create_presentation(topic: str, export_to: str = "/tmp/slides/") -> str:
    """
    Génère une présentation professionnelle complète (HTML Reveal.js + PPTX) sur un sujet donné.

    TOUJOURS utiliser cet outil quand l'utilisateur demande :
    - une présentation, un diaporama, des slides, un PowerPoint, un PPTX
    - un pitch deck, une présentation Gamma-style
    - "fais-moi une présentation sur X"
    - synthétiser un sujet en slides

    Args:
        topic:     Sujet ou brief complet de la présentation (inclure les contraintes si précisées)
        export_to: Dossier de sortie (défaut : /tmp/slides/)
    Returns:
        Chemins des fichiers générés.
    """
    import json
    import re
    from langchain_core.messages import HumanMessage, SystemMessage
    from src.llm.models import make_coding_llm
    from src.agents.slides.tools import create_slides

    llm = make_coding_llm()

    # Step 1: Web research for real facts, statistics, and examples
    research_context = ""
    try:
        from src.agents.search.tools import web_research_report as _wresearch
        research_raw = _wresearch.invoke(f"{topic} statistics data facts examples 2024 2025")
        if research_raw and isinstance(research_raw, str) and len(research_raw) > 100:
            research_context = (
                "\n\nRECHERCHE FACTUELLE (utilise impérativement ces vraies données, "
                "chiffres et exemples concrets dans les slides) :\n"
                + research_raw[:5000]
                + "\n"
            )
    except Exception:
        pass

    slides_prompt = (
        f"Crée une présentation professionnelle et DENSE sur : {topic}\n"
        f"{research_context}\n"
        'Réponds UNIQUEMENT avec un objet JSON valide (sans markdown, sans explication) :\n'
        '{"title": "...", "theme": {"accents": ["#hex1","#hex2","#hex3"], "bg": "#hex"}, "slides": [...]}\n\n'
        "THEME (champ racine, hors slides) :\n"
        "Choisir 4 couleurs cohérentes avec le domaine + un fond sombre (pas trop noir) :\n"
        '  Business/RH   : accents ["#2563eb","#0ea5e9","#f59e0b","#818cf8"], bg "#0a1628"\n'
        '  Tech/IA       : accents ["#7c3aed","#06b6d4","#f59e0b","#10b981"], bg "#0f172a"\n'
        '  Cybersécurité : accents ["#dc2626","#f97316","#fbbf24","#ef4444"], bg "#130604"\n'
        '  Finance       : accents ["#10b981","#0ea5e9","#6366f1","#34d399"], bg "#051910"\n'
        '  Design/créatif: accents ["#a855f7","#ec4899","#06b6d4","#f472b6"], bg "#0d0418"\n'
        '  Santé         : accents ["#06b6d4","#10b981","#3b82f6","#22d3ee"], bg "#061414"\n\n'
        "TYPES DISPONIBLES :\n"
        '  title    : {type, title, subtitle?, author?, date?}\n'
        '  timeline : {type, title, subtitle?, steps:[{num,label,sub?,duration?,color?}]}  ← SOMMAIRE CHRONOLOGIQUE\n'
        '  agenda   : {type, title, items:[{label,sub}]}  ← items DOIVENT avoir label + sub (1 phrase descriptive)\n'
        '  section  : {type, title, num?, eyebrow?, subtitle}  ← TRANSITION ENTRE PARTIES\n'
        '  content  : {type, title, body, bullets}  ← body=2 phrases, bullets=4-5 points MAX\n'
        '  split    : {type, title, left:{heading,body?,bullets}, right:{heading,body?,bullets}}  ← 3-4 bullets/col\n'
        '  split3   : {type, title, body?, columns:[{heading,color?,body?,bullets}]}  ← 3 colonnes comparatives\n'
        '  stats    : {type, title, source?, stats:[{value,label,source?}]}  ← EXACTEMENT 4 chiffres\n'
        '  table    : {type, title, columns:[{label}], rows:[{dim,values:[...]}]}  ← comparaison tabulaire\n'
        '  cases    : {type, title, cases:[{company,icon,arch,body,lesson}]}  ← 4 cas réels avec métriques\n'
        '  quote    : {type, quote, author, role?}  ← citation percutante d\'un expert réel\n'
        '  closing  : {type, title, subtitle?, cta?, eyebrow?}\n\n'
        "STRUCTURE OBLIGATOIRE :\n"
        "- Slide 1 = TOUJOURS type 'title' avec subtitle (1-2 phrases résumant le sujet) + date\n"
        "- Slide 2 = type 'timeline' si le sujet est chronologique/processus, OU 'agenda' si le sujet est transversal/comparatif\n"
        "- Dernière slide = TOUJOURS type 'closing' — RIEN après, jamais\n\n"
        "RÈGLES STRICTES :\n"
        "1. section : subtitle OBLIGATOIRE — 1 phrase d'accroche qui annonce la valeur de la partie "
        "(ex: 'Comment l'IA transforme le recrutement en profondeur')\n"
        "2. content : body = 2 phrases minimum avec données concrètes (chiffres, %) + 4-5 bullets informatifs\n"
        "3. split : chaque colonne DOIT avoir heading + 3-4 bullets (pas juste un body vide)\n"
        "4. stats : vraies valeurs chiffrées avec unités issues de la recherche (ex: '73%', '$4.4B') — EXACTEMENT 4 métriques\n"
        "5. cases : 4 entreprises réelles, body DOIT contenir des métriques chiffrées précises "
        "(ex: '-15% ruptures de stock', '+8% satisfaction client', '40% sinistres automatisés', '3x plus rapide'), lesson obligatoire\n"
        "6. bullets : phrases complètes et informatives, SANS **markdown**\n"
        "7. table : chaque élément de values = UNE SEULE valeur courte (< 80 chars) correspondant exactement à sa colonne — "
        "JAMAIS plusieurs valeurs dans une cellule. rows[i].values DOIT avoir exactement len(columns) éléments. "
        "Colonnes chronologiques → année la plus ANCIENNE en premier, la plus RÉCENTE en dernier\n"
        "8. Inclure OBLIGATOIREMENT : 1 stats (4 métriques) + 1 cases + au moins 1 table OU split3\n"
        "9. 14-18 slides — JAMAIS 2 slides 'content' consécutives : alterner avec split/split3/stats/cases/quote/table\n"
        "10. stats : TOUJOURS exactement 4 métriques (pas 3, pas 6) → grille 2×2 parfaitement symétrique\n"
        "11. split3 : chaque colonne DOIT avoir heading + au moins 3 bullets — pas seulement un body\n"
        "12. split3 : body OBLIGATOIRE — 1 phrase introductive avant les colonnes "
        "(ex: 'Trois approches s'affrontent sur ce marché') — sinon les colonnes semblent flotter sans contexte\n"
        "13. JAMAIS de titres génériques : 'Suite des applications', 'Autres points', 'Contexte (suite)' — "
        "chaque slide doit avoir un titre thématique précis et informatif\n"
        "14. agenda : chaque item DOIT avoir sub — 1 phrase qui résume la sous-partie "
        "(ex: 'Du screening automatisé à la décision augmentée')\n"
        "15. split : body RECOMMANDÉ — 1 phrase introductive avant les 2 colonnes si le titre seul ne suffit pas\n"
        "16. closing cta : COURT — 3-6 mots max (ex: 'Questions & Échanges', 'Découvrir la suite') "
        "— PAS une phrase complète\n\n"
        "Réponds UNIQUEMENT avec le JSON."
    )

    response = llm.invoke([
        SystemMessage(content=(
            "Tu es un expert en communication professionnelle. "
            "Tu génères des présentations DENSES, VISUELLEMENT RICHES et FACTUELLEMENT PRÉCISES. "
            "Utilise les données de la recherche pour produire du contenu réel et vérifiable. "
            "Génère uniquement du JSON valide, sans aucun texte avant ou après."
        )),
        HumanMessage(content=slides_prompt),
    ])

    content = response.content
    if isinstance(content, list):
        content = " ".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in content)
    content = content.strip()

    m = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', content)
    if m:
        content = m.group(1)

    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        data = _repair_json(content)
        if data is None:
            return f"Erreur parsing JSON — réponse tronquée ou invalide.\n\nDébut:\n{content[:800]}"

    pres_title = data.get("title", topic)
    # Guard against LLM returning the full prompt as title
    if "\n" in pres_title or len(pres_title) > 120:
        pres_title = topic.split("\n")[0][:80].strip()

    theme = data.get("theme")

    # Pad accents to 4 (cycling) so the 4th card always uses a distinct colour
    if theme and theme.get("accents"):
        accents = list(theme["accents"])
        while len(accents) < 4:
            accents += accents[:4 - len(accents)]
        theme = dict(theme, accents=accents)

    slides = data.get("slides", [])

    # Strip deprecated image fields
    for slide in slides:
        slide.pop("image_query", None)
        slide.pop("image_url", None)

    slides = _sanitize_slides(slides, pres_title)

    return create_slides.invoke({
        "title": pres_title,
        "slides": slides,
        "export_to": export_to,
        "theme": theme,
    })


@lc_tool("run_coding_agent")
def run_coding_agent(task: str) -> str:
    """
    Délègue une tâche de code au modèle spécialisé qui analyse, lit et modifie des projets locaux.

    Utilise ce tool quand l'utilisateur veut :
    - modifier, améliorer ou refactoriser du code dans un projet local
    - créer de nouvelles fonctionnalités dans un projet
    - corriger des bugs dans son code
    - analyser l'architecture ou la structure d'un projet
    - ajouter des tests, améliorer la documentation d'un projet
    - travailler sur des fichiers de code (lire, modifier, créer) dans n'importe quel langage
    - faire des changements visuels ou structurels dans un projet (UI, design, layout, style)

    Exemples de requêtes utilisateur qui déclenchent ce tool :
    - "va dans mon projet X et modifie le fichier Y"
    - "corrige l'erreur dans mon code"
    - "ajoute une nouvelle fonctionnalité à mon application"
    - "refactoriser ce module pour le rendre plus propre"
    - "analyse la structure de mon projet et dis-moi ce qui ne va pas"
    - "crée un nouveau composant / fichier / classe dans mon projet"
    - "améliore le design et rends-le plus moderne"
    - "regarde mon repo et fais des modifications"
    - "il y a un bug dans mon application, peux-tu le trouver et le corriger"
    - "lis le fichier X et modifie-le pour faire Y"

    Mots-clés : code, projet, fichier, repo, bug, modifier, créer, refactoriser, développer, programmer,
    application, composant, fonction, classe, module, design, style, interface, front, backend

    NE PAS utiliser pour :
    - créer une présentation, des slides, un PowerPoint, un pitch deck → utiliser create_slides
    - générer un diagramme → utiliser mermaid_diagram

    Args:
        task: description détaillée de la tâche (inclure le nom du projet si connu)
    Returns:
        résumé de ce qui a été analysé et proposé
    """
    # Guard: reject garbage task args (e.g. stringified message lists from weak models)
    stripped = task.strip()
    if len(stripped) < 10 or (stripped.startswith('[') and 'Message(' in stripped[:200]):
        return "Erreur : le paramètre 'task' doit être une description textuelle de la tâche, pas une liste de messages."
    from src.agents.coding.specialist import run_coding_task
    return run_coding_task(task)


def build_all_tools() -> List[BaseTool]:
    return [
        # === WEB SEARCH ===
        web_research_report,
        web_search_news,
        # === TIME/DATE ===
        get_current_time,
        get_weather_by_city,
        # === EMAILS ===
        gmail_search,
        gmail_edit_draft,
        gmail_confirm_send,
        gmail_send_email,
        gmail_summarize,
        # === GOOGLE DRIVE ===
        drive_list_files,
        drive_find_file_id,
        drive_read_file,
        drive_delete_file,
        drive_get_file_metadata,
        # === GOOGLE DOCS ===
        google_docs_create,
        google_docs_update,
        google_docs_read,
        # === SLIDES / PRÉSENTATIONS ===
        create_presentation,
        create_slides,
        # === FILESYSTEM LOCAL ===
        local_find_file,
        local_list_directory,
        local_read_file,
        local_grep,
        local_glob,
        # === GOOGLE CALENDAR ===
        calendar_list_events,
        calendar_create_event,
        calendar_update_event,
        calendar_delete_event,
        calendar_list_calendars,
        calendar_search_events,
        # === SLACK ===
        slack_list_channels,
        slack_read_channel,
        slack_get_mentions,
        slack_list_dms,
        slack_send_message,
        slack_search_messages,
        slack_find_user,
        # === SHELL / SYSTÈME ===
        notify,
        clipboard_read,
        clipboard_write,
        # === GIT + WEB ===
        git_status,
        git_log,
        git_diff,
        git_suggest_commit,
        git_add,
        git_commit,
        git_checkout,
        git_stash,
        url_fetch,
        # === SYSTÈME ===
        screenshot_take,
        process_list,
        process_kill,
        wifi_info,
        # === ARXIV ===
        arxiv_search,
        arxiv_get_paper,
        # === JIRA ===
        jira_get_my_issues,
        jira_get_issue,
        jira_search_issues,
        jira_get_project_summary,
        jira_get_sprint_issues,
        jira_list_projects,
        jira_add_comment,
        jira_transition_issue,
        jira_get_workload,
        jira_create_issue,
        jira_create_issues_bulk,
        jira_assign_issue,
        jira_update_issue,
        jira_get_issue_comments,
        jira_search_users,
        jira_move_issue,
        jira_delete_issue,
        jira_link_to_epic,
        # === CODING / PROJETS ===
        run_coding_agent,
        # === MÉMOIRE PROJET ===
        axon_note,
        # === DIAGRAMMES ===
        mermaid_diagram,
        # === ÉTUDE ===
        save_study_file,
    ]
