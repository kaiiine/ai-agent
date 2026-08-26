from langchain_core.tools import BaseTool
from typing import List
import json


from src.agents.search.tools import web_research_report, web_search_news
from src.agents.weather.tools import get_weather_by_city
from src.agents.gmail.tools import (
    gmail_search, gmail_edit_draft, gmail_confirm_send, gmail_send_email,
    gmail_summarize, gmail_reply,
)
from src.agents.google_drive.tools import drive_find_file_id, drive_list_files, drive_delete_file, drive_get_file_metadata, drive_read_file
from src.agents.google_doc.tools import google_docs_create, google_docs_write, google_docs_read
# Sheets et Slides n'étaient PAS enregistrés : leurs outils existaient sur le
# disque et l'agent ne pouvait pas les appeler. C'est ce qui a laissé passer un
# constructeur de service mort et un `add_slide` qui jetait son contenu.
from src.agents.google_sheet.tools import sheets_create, sheets_append_rows, sheets_read
from src.agents.coding.tools import edit_file, propose_file_change
from src.agents.slides.tools import create_slides
from src.agents.translator.tools import translator
from src.agents.google_slide.tools import (
    slides_create, slides_add_slide, slides_from_markdown,
)
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
from src.agents.shell.tools import (
    shell_run, shell_cd, shell_pwd, shell_ls,
    notify, clipboard_read, clipboard_write,
)
from src.agents.clarify.tools import ask_clarification
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

from src.agents.cron.tools import (
    schedule_task,
    list_cron_task,
    stop_cron_task,
    surveiller,
)
from src.skills.tools import make_load_skill
from src.agents.quant.tools import (
    winamax_odds_fetch, sports_stats_fetch, probability_compute,
    ev_analyze, parlay_analyze, same_match_combo_analyze,
)
from src.agents.quant.conversation.tools import betting_recommend

from langchain_core.tools import tool as lc_tool

# Ne voit que les skills qui déclarent cette portée — les guides de stack restent
# réservés à l'agent coding.
load_skill = make_load_skill("orchestrator")

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
        gmail_reply,
        # === GOOGLE DRIVE ===
        drive_list_files,
        drive_find_file_id,
        drive_read_file,
        drive_delete_file,
        drive_get_file_metadata,
        # === GOOGLE DOCS ===
        google_docs_create,
        google_docs_write,
        google_docs_read,
        # === GOOGLE SHEETS ===
        sheets_create,
        sheets_append_rows,
        sheets_read,
        # === ÉCRITURE DE FICHIERS ===
        # `shell_run` REFUSE `sed -i`, `cat >` et consorts, et renvoie le modèle
        # vers `edit_file` / `propose_file_change` — deux outils que
        # l'orchestrateur n'avait pas. Le message le dirigeait donc vers une
        # porte qui n'existait pas pour lui, et il n'avait plus qu'à expliquer à
        # l'utilisateur comment faire à la main. Vécu sur « commente ces deux
        # lignes dans ~/.config/hypr/keybindings.conf » : le modèle a tenté
        # `run_coding_agent`, dont la description ne parle que de projets de
        # code, s'est trompé d'argument, puis a rendu un mode d'emploi.
        #
        # Ce n'est pas une couche de plus : les changements proposés sont déjà
        # drainés après chaque tour par `streaming.py` (auto_write_all en mode
        # auto, review_pending sinon). L'outil existait, son consommateur
        # existait ; seul le fil entre les deux manquait.
        edit_file,
        propose_file_change,
        # === TRADUCTION ===
        # Documenté dans le README, jamais importé : même panne silencieuse que
        # `create_slides`.
        translator,
        # === PRÉSENTATION LOCALE (Reveal.js + PPTX) ===
        # `create_slides` existait, était testé et documenté dans le README —
        # mais n'était importé NULLE PART. Le paquet `src/agents/slides/` entier
        # était donc mort côté agent : « fais-moi une présentation » ne pouvait
        # qu'atterrir sur l'API Google Slides, un appel par diapositive, ce qui
        # épuise le budget de tours avant la fin du deck.
        create_slides,
        # === GOOGLE SLIDES ===
        slides_create,
        slides_add_slide,
        slides_from_markdown,
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
        shell_run,
        shell_cd,
        shell_pwd,
        shell_ls,
        notify,
        clipboard_read,
        clipboard_write,
        ask_clarification,
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
        # === SKILLS PROJET ===
        load_skill,
        # === MÉMOIRE PROJET ===
        axon_note,
        # === DIAGRAMMES ===
        mermaid_diagram,
        # === ÉTUDE ===
        save_study_file,
        # === CRON JOBS ===
        schedule_task,
        surveiller,
        list_cron_task,
        stop_cron_task,
        # === VALUE BETTING (QUANT) ===
        # L'UNIQUE chemin de recommandation : scan -> Betting Engine -> Advisor.
        # Sans lui, une demande de scan n'avait aucun outil capable d'y répondre,
        # et le modèle terminait le travail lui-même.
        betting_recommend,
        winamax_odds_fetch,
        sports_stats_fetch,
        probability_compute,
        ev_analyze,
        parlay_analyze,
        same_match_combo_analyze,
    ]
