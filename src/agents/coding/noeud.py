"""Le nœud qui délègue à l'agent de code.

L'agent tournait DANS un outil : `run_coding_agent` appelait la boucle et rendait
son résultat. Un outil est atomique pour le moteur, et son enveloppe est
ré-entrée à chaque reprise — trace mesurée avant de changer quoi que ce soit :

    ['outil-entree', 'travail-lourd', 'outil-entree', 'apres-accord:oui']

L'étape checkpointée n'était pas rejouée, mais tout ce que l'enveloppe faisait
avant l'invocation l'était. Invoqué depuis un NŒUD, il n'y a plus d'enveloppe.

Même motif que `deep_research` → `approfondir` : l'outil ne travaille pas, il
POSE un marqueur ; le routeur voit le marqueur et donne la main au nœud.
"""
from __future__ import annotations

import json
import re
from typing import Any

from langchain_core.messages import ToolMessage

from src.orchestrator.note_interne import note

MARQUEUR = "tache_de_code_demandee"

#: L'événement d'affichage du rapport final de l'agent de code.
RAPPORT = "specialist:rapport"

_TRACE = re.compile(r"\[SPECIALIST-TRACE\](.*?)\[/SPECIALIST-TRACE\]\s*", re.DOTALL)


def _separer(resultat: str) -> tuple[str, list[str], list[str]]:
    """Le rapport lisible, les fichiers touchés, l'état du plan.

    La trace est de la plomberie : `cwd:`, `files:`, `plan:`. Elle n'était retirée
    que par la relecture de thread — partout ailleurs elle partait au modèle et
    s'affichait.
    """
    fichiers: list[str] = []
    etapes: list[str] = []
    trouve = _TRACE.search(resultat)
    if trouve:
        for ligne in trouve.group(1).splitlines():
            if ligne.startswith("files:"):
                fichiers = [c.strip() for c in ligne[6:].split(",") if c.strip()]
            elif ligne.startswith("plan:"):
                etapes = [e for e in ligne[5:].split("|") if e.strip()]
    return _TRACE.sub("", resultat).strip(), fichiers, etapes


def _faute_de_conclusion(fichiers: list[str], etapes: list[str]) -> str:
    """Ce qui s'est passé, quand le modèle n'en dit rien lui-même.

    Le sous-graphe rend « la trace + le texte du DERNIER `AIMessage` ». Or ce
    dernier message porte souvent des appels d'outils — un `shell_run` de
    vérification — et son texte est alors VIDE. Vécu : le fichier écrit, relu,
    exécuté deux fois avec succès, et pour toute conclusion « L'agent de code n'a
    rien produit ». Le travail avait eu lieu ; c'est le récit qui manquait.

    On ne redemande pas au modèle — un appel de plus pour un texte qu'il vient de
    ne pas écrire. On dit les faits qu'on tient déjà.
    """
    if not fichiers and not etapes:
        return ""
    morceaux: list[str] = []
    if fichiers:
        morceaux.append("Fichiers écrits : " + ", ".join(fichiers) + ".")
    restantes = [e[1:].strip() for e in etapes if e.startswith("○")]
    faites = [e for e in etapes if e.startswith("✓")]
    if faites:
        morceaux.append(f"{len(faites)} étape(s) du plan sur {len(etapes)} achevée(s).")
    if restantes:
        morceaux.append("Reste : " + " ; ".join(restantes) + ".")
    morceaux.append("(L'agent de code n'a pas rédigé de conclusion.)")
    return " ".join(morceaux)


def tache_a_coder(message: Any) -> str | None:
    """La tâche dont ce résultat d'outil demande l'exécution."""
    if not isinstance(message, ToolMessage) or not isinstance(message.content, str):
        return None
    try:
        charge = json.loads(message.content)
    except (ValueError, TypeError):
        return None
    if not isinstance(charge, dict) or charge.get("status") != MARQUEUR:
        return None
    tache = charge.get("tache")
    return tache if isinstance(tache, str) and tache.strip() else None


#: Au-delà, on donne le chemin plutôt que le contenu : le sous-graphe a de quoi
#: lire lui-même, et un contexte d'ouverture démesuré coûte à chaque tour.
_PIECES_MAX = 20_000


