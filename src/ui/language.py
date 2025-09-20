import re

def detect_lang(text: str) -> str:
    return "fr" if re.search(r"[éèàùâêîôûç]", text, re.I) else "en"

def contains_cjk(text: str) -> bool:
    return any('\u4e00' <= c <= '\u9fff' for c in text)

def enforce_lang_ephemeral_system(state: dict, lang: str) -> None:
    if lang not in {"fr", "en"}:
        lang = "en"
    sys = ("Réponds STRICTEMENT en français. Ne réponds jamais dans une autre langue. "
           "Formate toujours en Markdown."
           if lang == "fr" else
           "Answer STRICTLY in English. Never use any other language. Always format in Markdown.")
    state["messages"].append({"role": "system", "content": sys})

def enforce_lang_output(text: str, lang: str) -> str:
    if contains_cjk(text):
        tag = "FR" if lang == "fr" else "EN"
        return f"> ⚠️ Réponse réécrite ({tag}) :\n\n{text}"
    return text
