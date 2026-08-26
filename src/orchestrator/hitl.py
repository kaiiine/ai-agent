"""Protocole unique pour demander quelque chose à l'utilisateur.

Un nœud construit une `Demande` et appelle `demander()` : le graphe s'arrête, et
n'importe quel client — TUI, API — la sert de la même façon.

RÈGLE : à la reprise, LangGraph rejoue le nœud depuis son début. Tout ce qui
précède `demander()` s'exécute donc DEUX fois, tout ce qui suit une seule.
Les effets sur le monde extérieur — écrire un fichier, envoyer un mail, inscrire
une autorisation — se placent après l'appel.

COROLLAIRE : on interrompt depuis un nœud, jamais depuis un outil. Un outil est
atomique pour le moteur : son travail entier serait rejoué.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from langgraph.types import Command, interrupt

#: Genres de demande. Ne changent pas le protocole : servent au client à choisir
#: un rendu — un diff ne s'affiche pas comme un questionnaire.
CLARIFICATION = "clarification"
AUTORISATION = "autorisation"
DIFF = "diff"
PLAN = "plan"
ENVOI = "envoi"

#: Jetons normalisés d'un choix binaire, pour les clients qui ne renvoient pas
#: le libellé affiché.
ACCORD = "accord"
REFUS = "refus"


@dataclass(frozen=True)
class Question:
    """Une question, ses choix éventuels, et lequel vaut accord.

    `choix` vide = question ouverte. Ne pas y mettre « Autre » : les clients
    l'ajoutent eux-mêmes. `affirmatif` doit valoir l'un des `choix`.
    """
    texte: str
    choix: tuple[str, ...] = ()
    affirmatif: str = ""


@dataclass(frozen=True)
class Demande:
    """Ce que le graphe attend de l'utilisateur, sous forme transportable."""
    genre: str
    #: Ce sur quoi on demande — une commande, un champ, un chemin.
    cle: str
    questions: tuple[Question, ...]
    #: Ce qu'il faut montrer avant de répondre : diff, aperçu d'écriture, corps
    #: d'un mail.
    apercu: str = ""
    #: Ce dont le client a besoin sans que le protocole le sache (chemin, hôte).
    #: Jamais lu par ce module.
    extra: dict[str, Any] = field(default_factory=dict)

    def en_clair(self) -> dict[str, Any]:
        """La demande en JSON — seule forme qui survit à un checkpoint."""
        return {
            "genre": self.genre,
            "cle": self.cle,
            "apercu": self.apercu,
            "extra": dict(self.extra),
            "questions": [{"texte": q.texte, "choix": list(q.choix),
                           "affirmatif": q.affirmatif}
                          for q in self.questions],
        }

    @classmethod
    def depuis(cls, brut: dict[str, Any]) -> "Demande":
        return cls(
            genre=brut.get("genre", ""),
            cle=brut.get("cle", ""),
            apercu=brut.get("apercu", ""),
            extra=dict(brut.get("extra") or {}),
            questions=tuple(
                Question(texte=q.get("texte", ""), choix=tuple(q.get("choix") or ()),
                         affirmatif=q.get("affirmatif", ""))
                for q in (brut.get("questions") or [])),
        )


def demander(demande: Demande) -> list[str]:
    """Arrête le graphe et rend une réponse par question, à la reprise.

    Ce qui précède cet appel dans le même nœud s'exécute deux fois : placer les
    effets après.
    """
    brut = interrupt(demande.en_clair())
    return normaliser(brut, attendues=len(demande.questions))


def normaliser(brut: Any, *, attendues: int = 1) -> list[str]:
    """Ce qu'un client a renvoyé, ramené à `attendues` chaînes.

    Accepte une chaîne, une liste ou un dict. Complète avec du vide si le client
    a répondu à moins de questions qu'il n'y en avait.
    """
    if brut is None:
        reponses: list[str] = []
    elif isinstance(brut, str):
        reponses = [brut]
    elif isinstance(brut, dict):
        reponses = [str(v) for _, v in sorted(brut.items(), key=lambda kv: str(kv[0]))]
    elif isinstance(brut, (list, tuple)):
        reponses = [str(x) for x in brut]
    else:
        reponses = [str(brut)]
    return reponses + [""] * max(0, attendues - len(reponses))


def accorde(reponse: str, question: Question | None = None) -> bool:
    """Cette réponse vaut-elle un accord ?

    Accepte le libellé affiché (via `question.affirmatif`) ou le jeton `ACCORD`.
    Tout le reste — vide, annulation, valeur inattendue — vaut refus.
    """
    propre = (reponse or "").strip()
    if question is not None and question.affirmatif:
        return propre == question.affirmatif
    return propre.lower() == ACCORD


# ── Côté client ──────────────────────────────────────────────────────────────
def demande_en_attente(sortie: Any) -> Demande | None:
    """La demande portée par une sortie de graphe (`__interrupt__`), ou None."""
    if not isinstance(sortie, dict):
        return None
    interruptions = sortie.get("__interrupt__") or []
    for interruption in interruptions:
        valeur = getattr(interruption, "value", None)
        if isinstance(valeur, dict) and valeur.get("questions") is not None:
            return Demande.depuis(valeur)
    return None


def reponse(reponses: list[str]) -> Command:
    """La commande de reprise à passer au graphe."""
    return Command(resume=list(reponses))
