"""Pricer LIVE des marchés de score — un seul, pour tous les sports à points.

Le pendant production du benchmark : les mêmes notes, la même loi, les mêmes
paramètres. Un second chemin de calcul, même écrit à l'identique le jour où on
l'écrit, diverge tôt ou tard de celui qui a été validé — et c'est alors la
version validée qu'on croit exécuter.

UNE SEULE LOI PAR RENCONTRE, N PROJECTIONS. Un événement NBA expose 78 lignes de
handicap et 81 lignes de total : recalculer les notes pour chacune coûterait cent
cinquante reconstructions du même état, et ne garantirait plus que le `-5,5` et le
`+5,5` du même match sortent de la même distribution.

LE DOMAINE EST VÉRIFIÉ AVANT DE PRICER. Le corpus embarqué s'arrête à une date ;
au-delà, les notes décrivent une saison que les équipes ne jouent plus. Et il
couvre UNE compétition : appliquer des notes NBA à une rencontre WNBA
produirait une probabilité sur des équipes que le modèle n'a jamais vues. Les
deux refus sont mesurés, pas supposés.
"""

from __future__ import annotations

import functools
from collections.abc import Mapping

from ..markets.families import MarketFamily
from ..markets.pricing import (
    MarketPricing,
    PricedSelection,
    PricingStatus,
    abstention,
)
from ..markets.observation import CLES_DE_PORTEE, CLES_DE_SUJET
from .score_distribution import LOIS, SequentialScoreRatings

#: Âge maximal du corpus au moment de la décision. Ce n'est pas un seuil de
#: décision money : c'est la borne au-delà de laquelle des notes séquentielles
#: cessent de décrire les équipes qui jouent. La valeur est celle du garde de
#: domaine football — un cycle de compétition — et pour la même raison.
CYCLE_CORPUS_JOURS = 365


@functools.lru_cache(maxsize=8)
def _etat_du_corpus(cle: str):
    """Notes séquentielles ajustées sur TOUT le corpus embarqué, mémorisées.

    Le corpus ne change pas d'un événement à l'autre : le rejouer par rencontre
    coûterait quatre mille mises à jour pour un état identique. La mémorisation
    porte sur la CLÉ DE CONFIGURATION, jamais sur l'instant de décision — sans
    quoi un run tardif réutiliserait l'état d'un run antérieur.
    """
    config = _CONFIGS[cle]
    jeux = sorted(config.load(), key=lambda g: g.tipoff)
    notes = SequentialScoreRatings(config.params)
    for game in jeux:
        notes.update(game)
    dernier = jeux[-1].tipoff if jeux else None
    equipes = frozenset(notes.played)
    return notes, dernier, equipes


def _configs() -> dict:
    from .american_football.score_markets import NFL_SCORE_CONFIG
    from .basketball.score_markets import NBA_SCORE_CONFIG
    from .baseball.score_markets import MLB_SCORE_CONFIG
    return {c.sport: c for c in (NBA_SCORE_CONFIG, NFL_SCORE_CONFIG, MLB_SCORE_CONFIG)}


_CONFIGS = _configs()


