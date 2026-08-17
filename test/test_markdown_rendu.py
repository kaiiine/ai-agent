"""Un markdown, plusieurs destinations — et aucune qui laisse passer les marques.

Ce fichier garde la correction du défaut central de la revue Workspace : le modèle
écrit toujours le même markdown, et une seule surface le traduisait.

    Docs    le paramètre s'appelait `md` et partait dans un `insertText` : les
            dièses et les astérisques s'AFFICHAIENT
    mail    conversion présente, mais sans l'extension `tables` — un tableau,
            que tout rapport contient, arrivait en pipes bruts
    Slack   aucune conversion, seulement une consigne en docstring
    slides  le titre et les puces étaient jetés

Les tests ci-dessous portent sur l'analyseur et les rendus, pas sur les API : ce
qui part chez Google et Slack n'est pas vérifiable ici, mais tout ce qui décide de
l'apparence l'est.
"""
import pytest

from src.infra.markdown_rendu import (
    analyser, en_blocs_slack, en_html, en_requetes_docs, en_texte, fragments,
    requetes_cellules,
)

RAPPORT = """# Rapport Q3

Voici la **synthèse** avec du `code` et un [lien](https://exemple.fr).

## Revenus

| Métrique | Valeur |
|---|---|
| Revenus | 12 400 € |
| Marge | 31 % |

- **Croissance** : +12 %
- Marge stable

1. Premier
2. Second

> Une citation

---

```python
x = 1
```
"""


# ── Analyse ───────────────────────────────────────────────────────────────────
def test_un_rapport_complet_se_decoupe_en_blocs():
    genres = [b.genre for b in analyser(RAPPORT)]

    assert genres == ["titre", "paragraphe", "titre", "tableau", "liste",
                      "numerotee", "citation", "regle", "code"]


def test_des_pipes_sans_separateur_ne_sont_pas_un_tableau():
    """« Le total | la marge » est une phrase, pas une grille. Sans ligne de
    tirets, les pipes restent du texte."""
    blocs = analyser("Le total | la marge sont bons")

    assert [b.genre for b in blocs] == ["paragraphe"]


def test_un_bloc_de_code_garde_ses_asterisques():
    """Une marque DANS du code n'est pas une marque — sinon un extrait de code
    ressort à moitié en gras."""
    (bloc,) = analyser("```\nx = a ** b\n```")

    assert bloc.genre == "code"
    assert bloc.lignes == ("x = a ** b",)


@pytest.mark.parametrize("texte, attendu", [
    ("**gras**",            [("gras", True, False, False)]),
    ("_italique_",          [("italique", False, True, False)]),
    ("`code`",              [("code", False, False, True)]),
    ("**gras et `code`**",  [("gras et ", True, False, False), ("code", True, False, True)]),
])
def test_les_marques_en_ligne_se_cumulent(texte, attendu):
    obtenu = [(f.texte, f.gras, f.italique, f.code) for f in fragments(texte)
              if f.texte]

    assert obtenu == attendu


def test_un_soulignement_dans_une_url_n_est_pas_de_l_italique():
    (f,) = [f for f in fragments("[t](https://x.fr/a_b_c)") if f.texte]

    assert f.lien == "https://x.fr/a_b_c" and not f.italique


def test_une_marque_non_fermee_reste_du_texte():
    """Un rapport à moitié écrit vaut mieux qu'une exception."""
    assert "".join(f.texte for f in fragments("**pas fermé")) == "**pas fermé"


def test_analyser_ne_leve_jamais():
    for entree in ("", None, "#", "|", "```", "> ", "- "):
        analyser(entree)


# ── Mail ──────────────────────────────────────────────────────────────────────
def test_un_tableau_devient_une_vraie_table_html():
    """Le défaut mesuré : l'extension `tables` manquait, donc un tableau arrivait
    en pipes bruts dans un paragraphe."""
    html = en_html(RAPPORT)

    assert "<table" in html and "<th " in html and "<td " in html
    assert "| Métrique |" not in html


def test_le_html_du_mail_n_utilise_aucune_feuille_de_style():
    """Les règles vivaient dans un `<style>` placé DANS un `<td>`. Plusieurs
    clients dont Outlook l'ignorent, et une règle ignorée rend le rapport nu sans
    que personne le sache."""
    html = en_html(RAPPORT)

    assert "<style" not in html
    assert 'style="' in html, "tout doit être en style en ligne"


