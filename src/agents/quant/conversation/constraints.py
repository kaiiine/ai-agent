"""`UserBettingConstraints` — les contraintes de la demande, en state TYPÉ (§11-13).

Le dump montre le symptôme : l'utilisateur répond « tout me va, tous les sports
et toutes les compétitions », et le tour suivant repose la même question. La
réponse existait, mais uniquement comme du texte dans l'historique — donc à
re-comprendre à chaque tour, et re-comprise différemment.

Ici la réponse devient un objet. Il porte trois états distincts par champ, et
c'est cette distinction qui ferme la boucle de clarification :

    None          l'utilisateur ne s'est pas prononcé  -> clarification légitime
    ALL           il a dit « tous »                    -> ne plus jamais demander
    {"tennis"}    il a restreint                       -> filtrer, et ne pas élargir

Confondre les deux premiers, c'est reposer la question ; confondre les deux
derniers, c'est répondre du football à une demande d'ATP.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Any, Iterable

from .window import TimeWindow


class _All:
    """Sentinelle « tous » — distincte de « non précisé »."""

    _instance: "_All | None" = None

    def __new__(cls) -> "_All":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "ALL"

    def __reduce__(self):
        return (_All, ())


ALL = _All()

Scope = frozenset | _All | None


@dataclass(frozen=True)
class PromotionalBalance:
    """Solde promotionnel DÉCLARÉ — jamais valorisé ici.

    Un freebet n'est pas du cash : sa mise n'est pas rendue en cas de gain, sa
    cote minimale et son expiration conditionnent son usage. Tant qu'aucun
    contrat promotionnel canonique n'existe, ce solde est enregistré pour être
    RESTITUÉ à l'utilisateur, et exclu de la bankroll de sizing. Le valoriser
    demanderait une formule de mise promotionnelle — une décision money qui ne
    se prend pas par défaut.
    """

    amount: Decimal
    currency: str = "EUR"
    terms: str = "PROMOTION_TERMS_UNKNOWN"


@dataclass(frozen=True)
class UserBettingConstraints:
    """Contraintes accumulées d'un fil de conversation."""

    sports: Scope = None
    competitions: Scope = None
    markets: Scope = None
    time_window: TimeWindow | None = None
    allow_singles: bool = True
    allow_combos: bool = False
    bankroll: Decimal | None = None
    promotional_balances: tuple[PromotionalBalance, ...] = ()
    risk_profile: str = "balanced"
    #: Probabilité minimale souhaitée, telle que l'utilisateur l'a dite (« environ
    #: 90 % de chances »). N'est PAS un filtre : elle ordonne l'affichage de la
    #: revue et rien d'autre. Aucune mise n'en dépend, aucun seuil du moteur n'est
    #: touché — un candidat qui l'atteint reste non misable s'il l'était.
    #:
    #: Elle se compare à `probability_low`, la borne basse mesurée, JAMAIS à
    #: `fair_probability` : l'utilisateur qui dit « 90 % » demande une garantie,
    #: et une estimation ponctuelle n'en est pas une.
    probability_target: Decimal | None = None
    #: Objectif de cote / multiplicateur (« faire x2 », « entre 1,8 et 2,2 »).
    #: `TargetOddsPreference` ou None. Comme la préférence de probabilité, elle
    #: ORDONNE l'affichage et ne crée aucune recommandation.
    #:
    #: Elle est SUBORDONNÉE à la probabilité : une cote visée ne justifie jamais
    #: de descendre sous le seuil de probabilité demandé. Le rendu sépare donc
    #: « respecte les deux » de « respecte la probabilité seule » et de « proche
    #: de la cote seulement », plutôt que de les fondre en un classement unique
    #: où le prix rattraperait la prudence.
    target_odds: Any = None

    # ── Ce qui manque encore pour construire un contrat ────────────────────────
    def missing(self) -> tuple[str, ...]:
        """Les SEULS champs dont l'absence empêche de construire une demande.

        La liste est volontairement courte. Ni le sport, ni la compétition, ni le
        marché n'y figurent : leur absence a une réponse produit par défaut
        (« tout »), et demander à l'utilisateur de choisir ses matchs quand il
        demande justement qu'on les trouve pour lui inverse la demande.
        """
        return () if self.bankroll is not None and self.bankroll > 0 else ("bankroll",)

    def resolved_scope(self, field: str) -> frozenset[str] | None:
        """Portée effective : `None` (= aucun filtre côté Advisor) pour ALL comme
        pour non-précisé. La différence entre les deux ne concerne que la
        clarification, jamais le filtrage."""
        value = getattr(self, field)
        return None if value is None or isinstance(value, _All) else value

    def is_explicit(self, field: str) -> bool:
        """Vrai dès que l'utilisateur s'est prononcé — y compris pour dire
        « tous ». C'est ce booléen qui interdit de reposer la question."""
        return getattr(self, field) is not None

    def describe(self) -> dict[str, Any]:
        return {
            "sports": _scope_repr(self.sports),
            "competitions": _scope_repr(self.competitions),
            "markets": _scope_repr(self.markets),
            "time_window": self.time_window.describe() if self.time_window else None,
            "allow_singles": self.allow_singles,
            "allow_combos": self.allow_combos,
            "bankroll": None if self.bankroll is None else str(self.bankroll),
            "promotional_balances": [
                {"amount": str(p.amount), "currency": p.currency, "terms": p.terms}
                for p in self.promotional_balances
            ],
            "risk_profile": self.risk_profile,
            "probability_target": (None if self.probability_target is None
                                   else str(self.probability_target)),
            "target_odds": (None if self.target_odds is None
                            else self.target_odds.describe()),
        }


