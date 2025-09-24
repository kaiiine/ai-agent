from langchain_core.tools import tool
from src.infra.google_auth import get_docs_service

_CREATED_DOCS_CACHE: dict[str, str] = {}

@tool("google_docs_create")
def google_docs_create(title: str) -> dict:
    """
    Crée un nouveau Google Doc vide. Utiliser SEULEMENT quand l'utilisateur demande explicitement de créer un document.
    
    Args:
        title: Nom du document à créer
    Returns:
        {"doc_id": "...", "title": "...", "url": "..."}
    """
    # idempotence légère: si on vient de créer ce titre, renvoyer le même ID
    if title in _CREATED_DOCS_CACHE:
        doc_id = _CREATED_DOCS_CACHE[title]
        return {"doc_id": doc_id, "title": title, "url": f"https://docs.google.com/document/d/{doc_id}/edit"}

    svc = get_docs_service()
    doc = svc.documents().create(body={"title": title}).execute()
    doc_id = doc.get("documentId")
    _CREATED_DOCS_CACHE[title] = doc_id
    return {"doc_id": doc_id, "title": title, "url": f"https://docs.google.com/document/d/{doc_id}/edit"}


@tool("google_docs_update")
def google_docs_update(doc_id: str, md: str) -> str:
    """
    Ajoute du contenu à un Google Doc existant. Nécessite l'ID obtenu avec google_docs_create.
    
    Args:
        doc_id: ID du document (depuis google_docs_create)
        md: Contenu à ajouter (texte ou markdown)
    Returns:
        Message de confirmation
    """
    svc = get_docs_service()
    requests = [{"insertText": {"endOfSegmentLocation": {}, "text": md + "\n"}}]
    svc.documents().batchUpdate(documentId=doc_id, body={"requests": requests}).execute()
    return f"✅ Contenu ajouté au Doc `{doc_id}`"
