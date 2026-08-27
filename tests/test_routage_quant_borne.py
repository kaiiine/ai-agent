"""Le groupe le plus lourd ne s'invite pas au quatrième rang.

Vécu, sur une question de stockage : « il me reste combien de stockage ? »
embarquait les SEPT outils de paris sportifs. La tournure « il me reste
combien » ressemble à « combien il me reste à miser », et « espérance de gain »
comme « bankroll » figurent dans la description du groupe. Il sortait 4e — et
les cinq premiers groupes étaient tous retenus.

Le coût est mesurable, et il est lourd : ces sept outils pèsent ~5 000 tokens de
schémas, dont 1 984 pour `betting_recommend` seul.

    « il me reste combien de stockage ? »   13 174 tk  →  7 217 tk   (−45 %)

Sur une RTX 3070 Ti (8 Go), où un modèle qui ne tient pas en VRAM lit à 124
tokens/s, ces 5 957 tokens en trop valaient 48 secondes d'ingestion pour un
`df -h`.

Le remède existait déjà : `coding` porte un `requires_top_rank=3` pour la même
raison — ne pas mettre une action lourde à portée d'une requête qui ne la demande
pas. Le seuil est à 3, et pas plus bas. Première tentative à 2 : un test de
non-régression l'a refusée, à raison — les demandes qui POURSUIVENT une
conversation de paris n'ont ni le vocabulaire ni le rang 1. Les rangs mesurés
séparent proprement à 3 :

    rang 1   six demandes explicites de paris
    rang 2   « tous les sports et toutes les compétitions »
    rang 3   « uniquement l'ATP aujourd'hui »
    rang 4   « il me reste combien de stockage ? »   ← le seul à exclure
"""
import pytest

from src.orchestrator.registry import build_all_tools
from src.orchestrator.tool_retriever import TOOL_GROUPS, ToolRetriever, _money_intent

PARIS = {"betting_recommend", "winamax_odds_fetch", "sports_stats_fetch",
         "probability_compute", "ev_analyze", "parlay_analyze",
         "same_match_combo_analyze"}


@pytest.fixture(scope="module")
def retriever():
    return ToolRetriever(build_all_tools())


def _outils_de_paris(retriever, query: str) -> int:
    return len(PARIS & {t.name for t in retriever.get(query)})


# ── Ce que le garde-fou empêche ───────────────────────────────────────────────
@pytest.mark.parametrize("query", [
    "il me reste combien de stockage ?",
    "combien il me reste de place disque",
    "quelle heure est-il ?",
    "coucou",
])
def test_une_requete_sans_rapport_n_embarque_aucun_outil_de_paris(retriever, query):
    assert _outils_de_paris(retriever, query) == 0


# ── Ce qu'il ne doit pas casser ───────────────────────────────────────────────
@pytest.mark.parametrize("query", [
    "quels paris jouer ce soir ?",
    "scanne les matchs de demain, j'ai 20 balles",
    "cote de PSG-Marseille chez winamax",
    "est-ce un bon value bet ?",
    "analyse la forme de Liverpool",
    "combien miser sur ce combiné ?",
    # Poursuites de conversation : ni vocabulaire de paris, ni rang 1. Ce sont
    # elles qui fixent le seuil à 3 plutôt qu'à 2.
    "tous les sports et toutes les competitions",
    "uniquement l'ATP aujourd'hui",
])
def test_une_vraie_demande_de_paris_atteint_son_domaine(retriever, query):
    """Le contrepoids : le seuil ne doit pas rendre le domaine inatteignable.

    Ce test exigeait les SEPT outils. Ce n'était pas ce qu'il vérifiait — il
    vérifiait que `requires_top_rank=3` ne coupe pas le domaine —, et le groupe
    déclare depuis des familles d'intention : demander les cotes n'appelle ni le
    calcul de probabilité ni l'analyse d'un combiné. Ce qui doit rester vrai est
    l'ACCÈS au domaine, et `betting_recommend` en est l'unique chemin. Un outil
    de la famille visée qui manquerait reste réclamable au catalogue."""
    lies = PARIS & {t.name for t in retriever.get(query)}
    assert "betting_recommend" in lies, query
    assert len(lies) >= 2, lies


