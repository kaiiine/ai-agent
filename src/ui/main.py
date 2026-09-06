#!/usr/bin/env python3
from __future__ import annotations
import sys
import os

# ── 0. Commandes de diagnostic rapide — pas de boot loader / graphe pour ça ───
if len(sys.argv) > 1 and sys.argv[1] in ("sports-status", "sports-seed"):
    from dotenv import load_dotenv
    load_dotenv()
    if sys.argv[1] == "sports-seed":
        from src.agents.quant.gateway.status import seed_coverage
        seed_coverage()
    else:
        import argparse
        parser = argparse.ArgumentParser(prog="axon sports-status")
        parser.add_argument("--sport", default="football")
        parser.add_argument("--competition", default=None)
        parser.add_argument("--season", default=None)
        args = parser.parse_args(sys.argv[2:])
        from src.agents.quant.gateway.status import print_status
        print_status(competition=args.competition, season=args.season)
    sys.exit(0)

# ── 0bis. `axon recommend` — délègue au CLI Advisor (aucune logique métier ici) ─
if len(sys.argv) > 1 and sys.argv[1] == "recommend":
    from dotenv import load_dotenv
    load_dotenv()
    from src.agents.quant.advisor.cli import main as _advisor_recommend
    sys.exit(_advisor_recommend(sys.argv[2:]))

# ── 0ter. `axon record-odds` — collecte odds_history (BE-FR-015), aucune logique ici ─
if len(sys.argv) > 1 and sys.argv[1] == "record-odds":
    from src.agents.quant.betting_engine.clv.cli import main as _record_odds
    sys.exit(_record_odds(sys.argv[2:]))

# ── 0ter-bis. `axon outcomes` — justesse RÉELLE du modèle, aucune logique ici ─
# `status` lit la calibration mesurée sur les issues observées ; `settle` règle les
# prédictions en attente depuis le jeu de données. Sans elles, la seule mesure de
# justesse restait un walk-forward historique.
if len(sys.argv) > 1 and sys.argv[1] == "outcomes":
    from src.agents.quant.betting_engine.outcomes.cli import main as _outcomes
    sys.exit(_outcomes(sys.argv[2:]))

# ── 0ter-ter. `axon catalog-coverage` — part du catalogue réellement évaluable ─
if len(sys.argv) > 1 and sys.argv[1] == "catalog-coverage":
    from src.agents.quant.betting_engine.catalog_coverage.cli import main as _catcov
    sys.exit(_catcov(sys.argv[2:]))

# ── 0quater. `axon coverage` — couverture Winamax -> modèle (§16), aucune logique ici ─
if len(sys.argv) > 1 and sys.argv[1] == "coverage":
    from src.agents.quant.betting_engine.coverage_cli import main as _coverage
    sys.exit(_coverage(sys.argv[2:]))

# ── 0quinquies. `axon readiness` — maturité mécanique du modèle (§16), aucune logique ici ─
if len(sys.argv) > 1 and sys.argv[1] == "readiness":
    from src.agents.quant.betting_engine.readiness_cli import main as _readiness
    sys.exit(_readiness(sys.argv[2:]))

# ── 0sexies-bis. `axon tennis-inventory` — inventaire dataset tennis LOCAL (Unité B), aucun DL ─
if len(sys.argv) > 1 and sys.argv[1] == "tennis-inventory":
    from src.agents.quant.betting_engine.sports.tennis.inventory_cli import main as _tennis_inv
    sys.exit(_tennis_inv(sys.argv[2:]))

# ── 0quinquies-bis. `axon cron-test <id>` — lance une tâche planifiée MAINTENANT ─
# Sans elle, la seule façon de savoir si une tâche marche est d'attendre son
# déclenchement. L'exécution est réelle, seuls les effets sont suspendus.
if len(sys.argv) > 2 and sys.argv[1] == "cron-test":
    from dotenv import load_dotenv
    load_dotenv()
    from src.agents.cron.essai import essayer, rendre
    print(rendre(essayer(sys.argv[2])))
    sys.exit(0)

if len(sys.argv) > 1 and sys.argv[1] == "cron-test":
    from dotenv import load_dotenv
    load_dotenv()
    from src.agents.cron.store import get_tasks
    for t in get_tasks():
        etat = "actif " if t.get("active") else "arrêté"
        veille = " · veille" if t.get("surveillance") else ""
        print(f"  {t['id']}  {etat}{veille}  {t.get('description', '')}")
    print("\n  axon cron-test <id>  pour en essayer une")
    sys.exit(0)

# ── 0quinquies-ter. `axon trace` — relire la trace de décision ────────────────
# Avant le boot loader et le graphe : relire un journal n'a besoin ni de l'un ni
# de l'autre, et les charger coûterait quelques secondes pour lire un fichier.
if len(sys.argv) > 1 and sys.argv[1] == "trace":
    from dotenv import load_dotenv
    load_dotenv()
    from src.infra.trace_cli import main as _trace
    sys.exit(_trace(sys.argv[2:]))

# ── 0sexies. `axon providers-discover` — découverte de sources (Tavily), hors money-path (§25) ─
if len(sys.argv) > 1 and sys.argv[1] == "providers-discover":
    from dotenv import load_dotenv
    load_dotenv()
    from src.agents.quant.gateway.providers.discover_cli import main as _discover
    sys.exit(_discover(sys.argv[2:]))

# ── 1. Boot loader — démarre immédiatement ────────────────────────────────────
from rich.console import Console as _Console
from src.ui.boot import BootLoader, report_step

_console = _Console()
_console.clear()
_loader = BootLoader(_console)
_loader.start()

# ── 2. Imports lourds (warnings supprimés, loader visible pendant ce temps) ───
# streaming.py (qui crée PromptSession) est importé de façon lazy dans run_cli()
# → pas de conflit avec le Live actif ici
_stderr = sys.stderr
sys.stderr = open(os.devnull, "w")
try:
    import warnings
    warnings.filterwarnings("ignore")
    report_step("modules IA…")
    from src.orchestrator.graph import build_orchestrator
    from src.ui.app import run_cli
    from dotenv import load_dotenv
finally:
    sys.stderr.close()
    sys.stderr = _stderr

# La suppression ci-dessus ne vaut que pour la phase d'IMPORT. Les journaux émis
# à chaque appel LLM — un par clé de schéma refusée, par outil — passeraient
# sinon en plein milieu de l'interface.
from src.infra.journal import taire_les_bavards
taire_les_bavards()

# ── 3. Construction du graphe ─────────────────────────────────────────────────
report_step("construction du graphe…")
_graph = build_orchestrator()

# ── 4. Stop loader — streaming.py / PromptSession s'importent après ──────────
_loader.stop()

load_dotenv()


def main():
    run_cli(_graph)


if __name__ == "__main__":
    main()
