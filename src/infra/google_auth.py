# src/infra/google_auth.py
from __future__ import annotations
import json, pickle
from pathlib import Path
from typing import Sequence, Set
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

# === SETTIGNS ===
PROJECT_ROOT = Path(__file__).resolve().parents[2]
CREDENTIALS_PATH = (PROJECT_ROOT / "gcp-oauth.keys.json").resolve()
TOKEN_PATH = Path.home() / ".ai-agent" / "google_token.pickle"   
TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
SCOPES_GMAIL  = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
]
SCOPES_DOCS   = [
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/drive.file",
]
SCOPES_SLIDES = [
    "https://www.googleapis.com/auth/presentations",
    "https://www.googleapis.com/auth/drive.file",
]
SCOPES_SHEETS = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file",
]
SCOPES_DRIVE = [
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/drive.metadata.readonly",
]
SCOPES_ALL: list[str] = list({
    *SCOPES_GMAIL, *SCOPES_DOCS, *SCOPES_SLIDES, *SCOPES_SHEETS, *SCOPES_DRIVE
})

def _load_credentials(scopes: Sequence[str]):
    creds = None
    if TOKEN_PATH.exists():
        with open(TOKEN_PATH, "rb") as f:
            creds = pickle.load(f)

    current: Set[str] = set(getattr(creds, "scopes", []) or [])

    need_flow = (
        (creds is None)
        or (not creds.valid and not getattr(creds, "refresh_token", None))
        or (not set(scopes).issubset(current))
    )

    if need_flow:
        if not CREDENTIALS_PATH.exists():
            raise FileNotFoundError(f"Credentials introuvables: {CREDENTIALS_PATH}")
        with open(CREDENTIALS_PATH, "r", encoding="utf-8") as f:
            client_config = json.load(f)

        flow = InstalledAppFlow.from_client_config(client_config, SCOPES_ALL)
        creds = creds = flow.run_local_server(port=0, open_browser=False)
        with open(TOKEN_PATH, "wb") as f:
            pickle.dump(creds, f)

    elif not creds.valid and getattr(creds, "refresh_token", None):
        creds.refresh(Request())
        with open(TOKEN_PATH, "wb") as f:
            pickle.dump(creds, f)

    return creds

def get_service(api: str, version: str, scopes: Sequence[str]):
    creds = _load_credentials(scopes)
    return build(api, version, credentials=creds)


def get_gmail_service():
    return get_service("gmail", "v1", SCOPES_GMAIL)

def get_docs_service():
    return get_service("docs", "v1", SCOPES_DOCS)

def get_slides_service():
    return get_service("slides", "v1", SCOPES_SLIDES)

def get_sheets_service():
    return get_service("sheets", "v4", SCOPES_SHEETS)

def get_drive_service():
    return get_service("drive", "v3", SCOPES_DRIVE)
