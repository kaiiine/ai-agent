"""Un backend se déclare ICI, une fois. Pas dans six tables parallèles.

La correspondance « nom → fabrique » était recopiée dans six fichiers, et elles
avaient déjà divergé — mesuré avant d'écrire une ligne :

    orchestrator/graph.py       les 6
    ui/commands.py              sans nvidia
    memory/persistent.py        sans nvidia, sans ollama
    ui/spec.py                  sans nvidia, sans ollama
    cron_daemon.py              sans groq, sans ollama
    agents/deep/tools.py        sans groq, sans ollama

`nvidia` était donc invisible dans trois fichiers sur six, `ollama` dans quatre :
sélectionner ce backend n'avait aucun effet là où sa branche manquait, et rien ne
levait — chaque table retombait sur son défaut. `commands.py` porte déjà le récit
d'un bug identique, où `/model` écrivait le choix NVIDIA dans `settings.ollama_model`.

La fabrique est nommée par une CHAÎNE, résolue à l'appel : `models.py` importe
`settings`, et l'importer ici en retour fermerait la boucle. C'est aussi ce qui
rend un backend gratuit à déclarer — tant qu'on ne le choisit pas, son client
n'est jamais chargé.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class Backend:
    """Tout ce qu'AXON doit savoir d'un fournisseur de modèles."""

    nom: str
    fabrique: str                      # nom de la fonction dans `src.llm.models`
    champ_modele: str                  # champ de `settings` qui porte le choix
    cles: tuple[str, ...] = ()         # variables d'env qui le rendent utilisable
    modeles: tuple[str, ...] = ()      # proposés par `/model` ; vide = découverte
    gratuit: bool = False              # aucun euro engagé, quota ou machine locale
    #: Sait lire une image. Déclaré PRUDEMMENT : envoyer du base64 à un modèle qui
    #: l'ignore casse l'appel, alors que ne pas l'envoyer coûte au pire une
    #: question. Un `False` ici n'affirme donc pas l'incapacité — il dit qu'on ne
    #: l'a pas établie. Pour `ollama`, la vérité est par MODÈLE et se lit à
    #: l'exécution : l'API `/api/tags` annonce `capabilities: ["vision"]`.
    vision: bool = False


BACKENDS: dict[str, Backend] = {
    "ollama": Backend(
        nom="ollama", fabrique="make_llm", champ_modele="ollama_model",
        gratuit=True),                 # local : ses modèles se découvrent à l'exécution
    "ollama_cloud": Backend(
        nom="ollama_cloud", fabrique="make_llm_ollama_cloud",
        champ_modele="ollama_cloud_model",
        cles=("OLLAMA_CLOUD_API_KEYS", "OLLAMA_API_KEY"),
        modeles=("gpt-oss:120b-cloud", "deepseek-v4-flash:cloud", "qwen3.5:cloud",
                 "glm-5.3:cloud", "kimi-k2.6:cloud", "minimax-m3:cloud")),
    "groq": Backend(
        nom="groq", fabrique="make_llm_groq", champ_modele="groq_model",
        cles=("GROQ_API_KEY", "GROQ_API_KEYS"), gratuit=True,
        modeles=("openai/gpt-oss-20b", "openai/gpt-oss-120b",
                 "llama-3.3-70b-versatile", "qwen/qwen3-32b")),
    "gemini": Backend(
        nom="gemini", fabrique="make_llm_gemini", champ_modele="gemini_model",
        cles=("GEMINI_API_KEY", "GEMINI_API_KEYS", "GOOGLE_API_KEY"), gratuit=True,
        vision=True,
        modeles=("gemini-2.5-flash", "gemini-2.5-flash-lite")),
    "mistral": Backend(
        nom="mistral", fabrique="make_llm_mistral", champ_modele="mistral_model",
        cles=("MISTRAL_API_KEY", "MISTRAL_API_KEYS"),
        modeles=("mistral-small-2603", "codestral-2508", "mistral-large-latest")),
    "nvidia": Backend(
        nom="nvidia", fabrique="make_llm_nvidia", champ_modele="nvidia_model",
        cles=("NVIDIA_API_KEY", "NVIDIA_API_KEYS"), gratuit=True,
        modeles=("meta/muse-glimmer-30b", "meta/llama-3.3-70b-instruct")),
    # OpenRouter : compatible OpenAI, 21 modèles à 0 € au relevé du catalogue.
    #
    # La liste est celle qui a RÉPONDU, pas celle que le catalogue annonce. Six
    # candidats éprouvés sur un appel d'outil réel — la boucle d'AXON en dépend,
    # et `supported_parameters: tools` ne promet rien :
    #
    #     minimax/minimax-m3                    outils OK
    #     nvidia/nemotron-3-ultra-550b-a55b     outils OK
    #     nvidia/nemotron-3.5-lightning         outils OK
    #     inclusionai/ling-3.0-flash-fin        outils OK
    #     thinkingmachines/inkling              403 — accès refusé
    #     google/gemma-4-26b-a4b-it             429 — fournisseur saturé
    #
    # Un quota `:free` est partagé : ces mêmes appels peuvent renvoyer 429 plus
    # tard, d'où le pool de clés et l'ordre de repli.
    "openrouter": Backend(
        nom="openrouter", fabrique="make_llm_openrouter",
        champ_modele="openrouter_model",
        cles=("OPENROUTER_API_KEY", "OPENROUTER_API_KEYS"), gratuit=True,
        modeles=("minimax/minimax-m3:free",
                 "nvidia/nemotron-3-ultra-550b-a55b:free",
                 "nvidia/nemotron-3.5-lightning:free",
                 "inclusionai/ling-3.0-flash-fin:free")),
}


def noms() -> list[str]:
    """Les backends déclarés, dans l'ordre de déclaration."""
    return list(BACKENDS)


