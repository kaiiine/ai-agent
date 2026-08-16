"""Ce que le prompt initial dit déjà, et ce qu'il laisse ouvert.

Le générateur posait ses questions dans un ordre fixe et ne les sautait que si
le modèle décidait, question par question, qu'elle était « déjà couverte ». Deux
défauts : la décision était prise sans vue d'ensemble, et l'ordre ne dépendait
jamais de ce qui manquait vraiment.

Ici l'ordre est CALCULÉ. Une passe unique classe chaque catégorie en
CLAIR / PARTIEL / ABSENT, puis la priorité vaut `impact × incertitude` :

    incertitude : CLAIR 0 · PARTIEL 1 · ABSENT 2

Une catégorie à fort impact laissée absente passe donc devant deux catégories
mineures partiellement couvertes. Une catégorie CLAIRE ne produit aucune
question — c'est la seule façon de ne pas redemander ce que l'utilisateur vient
d'écrire.

Le budget de questions est VOLONTAIREMENT petit. Au-delà de six ou sept, on
n'obtient plus des décisions mais de la lassitude, et les dernières réponses
sont moins bonnes que les premières.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from .taxonomy import Categorie, categories_du_profil

#: CLAIR ne vaut pas zéro question par gentillesse : c'est ce qui distingue
#: « l'utilisateur l'a déjà dit » de « on n'a pas encore demandé ».
INCERTITUDE = {"CLAIR": 0, "PARTIEL": 1, "ABSENT": 2}

#: Au-delà, on ne collecte plus des décisions mais de la fatigue.
BUDGET_QUESTIONS = 6


@dataclass(frozen=True)
class Lecture:
    """Le statut d'une catégorie, et de quoi le contredire."""

    categorie: Categorie
    statut: str                  # CLAIR | PARTIEL | ABSENT
    note: str = ""

    @property
    def priorite(self) -> int:
        return self.categorie.impact * INCERTITUDE.get(self.statut, 2)

    @property
    def a_demander(self) -> bool:
        return self.priorite > 0


_SYSTEME = """\
Tu analyses un descriptif de projet pour repérer ce qu'il NE DIT PAS.

Pour chaque catégorie fournie, réponds :
- "CLAIR"   : le descriptif tranche déjà la question, un développeur saurait quoi faire
- "PARTIEL" : le sujet est effleuré mais une décision manque
- "ABSENT"  : rien dans le descriptif ne permet de trancher

Réponds UNIQUEMENT avec un objet JSON, sans markdown :
{"categories": {"<id>": {"statut": "CLAIR|PARTIEL|ABSENT", "note": "<8 mots max>"}}}

Règles :
- Sois STRICT sur CLAIR. Un mot-clé cité ne suffit pas : il faut une décision.
  « une base de données » est PARTIEL ; « PostgreSQL » est CLAIR.
- Un adjectif non chiffré ne rend rien CLAIR : « rapide », « robuste »,
  « intuitif » laissent la catégorie PARTIEL au mieux.
- N'invente aucune catégorie : réponds pour celles fournies, et elles seules.\
"""


def _parse(texte: str) -> dict:
    nettoye = re.sub(r"```(?:json)?\s*", "", texte).replace("```", "").strip()
    for tentative in (nettoye, (re.search(r"\{.*\}", nettoye, re.DOTALL) or [""])[0]):
        try:
            charge = json.loads(tentative)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(charge, dict):
            return charge.get("categories", charge)
    return {}


