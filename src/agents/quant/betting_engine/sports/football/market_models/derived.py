"""Marchés football DÉRIVÉS de la matrice de scores Dixon-Coles.

UNE SEULE DISTRIBUTION, PLUSIEURS MARCHÉS. Le 1X2, le Plus/Moins, la double
chance, le remboursé-si-nul et le score exact ne sont pas cinq modèles : ce sont
cinq lectures de la même loi jointe P(x buts domicile, y buts extérieur). Les
dériver séparément produirait des probabilités qui se contredisent — un P(over
2.5) incompatible avec le P(home) du même match — et personne ne le verrait.

CE QUI EST DÉRIVÉ, ET POURQUOI C'EST DÉMONTRÉ

    MATCH_WINNER    x>y / x=y / x<y — inchangé, mêmes nombres que `OneXTwoModel`
    DOUBLE_CHANCE   unions du 1X2 ; codes source 9/10/11 stables sur 23 marchés
                    et 4 sports dans la capture
    DRAW_NO_BET     conditionnelle P(home | pas de nul) ; libellé source
                    « Vainqueur (remboursé si match nul) », codes 1/2 sur
                    68 marchés
    TOTALS          P(x+y > ligne) — la ligne vient du marché, jamais codée en dur
    BTTS            P(x≥1 et y≥1)
    EXACT_SCORE     la loi jointe elle-même ; la source expose une grille 6×6 ET
                    une issue « other », donc la troncature est un vrai résultat

CE QUI EST REFUSÉ, ET POURQUOI (§11)

    lignes ENTIÈRES     « Plus de 2 » avec un total de 2 exactement : remboursé ?
                        perdu ? Le payload ne le dit pas. 28 des 60 totaux
                        football observés sont dans ce cas — c'est trop pour le
                        deviner, et une règle inventée fausse l'EV, pas la
                        probabilité (le pire des deux : invisible).
    HANDICAP            même problème de règlement sur les lignes entières
                        (`hcp=0`, `hcp=-1` observés), ET le sujet du handicap
                        n'est nommé que dans le libellé (« Cruz Azul 0 »). Un
                        handicap attribué à la mauvaise équipe est une prédiction
                        exactement inversée.
    TEAM_TOTALS         la marginale est immédiate (P(x > ligne)), mais le sujet
                        (« Nombre de buts de Chicago Fire ») n'existe que dans le
                        libellé : aucun champ structuré ne le porte.
    marchés COMBINÉS    « Résultat et nombre de buts », « Double chance et les
                        deux équipes marquent » : calculables depuis la loi
                        jointe, mais leur règlement exact n'est pas démontré.

MASSE HORS GRILLE. `score_matrix` renormalise une grille 11×11 : ce que la loi
met au-delà de 10 buts est redistribué à l'intérieur, silencieusement. À des
intensités réalistes (λ≈1.5) cette masse vaut 6e-7 et ne change rien ; mais les
bornes de force admises (`STRENGTH_MAX=3`) autorisent λ≈13.5, où elle atteint
0.90. On la MESURE donc à chaque match, et on s'abstient au-delà du seuil.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime

from src.agents.quant.dixon_coles import (
    AWAY_FACTOR,
    HOME_ADVANTAGE,
    LEAGUE_AVG_GOALS,
    MAX_GOALS,
    _poisson_pmf,
)

from ....markets.families import MarketFamily
from ....markets.pricing import (
    MarketPricing,
    PricedSelection,
    PricingStatus,
    abstention,
)
from ....markets.observation import CLES_DE_PORTEE, CLES_DE_SUJET
from .one_x_two import OneXTwoModel

#: Masse tolérée hors de la grille de scores. Ce n'est PAS un seuil de décision
#: (ni EV, ni Kelly, ni maturité) : c'est la limite de validité numérique de la
#: troncature. À λ=1.5 la masse réelle vaut 6e-7 — quatre ordres de grandeur sous
#: la borne. Un match qui la dépasse a des intensités hors du domaine où cette
#: grille représente la loi ; on s'abstient plutôt que de pricer une distribution
#: renormalisée à l'aveugle.
MASSE_HORS_GRILLE_MAX = 1e-4

FAMILLES_DERIVEES = frozenset({
    MarketFamily.MATCH_WINNER,
    MarketFamily.TOTALS,
    MarketFamily.DOUBLE_CHANCE,
    MarketFamily.DRAW_NO_BET,
    MarketFamily.EXACT_SCORE,
})

#: BTTS est DÉRIVABLE et validé statistiquement (Brier 0,4973, ECE 0,0201), mais
#: il n'est PAS câblé : la capture ne contient aucun marché « les deux équipes
#: marquent » AUTONOME en football — seulement des combinés (« Résultat et les
#: deux équipes marquent ») et des variantes par tiers-temps au hockey. Câbler un
#: pricer pour un marché que le bookmaker n'expose pas produirait une capacité
#: qui ne rencontre jamais son marché, et un chiffre de couverture qui ment.

#: Familles supplémentaires exposées par ce pricer sous leur nom canonique
#: interne — elles n'existent pas encore comme `MarketFamily` parce qu'aucun
#: marché correspondant n'a été canonicalisé depuis la capture. Les dériver quand
#: même permet aux tests de cohérence de les confronter au 1X2.
SELECTIONS_DOUBLE_CHANCE = ("home_or_draw", "home_or_away", "draw_or_away")


def masse_hors_grille(lam: float, mu: float) -> float:
    """Ce que la loi place au-delà de la grille, AVANT renormalisation."""
    dedans = (sum(_poisson_pmf(x, lam) for x in range(MAX_GOALS + 1))
              * sum(_poisson_pmf(y, mu) for y in range(MAX_GOALS + 1)))
    return max(0.0, 1.0 - dedans)


def intensites(features, event) -> tuple[float, float]:
    """Les intensités λ (domicile) et μ (extérieur) — mêmes constantes que le
    noyau, jamais réajustées ici."""
    by_role = {p.role: p.canonical_id for p in event.participants}
    dom = features.participant_features[by_role["home"]]
    ext = features.participant_features[by_role["away"]]
    lam = (LEAGUE_AVG_GOALS * HOME_ADVANTAGE
           * dom["attack_strength"] * ext["defense_strength"])
    mu = (LEAGUE_AVG_GOALS * AWAY_FACTOR
          * ext["attack_strength"] * dom["defense_strength"])
    return lam, mu


# ── Lectures de la loi jointe ────────────────────────────────────────────────

def issues_1x2(matrix) -> dict[str, float]:
    home = sum(p for x, row in enumerate(matrix) for y, p in enumerate(row) if x > y)
    nul = sum(row[x] for x, row in enumerate(matrix))
    ext = sum(p for x, row in enumerate(matrix) for y, p in enumerate(row) if x < y)
    return {"home": home, "draw": nul, "away": ext}


def double_chance(matrix) -> dict[str, float]:
    p = issues_1x2(matrix)
    return {"home_or_draw": p["home"] + p["draw"],
            "home_or_away": p["home"] + p["away"],
            "draw_or_away": p["draw"] + p["away"]}


def draw_no_bet(matrix) -> dict[str, float]:
    """Conditionnelle au non-nul : la mise est rendue sur un nul, donc la
    probabilité pertinente est celle du gagnant SACHANT qu'il y en a un."""
    p = issues_1x2(matrix)
    reste = p["home"] + p["away"]
    if reste <= 0:
        return {}
    return {"home": p["home"] / reste, "away": p["away"] / reste}


