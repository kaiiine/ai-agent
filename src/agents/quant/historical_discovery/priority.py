"""Où une donnée supplémentaire change réellement quelque chose.

Sans classement, l'effort suit ce qui est visible — le blocage du jour — et non
ce qui coûte le plus. Une compétition manquant onze évaluations et un sport
manquant tout un historique de qualifications ne méritent pas le même travail,
et l'ordre ne se devine pas : il se calcule.

UN GAIN N'EST PAS UNE PRIORITÉ SI ON N'A PAS LE DROIT DE LE PRENDRE. Une source
sans licence claire donne une probabilité de récupération NULLE, donc une
priorité nulle — quel que soit l'impact. Autrement le classement recommanderait
en tête exactement ce que §20 interdit d'intégrer, et l'interdit ne tiendrait
qu'à la discipline du lecteur. Ces cas sortent dans une liste distincte, `BLOQUÉ`,
qui dit ce qu'il faudrait débloquer plutôt que de les faire disparaître.

AUCUN SCORE OPAQUE. Le scalaire ne sert qu'à trier ; tous ses termes restent
lisibles. Un nombre seul empêcherait de contester le classement, et un classement
incontestable serait le plus sûr moyen de travailler longtemps au mauvais endroit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum

ZERO = Decimal("0")
UN = Decimal("1")


class PriorityBand(str, Enum):
    HAUTE = "HAUTE"
    MOYENNE = "MOYENNE"
    BASSE = "BASSE"
    BLOQUEE = "BLOQUEE"        # gain réel, mais aucune source licite


#: Poids des termes. Rangés ici, nommés, discutables — plutôt que dispersés dans
#: une formule. `readiness` domine : fermer un critère de maturité débloque un
#: modèle entier, là où gagner quelques évaluations n'améliore qu'une marge.
POIDS = {
    "predictions_perdues": Decimal("1.0"),
    "entites_affectees": Decimal("2.0"),
    "readiness": Decimal("400.0"),
}

#: Au-delà, l'effort réseau n'est plus un détail. Sert à AMORTIR le score, pas à
#: exclure : une source lente qui débloque un modèle reste prioritaire.
COUT_RESEAU_REFERENCE = Decimal("100")


@dataclass(frozen=True)
class HistoricalBackfillPriority:
    """Le classement d'un besoin, terme par terme.

    `recovery_probability` n'est pas une intuition : elle vient de la
    classification de la source la mieux placée (§5). Une source `USABLE` et
    déjà éprouvée vaut 1 ; une licence incertaine vaut 0.
    """

    need: object                                  # HistoricalDataNeed
    predictions_perdues: int
    coverage_gap: Decimal                         # écart au seuil, 0 si atteint
    sample_size_gap: int
    entites_affectees: int
    source_gratuite: bool
    cout_reseau_estime: int                       # requêtes/fichiers à récupérer
    recovery_probability: Decimal                 # [0,1], adossée à la classification
    ferme_un_critere_de_maturite: bool
    source_retenue: str = ""
    blockers: tuple[str, ...] = ()
    detail: dict = field(default_factory=dict)

    # ── Score ───────────────────────────────────────────────────────────────
    @property
    def gain_brut(self) -> Decimal:
        """Ce que la donnée rapporterait si on l'obtenait entièrement."""
        return (POIDS["predictions_perdues"] * Decimal(self.predictions_perdues)
                + POIDS["entites_affectees"] * Decimal(self.entites_affectees)
                + (POIDS["readiness"] if self.ferme_un_critere_de_maturite else ZERO))

    @property
    def amortissement_reseau(self) -> Decimal:
        """Un coût réseau élevé n'annule pas un gain, il le tempère."""
        cout = Decimal(max(0, self.cout_reseau_estime))
        return COUT_RESEAU_REFERENCE / (COUT_RESEAU_REFERENCE + cout)

    @property
    def score(self) -> Decimal:
        """Espérance de gain — le gain n'est compté que s'il est atteignable."""
        return (self.gain_brut * self.recovery_probability
                * self.amortissement_reseau).quantize(Decimal("0.0001"))

    @property
    def band(self) -> PriorityBand:
        if self.recovery_probability <= ZERO:
            # Gain réel, aucun moyen licite de le prendre : ce n'est pas « basse
            # priorité », c'est un blocage, et le nommer autrement le cacherait.
            return PriorityBand.BLOQUEE if self.gain_brut > ZERO else PriorityBand.BASSE
        if self.ferme_un_critere_de_maturite or self.score >= Decimal("100"):
            return PriorityBand.HAUTE
        if self.score >= Decimal("20"):
            return PriorityBand.MOYENNE
        return PriorityBand.BASSE

    def as_dict(self) -> dict:
        return {
            "sport": self.need.sport,
            "competition_id": self.need.competition_id,
            "reason": self.need.reason,
            "predictions_perdues": self.predictions_perdues,
            "coverage_gap": str(self.coverage_gap),
            "sample_size_gap": self.sample_size_gap,
            "entites_affectees": self.entites_affectees,
            "source_retenue": self.source_retenue,
            "source_gratuite": self.source_gratuite,
            "cout_reseau_estime": self.cout_reseau_estime,
            "recovery_probability": str(self.recovery_probability),
            "ferme_un_critere_de_maturite": self.ferme_un_critere_de_maturite,
            "gain_brut": str(self.gain_brut),
            "score": str(self.score),
            "band": self.band.value,
            "blockers": list(self.blockers),
            "detail": dict(self.detail),
        }


def probabilite_de_recuperation(capabilities) -> tuple[Decimal, str, tuple[str, ...]]:
    """`(probabilité, source retenue, blocages)` depuis les capacités candidates.

    Déterministe et grossière À DESSEIN. Une échelle fine suggérerait une
    précision qu'aucune mesure ne soutient ; ce qui compte est la frontière entre
    « on peut » et « on ne peut pas », et elle est nette.
    """
    routables = [c for c in capabilities if c.is_routable]
    if routables:
        meilleure = routables[0]
        return UN, meilleure.provider, ()
    if not capabilities:
        return ZERO, "", ("NO_SOURCE_KNOWN",)
    # Des sources existent mais aucune n'est utilisable : rendre les raisons,
    # car c'est la seule information actionnable qui reste.
    blocages: list[str] = []
    for c in capabilities:
        for b in c.classification.blockers:
            if b not in blocages:
                blocages.append(b)
    return ZERO, "", tuple(blocages)


def classer(priorites) -> tuple[HistoricalBackfillPriority, ...]:
    """Score décroissant. Les bloquées descendent en fin de liste sans être
    retirées : elles restent l'inventaire de ce qu'il faudrait débloquer."""
    return tuple(sorted(
        priorites,
        key=lambda p: (p.band is PriorityBand.BLOQUEE, -p.score, p.need.sport)))
