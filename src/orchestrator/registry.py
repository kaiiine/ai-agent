from langchain_core.tools import BaseTool
from typing import List

from src.agents.search.tools import web_research_report
from src.agents.weather.tools import get_weather_by_city
from src.agents.gmail.tools import gmail_search, gmail_edit_draft, gmail_confirm_send, gmail_send_email, gmail_summarize
from src.agents.google_drive.tools import drive_find_file_id, drive_list_files, drive_delete_file, drive_get_file_metadata, drive_read_file
from src.agents.google_doc.tools import google_docs_create, google_docs_update, google_docs_read
from src.agents.google_slide.tools import create_presentation, add_slide
from src.agents.time.tools import get_current_time
from src.agents.slack.tools import (
    slack_list_channels, slack_read_channel, slack_get_mentions,
    slack_list_dms, slack_send_message, slack_search_messages, slack_find_user,
)


def build_all_tools() -> List[BaseTool]:
    return [
        # === WEB SEARCH ===
        web_research_report,
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
        # === GOOGLE SLIDES ===
        create_presentation,
        add_slide,
        # === SLACK ===
        slack_list_channels,
        slack_read_channel,
        slack_get_mentions,
        slack_list_dms,
        slack_send_message,
        slack_search_messages,
        slack_find_user,
    ]
