"""`axon historical-data status | opportunities` — l'audit du backfill.

Deux questions distinctes, deux commandes. `status` dit ce qui manque et ce que
le backfill a déjà changé ; `opportunities` dit où travailler ensuite. Les fondre
produirait une liste où les manques comblés côtoieraient les manques ouverts,
et où l'ordre n'aurait plus de sens.

CE QUI EST BLOQUÉ RESTE AFFICHÉ. Un manque énorme sans source licite ne descend
pas en bas du classement pour disparaître : il sort dans sa propre section, avec
le blocage nommé. C'est la seule présentation qui n'encourage pas à contourner.
"""

from __future__ import annotations

import argparse
from decimal import Decimal

from .known_gaps import COUVERTURE_SUFFISANTE, MESURE_LE, besoins_mesures
from .priority import (HistoricalBackfillPriority, PriorityBand, classer,
                       probabilite_de_recuperation)
from .registry import registre_par_defaut


def _priorite(besoin, registre) -> HistoricalBackfillPriority:
    candidates = registre.candidates(besoin)
    if candidates:
        proba, source, blocages = probabilite_de_recuperation(candidates)
    else:
        # Aucune source ne peut servir CE besoin. On regarde quand même celles du
        # sport pour nommer ce qui bloque — mais elles ne peuvent jamais devenir
        # `source_retenue` : le fork ATP est utilisable et sans rapport avec le
        # manque WTA, et l'afficher comme remède ferait croire le besoin couvert.
        _p, _s, blocages = probabilite_de_recuperation(
            [c for c in registre.for_sport(besoin.sport) if not c.is_routable])
        proba, source = Decimal("0"), ""
        if not blocages:
            blocages = ("NO_SOURCE_FOR_THIS_COMPETITION",)
    d = besoin.detail
    couverture = d.get("couverture", d.get("couverture_apres"))
    ecart = (Decimal("0.9") - Decimal(str(couverture))
             if couverture is not None and couverture < 0.9 else Decimal("0"))
    return HistoricalBackfillPriority(
        need=besoin,
        predictions_perdues=d.get("predictions_perdues", 0),
        coverage_gap=max(Decimal("0"), ecart),
        sample_size_gap=besoin.gap,
        entites_affectees=d.get("entites_sous_seuil", d.get("entites_totales", 0)),
        source_gratuite=bool(source),
        cout_reseau_estime=d.get("cout_reseau", 20),
        recovery_probability=proba,
        ferme_un_critere_de_maturite=ecart > 0 or besoin.gap > 0,
        source_retenue=source, blockers=blocages, detail=d)


def _status(registre) -> str:
    lignes = [f"AXON — historique : état des lieux (mesuré le {MESURE_LE})", ""]
    lignes.append(f"{'sport':<19}{'compétition':<28}{'perdues':>9}{'couv.':>9}"
                  f"{'entités':>9}  source")
    lignes.append("-" * 96)
    for b in besoins_mesures():
        d = b.detail
        couv = d.get("couverture_apres", d.get("couverture"))
        p = _priorite(b, registre)
        source = d.get("comble_par") or p.source_retenue or "—"
        comp = (b.competition_id or "").split(":")[-1]
        lignes.append(
            f"{b.sport:<19}{comp:<28}{d.get('predictions_perdues', 0):>9}"
            f"{(f'{couv:.4f}' if couv is not None else 'n/m'):>9}"
            f"{d.get('entites_sous_seuil', d.get('entites_totales', 0)):>9}  {source}")

    lignes += ["", "Couverture déjà suffisante (mesurée, pas supposée) :"]
    for sport, info in sorted(COUVERTURE_SUFFISANTE.items()):
        lignes.append(f"  {sport:<19}{info['competition']:<10}"
                      f"couverture {info['couverture']:.4f}  "
                      f"({info['perdues']} rencontres écartées)")

    lignes += ["", "Sources classées :"]
    for c in registre.all():
        lignes.append(f"  {c.provider:<28}{c.sport:<19}"
                      f"{'USABLE' if c.is_routable else 'NOT_USABLE'}")
        lignes.append(f"      licence : {c.classification.licence_id or '— non déclarée'}")
        if not c.is_routable:
            lignes.append(f"      bloqué par : {', '.join(c.classification.blockers)}")
    return "\n".join(lignes)


def _opportunities(registre) -> str:
    priorites = classer(_priorite(b, registre) for b in besoins_mesures())
    ouvertes = [p for p in priorites if p.band is not PriorityBand.BLOQUEE
                and (p.need.gap > 0 or p.coverage_gap > 0)]
    bloquees = [p for p in priorites if p.band is PriorityBand.BLOQUEE]
    comblees = [p for p in priorites if p not in ouvertes and p not in bloquees]

    lignes = ["AXON — backfills historiques par impact", ""]
    lignes.append("OUVERTS (source utilisable identifiée)")
    if not ouvertes:
        lignes.append("  aucun")
    for p in ouvertes:
        lignes.append(f"  [{p.band.value:<8}] score {p.score:>10}  {p.need.sport}/"
                      f"{(p.need.competition_id or '').split(':')[-1]}")
        lignes.append(f"             {p.predictions_perdues} prédictions perdues, "
                      f"{p.entites_affectees} entités, source « {p.source_retenue} »")

    lignes += ["", "BLOQUÉS (gain réel, aucune source licite)"]
    if not bloquees:
        lignes.append("  aucun")
    for p in bloquees:
        lignes.append(f"  [{p.band.value:<8}] gain brut {p.gain_brut:>10}  {p.need.sport}/"
                      f"{(p.need.competition_id or '').split(':')[-1]}")
        lignes.append(f"             {p.predictions_perdues} prédictions perdues, "
                      f"{p.entites_affectees} entités")
        lignes.append(f"             blocage : {', '.join(p.blockers) or 'inconnu'}")
        cause = p.need.detail.get("cause")
        if cause:
            lignes.append(f"             cause : {cause}")

    lignes += ["", "COMBLÉS (trace)"]
    for p in comblees:
        d = p.need.detail
        av, ap = d.get("couverture_avant"), d.get("couverture_apres")
        if av is not None and ap is not None:
            lignes.append(f"  {p.need.sport}/{(p.need.competition_id or '').split(':')[-1]} : "
                          f"couverture {av:.4f} -> {ap:.4f} via « {d.get('comble_par')} »")
    return "\n".join(lignes)


def main(argv=None) -> int:
    parseur = argparse.ArgumentParser(
        prog="axon historical-data",
        description="Manques historiques mesurés, sources classées, backfills classés.")
    sous = parseur.add_subparsers(dest="commande", required=True)
    sous.add_parser("status", help="ce qui manque, ce que le backfill a changé")
    sous.add_parser("opportunities", help="où une donnée supplémentaire rapporte le plus")
    args = parseur.parse_args(argv)

    registre = registre_par_defaut()
    print(_status(registre) if args.commande == "status" else _opportunities(registre))
    return 0


if __name__ == "__main__":       # pragma: no cover
    raise SystemExit(main())
