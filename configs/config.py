from dotenv import load_dotenv
from pathlib import Path
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

MAIL_SETTINGS = {
    "imap_host": os.getenv("IMAP_HOST"),
    "imap_user": os.getenv("IMAP_USER"),
    "imap_password": os.getenv("IMAP_PASSWORD"),
    "imap_folder": "INBOX",
    "smtp_host": "smtp.gmail.com",
    "smtp_port": 587
}   

IMAGE_SETTINGS = {
    "realistic_model": Path("models/realistic-vision-v6/Realistic_Vision_V6.0_NV_B1.safetensors").resolve(),
    "realistic_model_dir": Path("models/realistic-vision-v6").resolve(),
    "fantasy_model": Path("models/openjourney/openjourney-v4.safetensors").resolve(),
    "fantasy_model_dir": Path("models/openjourney").resolve(),
    "vae": "./models/sd-vae-ft-ema"

}

DOWNLOAD_SETTINGS = {
    "openjourney_download_dir": Path("models/openjourney").resolve(),
    "realistic_vision_download_dir": Path("models/realistic-vision-v6").resolve(),
    "openjourney_repo": "prompthero/openjourney-v4",
    "realistic_vision_repo": "SG161222/Realistic_Vision_V6.0_B1_noVAE",
}