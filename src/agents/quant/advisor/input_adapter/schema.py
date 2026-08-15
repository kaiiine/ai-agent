"""Schéma d'entrée VERSIONNÉ de l'adaptateur (PRD §9, ADV-NFR-011).

`AdaptedEvaluation` est la traduction FIDÈLE d'UNE sélection évaluée par le
Betting Engine : mêmes nombres (proba, cote, EV/edge/no-vig déjà calculés par le
moteur), typés `Decimal`, jamais recalculés. Les champs DÉRIVÉS (candidate_id,
fair_odds, edge_mean/low, exposure_keys) ne sont PAS ici : ils appartiennent au
Candidate Generator (Lot 3).

Le versionnage (`schema_version` sur `AdaptedBatch`) isole le ranking/portfolio
des évolutions de noms/formats du moteur : un changement de contrat source est
absorbé ici, ou rejeté explicitement (cf. `errors.IncompatibleSchemaError`).

IMPORTANT — pas de versioning de source aujourd'hui : le Betting Engine n'émet
AUCUN `contract_version`. La compatibilité réelle est garantie STRUCTURELLEMENT
par l'adaptateur (champs obligatoires présents, `canonical_event` requis,
prédiction/décision par sélection, maturités connues, erreur explicite sur toute
forme incompatible), pas par une négociation de version source. `EXPECTED_ENGINE_SCHEMA`
n'est donc PAS une valeur émise par le moteur : c'est l'étiquette du schéma de
sortie que CET adaptateur attend. Le jour où le moteur exposera un vrai
`contract_version`, l'adaptateur pourra le comparer à cette étiquette."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

# Version du contrat d'entrée Advisor produit par l'adaptateur.
INPUT_SCHEMA_VERSION = "1"

# Étiquette du SCHÉMA DE SORTIE MOTEUR ATTENDU par cet adaptateur — l'attente de
# l'adaptateur, PAS une valeur émise par le moteur (qui n'en émet aucune). Sert
# uniquement à un appelant qui veut épingler le schéma attendu et échouer
# bruyamment si l'adaptateur est réécrit vers un schéma qu'il ne cible pas. La
# compatibilité de la sortie réelle du moteur est validée STRUCTURELLEMENT.
EXPECTED_ENGINE_SCHEMA = "betting-engine.live.v1"

# Maturités de modèle connues (miroir de `DataReadiness`, SANS `DEPRECATED` que
# la source n'émet jamais — cf. Lot 0 §4.2). Une valeur hors de cet ensemble =
# contrat source inconnu -> rejet, jamais mappée en silence.
KNOWN_MATURITIES = frozenset(
    {"SUPPORTED", "EXPERIMENTAL", "INSUFFICIENT_DATA", "UNSUPPORTED"}
)


@dataclass(frozen=True)
class AdaptedExplanation:
    """Explication de prédiction PRÉSERVÉE telle quelle (aucun warning supprimé).
    Les valeurs de features sont des quantités de modèle (diagnostic), non
    monétaires : conservées en `float`, hors du périmètre Decimal (ADV-NFR-010)."""

    top_features: tuple[tuple[str, float], ...]
    missing_features: frozenset[str]
    confidence_drivers: tuple[str, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class MarketProvenance:
    """D'où vient ce chiffre — la chaîne complète, du `betId` au modèle.

    Chaque champ répond à une question qu'on doit pouvoir poser d'une ligne
    affichée : quel marché du bookmaker ? quel type brut ? quelle famille
    canonique et quels paramètres ? quel modèle, et de quelle distribution ?

    AUCUN de ces champs n'entre dans un calcul. Ils existent pour que la
    provenance soit vérifiable plutôt que plausible — et parce qu'une chaîne qui
    évalue cinq familles au lieu d'une ne peut plus se relire de mémoire.

    `probability_origin` est le seul à avoir une conséquence : le portefeuille
    refuse de miser deux fois sur la même distribution (`CORRELATED_SAME_ORIGIN`).
    Il est donc DÉCLARÉ par le modèle, jamais déduit d'une ressemblance.
    """

    source_event_id: str | None = None
    bookmaker_market_id: str | None = None     # `betId` — None si la source n'en expose pas
    raw_bet_type: int | None = None            # betType : le seul discriminant de portée
    raw_bet_type_name: str | None = None
    market_family: str | None = None           # famille CANONIQUE (pas le libellé)
    parameters: tuple[tuple[str, str], ...] = ()
    model_name: str | None = None
    probability_origin: str | None = None
    #: Parts de règlement quand le pari n'est PAS binaire — un « remboursé si
    #: match nul » rend la mise sur un nul. `(issue, probabilité)`. Vide = WIN/LOSS
    #: pur. L'espérance affichée en dépend directement : la traiter comme binaire
    #: la surestime d'un facteur 1/(1−P(push)).
    settlement_shares: tuple[tuple[str, float], ...] = ()
    event_label: str | None = None


def _provenance_from_jsonable(d: dict | None) -> "MarketProvenance | None":
    """Provenance archivée -> objet. Absente des archives antérieures : un replay
    d'avant ce champ doit rester rejouable, donc `None` est une valeur normale."""
    if not d:
        return None
    return MarketProvenance(
        source_event_id=d.get("source_event_id"),
        bookmaker_market_id=d.get("bookmaker_market_id"),
        raw_bet_type=d.get("raw_bet_type"),
        raw_bet_type_name=d.get("raw_bet_type_name"),
        market_family=d.get("market_family"),
        parameters=tuple(tuple(p) for p in d.get("parameters") or ()),
        model_name=d.get("model_name"),
        probability_origin=d.get("probability_origin"),
        # Les probabilités sont archivées en chaîne canonique (`repr`) : les
        # relire en float restitue le MÊME nombre, sans arrondi intermédiaire.
        settlement_shares=tuple((str(issue), float(p))
                                for issue, p in d.get("settlement_shares") or ()),
        event_label=d.get("event_label"))


