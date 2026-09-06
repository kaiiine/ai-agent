"""La trace de décision — une ligne par ACTION, `run_id` comme clé de regroupement.

Quatre fois cette semaine, une mesure de routage a été refaite à la main : lancer
AXON, taper la requête, lire `/debug`, recopier les groupes. Ce module n'améliore
pas AXON, il améliore la capacité à le mesurer — c'est ce qui le place avant les
autres chantiers de supervision.

CE QU'IL VOIT, ET QU'UN TRACEUR GÉNÉRIQUE NE VOIT PAS. LangSmith et Langfuse
observent les appels LLM et les `tool_call`. Or les décisions d'AXON se prennent
ENTRE ces appels : quels groupes l'étage 1 a élus et à quel rang, quel outil a dû
être réclamé au catalogue faute d'avoir été lié, quel statut de refus un outil a
rendu, ce que `verifier()` a dit du fichier écrit. Ces colonnes-là n'existent que
si on les écrit soi-même — et ce sont elles qui portent le diagnostic.

Un exemple déjà vécu, que ce module aurait montré sans enquête : une tâche cron a
logué `status: "ok"` alors que TOUTES ses commandes avaient été bloquées. Le
statut de refus était rendu, personne ne le lisait.

FORME, reprise de `failure_log.py` qui a déjà tranché ces questions : JSONL en
append, aucune dépendance, aucune I/O à l'import, et surtout aucune exception qui
remonte. Un journal qui casse le tour qu'il observe est exactement le défaut
qu'on cherche à voir. Il en va de même du coût : ce qui est cher finit désactivé,
donc absent le jour où on en a besoin.

Une seule divergence avec `failure_log`, assumée : au plafond, lui efface et
repart à neuf ; ici on fait TOURNER vers `.1`. Un journal de diagnostic peut
oublier — un substrat de mesure qui efface son historique ne peut plus comparer
un avant à un après, ce qui est sa seule raison d'être.

PROMETHEUS ET GRAFANA — écartés aujourd'hui, avec le déclencheur qui les
rendrait justes, pour que l'arbitrage ne se refasse pas au doigt :

    Prometheus TIRE : il scrute un endpoint HTTP toutes les N secondes. Le
    processus où se prennent presque toutes ces décisions est le TUI — interactif,
    au premier plan, sans serveur, né et mort avec la session. Le couvrir
    demanderait un Pushgateway, que la doc de Prometheus déconseille hors job
    batch, et qui perd l'identité par run.

    Et ses labels doivent rester à BASSE cardinalité, quand toutes les questions
    ci-dessus sont à haute : quels outils pour CETTE requête, quelle commande
    bloquée dans CETTE tâche. Prometheus sait dire « 4 % de refus » ; il ne sait
    pas dire lequel, et le diagnostic est toujours dans le lequel.

    DÉCLENCHEUR : un processus long servant du trafic continu — `api_server.py`
    ouvert à plusieurs clients, ou le démon cron à haute fréquence. Là, cinq
    compteurs à basse cardinalité dans ces deux processus-là deviennent justes,
    et coûtent trois lignes parce qu'ils sont déjà longs. Le présent fichier reste
    la source : un exportateur lit ces lignes, il ne les remplace pas.
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

#: Le fichier courant, et la génération précédente. Construire un `Path` ne
#: touche pas le disque — l'import reste sans effet, cf. DETTE-001.
FICHIER = Path.home() / ".axon" / "decisions.jsonl"

#: Au-delà, rotation. Deux générations au plus : de quoi couvrir un avant/après
#: sans grandir sans fin sur la machine de quelqu'un.
_MAX_OCTETS = 5_000_000

# ── Genres d'action ──────────────────────────────────────────────────────────
#: Ce que l'étage 1 puis l'étage 2 ont retenu pour ce tour.
ROUTE = "route"
#: Un outil réclamé au catalogue parce que la sélection ne l'avait pas lié.
#: C'est LE taux qui dira jusqu'où le resserrement peut aller.
RATTRAPAGE = "rattrapage"
#: Un appel au modèle : tokens, latence, backend réellement utilisé.
APPEL_LLM = "appel_llm"
#: Une exécution d'outil, avec le verdict de policy que son statut révèle.
OUTIL = "outil"
#: Le contrôle déterministe d'après écriture.
VERIFICATION = "verification"
#: Une tâche planifiée, de bout en bout.
TACHE = "tache"

# ── Verdicts normalisés ──────────────────────────────────────────────────────
AUTORISE = "allow"
A_CONFIRMER = "confirm"
REFUSE = "deny"

OK = "ok"
ERREUR = "erreur"
BLOQUE = "bloque"
CACHE = "cache"

#: Ce qu'on écrit quand rien ne sait vérifier ce type d'action. Écrit
#: HONNÊTEMENT plutôt que laissé vide : la couverture de `verifier()` s'arrête
#: aujourd'hui à `.py` et `.json`, et c'est un trou qu'il faut voir, pas maquiller.
NON_VERIFIE = "none"


@dataclass(frozen=True)
class Action:
    """Une chose qu'AXON a décidée ou faite, et ce qu'elle est devenue.

    Un tour fait N appels d'outils dans une boucle : un enregistrement plat par
    TOUR perdrait l'information utile — lequel des N a fait quoi. D'où une ligne
    par action, regroupées par `run_id`.
    """
    genre: str
    #: La requête de l'utilisateur, telle qu'elle a servi au routage.
    intent: str = ""
    #: [(groupe, rang)] — le rang est ce qui décide des seuils, pas la position.
    groupes: tuple[tuple[str, int], ...] = ()
    outils_lies: tuple[str, ...] = ()
    outil: str = ""
    #: Ce sur quoi l'action a porté : un chemin, une commande, un canal.
    cible: str = ""
    policy: str = ""
    confirmation: str = ""
    resultat: str = ""
    verification: str = ""
    #: Court et stable — un code, pas un message. Ce qui se compte doit se grouper.
    erreur: str = ""
    tokens_entree: int = 0
    tokens_sortie: int = 0
    latence_ms: int = 0
    backend: str = ""
    modele: str = ""
    #: Ce que le reste du schéma ne prévoit pas. Rarement rempli, jamais lu par
    #: ce module.
    extra: dict = field(default_factory=dict)


# ── Le run courant ───────────────────────────────────────────────────────────
# Côté processus, jamais dans l'état du graphe : celui-ci est persisté et
# rejouable, et ressusciterait un run_id d'un tour déjà écrit.
_verrou = threading.Lock()
_run: str = ""
_source: str = ""
_seq: int = 0


def actif() -> bool:
    """`AXON_TRACE=0` éteint tout. Allumé par défaut, sans quoi la trace est
    toujours absente le jour où la question se pose."""
    return (os.environ.get("AXON_TRACE", "1") or "1").strip().lower() not in (
        "0", "false", "non", "no", "off")


#: D'où viennent les runs de ce processus, tant que personne ne dit le contraire.
_source_par_defaut = "tui"


def declarer_source(source: str) -> None:
    """Dit d'où parle ce processus : `tui`, `api`, `mcp`, `cron`.

    Appelé par le POINT D'ENTRÉE, une fois. Le graphe, lui, ne sait pas qui le
    pilote : `graph.chatbot` est le même code pour le terminal, le serveur API et
    le serveur MCP. Sans cette déclaration, tout serait étiqueté `tui`, et le
    filtre `axon trace --source` — dont l'intérêt est d'isoler ce que personne ne
    regarde — mentirait sur deux chemins sur quatre.
    """
    global _source_par_defaut
    _source_par_defaut = source or "tui"


def nouveau_run(source: str = "") -> str:
    """Ouvre un run et rend son identifiant. Un run = un tour d'utilisateur.

    `source` dit d'où : `tui`, `cron`, `api`, `mcp`. Sans elle, les lignes du
    démon et celles de la conversation se mélangent, et c'est justement le démon
    — celui que personne ne regarde — qu'on veut pouvoir isoler. Omise, elle vaut
    ce que le point d'entrée a déclaré.
    """
    global _run, _source, _seq
    with _verrou:
        _run = uuid4().hex[:12]
        _source = source or _source_par_defaut
        _seq = 0
        return _run


def run_courant() -> str:
    with _verrou:
        return _run


def inscrire(action: Action, *, fichier: Path | None = None) -> None:
    """Consigne une action. Ne lève JAMAIS, et n'ouvre aucun run tout seul.

    Une ligne sans run est écrite avec `run_id` vide plutôt que jetée : perdre
    une action parce que personne n'a appelé `nouveau_run()` serait un trou
    silencieux, et c'est la classe de défaut que ce module traque.
    """
    if not actif():
        return
    global _seq
    try:
        with _verrou:
            _seq += 1
            entree = {
                "run_id": _run,
                "seq": _seq,
                "at": datetime.now(timezone.utc).isoformat(),
                "source": _source,
                "axon_sha": _sha(),
                **asdict(action),
            }
        # Les tuples ne survivent pas au JSON : normalisés ici, une fois.
        entree["groupes"] = [list(g) for g in entree.get("groupes") or ()]
        entree["outils_lies"] = list(entree.get("outils_lies") or ())
        cible = fichier or FICHIER
        cible.parent.mkdir(parents=True, exist_ok=True)
        _faire_tourner(cible)
        with cible.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entree, ensure_ascii=False) + "\n")
    except Exception:                                            # noqa: BLE001
        # Silencieux, volontairement : signaler l'échec d'un journal sur le
        # terminal de l'utilisateur ferait du bruit à chaque tour pour un défaut
        # qui ne le concerne pas.
        pass


def _faire_tourner(fichier: Path) -> None:
    """Au plafond, la génération courante devient `.1`. L'ancienne `.1` part."""
    try:
        if not fichier.exists() or fichier.stat().st_size <= _MAX_OCTETS:
            return
        precedent = fichier.with_suffix(fichier.suffix + ".1")
        precedent.unlink(missing_ok=True)
        fichier.rename(precedent)
    except Exception:                                            # noqa: BLE001
        pass