def scanner(descriptif: str, profil: str, llm) -> tuple[Lecture, ...]:
    """Classe chaque catégorie du profil face au descriptif.

    Une panne de modèle ou une réponse illisible ne fait pas échouer le wizard :
    tout devient ABSENT, c'est-à-dire l'hypothèse prudente — on demandera des
    choses déjà dites plutôt que d'en oublier de décisives.
    """
    from langchain_core.messages import HumanMessage, SystemMessage

    categories = categories_du_profil(profil)
    inventaire = "\n".join(
        f"- {c.id} — {c.libelle} : {', '.join(c.couvre)}" for c in categories)
    contenu = f"Descriptif du projet :\n{descriptif}\n\nCatégories :\n{inventaire}"

    try:
        reponse = llm.invoke([SystemMessage(content=_SYSTEME),
                              HumanMessage(content=contenu)])
        brut = _parse(getattr(reponse, "content", str(reponse)))
    except Exception:                                            # noqa: BLE001
        brut = {}

    lectures = []
    for c in categories:
        entree = brut.get(c.id) or {}
        statut = str(entree.get("statut", "ABSENT")).upper()
        if statut not in INCERTITUDE:
            statut = "ABSENT"
        lectures.append(Lecture(c, statut, str(entree.get("note", ""))[:60]))
    return tuple(lectures)


def a_demander(lectures: tuple[Lecture, ...],
               budget: int = BUDGET_QUESTIONS) -> tuple[Lecture, ...]:
    """Les catégories à interroger, les plus décisives d'abord.

    LE DÉPARTAGE À PRIORITÉ ÉGALE ALTERNE ENTRE SOCLE ET PROFIL, et ce n'est pas
    un détail. Trier sur le seul rang de la taxonomie mettait tout le socle
    devant : sur un pipeline de données, quatre catégories de socle à priorité 6
    remplissaient le budget et « Idempotence & reprise » — impact 3, la question
    qui décide de ce qui se passe au redémarrage — n'était jamais posée.

    C'est le travers que ce module existe pour corriger, reproduit un cran plus
    bas : des questions choisies par le template plutôt que par le projet.
    L'alternance garantit qu'une nature de projet ne peut pas être noyée par le
    tronc commun.

    L'ordre reste TOTAL et reproductible : deux exécutions sur le même descriptif
    posent les mêmes questions dans le même ordre.
    """
    from .taxonomy import SOCLE

    ids_socle = {c.id for c in SOCLE}
    rang = {l.categorie.id: i for i, l in enumerate(lectures)}

    def file(du_socle: bool) -> list[Lecture]:
        retenues = [l for l in lectures
                    if l.a_demander and (l.categorie.id in ids_socle) is du_socle]
        return sorted(retenues, key=lambda l: (-l.priorite, rang[l.categorie.id]))

    socle, profil = file(True), file(False)
    choisies: list[Lecture] = []
    tour_du_socle = True
    while len(choisies) < budget and (socle or profil):
        # À priorité égale on alterne ; dès qu'une file propose STRICTEMENT
        # mieux, la priorité l'emporte sur l'alternance — une question décisive
        # ne cède pas sa place à une question mineure au nom de l'équilibre.
        tete_socle = socle[0].priorite if socle else -1
        tete_profil = profil[0].priorite if profil else -1
        if tete_socle > tete_profil:
            prendre_socle = True
        elif tete_profil > tete_socle:
            prendre_socle = False
        else:
            prendre_socle = tour_du_socle if socle and profil else bool(socle)
        source = socle if prendre_socle else profil
        choisies.append(source.pop(0))
        tour_du_socle = not prendre_socle
    return tuple(choisies)


def resume(lectures: tuple[Lecture, ...]) -> str:
    """Une ligne par statut — ce que le wizard affiche avant de commencer.

    Montrer la carte AVANT les questions change la nature de l'échange :
    l'utilisateur voit ce qui est déjà acquis, et comprend pourquoi on lui
    demande précisément ces choses-là.
    """
    par_statut: dict[str, list[str]] = {"CLAIR": [], "PARTIEL": [], "ABSENT": []}
    for l in lectures:
        par_statut.setdefault(l.statut, []).append(l.categorie.libelle)
    lignes = []
    for statut, marque in (("CLAIR", "✓"), ("PARTIEL", "~"), ("ABSENT", "·")):
        noms = par_statut.get(statut) or []
        if noms:
            lignes.append(f"  {marque} {statut.lower()} : {', '.join(noms)}")
    return "\n".join(lignes)