@dataclass(frozen=True)
class AdaptedEvaluation:
    """Une sélection évaluée, traduite fidèlement (une par home/draw/away)."""

    schema_version: str

    # Identité (propagée depuis CanonicalEvent / RawBookmakerEvent).
    event_id: str
    sport: str
    competition_id: str
    scheduled_at: datetime
    participant_ids: tuple[str, ...]

    # Instant d'OBSERVATION des cotes (côté bookmaker), = RawBookmakerEvent.fetched_at
    # (source de OddsSnapshot.observed_at). Distinct du decision_time Advisor :
    # c'est l'identité temporelle de l'OFFRE, pas de la requête (ADR-ADV-003).
    observed_at: datetime

    # Marché (market_id reconstruit via le builder canonique, jamais parallèle).
    bookmaker: str
    market_id: str
    market_type: str
    selection: str

    # Nombres du moteur -> Decimal, jamais recalculés.
    bookmaker_odds: Decimal
    fair_probability: Decimal
    probability_low: Decimal
    probability_high: Decimal
    uncertainty_status: str

    model_version: str
    model_maturity: str                 # = calibration_status, JAMAIS rehaussé
    data_quality: Decimal
    calibration_score: Decimal | None   # = model_reliability (None : calibration/ absent)
    freshness_score: Decimal | None     # None = FRESHNESS_UNKNOWN (Q1)
    liquidity_score: Decimal | None     # None : non exposé par la source

    # Métriques d'audit CALCULÉES PAR LE MOTEUR, seulement propagées (None si non évaluées).
    implied_probability_raw: Decimal | None
    no_vig_probability: Decimal | None
    edge: Decimal | None
    expected_value: Decimal | None

    is_boosted: bool
    decision: str                       # "ABSTAIN" en V1
    decision_reasons: tuple[str, ...]
    warnings: tuple[str, ...]           # union préservée résultat + explication
    explanation: AdaptedExplanation
    source_decision_id: str | None      # None tant qu'aucun id source réel (Q5)
    #: §9 — la chaîne de provenance du marché. `None` pour une évaluation dont la
    #: source ne l'a pas déclarée : jamais un objet vide, qui se lirait comme une
    #: provenance renseignée à blanc.
    provenance: MarketProvenance | None = None