def test_chaque_bloc_du_mail_porte_son_style():
    html = en_html(RAPPORT)

    for balise in ("<h1", "<p", "<ul", "<ol", "<blockquote", "<pre", "<hr", "<table"):
        i = html.index(balise)
        assert 'style="' in html[i:i + 240], f"{balise} sans style en ligne"


def test_le_html_echappe_ce_qui_ressemble_a_du_html():
    html = en_html("Compare `<script>` et 5 < 6")

    assert "<script>" not in html
    assert "&lt;script&gt;" in html


# ── Version texte du mail ─────────────────────────────────────────────────────
def test_la_version_texte_ne_montre_aucune_marque():
    """Elle compte : un client en mode texte, ou un lecteur d'écran, ne voit
    qu'elle. Y laisser le markdown brut serait le défaut d'origine, déplacé."""
    texte = en_texte(RAPPORT)

    assert "**" not in texte and "##" not in texte
    assert "|---|" not in texte
    assert "Croissance" in texte and "12 400 €" in texte


def test_la_version_texte_aligne_les_colonnes():
    texte = en_texte("| a | valeur longue |\n|---|---|\n| b | x |")

    assert "valeur longue" in texte
    lignes = [l for l in texte.split("\n") if l.strip()]
    assert len({len(l.rstrip()) for l in lignes}) > 1  # colonnes remplies, pas brutes


# ── Slack ─────────────────────────────────────────────────────────────────────
def test_slack_recoit_des_blocs_et_pas_du_markdown():
    blocs = en_blocs_slack(RAPPORT)
    genres = [b["type"] for b in blocs]

    assert "header" in genres, "un titre doit devenir un header Block Kit"
    assert "divider" in genres
    assert "section" in genres


def test_slack_utilise_son_propre_dialecte_de_gras():
    """`**gras**` s'affiche littéralement dans Slack ; c'est `*gras*` qu'il veut."""
    corps = str(en_blocs_slack("Voici la **synthèse** finale"))

    assert "*synthèse*" in corps
    assert "**synthèse**" not in corps


def test_slack_ne_laisse_aucun_diese_de_titre():
    corps = str(en_blocs_slack("# Titre\n## Sous-titre\n### Petit"))

    assert "# Titre" not in corps and "## Sous-titre" not in corps


def test_un_tableau_reste_lisible_dans_slack():
    """Slack n'a pas de tableaux. Une grille alignée dans un bloc de code reste
    lisible, là où des pipes bruts ne le sont pas."""
    corps = str(en_blocs_slack("| Métrique | Valeur |\n|---|---|\n| Marge | 31 % |"))

    assert "```" in corps and "Métrique" in corps and "31 %" in corps


def test_slack_respecte_ses_limites():
    """Slack refuse une section de plus de 3000 caractères et un message de plus
    de 50 blocs. Se faire rejeter le message entier pour un rapport long serait
    le défaut « ça plante »."""
    blocs = en_blocs_slack("\n\n".join(f"Paragraphe {i} " + "x" * 400 for i in range(60)))

    assert len(blocs) <= 50
    for b in blocs:
        if b["type"] == "section":
            assert len(b["text"]["text"]) <= 3000


# ── Google Docs ───────────────────────────────────────────────────────────────
def test_les_titres_deviennent_des_styles_nommes():
    """Le cœur du défaut : le markdown arrivait en caractères, pas en style."""
    requetes = en_requetes_docs("# Titre\n## Sous-titre").requetes
    styles = [r["updateParagraphStyle"]["paragraphStyle"]["namedStyleType"]
              for r in requetes if "updateParagraphStyle" in r]

    assert set(styles) == {"HEADING_1", "HEADING_2"}


def test_le_texte_insere_ne_contient_plus_les_marques():
    requetes = en_requetes_docs("Voici la **synthèse** et du `code`").requetes
    insere = "".join(r["insertText"]["text"] for r in requetes if "insertText" in r)

    assert "**" not in insere and "`" not in insere
    assert "synthèse" in insere and "code" in insere


