"""Météo d'une ville — actuelle ET prévue, par Open-Meteo (sans clé d'API).

Ce module ne demandait que `current=`. Axon appelait donc son propre outil pour
« quelle est la météo de demain ? », recevait la température de l'instant, ne
pouvait rien en conclure, et repartait fouiller le web — trois recherches et
trois `grep` pour une question à laquelle Open-Meteo répond en un appel. Le
symptôme se lisait comme un défaut de raisonnement ; c'était un défaut d'outil.

Deux conséquences dans la façon dont ce fichier est écrit :

  · les prévisions sont TOUJOURS jointes, jamais derrière un paramètre. Un
    argument optionnel n'existe que si le modèle pense à le passer, et le
    problème d'origine est précisément qu'il ne savait pas qu'il pouvait ;
  · les codes météo de l'OMM sont traduits ici. Renvoyer « weathercode: 61 »
    revient à demander au modèle de deviner — et deviner, sur des données, c'est
    inventer.
"""
from datetime import date, timedelta

import requests
from langchain.tools import tool

#: Assez pour « demain » et « ce week-end », qui sont les deux questions posées.
#: Au-delà, les prévisions perdent leur valeur et allongent la réponse.
_JOURS = 7

_DELAI_S = 8

#: Les codes de temps de l'OMM, tels qu'Open-Meteo les rend. Traduits ici parce
#: qu'un entier nu oblige le modèle à deviner ce qu'il désigne.
_TEMPS: dict[int, str] = {
    0: "ciel dégagé", 1: "plutôt dégagé", 2: "partiellement nuageux", 3: "couvert",
    45: "brouillard", 48: "brouillard givrant",
    51: "bruine légère", 53: "bruine", 55: "bruine dense",
    56: "bruine verglaçante", 57: "bruine verglaçante dense",
    61: "pluie faible", 63: "pluie", 65: "forte pluie",
    66: "pluie verglaçante", 67: "forte pluie verglaçante",
    71: "neige faible", 73: "neige", 75: "forte neige", 77: "grains de neige",
    80: "averses faibles", 81: "averses", 82: "averses violentes",
    85: "averses de neige", 86: "fortes averses de neige",
    95: "orage", 96: "orage et grêle", 99: "orage et forte grêle",
}


def _libelle(code) -> str:
    """Le temps qu'il fait, en toutes lettres."""
    try:
        return _TEMPS.get(int(code), "conditions inhabituelles")
    except (TypeError, ValueError):
        return ""


def _coordonnees(ville: str) -> dict:
    r = requests.get(
        "https://geocoding-api.open-meteo.com/v1/search",
        params={"name": ville, "count": 1, "language": "fr", "format": "json"},
        timeout=_DELAI_S,
    )
    r.raise_for_status()
    resultats = r.json().get("results")
    if not resultats:
        return {"error": f"Ville '{ville}' introuvable"}
    lieu = resultats[0]
    return {
        "latitude": lieu["latitude"],
        "longitude": lieu["longitude"],
        "name": lieu.get("name", ville),
        "country": lieu.get("country", ""),
    }


def _jours(brut: dict) -> list[dict]:
    """Les prévisions quotidiennes, une entrée par jour.

    Chaque jour porte son étiquette (`aujourd'hui`, `demain`) : sans elle, le
    modèle doit faire de l'arithmétique de dates pour répondre à « demain », et
    c'est exactement là qu'il s'est trompé puis rabattu sur le web.
    """
    table = brut.get("daily") or {}
    dates = table.get("time") or []
    aujourd_hui = date.today()
    demain = aujourd_hui + timedelta(days=1)

    def colonne(nom: str, i: int):
        valeurs = table.get(nom) or []
        return valeurs[i] if i < len(valeurs) else None

    sortie: list[dict] = []
    for i, jour in enumerate(dates):
        etiquette = ""
        if jour == aujourd_hui.isoformat():
            etiquette = "aujourd'hui"
        elif jour == demain.isoformat():
            etiquette = "demain"
        sortie.append({
            "date": jour,
            "quand": etiquette,
            "temps": _libelle(colonne("weathercode", i)),
            "temp_min_c": colonne("temperature_2m_min", i),
            "temp_max_c": colonne("temperature_2m_max", i),
            "precipitation_mm": colonne("precipitation_sum", i),
            "risque_pluie_pct": colonne("precipitation_probability_max", i),
            "vent_max_kmh": colonne("wind_speed_10m_max", i),
        })
    return sortie


