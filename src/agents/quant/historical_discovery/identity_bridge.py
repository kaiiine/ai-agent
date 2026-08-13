"""Rapprocher les participants de deux sources SANS jamais lire leurs noms.

Une source historique nouvelle n'apporte presque aucune métadonnée : openfootball
donne un nom et un code pays, rien d'autre. Le rapprochement par signaux
(`club_identity_resolution.resoudre`) en exige deux concordants ; pays + nom n'en
fait qu'UN, le pays servant d'ancrage et non de preuve. La source serait donc
inexploitable — alors que la preuve est ailleurs, et plus forte.

L'INSTANT COMME PREUVE. Si les deux sources rapportent exactement une rencontre
au même instant dans la même compétition, c'est la même rencontre : deux
rencontres distinctes ne partagent pas leur coup d'envoi à la minute près. Alors
domicile correspond à domicile, extérieur à extérieur — et aucun nom n'est entré
dans le raisonnement.

MAIS UN INSTANT SEUL NE SUFFIT PAS. Une soirée de coupe d'Europe aligne huit
rencontres à 21 h 00 : l'instant ne dit plus laquelle correspond à laquelle.
Mesuré sur la Ligue des Champions, 41 instants seulement sont non ambigus contre
156 qui ne le sont pas. D'où une PROPAGATION : dès qu'un participant est connu,
il désigne sa rencontre parmi les huit, ce qui livre son adversaire, qui à son
tour lève d'autres ambiguïtés. Chaque déduction reste FORCÉE — jamais préférée.

CE QUI REND LA MÉTHODE LÉGITIME, C'EST LA VÉRIFICATION DU FUSEAU. Sur un fuseau
supposé, l'appariement serait faux de bout en bout tout en paraissant parfait.
D'où l'exigence : `verifier_fuseau` doit avoir rendu VERIFIED avant d'appeler
ceci — sinon on rapproche des rencontres qui n'ont rien à voir, avec l'aplomb
d'une preuve exacte.

UNANIMITÉ, PAS MAJORITÉ. Un club revu vingt fois doit proposer vingt fois le même
homologue. Une seule divergence invalide le rapprochement entier : elle signifie
que l'hypothèse « un instant = une rencontre » a cédé quelque part, et une
majorité masquerait exactement l'erreur qu'on cherche.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import timedelta, timezone

_UTC = timezone.utc


@dataclass(frozen=True)
class AncrageTemporel:
    """Le résultat d'un ancrage : qui est qui, et ce qui a résisté."""

    paires: dict[str, str] = field(default_factory=dict)     # gauche -> droite
    #: Rejets explicites, par cause. Un rapprochement écarté doit se lire, sinon
    #: un corpus à moitié résolu ressemble à un corpus difficile.
    contradictions: dict[str, tuple[str, ...]] = field(default_factory=dict)
    non_unique: tuple[str, ...] = ()
    alias_acceptes: dict[str, str] = field(default_factory=dict)
    rencontres_appariees: int = 0
    tours_de_propagation: int = 0

    @property
    def resume(self) -> dict:
        return {
            "paires": len(self.paires),
            "alias_acceptes": len(self.alias_acceptes),
            "contradictions": len(self.contradictions),
            "non_unique": len(self.non_unique),
            "rencontres_appariees": self.rencontres_appariees,
            "tours": self.tours_de_propagation,
        }


