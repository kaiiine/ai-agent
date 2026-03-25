from datetime import datetime, timezone
from typing import Optional, Dict, Any
from langchain_core.tools import tool
from googleapiclient.errors import HttpError
from src.infra.google_auth import get_calendar_service


def _iso(dt: str) -> str:
    """Normalise une date/heure en RFC3339 si ce n'est pas déjà le cas."""
    if "T" not in dt:
        return f"{dt}T00:00:00Z"
    if not dt.endswith("Z") and "+" not in dt[-6:]:
        return dt + "Z"
    return dt


@tool("calendar_list_events")
def calendar_list_events(
    days_ahead: int = 7,
    max_results: int = 20,
    calendar_id: str = "primary",
) -> Dict[str, Any]:
    """
    Liste les prochains événements du calendrier Google pour les X prochains jours.

    Utilise ce tool quand l'utilisateur veut :
    - voir ses rendez-vous à venir
    - consulter son agenda ou planning
    - savoir ce qu'il a cette semaine ou ce mois-ci

    Mots-clés : calendrier, agenda, rendez-vous, événement, planning, semaine, Google Calendar

    Args:
        days_ahead: nombre de jours à venir à afficher (défaut 7)
        max_results: nombre max d'événements (défaut 20)
        calendar_id: ID du calendrier (défaut "primary")
    Returns:
        {"status": "ok", "events": [{"id", "title", "start", "end", "location", "description", "link"}, ...]}
    """
    svc = get_calendar_service()
    try:
        now = datetime.now(timezone.utc)
        from datetime import timedelta
        time_max = now + timedelta(days=days_ahead)

        resp = svc.events().list(
            calendarId=calendar_id,
            timeMin=now.isoformat(),
            timeMax=time_max.isoformat(),
            maxResults=max_results,
            singleEvents=True,
            orderBy="startTime",
        ).execute()

        events = []
        for e in resp.get("items", []):
            start = e.get("start", {})
            end = e.get("end", {})
            events.append({
                "id": e["id"],
                "title": e.get("summary", "(sans titre)"),
                "start": start.get("dateTime") or start.get("date"),
                "end": end.get("dateTime") or end.get("date"),
                "location": e.get("location"),
                "description": e.get("description"),
                "link": e.get("htmlLink"),
                "all_day": "date" in start,
            })
        return {"status": "ok", "count": len(events), "events": events}
    except HttpError as e:
        return {"status": "error", "error": str(e)}


@tool("calendar_create_event")
def calendar_create_event(
    title: str,
    start: str,
    end: str,
    description: Optional[str] = None,
    location: Optional[str] = None,
    attendees: Optional[list] = None,
    calendar_id: str = "primary",
) -> Dict[str, Any]:
    """
    Crée un nouvel événement dans Google Calendar. Toujours demander confirmation avant.

    Utilise ce tool quand l'utilisateur veut :
    - ajouter un rendez-vous dans son agenda
    - planifier une réunion, un rappel ou un événement
    - créer un créneau dans Google Calendar

    Mots-clés : créer événement, agenda, rendez-vous, planifier, réunion, calendrier, Google Calendar

    Args:
        title: titre de l'événement
        start: date/heure de début en ISO 8601 (ex: "2026-03-20T14:00:00" ou "2026-03-20")
        end: date/heure de fin en ISO 8601
        description: description optionnelle
        location: lieu optionnel
        attendees: liste d'emails à inviter (ex: ["alice@gmail.com"])
        calendar_id: ID du calendrier (défaut "primary")
    Returns:
        {"status": "ok", "event_id": "...", "title": "...", "link": "..."}
    """
    svc = get_calendar_service()
    try:
        is_all_day = "T" not in start
        if is_all_day:
            start_obj = {"date": start[:10]}
            end_obj = {"date": end[:10]}
        else:
            tz = "Europe/Paris"
            start_obj = {"dateTime": _iso(start), "timeZone": tz}
            end_obj = {"dateTime": _iso(end), "timeZone": tz}

        body: Dict[str, Any] = {
            "summary": title,
            "start": start_obj,
            "end": end_obj,
        }
        if description:
            body["description"] = description
        if location:
            body["location"] = location
        if attendees:
            body["attendees"] = [{"email": a} for a in attendees]

        event = svc.events().insert(calendarId=calendar_id, body=body).execute()
        return {
            "status": "ok",
            "event_id": event["id"],
            "title": event.get("summary"),
            "start": event.get("start"),
            "end": event.get("end"),
            "link": event.get("htmlLink"),
        }
    except HttpError as e:
        return {"status": "error", "error": str(e)}


