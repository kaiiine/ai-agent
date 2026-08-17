"""Google Docs — le markdown arrive en STYLE, pas en caractères.

Défaut d'origine, et cause directe de « le rapport n'est pas fou » : le
paramètre s'appelait `md` et partait tel quel dans un `insertText`. Les dièses,
les astérisques et les tirets s'affichaient. Aucun titre, aucun gras, aucune
puce, aucun tableau — alors que l'API sait tout faire.

La traduction vit dans `src/infra/markdown_rendu`, partagée avec le mail, Slack
et les présentations : ce que l'un comprend, tous le rendent.
"""
from __future__ import annotations

from googleapiclient.errors import HttpError
from langchain_core.tools import tool

from src.infra.google_auth import get_docs_service
from src.infra.markdown_rendu import en_requetes_docs, requetes_cellules

#: Dernier document créé ou écrit dans ce processus, pour rattraper un `doc_id`
#: que le modèle n'a pas retenu.
#:
#: Il n'y a PLUS de cache par titre. L'ancien associait un titre à un identifiant
#: pour toujours : demander deux fois un Doc nommé « Rapport » rendait celui de la
#: première fois, et le contenu s'ajoutait à la fin de l'ancien. Un document
#: supprimé du Drive gardait aussi son entrée, donc un 404 définitif.
_DERNIER_DOC: str | None = None

#: L'API rejette un `batchUpdate` trop gros. Un rapport normal tient largement
#: dessous ; au-delà, on découpe plutôt que de se faire refuser l'ensemble.
_LOT = 400


def _valide(doc_id: str | None) -> str | None:
    if doc_id and len(doc_id) >= 20 and doc_id != "new_doc_id":
        return doc_id
    return _DERNIER_DOC


def _lots(requetes: list[dict]):
    for i in range(0, len(requetes), _LOT):
        yield requetes[i:i + _LOT]


@tool("google_docs_create")
def google_docs_create(title: str) -> dict:
    """
    Crée un nouveau Google Doc vide avec le titre donné.

    Utilise ce tool quand l'utilisateur veut :
    - créer un nouveau document Google Docs
    - démarrer un nouveau document partagé
    - créer un fichier texte dans Google Drive

    Mots-clés : créer document, Google Docs, nouveau fichier, document partagé, Drive

    Deux documents peuvent porter le même titre : chaque appel en crée un NOUVEAU.
    Pour réécrire un document existant, passe son doc_id à google_docs_write.

    Args:
        title: Titre du document
    Returns:
        {"status": "ok", "doc_id": "...", "title": "...", "url": "..."}
    """
    global _DERNIER_DOC
    try:
        svc = get_docs_service()
        doc = svc.documents().create(body={"title": title}).execute()
        doc_id = doc.get("documentId")
        _DERNIER_DOC = doc_id
        return {
            "status": "ok",
            "doc_id": doc_id,
            "title": title,
            "url": f"https://docs.google.com/document/d/{doc_id}/edit",
        }
    except HttpError as e:
        return {"status": "error", "error": f"Création impossible : {e}"}


@tool("google_docs_write")
def google_docs_write(md: str, doc_id: str = "", remplacer: bool = False) -> dict:
    """
    Écrit du markdown MIS EN FORME dans un Google Doc : titres, gras, puces, tableaux.

    Utilise ce tool quand l'utilisateur veut :
    - rédiger un rapport, un compte-rendu, une note dans un Google Doc
    - écrire ou compléter un document Google Docs
    - mettre à jour le contenu d'un doc partagé

    Mots-clés : écrire Doc, rapport, rédiger, ajouter contenu, Google Docs, mettre en forme

    Écris du markdown normal — il est TRADUIT en vrai style Google Docs :
        # Titre        → style Titre 1        **gras**      → gras
        ## Sous-titre  → style Titre 2        `code`        → police mono
        - point        → puce                 [texte](url)  → lien
        1. point       → liste numérotée      | a | b |     → vrai tableau
        > citation     → retrait              ---           → filet

    Args:
        md: le contenu en markdown
        doc_id: identifiant du document ; vide = le dernier document de la session
        remplacer: True vide le document avant d'écrire (pour refaire un rapport),
                   False ajoute à la fin (défaut)
    Returns:
        {"status": "ok", "doc_id": "...", "url": "...", "blocs": N, "tableaux": N}
    """
    global _DERNIER_DOC

    cible = _valide(doc_id)
    if not cible:
        return {
            "status": "error",
            "error": "Aucun doc_id valide et aucun document créé dans cette session. "
                     "Appelle google_docs_create d'abord.",
        }

    plan = en_requetes_docs(md)
    if not plan.requetes:
        return {"status": "error", "doc_id": cible, "error": "Contenu vide — rien à écrire."}

    try:
        svc = get_docs_service()

        if remplacer:
            doc = svc.documents().get(documentId=cible).execute()
            fin = doc["body"]["content"][-1].get("endIndex", 1)
            if fin > 2:
                svc.documents().batchUpdate(documentId=cible, body={"requests": [
                    {"deleteContentRange": {
                        "range": {"startIndex": 1, "endIndex": fin - 1}}}
                ]}).execute()

        for lot in _lots(plan.requetes):
            svc.documents().batchUpdate(documentId=cible, body={"requests": lot}).execute()

        # Les cellules d'un tableau n'ont d'index qu'une fois la grille créée : on
        # relit le document pour les apprendre, puis on les remplit.
        tableaux_remplis = 0
        if plan.tableaux:
            doc = svc.documents().get(documentId=cible).execute()
            cellules = requetes_cellules(doc, plan.tableaux)
            for lot in _lots(cellules):
                svc.documents().batchUpdate(documentId=cible, body={"requests": lot}).execute()
            tableaux_remplis = len(plan.tableaux)

        _DERNIER_DOC = cible
        return {
            "status": "ok",
            "doc_id": cible,
            "url": f"https://docs.google.com/document/d/{cible}/edit",
            "requetes": len(plan.requetes),
            "tableaux": tableaux_remplis,
            "mode": "remplacé" if remplacer else "ajouté",
        }
    except HttpError as e:
        if e.resp is not None and e.resp.status == 404:
            return {"status": "not_found", "doc_id": cible,
                    "error": "Document introuvable ou accès refusé."}
        return {"status": "error", "doc_id": cible, "error": str(e)}


