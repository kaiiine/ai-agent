"""Google Drive — chercher, lire, supprimer, sans surprise.

Quatre défauts corrigés, tous mesurés avant :

  1. une APOSTROPHE cassait la recherche. Le nom était interpolé dans une chaîne
     entre quotes simples et seuls les guillemets doubles étaient échappés, donc
     « Compte-rendu d'équipe » donnait `name contains 'Compte-rendu d'équipe'` :
     trois apostrophes, requête malformée, HTTP 400 ;
  2. les Drive PARTAGÉS étaient invisibles, faute de `includeItemsFromAllDrives` ;
  3. les PDF et les Slides remontaient « non supporté », alors que le PDF est le
     format le plus courant d'un Drive ;
  4. `permanently=True` supprimait définitivement, avec pour seule garde une
     phrase dans la docstring.

Aucun test ne touche l'API : les appels sont interceptés. Ce qui compte ici est
la REQUÊTE envoyée et la décision prise, pas la réponse de Google.
"""
from unittest.mock import MagicMock, patch

import pytest

from src.agents.google_drive.tools import (
    _echapper, drive_delete_file, drive_find_file_id, drive_list_files,
)


@pytest.fixture
def drive():
    """Un service Drive factice qui enregistre les paramètres reçus."""
    svc = MagicMock()
    with patch("src.agents.google_drive.tools.get_drive_service", return_value=svc):
        yield svc


# ── 1 · Une apostrophe ne casse plus la recherche ─────────────────────────────
@pytest.mark.parametrize("nom", [
    "Compte-rendu d'équipe",
    "Bilan de l'année",
    "Notes d'aujourd'hui",
])
def test_une_apostrophe_est_echappee(nom):
    """En français, un nom de fichier sur trois contient une apostrophe."""
    echappe = _echapper(nom)

    assert "\\'" in echappe
    assert echappe.count("'") == echappe.count("\\'")


def test_la_requete_reste_equilibree_avec_une_apostrophe(drive):
    drive.files.return_value.list.return_value.execute.return_value = {"files": []}

    drive_find_file_id.invoke({"name": "Compte-rendu d'équipe"})

    q = drive.files.return_value.list.call_args.kwargs["q"]
    # Les apostrophes non échappées doivent être en nombre PAIR : les deux
    # délimiteurs, et rien d'autre.
    nues = q.replace("\\'", "")
    assert nues.count("'") == 2, f"requête déséquilibrée : {q}"


def test_un_antislash_est_echappe_aussi():
    assert _echapper("a\\b") == "a\\\\b"


def test_un_nom_sans_apostrophe_n_est_pas_alteree():
    assert _echapper("Rapport Q3") == "Rapport Q3"


# ── 2 · Les Drive partagés sont visibles ──────────────────────────────────────
def test_la_recherche_inclut_les_drive_partages(drive):
    drive.files.return_value.list.return_value.execute.return_value = {"files": []}

    drive_find_file_id.invoke({"name": "budget"})

    kwargs = drive.files.return_value.list.call_args.kwargs
    assert kwargs["includeItemsFromAllDrives"] is True
    assert kwargs["supportsAllDrives"] is True


def test_le_listage_inclut_les_drive_partages(drive):
    drive.files.return_value.list.return_value.execute.return_value = {"files": []}

    drive_list_files.invoke({})

    kwargs = drive.files.return_value.list.call_args.kwargs
    assert kwargs["includeItemsFromAllDrives"] is True


def test_un_fichier_de_drive_partage_est_signale(drive):
    """Le savoir change la suite : un fichier d'équipe n'a pas les mêmes droits."""
    drive.files.return_value.list.return_value.execute.return_value = {"files": [
        {"id": "1", "name": "Budget", "driveId": "abc"},
        {"id": "2", "name": "Perso"},
    ]}

    res = drive_find_file_id.invoke({"name": "B"})

    assert [m["drive_partage"] for m in res["matches"]] == [True, False]


def test_le_listage_borne_la_taille_de_page(drive):
    """Drive refuse au-delà de 1000 ; la docstring annonçait 200 sans rien vérifier."""
    drive.files.return_value.list.return_value.execute.return_value = {"files": []}

    drive_list_files.invoke({"page_size": 99999})

    assert drive.files.return_value.list.call_args.kwargs["pageSize"] == 1000


