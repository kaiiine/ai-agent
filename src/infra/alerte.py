"""Ce qui mérite qu'on réveille quelqu'un — sur le seul chemin que personne ne regarde.

Le TUI n'a pas besoin d'alerting : l'utilisateur est devant l'écran, une commande
refusée s'affiche, une erreur s'affiche. Le démon cron, lui, tourne sans témoin.
C'est là que les défauts coûtent, et c'est le seul endroit instrumenté ici.

Instance qui a décidé de la forme : une tâche planifiée a logué `status: "ok"`
alors que TOUTES ses commandes avaient été bloquées, faute de permission
déclarée. Le journal disait vrai ligne à ligne et faux en résumé. Une veille qui
échoue en silence est pire que pas de veille.

DÉTERMINISTE, et sans opinion. Des seuils lus sur la trace, jamais un modèle qui
juge — même motif que `guard.enforce` et que `verification.verifier` : ce qui
alerte doit être aussi fiable que ce qu'il surveille, sinon il ajoute une classe
d'échec au lieu d'en retirer une.

Ce module ne NOTIFIE pas. Il rend des raisons, et l'appelant les envoie sur ses
propres canaux — le démon a déjà Slack et le bureau câblés, et une dépendance
Slack ici les rendrait impossibles à tester sans réseau.
"""

from __future__ import annotations

import os

from src.infra import trace

#: Au-delà, un seul appel au modèle est signalé. Le défaut vient d'une mesure :
#: le plancher de schémas d'outils atteignait 30 outils / 12 731 tokens sur une
#: requête réelle, au-dessus de ce que Groq accepte — et personne ne l'a vu
#: avant que le tour échoue. Réglable, parce que le plafond dépend du backend.
SEUIL_TOKENS_DEFAUT = 12_000


def seuil_tokens() -> int:
    try:
        return int(os.environ.get("AXON_ALERTE_TOKENS") or SEUIL_TOKENS_DEFAUT)
    except (TypeError, ValueError):
        return SEUIL_TOKENS_DEFAUT


def evaluer(lignes: list[dict]) -> list[str]:
    """Les raisons d'alerter, sur les lignes de trace d'un run. Vide = rien à dire.

    Dédupliquées : dix commandes bloquées pour la même raison font une alerte,
    pas dix. Une notification qu'on trouve bavarde finit coupée, et c'est le jour
    d'après qu'elle aurait servi.
    """
    raisons: list[str] = []

    def ajouter(raison: str) -> None:
        if raison not in raisons:
            raisons.append(raison)

    for ligne in lignes:
        resultat = str(ligne.get("resultat") or "")
        outil = str(ligne.get("outil") or "?")
        cible = str(ligne.get("cible") or "")
        detail = f" ({cible[:60]})" if cible else ""

        if ligne.get("policy") == trace.REFUSE or resultat == trace.BLOQUE:
            # Le cas qui a motivé le module. On dit AUSSI le remède : une alerte
            # qui n'indique pas quoi faire se relit deux fois et s'ignore.
            ajouter(f"`{outil}` a été refusé{detail} — personne n'était là pour "
                    f"confirmer. Déclare-le dans `commandes_autorisees` de la "
                    f"tâche s'il doit tourner sans surveillance.")
        elif resultat == trace.ERREUR:
            code = str(ligne.get("erreur") or "erreur")
            ajouter(f"`{outil}` a échoué{detail} — {code}.")

        if ligne.get("verification") == "casse":
            ajouter(f"Fichier écrit mais CASSÉ : {cible[:80]}.")

        total = int(ligne.get("tokens_entree") or 0)
        if total > seuil_tokens():
            ajouter(f"Appel au modèle à {total:,} tokens d'entrée, au-dessus du "
                    f"seuil de {seuil_tokens():,}.".replace(",", " "))

    return raisons


def du_run(run_id: str) -> list[str]:
    """Les raisons d'alerter pour ce run, relues depuis la trace.

    Relire plutôt que d'accumuler en mémoire : le démon écrit déjà ses lignes,
    et une seconde comptabilité en parallèle finirait par diverger de la
    première — c'est exactement le défaut que la trace existe pour supprimer.

    Coût : le journal entier est relu, plafonné à 5 Mo par la rotation, soit une
    centaine de millisecondes. À comparer aux secondes que la tâche vient de
    passer dans des appels de modèle — l'optimiser serait payer une divergence
    pour rien.
    """
    if not run_id:
        return []
    return evaluer([l for l in trace.lire() if l.get("run_id") == run_id])