@dataclass(frozen=True)
class SkippedEvaluation:
    """Événement scanné mais NON évaluable : tracé (id + statut + raison) pour
    que la couche recommandation produise NO_EVALUABLE_EVENTS / rejection_summary,
    sans fabriquer de candidat."""

    bookmaker_event_id: str
    event_id: str | None
    status: str
    reason: str


@dataclass(frozen=True)
class AdaptedBatch:
    """Sortie de l'adaptateur pour un `decision_time` : évaluations traduites +
    événements écartés (traçabilité), estampillé de la version de schéma."""

    schema_version: str
    decision_time: datetime
    evaluations: tuple[AdaptedEvaluation, ...]
    skipped: tuple[SkippedEvaluation, ...]

    def by_event(self) -> Mapping[str, tuple[AdaptedEvaluation, ...]]:
        out: dict[str, list[AdaptedEvaluation]] = {}
        for ev in self.evaluations:
            out.setdefault(ev.event_id, []).append(ev)
        return {k: tuple(v) for k, v in out.items()}


# ── Désérialisation typée (Lot 10 : requise pour le replay exact) ─────────────
def _dec(v):
    return None if v is None else Decimal(v)


def _dt(v):
    return datetime.fromisoformat(v)


def _explanation_from_jsonable(d: dict) -> AdaptedExplanation:
    return AdaptedExplanation(
        top_features=tuple((n, float(f)) for n, f in d["top_features"]),   # valeur diagnostique -> float
        missing_features=frozenset(d["missing_features"]),
        confidence_drivers=tuple(d["confidence_drivers"]),
        warnings=tuple(d["warnings"]))


def _evaluation_from_jsonable(d: dict) -> AdaptedEvaluation:
    return AdaptedEvaluation(
        schema_version=d["schema_version"], event_id=d["event_id"], sport=d["sport"],
        competition_id=d["competition_id"], scheduled_at=_dt(d["scheduled_at"]),
        participant_ids=tuple(d["participant_ids"]), observed_at=_dt(d["observed_at"]),
        bookmaker=d["bookmaker"], market_id=d["market_id"], market_type=d["market_type"],
        selection=d["selection"], bookmaker_odds=Decimal(d["bookmaker_odds"]),
        fair_probability=Decimal(d["fair_probability"]), probability_low=Decimal(d["probability_low"]),
        probability_high=Decimal(d["probability_high"]), uncertainty_status=d["uncertainty_status"],
        model_version=d["model_version"], model_maturity=d["model_maturity"],
        data_quality=Decimal(d["data_quality"]), calibration_score=_dec(d["calibration_score"]),
        freshness_score=_dec(d["freshness_score"]), liquidity_score=_dec(d["liquidity_score"]),
        implied_probability_raw=_dec(d["implied_probability_raw"]),
        no_vig_probability=_dec(d["no_vig_probability"]), edge=_dec(d["edge"]),
        expected_value=_dec(d["expected_value"]), is_boosted=d["is_boosted"], decision=d["decision"],
        decision_reasons=tuple(d["decision_reasons"]), warnings=tuple(d["warnings"]),
        explanation=_explanation_from_jsonable(d["explanation"]),
        source_decision_id=d["source_decision_id"],
        provenance=_provenance_from_jsonable(d.get("provenance")))


def adapted_batch_from_jsonable(d: dict) -> AdaptedBatch:
    return AdaptedBatch(
        schema_version=d["schema_version"], decision_time=_dt(d["decision_time"]),
        evaluations=tuple(_evaluation_from_jsonable(e) for e in d["evaluations"]),
        skipped=tuple(SkippedEvaluation(**s) for s in d["skipped"]))