# ── Relecture ────────────────────────────────────────────────────────────────
def lire(*, fichier: Path | None = None, limite: int | None = None) -> list[dict]:
    """Les lignes, de la plus ancienne à la plus récente, générations comprises.

    `limite` compte les lignes rendues, pas les lignes lues : c'est la fin du
    journal qui intéresse, jamais son début.
    """
    cible = fichier or FICHIER
    lignes: list[dict] = []
    for chemin in (cible.with_suffix(cible.suffix + ".1"), cible):
        try:
            if not chemin.is_file():
                continue
            with chemin.open(encoding="utf-8") as fh:
                for brute in fh:
                    brute = brute.strip()
                    if not brute:
                        continue
                    try:
                        charge = json.loads(brute)
                    except ValueError:
                        # Une ligne tronquée — un processus tué en plein write —
                        # ne doit pas emporter la lecture des autres.
                        continue
                    if isinstance(charge, dict):
                        lignes.append(charge)
        except Exception:                                        # noqa: BLE001
            continue
    return lignes[-limite:] if limite else lignes


def par_run(lignes: list[dict]) -> list[list[dict]]:
    """Les lignes regroupées par run, dans l'ordre où les runs ont commencé.

    Les runs sans identifiant sont gardés à part plutôt que fondus ensemble : les
    confondre inventerait un tour qui n'a pas eu lieu.
    """
    ordre: list[str] = []
    groupes: dict[str, list[dict]] = {}
    orphelines: list[dict] = []
    for ligne in lignes:
        run = str(ligne.get("run_id") or "")
        if not run:
            orphelines.append(ligne)
            continue
        if run not in groupes:
            groupes[run] = []
            ordre.append(run)
        groupes[run].append(ligne)
    sortie = [sorted(groupes[r], key=lambda l: l.get("seq", 0)) for r in ordre]
    return sortie + ([orphelines] if orphelines else [])


