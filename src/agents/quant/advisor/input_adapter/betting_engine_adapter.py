"""Adaptateur Betting Engine -> input Advisor (PRD §9).

UNIQUE frontière entre Advisor et le moteur. Il consomme la frontière de DOMAINE
`evaluate_live_batch` (JAMAIS `cli.py`), traduit chaque sélection évaluée en
`AdaptedEvaluation` (Decimal, versionné), et :

- reconstruit `market_id` UNIQUEMENT via le builder canonique `build_market_id`
  (aucun format d'identifiant parallèle) ;
- laisse `source_decision_id=None` tant que le moteur n'expose aucun id de
  décision réel (Q5) ;
- NE recalcule RIEN : proba, EV, edge, no-vig sont ceux du moteur, seulement
  typés Decimal et propagés ;
- ne rehausse jamais la maturité, ne supprime aucun warning.

Compatibilité — validation STRUCTURELLE, pas de version source : le moteur
n'émet aucun `contract_version`. L'adaptateur garantit la compatibilité en
validant la FORME de la sortie et en échouant explicitement (jamais de valeur
par défaut silencieuse) : `canonical_event` requis sur un EVALUATED, prédiction
ET décision présentes pour chaque sélection, champs numériques requis non
`None`, maturité dans l'ensemble connu. `expected_schema` n'est qu'un point
d'épinglage optionnel de l'étiquette attendue (cf. `schema.EXPECTED_ENGINE_SCHEMA`),
pas une négociation avec une version émise par le moteur.
"""

from __future__ import annotations

from decimal import Decimal

from src.agents.quant.betting_engine.bookmakers.market_canonicalizer import build_market_id
from src.agents.quant.betting_engine.bookmakers.protocol import RawBookmakerEvent
from src.agents.quant.betting_engine.live_batch import LiveEvaluationBatch, evaluate_live_batch
from src.agents.quant.betting_engine.live_evaluation import (
    LiveEvaluationResult,
    LiveEvaluationStatus,
)

from .errors import IncompatibleSchemaError, MissingRequiredFieldError
from .schema import (
    EXPECTED_ENGINE_SCHEMA,
    INPUT_SCHEMA_VERSION,
    KNOWN_MATURITIES,
    AdaptedBatch,
    AdaptedEvaluation,
    AdaptedExplanation,
    MarketProvenance,
    SkippedEvaluation,
)


def _to_decimal(value: float, field: str) -> Decimal:
    """float du moteur -> Decimal via `str` (aucun artefact binaire). Ne
    recalcule rien : conversion de type seulement."""
    if value is None:
        raise MissingRequiredFieldError(f"champ numérique requis manquant : {field}")
    return Decimal(str(value))


def _opt_decimal(value: float | None) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def _maturity(prediction) -> str:
    """Maturité du modèle telle quelle — JAMAIS rehaussée. Une valeur hors du
    contrat connu est refusée (jamais mappée en silence)."""
    status = prediction.calibration_status
    value = getattr(status, "value", status)
    if value not in KNOWN_MATURITIES:
        raise IncompatibleSchemaError(f"maturité de modèle inconnue : {value!r}")
    return value


def _merge_warnings(*sources) -> tuple[str, ...]:
    """Union préservant l'ordre, AUCUN warning supprimé (dédup exacte seulement)."""
    out: list[str] = []
    for source in sources:
        for w in source:
            if w not in out:
                out.append(w)
    return tuple(out)


