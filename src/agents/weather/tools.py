"""
Weather tools for agents — fully powered by Open-Meteo (no API key required).
"""
import requests
from langchain.tools import tool


def _get_coordinates(city: str) -> dict:
    r = requests.get(
        "https://geocoding-api.open-meteo.com/v1/search",
        params={"name": city, "count": 1, "language": "fr", "format": "json"},
        timeout=5,
    )
    r.raise_for_status()
    results = r.json().get("results")
    if not results:
        return {"error": f"Ville '{city}' introuvable"}
    loc = results[0]
    return {
        "latitude": loc["latitude"],
        "longitude": loc["longitude"],
        "name": loc.get("name", city),
        "country": loc.get("country", ""),
    }


@tool
def get_weather_by_city(city: str) -> dict:
    """
    Retourne la météo actuelle (température, vent) pour n'importe quelle ville.

    Utilise ce tool quand l'utilisateur veut :
    - connaître la météo d'une ville aujourd'hui
    - savoir s'il va pleuvoir, faire chaud ou froid quelque part
    - consulter la température actuelle d'un lieu
    - planifier une sortie ou un voyage selon la météo

    Mots-clés : météo, temps, température, pluie, soleil, vent, ville, climat, aujourd'hui
    """
    coords = _get_coordinates(city)
    if "error" in coords:
        return coords

    lat, lon = coords["latitude"], coords["longitude"]
    r = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": lat,
            "longitude": lon,
            "current": "temperature_2m,wind_speed_10m,precipitation,weathercode",
        },
        timeout=6,
    )
    r.raise_for_status()
    cur = r.json().get("current", {})
    return {
        "city": coords["name"],
        "country": coords["country"],
        "latitude": lat,
        "longitude": lon,
        **cur,
    }


EXPORT_TOOLS = [get_weather_by_city]
