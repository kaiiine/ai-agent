from langchain_core.tools import tool
from src.infra.google_auth import get_docs_service
from googleapiclient.errors import HttpError

_CREATED_DOCS_CACHE: dict[str, str] = {}
_LAST_CREATED_DOC_ID: str | None = None


@tool("google_docs_create")
def google_docs_create(title: str) -> dict:
    """
    Crée un nouveau Google Doc vide. Utiliser SEULEMENT quand l'utilisateur demande explicitement de créer un document.
    """
    global _LAST_CREATED_DOC_ID

    if title in _CREATED_DOCS_CACHE:
        doc_id = _CREATED_DOCS_CACHE[title]
        _LAST_CREATED_DOC_ID = doc_id
        return {
            "doc_id": doc_id,
            "title": title,
            "url": f"https://docs.google.com/document/d/{doc_id}/edit",
        }

    svc = get_docs_service()
    doc = svc.documents().create(body={"title": title}).execute()
    doc_id = doc.get("documentId")

    _CREATED_DOCS_CACHE[title] = doc_id
    _LAST_CREATED_DOC_ID = doc_id

    return {
        "doc_id": doc_id,
        "title": title,
        "url": f"https://docs.google.com/document/d/{doc_id}/edit",
    }


@tool("google_docs_update")
def google_docs_update(doc_id: str, md: str) -> dict:
    """
    Ajoute du contenu à un Google Doc existant.
    """
    global _LAST_CREATED_DOC_ID

    if (not doc_id) or (len(doc_id) < 20) or (doc_id == "new_doc_id"):
        if _LAST_CREATED_DOC_ID:
            doc_id = _LAST_CREATED_DOC_ID
        else:
            return {
                "status": "error",
                "doc_id": doc_id,
                "error": "doc_id invalide et aucun document récemment créé pour le remplacer.",
            }

    svc = get_docs_service()
    requests = [{"insertText": {"endOfSegmentLocation": {}, "text": md + "\n"}}]

    try:
        svc.documents().batchUpdate(documentId=doc_id, body={"requests": requests}).execute()
        return {
            "status": "ok",
            "doc_id": doc_id,
            "message": f"Contenu ajouté au Doc `{doc_id}`",
        }
    except HttpError as e:
        if e.resp is not None and e.resp.status == 404:
            return {"status": "not_found", "doc_id": doc_id, "error": f"Document introuvable ou accès refusé: {e}"}
        return {"status": "error", "doc_id": doc_id, "error": str(e)}


@tool("google_docs_read")
def google_docs_read(doc_id: str) -> dict:
    """
    Lit le contenu texte complet d'un Google Doc existant.
    Utiliser après avoir obtenu un doc_id via drive_find_file_id.

    Args:
        doc_id: ID du document Google Docs (44 caractères)
    Returns:
        {"status": "ok", "title": "...", "content": "...", "word_count": N, "url": "..."}
    """
    svc = get_docs_service()
    try:
        doc = svc.documents().get(documentId=doc_id).execute()
        title = doc.get("title", "")

        parts = []
        for element in doc.get("body", {}).get("content", []):
            paragraph = element.get("paragraph")
            if not paragraph:
                continue
            for pe in paragraph.get("elements", []):
                text_run = pe.get("textRun")
                if text_run:
                    parts.append(text_run.get("content", ""))

        content = "".join(parts).strip()
        return {
            "status": "ok",
            "title": title,
            "doc_id": doc_id,
            "content": content[:50_000],
            "word_count": len(content.split()),
            "url": f"https://docs.google.com/document/d/{doc_id}/edit",
        }
    except HttpError as e:
        if e.resp is not None and e.resp.status == 404:
            return {"status": "not_found", "doc_id": doc_id, "error": "Document introuvable ou accès refusé"}
        return {"status": "error", "doc_id": doc_id, "error": str(e)}