def _adapt_selection(
    raw_event: RawBookmakerEvent, canonical_event, prediction, decision, result_warnings,
    freshness_score, probability_origin: str | None = None,
) -> AdaptedEvaluation:
    market_id = build_market_id(raw_event.bookmaker, canonical_event.event_id, prediction.market_type)
    exp = prediction.explanation
    provenance = MarketProvenance(
        source_event_id=raw_event.bookmaker_event_id,
        market_family=prediction.market_type,
        model_name=getattr(prediction, "model_name", None),
        # DÉCLARÉE par le moteur : le 1X2 et les marchés dérivés d'un même
        # événement lisent la même matrice de scores. Sans cette trace, le
        # portefeuille les traiterait comme des paris indépendants.
        probability_origin=probability_origin,
        event_label=f"{raw_event.slot_1_name} - {raw_event.slot_2_name}")
    return AdaptedEvaluation(
        schema_version=INPUT_SCHEMA_VERSION,
        event_id=canonical_event.event_id,
        sport=canonical_event.sport,
        competition_id=canonical_event.competition_id,
        scheduled_at=canonical_event.scheduled_at,
        participant_ids=tuple(p.canonical_id for p in canonical_event.participants),
        observed_at=raw_event.fetched_at,          # instant d'observation des cotes (bookmaker)
        bookmaker=raw_event.bookmaker,
        market_id=market_id,
        market_type=prediction.market_type,
        selection=prediction.selection,
        bookmaker_odds=_to_decimal(decision.bookmaker_odds, "bookmaker_odds"),
        fair_probability=_to_decimal(prediction.fair_probability, "fair_probability"),
        probability_low=_to_decimal(prediction.probability_low, "probability_low"),
        probability_high=_to_decimal(prediction.probability_high, "probability_high"),
        uncertainty_status=prediction.uncertainty_status.value,
        model_version=prediction.model_version,
        model_maturity=_maturity(prediction),
        data_quality=_to_decimal(prediction.data_quality, "data_quality"),
        calibration_score=_opt_decimal(decision.model_reliability),
        # Fraîcheur MESURÉE par la Gateway et propagée par le BE (result.freshness_score) ;
        # None = non mesurable (FRESHNESS_UNKNOWN), jamais 0. Décidé en aval par l'Advisor.
        freshness_score=_opt_decimal(freshness_score),
        liquidity_score=None,               # non exposé par la source — jamais 0
        implied_probability_raw=_opt_decimal(decision.implied_probability_raw),
        no_vig_probability=_opt_decimal(decision.no_vig_probability),
        edge=_opt_decimal(decision.edge),
        expected_value=_opt_decimal(decision.expected_value),
        # is_boosted N'EST PAS un inconnu forcé à False : le value_engine n'atteint
        # EVALUATED que pour une cote STANDARD (une offre boostée -> NOT_EVALUATED +
        # UNSUPPORTED_ODDS_TYPE). Ce flag reflète donc la détection réelle du moteur ;
        # False sur un EVALUATED est un fait vérifié.
        is_boosted="UNSUPPORTED_ODDS_TYPE" in decision.reasons,
        decision=decision.decision,
        decision_reasons=tuple(decision.reasons),
        warnings=_merge_warnings(result_warnings, exp.warnings),
        explanation=AdaptedExplanation(
            top_features=tuple((name, val) for name, val in exp.top_features),
            missing_features=frozenset(exp.missing_features),
            confidence_drivers=tuple(exp.confidence_drivers),
            warnings=tuple(exp.warnings),
        ),
        source_decision_id=None,            # aucun id source réel (Q5) — jamais inventé
        provenance=provenance,
    )


#: Statut d'incertitude quand la borne basse a été MESURÉE. Repris du vocabulaire
#: du moteur ; l'adaptateur ne l'invente pas, il le déduit de la présence d'une
#: borne — et une borne absente reste `NOT_ESTIMATED`, jamais comblée.
_ESTIMATED, _NOT_ESTIMATED = "ESTIMATED", "NOT_ESTIMATED"