def _pieces_jointes() -> str:
    """Ce que l'utilisateur a joint à son tour, remis à l'agent de code.

    Il ne recevait qu'une chaîne de tâche : joindre un PDF de cahier des charges
    puis demander « code ce qui est décrit dedans » ne lui transmettait que la
    phrase. Le contenu était pourtant lu — il restait dans l'historique de
    l'orchestrateur, de l'autre côté de la frontière.

    Les IMAGES ne traversent pas : aucun backend ne déclare ici s'il sait les
    lire, et envoyer du base64 à un modèle qui ne le sait pas casse l'appel. On
    dit qu'elles existent, sans les joindre.
    """
    try:
        from src.ui.attachments import attachments
    except Exception:
        return ""
    try:
        jointes = attachments.derniers
    except Exception:
        return ""
    if not jointes:
        return ""

    blocs: list[str] = []
    for piece in jointes:
        if piece.is_image:
            blocs.append(f"[Image jointe : {piece.name} — tu ne peux pas la voir ; "
                         f"demande ce qu'elle montre si tu en as besoin.]")
        elif len(piece.content) > _PIECES_MAX and piece.source_path:
            blocs.append(f"[Fichier joint : {piece.name} — trop long pour être "
                         f"recopié. Lis-le avec local_read_file(\"{piece.source_path}\").]")
        else:
            langue = piece.name.rsplit(".", 1)[-1] if "." in piece.name else ""
            blocs.append(f"Fichier joint : {piece.name}\n```{langue}\n"
                         f"{piece.content}\n```")
    return ("[PIÈCES JOINTES par l'utilisateur, pour cette tâche]\n\n"
            + "\n\n".join(blocs))


def coder(state: dict) -> dict:
    """Fait tourner l'agent de code comme un sous-graphe du graphe principal.

    Compilé sans checkpointer, il hérite de celui du parent : ses pas sont
    checkpointés dans le même fil, ses `interrupt()` remontent d'eux-mêmes, et
    une reprise continue au lieu de tout refaire.
    """
    from langgraph.errors import GraphBubbleUp

    from src.agents.coding.pending import dev_plan
    from src.agents.coding.specialist import (
        _vram_swap_in, _vram_swap_out, preparer,
    )

    messages = state.get("messages") or []
    tache = tache_a_coder(messages[-1] if messages else None) or ""
    if not tache:
        return {"messages": []}

    pieces = _pieces_jointes()

    _vram_swap_in()
    try:
        # Écrire un fichier exige d'avoir planifié — le temps de ce run seulement.
        with dev_plan.run_specialist(tache):
            graphe, finaliser = preparer(tache)
            resultat = finaliser(graphe.invoke({"tache": tache, "pieces": pieces}))
    except GraphBubbleUp:
        # Une interruption n'est PAS une erreur : c'est le graphe qui demande.
        # L'attraper la transformait en « l'agent de code a échoué », et la
        # confirmation n'atteignait jamais l'utilisateur — vérifié avant de
        # l'écrire, la demande était bien posée puis avalée ici.
        raise
    except Exception as erreur:      # noqa: BLE001 — rapporté, jamais avalé
        resultat = (f"L'agent de code a échoué : {type(erreur).__name__}: {erreur}. "
                    "Dis-le à l'utilisateur sans inventer de résultat.")
    finally:
        _vram_swap_out()

    # Le rapport est MONTRÉ, pas re-raconté. Il partait à l'orchestrateur — un
    # autre modèle — avec « restitue-le sans rien y ajouter ». Une prière, pas une
    # garantie : vécu, l'agent avait écrit un vrai résumé, et l'orchestrateur l'a
    # jeté pour répondre lui-même à la demande d'origine en réimprimant un script
    # DIFFÉRENT de celui du disque. Un texte qui existe déjà n'a rien à gagner à
    # repasser par un modèle.
    rapport, fichiers, etapes = _separer(resultat)
    rapport = rapport or _faute_de_conclusion(fichiers, etapes)
    _afficher(rapport)

    # Un message HUMAIN, pas un second `ToolMessage` : l'outil a déjà rendu le
    # sien avec le marqueur, et deux résultats pour un même appel déséquilibrent
    # les paires. Même choix que `approfondir`. Mais COMPACT : ce que
    # l'orchestrateur n'a pas sous les yeux, il ne peut pas le récrire de travers.
    return {"messages": [note(_consigne(tache, rapport, fichiers))]}


def _afficher(rapport: str) -> None:
    """Montre le rapport de l'agent de code, tel qu'il l'a écrit."""
    if not rapport:
        return
    from src.agents.coding.specialist import _notifier

    _notifier(RAPPORT, {"texte": rapport})


def _consigne(tache: str, rapport: str, fichiers: list[str]) -> str:
    if not rapport:
        return (f"L'agent de code n'a rien produit sur « {tache[:80]} ». Dis-le à "
                f"l'utilisateur sans inventer de résultat.")
    touches = (" Fichiers touchés : " + ", ".join(fichiers) + "." if fichiers else "")
    return (f"L'agent de code a terminé « {tache[:80]} », et son rapport est DÉJÀ "
            f"affiché à l'utilisateur.{touches} Ne le répète pas, et n'écris aucun "
            f"code : ce qui est sur le disque fait foi. S'il reste une autre étape à "
            f"la demande de l'utilisateur, fais-la maintenant ; sinon réponds par une "
            f"seule phrase courte, ou par rien du tout.")
