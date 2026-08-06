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


def render(run: RecommendationRun) -> str:
    """Rendu complet d'un tour. Aucune sélection de pari n'apparaît hors
    `COMPLETED` : un échec s'explique, il ne se contourne pas."""
    if run.status != COMPLETED:
        return _render_echec(run)
    return _render_reponse(run)


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


def _render_reponse(run: RecommendationRun) -> str:
    response, evidence = run.response, run.evidence
    outcome = response.outcome.value

    lignes = [
        f"**{outcome}** — audit `{response.audit_id}`",
        "",
        f"Fenêtre : {run.constraints.time_window.describe()}",
        f"Sports scannés : {', '.join(evidence.sports_scanned)}",
        f"Événements : {evidence.events_scanned} scannés · "
        f"{evidence.events_in_window} dans la fenêtre · "
        f"{evidence.events_evaluated} sélections évaluées",
    ]

    if response.portfolios:
        lignes += ["", "### Recommandation"]
        for pf in response.portfolios:
            lignes += _render_portefeuille(pf, run.constraints.bankroll)
    else:
        lignes += ["", "**Aucune mise recommandée.** Aucun portefeuille n'a été produit : "
                       "rien à placer, et aucune procédure de placement à suivre."]

    if response.review_candidates:
        lignes += ["", f"### À examiner seulement ({len(response.review_candidates)})",
                   "Ces sélections ne sont **pas** recommandées : leur modèle n'est pas "
                   "encore validé pour la mise réelle. Aucune n'a de mise associée."]
        for evaluation in response.review_candidates[:10]:
            lignes.append(_render_candidat(evaluation))
        if len(response.review_candidates) > 10:
            lignes.append(f"… et {len(response.review_candidates) - 10} autre(s).")

    if response.rejection_summary:
        detail = " · ".join(f"{code} : {n}"
                            for code, n in sorted(response.rejection_summary.items()))
        lignes += ["", f"### Motifs de rejet", detail]

    if response.warnings:
        lignes += ["", "### Avertissements"] + [f"- {w}" for w in response.warnings]

    lignes += _render_promotions(run)
    return "\n".join(lignes)


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
    lignes.append("- Aucun résultat n'est garanti : ces nombres sont des espérances "
                  "de long terme, pas une prévision de ce match.")
    return lignes


def _render_candidat(evaluation: Any) -> str:
    c = evaluation.candidate
    motifs = ", ".join(evaluation.policy_reasons) or "—"
    return (f"- {participant_label(c.participant_ids)} · {c.competition_id} · "
            f"{render_kickoff(c.scheduled_at)}\n"
            f"  - {c.selection} @ {c.bookmaker_odds} ({c.bookmaker}) · "
            f"probabilité modèle {_pct(c.fair_probability)} "
            f"[{_pct(c.probability_low)} – {_pct(c.probability_high)}]\n"
            f"  - EV {_signed(c.expected_value_mean)} (borne basse "
            f"{_signed(c.expected_value_low)}) · maturité {c.model_maturity} · "
            f"statut {evaluation.status.value} · motifs : {motifs}")


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
    return [
        "",
        "### Soldes promotionnels",
        f"Déclarés : {_eur(total)} — **PROMOTION_TERMS_UNKNOWN**.",
        "Ils sont exclus de la bankroll de dimensionnement et ne font l'objet "
        "d'aucune optimisation : un freebet n'est pas du cash (mise non rendue), "
        "et ses conditions exactes ne sont pas modélisées. Il n'est jamais « sans "
        "risque » : perdre le freebet en détruit toute la valeur.",
    ]