def _scope_repr(scope: Scope) -> Any:
    if scope is None:
        return None
    if isinstance(scope, _All):
        return "ALL"
    return sorted(scope)


def parse_scope(value: Any) -> Scope:
    """Traduit un argument d'outil en portée typée.

    `None` / absent            -> non précisé
    `"all"`, `"tous"`, `[]`    -> ALL
    `["tennis"]`               -> restriction

    Une liste vide vaut ALL et non « aucun sport » : personne ne demande une
    recommandation en excluant tous les sports, alors que « peu importe » se
    transmet naturellement comme une liste vide.
    """
    if value is None:
        return None
    if isinstance(value, _All):
        return value
    if isinstance(value, str):
        value = [value]
    items = [str(v).strip().lower() for v in value if str(v).strip()]
    if not items or any(v in ("all", "tous", "toutes", "*", "any", "peu importe") for v in items):
        return ALL
    return frozenset(items)


class _Effacer:
    """Sentinelle : « retire cette contrainte », par opposition à « rien dit ».

    Une conversation a besoin des deux. `None` hérite de la valeur précédente —
    c'est ce qui évite de reposer la question de la bankroll à chaque tour.
    `EFFACER` la retire, et c'est ce qui permet à « finalement, pas de seuil »
    d'annuler un « 90 % » dit deux tours plus tôt.
    """

    _instance: "_Effacer | None" = None

    def __new__(cls) -> "_Effacer":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "EFFACER"

    def __reduce__(self):
        return (_Effacer, ())


EFFACER = _Effacer()


def merge_constraints(
    previous: UserBettingConstraints | None,
    **updates: Any,
) -> UserBettingConstraints:
    """Fusionne un tour de conversation dans les contraintes accumulées.

    Règle unique : **un champ explicitement fourni REMPLACE, un champ absent est
    hérité.** C'est ce que veut dire une conversation — « tous les sports » puis
    « seulement du tennis ATP » donne du tennis ATP, pas leur union. Élargir
    silencieusement rendrait du football à une demande d'ATP ; oublier
    l'héritage reposerait la question de la bankroll à chaque tour.
    """
    base = previous or UserBettingConstraints()
    # `EFFACER` est une VALEUR, pas une absence. « pas de seuil » doit retirer un
    # seuil déjà posé ; traité comme None il aurait été confondu avec « rien dit »
    # et aurait laissé le seuil précédent en place. Mesuré en production :
    # l'utilisateur demandait « pas de seuil », le moteur continuait d'exiger 90 %.
    champs = {k: (None if v is EFFACER else v)
              for k, v in updates.items() if v is not None}
    return replace(base, **champs) if champs else base


def constraints_from_request(
    previous: UserBettingConstraints | None,
    *,
    sports: Any = None,
    competitions: Any = None,
    markets: Any = None,
    time_window: TimeWindow | None = None,
    bankroll: Decimal | None = None,
    promotional_balances: Iterable[PromotionalBalance] | None = None,
    allow_combos: bool | None = None,
    allow_singles: bool | None = None,
    risk_profile: str | None = None,
    probability_target: Decimal | None = None,
    target_odds: Any = None,
) -> UserBettingConstraints:
    """Point d'entrée unique : arguments bruts d'un tour -> state fusionné."""
    return merge_constraints(
        previous,
        target_odds=target_odds,
        sports=parse_scope(sports),
        competitions=parse_scope(competitions),
        markets=parse_scope(markets),
        time_window=time_window,
        bankroll=bankroll,
        probability_target=probability_target,
        promotional_balances=(None if promotional_balances is None
                              else tuple(promotional_balances)),
        allow_combos=allow_combos,
        allow_singles=allow_singles,
        risk_profile=risk_profile,
    )
