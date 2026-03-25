# src/agents/util/time_tools.py
from __future__ import annotations
from datetime import datetime
from zoneinfo import ZoneInfo
from langchain_core.tools import tool

@tool("get_current_time")
def get_current_time(timezone: str = "Europe/Paris") -> dict:
    """
    Retourne la date et l'heure actuelle précise pour un fuseau horaire donné.

    Utilise ce tool quand l'utilisateur veut :
    - connaître la date ou l'heure actuelle
    - savoir quel jour on est aujourd'hui
    - calculer des délais à partir d'une date précise

    Mots-clés : heure, date, aujourd'hui, maintenant, fuseau horaire, jour, année, temps

    Ne jamais inventer la date : utiliser ce tool quand la date/année du moment est requise.

    Args:
      timezone: ex. "Europe/Paris"
    Returns:
      {"iso": "...", "date": "YYYY-MM-DD", "time": "HH:MM:SS", "year": 2025, "tz": "Europe/Paris"}
    """
    now = datetime.now(ZoneInfo(timezone))
    return {
        "iso": now.isoformat(timespec="seconds"),
        "date": now.date().isoformat(),
        "time": now.time().strftime("%H:%M:%S"),
        "year": now.year,
        "tz": timezone,
    }
