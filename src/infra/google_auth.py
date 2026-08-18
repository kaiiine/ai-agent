# src/infra/google_auth.py
from __future__ import annotations
import json, os, pickle, stat
from pathlib import Path
from typing import Sequence, Set
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.auth.exceptions import RefreshError

# === SETTIGNS ===
PROJECT_ROOT = Path(__file__).resolve().parents[2]
CREDENTIALS_PATH = (PROJECT_ROOT / "gcp-oauth.keys.json").resolve()
TOKEN_PATH = Path.home() / ".ai-agent" / "google_token.pickle"


def _restreindre(chemin: Path) -> None:
    """Retire les droits de groupe et d'autrui sur un secret.

    Mesuré sur la machine : le jeton était en 0644 dans un répertoire 0755, donc
    lisible par tout compte local. Il porte `gmail.send`, `documents`,
    `spreadsheets`, `drive.file` et `calendar` — l'exposer revient à exposer la
    boîte mail et le Drive, pas seulement une session.

    Le voisin immédiat suit pourtant la bonne convention : `~/.axon/mcp_servers.json`
    est en 0600. Ce n'était donc pas un choix, mais l'umask par défaut appliqué à
    un `open(..., "wb")` sans mode.

    Le rattrapage vaut pour les fichiers DÉJÀ écrits : sans lui, celui qui existe
    aujourd'hui resterait ouvert indéfiniment, la correction ne valant que pour
    les prochaines écritures.
    """
    try:
        actuel = chemin.stat().st_mode
        if actuel & (stat.S_IRWXG | stat.S_IRWXO):
            chemin.chmod(actuel & ~(stat.S_IRWXG | stat.S_IRWXO))
    except OSError:
        pass


def _ouvrir_prive(chemin: Path):
    """Ouvre en écriture avec 0600 dès la CRÉATION.

    Écrire puis `chmod` laisserait le secret lisible entre les deux appels.
    """
    return os.fdopen(os.open(chemin, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "wb")


# `mode=` de mkdir ne vaut QUE pour une création : sur une machine où le
# répertoire existe déjà — le cas de toute installation antérieure — il reste tel
# qu'il a été créé. Mesuré : 0755 après correction du seul mkdir. D'où le
# resserrement explicite, qui rattrape l'existant.
TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
_restreindre(TOKEN_PATH.parent)

# Les clés client sont le même genre de secret, et le resserrement qui vit dans
# `_load_credentials` ne les atteint que lors d'un NOUVEAU flux OAuth — soit
# presque jamais, une fois le jeton obtenu. Elles resteraient donc en 0644 pour
# toujours. Le fichier est absent sur beaucoup de machines : `_restreindre` s'en
# accommode sans lever.
_restreindre(CREDENTIALS_PATH)


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
#: `drive.file` seul ne donne le CONTENU que des fichiers qu'Axon a lui-même
#: créés. Avec `drive.metadata.readonly` par-dessus, `drive_find_file_id`
#: trouvait n'importe quel document et `drive_read_file` refusait de l'ouvrir —
#: l'agent voyait ton Drive sans pouvoir le lire.
#:
#: `drive.readonly` lève cette limite et couvre déjà les métadonnées, d'où le
#: retrait de la ligne devenue redondante. `drive.file` reste nécessaire : c'est
#: lui qui autorise l'ÉCRITURE dans les documents qu'Axon crée.
#:
#: Conséquence à connaître : tout fichier lu entre dans le contexte du modèle,
#: donc chez le fournisseur LLM. Élargir la lecture élargit ce qui peut sortir.
SCOPES_DRIVE = [
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/drive.readonly",
]
SCOPES_CALENDAR = [
    "https://www.googleapis.com/auth/calendar",
]
SCOPES_ALL: list[str] = list({
    *SCOPES_GMAIL, *SCOPES_DOCS, *SCOPES_SLIDES, *SCOPES_SHEETS, *SCOPES_DRIVE, *SCOPES_CALENDAR
})

def _load_credentials(scopes: Sequence[str]):
    creds = None
    if TOKEN_PATH.exists():
        _restreindre(TOKEN_PATH)
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
        _restreindre(CREDENTIALS_PATH)
        with open(CREDENTIALS_PATH, "r", encoding="utf-8") as f:
            client_config = json.load(f)

        flow = InstalledAppFlow.from_client_config(client_config, SCOPES_ALL)
        creds = flow.run_local_server(port=0, open_browser=False)
        with _ouvrir_prive(TOKEN_PATH) as f:
            pickle.dump(creds, f)

    elif not creds.valid and getattr(creds, "refresh_token", None):
        try:
            creds.refresh(Request())
        except RefreshError:
            # 🔥 refresh token mort → on repart de zéro
            if TOKEN_PATH.exists():
                TOKEN_PATH.unlink()
            return _load_credentials(scopes)
        else:
            with _ouvrir_prive(TOKEN_PATH) as f:
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
    """Le vrai constructeur, celui que `agents/google_sheet` n'appelait pas.

    Il en avait un local, resté à l'état de brouillon : il construisait un client
    Docs sans identifiants pour lui voler `._http.credentials`. Mesuré,
    `DefaultCredentialsError` avant tout appel réseau — les deux outils Sheets
    étaient morts depuis toujours, alors que `SCOPES_SHEETS` attendait ici.
    """
    return get_service("sheets", "v4", SCOPES_SHEETS)

def get_drive_service():
    return get_service("drive", "v3", SCOPES_DRIVE)

def get_calendar_service():
    return get_service("calendar", "v3", SCOPES_CALENDAR)
