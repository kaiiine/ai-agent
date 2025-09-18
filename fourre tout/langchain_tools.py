import os
import asyncio
import requests
from langchain.tools import tool
from langchain_ollama import ChatOllama
from langchain.agents import initialize_agent, AgentType
from langchain.prompts import ChatPromptTemplate
from configs.config import GEOCODE_CONFIG
import warnings
from langchain_core._api.deprecation import LangChainDeprecationWarning
warnings.filterwarnings("ignore", category=LangChainDeprecationWarning)


OLLAMA_MODEL = "mistral:latest"

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


@tool
def get_weather_by_city(city: str) -> dict:
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


tools = [get_weather_by_city]

prompt = ChatPromptTemplate.from_messages([
    ("system",
     "You are a helpful weather assistant. "
     "Never print your chain-of-thought or tool JSON. "
     "Use tools when a city is mentioned: call get_coordinates(city) then get_weather(latitude, longitude). "
     "Only print the final answer."),
    ("human", "{input}"),
    ("placeholder", "{agent_scratchpad}"),
])

llm = ChatOllama(model=OLLAMA_MODEL, streaming=True, temperature=0)

# Agent ReAct **structuré** (accepte des tools multi-arguments)
agent_executor = initialize_agent(
    tools=tools,
    llm=llm,
    agent=AgentType.STRUCTURED_CHAT_ZERO_SHOT_REACT_DESCRIPTION,
    handle_parsing_errors=True,
    verbose=False,
    max_iterations=4,
)

async def main():
    in_tool = False
    printed_research = False
    printing_enabled = False
    pretool_buffer = []

    async for event in agent_executor.astream_events(
        {"input": "What's the weather like in Vaasa today?"},
        version="v2",
    ):
        et = event["event"]

        # tokens LLM
        if et == "on_chat_model_stream":
            text = event["data"]["chunk"].content or ""
            if in_tool:
                continue               # ne rien montrer pendant les tools
            if printing_enabled:
                print(text, end="", flush=True)   # stream de la réponse finale
            else:
                pretool_buffer.append(text)       # on bufferise avant d'être sûr

        elif et == "on_tool_start":
            in_tool = True
            if not printed_research:
                print("recherche d'information", flush=True)
                printed_research = True
            pretool_buffer = []        # on jette ce qui a été dit avant l'outil

        elif et == "on_tool_end":
            in_tool = False
            printing_enabled = True     # à partir de maintenant : streamer la réponse

    # Aucun outil utilisé ? on imprime le buffer (réponse unique)
    if not printing_enabled and pretool_buffer:
        print("".join(pretool_buffer), end="", flush=True)

if __name__ == "__main__":
    asyncio.run(main())