def ancrer_par_instant(
    gauche, droite, *, tolerance: timedelta = timedelta(0),
    participants_gauche=None, participants_droite=None,
    accepter_alias: bool = True, max_tours: int = 20,
) -> AncrageTemporel:
    """Apparie les participants de deux corpus par coïncidence d'instant.

    `gauche` et `droite` sont des itérables d'objets portant `scheduled_at`,
    `competition` et `participants` ordonnés par rôle. Une `tolerance` non nulle
    est possible mais DÉCONSEILLÉE : elle rouvre l'ambiguïté que la méthode ferme.
    Elle existe pour les sports dont aucune source ne donne l'heure à la minute.

    `accepter_alias` autorise deux libellés de gauche à désigner le même
    participant de droite — le cas réel d'une source qui renomme un club d'une
    saison à l'autre. L'autorisation est CONDITIONNELLE : les deux libellés ne
    doivent jamais coexister dans une même saison. Deux clubs réellement distincts
    se croisent ; deux écritures d'un même club ne se croisent jamais.
    """
    if participants_gauche is None:
        participants_gauche = lambda e: tuple(e.participants)     # noqa: E731
    if participants_droite is None:
        participants_droite = lambda e: tuple(e.participants)     # noqa: E731

    par_instant_g = _grouper(gauche, tolerance)
    par_instant_d = _grouper(droite, tolerance)
    communs = [c for c in par_instant_g if c in par_instant_d]

    propositions: dict[str, list[str]] = defaultdict(list)
    connus: dict[str, str] = {}
    apparies: set[tuple[int, int]] = set()
    n_apparies = 0
    tours = 0

    for tour in range(1, max_tours + 1):
        tours = tour
        gagne = 0
        for cle in communs:
            evs_g, evs_d = par_instant_g[cle], par_instant_d[cle]
            libres_g = [(i, e) for i, e in enumerate(evs_g)
                        if not any(a[0] == i for a in apparies if a[2] == cle)]
            libres_d = [(j, e) for j, e in enumerate(evs_d)
                        if not any(a[1] == j for a in apparies if a[2] == cle)]
            if not libres_g or not libres_d:
                continue

            # 1. Déduction par participant déjà connu : un participant identifié
            #    désigne SA rencontre parmi celles de l'instant, et livre l'autre.
            for i, eg in list(libres_g):
                pg = participants_gauche(eg)
                cibles = [connus[p] for p in pg if p in connus]
                if not cibles:
                    continue
                candidats = [(j, ed) for j, ed in libres_d
                             if set(cibles) <= set(participants_droite(ed))]
                if len(candidats) != 1:
                    continue
                j, ed = candidats[0]
                pd = participants_droite(ed)
                if len(pg) != len(pd):
                    continue
                apparies.add((i, j, cle))
                libres_g = [(k, e) for k, e in libres_g if k != i]
                libres_d = [(k, e) for k, e in libres_d if k != j]
                n_apparies += 1
                gagne += 1
                for a, b in zip(pg, pd):
                    propositions[a].append(b)

            # 2. Déduction par élimination : s'il ne reste qu'une rencontre de
            #    chaque côté à cet instant, elles se correspondent forcément.
            if len(libres_g) == 1 and len(libres_d) == 1:
                (i, eg), (j, ed) = libres_g[0], libres_d[0]
                pg, pd = participants_gauche(eg), participants_droite(ed)
                if len(pg) == len(pd):
                    apparies.add((i, j, cle))
                    n_apparies += 1
                    gagne += 1
                    for a, b in zip(pg, pd):
                        propositions[a].append(b)

        # Un participant n'entre dans `connus` que si TOUTES ses propositions
        # concordent : une contradiction gèle le participant au lieu de trancher.
        connus = {a: bs[0] for a, bs in propositions.items() if len(set(bs)) == 1}
        if gagne == 0:
            break

    paires: dict[str, str] = {}
    contradictions: dict[str, tuple[str, ...]] = {}
    for a, bs in propositions.items():
        distincts = tuple(sorted(set(bs)))
        if len(distincts) == 1:
            paires[a] = distincts[0]
        else:
            contradictions[a] = distincts

    paires, non_unique, alias = _resoudre_collisions(
        paires, gauche, participants_gauche, accepter_alias)

    return AncrageTemporel(paires, contradictions, non_unique, alias,
                           n_apparies, tours)


def _resoudre_collisions(paires, gauche, participants_gauche, accepter_alias):
    """Deux libellés de gauche pour un même participant de droite : alias ou erreur ?

    La question se tranche sur les données, pas sur les chaînes : deux clubs
    distincts finissent par jouer la même saison — deux écritures d'un même club,
    jamais. Sans cette vérification, accepter les collisions fusionnerait deux
    histoires réelles ; les refuser toutes perdrait les sources qui renomment.
    """
    inverse: dict[str, list[str]] = defaultdict(list)
    for a, b in paires.items():
        inverse[b].append(a)

    saisons: dict[str, set] = defaultdict(set)
    for e in gauche:
        for p in participants_gauche(e):
            saisons[p].add(getattr(e, "season", None) or "")

    non_unique: list[str] = []
    alias: dict[str, str] = {}
    for cible, sources in inverse.items():
        if len(sources) == 1:
            continue
        disjoints = all(
            not (saisons[x] & saisons[y])
            for i, x in enumerate(sources) for y in sources[i + 1:])
        if accepter_alias and disjoints:
            # Tous restent dans `paires` — ce sont des rapprochements corrects.
            # `alias` signale les libellés SUPPLÉMENTAIRES, c'est-à-dire tous sauf
            # le plus ancien : l'ordre est donné par la première saison observée,
            # pas par l'alphabet, sans quoi le rapport changerait au renommage.
            par_anciennete = sorted(sources, key=lambda s: (min(saisons[s]), s))
            for s in par_anciennete[1:]:
                alias[s] = cible
            continue
        non_unique.extend(sources)
    for a in non_unique:
        paires.pop(a, None)
    return paires, tuple(sorted(set(non_unique))), alias


def _grouper(evenements, tolerance: timedelta) -> dict[tuple, list]:
    """(compétition, instant) -> rencontres. Avec tolérance, l'instant est
    quantifié — un seau, pas un arrondi glissant, pour rester déterministe."""
    par_cle: dict[tuple, list] = defaultdict(list)
    for e in evenements:
        if tolerance:
            pas = int(tolerance.total_seconds())
            cle_temps = int(e.scheduled_at.timestamp()) // pas
        else:
            cle_temps = e.scheduled_at.astimezone(_UTC).isoformat()
        par_cle[(e.competition, cle_temps)].append(e)
    return par_cle
