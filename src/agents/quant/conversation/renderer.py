"""Renderer DÉTERMINISTE (§19, §23). Tout fait sportif affiché sort d'ici.

Le LLM peut commenter ce texte ; il ne peut pas en produire un équivalent. La
différence est mécanique : ici, chaque nombre provient d'un champ d'un objet du
domaine, et un champ absent devient une mention d'absence — jamais une valeur
plausible.

Aucun recalcul. En particulier : **l'EV n'est jamais recalculée**. Elle est lue
sur la ligne du portefeuille ou sur le candidat. Recalculer ouvrirait la porte à
la formule interdite `p = 1/cote` puis `EV = p × cote − 1`, qui rend
mécaniquement zéro avant marge et négatif après — donc jamais une « EV positive »
(§7).
"""

from __future__ import annotations

from decimal import Decimal
from functools import lru_cache
from typing import Any, Sequence

from .recommend import (
    CLARIFICATION_REQUIRED,
    COMPLETED,
    DATA_UNAVAILABLE,
    EMPTY_WINDOW,
    FILTER_UNRESOLVED,
    TECHNICAL_FAILURE,
    RecommendationRun,
)
from .observability import INDISPONIBLE, NON_APPLICABLE, NON_MESURE
from .window import render_kickoff

_CENT = Decimal("0.01")


@lru_cache(maxsize=1)
def _names() -> dict[str, str]:
    """`canonical_id -> nom canonique`. Le référentiel d'identités est la seule
    source de noms : dériver un nom d'un identifiant produirait « Psg »."""
    from ..betting_engine.sports.registry import all_known_entities
    return {e.canonical_id: e.canonical_name for e in all_known_entities()}


def participant_label(participant_ids: Sequence[str]) -> str:
    noms = [_names().get(pid, pid) for pid in participant_ids]
    return " – ".join(noms) if noms else "participants non identifiés"


def _eur(amount: Decimal | None) -> str:
    return "n/d" if amount is None else f"{amount.quantize(_CENT)} €"


def _pct(value: Decimal | None) -> str:
    return "n/d" if value is None else f"{(value * 100).quantize(_CENT)} %"


def _signed(value: Decimal | None) -> str:
    """L'EV est un nombre signé : la masquer derrière une valeur absolue
    transformerait une perte attendue en gain apparent."""
    if value is None:
        return "n/d"
    return f"{'+' if value >= 0 else ''}{value.quantize(Decimal('0.0001'))}"


# ── Sorties non actionnables ──────────────────────────────────────────────────
_ECHECS = {
    CLARIFICATION_REQUIRED: "CLARIFICATION_REQUIRED",
    FILTER_UNRESOLVED: "FILTER_UNRESOLVED",
    EMPTY_WINDOW: "EMPTY_WINDOW",
    DATA_UNAVAILABLE: "DATA_UNAVAILABLE",
    TECHNICAL_FAILURE: "TECHNICAL_FAILURE",
}


def render(run: RecommendationRun, *, debug: bool = False) -> str:
    """Rendu complet d'un tour. Aucune sélection de pari n'apparaît hors
    `COMPLETED` : un échec s'explique, il ne se contourne pas.

    `debug` n'ouvre aucune information nouvelle sur la décision — il lève
    seulement la troncature. Déverser 700 événements dans la réponse normale
    rendrait illisible ce qu'on cherche justement à rendre lisible.
    """
    if run.status != COMPLETED:
        return _render_echec(run)
    return _render_reponse(run, debug=debug)


def _render_echec(run: RecommendationRun) -> str:
    code = _ECHECS.get(run.status, TECHNICAL_FAILURE)
    lignes = [f"**{code}** — aucune recommandation possible.", "", run.detail]
    if run.available:
        apercu = ", ".join(run.available[:20])
        suite = f" (+{len(run.available) - 20} autres)" if len(run.available) > 20 else ""
        lignes += ["", f"Disponible dans ce scan : {apercu}{suite}"]
    if code == "CLARIFICATION_REQUIRED":
        lignes += ["", "Aucune cote, aucune probabilité et aucune sélection ne peuvent être "
                       "affichées tant que la chaîne structurée n'a pas tourné."]
    return "\n".join(lignes)