def _adapt_priced_selection(
    raw_event: RawBookmakerEvent, canonical_event, marche, selection,
    *, result_warnings, contract: str, freshness_score,
) -> AdaptedEvaluation | None:
    """Une issue d'un marché dérivé -> évaluation adaptée, ou rien.

    RIEN, et c'est le point important, quand la borne basse n'est pas mesurée
    (§5) : un candidat sans borne entrerait dans le classement PRUDENT avec sa
    probabilité centrale déguisée en minorant. Il reste visible dans la revue
    détaillée, classé `NOT_COMPARABLE` avec son motif — ce qui est une
    information, alors qu'un rang usurpé n'en est pas une.
    """
    if selection.probability_low is None or selection.bookmaker_odds is None:
        return None
    # Sans dévigorisation, pas de candidat : la marge ne se retire que sur un
    # marché COMPLET, et 1/cote n'est pas une probabilité de marché. Comparer une
    # probabilité de modèle à une implicite brute fabriquerait un edge négatif de
    # l'ordre de la marge — soit l'ordre de grandeur de ce qu'on cherche.
    if selection.vig_adjusted_probability is None:
        return None

    prix, obs = marche.pricing, marche.row.observation
    market_id = build_market_id(raw_event.bookmaker, canonical_event.event_id, contract)
    return AdaptedEvaluation(
        schema_version=INPUT_SCHEMA_VERSION,
        event_id=canonical_event.event_id,
        sport=canonical_event.sport,
        competition_id=canonical_event.competition_id,
        scheduled_at=canonical_event.scheduled_at,
        participant_ids=tuple(p.canonical_id for p in canonical_event.participants),
        observed_at=raw_event.fetched_at,
        bookmaker=raw_event.bookmaker,
        market_id=market_id,
        # L'identité ÉCONOMIQUE complète du contrat, la même que celle sous
        # laquelle la CLV apparie : « TOTALS(line=2.5) », jamais « TOTALS ».
        # Sans la ligne, deux paris différents partageraient une exposition.
        market_type=contract,
        selection=selection.selection,
        bookmaker_odds=_to_decimal(selection.bookmaker_odds, "bookmaker_odds"),
        fair_probability=_to_decimal(selection.fair_probability, "fair_probability"),
        probability_low=_to_decimal(selection.probability_low, "probability_low"),
        # Aucune borne HAUTE n'est mesurée : on répète le point, comme le font
        # les six modèles qui bornent déjà. `low <= fair <= high` reste vrai, et
        # rien n'est annoncé au-dessus de l'estimation.
        probability_high=_to_decimal(selection.fair_probability, "probability_high"),
        uncertainty_status=_ESTIMATED,
        model_version=prix.model_version,
        model_maturity=_maturite_de(prix.maturity),
        data_quality=_to_decimal(prix.data_quality, "data_quality"),
        calibration_score=None,             # non SUPPORTED : aucune fiabilité exposée
        # La MÊME fraîcheur de DONNÉES que le marché « qui gagne » du même
        # événement : ces marchés sortent des mêmes features. Ce n'est pas l'âge
        # de la cote — celui-là se mesure à la fin de l'acquisition, ailleurs.
        freshness_score=_opt_decimal(freshness_score),
        liquidity_score=None,
        implied_probability_raw=_opt_decimal(selection.implied_probability),
        no_vig_probability=_opt_decimal(selection.vig_adjusted_probability),
        edge=_opt_decimal(selection.edge),
        expected_value=_opt_decimal(selection.expected_value),
        is_boosted=False,
        decision="ABSTAIN",                 # cap dur BE-FR-011 : non SUPPORTED
        decision_reasons=("MODEL_NOT_SUPPORTED",),
        warnings=_merge_warnings(result_warnings, prix.abstention_reasons),
        explanation=AdaptedExplanation(
            top_features=(), missing_features=frozenset(),
            confidence_drivers=(f"marché dérivé de {prix.probability_origin}",),
            warnings=tuple(prix.abstention_reasons)),
        source_decision_id=None,
        provenance=MarketProvenance(
            source_event_id=obs.source_event_id,
            bookmaker_market_id=obs.market_source_id,
            raw_bet_type=obs.bet_type,
            raw_bet_type_name=obs.bet_type_name,
            market_family=prix.family.value,
            parameters=tuple(sorted((str(k), str(v)) for k, v in prix.parameters.items()
                                    if k != "source_family_id")),
            model_name=prix.model_name,
            probability_origin=prix.probability_origin,
            settlement_shares=tuple((p.settlement.value, float(p.probability))
                                    for p in selection.settlement_shares),
            event_label=obs.event_label),
    )


def _maturite_de(valeur) -> str:
    """Maturité du ledger, telle quelle. Une valeur hors contrat est refusée —
    jamais mappée en silence vers la plus permissive."""
    lue = getattr(valeur, "value", valeur)
    if lue not in KNOWN_MATURITIES:
        raise IncompatibleSchemaError(f"maturité de modèle inconnue : {lue!r}")
    return lue


def adapt_priced_markets(
    raw_event: RawBookmakerEvent, result: LiveEvaluationResult,
) -> list[AdaptedEvaluation]:
    """Les marchés dérivés d'un événement -> évaluations adaptées.

    Ne touche à rien du chemin historique : ce sont des marchés que celui-ci
    n'évaluait pas du tout. Un marché non pricé ne produit AUCUNE évaluation —
    son motif vit dans l'entonnoir, pas dans une ligne à zéro.
    """
    from src.agents.quant.betting_engine.clv.contract import identite_contrat

    if result.canonical_event is None:
        return []
    sorties: list[AdaptedEvaluation] = []
    for marche in result.priced_markets:
        if not marche.priced:
            continue
        contrat = identite_contrat(marche.pricing.family, marche.pricing.parameters)
        for selection in marche.pricing.selections:
            adaptee = _adapt_priced_selection(
                raw_event, result.canonical_event, marche, selection,
                result_warnings=result.warnings, contract=contrat,
                freshness_score=result.freshness_score)
            if adaptee is not None:
                sorties.append(adaptee)
    return sorties


