"""CLI `axon clv-status` — où en est la collecte, sport par sport.

La CLV est le dernier bloqueur commun aux quatorze modèles, et le seul que rien
d'autre que le temps ne lève. Son avancement n'était lisible nulle part : le
rapport de maturité dit « NOT_YET_MEASURABLE » pour un modèle, sans distinguer
« aucune décision capturée » de « des décisions mais aucune clôture ». Les deux
se corrigent différemment — l'une en lançant la collecte, l'autre en la lançant
au bon moment.

Cette vue lit l'historique et rien d'autre. Elle ne calcule aucune CLV qui ne
serait pas déjà calculée par `clv_readiness` : elle regroupe par sport et montre
ce qui manque pour la prochaine paire.
"""

from __future__ import annotations

import argparse
import pathlib
from collections import defaultdict

from ..maturity import load_maturity_policy
from .clv import clv_readiness
from .observation import ObservationPhase
from .store import JsonlOddsHistoryStore

#: Ce qui manque, dit dans l'ordre où il faut le corriger. Un sport sans décision
#: n'a pas besoin qu'on lui parle de clôtures.
_AUCUNE_DECISION = "aucune décision capturée"
_AUCUNE_CLOTURE = "décisions capturées, aucune clôture"
_PAS_APPARIE = "décisions et clôtures présentes, mais aucune ne s'apparie"


def _sport_de(event_id: str) -> str:
    """« event:tennis:tour:… » -> « tennis ». L'identité d'événement porte déjà
    son sport ; le redemander ailleurs ouvrirait un second chemin de vérité."""
    parties = (event_id or "").split(":")
    return parties[1] if len(parties) >= 2 and parties[0] == "event" else "?"


def collect(observations, *, min_events: int) -> list[dict]:
    """Une ligne par sport présent dans l'historique, plus le total."""
    par_sport: dict[str, list] = defaultdict(list)
    for obs in observations:
        par_sport[_sport_de(obs.event_id)].append(obs)

    lignes = []
    for sport in sorted(par_sport) + (["TOTAL"] if len(par_sport) > 1 else []):
        lot = list(observations) if sport == "TOTAL" else par_sport[sport]
        decisions = [o for o in lot if o.phase is ObservationPhase.DECISION]
        clotures = [o for o in lot if o.phase is ObservationPhase.CLOSING]
        lecture = clv_readiness(lot)
        if not decisions:
            manque = _AUCUNE_DECISION
        elif not clotures:
            manque = _AUCUNE_CLOTURE
        elif lecture.n_complete_pairs == 0:
            manque = _PAS_APPARIE
        else:
            reste = max(0, min_events - lecture.n_events)
            manque = "—" if reste == 0 else f"{reste} rencontre(s) de plus"
        lignes.append({
            "sport": sport,
            "decisions": len(decisions),
            "clotures": len(clotures),
            "evenements": len({o.event_id for o in lot}),
            "paires": lecture.n_complete_pairs,
            "independants": lecture.n_events,
            "statut": lecture.status,
            "manque": manque,
        })
    return lignes


def render(lignes: list[dict], *, min_events: int) -> list[str]:
    if not lignes:
        return ["Historique de cotes vide — aucune observation collectée.",
                "",
                "Lancer une collecte :",
                "  python -m src.agents.quant.betting_engine.clv.cli --live tennis --phase decision",
                "  python -m src.agents.quant.betting_engine.clv.cli --live tennis --phase closing"]

    entete = (f"{'sport':16} {'décisions':>9} {'clôtures':>9} {'rencontres':>11} "
              f"{'paires':>7} {'indép.':>7} {'statut':>19}  il manque")
    sortie = [entete, "-" * len(entete)]
    for ligne in lignes:
        sortie.append(
            f"{ligne['sport']:16} {ligne['decisions']:>9} {ligne['clotures']:>9} "
            f"{ligne['evenements']:>11} {ligne['paires']:>7} {ligne['independants']:>7} "
            f"{ligne['statut']:>19}  {ligne['manque']}")
    sortie += [
        "",
        f"Seuil de maturité : {min_events} rencontres indépendantes ET une borne "
        "de confiance inférieure strictement positive.",
        "« indép. » est l'échantillon EFFECTIF : plusieurs sélections d'un même "
        "match bougent ensemble et ne comptent que pour une.",
    ]
    if all(ligne["clotures"] == 0 for ligne in lignes):
        sortie += [
            "",
            "Aucune clôture n'a jamais été capturée. Une clôture se prend AVANT le "
            "coup d'envoi : après, le bookmaker cote le direct, et cette cote-là "
            "est refusée à l'enregistrement.",
        ]
    return sortie


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="axon clv-status",
        description="Avancement de la collecte CLV, sport par sport.")
    p.add_argument("--store", default=None,
                   help="chemin odds_history.jsonl (défaut : var/ du dépôt)")
    args = p.parse_args(argv)

    store = JsonlOddsHistoryStore(None if args.store is None else pathlib.Path(args.store))
    min_events = load_maturity_policy().criteria["min_clv_events"]
    for ligne in render(collect(store.all(), min_events=min_events), min_events=min_events):
        print(ligne)
    return 0


if __name__ == "__main__":   # pragma: no cover
    raise SystemExit(main())
