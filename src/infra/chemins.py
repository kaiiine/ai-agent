"""Où AXON écrit son état — déclaré une fois, surchargeable.

Neuf fichiers recalculaient chacun `Path.home() / ".axon"`. Trois conséquences :

- **rien n'était surchargeable.** Le README annonce `AXON_INSTALL_DIR` pour le
  dépôt ; l'état, lui, était cloué dans `$HOME`. Sur une machine où `$HOME` est
  petit, monté en réseau ou partagé, il n'y avait aucune issue.
- **rien ne listait ce qu'AXON écrit.** Il fallait grepper pour le savoir.
- **les tests écrivaient dans le VRAI état.** Chaque suite qui touchait au cache
  d'outils ou au journal des échecs marchait sur celui de l'utilisateur.

Ce qui n'entre PAS ici : les constantes réglées — `_BUDGET_OUTILS`,
`_DOMAINES_MAX`, `_MARGE_CLAUSE`. Chacune porte en commentaire le balayage qui
l'a fixée et le harnais qui le rejoue ; les déplacer les couperait de leur
justification, et c'est précisément le défaut que le chantier harnais corrige —
130 chiffres dont la provenance s'était perdue. Un paramètre de déploiement se
configure, une propriété mesurée se documente sur place.

Ce qui n'entre pas non plus : le `.axon/` d'un PROJET (`build-state.json`,
`memory/`). Il vit à la racine du dépôt visé, pas dans l'état de l'utilisateur —
deux notions que le même nom rapproche à tort.
"""
from __future__ import annotations

import os
from pathlib import Path


def racine_etat() -> Path:
    """Le dossier d'état, `~/.axon` par défaut.

    Lu à CHAQUE appel, jamais figé à l'import : un test qui pose
    `AXON_STATE_DIR` via `monkeypatch` doit être entendu, or l'import a lieu
    bien avant lui.
    """
    return Path(os.environ.get("AXON_STATE_DIR") or Path.home() / ".axon")


def etat(*parties: str) -> Path:
    """Un chemin sous le dossier d'état. Ne crée rien — c'est à l'appelant."""
    return racine_etat().joinpath(*parties)


# ── Ce qu'AXON écrit, nommé une fois ─────────────────────────────────────────
# Fonctions et non constantes : une constante fige `$HOME` à l'import et rend la
# surcharge inopérante.

def base_memoire() -> Path:
    """Threads LangGraph — `memory.db`."""
    return etat("memory.db")


def dernier_thread() -> Path:
    return etat("last_thread")


def echecs_backend() -> Path:
    """Journal des pannes de fournisseur, lu par `/backend`."""
    return etat("backend_failures.jsonl")


def pool_de_cles() -> Path:
    """Cooldown des clés API, par fournisseur."""
    return etat("key_pool_state.json")


def index_outils() -> Path:
    """Cache Chroma du routage — reconstruit si l'empreinte change."""
    return etat("tool_store")


def serveurs_mcp() -> Path:
    """`AXON_MCP_CONFIG` reste prioritaire : cette surcharge existait déjà."""
    return Path(os.environ.get("AXON_MCP_CONFIG") or etat("mcp_servers.json"))


def pid_cron() -> Path:
    return etat("cron.pid")


def mesures() -> Path:
    """Relevés datés des harnais — `outils/mesure_routage.py --journal`."""
    return etat("mesures.jsonl")


def crons() -> Path:
    return etat("crons.json")


def journaux_cron() -> Path:
    return etat("cron_logs")


def historique_saisie() -> Path:
    """Ce que l'utilisateur a tapé — relu par la flèche haut."""
    return etat("input_history")


# Le moteur de paris tient ses propres bases. Elles sont nommées ici pour la même
# raison que les autres : rien ne listait ce qu'AXON écrit sous `~/.axon`.
def cache_quant() -> Path:
    return etat("quant_cache.db")


def cache_operationnel() -> Path:
    return etat("sports_operational_cache.db")


def magasin_point_in_time() -> Path:
    return etat("sports_point_in_time.db")


def journal_decisions() -> Path:
    return etat("sports_gateway_decisions.log")


def couverture_fournisseurs() -> Path:
    return etat("sports_provider_coverage.db")


def decisions() -> Path:
    """La trace de décision — une ligne par action, `run_id` en clé."""
    return etat("decisions.jsonl")


def repere_langfuse() -> Path:
    """Jusqu'où l'export Langfuse est monté, pour reprendre sans doublon."""
    return etat("langfuse_export.json")


def incidents() -> Path:
    """Erreurs déduites de la trace, gardées d'une conversation à l'autre."""
    return etat("incidents.jsonl")


def memoire_projet() -> Path:
    """Mémoire inter-sessions écrite par `axon_note`, côté état utilisateur."""
    return etat("memory")
