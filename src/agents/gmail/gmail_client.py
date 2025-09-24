# src/tools/gmail_client.py
import json, pickle
from pathlib import Path
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
]

# Fichier token (stocké dans le home de l'utilisateur)
TOKEN_PATH = Path.home() / ".gmail_token.pickle"

# Fichier credentials.json à la racine du projet
CREDENTIALS_PATH = Path(__file__).resolve().parent.parent.parent.parent / "gcp-oauth.keys.json"

def get_gmail_service():
    creds = None
    if TOKEN_PATH.exists():
        with open(TOKEN_PATH, "rb") as token:
            creds = pickle.load(token)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CREDENTIALS_PATH.exists():
                raise FileNotFoundError(f"Fichier {CREDENTIALS_PATH} introuvable !")
            with open(CREDENTIALS_PATH, "r") as f:
                client_config = json.load(f)
            flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
            creds = flow.run_local_server(port=0)

        with open(TOKEN_PATH, "wb") as token:
            pickle.dump(creds, token)

    return build("gmail", "v1", credentials=creds)
