"""L'outil météo doit répondre à « demain » — sinon Axon repart sur le web.

Symptôme observé, sur « Quelle est la météo de demain ? » :

    ✓  searching       météo Suresnes demain mercredi 19 août 2026
    ✓  get_weather_by_city
    ✓  searching       "Suresnes" météo prévisions mercredi 19 août
    ✓  searching       météo Hauts-de-Seine mercredi 19 août 2026
    ✓  running         … | grep -E "(demain|19 août|pluie|°C)" | head -40

Axon avait appelé son propre outil, et l'outil avait répondu — mais avec la
température de l'INSTANT, parce que la requête ne demandait que `current=`. Le
modèle ne pouvait rien en tirer pour demain, et se rabattait sur le web. Ça se
lisait comme un défaut de raisonnement ; c'était un défaut d'outil.

Ces tests portent donc sur le CONTRAT de l'outil, pas sur le réseau : ils
n'appellent jamais Open-Meteo. Un test qui dépend du ciel réel échouerait un jour
de canicule pour de mauvaises raisons.
"""
from datetime import date, timedelta
from unittest.mock import patch

import pytest

from src.agents.weather import tools as meteo


def _reponse(charge: dict):
    class R:
        def raise_for_status(self): pass
        def json(self): return charge
    return R()


AUJOURD_HUI = date.today()
DEMAIN = AUJOURD_HUI + timedelta(days=1)

PREVISION = {
    "current": {"temperature_2m": 22.5, "wind_speed_10m": 9.0,
                "precipitation": 0.0, "weathercode": 3},
    "daily": {
        "time": [AUJOURD_HUI.isoformat(), DEMAIN.isoformat(),
                 (AUJOURD_HUI + timedelta(days=2)).isoformat()],
        "weathercode": [3, 61, 0],
        "temperature_2m_max": [25.8, 22.2, 26.2],
        "temperature_2m_min": [18.0, 17.7, 16.4],
        "precipitation_sum": [0.0, 0.63, 0.0],
        "precipitation_probability_max": [5, 80, 5],
        "wind_speed_10m_max": [16.7, 13.7, 14.5],
    },
}

GEO = {"results": [{"latitude": 48.87, "longitude": 2.22,
                    "name": "Suresnes", "country": "France"}]}


ACTUEL = {"current": {"temperature_2m": 22.5, "wind_speed_10m": 9.0,
                      "precipitation": 0.0, "weathercode": 3}}


def _appeler(ville="Suresnes", geo=GEO, meteo_brute=PREVISION, actuel=ACTUEL):
    """Trois requêtes : géocodage, prévisions, instant présent — dans cet ordre."""
    with patch.object(meteo.requests, "get",
                      side_effect=[_reponse(geo), _reponse(meteo_brute),
                                   _reponse(actuel)]):
        return meteo.get_weather_by_city.invoke({"city": ville})


# ── Le manque à l'origine du repli sur le web ─────────────────────────────────
def test_la_meteo_de_demain_est_dans_la_reponse():
    """Le cœur du correctif : plus besoin de chercher ailleurs."""
    r = _appeler()

    demain = [j for j in r["previsions"] if j["quand"] == "demain"]
    assert len(demain) == 1
    assert demain[0]["temp_max_c"] == 22.2
    assert demain[0]["risque_pluie_pct"] == 80


def test_demain_est_etiquete_pas_a_calculer():
    """Sans étiquette, le modèle doit faire de l'arithmétique de dates — et
    c'est là qu'il s'est trompé avant d'aller sur le web."""
    r = _appeler()

    assert [j["quand"] for j in r["previsions"][:2]] == ["aujourd'hui", "demain"]


def test_les_previsions_ne_sont_pas_optionnelles():
    """Un paramètre optionnel n'existe que si le modèle pense à le passer, et le
    problème d'origine est justement qu'il ne savait pas qu'il pouvait."""
    import inspect

    signature = inspect.signature(meteo.get_weather_by_city.func)

    assert list(signature.parameters) == ["city"], (
        "les prévisions doivent venir d'office, sans argument à deviner")


def test_la_requete_demande_bien_les_jours():
    """Le défaut exact : la requête ne portait que `current=`."""
    with patch.object(meteo.requests, "get",
                      side_effect=[_reponse(GEO), _reponse(PREVISION),
                                   _reponse(ACTUEL)]) as faux:
        meteo.get_weather_by_city.invoke({"city": "Suresnes"})

    params = faux.call_args_list[1].kwargs["params"]
    assert "daily" in params and params["forecast_days"] >= 2
    assert params["timezone"] == "auto", (
        "en UTC, « demain » peut désigner le mauvais jour selon l'heure")


