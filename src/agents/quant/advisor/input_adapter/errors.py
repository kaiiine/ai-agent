"""Erreurs de l'adaptateur Betting Engine (ADV-FR-040, PRD §9).

L'adaptateur échoue TOUJOURS explicitement plutôt que de produire un input
corrompu silencieusement : une incompatibilité de schéma/contrat ou un champ
obligatoire manquant lève, jamais un remplissage par défaut (`0`, `""`, `None`
silencieux)."""

from __future__ import annotations


class AdapterError(Exception):
    """Base : toute défaillance de traduction Betting Engine -> input Advisor."""


class IncompatibleSchemaError(AdapterError):
    """Contrat source non reconnu : version de contrat inattendue, ou valeur
    d'énum (maturité/statut) que l'adaptateur ne sait pas mapper. On refuse
    plutôt que de deviner (jamais d'EXPERIMENTAL->SUPPORTED implicite)."""


class MissingRequiredFieldError(AdapterError):
    """Un champ requis par le contrat source est absent d'un résultat pourtant
    présenté comme évaluable (ex. `canonical_event` manquant, prédiction absente
    pour une sélection). Jamais comblé par une valeur par défaut."""