#: Nombre de candidats de revue affichés hors mode debug.
_TOP_REVIEW = 5


def _render_reponse(run: RecommendationRun, *, debug: bool = False) -> str:
    response, evidence, obs = run.response, run.evidence, run.observability
    fenetre = run.constraints.time_window

    lignes = [
        f"**{response.outcome.value}** — audit `{response.audit_id}`",
        "",
        f"Fenêtre : {fenetre.describe()}",
    ]
    lignes += _render_couverture(obs, evidence)
    lignes += _render_compteurs(obs, evidence)

    # Deux niveaux STRICTEMENT séparés. Le produit répondait « Aucune mise
    # recommandée » puis énumérait trente candidats : la phrase de tête niait ce
    # que la suite montrait, et l'utilisateur lisait un refus là où il y avait un
    # résultat.
    lignes += ["", "## 1 · Recommandations actionnables"]
    if response.portfolios:
        for pf in response.portfolios:
            lignes += _render_portefeuille(pf, run.constraints.bankroll)
    else:
        lignes += [
            "Aucune. Aucun modèle n'est encore validé pour la mise réelle, donc "
            "aucun portefeuille n'a pu être produit — rien à placer, aucune "
            "procédure de placement à suivre.",
        ]

    lignes += _render_revue(run, debug=debug)
    lignes += _render_bloqueurs(obs, response)
    lignes += _render_readiness(obs)

    if response.warnings:
        lignes += ["", "### Avertissements"] + [f"- {w}" for w in response.warnings]

    lignes += _render_promotions(run)

    if debug:
        lignes += _render_catalogue(obs)
        lignes += _render_chemins(obs)
        lignes += _render_provenance(run)
    return "\n".join(lignes)


# ── Couverture : quatre niveaux, quatre nombres ───────────────────────────────
def _render_couverture(obs: Any, evidence: Any) -> list[str]:
    """« 7 sports scannés » était vrai et trompeur : Winamax en expose 29. Le
    même nombre décrivait « ce que le bookmaker propose » et « ce que nous savons
    modéliser » — deux situations qui se réparent différemment."""
    if obs is None:
        return [f"Sports scannés : {', '.join(evidence.sports_scanned)}"]

    catalogue = len(obs.telemetry.catalog_sports)
    lignes = [
        "",
        "### Couverture",
        f"- Sports exposés par Winamax : **{catalogue if catalogue else INDISPONIBLE}**",
        f"- Sports disposant d'un modèle : **{len(obs.model_capable_sports)}** "
        f"({', '.join(obs.model_capable_sports)})",
        f"- Sports scannés dans ce run : **{len(obs.telemetry.scanned_sports)}**",
        f"- Sports ayant des événements dans la fenêtre : **{len(obs.sports_in_window)}**"
        + (f" ({', '.join(obs.sports_in_window)})" if obs.sports_in_window else ""),
        f"- Sports ayant atteint l'évaluation : **{len(obs.sports_evaluated)}**"
        + (f" ({', '.join(obs.sports_evaluated)})" if obs.sports_evaluated else ""),
    ]
    competitions = obs.competitions_in_window
    lignes += [
        f"- Compétitions rencontrées dans la fenêtre : "
        f"**{sum(len(c) for c in competitions.values())}**",
        f"- Compétitions résolues canoniquement : **{len(obs.competitions_resolved)}**",
        f"- Compétitions ayant atteint l'évaluation : **{len(obs.competitions_evaluated)}**",
    ]
    return lignes


def _render_compteurs(obs: Any, evidence: Any) -> list[str]:
    if obs is None:
        return []
    coherent, detail = obs.counters_balance()
    lignes = ["", "### Volumes", "```"]
    for nom, valeur in obs.counters.items():
        lignes.append(f"{nom:34} {valeur:>6}")
    lignes += ["```",
               f"Contrôle : {detail}" if coherent
               else f"⚠ {detail}"]
    return lignes


