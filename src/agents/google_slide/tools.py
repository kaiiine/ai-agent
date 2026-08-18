"""Google Slides — la diapositive reçoit enfin son titre et ses puces.

`add_slide` acceptait `title` et `bullets`, et les JETAIT : après la création de
la diapositive, ni l'un ni l'autre n'était mentionné. La fonction retournait
pourtant « ✅ Slide ajoutée », avec l'aveu en commentaire (« pour la démo : on ne
positionne pas encore les shapes »). Un deck de dix diapositives donnait dix
pages blanches et un message de succès.

Deux défauts secondaires l'accompagnaient : `insertionIndex: 1` était codé en
dur, donc toutes les diapositives s'empilaient au même endroit et sortaient dans
l'ordre inverse ; et `"objectId": None` envoyait un null à l'API.

Le remplissage se fait en DEUX temps, comme pour les tableaux d'un Doc : les
zones de texte d'une mise en page n'existent qu'une fois la diapositive créée, et
leurs identifiants ne sont connus qu'en relisant la présentation.
"""
from __future__ import annotations

import uuid

from googleapiclient.errors import HttpError
from langchain_core.tools import tool

from src.infra.google_auth import get_slides_service
from src.infra.markdown_rendu import analyser, fragments


def _plat(texte: str) -> str:
    """Le texte sans ses marques : Slides n'a pas de markdown."""
    return "".join(f.texte for f in fragments(texte))


def _url(pid: str, slide_id: str = "") -> str:
    base = f"https://docs.google.com/presentation/d/{pid}/edit"
    return f"{base}#slide=id.{slide_id}" if slide_id else base


@tool("slides_create")
def slides_create(title: str) -> dict:
    """
    Crée une nouvelle présentation Google Slides.

    Utilise ce tool quand l'utilisateur veut :
    - créer une présentation, un diaporama, un deck
    - préparer des slides pour une réunion ou un exposé

    Mots-clés : présentation, slides, diaporama, deck, Google Slides, créer

    Args:
        title: Nom de la présentation
    Returns:
        {"status": "ok", "presentation_id": "...", "url": "..."}
    """
    try:
        svc = get_slides_service()
        pres = svc.presentations().create(body={"title": title}).execute()
        pid = pres.get("presentationId")
        return {"status": "ok", "presentation_id": pid, "url": _url(pid), "title": title}
    except HttpError as e:
        return {"status": "error", "error": f"Création impossible : {e}"}


@tool("slides_add_slide")
def slides_add_slide(presentation_id: str, titre: str,
                     puces: list[str] | None = None) -> dict:
    """
    Ajoute une diapositive AVEC son titre et ses puces à une présentation.

    Utilise ce tool quand l'utilisateur veut :
    - ajouter une diapositive à une présentation existante
    - construire un deck slide par slide

    Mots-clés : ajouter slide, diapositive, présentation, Google Slides, insérer

    La diapositive est ajoutée à la FIN de la présentation. Le texte est inséré
    réellement : si l'insertion échoue, le tool le dit au lieu d'annoncer un succès.

    Args:
        presentation_id: identifiant de la présentation (via slides_create)
        titre: titre de la diapositive
        puces: points à afficher dans le corps (optionnel)
    Returns:
        {"status": "ok", "slide_id": "...", "puces": N, "url": "..."}
    """
    try:
        svc = get_slides_service()
        pres = svc.presentations().get(presentationId=presentation_id).execute()
        rang = len(pres.get("slides", []))

        slide_id = f"axon_{uuid.uuid4().hex[:10]}"
        svc.presentations().batchUpdate(
            presentationId=presentation_id,
            body={"requests": [{"createSlide": {
                "objectId": slide_id,
                "insertionIndex": rang,          # à la FIN, pas toujours en 1
                "slideLayoutReference": {
                    "predefinedLayout": "TITLE_AND_BODY" if puces else "TITLE_ONLY"},
            }}]},
        ).execute()

        # Les zones de texte de la mise en page n'existent qu'ici : on relit la
        # présentation pour apprendre leurs identifiants.
        pres = svc.presentations().get(presentationId=presentation_id).execute()
        creee = next((s for s in pres.get("slides", [])
                      if s.get("objectId") == slide_id), None)
        if creee is None:
            return {"status": "error",
                    "error": "Diapositive créée mais introuvable à la relecture."}

        zones = _zones(creee)
        if "TITLE" not in zones:
            return {"status": "error", "slide_id": slide_id,
                    "error": "Aucune zone de titre dans la mise en page — texte non inséré."}

        requetes = [{"insertText": {"objectId": zones["TITLE"], "text": _plat(titre)}}]
        lignes = [_plat(p) for p in (puces or []) if _plat(p).strip()]
        if lignes and "BODY" in zones:
            requetes.append({"insertText": {"objectId": zones["BODY"],
                                            "text": "\n".join(lignes)}})
            requetes.append({"createParagraphBullets": {
                "objectId": zones["BODY"],
                "textRange": {"type": "ALL"},
                "bulletPreset": "BULLET_DISC_CIRCLE_SQUARE",
            }})
        elif lignes:
            return {"status": "error", "slide_id": slide_id,
                    "error": "Aucune zone de corps : les puces n'ont pas pu être insérées."}

        svc.presentations().batchUpdate(
            presentationId=presentation_id, body={"requests": requetes}).execute()

        return {"status": "ok", "slide_id": slide_id, "rang": rang + 1,
                "puces": len(lignes), "url": _url(presentation_id, slide_id)}
    except HttpError as e:
        return {"status": "error", "error": str(e)}


