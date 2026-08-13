"""Rapprocher un joueur Sackmann (« Novak Djokovic ») d'un joueur tennis-data
(« Djokovic N. »), sans jamais approximer.

Les deux corpus écrivent les joueurs de façons incompatibles, et le module
d'identité tennis existant sait déjà réduire chaque forme à la MÊME clé exacte
`(patronyme, initiale)`. On le réutilise tel quel plutôt que d'inventer un
second mécanisme — deux règles de nommage qui divergeraient produiraient deux
identités pour un même joueur, donc un historique coupé en deux.

LE PIÈGE EST LE PRÉNOM COMPOSÉ. `winamax_key` suppose « prénom + patronyme » :
elle rend `("martin del potro", "j")` pour « Juan Martin Del Potro », quand
tennis-data écrit « Del Potro J.M. » et donne `("del potro", "j")`. Les deux
formes désignent le même joueur et ne se rencontrent jamais.

D'où une ÉNUMÉRATION DES DÉCOUPES : on essaie chaque frontière possible entre
prénoms et patronyme, et on ne retient une correspondance que si EXACTEMENT UNE
découpe tombe sur une clé connue. Ce n'est pas du rapprochement flou — chaque
candidat est une clé EXACTE, et l'ambiguïté fait échouer plutôt que choisir.

DEUX JOUEURS, UNE CLÉ : PERSONNE. Un patronyme et une initiale peuvent désigner
deux personnes réelles. Une telle clé n'identifie rien, ni côté Sackmann, ni côté
tennis-data : elle est écartée des deux côtés, et les rencontres concernées
restent hors du corpus plutôt que d'être attribuées au mauvais joueur.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from src.agents.quant.betting_engine.sports.tennis.identity import (
    dataset_key, slugify)


@dataclass(frozen=True)
class ResolutionJoueurs:
    """`nom Sackmann -> identité canonique`, avec ce qui n'a pas été résolu."""

    par_nom: dict[str, str] = field(default_factory=dict)
    #: Rapprochés à un joueur DÉJÀ connu de tennis-data — l'historique se recolle.
    apparies: int = 0
    #: Identité frappée : joueur absent de tennis-data (le cas normal en Challenger).
    frappes: int = 0
    #: Clés recouvrant deux personnes distinctes, écartées des deux côtés.
    ambigus: tuple[str, ...] = ()
    #: Noms dont aucune découpe ne produit de clé exploitable (doubles, formats rares).
    sans_cle: tuple[str, ...] = ()

    @property
    def resume(self) -> dict:
        return {"resolus": len(self.par_nom), "apparies": self.apparies,
                "frappes": self.frappes, "ambigus": len(self.ambigus),
                "sans_cle": len(self.sans_cle)}


def cles_candidates(nom_complet: str) -> list[tuple[str, str]]:
    """Toutes les découpes prénom(s)/patronyme d'un nom écrit en clair.

    « Juan Martin Del Potro » rend `("martin del potro","j")`, `("del potro","j")`
    et `("potro","j")`. Une seule sera connue du référentiel ; les autres ne
    correspondront à rien, ce qui est exactement le comportement voulu — une clé
    inconnue n'est pas un rapprochement raté, c'est un candidat éliminé.
    """
    jetons = [j for j in (nom_complet or "").replace("-", " ").split() if j]
    if len(jetons) < 2:
        return []
    initiale = jetons[0][0].lower()
    cles = []
    for debut in range(1, len(jetons)):
        cle = dataset_key(" ".join(jetons[debut:]) + f" {initiale.upper()}.")
        if cle and cle not in cles:
            cles.append(cle)
    return cles


def cle_de_frappe(nom_complet: str) -> tuple[str, str] | None:
    """La découpe RETENUE quand le joueur est inconnu de tennis-data : dernier
    jeton comme patronyme. Convention arbitraire mais FIXE — ce qui compte est
    que deux occurrences du même nom frappent la même identité."""
    cles = cles_candidates(nom_complet)
    return cles[-1] if cles else None


