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