# ── Le mécanisme ──────────────────────────────────────────────────────────────
def test_le_groupe_quant_declare_un_seuil_de_rang():
    """Sans lui, les cinq premiers groupes sont tous retenus, quel que soit
    l'écart de pertinence entre le premier et le cinquième."""
    assert TOOL_GROUPS["quant"].requires_top_rank == 3


def test_le_seuil_de_rang_ne_desarme_pas_le_filet_lexical(retriever):
    """Piège introduit par le seuil : une porte qui ajoute son groupe en QUEUE le
    place au rang 6 ou plus, et `requires_top_rank` l'écarte aussitôt — le filet
    devient silencieusement inopérant.

    Écrit sur le comportement, pas sur le texte de `get()`. Deux tests de cette
    famille vérifiaient chacun une chaîne de code différente pour dire cette
    seule chose, et ils se contredisaient : l'un exigeait
    `groups.append(_MONEY_GROUP)`, l'autre `[_MONEY_GROUP] + groups`. L'un des
    deux était donc rouge en permanence, et le refactor suivant a fait tomber les
    deux. Un invariant se garde par ce qu'il produit.
    """
    # Formulation SANS vocabulaire de pari pour le sémantique, mais que la porte
    # lexicale reconnaît : c'est exactement le cas que le seuil pourrait tuer.
    requete = "combien miser sur ce combiné ?"
    assert _money_intent(requete)
    # Le compte exact des sept outils servait à dire « le domaine est atteint ».
    # Depuis que `quant` déclare des familles d'intention, une demande de combiné
    # ramène le combiné, pas le domaine entier — ce qui reste vérifiable est que
    # la porte a bien ouvert le domaine, et sur la bonne famille.
    lies = PARIS & {t.name for t in retriever.get(requete)}
    assert "betting_recommend" in lies, "le seuil de rang a désarmé la porte lexicale"
    assert lies & {"parlay_analyze", "same_match_combo_analyze"}, lies


def test_la_porte_ne_retire_jamais_un_groupe(retriever):
    """Elle ADJOINT `quant`, elle ne substitue rien : ce que le sémantique avait
    élu doit survivre à son ouverture."""
    requete = "quel temps fait-il à Paris ?"
    sans_porte = {t.name for t in retriever.get("quel temps fait-il à Lyon ?")}
    avec = {t.name for t in retriever.get(requete)}
    assert "get_weather_by_city" in avec, \
        f"la porte a évincé la météo : {sorted(avec)[:8]}"
    assert sans_porte & avec


def test_le_filet_lexical_reste_efficace(retriever):
    """Une demande que le sémantique raterait doit encore être rattrapée par le
    vocabulaire — c'est la raison d'être de `_money_intent`."""
    assert _money_intent("combien miser sur ce combiné ?")
    # Le domaine, pas son inventaire : `quant` déclare des familles d'intention
    # et ne rend plus ses sept outils sur chaque demande.
    lies = PARIS & {t.name for t in retriever.get("combien miser sur ce combiné ?")}
    assert "betting_recommend" in lies, lies


def test_le_gain_en_tokens_est_reel(retriever):
    """L'invariant qui justifie le chantier : la requête fautive doit tomber
    nettement sous son coût d'origine."""
    import json
    from datetime import date

    import tiktoken

    from src.llm.prompts import build_system_prompt

    enc = tiktoken.get_encoding("o200k_base")
    outils = retriever.get("il me reste combien de stockage ?")
    sysp = build_system_prompt([t.name for t in outils], date.today().isoformat(),
                               "kaine", lang="fr")
    schemas = json.dumps(
        [{"name": t.name, "description": t.description,
          "parameters": t.args_schema.model_json_schema() if t.args_schema else {}}
         for t in outils], ensure_ascii=False)

    total = len(enc.encode(sysp)) + len(enc.encode(schemas))

    assert total < 9_000, f"{total} tokens — l'entrée devrait avoir fondu (13 174 avant)"
