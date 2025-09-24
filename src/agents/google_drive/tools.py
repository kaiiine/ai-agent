# src/agents/drive/tools.py
from typing import Optional, List, Dict, Any
from langchain_core.tools import tool
from src.infra.google_auth import get_drive_service
from googleapiclient.errors import HttpError

def _file_url(file_id: str) -> str:
    return f"https://drive.google.com/file/d/{file_id}/view"

@tool("drive_find_file_id")
def drive_find_file_id(name: str, exact: bool = True) -> Dict[str, Any]:
    """
    Recherche de fichiers Drive par nom. Utiliser SEULEMENT pour retrouver des fichiers existants.
    
    Args:
        name: nom exact ou fragment à chercher
        exact: True = nom exactement identique, False = "contains"
    Returns:
        {"status": "ok", "matches": [...]} ou {"status": "empty"} si rien trouvé
    """
    svc = get_drive_service()
    try:
        if exact:
            q = f"name = \"{name.replace('\"', '\\\"')}\" and trashed = false"
        else:
            q = f"name contains '{name.replace('\"', '\\\"')}' and trashed = false"
        resp = svc.files().list(
            q=q, spaces="drive",
            fields="files(id,name,mimeType,modifiedTime)",
            pageSize=50
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
            } for f in files
        ]
        return {"status": "ok", "matches": matches}
    except HttpError as e:
        return {"status": "error", "error": str(e)}

@tool("drive_list_files")
def drive_list_files(q: Optional[str] = None, page_size: int = 50, page_token: Optional[str] = None) -> Dict[str, Any]:
    """
    Liste des fichiers Drive. Utiliser pour navigation Drive, pas pour contenu.
    
    Args:
        q: requête Drive optionnelle (ex: "mimeType='application/pdf'")
        page_size: nombre max de résultats (max 200)
        page_token: pour pagination
    Returns:
        {"status": "ok", "files": [...], "next_page_token": "..."}
    """
    svc = get_drive_service()
    try:
        if q is None:
            q = "trashed = false"
        resp = svc.files().list(
            q=q, spaces="drive",
            fields="nextPageToken,files(id,name,mimeType,modifiedTime)",
            pageSize=page_size,
            pageToken=page_token
        ).execute()
        files = resp.get("files", [])
        out = [
            {
                "id": f["id"],
                "name": f["name"],
                "mimeType": f.get("mimeType"),
                "modifiedTime": f.get("modifiedTime"),
                "url": _file_url(f["id"]),
            } for f in files
        ]
        return {"status": "ok", "files": out, "next_page_token": resp.get("nextPageToken")}
    except HttpError as e:
        return {"status": "error", "error": str(e)}

@tool("drive_delete_file")
def drive_delete_file(file_id: str, permanently: bool = False) -> Dict[str, Any]:
    """
    Supprime un fichier Drive (APRES confirmation explicite).
    Args:
      file_id: ID du fichier.
      permanently: True = suppression définitive (IRRÉVERSIBLE), False = envoie à la corbeille.
    Returns: {"status":"ok","message":"..."} ou {"status":"error","error":"..."}.
    """
    svc = get_drive_service()
    try:
        if permanently:
            svc.files().delete(fileId=file_id).execute()
            return {"status": "ok", "message": f"Fichier {file_id} supprimé définitivement."}
        else:
            svc.files().update(fileId=file_id, body={"trashed": True}).execute()
            return {"status": "ok", "message": f"Fichier {file_id} mis à la corbeille."}
    except HttpError as e:
        return {"status": "error", "error": str(e)}

@tool("drive_get_file_metadata")
def drive_get_file_metadata(file_id: str) -> Dict[str, Any]:
    """
    Métadonnées Drive (JSON). Utile pour récupérer l'URL et le propriétaire.
    Returns:
      {"status":"ok","file":{"id","name","mimeType","size","modifiedTime","owners":[...],"url"}}
    """
    svc = get_drive_service()
    try:
        resp = svc.files().get(
            fileId=file_id,
            fields="id,name,mimeType,modifiedTime,size,owners"
        ).execute()
        owners = [{"email": o.get("emailAddress","?")} for o in resp.get("owners", [])]
        file = {
            "id": resp["id"],
            "name": resp["name"],
            "mimeType": resp.get("mimeType"),
            "size": resp.get("size"),
            "modifiedTime": resp.get("modifiedTime"),
            "owners": owners,
            "url": _file_url(resp["id"]),
        }
        return {"status": "ok", "file": file}
    except HttpError as e:
        return {"status": "error", "error": str(e)}
