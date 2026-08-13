"""Rejeu chronologique point-in-time, FAMILLE PAR FAMILLE.

Le harness 1X2 (`walk_forward.py`) reste la référence du marché principal et n'est
pas touché. Celui-ci répond à une question différente : un modèle validé sur « qui
gagne » ne dit RIEN de sa qualité sur « plus de 2,5 buts ». Les deux probabilités
sortent de la même loi jointe, mais elles sont confrontées à des événements
différents, et rien ne garantit que la calibration de l'une vaille pour l'autre.
C'est la promotion par héritage que le chantier interdit.

UNE SEULE MATRICE PAR MATCH. Toutes les familles d'un même match sont dérivées de
la même distribution, calculée une fois. Ce n'est pas une optimisation : deux
matrices, même issues du même code, autoriseraient un jour une divergence entre
le 1X2 validé et le Plus/Moins validé.

LA SÉMANTIQUE HISTORIQUE DOIT ÊTRE RECONSTRUCTIBLE, ET ELLE NE L'EST PAS TOUJOURS
DE LA MÊME FAÇON :

- `TOTALS` demi-ligne, `BTTS`, `MATCH_WINNER`, `EXACT_SCORE` : le score suffit,
  le règlement est déterministe ;
- `DRAW_NO_BET` : un nul REMBOURSE la mise. Ces matchs ne sont donc ni gagnés ni
  perdus — ils sortent de la population évaluée. Les compter en pertes mesurerait
  un marché qui n'existe pas ;
- `DOUBLE_CHANCE` : ses trois issues se CHEVAUCHENT (« 1 ou N » et « 1 ou 2 »
  partagent la victoire à domicile). Ce n'est pas un multiclasses, et l'évaluer
  comme tel donnerait un Brier qui ne veut rien dire. Chaque issue est donc
  évaluée comme un marché BINAIRE — c'est ainsi qu'elle se parie.

Aucun paramètre n'est réestimé : c'est un rejeu, pas un entraînement. Aucun
statut de modèle n'est promu ici.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from src.agents.quant.betting_engine.calibration import metrics
from src.agents.quant.betting_engine.calibration.point_in_time_gateway import PointInTimeGateway
from src.agents.quant.betting_engine.core.canonical_event import CanonicalEvent, CanonicalParticipant
from src.agents.quant.betting_engine.core.market_model import DataReadiness
from src.agents.quant.betting_engine.sports.football.feature_engineering import (
    build_event_feature_set,
)
from src.agents.quant.betting_engine.sports.football.market_models.derived import (
    MASSE_HORS_GRILLE_MAX,
    btts,
    double_chance,
    draw_no_bet,
    exact_score,
    intensites,
    issues_1x2,
    masse_hors_grille,
    totals,
)
from src.agents.quant.betting_engine.sports.football.market_models.one_x_two import OneXTwoModel
from src.agents.quant.gateway.sports.football.canonical_facts import CanonicalMatch

#: Valeur rendue par un règlement quand le pari est ANNULÉ (mise remboursée). Le
#: match ne compte alors ni pour ni contre : il quitte la population évaluée.
VOID = "__VOID__"


@dataclass(frozen=True)
class MarketTarget:
    """Une cible d'évaluation : comment la pricer, et comment la régler.

    `probabilities` lit la matrice ; `settle` lit le score réel. Les deux sont
    fournis ensemble pour qu'une famille ne puisse pas être évaluée contre le
    mauvais événement — l'erreur la plus coûteuse et la plus discrète de tout
    l'exercice.
    """

    key: str                                          # « TOTALS(line=2.5) »
    family: str
    classes: tuple[str, ...]
    probabilities: Callable[[list[list[float]]], dict[str, float]]
    settle: Callable[[CanonicalMatch], str]
    parameters: dict = field(default_factory=dict)


# ── Règlements — déterministes depuis le score ────────────────────────────────

def _issue_1x2(match: CanonicalMatch) -> str:
    if match.goals_home > match.goals_away:
        return "home"
    if match.goals_away > match.goals_home:
        return "away"
    return "draw"


def cibles_football(lignes_totals: Sequence[float]) -> tuple[MarketTarget, ...]:
    """Les familles football dérivables, avec leur règlement historique.

    Les lignes de `TOTALS` sont celles RÉELLEMENT observées au catalogue et dont
    le règlement est démontré (demi-lignes) : on ne valide pas une ligne que le
    bookmaker ne propose pas, et on ne devine pas celle qu'il propose sans en
    connaître la règle.
    """
    cibles: list[MarketTarget] = [
        MarketTarget(
            key="MATCH_WINNER", family="MATCH_WINNER",
            classes=("home", "draw", "away"),
            probabilities=issues_1x2, settle=_issue_1x2),
        MarketTarget(
            key="BTTS", family="BTTS", classes=("yes", "no"),
            probabilities=btts,
            settle=lambda m: "yes" if (m.goals_home >= 1 and m.goals_away >= 1) else "no"),
        MarketTarget(
            key="EXACT_SCORE", family="EXACT_SCORE",
            classes=tuple([f"{x}:{y}" for x in range(6) for y in range(6)] + ["other"]),
            probabilities=lambda mat: exact_score(mat, max_buts=5),
            settle=lambda m: (f"{m.goals_home}:{m.goals_away}"
                              if m.goals_home <= 5 and m.goals_away <= 5 else "other")),
    ]

    for ligne in lignes_totals:
        cibles.append(MarketTarget(
            key=f"TOTALS(line={ligne})", family="TOTALS", classes=("over", "under"),
            parameters={"line": ligne},
            probabilities=lambda mat, l=ligne: totals(mat, l),
            settle=lambda m, l=ligne: "over" if (m.goals_home + m.goals_away) > l else "under"))

    # Double chance : trois marchés BINAIRES, parce que ses issues se chevauchent.
    unions = {"home_or_draw": ("home", "draw"),
              "home_or_away": ("home", "away"),
              "draw_or_away": ("draw", "away")}
    for nom, issues in unions.items():
        cibles.append(MarketTarget(
            key=f"DOUBLE_CHANCE({nom})", family="DOUBLE_CHANCE", classes=("yes", "no"),
            parameters={"selection": nom},
            probabilities=lambda mat, n=nom: {"yes": double_chance(mat)[n],
                                              "no": 1.0 - double_chance(mat)[n]},
            settle=lambda m, i=issues: "yes" if _issue_1x2(m) in i else "no"))

    # Remboursé si nul : le nul ANNULE le pari, il ne le perd pas.
    for role in ("home", "away"):
        cibles.append(MarketTarget(
            key=f"DRAW_NO_BET({role})", family="DRAW_NO_BET", classes=("yes", "no"),
            parameters={"selection": role},
            probabilities=lambda mat, r=role: {"yes": draw_no_bet(mat)[r],
                                               "no": 1.0 - draw_no_bet(mat)[r]},
            settle=lambda m, r=role: (VOID if _issue_1x2(m) == "draw"
                                      else ("yes" if _issue_1x2(m) == r else "no"))))
    return tuple(cibles)


# ── Rejeu ────────────────────────────────────────────────────────────────────

@dataclass
class TargetRun:
    target: MarketTarget
    predictions: list[tuple[dict, str]] = field(default_factory=list)
    baseline: list[tuple[dict, str]] = field(default_factory=list)
    kickoffs: list[str] = field(default_factory=list)
    competitions: list[str] = field(default_factory=list)
    n_void: int = 0


@dataclass(frozen=True)
class MarketWalkForwardRun:
    runs: dict[str, TargetRun]
    n_matches: int
    n_predicted: int
    exclusions: dict
    evaluation_start: str
    evaluation_end: str
    #: `data_quality` du modèle par match prédit. Mesurable, donc mesurée : la
    #: passer à `None` ferait sortir `min_data_quality` en NOT_MEASURABLE, ce qui
    #: se lit « on ne peut pas savoir » alors que la valeur est là.
    data_qualities: tuple[float, ...] = ()


def run_market_walk_forward(
    matches: Sequence[CanonicalMatch],
    *,
    league_id: str,
    season: str,
    targets: Sequence[MarketTarget],
    model: OneXTwoModel | None = None,
) -> MarketWalkForwardRun:
    """Un passage chronologique, toutes familles évaluées sur la MÊME matrice."""
    modele = model or OneXTwoModel()
    ordonnes = sorted(matches, key=lambda m: m.kickoff)
    runs = {c.key: TargetRun(c) for c in targets}
    exclusions: Counter = Counter()
    qualites: list[float] = []
    n_predit = 0

    # Historique des issues, pour les baselines POINT-IN-TIME : à T, seules les
    # rencontres strictement antérieures comptent — même gate que les features.
    historique: list[tuple[object, CanonicalMatch]] = []

    for match in ordonnes:
        cutoff = match.kickoff
        pit = PointInTimeGateway(matches, cutoff=cutoff, league_id=league_id, season=season)
        event = CanonicalEvent(
            event_id=match.canonical_match_id, sport="football", competition_id=league_id,
            participants=(CanonicalParticipant(match.home_team_id, "home"),
                          CanonicalParticipant(match.away_team_id, "away")),
            scheduled_at=cutoff)
        features = build_event_feature_set(event, gateway=pit, as_of=cutoff)

        if modele.assess_data_readiness(event, features) == DataReadiness.INSUFFICIENT_DATA:
            exclusions["INSUFFICIENT_DATA_no_prior_form"] += 1
            historique.append((cutoff, match))
            continue

        lam, mu = intensites(features, event)
        hors = masse_hors_grille(lam, mu)
        if hors > MASSE_HORS_GRILLE_MAX:
            # Le même refus qu'en production : une distribution renormalisée hors
            # de son domaine ne doit pas non plus entrer dans une validation.
            exclusions["OUT_OF_DOMAIN_truncation_mass"] += 1
            historique.append((cutoff, match))
            continue

        matrix = modele.distribution(event, features, cutoff)
        n_predit += 1
        qualites.append(modele._data_quality(event, features))
        anterieurs = [m for (k, m) in historique if k < cutoff]

        for cible in targets:
            reel = cible.settle(match)
            run = runs[cible.key]
            if reel == VOID:
                run.n_void += 1
                continue
            probs = cible.probabilities(matrix)
            run.predictions.append(({c: probs[c] for c in cible.classes}, reel))
            run.kickoffs.append(cutoff.isoformat())
            run.competitions.append(league_id)

            # Baseline : la FRÉQUENCE observée avant T, pour CETTE cible. Battre
            # une uniforme ne prouve rien sur un marché déséquilibré ; battre la
            # fréquence historique, si.
            regles = [cible.settle(m) for m in anterieurs]
            regles = [r for r in regles if r != VOID]
            if regles:
                compte = Counter(regles)
                freq = {c: compte.get(c, 0) / len(regles) for c in cible.classes}
                run.baseline.append((freq, reel))

        historique.append((cutoff, match))

    return MarketWalkForwardRun(
        runs=runs, n_matches=len(ordonnes), n_predicted=n_predit,
        data_qualities=tuple(qualites), exclusions=dict(exclusions),
        evaluation_start=ordonnes[0].kickoff.isoformat() if ordonnes else "",
        evaluation_end=ordonnes[-1].kickoff.isoformat() if ordonnes else "")


def paires_de_calibration(run: TargetRun) -> list[tuple[float, float]]:
    """Couples (probabilité annoncée, issue 0/1) — la matière d'une borne basse.

    Toutes les issues du marché entrent, pas seulement la « gagnante » : une
    borne sert aussi bien à `under` qu'à `over`, et les tranches se peuplent
    d'autant mieux. C'est la même convention que l'ECE mutualisée.
    """
    return [(probs[classe], 1.0 if classe == reel else 0.0)
            for probs, reel in run.predictions for classe in run.target.classes]


def build_target_metrics(run: TargetRun, *, n_folds: int = 4) -> dict:
    """Métriques d'UNE cible : qualité, calibration, baseline, stabilité.

    `probability_low_coverage` est rendu `NOT_MEASURED` et non 0 : le modèle
    déclare `uncertainty_status=NOT_ESTIMATED`, donc il n'existe aucun intervalle
    dont on pourrait mesurer la couverture. Écrire 0 % en ferait une mesure — et
    une mesure fausse.
    """
    classes = run.target.classes
    if not run.predictions:
        return {"key": run.target.key, "family": run.target.family,
                "n_eval": 0, "status": "NOT_EVALUATED",
                "reason": "aucune prédiction — population vide après exclusions",
                "n_void": run.n_void}

    # Règlements OBSERVÉS, comptés séparément. Un PUSH est un règlement connu :
    # le match a eu lieu, ses features étaient là, la règle du marché a rendu la
    # mise. Le ranger avec « données manquantes » confondrait une propriété du
    # MARCHÉ avec une lacune de DONNÉES — et ferait échouer un marché sain sur un
    # critère de couverture qui ne le concerne pas.
    n_avec_features = len(run.predictions) + run.n_void
    binaire = tuple(classes) == ("yes", "no")
    distribution = metrics.evaluate(run.predictions, classes=classes)["outcome_distribution"]
    settlement = {
        "events_with_usable_features": n_avec_features,
        "win": distribution.get("yes") if binaire else None,
        "loss": distribution.get("no") if binaire else None,
        "push": run.n_void,
        "non_push_evaluated": len(run.predictions),
        "push_rate": round(run.n_void / n_avec_features, 4) if n_avec_features else None,
        "note": ("WIN/LOSS mesurés sur la population NON-PUSH ; un PUSH n'est "
                 "jamais converti en LOSS. La probabilité évaluée est celle du "
                 "marché tel qu'il se règle : conditionnelle au non-remboursement."
                 if binaire else "famille multiclasses — WIN/LOSS sans objet"),
    }

    modele = metrics.evaluate(run.predictions, classes=classes)
    ece = metrics.expected_calibration_error(run.predictions, classes=classes)
    baseline = metrics.evaluate(run.baseline, classes=classes) if run.baseline else None
    uniforme = metrics.uniform_baseline([o for _, o in run.predictions], classes=classes)

    return {
        "key": run.target.key,
        "family": run.target.family,
        "parameters": run.target.parameters,
        "classes": list(classes),
        "n_eval": len(run.predictions),
        "n_void": run.n_void,
        "settlement": settlement,
        #: Part de la population À FEATURES qui a pu être évaluée. Vaut 1 partout
        #: sauf sur un marché à PUSH — et là c'est une propriété du marché, pas
        #: une couverture de données.
        "evaluable_rate": round(len(run.predictions) / n_avec_features, 4)
        if n_avec_features else None,
        "brier": modele["brier"]["value"],
        "log_loss": modele["log_loss"]["value"],
        "ece": ece["ece"],
        "outcome_distribution": modele["outcome_distribution"],
        "baseline_frequency_brier": baseline["brier"]["value"] if baseline else None,
        "baseline_uniform_brier": uniforme["brier"]["value"],
        "beats_frequency_baseline": (
            modele["brier"]["value"] < baseline["brier"]["value"] if baseline else None),
        "folds": _folds(run, n_folds=n_folds),
        "probability_low_coverage": "NOT_MEASURED",
    }


def verdict_de_famille(
    resultat: dict,
    *,
    model_name: str,
    model_version: str,
    n_catalogue: int,
    mean_data_quality: float | None = None,
    odds_observations: Sequence = (),
    live_freshness_status: str | None = None,
    policy=None,
):
    """Le verdict de maturité d'UNE famille — par la machinerie EXISTANTE.

    Rien n'est réécrit ici : mêmes critères, mêmes seuils, même `evaluate_maturity`
    que le 1X2. Un verdict maison, même prudent, autoriserait un jour une famille à
    passer par une porte que le marché principal n'a pas franchie.

    Ce que cette fonction fait vraiment, c'est traduire les métriques d'une cible
    en `MaturityObservations`. Deux traductions méritent d'être dites :

    - `data_coverage` mesure les rencontres dont les DONNÉES permettaient de
      pricer, rapportées au catalogue. Numérateur : les événements à features
      utilisables, PUSH COMPRIS. Un nul qui rembourse un « remboursé si match
      nul » n'est pas une donnée manquante — c'est un règlement connu, observé,
      et le marché a bel et bien été price. Compter le contraire faisait échouer
      `min_data_coverage` à 0,719 sur un marché dont les données étaient
      complètes à 97 %. Le seuil, lui, n'a pas bougé ;
    - la CLV est MESURÉE sur les observations de cotes fournies, pas déclarée.
      Sans cotes historiques de Plus/Moins — et nous n'en avons pas (§6) —
      `clv_readiness` rend NOT_YET_MEASURABLE de lui-même. La nuance compte : le
      jour où ces cotes existent, la mesure se fait sans toucher à ce code, et
      d'ici là aucune validation économique n'est réputée avoir eu lieu.
    - la fraîcheur live est DÉCLARÉE PAR L'APPELANT, jamais par cet évaluateur.
      L'écrire ici reviendrait à s'auto-délivrer le critère : le rapport
      afficherait « freshness exposée » sans que rien ne l'ait vérifié.
    """
    from ..clv import clv_readiness
    from ..maturity import (
        FRESHNESS_NOT_MEASURABLE,
        MaturityObservations,
        evaluate_maturity,
        load_maturity_policy,
    )

    politique = policy or load_maturity_policy()
    fraicheur = live_freshness_status or FRESHNESS_NOT_MEASURABLE
    clv = clv_readiness(list(odds_observations),
                        confidence=politique.criteria["clv_confidence_level"])
    folds = resultat.get("folds") or []
    briers = [f["brier"] for f in folds]
    ecart = (max(briers) - min(briers)) if len(briers) >= 2 else None
    baselines = [b for b in (resultat.get("baseline_frequency_brier"),
                             resultat.get("baseline_uniform_brier")) if b is not None]

    observations = MaturityObservations(
        n_evaluated=resultat["n_eval"],
        n_temporal_folds=len(folds),
        calibration_error=resultat.get("ece"),
        model_brier=resultat.get("brier"),
        best_baseline_brier=min(baselines) if baselines else None,
        data_coverage=round(
            resultat["settlement"]["events_with_usable_features"] / n_catalogue, 4)
        if n_catalogue else None,
        mean_data_quality=mean_data_quality,
        fold_brier_spread=round(ecart, 6) if ecart is not None else None,
        clv_status=clv.status,
        clv_mean=clv.mean_clv,
        clv_n_events=clv.n_events,
        clv_lower_bound=clv.clv_lower_bound,
        live_freshness_status=fraicheur,
    )
    return evaluate_maturity(model_name=model_name, model_version=model_version,
                             observations=observations, policy=politique)


def _folds(run: TargetRun, *, n_folds: int) -> list[dict]:
    """Découpage TEMPOREL en tranches égales — la stabilité dans le temps, pas
    une validation croisée (qui mélangerait passé et futur)."""
    n = len(run.predictions)
    if n < n_folds:
        return []
    ordre = sorted(range(n), key=lambda i: run.kickoffs[i])
    taille = n // n_folds
    sorties = []
    for f in range(n_folds):
        debut = f * taille
        fin = n if f == n_folds - 1 else (f + 1) * taille
        idx = ordre[debut:fin]
        tranche = [run.predictions[i] for i in idx]
        m = metrics.evaluate(tranche, classes=run.target.classes)
        sorties.append({
            "fold": f, "n": len(tranche),
            "start": run.kickoffs[idx[0]], "end": run.kickoffs[idx[-1]],
            "brier": m["brier"]["value"],
            "ece": metrics.expected_calibration_error(
                tranche, classes=run.target.classes)["ece"]})
    return sorties
