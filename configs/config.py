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

MAIL_SETTINGS = {
    "imap_host": os.getenv("IMAP_HOST"),
    "imap_user": os.getenv("IMAP_USER"),
    "imap_password": os.getenv("IMAP_PASSWORD"),
    "imap_folder": "INBOX",
    "smtp_host": "smtp.gmail.com",
    "smtp_port": 587
}   