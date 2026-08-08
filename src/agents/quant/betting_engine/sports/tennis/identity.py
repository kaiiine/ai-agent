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


# Un bloc d'initiales : « N. », « L.A. », « T. A. ». Le point est EXIGÉ dès qu'il y
# a plus d'une lettre, sinon un patronyme court (« Li », « Wu ») passerait pour des
# initiales et le nom de famille serait perdu.
_INITIALES = re.compile(r"^(?:[A-Za-z]\.)+[A-Za-z]?$|^[A-Za-z]$")


def dataset_key(name: str) -> tuple[str, str] | None:
    """« Djokovic N. » / « De Minaur A. » -> (nom_famille, initiale).

    Le nom de famille court jusqu'au PREMIER bloc d'initiales, ce qui préserve les
    patronymes composés. L'expression précédente terminait par
    `(?:\\s*[A-Za-z]\\.?)*`, qui consomme n'importe quelle suite de lettres une par
    une : « De Minaur A. » rendait `('de', 'm')` — le prénom devenait le nom, et
    tous les joueurs à particule restaient introuvables.
    """
    jetons = name.strip().split()
    for i, jeton in enumerate(jetons):
        if i == 0 or not _INITIALES.match(jeton):
            continue
        surname = _norm(" ".join(jetons[:i]))
        return (surname, jeton[0].lower()) if surname else None
    return None


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


def cles_ambigues(noms) -> set:
    """Clés qui recouvrent DEUX PERSONNES distinctes — les seules à refuser.

    Plusieurs orthographes d'un même joueur (« Tirante T. A. » / « Tirante T.A. »,
    « McNally C. » / « Mcnally C. ») partagent déjà un identifiant canonique : les
    traiter comme ambiguës ferait perdre le joueur pour une différence de
    ponctuation. Deux personnes réelles, elles, produisent des slugs distincts.

    Cette règle était écrite DEUX FOIS — ici et dans la construction des alias —
    et les deux copies décidaient d'argent. Une seule source désormais.
    """
    par_cle: dict = {}
    for n in noms:
        k = dataset_key(n)
        if k:
            par_cle.setdefault(k, set()).add(slugify(n))
    return {k for k, slugs in par_cle.items() if len(slugs) > 1}


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

    ambigues = cles_ambigues(names)

    alias_map = _load_aliases().get("aliases", {}).get(tour, {})   # {nom_dataset: [alias…]}
    entities: list[CanonicalEntity] = []
    dataset_of: dict[str, str] = {}
    for name in sorted(names):
        k = dataset_key(name)
        cid = f"player:tennis:{tour}:{slugify(name)}"
        ambiguous = bool(k) and k in ambigues
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
    ambigues = cles_ambigues(names)
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
        if not candidates:
            continue
        # Plusieurs ORTHOGRAPHES d'une même personne ne sont pas une ambiguïté :
        # « Tirante T. A. » et « Tirante T.A. » désignent le même joueur et portent
        # déjà le même identifiant canonique. Refuser là ferait perdre le joueur
        # pour une différence de ponctuation. L'ambiguïté RÉELLE — deux personnes
        # distinctes sous la même clé — reste refusée : leurs slugs diffèrent.
        if k in ambigues:
            continue
        target = sorted(candidates)[0]              # déterministe entre variantes
        table.setdefault(target, [])
        if wx not in table[target]:
            table[target].append(wx)
    return table
