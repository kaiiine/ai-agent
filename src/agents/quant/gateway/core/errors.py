"""Exceptions typées de la gateway.

Aucune exception non gérée ne doit remonter jusqu'à axon-quant (PRD §7) —
soit une CanonicalEnvelope (éventuellement stale=True), soit une de ces erreurs.
"""


class NoDataAvailableError(Exception):
    """Aucun provider n'a pu répondre et aucun snapshot n'existe dans le point_in_time_store."""