@tool("slides_from_markdown")
def slides_from_markdown(presentation_id: str, md: str) -> dict:
    """
    Construit une présentation entière depuis du markdown, en un seul appel.

    Utilise ce tool quand l'utilisateur veut :
    - transformer un plan, un rapport ou des notes en présentation
    - créer plusieurs diapositives d'un coup

    Mots-clés : présentation depuis markdown, deck, plan en slides, générer diaporama

    Chaque titre de niveau 1 ou 2 ouvre une diapositive ; les listes et paragraphes
    qui suivent en deviennent les puces. Le nombre de diapositives réellement
    écrites est retourné — jamais une réussite supposée.

    Args:
        presentation_id: identifiant de la présentation (via slides_create)
        md: le plan en markdown
    Returns:
        {"status": "ok", "creees": N, "echouees": [...], "url": "..."}
    """
    sections: list[tuple[str, list[str]]] = []
    for bloc in analyser(md):
        if bloc.genre == "titre" and bloc.niveau <= 2:
            sections.append((bloc.lignes[0], []))
        elif not sections:
            continue
        elif bloc.genre in ("liste", "numerotee"):
            sections[-1][1].extend(bloc.lignes)
        elif bloc.genre == "paragraphe":
            sections[-1][1].append(" ".join(bloc.lignes))
        elif bloc.genre == "titre":
            sections[-1][1].append(bloc.lignes[0])

    if not sections:
        return {"status": "error",
                "error": "Aucun titre de niveau 1 ou 2 : rien pour découper en diapositives."}

    creees, echouees = 0, []
    for titre, puces in sections:
        res = slides_add_slide.invoke({
            "presentation_id": presentation_id, "titre": titre, "puces": puces})
        if res.get("status") == "ok":
            creees += 1
        else:
            echouees.append({"titre": titre, "error": res.get("error")})

    return {
        "status": "ok" if creees else "error",
        "creees": creees,
        "demandees": len(sections),
        "echouees": echouees,
        "url": _url(presentation_id),
    }


def _zones(slide: dict) -> dict[str, str]:
    """Associe le TYPE de zone de la mise en page à son identifiant d'objet."""
    trouvees: dict[str, str] = {}
    for element in slide.get("pageElements", []):
        forme = element.get("shape", {})
        genre = forme.get("placeholder", {}).get("type", "")
        if genre and genre not in trouvees:
            trouvees[genre] = element["objectId"]
    # Certaines mises en page nomment le corps « BODY », d'autres « SUBTITLE ».
    if "BODY" not in trouvees and "SUBTITLE" in trouvees:
        trouvees["BODY"] = trouvees["SUBTITLE"]
    if "TITLE" not in trouvees and "CENTERED_TITLE" in trouvees:
        trouvees["TITLE"] = trouvees["CENTERED_TITLE"]
    return trouvees
