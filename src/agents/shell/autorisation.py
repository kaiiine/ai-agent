"""Qui a le droit d'autoriser une commande — et ce n'est pas le modèle.

`shell_run` portait un paramètre `confirmed: bool`. Le modèle le remplissait
lui-même. Mesuré :

    shell_run("rm -rf /tmp/zzz_axon_preuve", confirmed=True)
      → status: ok      dossier supprimé, aucun humain n'a rien vu

Un seul appel suffisait. Toute la politique « demander TOUJOURS confirmation »
tenait dans une phrase de docstring adressée au modèle — c'est-à-dire dans une
obéissance, pas dans une garantie.

Ce magasin déplace l'autorisation hors de portée du modèle. Deux sources, une
seule règle : aucune des deux n'est quelque chose que le modèle peut produire.

    accorder()  — un humain a répondu « oui » à une question précise.
                  Usage UNIQUE et péremption courte : un accord ne peut être ni
                  rejoué plus tard, ni reporté sur une commande voisine.

    declarer()  — une permission permanente écrite dans la config par
                  l'utilisateur. Sert aux tâches planifiées, où personne n'est
                  là pour répondre. Elle ne se consomme pas : c'est une règle,
                  pas un jeton.

La clé est la commande EXACTE, à l'espacement de bord près. Pas de normalisation
plus large : accepter « la même commande à peu près » revient à autoriser une
famille de commandes à partir d'un accord donné pour une seule.

Le magasin vit CÔTÉ PROCESSUS, jamais dans l'état du graphe. Un état de graphe
est persisté et rejouable : un rejeu de checkpoint pourrait alors ressusciter une
autorisation déjà consommée, ce qui est exactement ce que « usage unique » doit
empêcher.
"""
from __future__ import annotations

import threading
import time

#: Durée par défaut d'un accord humain. Court volontairement : un « oui » donné
#: il y a dix minutes ne dit rien de la commande qu'on s'apprête à lancer.
DUREE_DEFAUT = 300

_verrou = threading.Lock()
#: commande exacte → instant de péremption
_accordees: dict[str, float] = {}
#: commandes permises en permanence, par source (« cron:<id> », …)
_declarees: dict[str, set[str]] = {}


def _cle(commande: str) -> str:
    return (commande or "").strip()


def accorder(commande: str, *, duree: int = DUREE_DEFAUT) -> None:
    """Enregistre un accord HUMAIN, valable une fois et pour un temps borné."""
    with _verrou:
        _accordees[_cle(commande)] = time.monotonic() + duree


def consommer(commande: str) -> bool:
    """L'accord existe-t-il ? Si oui il est CONSOMMÉ, et ne resservira pas.

    Consommer plutôt que consulter : sans cela, un « oui » donné pour une
    commande autoriserait toutes ses répétitions pendant la durée de validité,
    et une boucle du modèle pourrait la rejouer sans qu'on soit redemandé.
    """
    cle = _cle(commande)
    with _verrou:
        expire = _accordees.pop(cle, None)
        if expire is None:
            return False
        if time.monotonic() > expire:
            return False
        return True


def declarer(source: str, commandes: list[str]) -> None:
    """Déclare les commandes qu'une source non interactive a le droit de lancer.

    `source` identifie qui déclare (« cron:3f2a »), pour qu'on puisse retirer ses
    permissions sans toucher aux autres.
    """
    with _verrou:
        _declarees[source] = {_cle(c) for c in commandes if _cle(c)}


def retirer(source: str) -> None:
    with _verrou:
        _declarees.pop(source, None)


def est_declaree(commande: str) -> bool:
    """Une permission permanente couvre-t-elle cette commande, à l'identique ?"""
    cle = _cle(commande)
    with _verrou:
        return any(cle in permises for permises in _declarees.values())


def est_autorisee(commande: str) -> bool:
    """La porte unique. Une permission déclarée, sinon un accord humain consommé.

    L'ordre compte : une commande déclarée ne doit pas consommer l'accord humain
    d'une commande identique en attente — ce serait perdre silencieusement une
    confirmation, et faire croire qu'on l'a honorée.
    """
    return est_declaree(commande) or consommer(commande)


def reinitialiser() -> None:
    """Vide tout. Pour les tests, et pour un changement de session."""
    with _verrou:
        _accordees.clear()
        _declarees.clear()