# ── Ce que le modèle reçoit doit se lire sans deviner ─────────────────────────
def test_la_prevision_ne_demande_jamais_l_instant_present():
    """Mesuré sur Suresnes, au même instant, pour le 19 août :

        daily seul                    → 0.63 mm   (code 61, « pluie faible »)
        daily + current, même requête → 16.4 mm   (code 61, mêmes températures)

    N'importe quel champ `current` suffit à faire basculer la valeur, et le
    cumul horaire bascule avec elle : Open-Meteo change de modèle quand on lui
    demande l'instant présent. Chaque série est juste pour son modèle, mais
    mélangées le chiffre rendu dépend d'un couplage invisible — et Axon a
    annoncé 16,4 mm de pluie là où l'API en prévoit 0,63.
    """
    with patch.object(meteo.requests, "get",
                      side_effect=[_reponse(GEO), _reponse(PREVISION),
                                   _reponse(ACTUEL)]) as faux:
        meteo.get_weather_by_city.invoke({"city": "Suresnes"})

    prevision = faux.call_args_list[1].kwargs["params"]
    instant = faux.call_args_list[2].kwargs["params"]

    assert "current" not in prevision, "le couplage fausse le cumul de pluie"
    assert "daily" not in instant
    assert "current" in instant, "les conditions actuelles restent servies"


def test_un_echec_sur_l_instant_n_emporte_pas_les_previsions():
    """C'est la réponse à « demain » qui est demandée : la perdre parce que
    l'instant présent a échoué serait renvoyer Axon sur le web."""
    with patch.object(meteo.requests, "get",
                      side_effect=[_reponse(GEO), _reponse(PREVISION),
                                   RuntimeError("réseau")]):
        r = meteo.get_weather_by_city.invoke({"city": "Suresnes"})

    assert r["previsions"][1]["quand"] == "demain"
    assert r["previsions"][1]["temp_max_c"] == 22.2


def test_le_code_meteo_est_traduit():
    """« weathercode: 61 » oblige le modèle à deviner — et deviner sur des
    données, c'est inventer."""
    r = _appeler()

    assert r["temps_actuel"] == "couvert"
    assert r["previsions"][1]["temps"] == "pluie faible"


@pytest.mark.parametrize("code, attendu", [
    (0, "ciel dégagé"), (61, "pluie faible"), (95, "orage"), (75, "forte neige"),
])
def test_les_codes_courants_ont_un_libelle(code, attendu):
    assert meteo._libelle(code) == attendu


@pytest.mark.parametrize("code", [None, "", "abc", 4242])
def test_un_code_inconnu_ne_leve_pas(code):
    meteo._libelle(code)


# ── Robustesse ────────────────────────────────────────────────────────────────
def test_une_ville_introuvable_le_dit():
    with patch.object(meteo.requests, "get", return_value=_reponse({"results": []})):
        r = meteo.get_weather_by_city.invoke({"city": "Zzzz"})

    assert "error" in r


def test_une_reponse_sans_jours_ne_leve_pas():
    """Open-Meteo peut renvoyer moins que demandé ; l'outil doit rendre ce qu'il
    a plutôt que de casser le tour."""
    r = _appeler(meteo_brute={})            # prévisions vides
    assert r["previsions"] == []
    assert r["temperature_2m"] == 22.5, "l'instant présent vient de son propre appel"


def test_des_colonnes_incompletes_ne_levent_pas():
    """Une colonne plus courte que `time` ne doit pas faire sauter l'index."""
    tronque = {"current": {}, "daily": {
        "time": [AUJOURD_HUI.isoformat(), DEMAIN.isoformat()],
        "weathercode": [3],
        "temperature_2m_max": [],
    }}
    r = _appeler(meteo_brute=tronque)

    assert len(r["previsions"]) == 2
    assert r["previsions"][1]["temp_max_c"] is None


# ── Ce que le modèle lit pour choisir l'outil ─────────────────────────────────
def test_la_description_annonce_les_previsions():
    """Le modèle choisit sur cette description. Elle disait « météo actuelle …
    aujourd'hui » — il était donc fondé à chercher ailleurs pour demain."""
    doc = meteo.get_weather_by_city.description.lower()

    assert "demain" in doc and "prévisions" in doc
    assert "recherche web" in doc, "il faut dire explicitement de ne PAS chercher"


def test_le_routage_semantique_mene_a_l_outil():
    """La description du groupe doit couvrir « demain », sinon la question
    n'atteint jamais l'outil."""
    from src.orchestrator.tool_retriever import TOOL_GROUPS

    couverture = TOOL_GROUPS["weather"].covers.lower()
    assert "demain" in couverture and "prévisions" in couverture
