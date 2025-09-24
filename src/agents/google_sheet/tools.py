from langchain_core.tools import tool
from googleapiclient.discovery import build
from ...infra.google_auth import get_docs_service  # ou util dédié sheets

def get_sheets_service():
    # implémentation analogue aux autres
    return build("sheets", "v4", credentials=build("docs","v1")._http.credentials)

@tool
def create_sheet(title: str) -> str:
    """
    Crée une nouvelle feuille de calcul Google Sheets. Utiliser SEULEMENT quand l'utilisateur demande explicitement de créer une feuille de calcul.
    
    Args:
        title: Nom de la feuille de calcul à créer
    Returns:
        ID de la feuille créée (à conserver pour ajouter des données)
    """
    svc = get_sheets_service()
    sheet = svc.spreadsheets().create(body={"properties": {"title": title}}).execute()
    return sheet.get("spreadsheetId")

@tool
def add_rows(spreadsheet_id: str, rows: list[list[str]], sheet_name: str = "Feuille 1") -> str:
    """
    Ajoute des lignes de données à une feuille existante. Nécessite l'ID obtenu avec create_sheet.
    
    Args:
        spreadsheet_id: ID de la feuille (depuis create_sheet)
        rows: Données sous forme de liste de listes [["Col1", "Col2"], ["Val1", "Val2"]]
        sheet_name: Nom de l'onglet (par défaut "Feuille 1")
    Returns:
        Message de confirmation
    """
    svc = get_sheets_service()
    rng = f"{sheet_name}!A1"
    svc.spreadsheets().values().append(
        spreadsheetId=spreadsheet_id,
        range=rng,
        valueInputOption="RAW",
        insertDataOption="INSERT_ROWS",
        body={"values": rows}
    ).execute()
    return f"✅ Lignes ajoutées à `{spreadsheet_id}`"