def test_le_gras_devient_un_style_de_texte():
    requetes = en_requetes_docs("Voici la **synthèse** finale").requetes
    gras = [r for r in requetes
            if "updateTextStyle" in r and r["updateTextStyle"]["textStyle"].get("bold")]

    assert len(gras) == 1
    plage = gras[0]["updateTextStyle"]["range"]
    assert plage["endIndex"] - plage["startIndex"] == len("synthèse")


def test_le_gras_vise_le_bon_endroit_dans_la_ligne():
    """La plage est calculée depuis la position du fragment, pas depuis le début
    du bloc : un décalage d'un caractère mettrait le mot voisin en gras."""
    requetes = en_requetes_docs("abc **gras**").requetes
    (style,) = [r["updateTextStyle"] for r in requetes
                if "updateTextStyle" in r and r["updateTextStyle"]["textStyle"].get("bold")]

    assert style["range"]["startIndex"] == 1 + len("abc ")


def test_une_liste_recoit_de_vraies_puces():
    requetes = en_requetes_docs("- un\n- deux").requetes
    puces = [r for r in requetes if "createParagraphBullets" in r]

    assert len(puces) == 1
    assert "BULLET" in puces[0]["createParagraphBullets"]["bulletPreset"]


def test_une_liste_numerotee_recoit_des_numeros():
    requetes = en_requetes_docs("1. un\n2. deux").requetes
    (puces,) = [r for r in requetes if "createParagraphBullets" in r]

    assert "NUMBERED" in puces["createParagraphBullets"]["bulletPreset"]


def test_un_lien_devient_un_lien_cliquable():
    requetes = en_requetes_docs("voir [le site](https://exemple.fr)").requetes
    liens = [r["updateTextStyle"]["textStyle"]["link"]["url"] for r in requetes
             if "updateTextStyle" in r and "link" in r["updateTextStyle"]["textStyle"]]

    assert liens == ["https://exemple.fr"]


def test_les_requetes_sont_en_ordre_inverse_du_document():
    """C'est ce qui rend le calcul d'index tenable : chaque bloc s'insère à
    l'index 1 et se style sur [1, 1+len] avant que le suivant ne le repousse.
    Insérer dans l'ordre obligerait à recalculer chaque index après chaque
    requête, et casserait au premier bloc dont la longueur rendue diffère."""
    requetes = en_requetes_docs("# Premier\n\n# Dernier").requetes
    inseres = [r["insertText"]["text"] for r in requetes if "insertText" in r]

    assert inseres[0].strip() == "Dernier"
    assert all(r["insertText"]["location"]["index"] == 1
               for r in requetes if "insertText" in r)


def test_un_tableau_est_annonce_pour_un_second_passage():
    """Les cellules n'ont d'index qu'une fois la grille créée : elles ne peuvent
    pas être remplies dans le même appel."""
    plan = en_requetes_docs(RAPPORT)

    assert any("insertTable" in r for r in plan.requetes)
    assert len(plan.tableaux) == 1
    assert plan.tableaux[0][0] == ("Métrique", "Valeur")


def test_les_cellules_se_remplissent_a_rebours():
    """Écrire dans une cellule décale toutes les suivantes : il faut donc partir
    de la dernière."""
    document = {"body": {"content": [{"table": {"tableRows": [
        {"tableCells": [{"startIndex": 10}, {"startIndex": 20}]},
        {"tableCells": [{"startIndex": 30}, {"startIndex": 40}]},
    ]}}]}}
    grille = (("A", "B"), ("C", "D"))

    requetes = requetes_cellules(document, [grille])
    index = [r["insertText"]["location"]["index"] for r in requetes if "insertText" in r]

    assert index == sorted(index, reverse=True)


def test_l_entete_du_tableau_est_en_gras():
    document = {"body": {"content": [{"table": {"tableRows": [
        {"tableCells": [{"startIndex": 10}]},
        {"tableCells": [{"startIndex": 20}]},
    ]}}]}}

    requetes = requetes_cellules(document, [(("Métrique",), ("Marge",))])
    gras = [r for r in requetes
            if "updateTextStyle" in r and r["updateTextStyle"]["textStyle"].get("bold")]

    assert len(gras) == 1, "seule la première rangée est une en-tête"