class ScorePricer:
    """Price `TOTALS` et `HANDICAP` d'un sport à points, refuse le reste avec son motif."""

    families = frozenset({MarketFamily.TOTALS, MarketFamily.HANDICAP,
                          MarketFamily.TEAM_TOTALS})

    def __init__(self, sport: str):
        self.sport = sport
        self.config = _CONFIGS[sport]
        self.model_name = self.config.model_name

    # -- contrat MarketPricer -------------------------------------------------
    def supports(self, family: MarketFamily, parameters: Mapping) -> bool:
        if family not in self.families or self.config.law is None:
            return False
        if any(c in parameters for c in (*CLES_DE_PORTEE, *CLES_DE_SUJET)):
            return False
        from ..markets.capability import _score_rencontre, _total_equipe
        from ..bookmakers.winamax.connector import SPORT_IDS

        sport_id = SPORT_IDS.get(self.sport)
        if sport_id is None:
            return False
        if family is MarketFamily.TEAM_TOTALS:
            return _total_equipe(sport_id, parameters)
        return _score_rencontre(sport_id, family, parameters)

    def price(self, *, event, family: MarketFamily, parameters: Mapping,
              context: Mapping) -> MarketPricing:
        event_id = str(getattr(event, "event_id", ""))
        refus = lambda statut, motif: abstention(  # noqa: E731
            event_id=event_id, sport=self.sport, family=family, status=statut,
            reason=motif, parameters=parameters, context={})

        if self.config.law is None:
            from .baseball.score_markets import STOP_STATISTIQUE
            return refus(PricingStatus.VALIDATION_REJECTED, STOP_STATISTIQUE)

        if not self.supports(family, parameters):
            return refus(PricingStatus.MODEL_CONTEXT_MISMATCH,
                         f"ce marché n'est pas celui de la RENCONTRE pour "
                         f"{family.value}, ou sa ligne sort du support évalué : "
                         f"{dict(parameters)}")

        point_in_time = context.get("point_in_time")
        if point_in_time is None:
            return refus(PricingStatus.DATA_NOT_AVAILABLE,
                         "point_in_time absent du contexte")

        competition = getattr(event, "competition_id", None)
        if competition and competition != self.config.competition_id:
            return refus(
                PricingStatus.MODEL_DOMAIN_MISMATCH,
                f"corpus {self.config.competition_id} — cette rencontre est de "
                f"{competition}. Les notes décrivent des équipes que ce "
                "championnat ne fait pas jouer.")

        notes, dernier, connues = _etat_du_corpus(self.sport)
        if dernier is None:
            return refus(PricingStatus.DATA_NOT_AVAILABLE, "corpus vide")
        age = (point_in_time - dernier).days
        if age > CYCLE_CORPUS_JOURS:
            return refus(
                PricingStatus.MODEL_DOMAIN_MISMATCH,
                f"dernière rencontre du corpus il y a {age} j (> {CYCLE_CORPUS_JOURS}) : "
                "les notes décrivent une saison qui n'est plus jouée")

        par_role = {p.role: p.canonical_id for p in getattr(event, "participants", ())}
        if par_role.get("home") is None or par_role.get("away") is None:
            return refus(PricingStatus.DATA_NOT_AVAILABLE,
                         "rôles domicile/extérieur non résolus")
        # Identité CANONIQUE -> identifiant du corpus, via la table du moneyline
        # du sport. Le corpus indexe ses équipes par leur identifiant de source ;
        # lui présenter un identifiant canonique ne trouve jamais rien, et le
        # refus se lirait « équipe inconnue » alors que c'est le pont qui manque.
        domicile = self.config.corpus_id(par_role["home"])
        exterieur = self.config.corpus_id(par_role["away"])
        non_ponte = [par_role[r] for r, c in (("home", domicile), ("away", exterieur))
                     if c is None]
        if non_ponte:
            return refus(
                PricingStatus.MODEL_DOMAIN_MISMATCH,
                f"aucune correspondance dans l'annuaire du corpus pour {non_ponte}")
        inconnues = [t for t in (domicile, exterieur) if t not in connues]
        if inconnues:
            return refus(
                PricingStatus.MODEL_DOMAIN_MISMATCH,
                f"aucune rencontre dans le corpus pour {inconnues} : le modèle "
                "n'a jamais observé ce(s) participant(s)")

        prediction = notes.predict(domicile, exterieur)
        if prediction is None:
            return refus(PricingStatus.DATA_NOT_AVAILABLE,
                         "notes ou dispersion insuffisantes pour ces participants")

        distribution = LOIS[self.config.law](prediction)
        probabilites = self._issues(family, parameters, distribution,
                                    context.get("roles"))
        if not probabilites:
            return refus(PricingStatus.UNSUPPORTED,
                         f"famille non projetable : {family.value}")

        return MarketPricing(
            event_id=event_id, sport=self.sport, family=family,
            parameters=dict(parameters), context={},
            status=PricingStatus.PRICED,
            selections=tuple(
                PricedSelection(selection=nom, model_probability=p, fair_probability=p,
                                probability_low=self._borne_basse(family, parameters, p))
                for nom, p in probabilites.items()),
            model_name=self.model_name,
            model_version=self._version(family),
            maturity=self._maturite(family),
            calibration_status="EXPERIMENTAL",
            data_quality=self._qualite(prediction),
            freshness=None,                       # NON MESURÉE — jamais 0
            point_in_time=point_in_time,
            probability_origin=f"{self.config.model_version}:score:{event_id}",
            abstention_reasons=(
                f"espérance de marge {prediction.margin_mean:+.2f} ± "
                f"{prediction.margin_sigma:.2f}, total {prediction.total_mean:.1f} ± "
                f"{prediction.total_sigma:.1f} (loi {self.config.law})",))

    # -- projections ----------------------------------------------------------
    @staticmethod
    def _issues(family: MarketFamily, parameters: Mapping, distribution,
                roles: Mapping | None = None) -> dict:
        if family is MarketFamily.TOTALS:
            over = distribution.p_total_superieur(float(parameters["line"]))
            return {"over": over, "under": 1.0 - over}
        if family is MarketFamily.HANDICAP:
            # `hcp` est le handicap appliqué au DOMICILE : le domicile couvre
            # quand sa marge dépasse −hcp. Le signe est celui mesuré sur 548
            # marchés réels, jamais celui qu'on suppose.
            handicap = float(parameters["handicap"])
            p_home = distribution.p_marge_superieure(-handicap)
            return {"home": p_home, "away": 1.0 - p_home}
        if family is MarketFamily.TEAM_TOTALS:
            # Le camp vient du `betType`, traduit en slot par la table mesurée,
            # puis en rôle par le résolveur. Jamais du libellé, qui nomme
            # l'ÉQUIPE et non le camp.
            camp = roles.get(parameters.get("side")) if roles else None
            if camp not in ("home", "away"):
                return {}
            over = distribution.p_camp_superieur(float(parameters["line"]), camp)
            return {"over": over, "under": 1.0 - over}
        return {}

    _ETIQUETTES = {MarketFamily.TOTALS: "totals", MarketFamily.HANDICAP: "spread",
                   MarketFamily.TEAM_TOTALS: "team_totals"}

    def _version(self, family: MarketFamily) -> str:
        return f"{self.sport}.score.{self._ETIQUETTES[family]}.normal.v0"

    def _maturite(self, family: MarketFamily) -> str:
        """Lue au ledger sous l'identité PROPRE de la capacité. Un marché de
        score n'hérite pas de la validation du moneyline du même sport."""
        from ..support_status import resolve_market_status
        return resolve_market_status(self.model_name, self._version(family)).value

    def _borne_basse(self, family: MarketFamily, parameters: Mapping, probabilite: float):
        from ..uncertainty import bins_for_capability
        tables = bins_for_capability(self._version(family))
        return tables.borne_basse(probabilite) if tables is not None else None

    @staticmethod
    def _qualite(prediction) -> float:
        """Complétude de l'historique derrière CETTE prédiction.

        Rapportée au nombre de rencontres antérieures des deux participants, la
        moins fournie faisant foi : une équipe à cinq matchs et une à cinq cents
        donnent une prédiction dont la partie faible commande. Plafonnée à 1.
        """
        return round(min(1.0, min(prediction.prior_games_home,
                                  prediction.prior_games_away) / 40.0), 3)