@tool("google_docs_read")
def google_docs_read(doc_id: str) -> dict:
    """
    Lit le contenu d'un Google Doc, tableaux compris, en markdown.

    Utilise ce tool quand l'utilisateur veut :
    - lire un Google Doc
    - accéder au texte d'un document Google
    - voir le contenu d'un doc partagé

    Mots-clés : lire Google Doc, contenu document, texte, document partagé, Drive

    Args:
        doc_id: ID du document Google Docs
    Returns:
        {"status": "ok", "title": "...", "content": "...", "word_count": N, "url": "..."}
    """
    try:
        svc = get_docs_service()
        doc = svc.documents().get(documentId=doc_id).execute()
        return {
            "status": "ok",
            "title": doc.get("title", ""),
            "doc_id": doc_id,
            "content": _en_markdown(doc)[:50_000],
            "word_count": len(_en_markdown(doc).split()),
            "url": f"https://docs.google.com/document/d/{doc_id}/edit",
        }
    except HttpError as e:
        if e.resp is not None and e.resp.status == 404:
            return {"status": "not_found", "doc_id": doc_id,
                    "error": "Document introuvable ou accès refusé"}
        return {"status": "error", "doc_id": doc_id, "error": str(e)}


def _texte_paragraphe(paragraphe: dict) -> str:
    return "".join(pe.get("textRun", {}).get("content", "")
                   for pe in paragraphe.get("elements", []))


def _en_markdown(doc: dict) -> str:
    """Relit un document EN GARDANT sa structure.

    L'ancienne lecture concaténait les `textRun` des paragraphes : les titres
    perdaient leur niveau et les tableaux disparaissaient entièrement. Un agent
    qui relit son propre rapport pour le compléter n'y voyait donc plus les
    chiffres qu'il venait d'écrire.
    """
    niveaux = {f"HEADING_{i}": "#" * i for i in range(1, 7)}
    out: list[str] = []

    for element in doc.get("body", {}).get("content", []):
        if (paragraphe := element.get("paragraph")):
            texte = _texte_paragraphe(paragraphe).rstrip("\n")
            if not texte.strip():
                continue
            style = paragraphe.get("paragraphStyle", {}).get("namedStyleType", "")
            if (diese := niveaux.get(style)):
                out.append(f"{diese} {texte}")
            elif paragraphe.get("bullet"):
                out.append(f"- {texte}")
            else:
                out.append(texte)
            out.append("")
        elif (table := element.get("table")):
            rangees = []
            for rang in table.get("tableRows", []):
                cellules = []
                for cellule in rang.get("tableCells", []):
                    morceaux = [_texte_paragraphe(c["paragraph"]).strip()
                                for c in cellule.get("content", []) if "paragraph" in c]
                    cellules.append(" ".join(m for m in morceaux if m))
                rangees.append(cellules)
            if rangees:
                largeur = max(len(r) for r in rangees)
                for n, rang in enumerate(rangees):
                    rang = rang + [""] * (largeur - len(rang))
                    out.append("| " + " | ".join(rang) + " |")
                    if n == 0:
                        out.append("|" + "---|" * largeur)
                out.append("")

    return "\n".join(out).strip()
