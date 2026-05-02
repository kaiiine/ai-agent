"""Tests for src/agents/time/tools.py and src/agents/weather/tools.py."""
import pytest
from unittest.mock import patch, MagicMock


# ── get_current_time ──────────────────────────────────────────────────────────

def test_current_time_returns_required_fields():
    from src.agents.time.tools import get_current_time
    result = get_current_time.invoke({"timezone": "Europe/Paris"})
    assert "iso" in result
    assert "date" in result
    assert "time" in result
    assert "year" in result
    assert "tz" in result


def test_current_time_date_format():
    from src.agents.time.tools import get_current_time
    import re
    result = get_current_time.invoke({"timezone": "Europe/Paris"})
    assert re.match(r"\d{4}-\d{2}-\d{2}", result["date"])


def test_current_time_time_format():
    from src.agents.time.tools import get_current_time
    import re
    result = get_current_time.invoke({"timezone": "Europe/Paris"})
    assert re.match(r"\d{2}:\d{2}:\d{2}", result["time"])


def test_current_time_iso_format():
    from src.agents.time.tools import get_current_time
    result = get_current_time.invoke({"timezone": "UTC"})
    # Should be parseable as ISO 8601
    from datetime import datetime
    datetime.fromisoformat(result["iso"])


def test_current_time_year_is_int():
    from src.agents.time.tools import get_current_time
    result = get_current_time.invoke({"timezone": "Europe/Paris"})
    assert isinstance(result["year"], int)
    assert result["year"] >= 2024


def test_current_time_tz_echoed_back():
    from src.agents.time.tools import get_current_time
    result = get_current_time.invoke({"timezone": "America/New_York"})
    assert result["tz"] == "America/New_York"


def test_current_time_different_timezones_differ():
    from src.agents.time.tools import get_current_time
    paris = get_current_time.invoke({"timezone": "Europe/Paris"})
    ny = get_current_time.invoke({"timezone": "America/New_York"})
    # ISO strings will differ (different offset)
    assert paris["iso"] != ny["iso"]


def test_current_time_invalid_timezone():
    from src.agents.time.tools import get_current_time
    with pytest.raises(Exception):
        get_current_time.invoke({"timezone": "Invalid/Zone"})


def test_current_time_default_timezone():
    from src.agents.time.tools import get_current_time
    # Should work without explicit timezone (uses Europe/Paris default)
    result = get_current_time.invoke({})
    assert result["tz"] == "Europe/Paris"


# ── get_weather_by_city ───────────────────────────────────────────────────────

def _mock_geo_response(city="Paris", lat=48.8566, lon=2.3522, country="France"):
    mock = MagicMock()
    mock.json.return_value = {"results": [{"latitude": lat, "longitude": lon,
                                            "name": city, "country": country}]}
    mock.raise_for_status = MagicMock()
    return mock


def _mock_weather_response(temp=18.0, wind=10.5, precip=0.0, code=0):
    mock = MagicMock()
    mock.json.return_value = {
        "current": {
            "temperature_2m": temp,
            "wind_speed_10m": wind,
            "precipitation": precip,
            "weathercode": code,
        }
    }
    mock.raise_for_status = MagicMock()
    return mock


def test_weather_returns_city_data():
    from src.agents.weather.tools import get_weather_by_city

    with patch("requests.get") as mock_get:
        mock_get.side_effect = [
            _mock_geo_response("Paris", 48.8566, 2.3522),
            _mock_weather_response(22.0),
        ]
        result = get_weather_by_city.invoke({"city": "Paris"})

    assert result["city"] == "Paris"
    assert result["country"] == "France"
    assert result["temperature_2m"] == 22.0


def test_weather_city_not_found():
    from src.agents.weather.tools import get_weather_by_city

    mock = MagicMock()
    mock.json.return_value = {"results": []}
    mock.raise_for_status = MagicMock()

    with patch("requests.get", return_value=mock):
        result = get_weather_by_city.invoke({"city": "ZZZNonexistentCity999"})

    assert "error" in result


def test_weather_returns_coordinates():
    from src.agents.weather.tools import get_weather_by_city

    with patch("requests.get") as mock_get:
        mock_get.side_effect = [
            _mock_geo_response("Lyon", 45.75, 4.85),
            _mock_weather_response(15.0),
        ]
        result = get_weather_by_city.invoke({"city": "Lyon"})

    assert "latitude" in result
    assert "longitude" in result
    assert result["latitude"] == 45.75


def test_weather_includes_wind_and_precip():
    from src.agents.weather.tools import get_weather_by_city

    with patch("requests.get") as mock_get:
        mock_get.side_effect = [
            _mock_geo_response(),
            _mock_weather_response(temp=10.0, wind=25.0, precip=2.5),
        ]
        result = get_weather_by_city.invoke({"city": "Brest"})

    assert result["wind_speed_10m"] == 25.0
    assert result["precipitation"] == 2.5


def test_weather_geo_api_error():
    from src.agents.weather.tools import get_weather_by_city

    with patch("requests.get", side_effect=Exception("Network error")):
        with pytest.raises(Exception):
            get_weather_by_city.invoke({"city": "Paris"})


def test_weather_forecast_api_error():
    from src.agents.weather.tools import get_weather_by_city

    def side_effects(url, **kwargs):
        if "geocoding" in url:
            return _mock_geo_response()
        raise Exception("Forecast API down")

    with patch("requests.get", side_effect=side_effects):
        with pytest.raises(Exception):
            get_weather_by_city.invoke({"city": "Paris"})


def test_weather_different_cities():
    from src.agents.weather.tools import get_weather_by_city

    with patch("requests.get") as mock_get:
        mock_get.side_effect = [
            _mock_geo_response("Tokyo", 35.6762, 139.6503, "Japan"),
            _mock_weather_response(28.0),
        ]
        result = get_weather_by_city.invoke({"city": "Tokyo"})

    assert result["city"] == "Tokyo"
    assert result["country"] == "Japan"
