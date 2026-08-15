"""`betting_recommend` — l'UNIQUE outil de recommandation de paris.

Il n'existait pas. C'est toute l'origine du problème : la chaîne qui sait
scanner, classer et dimensionner (`axon recommend`) était liée à `sys.argv`, et
le graphe conversationnel n'avait aucun moyen de l'atteindre. Face à « scanne
tout aujourd'hui et demain », le modèle ne disposait que d'un catalogue de cotes
brutes accompagné de leur probabilité implicite — c'est-à-dire exactement de quoi
terminer le travail lui-même.

Le tool rend un JSON qui contient DEUX choses :

- `rendered` : le texte déterministe, seul autorisé à énoncer un fait sportif ;
- `betting_evidence` : la provenance du tour, que le garde exige pour laisser
  passer toute affirmation de pari.

Le modèle peut commenter `rendered`. Il ne peut pas le remplacer.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from . import session
from .constraints import PromotionalBalance, constraints_from_request
from .evidence import EVIDENCE_KEY
from .observability import collect_readiness
from .recommend import COMPLETED, bankroll_decimal, run_recommendation
from .renderer import render
from .review_preference import cible_depuis_texte, objectif_de_cote
from .window import resolve_window


def _enrichir(response, sports):
    """Faits externes pour la revue. Une panne d'enrichissement est sans
    conséquence : la réponse structurée existe déjà quand on arrive ici."""
    try:
        from ..enrichment.enrich import enrich_review_candidates
        return enrich_review_candidates(response, sports)
    except Exception:   # noqa: BLE001
        return {}


@tool("betting_recommend")
def betting_recommend(
    when: str = "",
    bankroll: float | None = None,
    sports: list[str] | None = None,
    competitions: list[str] | None = None,
    markets: list[str] | None = None,
    allow_combos: bool = False,
    freebets: float | None = None,
    probability_preference: str = "",
    odds_preference: str = "",
    debug: bool = False,
    config: RunnableConfig = None,
) -> str:
    """Scanne, évalue et recommande — la SEULE façon de produire un pari.

    Lance la chaîne complète : scan Winamax multisport, résolution d'identité,
    Betting Engine, Advisor (éligibilité, classement, combos, dimensionnement),
    audit. Rend un texte déterministe déjà rédigé (`rendered`) : le restituer tel
    quel, sans en modifier un chiffre, un horaire, une cote ni une décision.

    N'invente JAMAIS un match, une cote, un horaire ou une probabilité, et ne
    calcule jamais une EV à partir d'une cote. Si cet outil n'a pas tourné, il
    n'y a rien à proposer — le dire est la seule réponse correcte.

    Les contraintes sont MÉMORISÉES sur le fil : ne redemande pas un sport ou une
    compétition déjà donnés. Un argument omis conserve sa valeur précédente ; un
    argument fourni la remplace.

    Args:
        when: période demandée, telle que dite ("aujourd'hui", "demain matin",
            "ce soir"). Vide = de maintenant à la fin de demain.
        bankroll: bankroll en euros (cash uniquement, hors bonus). Obligatoire au
            premier appel du fil.
        sports: sports voulus (["tennis"]). Liste vide ou ["all"] = tous.
        competitions: compétitions voulues (["atp"]). Liste vide ou ["all"] = toutes.
        markets: types de marché voulus. Liste vide ou ["all"] = tous.
        allow_combos: autoriser les combinés (construits par le Combo Builder seul).
        freebets: montant de freebets déclaré. Restitué mais JAMAIS optimisé :
            un freebet n'est pas du cash et ses conditions ne sont pas modélisées.
        probability_preference: la préférence de probabilité TELLE QUE DITE
            ("environ 90 % de chances", "au moins 85 % de probabilité"). Elle
            ORDONNE l'affichage de la revue et ne filtre rien : les candidats sous
            le seuil restent montrés. Ne JAMAIS demander à l'utilisateur de
            l'abaisser pour avoir le droit de voir des candidats — le rendu
            s'occupe déjà de dire qu'aucun ne l'atteint et d'afficher les
            meilleurs en dessous.
        odds_preference: l'objectif de COTE ou de multiplicateur, tel que dit
            ("faire x2", "autour de 2 de cote", "entre 1.8 et 2.2", "doubler ma
            mise"). Toujours SUBORDONNÉ à la préférence de probabilité : ne
            propose jamais une cote plus élevée en descendant sous le seuil de
            probabilité demandé. Ne confonds pas un montant avec une cote —
            "doubler 10 €" vise x2, pas x10.
        debug: rendu complet — catalogue intégral, chemin de décision de chaque
            événement, readiness des modèles, provenance. À activer quand
            l'utilisateur demande pourquoi, pas par défaut.
    Returns:
        JSON {status, rendered, betting_evidence, constraints}
    """
    fil = session.thread_id(config)
    maintenant = datetime.now(timezone.utc)

    soldes = ([PromotionalBalance(bankroll_decimal(freebets))]
              if freebets is not None and freebets > 0 else None)

    contraintes = constraints_from_request(
        session.load(fil),
        sports=sports,
        competitions=competitions,
        markets=markets,
        # Une période n'est résolue QUE si elle est dite : sans cela, chaque tour
        # ré-appliquerait le défaut et écraserait un « demain matin » explicite.
        time_window=resolve_window(when, maintenant) if when else None,
        bankroll=bankroll_decimal(bankroll) if bankroll else None,
        promotional_balances=soldes,
        allow_combos=allow_combos or None,
        probability_target=cible_depuis_texte(probability_preference),
        target_odds=objectif_de_cote(odds_preference),
    )
    if contraintes.time_window is None:
        contraintes = constraints_from_request(
            contraintes, time_window=resolve_window("", maintenant))

    session.store(fil, contraintes)

    try:
        # La readiness rejoue une validation walk-forward par modèle. Elle est
        # MÉMORISÉE pour la durée du processus — un modèle et son dataset embarqué
        # ne bougent pas entre deux tours — donc son coût ne se paie qu'une fois.
        # Elle entre désormais dans la réponse normale : « pourquoi ce n'est pas
        # misable » sans dire ce qui manque au modèle n'explique rien.
        run = run_recommendation(
            contraintes, now=maintenant,
            readiness=collect_readiness,
            # Enrichissement APRÈS l'évaluation, borné aux premiers candidats de
            # revue. Son échec réseau ne coûte jamais la réponse structurée.
            enrich=_enrichir)
    except Exception as exc:   # noqa: BLE001 — une panne ne doit rien faire inventer
        return json.dumps({
            "status": "TECHNICAL_FAILURE",
            "rendered": ("**TECHNICAL_FAILURE** — la chaîne structurée n'a pas pu "
                         f"produire de réponse : {type(exc).__name__}: {exc}\n\n"
                         "Aucune sélection, cote ou mise ne peut être affichée."),
            EVIDENCE_KEY: None,
            "constraints": contraintes.describe(),
        }, ensure_ascii=False)

    return json.dumps({
        "status": run.status,
        "rendered": render(run, debug=debug),
        # La preuve n'accompagne QUE l'exécution complète : un échec ne doit pas
        # débloquer le garde.
        EVIDENCE_KEY: (run.evidence.to_dict()
                       if run.status == COMPLETED and run.evidence else None),
        "constraints": run.constraints.describe(),
    }, ensure_ascii=False)
