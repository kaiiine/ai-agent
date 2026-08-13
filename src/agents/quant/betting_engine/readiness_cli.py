"""CLI `axon readiness` (§16) : état de maturité MÉCANIQUE du modèle réel — taille
d'échantillon, CLV, freshness, calibration, data quality, verdict, et bloqueurs EXACTS
vers SUPPORTED. Aucune promotion, aucune donnée fabriquée : dérive de
`assess_default_one_x_two` (walk-forward réel FL1). Le modèle réel reste EXPERIMENTAL
tant que les critères ne passent pas — cette commande le rend transparent.
"""

from __future__ import annotations

import argparse

from .assessment import (
    assess_champions_league,
    assess_conference_league,
    assess_europa_league,
    assess_bundesliga,
    assess_championship,
    assess_default_one_x_two,
    assess_eredivisie,
    assess_laliga,
    assess_primeira_liga,
    assess_serie_a,
)
from .maturity import Verdict, load_maturity_policy

# Compétitions ayant un dataset réel embarqué -> readiness mesurable par walk-forward.
# Football (Dixon-Coles 1X2) + basket NBA (Elo moneyline, famille statistique PROPRE).
def _assess_nba(odds=()):
    from .sports.basketball.moneyline import assess_nba
    return assess_nba(odds_observations=odds)


def _assess_mlb(odds=()):
    from .sports.baseball.moneyline import assess_mlb
    return assess_mlb(odds_observations=odds)


def _assess_nfl(odds=()):
    from .sports.american_football.moneyline import assess_nfl
    return assess_nfl(odds_observations=odds)


def _assess_volley(odds=()):
    from .sports.volleyball.moneyline import assess_volleyball
    return assess_volleyball(odds_observations=odds)


def _assess_nhl(odds=()):
    from .sports.hockey.regulation import assess_nhl
    return assess_nhl(odds_observations=odds)


def _assess_atp(odds=()):
    from .sports.tennis.elo_model import assess_tennis
    return assess_tennis("atp", odds_observations=odds)


def _assess_wta(odds=()):
    from .sports.tennis.elo_model import assess_tennis
    return assess_tennis("wta", odds_observations=odds)


def observations_collectees(cle: str) -> list:
    """Les paires de cotes RÉELLEMENT collectées pour ce modèle.

    Les enveloppes acceptaient déjà un argument `odds_observations` et le
    jetaient : l'historique pouvait se remplir indéfiniment sans que
    `positive_clv` bouge d'un pouce. Le lire ici referme la boucle entre la
    collecte et la mesure.

    Une lecture ratée ne fait pas tomber le rapport : sans historique, la CLV
    reste simplement non mesurable — ce qu'elle est.
    """
    try:
        from .clv.eligibility import eligible
        from .clv.identity import historique_horaires
        from .clv.routing import observations_pour
        from .clv.store import JsonlOddsHistoryStore
        # Filtre d'ADMISSIBILITÉ, pas de correction : l'historique reste entier,
        # seules les observations conformes au protocole de collecte courant
        # participent à la preuve. Sans lui, 45 décisions NHL prises 55 jours
        # avant leur coup d'envoi formeraient des paires mesurant deux mois de
        # dérive de marché.
        historique = JsonlOddsHistoryStore().all()
        # Le calendrier des horaires est construit sur l'historique COMPLET, avant
        # le routage : juger une clôture demande le dernier coup d'envoi annoncé
        # pour sa rencontre, et un sous-ensemble routé pourrait ne pas le porter.
        return eligible(observations_pour(cle, historique),
                        historique_horaires(historique))
    except Exception:   # noqa: BLE001
        return []


_ASSESSORS = {"fl1": assess_default_one_x_two, "serie-a": assess_serie_a,
              "laliga": assess_laliga, "bundesliga": assess_bundesliga,
              "championship": assess_championship, "eredivisie": assess_eredivisie,
              "primeira-liga": assess_primeira_liga, "nba": _assess_nba, "mlb": _assess_mlb,
              "nfl": _assess_nfl, "volley": _assess_volley, "nhl": _assess_nhl,
              "atp": _assess_atp, "wta": _assess_wta,
              # Coupes d'Europe : corpus backfillés par `historical_discovery`.
              # Sans entrée ici, un modèle benchmarké reste invisible du produit —
              # excellent sur le papier, absent de toute décision.
              "champions-league": assess_champions_league,
              "europa-league": assess_europa_league,
              "conference-league": assess_conference_league}


#: Compétition canonique de chaque modèle — pour lire sa couverture provider et
#: nommer, quand c'est le cas, le besoin EXTERNE exact.
_COMPETITIONS = {
    "fl1": "competition:football:fra:ligue1",
    "serie-a": "competition:football:ita:serie_a",
    "laliga": "competition:football:esp:laliga",
    "bundesliga": "competition:football:deu:bundesliga",
    "championship": "competition:football:eng:championship",
    "eredivisie": "competition:football:nld:eredivisie",
    "primeira-liga": "competition:football:prt:primeira_liga",
    "nba": "competition:basketball:usa:nba",
    "mlb": "competition:baseball:usa:mlb",
    "nfl": "competition:american_football:usa:nfl",
    "nhl": "competition:hockey:usa:nhl",
    "volley": "competition:volleyball:ita:serie_a1",
    "atp": "competition:tennis:atp:tour",
    "wta": "competition:tennis:wta:tour",
    "champions-league": "competition:football:eur:champions_league",
    "europa-league": "competition:football:eur:europa_league",
    "conference-league": "competition:football:eur:conference_league",
}