def utilisables() -> list[str]:
    """Ceux dont une clé est réellement posée — `ollama` en a toujours une : la machine."""
    return [n for n, b in BACKENDS.items()
            if not b.cles or any(os.environ.get(c, "").strip() for c in b.cles)]


#: L'ordre dans lequel on se rabat quand un backend manque ou tombe.
#:
#: `noms()` rendait l'ordre de DÉCLARATION, qui place `ollama` en tête parce
#: qu'il est le plus ancien. Tout ce qui choisissait « le premier disponible »
#: tombait donc sur le modèle local — et un chiffre produit par un 4B local ne
#: dit rien de ce que fera le modèle de production. Le local est un filet, pas
#: un défaut : il vient en dernier, et il vient toujours, puisqu'il ne demande
#: aucune clé.
ORDRE_DE_REPLI: tuple[str, ...] = ("ollama_cloud", "gemini", "mistral", "ollama")


def ordre_de_repli() -> list[str]:
    """Les backends utilisables, du plus souhaité au dernier recours.

    Ce qui est déclaré mais absent de la chaîne vient ensuite : un backend
    nouvellement ajouté reste joignable sans qu'on ait à penser à l'inscrire ici.
    """
    dispo = set(utilisables())
    chaine = [n for n in ORDRE_DE_REPLI if n in dispo]
    return chaine + [n for n in BACKENDS if n in dispo and n not in chaine]


def champ_modele(nom: str, defaut: str = "ollama_model") -> str:
    """Le champ de `settings` où vit le modèle choisi.

    Backend inconnu : on vise le local, seul à ne rien coûter.
    """
    backend = BACKENDS.get(nom)
    return backend.champ_modele if backend else defaut


def modeles(nom: str) -> tuple[str, ...]:
    backend = BACKENDS.get(nom)
    return backend.modeles if backend else ()


def sait_lire_une_image(nom: str) -> bool:
    """Ce backend peut-il recevoir une image ?

    Rien ne le disait, et rien dans un nom de modèle ne le laisse deviner :
    `gemini-2.5-flash` sait, `gpt-oss:120b-cloud` non. Faute de cette réponse,
    AXON essayait, échouait, puis reniflait le message d'erreur à la recherche de
    « not support » ou « vision » pour retirer les images des messages
    checkpointés — un rattrapage qui dépend du TEXTE d'une erreur, donc qu'un
    fournisseur casse en reformulant sa phrase.

    Pour `ollama`, la question se pose par modèle et la machine sait répondre :
    on la lui pose plutôt que de deviner.
    """
    backend = BACKENDS.get(nom)
    if backend is None:
        return False
    if backend.vision:
        return True
    if nom == "ollama":
        return _ollama_voit(_modele_actif(nom))
    return False


def _modele_actif(nom: str) -> str:
    try:
        from src.infra.settings import settings

        return getattr(settings, champ_modele(nom), "") or ""
    except Exception:                                        # noqa: BLE001
        return ""


def _ollama_voit(modele: str) -> bool:
    """La machine le dit : `/api/tags` annonce les capacités de chaque modèle."""
    if not modele:
        return False
    import json
    import urllib.request

    hote = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
    if not hote.startswith("http"):
        hote = f"http://{hote}"
    try:
        with urllib.request.urlopen(f"{hote}/api/tags", timeout=2) as reponse:
            for m in json.load(reponse).get("models", []):
                if m.get("name") == modele:
                    return "vision" in (m.get("capabilities") or [])
    except Exception:                                        # noqa: BLE001
        pass
    return False


def fabriques() -> dict[str, Callable]:
    """Nom → fabrique, résolues maintenant. Un backend absent de `models.py` est
    simplement omis : mieux vaut une liste courte qu'un import qui casse tout."""
    from src.llm import models

    trouvees = {}
    for nom, backend in BACKENDS.items():
        fabrique = getattr(models, backend.fabrique, None)
        if callable(fabrique):
            trouvees[nom] = fabrique
    return trouvees
