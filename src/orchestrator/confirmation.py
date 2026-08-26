"""L'accord de l'utilisateur, demandé par le graphe — jamais par le modèle.

`shell_run` rend `requires_confirmation` quand une commande est destructive ou
non reconnue. Ce statut était produit à trois endroits et consommé NULLE PART :
la suite dépendait entièrement du bon vouloir du modèle, qui pouvait aussi bien
passer `confirmed=True` du premier coup. Mesuré :

    shell_run("rm -rf /tmp/zzz_axon_preuve", confirmed=True)
      → status: ok      dossier supprimé, aucun humain n'a rien vu

Le paramètre a disparu (cf. `shell/autorisation.py`). Ce module fournit l'autre
moitié : c'est le GRAPHE qui pose la question, et lui seul qui inscrit l'accord.

LE SLOT
-------
Un seul questionnaire en vol, TOUS TYPES CONFONDUS — une clarification et une
confirmation ne peuvent pas coexister. Une demande qui arrive alors que le slot
est pris est REFUSÉE, pas mise en file et surtout pas écrasée.

Refusée plutôt qu'en file, délibérément : une file ferait répondre à la question
n°2 sur une commande qu'on n'a plus sous les yeux, et ajoute des bugs d'ordre et
de péremption. Le refus est bruyant et rattrapable — le modèle réessaie une fois
la première tranchée.

L'invariant qui compte, et qu'un test surveille : AUCUN chemin ne libère le slot
sans avoir accordé ou refusé. S'il en existait un, une confirmation se perdrait
en silence — et on retomberait de fait sur « pas de confirmation du tout » sans
que personne l'ait décidé.

Le slot vit CÔTÉ PROCESSUS, jamais dans l'état du graphe : un état de graphe est
persisté et rejouable, et un rejeu ressusciterait une autorisation consommée.
"""
from __future__ import annotations

import json
import threading
import time
from typing import Any
from uuid import uuid4

from langchain_core.messages import AIMessage, ToolMessage

from src.agents.shell.autorisation import accorder

#: Au-delà, un questionnaire sans réponse est considéré abandonné et le slot est
#: rendu. Sans péremption, une session interrompue bloquerait toute confirmation
#: ultérieure pour la durée du processus.
PEREMPTION = 900

OUI, NON = "Oui, exécuter", "Non, annuler"

_verrou = threading.Lock()
_en_vol: dict[str, Any] | None = None


# ── Le slot ──────────────────────────────────────────────────────────────────
def reserver(genre: str, cle: str, tool_call_id: str) -> bool:
    """Prend le slot. Rend False s'il est déjà pris par autre chose."""
    global _en_vol
    with _verrou:
        if _en_vol is not None:
            if time.monotonic() - _en_vol["t"] < PEREMPTION:
                return _en_vol["cle"] == cle      # ré-entrance sur la MÊME demande
            # Périmé : on le rend, en le disant. Ce n'est pas un accord.
            _en_vol = None
        _en_vol = {"genre": genre, "cle": cle, "tool_call_id": tool_call_id,
                   "t": time.monotonic()}
        return True


def liberer(tool_call_id: str | None = None) -> dict[str, Any] | None:
    """Rend le slot et retourne ce qu'il contenait.

    Passer `tool_call_id` protège d'une libération par un tour qui n'est pas
    celui qui a réservé — c'est ce qui ferait disparaître une confirmation en
    attente au profit d'une autre.
    """
    global _en_vol
    with _verrou:
        if _en_vol is None:
            return None
        if tool_call_id is not None and _en_vol["tool_call_id"] != tool_call_id:
            return None
        ancien, _en_vol = _en_vol, None
        return ancien


def en_vol() -> dict[str, Any] | None:
    with _verrou:
        if _en_vol and time.monotonic() - _en_vol["t"] >= PEREMPTION:
            return None
        return dict(_en_vol) if _en_vol else None


def reinitialiser() -> None:
    global _en_vol
    with _verrou:
        _en_vol = None


