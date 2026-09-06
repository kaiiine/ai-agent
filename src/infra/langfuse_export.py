"""Pousser la trace vers un Langfuse auto-hébergé — par lots, jamais en ligne.

L'EXPORT EST UN LECTEUR, PAS UN CAPTEUR. La trace est écrite par `trace.py`,
sur le disque, sans réseau ; ce module la relit et l'envoie. Trois conséquences
qui ont décidé de cette forme plutôt que d'un callback dans le graphe :

    · AXON tourne sans Langfuse, hors ligne, et sans rien perdre. Un capteur en
      ligne fait dépendre le tour d'un service tiers — pour un journal, c'est
      inverser le rapport de force.
    · L'export est REJOUABLE. Langfuse a été mal configuré, l'instance était
      éteinte, la clé était fausse : on relance, rien n'a été perdu.
    · Rien à installer pour que la trace fonctionne.

PAS LE SDK, l'API d'ingestion. Le client Python de Langfuse a changé d'interface
entre ses versions majeures (v2 objet, v3 sur OpenTelemetry) : câbler l'une
condamne à la réécrire à la suivante, et ajoute une dépendance à un dépôt qui
tient à n'en avoir aucune ici. L'endpoint d'ingestion, lui, prend un lot JSON en
authentification basique et ne bouge pas — `requests` suffit, et il est déjà là.

IDENTIFIANTS DÉTERMINISTES : `run_id` sert d'identifiant de trace, `run_id-seq`
d'identifiant d'observation. Langfuse met à jour au lieu d'insérer, donc un
double export ne fabrique pas de doublons. C'est ce qui rend l'opération sûre à
relancer sans réfléchir.

Configuration (`.env`) :

    LANGFUSE_HOST=http://localhost:3000
    LANGFUSE_PUBLIC_KEY=pk-lf-...
    LANGFUSE_SECRET_KEY=sk-lf-...

NON VÉRIFIÉ CONTRE UNE INSTANCE RÉELLE au moment d'écrire : aucun Langfuse ne
tournait sur la machine de développement. Le lot est construit et sérialisé sous
test, l'envoi ne l'est pas. À éprouver au premier branchement.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from src.infra import trace

#: Jusqu'où le dernier export est allé. Sans elle, chaque passage renverrait tout
#: le journal — sans dommage, grâce aux identifiants déterministes, mais pour
#: rien.
REPERE = Path.home() / ".axon" / "langfuse_export.json"

#: Taille d'un lot. L'API accepte de gros corps, mais un lot énorme échoue en
#: entier : découper rend l'échec partiel et réessayable.
_LOT = 200


def _config() -> tuple[str, str, str]:
    return (
        (os.environ.get("LANGFUSE_HOST") or "http://localhost:3000").rstrip("/"),
        os.environ.get("LANGFUSE_PUBLIC_KEY") or "",
        os.environ.get("LANGFUSE_SECRET_KEY") or "",
    )


def _niveau(ligne: dict) -> str:
    """Le niveau Langfuse d'une action. Un refus n'est pas une erreur.

    Bloqué veut dire « le garde a fait son travail » : le peindre en ERROR
    noierait les vraies pannes sous des refus attendus.
    """
    resultat = ligne.get("resultat")
    if resultat == trace.ERREUR or ligne.get("verification") == "casse":
        return "ERROR"
    if resultat == trace.BLOQUE or ligne.get("policy") == trace.REFUSE:
        return "WARNING"
    return "DEFAULT"


def _horodatage(ligne: dict) -> str:
    return str(ligne.get("at") or datetime.now(timezone.utc).isoformat())


def _fin(ligne: dict) -> str:
    """L'instant de fin, déduit de la latence. Faute de latence, la fin est le
    début : une durée inventée serait pire qu'une durée absente."""
    debut = _horodatage(ligne)
    latence = int(ligne.get("latence_ms") or 0)
    if latence <= 0:
        return debut
    try:
        instant = datetime.fromisoformat(debut)
    except ValueError:
        return debut
    return (instant + timedelta(milliseconds=latence)).isoformat()


def _evenement(type_: str, corps: dict) -> dict:
    return {"id": uuid4().hex, "timestamp": datetime.now(timezone.utc).isoformat(),
            "type": type_, "body": corps}


