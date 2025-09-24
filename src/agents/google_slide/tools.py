from langchain_core.tools import tool
from ...infra.google_auth import get_slides_service 

@tool
def create_presentation(title: str) -> str:
    """
    Crée une nouvelle présentation Google Slides vide. Utiliser SEULEMENT quand l'utilisateur demande explicitement de créer une présentation.
    
    Args:
        title: Nom de la présentation à créer
    Returns:
        ID de la présentation créée (à conserver pour ajouter des slides)
    """
    svc = get_slides_service()
    pres = svc.presentations().create(body={"title": title}).execute()
    return pres.get("presentationId")

@tool
def add_slide(presentation_id: str, title: str, bullets: list[str] | None = None) -> str:
    """
    Ajoute une slide à une présentation existante. Nécessite l'ID obtenu avec create_presentation.
    
    Args:
        presentation_id: ID de la présentation (depuis create_presentation)
        title: Titre de la slide
        bullets: Points à ajouter (optionnel)
    Returns:
        Message de confirmation
    """
    svc = get_slides_service()
    requests = [
        {"createSlide": {"objectId": None, "insertionIndex": 1, "slideLayoutReference": {"predefinedLayout": "TITLE_AND_BODY"}}},
    ]
    svc.presentations().batchUpdate(presentationId=presentation_id, body={"requests": requests}).execute()
    # Pour la démo : on ne positionne pas encore les shapes; à compléter si besoin
    return f"✅ Slide ajoutée à `{presentation_id}` (à enrichir: insertion de texte)"
