"""Contrat `SportModule` et registre des sports installés (PRD v2 §6).

Un module sportif regroupe, côté gateway : schéma canonique versionné,
normalizers par provider, validateur de payload, types d'entités, calculateurs
dérivés. `core/` n'importe jamais un module sportif concret — il passe toujours
par `get_sport_module(sport)`, ce qui garantit :
  - GW-FR-001 : ajouter un sport ne touche pas `core/`/`cache/`
  - GW-NFR-006 : un module défaillant n'interrompt pas les autres sports

Vague 0 : le registre est VIDE. Le module football y est enregistré à l'étape
C1 (`sports/football/module.py`). Additif ici : rien dans le pipeline n'appelle
encore `get_sport_module`.
"""

from __future__ import annotations
from typing import Protocol, runtime_checkable


class UnsupportedSportError(Exception):
    """Levée par `get_sport_module` quand le sport n'est pas installé — jamais None."""

    def __init__(self, sport: str):
        super().__init__(f"Sport non installé dans la gateway : {sport!r}")
        self.sport = sport


@runtime_checkable
class DerivedCalculator(Protocol):
    """Calculateur dérivé nommé et versionné : fonction pure des faits canoniques
    + une fenêtre temporelle (GW-FR-012). La signature d'appel est propre au sport
    (recent_form, standings_strength...)."""
    version: str


@runtime_checkable
class SportModule(Protocol):
    sport: str
    schema_version: str                          # version courante du schéma canonique du sport

    def supported_data_types(self) -> set[str]:
        """Sous-ensemble du vocabulaire §5.2 réellement modélisé par ce sport."""
        ...

    def normalizers(self) -> dict[str, object]:
        """{provider_name: ProviderNormalizer} — quel adaptateur convertit le
        RawProviderResponse de quel provider vers les faits canoniques du sport."""
        ...

    def validate_payload(self, payload: object, data_type: str) -> None:
        """Lève une exception typée si le payload ne respecte pas le schéma canonique
        courant du sport. Appelé avant toute écriture dans le point_in_time_store."""
        ...

    def entity_types(self) -> set[str]:
        """Types d'entités manipulés par ce sport : {"team"}, {"player", "pair"}..."""
        ...

    def derived_calculators(self) -> dict[str, DerivedCalculator]:
        """Datasets dérivés du sport (§5.3), nommés et versionnés."""
        ...

    def is_schema_compatible(self, stored_schema_version: str) -> bool:
        """Un snapshot stocké sous une ancienne version est-il lisible par le code
        courant ? Permet un refus explicite plutôt qu'une interprétation erronée."""
        ...


# Registre statique. Vide en Vague 0 ; peuplé sport par sport (football à C1).
SPORT_MODULES: dict[str, SportModule] = {}


def get_sport_module(sport: str) -> SportModule:
    """Retourne le module d'un sport installé, ou lève UnsupportedSportError.

    Jamais de None silencieux : un sport absent est une erreur explicite, isolée
    au sport demandé (GW-NFR-006)."""
    try:
        return SPORT_MODULES[sport]
    except KeyError:
        raise UnsupportedSportError(sport) from None