@tool("calendar_update_event")
def calendar_update_event(
    event_id: str,
    title: Optional[str] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    description: Optional[str] = None,
    location: Optional[str] = None,
    calendar_id: str = "primary",
) -> Dict[str, Any]:
    """
    Modifie un événement existant dans Google Calendar (titre, horaire, lieu).

    Utilise ce tool quand l'utilisateur veut :
    - changer l'heure ou le titre d'un rendez-vous
    - modifier un événement déjà créé
    - reporter ou déplacer une réunion

    Mots-clés : modifier événement, changer rendez-vous, reporter, déplacer réunion, calendrier

    Args:
        event_id: ID de l'événement (obtenu via calendar_list_events)
        title: nouveau titre (optionnel)
        start: nouvelle date/heure de début (optionnel)
        end: nouvelle date/heure de fin (optionnel)
        description: nouvelle description (optionnel)
        location: nouveau lieu (optionnel)
        calendar_id: ID du calendrier (défaut "primary")
    """
    svc = get_calendar_service()
    try:
        event = svc.events().get(calendarId=calendar_id, eventId=event_id).execute()

        if title:
            event["summary"] = title
        if description is not None:
            event["description"] = description
        if location is not None:
            event["location"] = location
        if start:
            is_all_day = "T" not in start
            if is_all_day:
                event["start"] = {"date": start[:10]}
            else:
                event["start"] = {"dateTime": _iso(start), "timeZone": "Europe/Paris"}
        if end:
            is_all_day = "T" not in end
            if is_all_day:
                event["end"] = {"date": end[:10]}
            else:
                event["end"] = {"dateTime": _iso(end), "timeZone": "Europe/Paris"}

        updated = svc.events().update(calendarId=calendar_id, eventId=event_id, body=event).execute()
        return {
            "status": "ok",
            "event_id": updated["id"],
            "title": updated.get("summary"),
            "start": updated.get("start"),
            "end": updated.get("end"),
            "link": updated.get("htmlLink"),
        }
    except HttpError as e:
        return {"status": "error", "error": str(e)}


@tool("calendar_delete_event")
def calendar_delete_event(
    event_id: str,
    calendar_id: str = "primary",
) -> Dict[str, Any]:
    """
    Supprime un événement du calendrier. Toujours demander confirmation explicite avant.

    Utilise ce tool quand l'utilisateur veut :
    - annuler un rendez-vous
    - supprimer un événement de son agenda
    - effacer une réunion du calendrier

    Mots-clés : supprimer événement, annuler rendez-vous, effacer, calendrier, Google Calendar

    Args:
        event_id: ID de l'événement
        calendar_id: ID du calendrier (défaut "primary")
    """
    svc = get_calendar_service()
    try:
        svc.events().delete(calendarId=calendar_id, eventId=event_id).execute()
        return {"status": "ok", "message": f"Événement {event_id} supprimé."}
    except HttpError as e:
        return {"status": "error", "error": str(e)}


@tool("calendar_list_calendars")
def calendar_list_calendars() -> Dict[str, Any]:
    """
    Liste tous les calendriers Google accessibles (personnel, partagés, etc.).

    Utilise ce tool quand l'utilisateur veut :
    - voir ses calendriers Google disponibles
    - trouver l'ID d'un calendrier secondaire
    - savoir quels agendas sont accessibles

    Mots-clés : liste calendriers, agendas, Google Calendar, calendriers disponibles, ID calendrier

    Returns:
        {"status": "ok", "calendars": [{"id", "name", "primary", "color"}, ...]}
    """
    svc = get_calendar_service()
    try:
        resp = svc.calendarList().list().execute()
        calendars = [
            {
                "id": c["id"],
                "name": c.get("summary"),
                "primary": c.get("primary", False),
                "color": c.get("backgroundColor"),
                "access_role": c.get("accessRole"),
            }
            for c in resp.get("items", [])
        ]
        return {"status": "ok", "calendars": calendars}
    except HttpError as e:
        return {"status": "error", "error": str(e)}


@tool("calendar_search_events")
def calendar_search_events(
    query: str,
    max_results: int = 10,
    calendar_id: str = "primary",
) -> Dict[str, Any]:
    """
    Recherche des événements Google Calendar par mot-clé dans le titre ou la description.

    Utilise ce tool quand l'utilisateur veut :
    - retrouver un événement par son nom ou contenu
    - chercher un rendez-vous spécifique dans l'agenda
    - trouver quand a lieu une réunion précise

    Mots-clés : chercher événement, trouver rendez-vous, calendrier, recherche, agenda

    Args:
        query: mot-clé à rechercher
        max_results: nombre max de résultats
        calendar_id: ID du calendrier (défaut "primary")
    """
    svc = get_calendar_service()
    try:
        now = datetime.now(timezone.utc).isoformat()
        resp = svc.events().list(
            calendarId=calendar_id,
            q=query,
            timeMin=now,
            maxResults=max_results,
            singleEvents=True,
            orderBy="startTime",
        ).execute()

        events = []
        for e in resp.get("items", []):
            start = e.get("start", {})
            events.append({
                "id": e["id"],
                "title": e.get("summary", "(sans titre)"),
                "start": start.get("dateTime") or start.get("date"),
                "link": e.get("htmlLink"),
            })
        return {"status": "ok", "count": len(events), "events": events}
    except HttpError as e:
        return {"status": "error", "error": str(e)}