#: Besoins EXTERNES connus, avec leur objet exact. Ne rien souscrire, mais dire
#: précisément ce qui manque : « bloqué » sans dire par quoi n'aide personne à
#: décider s'il faut payer.
_BESOINS_EXTERNES = {
    "min_data_coverage": {
        "tennis": "abonnement couvrant Challenger, ITF et qualifications — "
                  "le corpus actuel s'arrête aux tableaux finaux",
    },
}


def besoin_externe(cle: str, blocker: str) -> str | None:
    """Ce qu'il faudrait acheter pour lever ce bloqueur, ou None.

    La réponse vient de deux faits enregistrés, jamais d'une estimation : la note
    de couverture du provider (issue d'une sonde réelle) et, pour le tennis, le
    manque de plateau documenté.
    """
    competition = _COMPETITIONS.get(cle)
    if competition is None:
        return None
    sport = competition.split(":")[1]

    par_sport = _BESOINS_EXTERNES.get(blocker, {})
    if sport in par_sport:
        return par_sport[sport]

    if blocker != "measurable_live_freshness":
        return None
    from .live_coverage import _sport_of  # noqa: F401  (même lecture du sport)
    from src.agents.quant.gateway.gateway import current_season
    from src.agents.quant.gateway.registries.provider_coverage_registry import (
        CoverageStatus, all_coverage,
    )
    saison = current_season()
    absentes = [e for e in all_coverage(competition, saison)
                if e.status is CoverageStatus.ABSENT and e.notes]
    if absentes:
        return f"{absentes[0].provider} saison {saison} : {absentes[0].notes}"
    return f"aucun provider ne couvre {competition} pour la saison {saison}"


def render(assessment, recency=None, cle: str | None = None) -> list[str]:
    d = assessment.decision
    o = assessment.observations
    prets = sum(1 for c in d.criteria if c.required and c.verdict is Verdict.PASS)
    requis = sum(1 for c in d.criteria if c.required)
    lines = [
        f"Readiness {d.model_name} {d.model_version} -> {d.status}",
        f"  progression : {prets}/{requis} critères requis prêts",
        f"  policy maturité v{d.policy_version} (checksum {d.policy_checksum[:12]}…)",
        f"  échantillon hors échantillon : {o.n_evaluated}   | folds temporels : {o.n_temporal_folds}",
        f"  calibration (ECE) : {o.calibration_error}   | Brier {o.model_brier} vs baseline {o.best_baseline_brier}",
        f"  coverage : {o.data_coverage}   | data_quality : {o.mean_data_quality}",
        # Deux grandeurs distinctes, affichées séparément : la fraîcheur de la
        # donnée LIVE au point de décision, et la récence du CORPUS historique.
        # Un corpus arrêté il y a trois ans avec des cotes fraîches, ou l'inverse,
        # sont deux situations différentes qui appelaient le même diagnostic tant
        # qu'un seul chiffre les représentait.
        f"  CLV : {o.clv_status}   | freshness live : {o.live_freshness_status}",
        # §17 : progression empirique CLV visible sans ouvrir les fichiers.
        f"  CLV échantillon : {o.clv_n_events} événement(s) indép. | moyenne : {o.clv_mean}"
        f" | borne basse : {o.clv_lower_bound}",
        "  critères :",
    ]
    if recency is not None:
        lines.insert(-1, f"  dataset : {recency.describe()}")
    for c in d.criteria:
        flag = "REQUIS" if c.required else "monitoring"
        detail = c.detail
        # §11 : la CLV est le seul bloqueur qui n'avance qu'avec le temps. Dire
        # « NOT_MEASURABLE » n'indique pas s'il manque une rencontre ou trente.
        if c.name == "positive_clv" and c.verdict is not Verdict.PASS:
            requis_clv = load_maturity_policy().criteria.get("min_clv_events")
            detail = (f"EN ATTENTE — {o.clv_n_events or 0}/{requis_clv} rencontres "
                      f"indépendantes collectées ({detail})")
        lines.append(f"    {c.name:28} {c.verdict.value:15} [{flag}]  {detail}")
    blockers = [c.name for c in d.criteria if c.required and c.verdict is not Verdict.PASS]
    lines.append(f"  bloqueurs vers SUPPORTED : {', '.join(blockers) if blockers else 'aucun'}")

    # §12 : nommer le besoin externe, sans jamais rien souscrire.
    for blocker in blockers:
        besoin = besoin_externe(cle, blocker) if cle else None
        if besoin:
            lines.append(f"    EXTERNAL_PROVIDER_REQUIRED [{blocker}] : {besoin}")

    return lines


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="axon readiness",
                                description="Maturité mécanique du modèle (§16).")
    p.add_argument("--competition", choices=tuple(_ASSESSORS), default="fl1",
                   help="compétition à évaluer (dataset réel embarqué)")
    args = p.parse_args(argv)
    from .dataset_recency import for_model

    evaluation = _ASSESSORS[args.competition](observations_collectees(args.competition))
    for line in render(evaluation, for_model(args.competition),
                       cle=args.competition):
        print(line)
    return 0


if __name__ == "__main__":   # pragma: no cover
    raise SystemExit(main())