# ── Candidats de revue — NON MISABLES ─────────────────────────────────────────
def _render_revue(run: RecommendationRun, *, debug: bool) -> list[str]:
    response, obs = run.response, run.observability
    candidats = list(response.review_candidates)
    if not candidats:
        return []

    from .review_ranking import rank_review

    fenetre = run.constraints.time_window
    classees = rank_review(candidats)
    lignes = [
        "",
        f"## 2 · Shortlist de revue — NON MISABLES ({len(classees)} rencontres)",
        "Ce que le modèle trouve intéressant, et qui reste bloqué. Aucune de ces "
        "lignes n'est un pari : pas de mise, pas de Kelly, aucune procédure de "
        "placement. Classement par borne basse d'edge — il ne mesure pas une "
        "distance au misable, aucun candidat ne l'étant.",
        "",
        "| # | rencontre | h. Paris | sél. | cote | implicite | modèle | borne basse | edge | EV |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    affichees = classees if debug else classees[:_TOP_REVIEW]
    for ligne in affichees:
        lignes.append(_render_ligne_revue(ligne, fenetre))
    if not debug and len(classees) > _TOP_REVIEW:
        lignes.append(f"\n… et {len(classees) - _TOP_REVIEW} autre(s) — mode debug "
                      "pour la liste complète.")

    lignes += ["", "**Détail des trois premiers**"]
    for ligne in affichees[:3]:
        lignes += _render_candidat(ligne.evaluation, obs, fenetre)
    return lignes


def _render_ligne_revue(ligne: Any, fenetre: Any) -> str:
    """Une ligne de tableau. Tous les nombres viennent du candidat structuré."""
    c = ligne.candidate
    if fenetre is not None and not fenetre.contains(c.scheduled_at):
        return f"| {ligne.rang} | ⚠ hors fenêtre — écarté du rendu | | | | | | | | |"
    from .window import to_paris

    return (f"| {ligne.rang} | {participant_label(c.participant_ids)} "
            f"| {to_paris(c.scheduled_at):%d/%m %H:%M} | {c.selection} "
            f"| {c.bookmaker_odds} | {_pct(c.implied_probability)} "
            f"| {_pct(c.fair_probability)} | {_pct(c.probability_low)} "
            f"| {_signed(c.edge_low)} | {_signed(c.expected_value_low)} |")


def _valeur(value: Any, rendu=lambda v: str(v)) -> str:
    """Une absence n'est pas un zéro. `freshness_score=None` veut dire non
    mesurée ; l'écrire `0` en ferait une mesure, et la pire possible."""
    return NON_MESURE if value is None else rendu(value)


def _render_candidat(evaluation: Any, obs: Any = None, fenetre: Any = None) -> list[str]:
    from .observability import primary_blocker

    c = evaluation.candidate
    adapte = obs.adapted_for(c) if obs is not None else None

    # §13 : un candidat hors fenêtre ne peut pas être rendu. Le vérifier ici, et
    # pas seulement au scan, ferme le cas où un candidat proviendrait d'ailleurs.
    if fenetre is not None and not fenetre.contains(c.scheduled_at):
        return [f"- ⚠ candidat écarté du rendu : coup d'envoi hors fenêtre "
                f"({render_kickoff(c.scheduled_at)})"]

    no_vig = getattr(adapte, "no_vig_probability", None)
    observed_at = getattr(adapte, "observed_at", None)

    return [
        "",
        f"**{participant_label(c.participant_ids)}**",
        "> Cette sélection n'est pas une recommandation de pari.",
        f"- Sport / compétition : {c.sport} · `{c.competition_id}`",
        f"- Coup d'envoi : {render_kickoff(c.scheduled_at)}",
        f"- Marché / sélection : {c.market_type} · **{c.selection}**",
        f"- Cote bookmaker : {c.bookmaker_odds} ({c.bookmaker})",
        f"- Probabilité implicite (1/cote, marge incluse) : {_pct(c.implied_probability)}",
        f"- Probabilité modèle : {_pct(c.fair_probability)} "
        f"(borne basse {_pct(c.probability_low)})",
        f"- Probabilité sans marge : {_valeur(no_vig, _pct)}",
        f"- Edge : {_signed(c.edge_mean)} (borne basse {_signed(c.edge_low)})",
        f"- EV moyenne : {_signed(c.expected_value_mean)} · "
        f"EV pire cas : {_signed(c.expected_value_low)}",
        f"- Modèle : `{c.model_version}` · maturité **{c.model_maturity}**",
        f"- Qualité des données : {_valeur(c.data_quality, _pct)} · "
        f"fraîcheur : {_valeur(c.freshness_score, _pct)} · "
        f"fiabilité modèle : {_valeur(c.calibration_score, _pct)}",
        f"- Statut Advisor : **{evaluation.status.value}** · "
        f"premier bloqueur : **{primary_blocker(evaluation)}**",
        f"- Raisons complètes : {', '.join(evaluation.policy_reasons) or NON_APPLICABLE}",
        f"- Provenance : `{c.event_id}` · `{c.market_id}` · "
        f"observé {_valeur(observed_at, lambda v: render_kickoff(v))}",
    ] + _render_internet(obs, c)


def _render_internet(obs: Any, candidate: Any) -> list[str]:
    """Faits externes — clairement séparés des chiffres.

    Ils sont présentés APRÈS les probabilités et sous un intitulé distinct :
    accolés aux nombres, ils se liraient comme une justification de la mesure,
    alors qu'ils n'y participent en rien.
    """
    features = obs.features_for(candidate) if obs is not None else ()
    if not features:
        return []

    lignes = ["- **Contexte externe** — informatif, n'entre dans aucun calcul :"]
    for f in features:
        marque = {"OFFICIAL": "✓", "REPUTABLE": "·"}.get(f.confidence, "⚠")
        lignes.append(f"  - {marque} {f.value[:160]} — [{f.source[:40]}]({f.url})")
    return lignes


#: Refus MOTEUR signifiant « aucun provider vérifié ne couvre cette compétition ».
#: C'est le seul blocage qu'un abonnement puisse lever, et il se produit AVANT
#: le modèle — donc jamais sur un candidat, toujours sur un événement écarté.
_REFUS_SANS_PROVIDER = "COMPETITION_NOT_COVERED"


def _render_providers(obs: Any) -> list[str]:
    """Pistes d'abonnement, pour les sports réellement bloqués faute de provider.

    Cette section a d'abord été écrite sur la ligne d'un candidat, en lisant
    `evaluation.policy_reasons`. Elle ne pouvait pas s'afficher : `COMPETITION_NOT_COVERED`
    est un refus du Betting Engine, appliqué AVANT le modèle. Un événement qui le
    subit ne devient jamais un candidat, donc la raison recherchée ne pouvait pas
    se trouver là où on la cherchait. La leçon est de lire le blocage dans la
    couche qui l'a produit — ici les traces du scan, qui portent le sport.
    """
    if obs is None:
        return []

    from ..enrichment.providers import providers_for

    sports = sorted({t.sport for t in obs.traces if t.status == _REFUS_SANS_PROVIDER})
    lignes: list[str] = []
    for sport in sports:
        options = providers_for(sport)
        if not options:
            continue
        lignes += ["", f"*{sport} — aucun provider vérifié ne couvre ces compétitions.*",
                   "Options sondées (aucune intégration automatique : un provider "
                   "payant engage de l'argent, un gratuit engage une licence) :"]
        for o in options[:5]:
            lignes.append(f"- {o.name} — **{o.access}**"
                          + (f" · {o.price_hint}" if o.price_hint else "")
                          + f" · {', '.join(o.covers[:4])}")
    return lignes


# ── Matrice des bloqueurs, couche par couche ──────────────────────────────────
def _render_bloqueurs(obs: Any, response: Any) -> list[str]:
    if obs is None:
        if not response.rejection_summary:
            return []
        detail = " · ".join(f"{code} : {n}"
                            for code, n in sorted(response.rejection_summary.items()))
        return ["", "### Motifs de rejet", detail]

    lignes = ["", "### Bloqueurs"]
    for couche, compte in obs.blocker_matrix().items():
        if not compte:
            continue
        lignes += ["", f"*{couche}*", "```"]
        for code, n in sorted(compte.items(), key=lambda kv: (-kv[1], kv[0])):
            lignes.append(f"{code:44} {n:>5}")
        lignes.append("```")
    return lignes + _render_providers(obs)


# ── Readiness des modèles présents ────────────────────────────────────────────
def _render_readiness(obs: Any) -> list[str]:
    if obs is None or not obs.readiness:
        return []
    # La formulation évite le vocabulaire qu'elle interdit, y compris nié : le
    # LLM restitue ce texte et le garde relit sa restitution.
    lignes = ["", "### Readiness des modèles présents dans le run",
              "La proximité mesurée est celle de la MATURITÉ D'UN MODÈLE, jamais "
              "celle d'une sélection. Un modèle à 6 critères requis sur 8 reste "
              "EXPERIMENTAL, et aucune de ses sélections n'est misable."]
    for r in obs.readiness:
        lignes += [
            "",
            f"**`{r.model_version}`** — {r.sport} · statut **{r.status}**",
            f"- Critères requis satisfaits : {len(r.passed)}/{r.required_total}",
            f"- En échec : {', '.join(r.failed) or 'aucun'}",
            f"- Non mesurables : {', '.join(r.not_measurable) or 'aucun'}",
            f"- Bloqueurs vers SUPPORTED : {', '.join(r.blockers) or 'aucun'}",
        ]
        if r.monitoring:
            suivi = ", ".join(f"{nom}={verdict}" for nom, verdict in r.monitoring)
            lignes.append(f"- Suivi (non requis) : {suivi}")
    return lignes


# ── Sections debug ────────────────────────────────────────────────────────────
def _render_catalogue(obs: Any) -> list[str]:
    if obs is None:
        return []
    lignes = ["", "### Catalogue découvert dans ce run"]
    sports = obs.telemetry.catalog_sports
    if sports:
        lignes.append(f"Sports exposés par Winamax ({len(sports)}) : "
                      + ", ".join(str(n) for _, n in sorted(sports.items())))
    for sport, competitions in obs.telemetry.catalog_competitions.items():
        lignes += ["", f"**{sport}** ({len(competitions)})"]
        lignes += [f"  - {c}" for c in competitions]
    return lignes


#: Ordre des portes, DÉCLARÉ ici et vérifié contre le code du domaine par
#: `tests/test_observability.py` : un ordre recopié à la main diverge, un ordre
#: recopié et testé ne le peut pas.
GATE_SEQUENCE = (
    "catalog discovery", "time-window filter", "sport dispatch",
    "participant identity", "competition identity", "market canonicalization",
    "provider coverage", "feature readiness", "freshness", "model evaluation",
    "maturity gate", "value gate", "adapter", "Advisor policy", "ranking/review",
)


def _render_chemins(obs: Any) -> list[str]:
    """Chemin de décision par événement — lu sur la trace, jamais reconstruit.

    Chaque ligne porte le statut TYPÉ rendu par le domaine et sa raison, pas une
    déduction faite depuis ce qui manque en sortie.
    """
    if obs is None or not obs.traces:
        return []
    lignes = ["", "### Chemin de décision par événement",
              "Portes appliquées, dans l'ordre : " + " → ".join(GATE_SEQUENCE),
              "", "```"]
    for trace in obs.traces:
        horaire = render_kickoff(trace.kickoff) if trace.kickoff else NON_MESURE
        lignes.append(
            f"[{trace.status:26}] {trace.sport:18} {trace.competition_label[:28]:30} "
            f"{horaire}")
        lignes.append(f"{'':30}{trace.reason[:110]}")
    lignes.append("```")
    return lignes


def _render_provenance(run: RecommendationRun) -> list[str]:
    evidence = run.evidence
    if evidence is None:
        return []
    return [
        "", "### Provenance",
        "```",
        f"request_id                 {evidence.request_id}",
        f"run_id                     {evidence.run_id}",
        f"audit_id                   {evidence.audit_id}",
        f"scan_started_at            {evidence.scan_started_at.isoformat()}",
        f"scan_completed_at          {evidence.scan_completed_at.isoformat()}",
        f"window_start               {evidence.window_start.isoformat()}",
        f"window_end                 {evidence.window_end.isoformat()}",
        # §19 : la portée du state est une information d'exploitation, pas une
        # promesse de persistance. Un redémarrage repart d'un state vide.
        "constraints_state_scope    process/thread",
        "```",
    ]


def _render_portefeuille(pf: Any, bankroll: Decimal | None) -> list[str]:
    from ..advisor.domain.enums import LineType

    lignes: list[str] = []
    for line in pf.lines:
        genre = "COMBINÉ" if line.line_type is LineType.COMBO else "SIMPLE"
        legs = " + ".join(
            f"{leg.selection} @ {leg.odds} ({leg.bookmaker})" for leg in line.legs)
        # Retour BRUT et profit NET sont deux nombres distincts : les confondre
        # présente une mise de 10 € à cote 1,5 comme un gain de 15 €.
        retour_brut = (line.stake * line.total_odds).quantize(_CENT)
        profit_net = (retour_brut - line.stake).quantize(_CENT)
        lignes += [
            f"- **{genre}** — {legs}",
            f"  - cote totale {line.total_odds} · probabilité estimée "
            f"{_pct(line.estimated_probability)}",
            f"  - EV {_signed(line.expected_value)} (borne basse "
            f"{_signed(line.worst_case_ev)})",
            f"  - mise **{_eur(line.stake)}** · retour brut si gain {_eur(retour_brut)} "
            f"· profit net si gain {_eur(profit_net)}",
        ]
        if line.correlation_warning:
            lignes.append(f"  - corrélation : {line.correlation_warning}")
    lignes.append(
        f"- Total misé {_eur(pf.total_stake)} · bankroll non allouée "
        f"{_eur(pf.unallocated_bankroll)}")
    if pf.explanation and pf.explanation.major_risks:
        lignes += [f"- Risque : {r}" for r in pf.explanation.major_risks]
    # Le vocabulaire de certitude est banni ICI AUSSI, y compris sous forme niée.
    # Le LLM restitue ce texte, le garde relit sa restitution : une phrase comme
    # « aucun résultat n'est garanti » contient le mot interdit, et ferait
    # bloquer la réponse valide qu'elle accompagne.
    lignes.append("- Ces nombres sont des espérances de long terme, pas une "
                  "prévision de ce match.")
    return lignes


def _render_promotions(run: RecommendationRun) -> list[str]:
    """Les soldes promotionnels sont RESTITUÉS, jamais optimisés.

    Un freebet dont la mise n'est pas rendue vaut `mise × (cote − 1)` en cas de
    gain, pas `mise × cote` ; et il ne vaut rien s'il perd. Tant que les
    conditions exactes (cote minimale, expiration, marchés éligibles) ne sont pas
    modélisées, les dimensionner reviendrait à inventer la règle qui décide de
    l'argent.
    """
    soldes = run.constraints.promotional_balances
    if not soldes:
        return []
    total = sum((p.amount for p in soldes), Decimal("0"))
    cash = _eur(run.constraints.bankroll) if run.constraints.bankroll else "n/d"
    return [
        "",
        "### Soldes promotionnels",
        f"La bankroll cash est prise en compte : {cash}.",
        f"Le freebet n'est pas utilisé car ses conditions promotionnelles ne sont "
        f"pas connues : {_eur(total)} déclaré(s), **PROMOTION_TERMS_UNKNOWN**.",
        "Il est exclu du dimensionnement et ne fait l'objet d'aucune optimisation. "
        "Un freebet n'est pas du cash : sa mise n'est pas rendue en cas de gain, et "
        "sa perte en détruit toute la valeur économique.",
    ]
