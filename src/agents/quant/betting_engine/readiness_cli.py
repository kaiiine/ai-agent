"""CLI `axon readiness` (§16) : état de maturité MÉCANIQUE du modèle réel — taille
d'échantillon, CLV, freshness, calibration, data quality, verdict, et bloqueurs EXACTS
vers SUPPORTED. Aucune promotion, aucune donnée fabriquée : dérive de
`assess_default_one_x_two` (walk-forward réel FL1). Le modèle réel reste EXPERIMENTAL
tant que les critères ne passent pas — cette commande le rend transparent.
"""

from __future__ import annotations

import argparse

from .assessment import (
    assess_bundesliga,
    assess_championship,
    assess_default_one_x_two,
    assess_eredivisie,
    assess_laliga,
    assess_primeira_liga,
    assess_serie_a,
)
from .maturity import Verdict

# Compétitions ayant un dataset réel embarqué -> readiness mesurable par walk-forward.
# Football (Dixon-Coles 1X2) + basket NBA (Elo moneyline, famille statistique PROPRE).
def _assess_nba(_odds=()):
    from .sports.basketball.moneyline import assess_nba
    return assess_nba()


def _assess_mlb(_odds=()):
    from .sports.baseball.moneyline import assess_mlb
    return assess_mlb()


def _assess_nfl(_odds=()):
    from .sports.american_football.moneyline import assess_nfl
    return assess_nfl()


def _assess_volley(_odds=()):
    from .sports.volleyball.moneyline import assess_volleyball
    return assess_volleyball()


_ASSESSORS = {"fl1": assess_default_one_x_two, "serie-a": assess_serie_a,
              "laliga": assess_laliga, "bundesliga": assess_bundesliga,
              "championship": assess_championship, "eredivisie": assess_eredivisie,
              "primeira-liga": assess_primeira_liga, "nba": _assess_nba, "mlb": _assess_mlb,
              "nfl": _assess_nfl, "volley": _assess_volley}


def render(assessment) -> list[str]:
    d = assessment.decision
    o = assessment.observations
    lines = [
        f"Readiness {d.model_name} {d.model_version} -> {d.status}",
        f"  policy maturité v{d.policy_version} (checksum {d.policy_checksum[:12]}…)",
        f"  échantillon hors échantillon : {o.n_evaluated}   | folds temporels : {o.n_temporal_folds}",
        f"  calibration (ECE) : {o.calibration_error}   | Brier {o.model_brier} vs baseline {o.best_baseline_brier}",
        f"  coverage : {o.data_coverage}   | data_quality : {o.mean_data_quality}",
        f"  CLV : {o.clv_status}   | freshness live : {o.live_freshness_status}",
        "  critères :",
    ]
    for c in d.criteria:
        flag = "REQUIS" if c.required else "monitoring"
        lines.append(f"    {c.name:28} {c.verdict.value:15} [{flag}]  {c.detail}")
    blockers = [c.name for c in d.criteria if c.required and c.verdict is not Verdict.PASS]
    lines.append(f"  bloqueurs vers SUPPORTED : {', '.join(blockers) if blockers else 'aucun'}")
    return lines


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="axon readiness",
                                description="Maturité mécanique du modèle (§16).")
    p.add_argument("--competition", choices=tuple(_ASSESSORS), default="fl1",
                   help="compétition à évaluer (dataset réel embarqué)")
    args = p.parse_args(argv)
    for line in render(_ASSESSORS[args.competition]()):
        print(line)
    return 0


if __name__ == "__main__":   # pragma: no cover
    raise SystemExit(main())
