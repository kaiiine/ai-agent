from langchain_core.tools import tool
from src.infra.translator import get_translator

@tool("translator")
def translator(
    sentence: str,
    original_language: str = "fr",
    target_language: str = "en",
    instruction: str = "Use informal",
) -> dict:
    """
    Traduit un mot, une phrase ou un texte d'une langue vers une autre.

    Utilise ce tool pour toute demande de traduction : "traduis", "translate",
    "comment dit-on X en Y", "dis-moi X en anglais/espagnol/allemand/italien".

    Args:
        sentence: texte à traduire
        original_language: code ISO langue source ("fr", "en", "es", "it", "de"). Défaut : "fr"
        target_language: code ISO langue cible. Défaut : "en"
        instruction: consigne de style. Ex : "Use informal", "Do not translate brand names"
    """
    try:
        result = get_translator().translate(
            text=sentence,
            source=original_language,
            target=target_language,
            format="text",
            instructions=instruction,
        )
        return {"status": "ok", "translation": result}
    except Exception as e:
        return {"status": "error", "error": str(e)}
