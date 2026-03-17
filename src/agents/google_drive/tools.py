from typing import Optional, Dict, Any
from langchain_core.tools import tool
from src.infra.google_auth import get_drive_service
from googleapiclient.errors import HttpError


def _file_url(file_id: str) -> str:
    return f"https://drive.google.com/file/d/{file_id}/view"


@tool("drive_find_file_id")
def drive_find_file_id(name: str, exact: bool = False) -> Dict[str, Any]:
    """
    Recherche des fichiers Drive par nom (exact ou approximatif).
    À utiliser en premier quand l'utilisateur mentionne un nom de fichier ou document.
    Si plusieurs résultats, les lister et demander à l'utilisateur lequel il veut.

    Args:
        name: nom exact ou fragment à chercher
        exact: True = nom exactement identique, False = contient le fragment
    Returns:
        {"status": "ok", "matches": [{"id", "name", "mimeType", "modifiedTime", "url"}, ...]}
        {"status": "empty"} si aucun résultat
    """
    svc = get_drive_service()
    try:
        escaped = name.replace('"', '\\"')
        q = f'name = "{escaped}" and trashed = false' if exact else f"name contains '{escaped}' and trashed = false"
        resp = svc.files().list(
            q=q, spaces="drive",
            fields="files(id,name,mimeType,modifiedTime)",
            pageSize=50,
        ).execute()
        files = resp.get("files", [])
        if not files:
            return {"status": "empty", "matches": []}
        matches = [
            {
                "id": f["id"],
                "name": f["name"],
                "mimeType": f.get("mimeType"),
                "modifiedTime": f.get("modifiedTime"),
                "url": _file_url(f["id"]),
            }
            for f in files
        ]
        return {"status": "ok", "count": len(matches), "matches": matches}
    except HttpError as e:
        return {"status": "error", "error": str(e)}


@tool("drive_read_file")
def drive_read_file(file_id: str) -> Dict[str, Any]:
    """
    Lit le contenu d'un fichier Drive.
    Supporte: Google Docs (texte), Google Sheets (CSV), fichiers texte brut.
    Utiliser après avoir obtenu un file_id via drive_find_file_id.

    Args:
        file_id: ID du fichier Drive
    Returns:
        {"status": "ok", "name": "...", "content": "...", "mime_type": "..."}
    """
    import io
    from googleapiclient.http import MediaIoBaseDownload

    svc = get_drive_service()
    try:
        meta = svc.files().get(fileId=file_id, fields="id,name,mimeType").execute()
        mime = meta.get("mimeType", "")
        name = meta.get("name", "")

        # Google Docs → texte brut
        if mime == "application/vnd.google-apps.document":
            raw = svc.files().export(fileId=file_id, mimeType="text/plain").execute()
            text = raw.decode("utf-8") if isinstance(raw, bytes) else raw
            return {"status": "ok", "name": name, "mime_type": mime, "content": text[:50_000]}

        # Google Sheets → CSV
        if mime == "application/vnd.google-apps.spreadsheet":
            raw = svc.files().export(fileId=file_id, mimeType="text/csv").execute()
            text = raw.decode("utf-8") if isinstance(raw, bytes) else raw
            return {"status": "ok", "name": name, "mime_type": mime, "content": text[:20_000]}

        # Fichiers texte brut
        if mime.startswith("text/"):
            fh = io.BytesIO()
            downloader = MediaIoBaseDownload(fh, svc.files().get_media(fileId=file_id))
            done = False
            while not done:
                _, done = downloader.next_chunk()
            text = fh.getvalue().decode("utf-8", errors="replace")
            return {"status": "ok", "name": name, "mime_type": mime, "content": text[:50_000]}

        return {
            "status": "unsupported",
            "name": name,
            "mime_type": mime,
            "error": f"Type non supporté pour la lecture : {mime}. Utilisez Google Docs ou un fichier texte.",
        }
    except HttpError as e:
        if e.resp is not None and e.resp.status == 404:
            return {"status": "not_found", "file_id": file_id, "error": "Fichier introuvable ou accès refusé"}
        return {"status": "error", "error": str(e)}


@tool("drive_list_files")
def drive_list_files(q: Optional[str] = None, page_size: int = 50, page_token: Optional[str] = None) -> Dict[str, Any]:
    """
    Liste des fichiers Drive avec filtre optionnel.

    Args:
        q: requête Drive optionnelle (ex: "mimeType='application/pdf'")
        page_size: nombre max de résultats (max 200)
        page_token: pour pagination
    """
    svc = get_drive_service()
    try:
        if q is None:
            q = "trashed = false"
        resp = svc.files().list(
            q=q, spaces="drive",
            fields="nextPageToken,files(id,name,mimeType,modifiedTime)",
            pageSize=page_size,
            pageToken=page_token,
        ).execute()
        files = [
            {
                "id": f["id"],
                "name": f["name"],
                "mimeType": f.get("mimeType"),
                "modifiedTime": f.get("modifiedTime"),
                "url": _file_url(f["id"]),
            }
            for f in resp.get("files", [])
        ]
        return {"status": "ok", "files": files, "next_page_token": resp.get("nextPageToken")}
    except HttpError as e:
        return {"status": "error", "error": str(e)}


@tool("drive_delete_file")
def drive_delete_file(file_id: str, permanently: bool = False) -> Dict[str, Any]:
    """
    Supprime un fichier Drive (APRÈS confirmation explicite de l'utilisateur).

    Args:
        file_id: ID du fichier
        permanently: True = suppression définitive (IRRÉVERSIBLE), False = corbeille
    """
    svc = get_drive_service()
    try:
        if permanently:
            svc.files().delete(fileId=file_id).execute()
            return {"status": "ok", "message": f"Fichier {file_id} supprimé définitivement."}
        svc.files().update(fileId=file_id, body={"trashed": True}).execute()
        return {"status": "ok", "message": f"Fichier {file_id} mis à la corbeille."}
    except HttpError as e:
        return {"status": "error", "error": str(e)}


@tool("drive_get_file_metadata")
def drive_get_file_metadata(file_id: str) -> Dict[str, Any]:
    """
    Métadonnées d'un fichier Drive (nom, type, taille, propriétaire, URL).
    """
    svc = get_drive_service()
    try:
        resp = svc.files().get(fileId=file_id, fields="id,name,mimeType,modifiedTime,size,owners").execute()
        return {
            "status": "ok",
            "file": {
                "id": resp["id"],
                "name": resp["name"],
                "mimeType": resp.get("mimeType"),
                "size": resp.get("size"),
                "modifiedTime": resp.get("modifiedTime"),
                "owners": [{"email": o.get("emailAddress", "?")} for o in resp.get("owners", [])],
                "url": _file_url(resp["id"]),
            },
        }
    except HttpError as e:
        return {"status": "error", "error": str(e)}
