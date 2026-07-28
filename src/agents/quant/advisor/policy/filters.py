"""Filtres utilisateur (PRD §11.1 : user filters + bookmaker availability).

Whitelists (`allowed_*`) et blacklists (`excluded_*`) de la requête. Retourne le
PREMIER code de rejet applicable (ordre déterministe) ou `None`. Un `allowed_*`
à `None` = « pas de restriction » (jamais un rejet)."""

from __future__ import annotations

from ..domain.candidates import CandidateBet
from ..domain.requests import RecommendationRequest
from . import reason_codes


def user_filter_rejection(candidate: CandidateBet, request: RecommendationRequest) -> str | None:
    # Whitelists : si définies, le candidat doit y appartenir.
    if request.allowed_sports is not None and candidate.sport not in request.allowed_sports:
        return reason_codes.USER_FILTERED_SPORT
    if (request.allowed_competitions is not None
            and candidate.competition_id not in request.allowed_competitions):
        return reason_codes.USER_FILTERED_COMPETITION
    if (request.allowed_market_types is not None
            and candidate.market_type not in request.allowed_market_types):
        return reason_codes.USER_FILTERED_MARKET
    if (request.allowed_bookmakers is not None
            and candidate.bookmaker not in request.allowed_bookmakers):
        return reason_codes.USER_FILTERED_BOOKMAKER

    # Blacklists : si le candidat y figure, il est rejeté.
    if candidate.event_id in request.excluded_event_ids:
        return reason_codes.USER_EXCLUDED_EVENT
    if any(pid in request.excluded_participant_ids for pid in candidate.participant_ids):
        return reason_codes.USER_EXCLUDED_PARTICIPANT
    if candidate.market_type in request.excluded_market_types:
        return reason_codes.USER_FILTERED_MARKET

    return None