def totals(matrix, ligne: float) -> dict[str, float]:
    """P(total > ligne) et son complément. La ligne vient du marché."""
    over = sum(p for x, row in enumerate(matrix)
               for y, p in enumerate(row) if x + y > ligne)
    return {"over": over, "under": 1.0 - over}


def btts(matrix) -> dict[str, float]:
    oui = sum(p for x, row in enumerate(matrix)
              for y, p in enumerate(row) if x >= 1 and y >= 1)
    return {"yes": oui, "no": 1.0 - oui}


def exact_score(matrix, *, offered: Sequence[str] | None = None,
                max_buts: int = 5) -> dict[str, float]:
    """Les scores RÉELLEMENT proposés, plus leur complément exact.

    Le support vient du MARCHÉ, jamais d'une grille supposée. Mesuré : le marché
    « Score exact » football expose 35 scores et une issue `other` — pas 36. Il
    n'offre pas `5:5`. Une grille 6×6 supposée aurait donc pricé une sélection
    inexistante ET sous-estimé `other` de P(5:5).

    « other » n'est pas un reste comptable : c'est une issue que le bookmaker
    propose, et sa probabilité est exactement ce que la loi met hors des scores
    affichés — y compris au-delà de la grille du modèle.
    """
    if offered is None:
        offered = [f"{x}:{y}" for x in range(max_buts + 1) for y in range(max_buts + 1)]
    scores: dict[str, float] = {}
    for code in offered:
        if code == "other":
            continue
        try:
            x, y = (int(v) for v in code.split(":"))
        except (ValueError, AttributeError):
            continue
        scores[code] = matrix[x][y] if x < len(matrix) and y < len(matrix[x]) else 0.0
    scores["other"] = max(0.0, 1.0 - sum(scores.values()))
    return scores


