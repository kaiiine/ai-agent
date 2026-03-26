"""
Weather tools for agents.
"""
from configs.config import GEOCODE_CONFIG
import requests
from langchain.tools import tool

# 1) Un SEUL tool (coordonnées + météo)
def get_coordinates(city: str) -> dict:
    """
    Utilise Google Geocoding API pour obtenir la latitude/longitude d'une ville.
    """
    params = GEOCODE_CONFIG["params"].copy()
    params["address"] = city

    r = requests.get(
        url=GEOCODE_CONFIG["url"],
        params=params,
        timeout=5
        )
    r.raise_for_status()
    data = r.json()
    if data["status"] != "OK" or not data.get("results"):
        return {"error": f"Ville '{city}' introuvable (status: {data['status']})"}

    location = data["results"][0]["geometry"]["location"]
    return {"latitude": location["lat"], "longitude": location["lng"]}


# --------------------------------------------------------------
# Step 2: Define the tools
# --------------------------------------------------------------

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
    coords = get_coordinates(city)
    lat, lon = coords["latitude"], coords["longitude"]
    r = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": lat,
            "longitude": lon,
            "current": "temperature_2m,wind_speed_10m",
        },
        timeout=6, 
    )
    r.raise_for_status()
    cur = r.json().get("current", {})
    return {"city": city, "latitude": lat, "longitude": lon, **cur}

EXPORT_TOOLS = [get_weather_by_city]