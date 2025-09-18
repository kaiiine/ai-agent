from dotenv import load_dotenv
import os
load_dotenv()

# === GEOCODE CONFIG ===

GEOCODE_CONFIG = {
    "url": "https://maps.googleapis.com/maps/api/geocode/json",
    "params": {
        "address": "{address}",
        "key": os.getenv("GOOGLE_API_KEY"),
    },
}