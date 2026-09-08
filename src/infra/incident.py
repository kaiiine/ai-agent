# src/infra/incident.py
"""Le journal des incidents — une erreur constatée, avec ce qui aurait dû être fait.

CE N'EST PAS UNE COLONNE DE PLUS DANS `decisions.jsonl`. La trace enregistre des
ACTIONS, au moment où elles ont lieu ; un incident est une LECTURE de plusieurs
actions, produite après coup. Les mélanger obligerait à écrire pendant le tour
une conclusion qu'on ne tire qu'ensuite, et la trace cesserait d'être un compte
rendu pour devenir un jugement.

D'où une passe séparée, rejouable : `capturer()` relit la trace, en déduit les
incidents nouveaux, et ne redouble jamais ceux déjà écrits (clé `origine`).
Elle peut donc tourner autant de fois qu'on veut, y compris sur un journal déjà
en partie converti.

PORTÉE. Le fichier est global — `~/.axon/`, comme la trace, et non
`{git_root}/.axon/` comme la mémoire de session — parce que c'est la condition
littérale pour qu'une leçon serve d'une conversation à l'autre. Mais un fichier
global sans provenance mélange des leçons qui ne se transposent pas : le
catalogue d'outils d'un dépôt n'est pas celui d'un autre, et une règle de routage
apprise ici peut ne rien vouloir dire là-bas, voire nuire. D'où `projet`, écrit
dès la première ligne. Il ne se rattraperait pas plus tard : `decisions.jsonl` ne
portait pas cette colonne avant cette branche, donc l'information n'existerait
nulle part à reconstruire.

CE QUE LA CAPTURE NE FAIT PAS. Elle ne promeut rien, ne durcit rien, ne juge pas.
Un incident capturé est un candidat, pas une leçon — en particulier le signal
`rattrapage`, qui atteste que la sélection n'a pas proposé l'outil réclamé et non
que l'outil réclamé était le bon. La décision de durcir appartient à la
consolidation, qui doit relire un échantillon avant de croire un compte.

FORME, reprise de `trace.py` qui l'a reprise de `failure_log.py` : JSONL en
append, aucune I/O à l'import, plafonné, et aucune exception qui remonte.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from src.infra import trace

from src.infra import chemins as _chemins

#: Construire un `Path` ne touche pas le disque — l'import reste sans effet.
FICHIER = _chemins.incidents()

#: Plus petit que le plafond de la trace : un incident est un condensé de
#: plusieurs lignes, il en faut beaucoup moins pour dire la même chose.
_MAX_OCTETS = 2_000_000

# ── Catégories d'attribution ─────────────────────────────────────────────────
#: Mauvais outil sélectionné. La seule que la trace attribue mécaniquement.
ROUTING = "routing"
#: Bon outil, mauvaise décomposition. Personne ne l'attribue aujourd'hui —
#: la case reste vide plutôt que d'être confiée à un classifieur, qui
#: réintroduirait le juge écarté à la détection, un cran plus loin.
PLAN = "plan"
#: Bon plan, bug d'appel ou de paramètre.
EXECUTION = "execution"
#: Le monde a changé depuis le contexte chargé. Aucune règle statique ne le
#: corrige : seule la vérification suivante le rattrape.
ETAT_PERIME = "etat_perime"

# ── D'où vient le constat ────────────────────────────────────────────────────
RATTRAPAGE = "rattrapage"
REFUS = "refus"
VERIFY = "verify"
ECHEC_DUR = "echec_dur"

#: `hitl.REFUS`. Recopié, comme dans `erreurs.py` : `src.infra` ne dépend pas de
#: `src.orchestrator`.
_REFUS = "refus"


@dataclass(frozen=True)
class Incident:
    """Une erreur constatée, et ce qu'elle aurait dû être.

    `origine` n'est pas dans le schéma du PRD ; il y est ajouté pour une raison
    opératoire : sans clé de la ligne source, une seconde passe de capture
    réécrirait tout, et le compte des récidives — la métrique n°1 — compterait
    des passes au lieu d'erreurs.
    """
    run_id: str
    horodatage: str
    #: Le dépôt d'où vient l'incident, ou `trace.HORS_REPO`.
    projet: str
    intention_reformulee: str
    #: Niveau 1 du contrat de réussite. Vide tant que les postconditions par
    #: outil n'existent pas — écrit vide plutôt qu'omis, pour que le trou se
    #: compte au lieu de se deviner.
    contrat_etat: str
    action_tentee: str
    categorie: str
    resultat_reel: str
    #: Ce qui aurait dû être fait. Rempli quand l'utilisateur l'a dit lui-même.
    correction: str
    signal_source: str
    #: `<run_id>:<seq>` de la ligne de trace dont il est déduit.
    origine: str


def _origine(ligne: dict) -> str:
    run = str(ligne.get("run_id") or "")
    if run:
        return f"{run}:{ligne.get('seq', 0)}"
    # Une ligne sans run — écrite avant tout `nouveau_run()` — n'a pas de clé
    # stable. Son horodatage en tient lieu : deux passes ne la dédoubleront pas.
    return f"-:{ligne.get('at', '')}"


def _intents_par_run(lignes: list[dict]) -> dict[str, str]:
    """La requête de l'utilisateur, par run.

    Un refus est écrit sur la ligne du fichier refusé, qui ne porte pas la
    demande d'origine — sans ce report, l'incident dirait CE qui a été refusé
    sans dire à quoi ça répondait, et la relecture six mois plus tard serait
    aveugle.
    """
    intents: dict[str, str] = {}
    for ligne in lignes:
        run = str(ligne.get("run_id") or "")
        intent = str(ligne.get("intent") or "").strip()
        if run and intent and run not in intents:
            intents[run] = intent
    return intents


def _groupes_par_run(lignes: list[dict]) -> dict[str, str]:
    """Ce que l'étage 1 a retenu, par run.

    C'est CE QUI A ÉTÉ TENTÉ pour un incident de routage. Écrire à la place
    « sélection sans <outil> » ne dirait que la correction une seconde fois, et
    la relecture n'apprendrait rien : ce qu'on veut voir, c'est quel groupe a
    gagné à la place, parce que c'est lui qu'une porte devra déloger.
    """
    retenus: dict[str, str] = {}
    for ligne in lignes:
        run = str(ligne.get("run_id") or "")
        if not run or ligne.get("genre") != trace.ROUTE or run in retenus:
            continue
        noms = [str(g[0]) for g in (ligne.get("groupes") or []) if g]
        retenus[run] = ", ".join(noms[:6])
    return retenus


def depuis_la_trace(lignes: list[dict]) -> list[Incident]:
    """Déduit les incidents des deux signaux structurés de la trace.

    Aucun jugement : chaque incident rendu correspond à une ligne qui portait
    déjà, à l'écriture, la mention de l'échec. Ce qui n'est pas dans la trace
    n'est pas inventé ici — une correction dite en conversation libre reste
    invisible, et c'est une limite assumée du périmètre.
    """
    intents = _intents_par_run(lignes)
    groupes = _groupes_par_run(lignes)
    incidents: list[Incident] = []
    for ligne in lignes:
        run = str(ligne.get("run_id") or "")
        commun = {
            "run_id": run,
            "horodatage": str(ligne.get("at") or ""),
            "projet": str(ligne.get("projet") or trace.HORS_REPO),
            "contrat_etat": "",
            "origine": _origine(ligne),
        }
        if ligne.get("genre") == trace.RATTRAPAGE:
            outil = str(ligne.get("outil") or "")
            incidents.append(Incident(
                **commun,
                intention_reformulee=str(ligne.get("intent") or intents.get(run, "")),
                # Ce que le routeur a élu à la place, et non la négation de la
                # correction : c'est ce groupe-là qu'une porte devra déloger.
                action_tentee=(f"groupes retenus : {groupes[run]}"
                               if groupes.get(run) else "routage non tracé"),
                categorie=ROUTING,
                resultat_reel="outil non lié — réclamé au catalogue",
                # L'outil réclamé est la correction CANDIDATE, pas la correction
                # établie : le modèle a pu se tromper de nom. C'est la raison pour
                # laquelle la consolidation doit relire un échantillon avant de
                # durcir quoi que ce soit là-dessus.
                correction=f"lier {outil}" if outil else "",
                signal_source=RATTRAPAGE))
            continue
        if ligne.get("confirmation") == _REFUS and ligne.get("resultat") == trace.BLOQUE:
            precision = str((ligne.get("extra") or {}).get("precision") or "")
            incidents.append(Incident(
                **commun,
                intention_reformulee=intents.get(run, ""),
                action_tentee=str(ligne.get("cible") or ""),
                categorie=EXECUTION,
                resultat_reel=("refusé avec consigne"
                               if ligne.get("erreur") == "preciser" else "refusé"),
                correction=precision,
                signal_source=REFUS))
    return incidents


# ── Écriture ─────────────────────────────────────────────────────────────────
def inscrire(incident: Incident, *, fichier: Path | None = None) -> None:
    """Ajoute un incident. Ne lève JAMAIS — même règle que la trace.

    Un journal qui casse le tour qu'il observe est le défaut que tout ce chantier
    existe pour montrer. Ici la capture tourne hors tour, mais la règle ne se
    relâche pas pour autant : elle finirait par être appelée depuis un tour.
    """
    if not trace.actif():
        return
    try:
        cible = fichier or FICHIER
        cible.parent.mkdir(parents=True, exist_ok=True)
        _faire_tourner(cible)
        with cible.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(asdict(incident), ensure_ascii=False) + "\n")
    except Exception:                                            # noqa: BLE001
        pass


def _faire_tourner(fichier: Path) -> None:
    """Au plafond, la génération courante devient `.1`. Comme la trace : un
    substrat de mesure qui efface son historique ne peut plus comparer."""
    try:
        if not fichier.exists() or fichier.stat().st_size <= _MAX_OCTETS:
            return
        precedent = fichier.with_suffix(fichier.suffix + ".1")
        precedent.unlink(missing_ok=True)
        fichier.rename(precedent)
    except Exception:                                            # noqa: BLE001
        pass


def lire(*, fichier: Path | None = None) -> list[dict]:
    """Les incidents déjà capturés, générations comprises.

    Même format que la trace, donc même lecteur : `trace.lire` sait déjà ignorer
    une ligne tronquée par un processus tué en plein write, et le redire ici
    créerait deux relectures à maintenir pour un seul format.
    """
    return trace.lire(fichier=fichier or FICHIER)


def capturer(lignes: list[dict] | None = None, *,
             fichier: Path | None = None) -> list[Incident]:
    """Relit la trace, écrit les incidents nouveaux, rend ceux qu'elle a ajoutés.

    Idempotente : une origine déjà présente n'est pas réécrite. C'est ce qui
    permet de la lancer sans se demander quand elle a tourné la dernière fois —
    une passe qui exige qu'on tienne le compte de ses exécutions finit par ne
    plus être lancée du tout.
    """
    lignes = trace.lire() if lignes is None else lignes
    connues = {str(i.get("origine") or "") for i in lire(fichier=fichier)}
    nouveaux = [i for i in depuis_la_trace(lignes) if i.origine not in connues]
    for incident in nouveaux:
        inscrire(incident, fichier=fichier)
    return nouveaux