def _sha() -> str:
    """Le commit sur lequel tourne AXON, ou "" — lu, jamais deviné.

    Sans lui, comparer deux mesures suppose de se souvenir de l'arbre qui les a
    produites. Lu dans `.git` directement : un `git rev-parse` par processus
    coûterait un sous-processus pour douze caractères.
    """
    global _sha_cache
    if _sha_cache is not None:
        return _sha_cache
    _sha_cache = ""
    try:
        git = Path(__file__).resolve().parents[2] / ".git"
        tete = (git / "HEAD").read_text(encoding="utf-8").strip()
        if tete.startswith("ref:"):
            ref = git / tete.split(" ", 1)[1].strip()
            tete = (ref.read_text(encoding="utf-8").strip() if ref.is_file()
                    else _sha_empaquete(git, tete.split(" ", 1)[1].strip()))
        _sha_cache = tete[:12]
    except Exception:                                            # noqa: BLE001
        pass
    return _sha_cache


def _sha_empaquete(git: Path, ref: str) -> str:
    """La ref dans `packed-refs` — une branche fraîchement clonée n'a pas de
    fichier propre sous `.git/refs`."""
    try:
        for ligne in (git / "packed-refs").read_text(encoding="utf-8").splitlines():
            if ligne.endswith(" " + ref):
                return ligne.split(" ", 1)[0]
    except Exception:                                            # noqa: BLE001
        pass
    return ""


_sha_cache: str | None = None
