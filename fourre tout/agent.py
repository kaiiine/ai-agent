from langgraph.prebuilt import create_react_agent
from langchain_ollama import ChatOllama
from langchain.tools import tool
from langchain_core.messages import AIMessageChunk
from configs.config import GEOCODE_CONFIG
from langgraph.checkpoint.memory import InMemorySaver
import requests
from pydantic import BaseModel

# --- Modèle Ollama ---
llm = ChatOllama(model="mistral:latest", temperature=0, streaming=True)
checkpointer = InMemorySaver()
config = {"configurable": {"thread_id": "1"}}
class WeatherResponse(BaseModel):
    conditions: str
    temperature: float
    wind_speed: float


# --- Tool déclaré proprement ---
@tool
def get_weather(city: str) -> dict:
    """Retourne la météo actuelle pour une ville (lookup coords interne)."""
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

# --- Agent LangGraph ---
agent = create_react_agent(
    model=llm,
    tools=[get_weather],
    prompt="You are a helpful assistant.",  # <- remplace 'prompt'
    checkpointer=checkpointer,
    response_format=WeatherResponse,
)


def stream_agent(agent, user_input: str, thread_id: str):
    """
    Lance un agent LangGraph en streaming et affiche UNIQUEMENT
    la réponse de l'assistant en temps réel (token par token).
    """
    for msg, _ in agent.stream(
        {"messages": [{"role": "user", "content": user_input}]},
        stream_mode="messages",
        config={"configurable": {"thread_id": thread_id}},
    ):
        # Cas 1: message = AIMessageChunk (stream token par token)
        if isinstance(msg, AIMessageChunk):
            print(msg.content, end="", flush=True)

        # Cas 2: message complet (si pas de streaming ou chunk final)
        else:
            role = getattr(msg, "type", None) or getattr(msg, "role", None)
            if role == "ai":
                print(getattr(msg, "content", ""), end="", flush=True)

    print("")

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



stream_agent(agent, "What's the weather like in Vaasa today?", thread_id="conv-1")
response = agent.invoke(
    {"messages": [{"role": "user", "content": "what is the weather in sf"}]},
    {"configurable": {"thread_id": "1"}}
)

response["structured_response"]