#: DEUX appels au lieu d'un, et c'est délibéré. Mesuré sur Suresnes, au même
#: instant, pour le 19 août :
#:
#:     daily seul                  → 0.63 mm   (code 61, « pluie faible »)
#:     daily + current dans le même → 16.4 mm   (code 61, mêmes températures)
#:
#: N'IMPORTE quel champ `current` suffit à faire basculer la valeur, et le cumul
#: horaire bascule avec elle : Open-Meteo ne corrompt pas la réponse, il change
#: de modèle quand on lui demande l'instant présent. Les deux séries sont donc
#: justes chacune pour son modèle — mais mélangées dans un seul appel, le chiffre
#: rendu dépend d'un couplage invisible, et un facteur 26 sur la pluie annoncée
#: est exactement ce qui fait qu'on cesse de croire l'outil.
#:
#: Séparer les deux requêtes rend chaque réponse canonique pour sa forme. Le coût
#: est un aller-retour de plus, sur une API gratuite et sans clé.


def _prevoir(lat: float, lon: float) -> dict:
    """Les prévisions quotidiennes. Sans `current` — voir la note ci-dessus."""
    r = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": lat,
            "longitude": lon,
            "daily": "weathercode,temperature_2m_max,temperature_2m_min,"
                     "precipitation_sum,precipitation_probability_max,"
                     "wind_speed_10m_max",
            "forecast_days": _JOURS,
            # Sans ça, Open-Meteo répond en UTC et « demain » peut désigner le
            # mauvais jour selon l'heure — le genre d'erreur qu'on ne voit pas.
            "timezone": "auto",
        },
        timeout=_DELAI_S + 4,
    )
    r.raise_for_status()
    return r.json()


def _maintenant(lat: float, lon: float) -> dict:
    """Les conditions de l'instant. Un échec ici ne doit pas emporter les
    prévisions : c'est la réponse à « demain » qui est demandée."""
    try:
        r = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": lat,
                "longitude": lon,
                "current": "temperature_2m,wind_speed_10m,precipitation,weathercode",
                "timezone": "auto",
            },
            timeout=_DELAI_S,
        )
        r.raise_for_status()
        return r.json().get("current", {}) or {}
    except Exception:                                            # noqa: BLE001
        return {}


@tool
def get_weather_by_city(city: str) -> dict:
    """
    Météo complète d'une ville : conditions actuelles ET prévisions sur 7 jours.

    Utilise ce tool — et PAS une recherche web — dès qu'il s'agit du temps qu'il
    fait ou qu'il fera quelque part :
    - la météo maintenant, aujourd'hui, demain, après-demain, ce week-end
    - va-t-il pleuvoir, neiger, faire chaud ou froid, y aura-t-il du vent
    - les températures min et max d'un jour à venir
    - planifier une sortie, un trajet ou un voyage selon le temps

    Les prévisions sont renvoyées d'office : le champ `previsions` contient une
    entrée par jour, et le jour de demain y porte `"quand": "demain"`. Aucun
    second appel ni aucune recherche web n'est nécessaire pour l'obtenir.

    Mots-clés : météo, temps, température, prévisions, pluie, neige, soleil,
    vent, orage, climat, aujourd'hui, demain, week-end, semaine.
    """
    coords = _coordonnees(city)
    if "error" in coords:
        return coords

    lat, lon = coords["latitude"], coords["longitude"]
    brut = _prevoir(lat, lon)
    actuel = _maintenant(lat, lon)

    return {
        "city": coords["name"],
        "country": coords["country"],
        "latitude": lat,
        "longitude": lon,
        **actuel,
        "temps_actuel": _libelle(actuel.get("weathercode")),
        "previsions": _jours(brut),
        "source": "Open-Meteo",
    }


EXPORT_TOOLS = [get_weather_by_city]