class FootballDerivedPricer:
    """Price les familles dérivables de la matrice, refuse le reste avec son motif."""

    sport = "football"
    families = FAMILLES_DERIVEES
    model_name = "football_derived"
    #: Version PROPRE : ces marchés ne sont pas le 1X2, et hériter de sa version
    #: ferait croire qu'ils héritent aussi de sa validation (§5).
    model_version = "football.derived.dixon_coles.v0"

    def __init__(self, base: OneXTwoModel | None = None):
        self._base = base or OneXTwoModel()

    def supports(self, family: MarketFamily, parameters: Mapping) -> bool:
        from ....markets.capability import (
            BET_TYPES_FOOTBALL_RENCONTRE,
            LIGNES_TOTALS_REJETEES,
        )

        if family not in self.families:
            return False
        if any(c in parameters for c in (*CLES_DE_PORTEE, *CLES_DE_SUJET)):
            return False        # période ou sujet structurés : hors domaine
        # La portée n'est pas toujours structurée : « Mi-temps - Vainqueur
        # (remboursé si match nul) » ne porte aucun paramètre. Seul le betType la
        # distingue du marché de la rencontre.
        attendu = BET_TYPES_FOOTBALL_RENCONTRE.get(family)
        if attendu is not None and parameters.get("source_family_id") != attendu:
            return False
        if family is MarketFamily.TOTALS:
            ligne = parameters.get("line")
            if not isinstance(ligne, (int, float)) or float(ligne) % 1 != 0.5:
                return False
            return float(ligne) not in LIGNES_TOTALS_REJETEES
        return True

    def price(self, *, event, family: MarketFamily, parameters: Mapping,
              context: Mapping) -> MarketPricing:
        event_id = str(getattr(event, "event_id", ""))
        features = context.get("features")
        point_in_time = context.get("point_in_time")
        refus = lambda statut, motif: abstention(  # noqa: E731
            event_id=event_id, sport=self.sport, family=family, status=statut,
            reason=motif, parameters=parameters, context={})

        if features is None or point_in_time is None:
            return refus(PricingStatus.DATA_NOT_AVAILABLE,
                         "features ou point_in_time absents du contexte")

        # Restrictions de portée/sujet : refusées AVANT tout calcul.
        restrictions = [c for c in (*CLES_DE_PORTEE, *CLES_DE_SUJET) if c in parameters]
        if restrictions:
            return refus(PricingStatus.MODEL_CONTEXT_MISMATCH,
                         f"modèle de rencontre entière — portée non couverte : {restrictions}")

        # La portée n'est PAS toujours dans les paramètres. « Mi-temps - Vainqueur
        # (remboursé si match nul) » n'en porte aucun : seule sa clé de famille
        # source la distingue du marché de la rencontre. Le contrôle porte donc
        # sur le betType, jamais sur le libellé.
        from ....markets.capability import BET_TYPES_FOOTBALL_RENCONTRE

        attendu = BET_TYPES_FOOTBALL_RENCONTRE.get(family)
        if attendu is not None and parameters.get("source_family_id") != attendu:
            return refus(
                PricingStatus.MODEL_CONTEXT_MISMATCH,
                f"betType={parameters.get('source_family_id')} : ce n'est pas le marché "
                f"de la RENCONTRE pour {family.value} (attendu {attendu}). Mi-temps, "
                "période, équipe et joueur portent la même forme canonique et ne se "
                "distinguent que là — jamais par le libellé")

        if family is MarketFamily.TOTALS:
            from ....markets.capability import LIGNES_TOTALS_REJETEES

            ligne = parameters.get("line")
            if not isinstance(ligne, (int, float)):
                return refus(PricingStatus.UNSUPPORTED, "ligne absente ou non numérique")
            if float(ligne) % 1 != 0.5:
                return refus(
                    PricingStatus.RULE_NOT_DEMONSTRATED,
                    f"ligne entière ({ligne}) : le règlement d'un total exactement égal "
                    "à la ligne (remboursement ? perte ?) n'est pas démontré par la source")
            if float(ligne) in LIGNES_TOTALS_REJETEES:
                return refus(
                    PricingStatus.VALIDATION_REJECTED,
                    f"ligne {ligne} rejetée par la validation walk-forward : le modèle "
                    "ne bat pas la fréquence historique (must_beat_baselines FAIL). "
                    "Une probabilité qui n'apporte rien ne doit pas ressortir comme un edge")

        try:
            matrix = self._base.distribution(event, features, point_in_time)
        except Exception as exc:   # noqa: BLE001 — l'abstention porte la cause
            return refus(PricingStatus.DATA_NOT_AVAILABLE,
                         f"{type(exc).__name__}: {exc}")

        lam, mu = intensites(features, event)
        hors = masse_hors_grille(lam, mu)
        if hors > MASSE_HORS_GRILLE_MAX:
            return refus(
                PricingStatus.DATA_NOT_AVAILABLE,
                f"masse hors grille {hors:.3e} > {MASSE_HORS_GRILLE_MAX:.0e} "
                f"(λ={lam:.2f}, μ={mu:.2f}) : la troncature renormalisée ne "
                "représente plus la loi")

        if family is MarketFamily.MATCH_WINNER:
            probabilites = issues_1x2(matrix)
        elif family is MarketFamily.TOTALS:
            probabilites = totals(matrix, float(parameters["line"]))
        elif family is MarketFamily.DOUBLE_CHANCE:
            probabilites = double_chance(matrix)
        elif family is MarketFamily.DRAW_NO_BET:
            probabilites = draw_no_bet(matrix)
        else:
            proposees = tuple(context.get("offered_selections") or ())
            if not proposees:
                return refus(PricingStatus.DATA_NOT_AVAILABLE,
                             "support du marché inconnu : les sélections réellement "
                             "proposées doivent venir du marché, jamais d'une grille supposée")
            probabilites = exact_score(matrix, offered=proposees)
            if "other" not in proposees:
                # Sans issue « other », le support proposé prétend couvrir toute
                # la distribution. Redistribuer le résidu sur les seuls scores
                # affichés est précisément la renormalisation trompeuse à éviter.
                residu = probabilites.pop("other")
                if residu > MASSE_HORS_GRILLE_MAX:
                    return refus(
                        PricingStatus.DATA_NOT_AVAILABLE,
                        f"aucune issue « other » et {residu:.4f} de masse hors du support "
                        f"proposé ({len(proposees)} scores) : la renormaliser sur les "
                        "scores affichés fabriquerait des probabilités trop hautes")

        readiness = self._base.assess_data_readiness(event, features)
        return MarketPricing(
            event_id=event_id, sport=self.sport, family=family,
            parameters=dict(parameters), context={},
            status=PricingStatus.PRICED,
            selections=tuple(
                PricedSelection(
                    selection=nom, model_probability=p, fair_probability=p,
                    probability_low=_borne_basse(family, parameters, p),
                    settlement_shares=_parts_de_reglement(family, nom, matrix))
                for nom, p in probabilites.items()),
            model_name=self.model_name, model_version=self.model_version,
            maturity=_maturite(), calibration_status=readiness.value,
            data_quality=self._base._data_quality(event, features),
            freshness=None,                      # NON MESURÉE — jamais 0
            point_in_time=point_in_time,
            probability_origin=f"dixon_coles:score_matrix:{event_id}",
            abstention_reasons=(f"masse hors grille mesurée : {hors:.3e}",))