def construire(lignes: list[dict]) -> list[dict]:
    """Le lot d'événements Langfuse pour ces lignes de trace.

    Séparé de l'envoi pour être testable sans réseau : c'est la construction qui
    porte les décisions — quelle action devient quoi, avec quel niveau.
    """
    evenements: list[dict] = []
    vus: set[str] = set()

    for ligne in lignes:
        run = str(ligne.get("run_id") or "")
        if not run:
            continue
        if run not in vus:
            vus.add(run)
            evenements.append(_evenement("trace-create", {
                "id": run,
                "name": f"axon:{ligne.get('source') or 'tui'}",
                "timestamp": _horodatage(ligne),
                "input": ligne.get("intent") or "",
                "tags": [t for t in (ligne.get("source"), ligne.get("axon_sha")) if t],
                "metadata": {"axon_sha": ligne.get("axon_sha") or "",
                             "source": ligne.get("source") or ""},
            }))

        commun: dict[str, Any] = {
            "id": f"{run}-{ligne.get('seq', 0)}",
            "traceId": run,
            "name": f"{ligne.get('genre') or 'action'}"
                    + (f":{ligne['outil']}" if ligne.get("outil") else ""),
            "startTime": _horodatage(ligne),
            "endTime": _fin(ligne),
            "level": _niveau(ligne),
            "statusMessage": str(ligne.get("erreur") or ""),
            # Les colonnes d'AXON en entier. Ce sont elles que Langfuse ne
            # saurait pas produire seul — c'est tout l'intérêt de l'exporter.
            "metadata": {k: ligne.get(k) for k in (
                "genre", "policy", "confirmation", "resultat", "verification",
                "groupes", "outils_lies", "cible", "extra") if ligne.get(k)},
        }

        if ligne.get("genre") == trace.APPEL_LLM:
            evenements.append(_evenement("generation-create", {
                **commun,
                "model": ligne.get("modele") or ligne.get("backend") or "",
                "usage": {"input": int(ligne.get("tokens_entree") or 0),
                          "output": int(ligne.get("tokens_sortie") or 0),
                          "unit": "TOKENS"},
            }))
        else:
            evenements.append(_evenement("span-create", commun))

    return evenements


def _depuis_le_repere(lignes: list[dict]) -> list[dict]:
    try:
        repere = json.loads(REPERE.read_text(encoding="utf-8")).get("at") or ""
    except Exception:                                            # noqa: BLE001
        return lignes
    return [l for l in lignes if str(l.get("at") or "") > repere] if repere else lignes


def _poser_le_repere(lignes: list[dict]) -> None:
    if not lignes:
        return
    try:
        REPERE.parent.mkdir(parents=True, exist_ok=True)
        REPERE.write_text(json.dumps(
            {"at": max(str(l.get("at") or "") for l in lignes)}), encoding="utf-8")
    except Exception:                                            # noqa: BLE001
        pass


def exporter(lignes: list[dict], *, console=None, tout: bool = False) -> int:
    """Envoie les lignes non encore exportées. Rend un code de sortie."""
    import requests

    hote, publique, secrete = _config()
    dire = console.print if console is not None else print
    if not publique or not secrete:
        dire("\n  LANGFUSE_PUBLIC_KEY et LANGFUSE_SECRET_KEY manquent — "
             "rien n'a été envoyé.")
        dire("  Instance auto-hébergée : voir docs/monitoring.md\n")
        return 1

    a_envoyer = lignes if tout else _depuis_le_repere(lignes)
    if not a_envoyer:
        dire("\n  rien de nouveau depuis le dernier export.\n")
        return 0

    evenements = construire(a_envoyer)
    envoyes = 0
    for debut in range(0, len(evenements), _LOT):
        lot = evenements[debut:debut + _LOT]
        try:
            reponse = requests.post(
                f"{hote}/api/public/ingestion",
                auth=(publique, secrete), json={"batch": lot}, timeout=30)
        except Exception as erreur:                              # noqa: BLE001
            dire(f"\n  échec réseau vers {hote} : "
                 f"{type(erreur).__name__}: {erreur}")
            dire(f"  {envoyes} événement(s) envoyé(s) avant l'échec — "
                 f"relance, l'export est rejouable.\n")
            return 1
        if reponse.status_code >= 400:
            dire(f"\n  Langfuse a refusé le lot ({reponse.status_code}) : "
                 f"{reponse.text[:300]}\n")
            return 1
        envoyes += len(lot)

    _poser_le_repere(a_envoyer)
    dire(f"\n  {envoyes} événement(s) envoyés à {hote}  ·  "
         f"{len({l.get('run_id') for l in a_envoyer})} run(s)\n")
    return 0
