"""Les autorisations d'exécuter une commande shell.

Deux sources, aucune que le modèle puisse produire :

    accorder()  — un humain a répondu oui. Usage UNIQUE et péremption courte.
    declarer()  — permission permanente écrite en config, pour les tâches
                  planifiées où personne ne peut répondre.

La clé est la commande exacte, à l'espacement de bord près : « la même commande
à peu près » autoriserait une famille à partir d'un accord donné pour une seule.

Le magasin vit côté processus, jamais dans l'état du graphe — qui est persisté et
rejouable, donc capable de ressusciter une autorisation consommée.
"""
from __future__ import annotations

import threading
import time

#: Durée d'un accord humain. Court : un « oui » d'il y a dix minutes ne dit rien
#: de la commande qu'on s'apprête à lancer.
DUREE_DEFAUT = 300

_verrou = threading.Lock()
#: commande exacte → instant de péremption
_accordees: dict[str, float] = {}
#: commandes permises en permanence, par source (« cron:<id> », …)
_declarees: dict[str, set[str]] = {}


def _cle(commande: str) -> str:
    return (commande or "").strip()


def accorder(commande: str, *, duree: int = DUREE_DEFAUT) -> None:
    """Enregistre un accord humain, valable une fois et pour `duree` secondes."""
    with _verrou:
        _accordees[_cle(commande)] = time.monotonic() + duree


def consommer(commande: str) -> bool:
    """L'accord existe et n'est pas périmé — et il est consommé au passage.

    Consommer plutôt que consulter : sinon un « oui » autoriserait toutes les
    répétitions de la commande pendant sa durée de validité.
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
    """Les commandes qu'une source non interactive a le droit de lancer.

    `source` identifie qui déclare (« cron:3f2a »), pour un retrait ciblé.
    """
    with _verrou:
        _declarees[source] = {_cle(c) for c in commandes if _cle(c)}


def retirer(source: str) -> None:
    with _verrou:
        _declarees.pop(source, None)


def est_declaree(commande: str) -> bool:
    """Une permission déclarée couvre cette commande, à l'identique."""
    cle = _cle(commande)
    with _verrou:
        return any(cle in permises for permises in _declarees.values())


def est_autorisee(commande: str) -> bool:
    """La porte unique : permission déclarée, sinon accord humain consommé.

    L'ordre compte — une commande déclarée ne doit pas consommer l'accord humain
    d'une commande identique en attente.
    """
    return est_declaree(commande) or consommer(commande)


def reinitialiser() -> None:
    """Vide tout — tests et changement de session."""
    with _verrou:
        _accordees.clear()
        _declarees.clear()