def identite_depuis_cle(cle: tuple[str, str], tour: str) -> str:
    """Même forme que les identités existantes : `slugify("Djokovic N.")` donne
    `djokovic_n`. Un joueur qui rejoint plus tard le circuit principal retrouve
    donc exactement l'identité qu'il avait en Challenger."""
    patronyme, initiale = cle
    return f"player:tennis:{tour}:{slugify(f'{patronyme} {initiale}.')}"


#: Un bloc d'initiales : « J. », « J.M. », « P.H ». Sert à distinguer une
#: SECONDE ORTHOGRAPHE d'un joueur d'un SECOND JOUEUR.
_RE_INITIALES = __import__("re").compile(r"^(?:[A-Za-z]\.?\s*)+$")


def _suite_initiales(nom: str, patronyme: str) -> str | None:
    """Les initiales qui suivent le patronyme, ou `None` si ce n'en sont pas.

    « Del Potro J.M. » rend « jm ». « Wang Y. Jr » rend `None` : « Jr » n'est pas
    une initiale, donc cette écriture peut désigner quelqu'un d'autre.
    """
    from src.agents.quant.betting_engine.sports.tennis.identity import _norm

    reste = _norm(nom)[len(patronyme):].strip()
    if not reste or not _RE_INITIALES.match(reste):
        return None
    return reste.replace(".", "").replace(" ", "")


def famille_d_orthographes(noms) -> str | None:
    """Ces écritures désignent-elles UNE personne ? Si oui, laquelle retenir.

    `cles_ambigues` refuse toute clé portée par plusieurs slugs, ce qui est la
    bonne règle par défaut : deux personnes ne doivent jamais fusionner. Mais
    tennis-data écrit le même joueur de plusieurs façons — « Del Potro J. »,
    « Del Potro J. M. », « Del Potro J.M. » — et la règle par défaut le rend
    alors introuvable, donc scindé en deux identités.

    Le critère est vérifiable, pas interprétatif : même patronyme, et suites
    d'initiales formant une CHAÎNE DE PRÉFIXES (« j » ⊂ « jm »). Une écriture qui
    n'est pas faite d'initiales — « Wang Y. Jr » — brise la chaîne et la clé
    reste ambiguë, car rien ne prouve qu'il s'agit de la même personne.

    Rend l'écriture la plus COURTE (la plus générale), ou `None`.
    """
    noms = sorted(set(noms))
    cles = {dataset_key(n) for n in noms}
    if len(cles) != 1 or None in cles:
        return None
    patronyme = next(iter(cles))[0]
    suites = {}
    for n in noms:
        s = _suite_initiales(n, patronyme)
        if s is None:
            return None
        suites.setdefault(s, n)
    ordonnees = sorted(suites)
    for court, long in zip(ordonnees, ordonnees[1:]):
        if not long.startswith(court):
            return None
    return suites[ordonnees[0]]


def index_tennis_data(noms_dataset, tour: str) -> tuple[dict, set]:
    """`(clé -> identité canonique, clés ambiguës)` côté tennis-data.

    Réutilise `cles_ambigues` — la règle qui protège l'argent ailleurs et qu'on
    ne touche pas — puis récupère les clés qu'elle a refusées pour cause de
    MULTI-ORTHOGRAPHE plutôt que de multi-personne.
    """
    from collections import defaultdict as _dd

    from src.agents.quant.betting_engine.sports.tennis.identity import cles_ambigues

    ambigues = cles_ambigues(noms_dataset)
    par_cle: dict = _dd(set)
    for nom in noms_dataset:
        cle = dataset_key(nom)
        if cle:
            par_cle[cle].add(nom)

    index: dict[tuple[str, str], str] = {}
    ambigues_reelles = set()
    for cle, noms in par_cle.items():
        if cle not in ambigues:
            index[cle] = f"player:tennis:{tour}:{slugify(next(iter(noms)))}"
            continue
        retenu = famille_d_orthographes(noms)
        if retenu is None:
            ambigues_reelles.add(cle)
        else:
            index[cle] = f"player:tennis:{tour}:{slugify(retenu)}"
    return index, ambigues_reelles


