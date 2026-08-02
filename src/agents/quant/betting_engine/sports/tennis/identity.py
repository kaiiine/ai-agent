"""Identité JOUEUR tennis — pont Winamax <-> dataset, DÉTERMINISTE (jamais fuzzy).

Le dataset nomme « Djokovic N. » ; Winamax nomme « Novak Djokovic ». Le pont est une clé
NORMALISÉE `(nom_de_famille, initiale)` calculée des DEUX côtés, sans accents et sans
casse — c'est une normalisation exacte, PAS une approximation :

    « Novak Djokovic »  -> ("djokovic", "n")
    « Djokovic N. »     -> ("djokovic", "n")

Garde-fous (identiques à la discipline des autres sports) :
- une clé partagée par PLUSIEURS joueurs du même circuit est AMBIGUË -> ces joueurs
  n'obtiennent AUCUN alias, donc l'événement reste UNRESOLVED (jamais mal résolu) ;
- les paires de double (« A.Klepac / M.Ninomiya ») ne sont PAS des joueurs -> ignorées ;
- ATP et WTA vivent dans des espaces de noms SÉPARÉS (`player:tennis:atp:…` /
  `player:tennis:wta:…`), donc un homonyme inter-circuits ne se croise jamais.

Les alias Winamax proviennent d'un scan LIVE réel (fixture `tennis_winamax_aliases.json`,
provenance + date dedans). Un joueur absent de ce scan existe comme entité mais sans alias
Winamax : son événement reste explicitement non résolu tant que l'alias n'est pas observé
(rafraîchir via `python -m ...tennis.refresh_aliases`). Jamais de nom deviné.
"""

from __future__ import annotations

import functools
import json
import re
import unicodedata
from pathlib import Path

from src.agents.quant.gateway.core.identity_resolver import CanonicalEntity

from .tennis_data_loader import load_tennis_data

_ALIAS_FIXTURE = (Path(__file__).resolve().parents[6] / "tests" / "fixtures" / "tennis"
                  / "tennis_winamax_aliases.json")


def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def _norm(s: str) -> str:
    return _strip_accents(s).lower().replace("-", " ").strip()


def dataset_key(name: str) -> tuple[str, str] | None:
    """« Djokovic N. » / « Auger-Aliassime F. » -> (nom_famille, initiale)."""
    m = re.match(r"^(.*?)\s+([A-Za-z])\.?(?:\s*[A-Za-z]\.?)*\s*$", name.strip())
    if not m:
        return None
    surname = _norm(m.group(1))
    return (surname, m.group(2).lower()) if surname else None


def winamax_key(name: str) -> tuple[str, str] | None:
    """« Novak Djokovic » -> (nom_famille, initiale). None si double/abréviation."""
    n = _strip_accents(name or "").strip()
    if "/" in n or "." in n:                       # paire de double, ou nom déjà abrégé
        return None
    parts = n.split()
    if len(parts) < 2:
        return None
    return (_norm(" ".join(parts[1:])), parts[0][0].lower())


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", _norm(name)).strip("_")


def _load_aliases() -> dict:
    if not _ALIAS_FIXTURE.exists():
        return {"aliases": {}}
    return json.loads(_ALIAS_FIXTURE.read_text(encoding="utf-8"))


@functools.lru_cache(maxsize=2)
def tennis_players(tour: str) -> tuple[list[CanonicalEntity], dict[str, str]]:
    """(`entités canoniques`, `canonical_id -> nom dataset`) pour un circuit.

    Une clé AMBIGUË (plusieurs joueurs, même nom de famille + initiale) ne reçoit aucun
    alias Winamax : l'événement restera non résolu plutôt que mal attribué."""
    tour = tour.lower()
    ds = load_tennis_data(tour)
    names: set[str] = set()
    for m in ds.matches:
        names.add(m.p1_name)
        names.add(m.p2_name)

    by_key: dict[tuple[str, str], set[str]] = {}
    for n in names:
        k = dataset_key(n)
        if k:
            by_key.setdefault(k, set()).add(n)

    alias_map = _load_aliases().get("aliases", {}).get(tour, {})   # {nom_dataset: [alias…]}
    entities: list[CanonicalEntity] = []
    dataset_of: dict[str, str] = {}
    for name in sorted(names):
        k = dataset_key(name)
        cid = f"player:tennis:{tour}:{slugify(name)}"
        ambiguous = bool(k) and len(by_key.get(k, ())) > 1
        aliases = [] if ambiguous else list(alias_map.get(name, []))
        entities.append(CanonicalEntity(cid, name, aliases, {}))
        dataset_of[cid] = name
    return entities, dataset_of


def build_alias_table(winamax_names, tour: str) -> dict[str, list[str]]:
    """Apparie des noms Winamax RÉELS aux joueurs du dataset par clé normalisée.
    Une clé ambiguë ou inconnue ne produit AUCUN alias (jamais un rattachement deviné)."""
    ds = load_tennis_data(tour)
    names: set[str] = set()
    for m in ds.matches:
        names.add(m.p1_name)
        names.add(m.p2_name)
    by_key: dict[tuple[str, str], set[str]] = {}
    for n in names:
        k = dataset_key(n)
        if k:
            by_key.setdefault(k, set()).add(n)

    table: dict[str, list[str]] = {}
    for wx in sorted(set(winamax_names)):
        k = winamax_key(wx)
        if not k:
            continue
        candidates = by_key.get(k)
        if not candidates or len(candidates) > 1:   # inconnu ou AMBIGU -> aucun alias
            continue
        target = next(iter(candidates))
        table.setdefault(target, [])
        if wx not in table[target]:
            table[target].append(wx)
    return table
