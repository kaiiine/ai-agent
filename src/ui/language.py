import re

def detect_lang(text: str) -> str:
    return "fr" if re.search(r"[éèàùâêîôûç]", text, re.I) else "en"

def contains_cjk(text: str) -> bool:
    return any('\u4e00' <= c <= '\u9fff' for c in text)

def enforce_lang_output(text: str, lang: str) -> str:
    if contains_cjk(text):
        tag = "FR" if lang == "fr" else "EN"
        return f"> ⚠️ Réponse réécrite ({tag}) :\n\n{text}"
    return text
