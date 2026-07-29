"""Identité d'audit déterministe (Lot 10 §9/§10).

`request_fingerprint` = hash du CONTENU MÉTIER de la requête, `request_id` EXCLU
(l'identité d'appel n'appartient pas au contenu logique) ; indépendant de
`created_at`, de l'ordre d'un Mapping, d'un chemin ou de l'environnement.

`audit_id` = hash déterministe de `(request_id, request_fingerprint)` : sépare
identité d'appel et contenu logique."""

from __future__ import annotations

import hashlib
import json

from ..domain import serialization
from ..domain.requests import RecommendationRequest


def request_fingerprint(request: RecommendationRequest) -> str:
    payload = serialization.to_jsonable(request)
    payload.pop("request_id", None)                  # exclut l'identité d'appel
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def audit_id(request_id: str, fingerprint: str) -> str:
    digest = hashlib.sha256(f"{request_id}|{fingerprint}".encode("utf-8")).hexdigest()
    return f"audit:{digest[:24]}"