def _borne_basse(family: MarketFamily, parameters: Mapping, probabilite: float):
    """La borne d'incertitude de CETTE capacité — jamais celle d'une autre.

    Une borne de `TOTALS 1.5` servie à un `TOTALS 4.5` serait mesurée sur un
    autre marché : les deux n'ont ni la même fréquence de base, ni la même
    calibration. La table est donc cherchée sous l'identité de la capacité qui
    traiterait ce marché précis, ligne comprise.

    `None` veut dire NON ESTIMÉE, et surtout pas `fair_probability` : rendre le
    point comme borne prudente est le faux substitut que tout ce mécanisme
    existe pour supprimer.
    """
    from ....markets.capability import identite_capacite
    from ....uncertainty import bins_for_capability

    version = identite_capacite(family, parameters)
    if version is None:
        return None
    tables = bins_for_capability(version)
    return tables.borne_basse(probabilite) if tables is not None else None


def _parts_de_reglement(family: MarketFamily, selection: str, matrix) -> tuple:
    """La partition des règlements de CE pari — vide si WIN/LOSS suffit.

    Un « remboursé si match nul » n'est pas un pari binaire : le nul rend la
    mise. Sa probabilité affichée, elle, est conditionnelle au non-nul — c'est
    ainsi que le marché se cote. Les deux vues sont justes et servent à des
    choses différentes : la conditionnelle se compare à la cote dévigorisée,
    la partition inconditionnelle calcule l'espérance par unité MISÉE.

    Les confondre surestime l'EV d'un facteur 1/(1−P(nul)) — assez pour faire
    passer le seuil de décision à un pari qui ne l'atteint pas.
    """
    if family is not MarketFamily.DRAW_NO_BET:
        return ()
    from ....value_engine.settlement import push_shares

    p = issues_1x2(matrix)
    gagnante = p["home"] if selection == "home" else p["away"]
    perdante = p["away"] if selection == "home" else p["home"]
    return push_shares(gagnante, p["draw"], perdante)


def _maturite() -> str:
    """Maturité du modèle DÉRIVÉ, lue au ledger sous SA propre identité.

    Un marché dérivé n'hérite pas de la validation de son parent (§5) : tant
    qu'aucun `ModelSupportDecision` ne le concerne, il reste EXPERIMENTAL.
    """
    from ....support_status import resolve_market_status
    return resolve_market_status(FootballDerivedPricer.model_name,
                                 FootballDerivedPricer.model_version).value
