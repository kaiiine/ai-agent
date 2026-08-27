"""Un appel d'outil rendu comme texte n'exécute rien — et l'utilisateur reçoit
les arguments à la place du résultat.

Vécu sur gpt-oss:120b : « schématise un RAG en prod » avec `mermaid_diagram` lié
a rendu `{"definition": "...", "title": "...", "export_to": ""}` comme réponse
finale. Aucun diagramme. Le garde-fou existant ne voyait que les balises
`xxx:tool_call` ; celui-ci voit la forme sans balise.
"""
from __future__ import annotations

import json

from src.orchestrator.provider_quirks import outil_ecrit_en_json
from src.orchestrator.registry import build_all_tools

OUTILS = build_all_tools()


def test_reconnait_les_arguments_dun_outil_lie():
    texte = json.dumps({"definition": "graph LR\n A --> B",
                        "title": "Architecture RAG", "export_to": ""})
    assert outil_ecrit_en_json(texte, OUTILS) == "mermaid_diagram"


def test_ignore_un_json_cite_dans_une_explication():
    texte = ("Voici comment on configure ça. Le fichier ressemble à "
             + json.dumps({"definition": "x", "title": "y"})
             + " et tu peux le placer où tu veux, par exemple à la racine du "
               "projet, puis relancer le service pour qu'il soit relu.")
    assert outil_ecrit_en_json(texte, OUTILS) is None


def test_ignore_une_reponse_sans_json():
    assert outil_ecrit_en_json("Le RAG en production ajoute un cache.", OUTILS) is None


def test_ignore_un_json_qui_ne_correspond_a_aucun_outil():
    texte = json.dumps({"couleur": "rouge", "taille": 42})
    assert outil_ecrit_en_json(texte, OUTILS) is None


def test_exige_les_parametres_requis():
    """Un objet qui n'a qu'un champ optionnel n'est pas un appel."""
    assert outil_ecrit_en_json(json.dumps({"export_to": "pptx"}), OUTILS) is None