# ── Lecture des messages ─────────────────────────────────────────────────────
def _charge(message: Any) -> dict | None:
    if not isinstance(message, ToolMessage) or not isinstance(message.content, str):
        return None
    try:
        charge = json.loads(message.content)
    except (ValueError, TypeError):
        return None
    return charge if isinstance(charge, dict) else None


def commande_a_confirmer(message: Any) -> str | None:
    """La commande dont ce résultat d'outil réclame l'autorisation."""
    charge = _charge(message)
    if not charge or charge.get("status") != "requires_confirmation":
        return None
    commande = charge.get("command")
    return commande if isinstance(commande, str) and commande.strip() else None


def _question(charge: dict, commande: str) -> dict[str, Any]:
    """Ce que l'utilisateur doit lire AVANT de répondre.

    L'aperçu d'écriture est repris tel quel quand il existe : approuver une
    commande sans voir ce qu'elle écrit, c'est approuver un effet inconnu.
    """
    motif = charge.get("reason")
    entete = {"destructive": "Commande DESTRUCTIVE",
              "inconnue": "Commande non reconnue comme sûre"}.get(motif, "Commande")
    if charge.get("host"):
        entete = f"Écriture sur {charge['host']} (machine DISTANTE)"
    corps = [f"{entete} :", "", commande]
    apercu = charge.get("preview")
    if isinstance(apercu, str) and apercu.strip():
        corps += ["", apercu]
    return {"question": "\n".join(corps), "choices": [NON, OUI]}


# ── Le nœud ──────────────────────────────────────────────────────────────────
def confirmer(state: dict) -> dict:
    """Émet le questionnaire d'autorisation. Réserve le slot au passage."""
    dernier = state["messages"][-1]
    charge = _charge(dernier) or {}
    commande = commande_a_confirmer(dernier) or ""
    identifiant = f"confirm_{uuid4().hex[:16]}"
    reserver("confirmation", commande, identifiant)
    return {"messages": [AIMessage(
        content="",
        tool_calls=[{"name": "ask_clarification",
                     "args": {"questions": [_question(charge, commande)]},
                     "id": identifiant}],
    )]}


def reponse_de_confirmation(message: Any) -> tuple[str, bool] | None:
    """(commande, accordée) si ce message répond au questionnaire en vol."""
    charge = _charge(message)
    if charge is None or "answers" not in charge:
        return None
    attendu = en_vol()
    if not attendu or attendu["genre"] != "confirmation":
        return None
    if getattr(message, "tool_call_id", None) != attendu["tool_call_id"]:
        return None
    texte = json.dumps(charge.get("answers"), ensure_ascii=False)
    return attendu["cle"], OUI in texte


def enregistrer_reponse(state: dict) -> dict:
    """Inscrit l'accord s'il y en a un, libère le slot dans TOUS les cas.

    Un refus libère aussi : le slot ne doit pas rester pris parce que la réponse
    était « non ». Et l'accord est inscrit AVANT la libération, pour qu'aucune
    fenêtre ne laisse un slot libre sans que la décision soit enregistrée.
    """
    dernier = state["messages"][-1]
    lu = reponse_de_confirmation(dernier)
    if lu is None:
        return {"messages": []}
    commande, accordee = lu
    if accordee:
        accorder(commande)
    liberer(getattr(dernier, "tool_call_id", None))
    if not accordee:
        return {"messages": [AIMessage(
            content=f"L'utilisateur a refusé l'exécution de : {commande}")]}
    # Réémettre l'appel : sans cela, l'accord serait donné et rien ne partirait.
    return {"messages": [AIMessage(
        content="",
        tool_calls=[{"name": "shell_run", "args": {"command": commande},
                     "id": f"apres_accord_{uuid4().hex[:12]}"}],
    )]}


def apres_enregistrement(state: dict) -> str:
    """Où aller après avoir inscrit la décision.

    Un ACCORD réémet l'appel `shell_run` : il doit repasser par le nœud d'outils.
    Un REFUS ne produit qu'un message : l'envoyer à `tools` planterait, puisqu'il
    ne porte aucun appel. Distinguer les deux est la raison d'être de cette arête.
    """
    dernier = (state.get("messages") or [None])[-1]
    return "tools" if getattr(dernier, "tool_calls", None) else "chatbot"
