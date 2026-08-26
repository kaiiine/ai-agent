"""Le pont lexical FR→EN : où il s'applique, et ce qu'il ne doit PAS attraper.

Les descriptions d'outils MCP viennent des serveurs, en anglais ; les requêtes
d'AXON sont en français. Le pont existait déjà, mesuré, mais seulement dans le
retriever de l'agent de code. Le chemin MCP de l'ORCHESTRATEUR interrogeait
l'index avec la requête française brute : `browser_click` ne remontait jamais,
pas même sur « clique sur le bouton accepter », parce que l'outil se décrit
« Perform click on a web page ».

Le régler par le `capabilities_hint` du serveur ne pouvait pas marcher — ce
texte ne pèse qu'à l'ÉTAGE 1, qui choisit le serveur, pas les outils. D'où le
test d'étage ci-dessous : il verrouille l'endroit, pas seulement l'effet.
"""
from __future__ import annotations

import pytest

from src.infra.pont_fr_en import PONT_FR_EN, pont_linguistique
from src.mcp_client.registry import route


# ── Ce que le pont ne doit PAS attraper ──────────────────────────────────────
@pytest.mark.parametrize("phrase, piege", [
    ("passe à une étape suivante", "tape"),
    ("la fonction renvoie la liste des clients", "envoie"),
    ("le champion du monde", "champ"),
    ("invalider le cache avant de relancer", "valider"),
    ("il faut recocher la case plus tard", "coche"),
])
def test_le_pont_compare_des_mots_entiers(phrase, piege):
    """La comparaison était `cle in texte`. Elle a tenu tant que les clés
    n'étaient contenues dans rien d'autre — l'auteur énumérait d'ailleurs
    « clique » ET « cliquer » plutôt que de compter sur le préfixe.

    Étendre le pont aux verbes d'action a exposé le défaut. `renvoie` et `étape`
    sont omniprésents dans les tâches françaises d'AXON : le pont aurait injecté
    du vocabulaire de formulaire à l'étage même où l'on choisit les outils."""
    assert piege in PONT_FR_EN, f"le piège testé n'existe plus : {piege}"
    ajout = pont_linguistique(phrase)
    traduction = PONT_FR_EN[piege]
    assert traduction not in ajout, (
        f"« {phrase} » déclenche « {piege} » → « {traduction} » par sous-chaîne")


# ── Ce qu'il doit attraper ───────────────────────────────────────────────────
@pytest.mark.parametrize("phrase, attendu", [
    ("clique sur le bouton accepter", "click"),
    ("tape mon adresse email", "type"),
    ("ajoute cet article au panier", "cart"),
    ("remplis le formulaire", "form"),
    ("sélectionne la taille XL", "select"),
    ("la page s'affiche mal", "renders"),      # apostrophe : la borne doit tenir
    ("dis-moi où en est le build", "status"),  # trait d'union
])
def test_le_pont_traduit_les_intentions_presentes(phrase, attendu):
    assert attendu in pont_linguistique(phrase), (
        f"« {phrase} » ne produit pas « {attendu} »")


def test_le_pont_ajoute_sans_remplacer():
    """Traduire à la place perdrait les noms propres et le vocabulaire technique
    que le français porte déjà correctement."""
    phrase = "clique sur le bouton dans framer-motion"
    resultat = pont_linguistique(phrase)
    assert resultat.startswith(phrase), "la requête française doit rester en tête"
    assert "framer-motion" in resultat


def test_une_requete_sans_intention_connue_est_rendue_telle_quelle():
    phrase = "le chat dort sur le canapé"
    assert pont_linguistique(phrase) == phrase


# ── L'ÉTAGE où il s'applique ─────────────────────────────────────────────────
class _IndexEspion:
    """Index factice qui retient les requêtes reçues par chaque étage."""

    def __init__(self):
        self.vu_etage1: list[str] = []
        self.vu_etage2: list[str] = []

    def query_servers(self, query, n=3):
        self.vu_etage1.append(query)
        return ["playwright"]

    def query_tools(self, query, k=7, where=None):
        self.vu_etage2.append(query)
        return ["playwright.browser_click"]


def test_le_pont_s_applique_a_l_etage_des_outils_pas_des_serveurs():
    """L'étage 1 interroge des documents de serveur dont le `capabilities_hint`
    est écrit EN FRANÇAIS par l'utilisateur ; le traduire le désaccorderait de
    sa propre langue. L'étage 2 interroge les descriptions fournies par les
    serveurs, en anglais — c'est là que le pont sert."""
    espion = _IndexEspion()
    route("clique sur le bouton accepter", espion)

    assert espion.vu_etage1 == ["clique sur le bouton accepter"], (
        "l'étage 1 doit voir la requête française intacte")
    assert "click" in espion.vu_etage2[0], (
        "l'étage 2 doit voir la traduction anglaise")
