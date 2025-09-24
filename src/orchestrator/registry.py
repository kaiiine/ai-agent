# src/tools/registry.py
from langchain_core.tools import BaseTool
from typing import List
from src.agents.email.emailAgent import EmailAgent

# Practical tools
from src.agents.search.tools import build_search_tool,web_search, web_research_report
from src.agents.weather.tools import get_weather_by_city
from src.agents.gmail.tools import gmail_search, gmail_edit_draft, gmail_confirm_send, gmail_send_email, gmail_summarize
from src.agents.google_drive.tools import drive_find_file_id, drive_list_files, drive_delete_file, drive_get_file_metadata
from src.agents.google_doc.tools import google_docs_create, google_docs_update
from src.agents.google_slide.tools import create_presentation, add_slide
from src.agents.time.tools import get_current_time

def build_all_tools() -> List[BaseTool]:
    tools: List[BaseTool] = []
    # Web search
    tools.append(web_research_report)
    # Time/Date tool
    tools.append(get_current_time)
    tools.append(get_weather_by_city)
    # Emails tools
    tools.append(gmail_search)
    tools.append(gmail_edit_draft)
    tools.append(gmail_confirm_send)
    tools.append(gmail_send_email)
    tools.append(gmail_summarize)
    # Google Drive tools
    tools.append(drive_find_file_id)
    tools.append(drive_list_files)
    tools.append(drive_delete_file)
    tools.append(drive_get_file_metadata)
    # Google Docs tools
    tools.append(google_docs_create)
    tools.append(google_docs_update)
    # Google Slides tools
    tools.append(create_presentation)
    tools.append(add_slide)
    
    return tools