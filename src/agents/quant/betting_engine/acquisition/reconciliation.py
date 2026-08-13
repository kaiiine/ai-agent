"""Fusionner deux providers sans compter deux fois la même rencontre.

Concaténer naïvement doublerait l'échantillon d'un walk-forward : le modèle
verrait le même match deux fois, `min_sample_size` passerait pour de mauvaises
raisons, et la calibration serait mesurée sur des doublons. Un critère de
maturité franchi par duplication est pire qu'un critère non franchi.

APPARIEMENT DÉTERMINISTE, jamais probabiliste : même compétition, même paire de
participants canoniques, coup d'envoi à moins de `TOLERANCE_HEURES`. Aucune
similarité de nom, aucun score de ressemblance — un rapprochement flou ferait
fusionner deux rencontres réellement distinctes, et l'erreur serait invisible.

AUCUNE PRÉFÉRENCE SILENCIEUSE. Deux providers qui donnent des scores différents
pour la même rencontre produisent un CONFLIT rapporté, pas un arbitrage. Choisir
« le premier » ou « le plus récent » serait une décision statistique déguisée en
détail d'implémentation.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import timedelta

#: Deux providers horodatent rarement à la seconde près (fuseau, heure annoncée
#: contre heure réelle). Au-delà, ce sont deux rencontres.
TOLERANCE_HEURES = 6


def _cle_paire(a: str, b: str) -> tuple[str, str]:
    """Paire NON ORDONNÉE : un provider peut inverser domicile et extérieur."""
    return (a, b) if a <= b else (b, a)


@dataclass(frozen=True)
class Conflit:
    """Deux sources, une rencontre, deux vérités. Rapporté, jamais arbitré."""

    competition_id: str
    participants: tuple[str, str]
    kickoff: str
    scores: tuple[tuple[str, int, int], ...]     # (provider, buts_dom, buts_ext)


@dataclass(frozen=True)
class Reconciliation:
    matches: tuple                              # rencontres canoniques uniques
    par_provider: dict[str, int] = field(default_factory=dict)
    duplicates_matched: int = 0
    conflicts: tuple[Conflit, ...] = ()
    unresolved: tuple = ()

    @property
    def resume(self) -> dict:
        return {
            "raw_par_provider": dict(self.par_provider),
            "raw_total": sum(self.par_provider.values()),
            "unique_canonical": len(self.matches),
            "duplicates_matched": self.duplicates_matched,
            "conflicts": len(self.conflicts),
            "unresolved": len(self.unresolved),
        }


def _empreinte(match) -> tuple:
    """Clé d'appariement : compétition + paire, SANS horaire.

    L'horodatage a d'abord figuré ici, arrondi à l'heure — ce qui annulait la
    tolérance : 19 h 00 et 21 h 00 tombaient dans deux clés distinctes et
    n'étaient donc jamais comparés. Le temps ne sépare qu'APRÈS, par
    `_regrouper_par_proximite`, qui distingue proprement un doublon d'un match
    aller-retour.
    """
    return (match.league_id, _cle_paire(match.home_team_id, match.away_team_id))


def reconcilier(par_provider: dict[str, list]) -> Reconciliation:
    """Fusionne des rencontres canoniques venues de plusieurs providers.

    L'ordre des providers ne change PAS le résultat : sur rencontre identique la
    première vue est conservée, et sur score divergent rien n'est conservé — le
    conflit est rapporté et la rencontre écartée de l'échantillon plutôt que
    d'entrer avec une valeur choisie au hasard.
    """
    groupes: dict[tuple, list[tuple[str, object]]] = defaultdict(list)
    comptes: dict[str, int] = {}

    for provider, matches in sorted(par_provider.items()):
        comptes[provider] = len(matches)
        for m in matches:
            groupes[_empreinte(m)].append((provider, m))

    # Un même provider peut lister deux rencontres dans la même fenêtre horaire :
    # ce n'est pas un doublon inter-provider, on les garde toutes.
    retenus, conflits, doublons = [], [], 0
    for empreinte, entrees in groupes.items():
        proches = _regrouper_par_proximite(entrees)
        for grappe in proches:
            providers = {p for p, _ in grappe}
            scores = {(m.goals_home, m.goals_away) for _, m in grappe}
            if len(providers) > 1 and len(scores) > 1:
                conflits.append(Conflit(
                    competition_id=grappe[0][1].league_id,
                    participants=_cle_paire(grappe[0][1].home_team_id,
                                            grappe[0][1].away_team_id),
                    kickoff=grappe[0][1].kickoff.isoformat(),
                    scores=tuple(sorted((p, m.goals_home, m.goals_away) for p, m in grappe))))
                continue
            doublons += len(grappe) - 1
            retenus.append(grappe[0][1])

    retenus.sort(key=lambda m: m.kickoff)
    return Reconciliation(tuple(retenus), comptes, doublons, tuple(conflits))


def _regrouper_par_proximite(entrees) -> list[list]:
    """Sépare des rencontres de même empreinte mais trop éloignées dans le temps."""
    ordonnees = sorted(entrees, key=lambda e: e[1].kickoff)
    grappes: list[list] = []
    for entree in ordonnees:
        if grappes and (entree[1].kickoff - grappes[-1][0][1].kickoff
                        <= timedelta(hours=TOLERANCE_HEURES)):
            grappes[-1].append(entree)
        else:
            grappes.append([entree])
    return grappes
