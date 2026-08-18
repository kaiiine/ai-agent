"""Google Sheets — les deux outils étaient morts au premier appel.

Le constructeur de service était resté un brouillon, commentaire compris :

    return build("sheets", "v4",
                 credentials=build("docs", "v1")._http.credentials)

Il construisait un client Docs SANS identifiants pour lui voler un attribut
privé. Mesuré : `DefaultCredentialsError` avant tout appel réseau. Les deux
outils étaient donc inutilisables depuis toujours, et `SCOPES_SHEETS` existait
dans `google_auth` sans que personne l'appelle.

Attention au premier usage : le jeton actuel a été obtenu sans le droit Sheets.
Le flux OAuth demande `SCOPES_ALL`, donc une reconsentation peut être nécessaire —
`_load_credentials` la déclenche seule quand un droit manque.
"""
from __future__ import annotations

from googleapiclient.errors import HttpError
from langchain_core.tools import tool

from src.infra.google_auth import get_sheets_service


def _url(spreadsheet_id: str) -> str:
    return f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit"


@tool("sheets_create")
def sheets_create(title: str) -> dict:
    """
    Crée une nouvelle feuille de calcul Google Sheets.

    Utilise ce tool quand l'utilisateur veut :
    - créer un tableur, une feuille de calcul, un Google Sheet
    - démarrer un suivi chiffré, un budget, un tableau de données

    Mots-clés : tableur, feuille de calcul, Google Sheets, créer, budget, suivi

    Args:
        title: Nom de la feuille de calcul
    Returns:
        {"status": "ok", "spreadsheet_id": "...", "url": "...", "onglet": "..."}
    """
    try:
        svc = get_sheets_service()
        feuille = svc.spreadsheets().create(
            body={"properties": {"title": title}}).execute()
        sid = feuille.get("spreadsheetId")
        onglets = feuille.get("sheets", [])
        # Le nom de l'onglet par défaut dépend de la LANGUE du compte : « Sheet1 »
        # ou « Feuille 1 ». L'ancien code le supposait en dur, donc toute écriture
        # visait une plage inexistante sur un compte anglophone. On le lit.
        onglet = (onglets[0]["properties"]["title"] if onglets else "Sheet1")
        return {"status": "ok", "spreadsheet_id": sid, "url": _url(sid),
                "onglet": onglet, "title": title}
    except HttpError as e:
        return {"status": "error", "error": f"Création impossible : {e}"}
    except Exception as e:                                       # noqa: BLE001
        return {"status": "error", "error": f"Authentification Sheets : {e}"}


@tool("sheets_append_rows")
def sheets_append_rows(spreadsheet_id: str, rows: list[list[str]],
                       onglet: str = "") -> dict:
    """
    Ajoute des lignes à la fin d'une feuille de calcul existante.

    Utilise ce tool quand l'utilisateur veut :
    - ajouter des données, des lignes, des enregistrements à un tableur
    - remplir un Google Sheet

    Mots-clés : ajouter lignes, remplir tableur, données, Google Sheets, insérer

    Args:
        spreadsheet_id: identifiant de la feuille (via sheets_create ou drive_find_file_id)
        rows: lignes à ajouter, ex. [["Date", "Montant"], ["2026-08-17", "120"]]
        onglet: nom de l'onglet ; vide = le premier onglet de la feuille
    Returns:
        {"status": "ok", "lignes_ajoutees": N, "plage": "...", "url": "..."}
    """
    if not rows:
        return {"status": "error", "error": "Aucune ligne à ajouter."}
    try:
        svc = get_sheets_service()
        if not onglet:
            meta = svc.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
            onglet = meta["sheets"][0]["properties"]["title"]
        res = svc.spreadsheets().values().append(
            spreadsheetId=spreadsheet_id,
            range=f"'{onglet}'!A1",
            valueInputOption="USER_ENTERED",   # les nombres et dates restent typés
            insertDataOption="INSERT_ROWS",
            body={"values": [[("" if c is None else str(c)) for c in r] for r in rows]},
        ).execute()
        maj = res.get("updates", {})
        return {
            "status": "ok",
            "lignes_ajoutees": maj.get("updatedRows", len(rows)),
            "plage": maj.get("updatedRange", ""),
            "url": _url(spreadsheet_id),
        }
    except HttpError as e:
        if e.resp is not None and e.resp.status == 404:
            return {"status": "not_found",
                    "error": "Feuille introuvable ou accès refusé."}
        return {"status": "error", "error": str(e)}
    except Exception as e:                                       # noqa: BLE001
        return {"status": "error", "error": f"Authentification Sheets : {e}"}


@tool("sheets_read")
def sheets_read(spreadsheet_id: str, plage: str = "") -> dict:
    """
    Lit les valeurs d'une feuille de calcul Google Sheets.

    Utilise ce tool quand l'utilisateur veut :
    - lire un tableur, consulter des chiffres, récupérer des données
    - analyser le contenu d'un Google Sheet

    Mots-clés : lire tableur, données, Google Sheets, valeurs, consulter, chiffres

    Args:
        spreadsheet_id: identifiant de la feuille
        plage: plage A1 (ex. "A1:D20") ; vide = tout le premier onglet
    Returns:
        {"status": "ok", "rangees": [[...]], "lignes": N, "markdown": "| … |"}
    """
    try:
        svc = get_sheets_service()
        if not plage:
            meta = svc.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
            plage = f"'{meta['sheets'][0]['properties']['title']}'"
        res = svc.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id, range=plage).execute()
        rangees = res.get("values", [])
        return {
            "status": "ok",
            "rangees": rangees,
            "lignes": len(rangees),
            "markdown": _en_markdown(rangees),
            "url": _url(spreadsheet_id),
        }
    except HttpError as e:
        if e.resp is not None and e.resp.status == 404:
            return {"status": "not_found",
                    "error": "Feuille introuvable ou accès refusé."}
        return {"status": "error", "error": str(e)}
    except Exception as e:                                       # noqa: BLE001
        return {"status": "error", "error": f"Authentification Sheets : {e}"}


def _en_markdown(rangees: list[list[str]]) -> str:
    """Un tableau markdown, pour que le modèle puisse le recopier dans un rapport.

    C'est le point de jonction avec `markdown_rendu` : ce que Sheets rend ici
    repart tel quel vers un Doc, un mail ou Slack, et y devient un vrai tableau.
    """
    if not rangees:
        return ""
    largeur = max(len(r) for r in rangees)
    lignes = []
    for n, rang in enumerate(rangees):
        cellules = [str(rang[c]) if c < len(rang) else "" for c in range(largeur)]
        lignes.append("| " + " | ".join(cellules) + " |")
        if n == 0:
            lignes.append("|" + "---|" * largeur)
    return "\n".join(lignes)
