"""Le garde des paris ne doit jamais bloquer une réponse qui ne parle pas d'argent.

Vécu, sur une question d'architecture RAG : la réponse s'est fait remplacer par
« DATA_UNAVAILABLE — réponse bloquée », avec une liste de griefs VIDE. Le seul
déclencheur était le mot « sécurisé », dans la phrase « les composants qui
rendent le système robuste, scalable et sécurisé en production ».

Deux défauts se cumulaient :

  1. `s[ée]curis[ée]` figurait seul dans le motif de langage trompeur. Ce mot est
     du français courant — une connexion, un stockage, un protocole sont
     sécurisés — et ne trompe QUE collé à un objet de pari.

  2. `enforce` s'applique à TOUTE réponse finale, quel que soit le sujet du
     tour. Un signal purement langagier (« sûr », « garanti ») suffisait donc à
     détruire une réponse légitime sur n'importe quel sujet.

Un garde d'argent qui se déclenche hors du domaine ne protège rien : il fait
perdre le travail du tour et laisse l'utilisateur sans réponse.
"""
from __future__ import annotations

import pytest

from src.agents.quant.conversation.guard import enforce


HORS_SUJET = [
    "Ce diagramme montre le flux avec les composants qui rendent le système "
    "robuste, scalable et sécurisé en production.",
    "En production, le stockage est sécurisé et chiffré au repos.",
    "Utilise une connexion sécurisée entre les deux services.",
    "Le protocole TLS rend l'échange sécurisé.",
    "Un déploiement blue-green est plus sûr qu'un remplacement direct.",
    "Cette migration est garantie sans perte de données par le fournisseur.",
    "Le typage rend le code plus dur à casser.",
]


@pytest.mark.parametrize("texte", HORS_SUJET)
def test_un_texte_sans_pari_n_est_jamais_bloque(texte):
    verdict = enforce(texte, None)
    assert not verdict.blocked, (
        f"réponse hors sujet bloquée par le garde des paris ({verdict.reason})")


PARIS_TROMPEURS = [
    "ce pari est sécurisé",
    "mise sécurisée sur ce match",
    "un combiné sécurisé à jouer ce soir",
    "gain sécurisé avec cette cote",
    "ce pari est sûr, il va passer",
    "pari garanti sans risque",
    "banco sur ce match",
    "c'est de l'argent facile",
    "je suis sûr à 95 % que ce pari passe",
]


@pytest.mark.parametrize("texte", PARIS_TROMPEURS)
def test_le_langage_trompeur_de_pari_reste_bloque(texte):
    """Le resserrement ne doit rien ouvrir : c'est la moitié qui protège."""
    assert enforce(texte, None).blocked, f"« {texte} » devrait être bloqué"


def test_le_message_de_blocage_nomme_toujours_un_grief():
    """Un blocage dont la liste de griefs est vide dit à l'utilisateur qu'on lui
    a retiré sa réponse sans pouvoir dire pourquoi. Si plus aucun signal de pari
    n'est présent, il ne doit pas y avoir de blocage du tout."""
    verdict = enforce("ce pari est garanti sans risque", None)
    assert verdict.blocked
    assert "affirmations non sourcées" not in verdict.replacement, (
        "grief vide : le garde bloque sans savoir ce qu'il reproche")


def test_une_certitude_chiffree_reste_interdite_meme_hors_contexte():
    """Le resserrement ne touche QUE les mots ordinaires. « garanti à 95 % »
    présente une probabilité comme un fait : c'est une fausse déclaration dans
    n'importe quel domaine, et le contrat produit l'interdit depuis l'origine.

    Ma première version l'avait rangée avec « sécurisé » et l'ouvrait donc hors
    contexte de pari — un test existant l'a refusé, à raison."""
    for phrase in ("garanti à 95 %", "Une certitude de 90 % sur ce marché.",
                   "90 % certain de passer.", "Ce pari est sûr à 90 %."):
        verdict = enforce(phrase, None)
        assert verdict.blocked, f"« {phrase} » devrait rester bloquée"
        assert verdict.reason == "MISLEADING_LANGUAGE"


def test_le_predicat_de_domaine_suit_la_meme_porte_que_le_routage():
    """`_parle_de_pari` réutilise `_money_intent`, la porte qui décide déjà si une
    requête est une demande d'argent. Deux définitions divergentes du « domaine
    du pari » finiraient par se contredire."""
    import inspect

    from src.agents.quant.conversation import guard

    source = inspect.getsource(guard._parle_de_pari)
    assert "_money_intent" in source
