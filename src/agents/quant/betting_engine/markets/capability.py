"""Troisième étape : **vérifier la capacité** — reconnaître ≠ savoir prédire.

Un marché peut être parfaitement identifié, avec sa famille et ses paramètres,
sans qu'AXON ait la moindre légitimité à conseiller un pari dessus. Ce module
tient la frontière, et il la tient dans les deux sens : il refuse d'évaluer ce
qu'aucun modèle ne couvre, et il refuse qu'un modèle existant soit appliqué hors
de son domaine.

LE SECOND REFUS EST LE MOINS ÉVIDENT ET LE PLUS IMPORTANT. Les sept modèles
validés prédisent le vainqueur de la RENCONTRE ENTIÈRE. Un marché « Mi-temps -
Résultat » a exactement la même forme canonique — `MATCH_WINNER`, trois issues —
et un registre indexé sur le seul couple (sport, famille) le lui donnerait sans
broncher. Il produirait alors une probabilité de fin de match présentée comme
une probabilité de mi-temps : une prédiction fausse, et invisible, parce que
tout le reste de la chaîne serait cohérent.

La résolution prend donc un CONTEXTE, et une capacité déclare ce qu'elle accepte.
Aucun `if sport == ... and market == ...` : une capacité est une donnée, et en
ajouter une ne demande pas de toucher à la résolution.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import Enum

from ..sports.model_registry import BY_WINAMAX_SPORT_ID, ValidatedSportModel
from .families import MarketFamily
from .observation import CLES_DE_PORTEE, CLES_DE_SUJET


class CapabilityStatus(str, Enum):
    """Ce qu'AXON peut faire de ce marché — jamais mélangé à ce qu'il en comprend."""

    MODEL_AVAILABLE = "MODEL_AVAILABLE"          # un modèle validé couvre ce marché ET ce contexte
    MODEL_NOT_AVAILABLE = "MODEL_NOT_AVAILABLE"  # famille reconnue, AUCUN modèle pour ce (sport, famille)
    #: Un modèle existe pour cette famille et ce sport, mais pas pour CE
    #: contexte : mi-temps, période, équipe, joueur, ligne rejetée. Distinct de
    #: `MODEL_NOT_AVAILABLE` — ici on sait exactement ce qui manque, et c'est une
    #: portée, pas un modèle.
    MODEL_CONTEXT_MISMATCH = "MODEL_CONTEXT_MISMATCH"
    DATA_NOT_AVAILABLE = "DATA_NOT_AVAILABLE"    # modèle existant, données absentes pour CET événement
    UNSUPPORTED = "UNSUPPORTED"                  # famille non démontrée : rien à modéliser


@dataclass(frozen=True)
class ModelCapability:
    """Ce qu'un modèle déclare savoir traiter.

    `accepts` reçoit les paramètres canoniques du marché et rend un booléen. Un
    prédicat plutôt qu'une liste de clés : une capacité future pourra accepter
    « les totaux de ligne entière uniquement », ce qu'aucune énumération de clés
    n'exprimerait.
    """

    winamax_sport_id: int
    family: MarketFamily
    model_name: str
    model_version: str
    methodology: str
    accepts: Callable[[Mapping], bool]
    domain: str = ""          # description lisible du domaine accepté


@dataclass(frozen=True)
class CapabilityResolution:
    status: CapabilityStatus
    capability: ModelCapability | None = None
    maturity: str | None = None
    reason: str = ""
    #: Capacités qui couvrent la famille mais REFUSENT ce contexte. Sans elles,
    #: « aucun modèle » se lit « ce marché n'intéresse personne », alors que la
    #: bonne lecture est « il en faudrait un pour cette portée-là ».
    rejected_by: tuple[str, ...] = field(default_factory=tuple)


def _plein_match(parametres: Mapping) -> bool:
    """La rencontre ENTIÈRE, et son résultat global.

    Refuse toute portée (mi-temps, set, quart-temps, manche, jeu) et tout sujet
    (joueur, duo) : un modèle de vainqueur de match ne dit rien d'un joueur
    particulier ni d'une période. Le refus est structurel — il ne dépend d'aucune
    liste de libellés, seulement de la présence d'une clé de restriction.
    """
    return not any(cle in parametres for cle in (*CLES_DE_PORTEE, *CLES_DE_SUJET))


def _capacites_des_modeles_valides() -> tuple[ModelCapability, ...]:
    """Le registre dérive de `VALIDATED_MODELS` — jamais une seconde liste.

    Dupliquer la table des modèles ferait diverger « ce qui est validé » et « ce
    qu'on accepte d'évaluer » ; c'est la sorte d'écart qui ne se voit qu'une fois
    la mauvaise réponse partie.
    """
    capacites = []
    for sport_id, modele in sorted(BY_WINAMAX_SPORT_ID.items()):
        assert isinstance(modele, ValidatedSportModel)
        if modele.market_type != "MATCH_WINNER":       # aucun aujourd'hui, mais la
            continue                                   # règle ne suppose pas le contraire
        capacites.append(ModelCapability(
            winamax_sport_id=sport_id,
            family=MarketFamily.MATCH_WINNER,
            model_name=modele.model_name,
            model_version=modele.model_version,
            methodology=modele.methodology,
            accepts=_plein_match,
            domain="rencontre entière, sans restriction de période ni de sujet"))
    return tuple(capacites)


#: `betType` du total de buts de la RENCONTRE en football, observé sur 60 marchés
#: et 6 compétitions. Les totaux d'ÉQUIPE (2615, 2680) et de MI-TEMPS (2394, 2531,
#: 2801) portent la même famille canonique et les mêmes paramètres structurés :
#: leur sujet n'existe que dans le libellé. Sans cette clé, « Nombre de buts de
#: Chicago Fire » serait pricé avec la loi du total du match — une probabilité
#: fausse, sur un marché parfaitement bien lu.
BET_TYPE_TOTAL_MATCH_FOOTBALL = 2749

#: `betType` du marché de la RENCONTRE ENTIÈRE, par famille, en football.
#: Chacun est mesuré sur la capture réelle ; tout autre `betType` de la même
#: famille est une AUTRE portée, et sera refusé en `MODEL_CONTEXT_MISMATCH`.
#:
#: Ce tableau existe parce que la portée n'est PAS dans les paramètres. Mesuré :
#: « Mi-temps - Vainqueur (remboursé si match nul) » (betType 3439) ne porte
#: aucun `periodnr` — la mi-temps n'apparaît que dans le libellé. Idem pour
#: « Mi-temps - Score exact » (3046), « Mi-temps - Double chance » (3403),
#: « Mi-temps - Résultat » (3598) et « Mi-temps - Nombre de buts » (2531).
#: Se fier au libellé pour trancher la portée reviendrait à pricer une mi-temps
#: avec la loi du match entier — et rien ne le signalerait.
BET_TYPES_FOOTBALL_RENCONTRE: dict = {
    MarketFamily.TOTALS: BET_TYPE_TOTAL_MATCH_FOOTBALL,   # 2749 — « Nombre de buts »
    MarketFamily.DOUBLE_CHANCE: 3072,                     # « Double chance »
    MarketFamily.DRAW_NO_BET: 3535,                       # « Vainqueur (remboursé si match nul) »
    MarketFamily.EXACT_SCORE: 2643,                       # « Score exact »
}

#: Les MÊMES familles à une autre portée. Listés pour que le refus soit explicite
#: et vérifiable, jamais implicite : 3439 mi-temps DNB, 3046 mi-temps score exact,
#: 3403 mi-temps double chance, 3598 mi-temps résultat, 2531 mi-temps total,
#: 2615/2680 totaux d'ÉQUIPE. Aucun ne porte de paramètre de portée.
BET_TYPES_FOOTBALL_AUTRE_PORTEE = frozenset({3439, 3046, 3403, 3598, 2531, 2615, 2680})

#: Lignes REJETÉES par la validation walk-forward, ligne par ligne, sur 7 397
#: rencontres (7 championnats × 3 saisons).
#:
#: `0.5` — Brier 0,1208 contre 0,1206 pour la fréquence point-in-time : le critère
#: `must_beat_baselines` échoue. Sur un marché où « au moins un but » se réalise
#: près de neuf fois sur dix, le modèle n'apporte rien qu'un compteur ne donne
#: déjà. La probabilité n'est pas absurde — elle est inutile, et une probabilité
#: inutile présentée comme un edge est une invitation à parier sans raison.
#:
#: Le rejet est PAR LIGNE et non par famille : les cinq autres demi-lignes
#: battent leur baseline. Rejeter la famille entière pour une de ses lignes
#: coûterait cinq marchés valides ; en garder une invalidée en coûterait la
#: confiance.
LIGNES_TOTALS_REJETEES: frozenset[float] = frozenset({0.5})


def _rencontre_entiere_football(famille, parametres: Mapping) -> bool:
    """Le marché est-il CELUI de la rencontre entière pour cette famille ?

    Deux conditions, et la première est la seule qui protège vraiment : le
    `betType` doit être exactement celui mesuré pour ce marché. La seconde
    (absence de clé de portée ou de sujet) attrape les cas où la source, elle,
    structure la restriction.
    """
    if parametres.get("source_family_id") != BET_TYPES_FOOTBALL_RENCONTRE.get(famille):
        return False
    return _plein_match(parametres)


def _total_football_demi_ligne(parametres: Mapping) -> bool:
    """Plus/Moins football, rencontre entière, DEMI-LIGNE non rejetée.

    La demi-ligne n'est pas une préférence de style : sur une ligne entière, un
    total exactement égal à la ligne a un règlement que le payload ne démontre
    pas (remboursement ? perte ?). 28 des 60 totaux football observés sont dans
    ce cas. Le calcul de probabilité serait le même ; c'est l'économie du pari
    qui serait fausse, et invisible.
    """
    if not _rencontre_entiere_football(MarketFamily.TOTALS, parametres):
        return False
    ligne = parametres.get("line")
    if not isinstance(ligne, (int, float)) or float(ligne) % 1 != 0.5:
        return False
    return float(ligne) not in LIGNES_TOTALS_REJETEES


#: Lignes de total VALIDÉES en walk-forward (7 397 rencontres). `0.5` en est
#: absente : elle est rejetée, cf. `LIGNES_TOTALS_REJETEES`.
LIGNES_TOTALS_VALIDEES: tuple[float, ...] = (1.5, 2.5, 3.5, 4.5, 5.5)


def _identite(famille: str) -> str:
    """L'identité de modèle d'une capacité — UNE PAR FAMILLE, UNE PAR LIGNE.

    Partager une version entre familles ferait partager leur maturité : promouvoir
    le Plus/Moins 2.5 promouvrait le score exact, qui n'a pas les mêmes chiffres.
    La ligne entre dans l'identité pour la même raison — 1.5 et 4.5 n'ont ni le
    même Brier, ni la même calibration, ni le même écart entre folds.
    """
    return f"football.{famille}.dixon_coles.v0"


def _capacite_football(famille, suffixe: str, accepte, domaine: str) -> ModelCapability:
    return ModelCapability(
        winamax_sport_id=1, family=famille,
        model_name=f"football_{suffixe}", model_version=_identite(suffixe),
        methodology="dixon_coles", accepts=accepte, domain=domaine)


def _capacites_derivees_football() -> list[ModelCapability]:
    """Les familles football dérivées de la matrice, chacune sous son identité.

    Toutes sont issues de la MÊME loi jointe et restent donc cohérentes entre
    elles ; elles ne partagent pour autant NI validation NI maturité. Chacune a
    été confrontée séparément à l'historique (§5), et chacune est lue séparément
    au ledger.
    """
    capacites = [
        _capacite_football(
            MarketFamily.DOUBLE_CHANCE, "double_chance",
            lambda p: _rencontre_entiere_football(MarketFamily.DOUBLE_CHANCE, p),
            "double chance, rencontre entière"),
        _capacite_football(
            MarketFamily.DRAW_NO_BET, "draw_no_bet",
            lambda p: _rencontre_entiere_football(MarketFamily.DRAW_NO_BET, p),
            "remboursé si match nul, rencontre entière"),
        _capacite_football(
            MarketFamily.EXACT_SCORE, "exact_score",
            lambda p: _rencontre_entiere_football(MarketFamily.EXACT_SCORE, p),
            "score exact, rencontre entière"),
    ]
    for ligne in LIGNES_TOTALS_VALIDEES:
        etiquette = f"totals_line_{str(ligne).replace('.', '_')}"
        capacites.append(ModelCapability(
            winamax_sport_id=1, family=MarketFamily.TOTALS,
            model_name="football_totals", model_version=_identite(etiquette),
            methodology="dixon_coles",
            accepts=(lambda p, l=ligne: _total_football_demi_ligne(p)
                     and float(p.get("line", -1)) == l),
            domain=f"total de buts, rencontre entière, ligne {ligne}"))
    return capacites


#: Registre EXTENSIBLE. Ajouter une famille = ajouter une capacité ici (ou
#: l'enregistrer à chaud), pas modifier `resolve_model`.
CAPABILITIES: list[ModelCapability] = (
    list(_capacites_des_modeles_valides()) + _capacites_derivees_football())


def register(capability: ModelCapability) -> None:
    """Déclare une capacité supplémentaire. Réservé au code de modèle : rien dans
    l'inventaire ne doit pouvoir s'auto-déclarer capable."""
    CAPABILITIES.append(capability)


def resolve_model(
    *,
    winamax_sport_id: int | None,
    family: MarketFamily,
    context: Mapping | None = None,
    capabilities: list[ModelCapability] | None = None,
) -> CapabilityResolution:
    """`(sport, famille, contexte)` -> capacité, ou l'explication de son absence."""
    parametres = dict(context or {})
    registre = CAPABILITIES if capabilities is None else capabilities

    if family is MarketFamily.UNMAPPED:
        return CapabilityResolution(
            CapabilityStatus.UNSUPPORTED,
            reason="famille non démontrée — il n'y a rien à modéliser tant que le "
                   "marché n'est pas canonicalisé")

    candidates = [c for c in registre
                  if c.winamax_sport_id == winamax_sport_id and c.family is family]
    if not candidates:
        return CapabilityResolution(
            CapabilityStatus.MODEL_NOT_AVAILABLE,
            reason=f"aucun modèle validé pour (sport_id={winamax_sport_id}, {family.value})")

    refusees: list[str] = []
    for capacite in candidates:
        if capacite.accepts(parametres):
            return CapabilityResolution(
                CapabilityStatus.MODEL_AVAILABLE, capacite,
                maturity=_maturite(capacite),
                reason=f"{capacite.model_name} couvre {capacite.domain}")
        refusees.append(f"{capacite.model_name} ({capacite.domain})")

    restrictions = ", ".join(
        f"{c}={parametres[c]}" for c in (*CLES_DE_PORTEE, *CLES_DE_SUJET) if c in parametres)
    detail = restrictions or f"betType={parametres.get('source_family_id')}"
    return CapabilityResolution(
        CapabilityStatus.MODEL_CONTEXT_MISMATCH,
        reason=(f"un modèle couvre ({family.value}) pour ce sport mais pas ce "
                f"contexte : {detail}"),
        rejected_by=tuple(refusees))


def _maturite(capacite: ModelCapability) -> str | None:
    """La maturité vient du ledger, sous l'identité PROPRE de la capacité.

    Interroger le ledger avec le modèle du sport ferait hériter chaque marché
    dérivé de la validation de son parent : le jour où le 1X2 football passerait
    SUPPORTED, le Plus/Moins dérivé le deviendrait aussi — sans qu'aucun total
    n'ait jamais été confronté à un résultat historique. C'est exactement la
    promotion par héritage que §5 interdit.
    """
    from ..support_status import resolve_market_status
    return resolve_market_status(capacite.model_name, capacite.model_version).value
