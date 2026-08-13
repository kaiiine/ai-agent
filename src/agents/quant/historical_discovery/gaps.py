"""Traduire un benchmark raté en BESOIN DE DONNÉES nommé.

Un walk-forward rend des exclusions (`INSUFFICIENT_DATA_no_prior_form: 132`) et
un verdict de maturité rend des critères en échec. Ni l'un ni l'autre ne dit
QUOI aller chercher : le premier compte des rencontres perdues sans dire de qui,
le second constate un seuil manqué sans dire ce qui le comblerait.

Ce module fait la jointure. Il part des exclusions RÉELLES, remonte aux entités
concernées, et produit des `HistoricalDataNeed` — c'est-à-dire une question à
laquelle une source peut répondre.

IL NE PROPOSE AUCUNE SOURCE. Séparer le constat du remède est ce qui empêche de
raisonner à l'envers : « quelle ligue ajouter » produit des données qu'aucun
modèle n'attendait. Le besoin d'abord, le routage ensuite (`capability`).

CE QUI EST DÉJÀ SUFFISANT NE PRODUIT PAS DE BESOIN. Un critère au vert n'ouvre
rien, même si des données existent — sans quoi la liste des besoins deviendrait
la liste de tout ce qui est téléchargeable, et ne trierait plus rien.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime

from .needs import HistoricalDataNeed

#: Exclusions qui traduisent un MANQUE D'HISTORIQUE, par opposition à un défaut
#: de la rencontre elle-même (score absent, identité non résolue). Seules
#: celles-ci se comblent par du backfill ; les autres relèvent de l'acquisition.
_EXCLUSIONS_HISTORIQUES = {
    "INSUFFICIENT_DATA_no_prior_form": "prior_form_absente",
}


def besoins_depuis_walk_forward(
    run, *, sport: str, competition_id: str,
    minimum_par_entite: int, entites_de=None,
) -> tuple[HistoricalDataNeed, ...]:
    """Besoins déduits des exclusions d'un rejeu.

    `entites_de(match)` rend les identités concernées par une rencontre. Sans
    lui, on saurait COMBIEN de rencontres sont perdues mais pas POUR QUI — et un
    besoin sans entité ne se comble pas, il se contemple.
    """
    besoins: list[HistoricalDataNeed] = []
    for code, n in (run.exclusions or {}).items():
        raison = _EXCLUSIONS_HISTORIQUES.get(code)
        if raison is None:
            continue
        besoins.append(HistoricalDataNeed(
            sport=sport, entity_type="team", entity_ids=("*",),
            data_type="matches", reason=code,
            minimum_required_evidence=minimum_par_entite,
            competition_id=competition_id,
            detail={"predictions_perdues": n, "categorie": raison}))
    return tuple(besoins)


def besoins_par_entite(
    matches, *, sport: str, competition_id: str, minimum_par_entite: int,
    exclus, participants_de=None, instant_de=None,
) -> tuple[HistoricalDataNeed, ...]:
    """Un besoin par entité réellement à court d'historique.

    `exclus` : les rencontres écartées faute de forme antérieure. On regarde ce
    que CHAQUE participant possédait au moment où sa rencontre a été écartée —
    c'est ce compte, et non le total de la compétition, qui dit s'il manque une
    saison ou dix.
    """
    if participants_de is None:
        participants_de = lambda m: (m.home_team_id, m.away_team_id)   # noqa: E731
    if instant_de is None:
        instant_de = lambda m: m.kickoff                                # noqa: E731

    anterieurs: dict[str, int] = Counter()
    vus: dict[str, int] = defaultdict(int)
    ordonnees = sorted(matches, key=instant_de)
    manquants: dict[str, int] = defaultdict(int)
    perdues: dict[str, int] = defaultdict(int)
    ids_exclus = {id(m) for m in exclus}

    for m in ordonnees:
        for p in participants_de(m):
            if id(m) in ids_exclus:
                manquants[p] = max(manquants[p], minimum_par_entite - vus[p])
                perdues[p] += 1
            vus[p] += 1
    anterieurs = dict(vus)

    besoins: list[HistoricalDataNeed] = []
    for entite, manque in sorted(manquants.items()):
        if manque <= 0:
            continue
        besoins.append(HistoricalDataNeed(
            sport=sport, entity_type="team", entity_ids=(entite,),
            data_type="matches", reason="INSUFFICIENT_DATA_no_prior_form",
            minimum_required_evidence=minimum_par_entite,
            observed_evidence=max(0, minimum_par_entite - manque),
            competition_id=competition_id,
            detail={"predictions_perdues": perdues[entite],
                    "rencontres_connues_au_total": anterieurs.get(entite, 0)}))
    return tuple(besoins)


def agreger(besoins, *, sport: str, competition_id: str) -> HistoricalDataNeed | None:
    """Fond des besoins d'entités en UN besoin de compétition.

    Deux cents besoins d'un match chacun ne se priorisent pas : ils se ressemblent
    tous. Agrégés, ils disent la vraie question — « cette compétition manque de
    profondeur historique » — qui a une réponse, elle."""
    besoins = tuple(besoins)
    if not besoins:
        return None
    entites = tuple(sorted({e for b in besoins for e in b.entity_ids}))
    perdues = sum(b.detail.get("predictions_perdues", 0) for b in besoins)
    return HistoricalDataNeed(
        sport=sport, entity_type="team", entity_ids=entites,
        data_type="matches", reason="INSUFFICIENT_DATA_no_prior_form",
        minimum_required_evidence=sum(b.minimum_required_evidence for b in besoins),
        observed_evidence=sum(b.observed_evidence for b in besoins),
        competition_id=competition_id,
        detail={"predictions_perdues": perdues, "entites": len(entites)})


def rencontres_exclues(matches, run, model, *, league_id: str, season: str):
    """Rejoue la gate de données pour retrouver QUELLES rencontres ont été écartées.

    Le `WalkForwardRun` n'en garde que le compte. Le rejeu est coûteux mais
    honnête : reconstruire la liste par déduction inverse ferait reposer un
    diagnostic sur une hypothèse, et c'est précisément ce qu'on cherche à éviter.
    """
    from src.agents.quant.betting_engine.core.canonical_event import (
        CanonicalEvent, CanonicalParticipant)
    from src.agents.quant.betting_engine.core.market_model import DataReadiness
    from src.agents.quant.betting_engine.calibration.point_in_time_gateway import (
        PointInTimeGateway)
    from src.agents.quant.betting_engine.sports.football.feature_engineering import (
        build_event_feature_set)

    ordonnees = sorted(matches, key=lambda m: m.kickoff)
    exclus = []
    for match in ordonnees:
        cutoff = match.kickoff
        pit = PointInTimeGateway(matches, cutoff=cutoff, league_id=league_id, season=season)
        event = CanonicalEvent(
            event_id=match.canonical_match_id, sport="football", competition_id=league_id,
            participants=(CanonicalParticipant(match.home_team_id, "home"),
                          CanonicalParticipant(match.away_team_id, "away")),
            scheduled_at=cutoff)
        features = build_event_feature_set(event, gateway=pit, as_of=cutoff)
        if model.assess_data_readiness(event, features) == DataReadiness.INSUFFICIENT_DATA:
            exclus.append(match)
    return exclus