def identite_desambiguisee(cle: tuple[str, str], tour: str, source_id: str) -> str:
    """Identité DISTINCTE pour un homonyme, adossée à l'identifiant de la source.

    Deux personnes sous une même clé ne peuvent pas être identifiées l'une par
    rapport à l'autre — mais les refuser jette leurs rencontres, et avec elles
    l'historique de leurs ADVERSAIRES, qui n'y sont pour rien. Quand la source
    fournit un identifiant stable, on peut les garder SÉPARÉES : aucune fusion
    fausse, seulement un rattachement manquant.

    Le coût assumé : si l'une de ces joueuses figure aussi au circuit principal,
    son historique reste coupé en deux. C'est une sous-liaison, jamais une
    erreur d'attribution — et la sous-liaison se voit dans la couverture, pas
    dans les résultats du modèle.
    """
    patronyme, initiale = cle
    return (f"player:tennis:{tour}:"
            f"{slugify(f'{patronyme} {initiale}.')}__{slugify(str(source_id))}")


def resoudre_joueurs(noms_sackmann, *, index_dataset, ambigues_dataset,
                     tour: str, ids_par_nom=None,
                     desambiguiser_par_id: bool = False) -> ResolutionJoueurs:
    """Rapproche les joueurs Sackmann du référentiel, ou leur frappe une identité.

    `ids_par_nom` associe chaque nom Sackmann à son identifiant joueur d'origine.
    Il sert UNIQUEMENT à détecter l'ambiguïté réelle : deux identifiants
    distincts sous une même clé sont deux personnes, et ni l'une ni l'autre ne
    sera identifiée. Sans lui, deux homonymes fusionneraient en silence.
    """
    noms = sorted(set(noms_sackmann))
    ids_par_nom = ids_par_nom or {}

    # Ambiguïté INTERNE : une clé de frappe partagée par deux personnes.
    porteurs: dict[tuple[str, str], set] = defaultdict(set)
    for nom in noms:
        cle = cle_de_frappe(nom)
        if cle:
            porteurs[cle].add(ids_par_nom.get(nom, nom))
    ambigues_internes = {c for c, p in porteurs.items() if len(p) > 1}

    par_nom: dict[str, str] = {}
    apparies = frappes = 0
    ambigus: list[str] = []
    sans_cle: list[str] = []

    for nom in noms:
        candidates = cles_candidates(nom)
        if not candidates:
            sans_cle.append(nom)
            continue

        # 1. Rapprochement : une SEULE découpe connue du référentiel.
        connues = [c for c in candidates if c in index_dataset]
        if len(connues) == 1:
            par_nom[nom] = index_dataset[connues[0]]
            apparies += 1
            continue
        if len(connues) > 1:
            # Plusieurs découpes tombent sur des joueurs différents : indécidable.
            ambigus.append(nom)
            continue

        # 2. Frappe : joueur inconnu du circuit principal — le cas ordinaire en
        #    Challenger et en Future.
        cle = cle_de_frappe(nom)
        if cle is None:
            ambigus.append(nom)
            continue
        if cle in ambigues_internes or cle in ambigues_dataset:
            identifiant = ids_par_nom.get(nom)
            if not (desambiguiser_par_id and identifiant):
                ambigus.append(nom)
                continue
            par_nom[nom] = identite_desambiguisee(cle, tour, identifiant)
            frappes += 1
            continue
        par_nom[nom] = identite_depuis_cle(cle, tour)
        frappes += 1

    return ResolutionJoueurs(par_nom, apparies, frappes,
                             tuple(ambigus), tuple(sans_cle))