def adapt_result(
    raw_event: RawBookmakerEvent, result: LiveEvaluationResult,
) -> tuple[list[AdaptedEvaluation], SkippedEvaluation | None]:
    """Traduit UN résultat. EVALUATED -> une `AdaptedEvaluation` par sélection ;
    sinon -> un `SkippedEvaluation` tracé (aucun candidat fabriqué)."""
    if result.status is not LiveEvaluationStatus.EVALUATED:
        return [], SkippedEvaluation(
            bookmaker_event_id=result.bookmaker_event_id,
            event_id=result.canonical_event.event_id if result.canonical_event else None,
            status=result.status.value, reason=result.reason,
        )

    if result.canonical_event is None:
        raise MissingRequiredFieldError(
            f"résultat EVALUATED sans canonical_event ({result.bookmaker_event_id})")

    # SCHÉMA-DRIVEN (§3) : les sélections viennent du résultat (2-way OU 3-way), jamais
    # d'un home/draw/away codé en dur — sinon un marché 2-way (basket/baseball/NFL/volley)
    # ferait échouer l'adaptation sur un « draw » inexistant.
    decisions = {d.selection: d for d in result.decisions}
    selections = tuple(d.selection for d in result.decisions)
    if not selections:
        raise MissingRequiredFieldError(
            f"résultat EVALUATED sans sélection ({result.bookmaker_event_id})")
    evaluations: list[AdaptedEvaluation] = []
    for sel in selections:
        prediction = result.predictions.get(sel)
        decision = decisions.get(sel)
        if prediction is None or decision is None:
            raise MissingRequiredFieldError(
                f"sélection « {sel} » absente d'un résultat EVALUATED "
                f"({result.bookmaker_event_id})")
        evaluations.append(
            _adapt_selection(raw_event, result.canonical_event, prediction, decision,
                             result.warnings, result.freshness_score,
                             getattr(result, "probability_origin", None)))
    # Les AUTRES marchés de l'événement — additif. Le marché « qui gagne » n'est
    # jamais repris ici : le moteur l'a retiré en amont, et un doublon serait une
    # opportunité comptée deux fois.
    evaluations.extend(adapt_priced_markets(raw_event, result))
    return evaluations, None


def adapt_live_batch(
    batch: LiveEvaluationBatch, *, expected_schema: str = EXPECTED_ENGINE_SCHEMA,
) -> AdaptedBatch:
    """Traduit un batch complet pour son `decision_time`. `expected_schema`
    permet à un appelant d'ÉPINGLER l'étiquette de schéma que l'adaptateur cible
    (défense contre une réécriture) — ce n'est PAS une version émise par le
    moteur ; la compatibilité de la sortie réelle est validée structurellement
    par `adapt_result`."""
    if expected_schema != EXPECTED_ENGINE_SCHEMA:
        raise IncompatibleSchemaError(
            f"schéma moteur attendu non supporté : {expected_schema!r} "
            f"(cet adaptateur cible {EXPECTED_ENGINE_SCHEMA!r})")

    evaluations: list[AdaptedEvaluation] = []
    skipped: list[SkippedEvaluation] = []
    for raw_event, result in batch.results:
        adapted, skip = adapt_result(raw_event, result)
        evaluations.extend(adapted)
        if skip is not None:
            skipped.append(skip)

    return AdaptedBatch(
        schema_version=INPUT_SCHEMA_VERSION,
        decision_time=batch.decision_time,
        evaluations=tuple(evaluations),
        skipped=tuple(skipped),
    )


def load_and_adapt(
    connector, *, sports_gateway, event_resolver,
    expected_schema: str = EXPECTED_ENGINE_SCHEMA, **batch_kwargs,
) -> AdaptedBatch:
    """Charge les évaluations via la frontière de DOMAINE `evaluate_live_batch`
    (jamais le CLI) puis les traduit. Seul point qui déclenche le scan+évaluation."""
    batch = evaluate_live_batch(
        connector, sports_gateway=sports_gateway, event_resolver=event_resolver, **batch_kwargs)
    return adapt_live_batch(batch, expected_schema=expected_schema)