# ── 3 · Ce qui contient du texte se lit ───────────────────────────────────────
@pytest.mark.parametrize("mime, export_attendu", [
    ("application/vnd.google-apps.document", "text/plain"),
    ("application/vnd.google-apps.spreadsheet", "text/csv"),
    ("application/vnd.google-apps.presentation", "text/plain"),
])
def test_les_formats_google_s_exportent(drive, mime, export_attendu):
    """Les présentations remontaient « non supporté » alors qu'un export texte
    donne les titres et les puces de chaque diapositive."""
    from src.agents.google_drive.tools import drive_read_file

    drive.files.return_value.get.return_value.execute.return_value = {
        "id": "x", "name": "Fichier", "mimeType": mime}
    drive.files.return_value.export.return_value.execute.return_value = b"du contenu"

    res = drive_read_file.invoke({"file_id": "x"})

    assert res["status"] == "ok"
    assert res["content"] == "du contenu"
    assert drive.files.return_value.export.call_args.kwargs["mimeType"] == export_attendu


def test_un_pdf_est_lu_par_l_extracteur_du_projet(drive, tmp_path):
    """Le PDF est le format le plus courant d'un Drive, et il était refusé.
    L'extraction réutilise `ui.attachments._extract_pdf` : en écrire un second
    garantirait qu'ils divergent."""
    from src.agents.google_drive import tools

    drive.files.return_value.get.return_value.execute.return_value = {
        "id": "x", "name": "Rapport.pdf", "mimeType": "application/pdf"}

    with patch.object(tools, "_telecharger", return_value=b"%PDF-1.4 factice"), \
         patch("src.ui.attachments._extract_pdf", return_value="[Page 1]\nDu texte"):
        res = tools.drive_read_file.invoke({"file_id": "x"})

    assert res["status"] == "ok"
    assert "Du texte" in res["content"]


def test_un_pdf_illisible_ne_leve_pas(drive):
    """Un PDF corrompu doit se dire, pas remonter en exception qui tue le tour."""
    from src.agents.google_drive import tools

    drive.files.return_value.get.return_value.execute.return_value = {
        "id": "x", "name": "Cassé.pdf", "mimeType": "application/pdf"}

    with patch.object(tools, "_telecharger", side_effect=ValueError("octets invalides")):
        res = tools.drive_read_file.invoke({"file_id": "x"})

    assert res["status"] == "error"
    assert "Extraction impossible" in res["error"]


def test_une_image_reste_non_supportee(drive):
    """Le contrepoids : accepter tout et rendre du binaire serait pire."""
    from src.agents.google_drive.tools import drive_read_file

    drive.files.return_value.get.return_value.execute.return_value = {
        "id": "x", "name": "photo.png", "mimeType": "image/png"}

    res = drive_read_file.invoke({"file_id": "x"})

    assert res["status"] == "unsupported"
    assert "image/png" in res["mime_type"]


def test_un_contenu_tronque_le_dit(drive):
    from src.agents.google_drive.tools import drive_read_file

    drive.files.return_value.get.return_value.execute.return_value = {
        "id": "x", "name": "Long", "mimeType": "application/vnd.google-apps.document"}
    drive.files.return_value.export.return_value.execute.return_value = b"x" * 60_000

    res = drive_read_file.invoke({"file_id": "x"})

    assert res["tronque"] is True
    assert len(res["content"]) == 50_000


# ── 4 · La suppression définitive exige une confirmation réelle ───────────────
def test_une_suppression_definitive_sans_le_nom_est_refusee(drive):
    """La garde d'origine était une phrase dans la docstring. Une docstring
    n'empêche rien : c'est au tool de refuser."""
    drive.files.return_value.get.return_value.execute.return_value = {"name": "Budget 2026"}

    res = drive_delete_file.invoke({"file_id": "x", "permanently": True})

    assert res["status"] == "confirmation_requise"
    assert res["nom_reel"] == "Budget 2026"
    drive.files.return_value.delete.assert_not_called()


def test_un_nom_de_confirmation_faux_est_refuse(drive):
    drive.files.return_value.get.return_value.execute.return_value = {"name": "Budget 2026"}

    res = drive_delete_file.invoke({
        "file_id": "x", "permanently": True, "confirmer_nom": "Budget"})

    assert res["status"] == "confirmation_requise"
    drive.files.return_value.delete.assert_not_called()


def test_le_bon_nom_autorise_la_suppression_definitive(drive):
    drive.files.return_value.get.return_value.execute.return_value = {"name": "Budget 2026"}

    res = drive_delete_file.invoke({
        "file_id": "x", "permanently": True, "confirmer_nom": "Budget 2026"})

    assert res["status"] == "ok"
    drive.files.return_value.delete.assert_called_once()


def test_la_corbeille_ne_demande_aucune_confirmation(drive):
    """Elle est réversible, et c'est le geste courant : l'alourdir pousserait
    l'agent vers la suppression définitive pour s'éviter une étape."""
    res = drive_delete_file.invoke({"file_id": "x"})

    assert res["status"] == "ok"
    assert "corbeille" in res["message"].lower()
    drive.files.return_value.update.assert_called_once()
    drive.files.return_value.delete.assert_not_called()
